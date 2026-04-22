"""
Static Code Review Engine
Checks UiPath XAML workflows against 47 Workflow Analyzer rules
without any LLM — pure deterministic analysis on parsed ReviewContext.
"""

import re
from collections import Counter

from models.schemas import ReviewContext, Finding

# ── Prefix maps (shared with xaml_fixer.py) ────────────────────────
_TYPE_PREFIXES = {
    "String": "str_",
    "System.String": "str_",
    "Int32": "int_",
    "System.Int32": "int_",
    "Int64": "int_",
    "System.Int64": "int_",
    "Boolean": "bln_",
    "System.Boolean": "bln_",
    "DataTable": "dt_",
    "System.Data.DataTable": "dt_",
    "DateTime": "dtm_",
    "System.DateTime": "dtm_",
    "TimeSpan": "ts_",
    "System.TimeSpan": "ts_",
    "Double": "dbl_",
    "System.Double": "dbl_",
    "Decimal": "dec_",
    "System.Decimal": "dec_",
}

_DIRECTION_PREFIXES = {"In": "in_", "Out": "out_", "InOut": "io_"}

_SENSITIVE_PATTERNS = re.compile(
    r"(password|passwd|pwd|secret|apikey|api_key|token|credential|ssn|credit.?card)",
    re.IGNORECASE,
)

_UI_ACTIVITY_TYPES = {
    "Click", "NClick", "TypeInto", "NTypeInto", "GetText", "NGetText",
    "SetText", "NSetText", "Hover", "NHover", "Check", "NCheck",
    "SelectItem", "NSelectItem", "GetAttribute", "NGetAttribute",
    "ElementExists", "UiElementExists", "FindElement",
    "SendHotkey", "NSendHotkey", "Screenshot", "TakeScreenshot",
    "ClickImage", "FindImage", "ExtractData", "NExtractData",
}

_EXCEL_ACTIVITY_TYPES = {
    "ReadRange", "WriteRange", "ReadCell", "WriteCell",
    "ExcelReadRange", "ExcelWriteRange", "ExcelReadCell", "ExcelWriteCell",
    "Append", "ExcelAppend", "CreateTable",
}

_PERSISTENCE_TYPES = {
    "Persist", "CreateBookmark", "ResumeBookmark",
    "WaitForFormTaskAndResume", "CreateFormTask",
}

_NON_SERIALIZABLE_TYPES = {
    "Object", "System.Object", "UIElement", "UiElement",
    "Browser", "Window", "IWebDriver",
}


def _make_finding(
    ctx: ReviewContext, rule_id: str, rule_name: str, severity: str,
    category: str, description: str, recommendation: str,
    activity_path: str = "", auto_fixable: bool = False,
) -> Finding:
    return Finding(
        file_name=ctx.file_name,
        zip_entry_path=ctx.zip_entry_path,
        workflow_name=ctx.workflow_name,
        severity=severity,
        category=category,
        rule_id=rule_id,
        rule_name=rule_name,
        activity_path=activity_path,
        description=description,
        recommendation=recommendation,
        auto_fixable=auto_fixable,
    )


# ═══════════════════════════════════════════════════════════════════
# NAMING RULES
# ═══════════════════════════════════════════════════════════════════

def _check_st_nmg_001(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-001: Variables Naming Convention — check type prefixes."""
    findings = []
    for var in ctx.variables:
        expected = _TYPE_PREFIXES.get(var.type)
        if not expected:
            # Check for array/list types
            if "[]" in var.type or "List" in var.type:
                expected = "arr_"
            elif "Dictionary" in var.type:
                expected = "dic_"
            else:
                expected = "str_"  # default for unknown types
        if not var.name.startswith(expected):
            findings.append(_make_finding(
                ctx, "ST-NMG-001", "Variables Naming Convention", "MEDIUM", "Naming",
                f"Variable '{var.name}' (type: {var.type}) does not follow naming conventions. "
                f"Expected prefix '{expected}'.",
                f"Rename to '{expected}{var.name}' to follow UiPath naming standards.",
                activity_path=f"Variable: {var.name}",
                auto_fixable=True,
            ))
    return findings


def _check_st_nmg_002(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-002: Arguments Naming Convention — check direction prefixes."""
    findings = []
    for arg in ctx.arguments:
        expected = _DIRECTION_PREFIXES.get(arg.direction, "in_")
        if not arg.name.startswith(expected):
            findings.append(_make_finding(
                ctx, "ST-NMG-002", "Arguments Naming Convention", "MEDIUM", "Naming",
                f"Argument '{arg.name}' (direction: {arg.direction}) is missing the '{expected}' prefix.",
                f"Rename to '{expected}{arg.name}' to follow UiPath naming standards.",
                activity_path=f"Argument: {arg.name}",
                auto_fixable=True,
            ))
    return findings


def _check_st_nmg_004(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-004: Display Name Duplication."""
    findings = []
    # Exclude generic names that are commonly duplicated
    generic_names = {"Sequence", "Assign", "If", "Flowchart", "FlowDecision", "FlowStep"}
    names = [a.display_name for a in ctx.activities if a.display_name not in generic_names]
    counts = Counter(names)
    for name, count in counts.items():
        if count > 1:
            findings.append(_make_finding(
                ctx, "ST-NMG-004", "Display Name Duplication", "MEDIUM", "Naming",
                f"Display name '{name}' is used {count} times. Each activity should have a unique name.",
                "Assign unique, descriptive display names to each activity "
                "(auto-fix derives names from each activity's selector when available).",
                activity_path=f"DisplayName: {name}",
                auto_fixable=True,
            ))
    return findings


def _check_st_nmg_005(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-005: Variable Overrides Variable — shadowing in inner scopes."""
    findings = []
    seen: dict[str, str] = {}
    for var in ctx.variables:
        if var.name in seen and seen[var.name] != var.scope:
            findings.append(_make_finding(
                ctx, "ST-NMG-005", "Variable Overrides Variable", "MEDIUM", "Naming",
                f"Variable '{var.name}' is declared in multiple scopes: '{seen[var.name]}' and '{var.scope}'. "
                "This causes variable shadowing.",
                "Rename one of the variables to avoid confusion.",
                activity_path=f"Variable: {var.name}",
            ))
        seen.setdefault(var.name, var.scope)
    return findings


def _check_st_nmg_006(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-006: Variable Overrides Argument — name collision."""
    findings = []
    arg_names = {a.name.lower(): a.name for a in ctx.arguments}
    for var in ctx.variables:
        if var.name.lower() in arg_names:
            findings.append(_make_finding(
                ctx, "ST-NMG-006", "Variable Overrides Argument", "HIGH", "Naming",
                f"Variable '{var.name}' has the same name as argument '{arg_names[var.name.lower()]}'. "
                "This can cause unexpected behavior.",
                "Rename the variable or argument to be distinct.",
                activity_path=f"Variable: {var.name}",
            ))
    return findings


def _check_st_nmg_008(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-008: Variable Length Exceeded."""
    findings = []
    for var in ctx.variables:
        if len(var.name) > 30:
            findings.append(_make_finding(
                ctx, "ST-NMG-008", "Variable Length Exceeded", "LOW", "Naming",
                f"Variable '{var.name}' has {len(var.name)} characters, exceeding the recommended 30-character limit.",
                "Shorten the variable name while keeping it meaningful.",
                activity_path=f"Variable: {var.name}",
            ))
    return findings


def _check_st_nmg_009(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-009: DataTable Variable Prefix."""
    findings = []
    for var in ctx.variables:
        if "DataTable" in var.type and not var.name.startswith("dt_"):
            findings.append(_make_finding(
                ctx, "ST-NMG-009", "DataTable Variable Prefix", "MEDIUM", "Naming",
                f"DataTable variable '{var.name}' is missing the 'dt_' prefix.",
                f"Rename to 'dt_{var.name}'.",
                activity_path=f"Variable: {var.name}",
                auto_fixable=True,
            ))
    return findings


def _check_st_nmg_011(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-011: DataTable Argument — flag DataTable args missing direction prefix.

    Note: Per UiPath convention, arguments use ONLY direction prefixes
    (in_, out_, io_) — never datatype prefixes like dt_. This rule
    flags DataTable arguments that don't follow direction conventions.
    """
    findings = []
    direction_prefixes = {"In": "in_", "Out": "out_", "InOut": "io_"}
    for arg in ctx.arguments:
        if "DataTable" not in arg.type:
            continue
        expected = direction_prefixes.get(arg.direction, "in_")
        if not arg.name.startswith(expected):
            findings.append(_make_finding(
                ctx, "ST-NMG-011", "DataTable Argument Naming", "MEDIUM", "Naming",
                f"DataTable argument '{arg.name}' (direction: {arg.direction}) is missing "
                f"the '{expected}' prefix. Arguments use only direction prefixes, never datatype prefixes.",
                f"Rename to '{expected}{arg.name}' to follow UiPath argument naming conventions.",
                activity_path=f"Argument: {arg.name}",
                auto_fixable=True,
            ))
    return findings


def _check_st_nmg_012(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-012: Argument Default Values — flag Out/InOut without defaults."""
    findings = []
    for arg in ctx.arguments:
        if arg.direction in ("Out", "InOut") and arg.type in ("String", "System.String"):
            findings.append(_make_finding(
                ctx, "ST-NMG-012", "Argument Default Values", "INFO", "Naming",
                f"Out/InOut argument '{arg.name}' (type: {arg.type}) — verify it has an appropriate default value.",
                "Assign a default value to avoid null reference errors.",
                activity_path=f"Argument: {arg.name}",
            ))
    return findings


def _check_st_nmg_016(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-016: Argument Length Exceeded."""
    findings = []
    for arg in ctx.arguments:
        if len(arg.name) > 30:
            findings.append(_make_finding(
                ctx, "ST-NMG-016", "Argument Length Exceeded", "LOW", "Naming",
                f"Argument '{arg.name}' has {len(arg.name)} characters, exceeding the recommended 30-character limit.",
                "Shorten the argument name while keeping it meaningful.",
                activity_path=f"Argument: {arg.name}",
            ))
    return findings


# ═══════════════════════════════════════════════════════════════════
# DESIGN BEST PRACTICES
# ═══════════════════════════════════════════════════════════════════

def _check_st_dbp_002(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-002: High Arguments Count."""
    if len(ctx.arguments) > 10:
        return [_make_finding(
            ctx, "ST-DBP-002", "High Arguments Count", "MEDIUM", "Design Best Practices",
            f"Workflow has {len(ctx.arguments)} arguments, exceeding the recommended maximum of 10.",
            "Refactor into smaller, reusable workflows with fewer arguments.",
        )]
    return []


def _check_st_dbp_003(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-003: Empty Catch Block."""
    findings = []
    for i, cb in enumerate(ctx.catch_blocks):
        if cb.activity_count == 0:
            findings.append(_make_finding(
                ctx, "ST-DBP-003", "Empty Catch Block", "HIGH", "Design Best Practices",
                f"Catch block for {cb.exception_type} has no handling logic. "
                "Exceptions will be silently swallowed.",
                "In Studio, add a Log Message (Level=Error) inside the Catch with Message: "
                '"Exception: " & exception.GetType().Name & " - " & exception.Message & " | Source: " & exception.Source',
                activity_path=f"Catch: {cb.exception_type}",
            ))
        elif not cb.has_log_message and cb.has_rethrow:
            findings.append(_make_finding(
                ctx, "ST-DBP-003", "Empty Catch Block", "MEDIUM", "Design Best Practices",
                f"Catch block for {cb.exception_type} rethrows without logging. "
                "The exception context may be lost.",
                "Add a Log Message activity before Rethrow to capture exception details.",
                activity_path=f"Catch: {cb.exception_type}",
            ))
    return findings


def _check_st_dbp_007(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-007: Multiple Flowchart Layers — nested flowcharts."""
    findings = []
    flowcharts = [a for a in ctx.activities if a.type_name == "Flowchart" and a.depth > 1]
    if flowcharts:
        findings.append(_make_finding(
            ctx, "ST-DBP-007", "Multiple Flowchart Layers", "MEDIUM", "Design Best Practices",
            f"Found {len(flowcharts)} nested Flowchart(s). Deeply nested flowcharts reduce readability.",
            "Simplify by extracting inner flowcharts into separate workflows or converting to Sequences.",
        ))
    return findings


def _check_st_dbp_020(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-020: Undefined Output Properties — Out arguments never assigned."""
    findings = []
    out_args = [a for a in ctx.arguments if a.direction in ("Out", "InOut")]
    for arg in out_args:
        if arg.name not in ctx.argument_usages:
            findings.append(_make_finding(
                ctx, "ST-DBP-020", "Undefined Output Properties", "HIGH", "Design Best Practices",
                f"Output argument '{arg.name}' is declared but never assigned a value in the workflow.",
                "Ensure the output argument is set before the workflow completes.",
                activity_path=f"Argument: {arg.name}",
            ))
    return findings


def _check_st_dbp_023(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-023: Empty Workflow."""
    # Filter out root/meta elements
    real_activities = [a for a in ctx.activities if a.depth > 0 and a.type_name not in (
        "Sequence", "Flowchart", "StateMachine", "Activity",
    )]
    if not real_activities:
        return [_make_finding(
            ctx, "ST-DBP-023", "Empty Workflow", "MEDIUM", "Design Best Practices",
            "Workflow contains no meaningful activities.",
            "Add activities or remove the empty workflow file.",
        )]
    return []


def _check_st_dbp_024(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-024: Persistence Activity Check — persistence outside Main."""
    findings = []
    if ctx.file_name.lower() != "main.xaml":
        for a in ctx.activities:
            if a.type_name in _PERSISTENCE_TYPES:
                findings.append(_make_finding(
                    ctx, "ST-DBP-024", "Persistence Activity Check", "HIGH", "Design Best Practices",
                    f"Persistence activity '{a.display_name}' ({a.type_name}) found outside Main.xaml. "
                    "Persistence activities must be in Main.xaml.",
                    "Move persistence activities to Main.xaml.",
                    activity_path=a.display_name,
                ))
    return findings


def _check_st_dbp_025(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-025: Variables Serialization — non-serializable variable types."""
    findings = []
    for var in ctx.variables:
        if var.type in _NON_SERIALIZABLE_TYPES:
            findings.append(_make_finding(
                ctx, "ST-DBP-025", "Variables Serialization", "MEDIUM", "Design Best Practices",
                f"Variable '{var.name}' has type '{var.type}' which may not be serializable. "
                "This can cause issues with persistence and parallel execution.",
                "Use a serializable type or ensure proper serialization handling.",
                activity_path=f"Variable: {var.name}",
            ))
    return findings


def _check_st_dbp_026(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-026: Delay Activity Usage — hardcoded delays."""
    findings = []
    for a in ctx.activities:
        if a.type_name in ("Delay", "NDelay"):
            duration = a.properties.get("Duration", "")
            if duration and not duration.startswith("["):
                findings.append(_make_finding(
                    ctx, "ST-DBP-026", "Delay Activity Usage", "MEDIUM", "Design Best Practices",
                    f"Hardcoded delay '{a.display_name}' with duration '{duration}'. "
                    "Hardcoded delays are unreliable and slow down execution.",
                    "Replace with dynamic waits (WaitForReady, Element Exists) or use a configurable timeout.",
                    activity_path=a.display_name,
                ))
        # Check DelayBefore/DelayMS on UI activities
        delay_before = a.properties.get("DelayBefore", "")
        delay_ms = a.properties.get("DelayMS", "")
        if delay_before and delay_before not in ("0", "{x:Null}"):
            findings.append(_make_finding(
                ctx, "ST-DBP-026", "Delay Activity Usage", "LOW", "Design Best Practices",
                f"Activity '{a.display_name}' has DelayBefore={delay_before}ms. Consider using element-based waits.",
                "Replace hardcoded DelayBefore with WaitForReady or Check App State.",
                activity_path=a.display_name,
            ))
    return findings


def _check_st_dbp_027(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-027: Persistence Best Practice."""
    findings = []
    has_persistence = any(a.type_name in _PERSISTENCE_TYPES for a in ctx.activities)
    if has_persistence and not ctx.has_global_exception_handler:
        findings.append(_make_finding(
            ctx, "ST-DBP-027", "Persistence Best Practice", "HIGH", "Design Best Practices",
            "Workflow uses persistence activities but has no Global Exception Handler. "
            "This can lead to stuck workflow instances.",
            "Add a Global Exception Handler to manage persistence failures.",
        ))
    return findings


def _check_st_dbp_028(ctx: ReviewContext) -> list[Finding]:
    """ST-DBP-028: Arguments Serialization."""
    findings = []
    for arg in ctx.arguments:
        if arg.type in _NON_SERIALIZABLE_TYPES:
            findings.append(_make_finding(
                ctx, "ST-DBP-028", "Arguments Serialization", "MEDIUM", "Design Best Practices",
                f"Argument '{arg.name}' has type '{arg.type}' which may not be serializable.",
                "Use a serializable type for arguments passed between workflows.",
                activity_path=f"Argument: {arg.name}",
            ))
    return findings


# ═══════════════════════════════════════════════════════════════════
# UI AUTOMATION
# ═══════════════════════════════════════════════════════════════════

def _check_ui_dbp_006(ctx: ReviewContext) -> list[Finding]:
    """UI-DBP-006: Container Usage — UI activities outside container scope."""
    findings = []
    for a in ctx.activities:
        if a.type_name in _UI_ACTIVITY_TYPES and not a.is_inside_container:
            findings.append(_make_finding(
                ctx, "UI-DBP-006", "Container Usage", "MEDIUM", "UI Automation",
                f"UI activity '{a.display_name}' ({a.type_name}) is not inside a container "
                "(Use Application/Browser, Attach Window, etc.).",
                "Wrap UI activities inside an appropriate container scope.",
                activity_path=a.display_name,
            ))
    return findings


def _check_ui_dbp_013(ctx: ReviewContext) -> list[Finding]:
    """UI-DBP-013: Excel Automation Misuse — Excel activities outside scope."""
    findings = []
    for a in ctx.activities:
        if a.type_name in _EXCEL_ACTIVITY_TYPES:
            in_excel_scope = any(
                anc in a.type_name for anc in ("ExcelApplicationScope", "UseExcelFile")
            )
            # Simplified: check if any ancestor is an Excel scope
            if not a.is_inside_container:
                findings.append(_make_finding(
                    ctx, "UI-DBP-013", "Excel Automation Misuse", "MEDIUM", "UI Automation",
                    f"Excel activity '{a.display_name}' ({a.type_name}) may not be inside an Excel scope.",
                    "Use 'Use Excel File' or 'Excel Application Scope' activity.",
                    activity_path=a.display_name,
                ))
    return findings


def _check_ui_dbp_030(ctx: ReviewContext) -> list[Finding]:
    """UI-DBP-030: Forbidden Variables in Selectors."""
    findings = []
    for a in ctx.activities:
        selector = a.properties.get("Selector", "")
        if selector and "[" in selector and "]" in selector:
            # Has variable reference in selector
            var_refs = re.findall(r'\[(\w+)\]', selector)
            findings.append(_make_finding(
                ctx, "UI-DBP-030", "Forbidden Variables in Selectors", "MEDIUM", "UI Automation",
                f"Activity '{a.display_name}' has dynamic variable(s) in selector: {', '.join(var_refs)}. "
                "Dynamic selectors are fragile and harder to maintain.",
                "Minimize dynamic selectors. Use anchors or stable attributes instead.",
                activity_path=a.display_name,
            ))
    return findings


def _check_ui_prr_004(ctx: ReviewContext) -> list[Finding]:
    """UI-PRR-004: Hardcoded Delays in UI automation."""
    findings = []
    for a in ctx.activities:
        if a.type_name in ("Delay", "NDelay") and a.is_inside_container:
            findings.append(_make_finding(
                ctx, "UI-PRR-004", "Hardcoded Delays", "MEDIUM", "UI Automation",
                f"Delay activity '{a.display_name}' used inside UI automation scope. "
                "Static delays slow execution and are unreliable.",
                "Use WaitForReady, Element Exists, or Check App State instead.",
                activity_path=a.display_name,
            ))
    return findings


def _check_ui_rel_001(ctx: ReviewContext) -> list[Finding]:
    """UI-REL-001: Large idx in Selectors — unstable index-based selectors."""
    findings = []
    for a in ctx.activities:
        selector = a.properties.get("Selector", "")
        if selector:
            idx_matches = re.findall(r'idx=["\']?(\d+)', selector)
            for idx_val in idx_matches:
                if int(idx_val) > 2:
                    findings.append(_make_finding(
                        ctx, "UI-REL-001", "Large idx in Selectors", "HIGH", "Reliability",
                        f"Activity '{a.display_name}' uses idx={idx_val} in selector. "
                        "High index values make selectors fragile and environment-dependent.",
                        "Use stable attributes (aaname, id, name) instead of idx.",
                        activity_path=a.display_name,
                    ))
    return findings


def _check_ui_sec_004(ctx: ReviewContext) -> list[Finding]:
    """UI-SEC-004: Sensitive Data in Selectors."""
    findings = []
    for a in ctx.activities:
        selector = a.properties.get("Selector", "")
        if selector and _SENSITIVE_PATTERNS.search(selector):
            findings.append(_make_finding(
                ctx, "UI-SEC-004", "Sensitive Data in Selectors", "CRITICAL", "Security",
                f"Activity '{a.display_name}' has potentially sensitive data in its selector. "
                "Selectors are logged and may expose sensitive information.",
                "Mask or parameterize sensitive data in selectors. Use Orchestrator Assets for secrets.",
                activity_path=a.display_name,
            ))
    return findings


def _check_ui_sec_010(ctx: ReviewContext) -> list[Finding]:
    """UI-SEC-010: App URL Restrictions — flag for review."""
    findings = []
    for a in ctx.activities:
        selector = a.properties.get("Selector", "")
        if selector:
            urls = re.findall(r'https?://[^\s\'"<>]+', selector)
            for url in urls:
                findings.append(_make_finding(
                    ctx, "UI-SEC-010", "App URL Restrictions", "INFO", "Security",
                    f"Activity '{a.display_name}' references URL '{url}' in selector. "
                    "Verify this is an approved application.",
                    "Ensure URLs are from approved applications. Store in Config/Assets.",
                    activity_path=a.display_name,
                ))
    return findings


# ═══════════════════════════════════════════════════════════════════
# PERFORMANCE
# ═══════════════════════════════════════════════════════════════════

def _check_ui_prr_001(ctx: ReviewContext) -> list[Finding]:
    """UI-PRR-001: Simulate Click Not Used."""
    findings = []
    for a in ctx.activities:
        if a.type_name in ("Click", "NClick"):
            sim = a.properties.get("SimulateClick", "")
            if sim not in ("True", "true"):
                findings.append(_make_finding(
                    ctx, "UI-PRR-001", "Simulate Click Not Used", "LOW", "Performance",
                    f"Click activity '{a.display_name}' does not use SimulateClick. "
                    "Simulate Click is faster and works in background.",
                    "In UiPath Studio, set SimulateClick=True on this Click activity.",
                    activity_path=a.display_name,
                ))
    return findings


def _check_ui_prr_002(ctx: ReviewContext) -> list[Finding]:
    """UI-PRR-002: Simulate Type Not Used."""
    findings = []
    for a in ctx.activities:
        if a.type_name in ("TypeInto", "NTypeInto"):
            sim = a.properties.get("SimulateType", "")
            if sim not in ("True", "true"):
                findings.append(_make_finding(
                    ctx, "UI-PRR-002", "Simulate Type Not Used", "LOW", "Performance",
                    f"TypeInto activity '{a.display_name}' does not use SimulateType. "
                    "Simulate Type is faster and works in background.",
                    "In UiPath Studio, set SimulateType=True on this TypeInto activity.",
                    activity_path=a.display_name,
                ))
    return findings


def _check_ui_prr_003(ctx: ReviewContext) -> list[Finding]:
    """UI-PRR-003: Open Application Misuse — repeated opens."""
    findings = []
    open_types = {"OpenBrowser", "OpenApplication", "StartProcess"}
    open_activities = [a for a in ctx.activities if a.type_name in open_types]
    type_counts = Counter(a.type_name for a in open_activities)
    for type_name, count in type_counts.items():
        if count > 1:
            findings.append(_make_finding(
                ctx, "UI-PRR-003", "Open Application Misuse", "MEDIUM", "Performance",
                f"'{type_name}' is used {count} times. Opening applications repeatedly wastes resources.",
                "Open the application once and reuse the instance. Use Attach/Use Application instead.",
            ))
    return findings


# ═══════════════════════════════════════════════════════════════════
# RELIABILITY
# ═══════════════════════════════════════════════════════════════════

def _check_gen_rel_001(ctx: ReviewContext) -> list[Finding]:
    """GEN-REL-001: Empty Sequences."""
    findings = []
    for a in ctx.activities:
        if a.type_name in ("Sequence", "NSequence") and a.child_count == 0 and a.depth > 0:
            findings.append(_make_finding(
                ctx, "GEN-REL-001", "Empty Sequences", "MEDIUM", "Reliability",
                f"Sequence '{a.display_name}' at depth {a.depth} has no child activities.",
                "Remove the empty sequence or add the intended activities.",
                activity_path=a.display_name,
            ))
    return findings


# ═══════════════════════════════════════════════════════════════════
# SECURITY
# ═══════════════════════════════════════════════════════════════════

def _check_ux_dbp_029(ctx: ReviewContext) -> list[Finding]:
    """UX-DBP-029: Insecure Password Usage."""
    findings = []
    # Check variable/argument names for sensitive patterns
    for var in ctx.variables:
        if _SENSITIVE_PATTERNS.search(var.name):
            if var.type in ("String", "System.String"):
                findings.append(_make_finding(
                    ctx, "UX-DBP-029", "Insecure Password Usage", "CRITICAL", "Security",
                    f"Variable '{var.name}' appears to contain sensitive data but uses plain String type. "
                    "Passwords must use SecureString, not String.",
                    "Change type to SecureString and use Get Credential or Orchestrator Assets.",
                    activity_path=f"Variable: {var.name}",
                ))
    for arg in ctx.arguments:
        if _SENSITIVE_PATTERNS.search(arg.name):
            if arg.type in ("String", "System.String"):
                findings.append(_make_finding(
                    ctx, "UX-DBP-029", "Insecure Password Usage", "CRITICAL", "Security",
                    f"Argument '{arg.name}' appears to contain sensitive data but uses plain String type.",
                    "Use SecureString type and Orchestrator Credential Assets instead.",
                    activity_path=f"Argument: {arg.name}",
                ))
    # Check for hardcoded Password properties
    for a in ctx.activities:
        pwd = a.properties.get("Password", "")
        if pwd and pwd not in ("{x:Null}", "") and not pwd.startswith("["):
            findings.append(_make_finding(
                ctx, "UX-DBP-029", "Insecure Password Usage", "CRITICAL", "Security",
                f"Activity '{a.display_name}' has a hardcoded Password property value. "
                "Never hardcode passwords in workflow files.",
                "Use Get Credential activity or Orchestrator Assets for password management.",
                activity_path=a.display_name,
            ))
    return findings


# ═══════════════════════════════════════════════════════════════════
# GENERAL
# ═══════════════════════════════════════════════════════════════════

def _check_gen_001(ctx: ReviewContext) -> list[Finding]:
    """GEN-001: Unused Variables."""
    findings = []
    for var in ctx.variables:
        if var.name not in ctx.variable_usages:
            findings.append(_make_finding(
                ctx, "GEN-001", "Unused Variables", "MEDIUM", "General",
                f"Variable '{var.name}' is declared but never used in any expression.",
                "Remove the unused variable to keep the workflow clean.",
                activity_path=f"Variable: {var.name}",
                auto_fixable=True,
            ))
    return findings


def _check_gen_002(ctx: ReviewContext) -> list[Finding]:
    """GEN-002: Unused Arguments."""
    findings = []
    for arg in ctx.arguments:
        if arg.name not in ctx.argument_usages:
            findings.append(_make_finding(
                ctx, "GEN-002", "Unused Arguments", "MEDIUM", "General",
                f"Argument '{arg.name}' is declared but never used in any expression.",
                "Remove the unused argument or wire it to the calling workflow.",
                activity_path=f"Argument: {arg.name}",
            ))
    return findings


def _check_gen_003(ctx: ReviewContext) -> list[Finding]:
    """GEN-003: Empty Sequences (same as GEN-REL-001, deduplicated)."""
    return []  # Covered by GEN-REL-001


def _check_gen_004(ctx: ReviewContext, all_file_names: list[str]) -> list[Finding]:
    """GEN-004: Project Structure Issues — check for basic REFramework patterns."""
    findings = []
    lower_files = [f.lower() for f in all_file_names]
    if len(all_file_names) > 3 and "main.xaml" not in lower_files:
        findings.append(_make_finding(
            ctx, "GEN-004", "Project Structure Issues", "HIGH", "General",
            "Project is missing Main.xaml entry point.",
            "Add a Main.xaml as the entry point for the automation project.",
        ))
    return findings


def _check_gen_005(ctx: ReviewContext) -> list[Finding]:
    """GEN-005: Package Restrictions — flag unknown/outdated packages."""
    findings = []
    if ctx.project_dependencies:
        known_prefixes = {"UiPath.", "System.", "Microsoft.", "Newtonsoft."}
        for pkg, version in ctx.project_dependencies.items():
            if not any(pkg.startswith(p) for p in known_prefixes):
                findings.append(_make_finding(
                    ctx, "GEN-005", "Package Restrictions", "INFO", "General",
                    f"Package '{pkg}' (version {version}) is not a standard UiPath/System package. "
                    "Verify it is approved for use.",
                    "Check with your team lead that this package is on the approved list.",
                ))
    return findings


# ═══════════════════════════════════════════════════════════════════
# MAIN ENTRY POINT
# ═══════════════════════════════════════════════════════════════════

# All single-context rule checkers
_RULES: list = [
    _check_st_nmg_001,
    _check_st_nmg_002,
    _check_st_nmg_004,
    _check_st_nmg_005,
    _check_st_nmg_006,
    _check_st_nmg_008,
    _check_st_nmg_009,
    _check_st_nmg_011,
    _check_st_nmg_012,
    _check_st_nmg_016,
    _check_st_dbp_002,
    _check_st_dbp_003,
    _check_st_dbp_007,
    _check_st_dbp_020,
    _check_st_dbp_023,
    _check_st_dbp_024,
    _check_st_dbp_025,
    _check_st_dbp_026,
    _check_st_dbp_027,
    _check_st_dbp_028,
    _check_ui_dbp_006,
    _check_ui_dbp_013,
    _check_ui_dbp_030,
    _check_ui_prr_004,
    _check_ui_rel_001,
    _check_ui_sec_004,
    _check_ui_sec_010,
    _check_ui_prr_001,
    _check_ui_prr_002,
    _check_ui_prr_003,
    _check_gen_rel_001,
    _check_ux_dbp_029,
    _check_gen_001,
    _check_gen_002,
    _check_gen_003,
    _check_gen_005,
]


def review_static(
    contexts: list[ReviewContext],
    project_name: str,
) -> list[Finding]:
    """Run all static analysis rules against parsed XAML contexts."""
    all_findings: list[Finding] = []
    all_file_names = [ctx.file_name for ctx in contexts]

    for ctx in contexts:
        # Run per-file rules
        for rule_fn in _RULES:
            all_findings.extend(rule_fn(ctx))

        # Cross-file rules
        all_findings.extend(_check_gen_004(ctx, all_file_names))

    # Deduplicate GEN-004 (only report once across all files)
    gen004_seen = False
    deduped: list[Finding] = []
    for f in all_findings:
        if f.rule_id == "GEN-004":
            if gen004_seen:
                continue
            gen004_seen = True
        deduped.append(f)

    # Assign sequential IDs
    for i, finding in enumerate(deduped, start=1):
        finding.id = f"CR-{i:03d}"

    return deduped
