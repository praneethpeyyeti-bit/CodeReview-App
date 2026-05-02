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
    """ST-NMG-001: Variables Naming Convention — check type prefixes.

    Only flags variables whose type maps to a known prefix (String, Int32,
    Boolean, DataTable, DateTime, TimeSpan, arrays/lists, dictionaries).
    Unknown types (e.g. `ui:WorkbookApplication`, custom entity types, SAP
    objects) are left alone — applying a wrong prefix there produced renames
    like `str_OpenWorkbook` on an Excel handle, which broke VB resolution
    and cascaded into BC30451 "variable not declared" errors.
    """
    findings = []
    for var in ctx.variables:
        expected = _TYPE_PREFIXES.get(var.type)
        if not expected:
            if "[]" in var.type or "List" in var.type:
                expected = "arr_"
            elif "Dictionary" in var.type:
                expected = "dic_"
            else:
                continue  # unknown type — don't guess
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
    """ST-NMG-004: Display Name Duplication.

    Includes Assign — multiple Assign activities with default DisplayName
    "Assign" is a real violation per UiPath naming guidelines. The remaining
    generic filter skips structural-by-design types (Sequence, flowchart
    nodes) where duplicates are common scaffolding noise rather than user
    mistakes.
    """
    findings = []
    # Aligned with the fixer's `_GENERIC_DISPLAY_NAMES` set — these are
    # structural scaffolding types where the fixer deliberately leaves
    # default names alone, so flagging them produces noise the user can't act
    # on (the fixer would just skip). Try/Catch/Finally are particularly
    # noisy because TryCatch blocks always emit them as duplicates.
    generic_names = {
        "Sequence", "Flowchart", "FlowDecision", "FlowStep",
        "Body", "TryCatch", "Try", "Catch", "Finally",
        # Typed UI sub-components — these are nested inside parent activities
        # and their DEFAULT display names equal the type name. They reject
        # `DisplayName` injection (Studio: "Could not find member 'DisplayName'
        # in type 'uix:TargetX'"), so flagging duplicates here just produces
        # findings the fixer can't act on without corrupting the file.
        "Target", "TargetApp", "TargetAnchorable", "TargetRegion", "TargetImage",
        "VerifyExecutionOptions", "VerifyExecutionTypeIntoOptions",
        "VerifyExecutionClickOptions", "VerifyExecutionGetTextOptions",
        "InputOptions", "OutputOptions", "ScreenshotOptions",
    }
    names = [a.display_name for a in ctx.activities if a.display_name not in generic_names]
    counts = Counter(names)
    # Iterate keys in a stable order so finding IDs are deterministic across runs
    for name, count in sorted(counts.items()):
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
    """ST-NMG-005: Variable Overrides Variable — only flag TRUE nested shadows.

    Two variables with the same name shadow each other only when one scope is
    an *ancestor* of the other (i.e. one scope_path is a strict prefix of the
    other). Sibling sub-sequences (e.g. ``<Sequence x:Key="get">`` and
    ``<Sequence x:Key="create">``) each have their own independent scope and
    legitimately declare the same name without shadowing.
    """
    findings = []
    # Group variables by name so we can compare every pair within the group.
    by_name: dict[str, list] = {}
    for var in ctx.variables:
        by_name.setdefault(var.name, []).append(var)

    reported: set[tuple[str, str]] = set()
    for name, group in sorted(by_name.items()):
        if len(group) < 2:
            continue
        # Find ancestor/descendant pairs. A is ancestor of B iff
        # A.scope_path is a strict prefix of B.scope_path.
        for outer in group:
            for inner in group:
                if outer is inner:
                    continue
                op = outer.scope_path or [outer.scope]
                ip = inner.scope_path or [inner.scope]
                if len(op) >= len(ip):
                    continue
                if ip[: len(op)] != op:
                    continue
                key = (name, inner.scope)
                if key in reported:
                    continue
                reported.add(key)
                findings.append(_make_finding(
                    ctx, "ST-NMG-005", "Variable Overrides Variable", "MEDIUM", "Naming",
                    f"Variable '{name}' declared in inner scope '{inner.scope}' "
                    f"shadows the outer declaration in '{outer.scope}'.",
                    "Rename the inner variable, or remove it so references resolve to the outer one "
                    "(auto-fix removes only this specific inner-scope declaration).",
                    activity_path=f"Variable: {name} @ {inner.scope}",
                    auto_fixable=True,
                ))
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
                "Rename the variable or argument to be distinct (auto-fix removes the variable, retaining the argument).",
                activity_path=f"Variable: {var.name}",
                auto_fixable=True,
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
                "Shorten the variable name while keeping it meaningful (auto-fix preserves prefix and drops middle words).",
                activity_path=f"Variable: {var.name}",
                auto_fixable=True,
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
    """ST-NMG-012: Argument Default Values — flag In arguments that carry defaults.

    Out/InOut arguments cannot be given defaults in XAML (the workflow assigns
    them), so this rule focuses on In arguments. A default value on an In
    argument is a code smell: callers that rely on it get hidden coupling to
    the workflow's internal "convenience" value.
    """
    findings = []
    for arg in ctx.arguments:
        if arg.direction != "In":
            continue
        if not arg.has_default:
            continue
        findings.append(_make_finding(
            ctx, "ST-NMG-012", "Argument Default Values", "LOW", "Naming",
            f"In argument '{arg.name}' has a default value. Callers should supply the value explicitly.",
            "Remove the default; callers should always pass a value explicitly (auto-fix deletes the default-value block).",
            activity_path=f"Argument: {arg.name}",
            auto_fixable=True,
        ))
    return findings


_PASCAL_PREFIXES = (
    "in_str_", "in_int_", "in_bln_", "in_dt_", "in_dtm_", "in_ts_", "in_arr_", "in_dic_",
    "out_str_", "out_int_", "out_bln_", "out_dt_", "out_dtm_", "out_ts_", "out_arr_", "out_dic_",
    "io_str_", "io_int_", "io_bln_", "io_dt_", "io_dtm_", "io_ts_", "io_arr_", "io_dic_",
    "in_", "out_", "io_",
    "str_", "int_", "bln_", "dt_", "dtm_", "ts_", "arr_", "dic_",
)


def _split_known_prefix(name: str) -> tuple[str, str]:
    """Split a variable/argument name into (prefix, body). Empty prefix if none match."""
    for p in _PASCAL_PREFIXES:
        if name.startswith(p):
            return p, name[len(p):]
    return "", name


def _body_is_pascal_case(body: str) -> bool:
    """True when the body part of a name is proper PascalCase.

    Rules:
      - Must not contain underscores
      - Must start with an uppercase letter
      - If the body is long (>= 10 chars) AND looks like a concatenation of
        multiple lowercase words with no boundary markers (e.g.
        'Filtercandidatedetailsfromsaptabledata'), treat it as needing
        word-splitting and reject. A long single English word like
        'Description' is valid PascalCase and must NOT be flagged — we
        consult wordninja to disambiguate (single-word bodies are accepted
        regardless of length).
    """
    if not body:
        return True
    if "_" in body:
        return False
    if not body[0].isalpha() or not body[0].isupper():
        return False
    # Long bodies with internal uppercase/digit boundaries are clearly
    # multi-word PascalCase — accept fast.
    if len(body) >= 10:
        tail = body[1:]
        has_boundary = any(c.isupper() or c.isdigit() for c in tail)
        if not has_boundary:
            # No internal boundary. Could be either a single long English
            # word ("Description", "Authentication", "Configuration") or
            # a concatenated soup ("Filtercandidatedetailsfromsaptabledata").
            # Use wordninja to decide — a single-word split means the whole
            # body IS that word, which is valid PascalCase.
            try:
                import wordninja as _wn
                parts = _wn.split(body.lower())
                if len(parts) <= 1:
                    return True
                # Multi-word soup — needs splitting + recapitalisation.
                return False
            except ImportError:
                # Fall back to the strict rule if wordninja isn't available.
                return False
    return True


def _check_st_nmg_010(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-010: PascalCase Convention for variable/argument bodies.

    After the known prefix (str_, dt_, in_, out_, ...), the remaining body of
    a variable or argument name must be PascalCase — starts with an uppercase
    letter and contains no underscores.
    """
    findings = []
    for var in ctx.variables:
        prefix, body = _split_known_prefix(var.name)
        if _body_is_pascal_case(body):
            continue
        findings.append(_make_finding(
            ctx, "ST-NMG-010", "PascalCase Convention", "LOW", "Naming",
            f"Variable '{var.name}' does not use PascalCase after the prefix "
            f"('{prefix}' + body '{body}').",
            "Rename to use PascalCase after the prefix "
            "(auto-fix removes underscores in the body and capitalizes each word).",
            activity_path=f"Variable: {var.name}",
            auto_fixable=True,
        ))
    for arg in ctx.arguments:
        prefix, body = _split_known_prefix(arg.name)
        if _body_is_pascal_case(body):
            continue
        findings.append(_make_finding(
            ctx, "ST-NMG-010", "PascalCase Convention", "LOW", "Naming",
            f"Argument '{arg.name}' does not use PascalCase after the prefix "
            f"('{prefix}' + body '{body}').",
            "Rename to use PascalCase after the prefix "
            "(auto-fix removes underscores in the body and capitalizes each word).",
            activity_path=f"Argument: {arg.name}",
            auto_fixable=True,
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
                "Shorten the argument name while keeping it meaningful (auto-fix preserves prefix and drops middle words).",
                activity_path=f"Argument: {arg.name}",
                auto_fixable=True,
            ))
    return findings


# Activity types whose default DisplayName (equal to the type name) is
# acceptable — these are structural containers where a more descriptive
# name is usually unnecessary and often misleading.
_STRUCTURAL_ACTIVITY_TYPES: frozenset = frozenset({
    # Workflow roots / delegate wrappers — Studio rejects DisplayName here.
    "Activity", "StateMachine",
    "ActivityFunc", "ActivityAction",
    # Property-element shells (also caught by the "." filter, kept for
    # safety on the bare-element case).
    "Body", "Try", "Catch", "Finally",
    # Modern UI-Automation target wrappers — nested inside NClick.Target /
    # NTypeInto.Target etc. Studio auto-numbers them, they aren't surfaced
    # as user-facing activities, AND most are typed components that REJECT
    # DisplayName injection ("Could not find member 'DisplayName' in type
    # 'uix:TargetX'"). Flagging them produces noise the fixer can't act on.
    "Target", "TargetApp", "TargetAnchorable", "TargetRegion", "TargetImage",
    "VerifyExecutionOptions", "VerifyExecutionTypeIntoOptions",
    "VerifyExecutionClickOptions", "VerifyExecutionGetTextOptions",
    "InputOptions", "OutputOptions", "ScreenshotOptions",
})


def _check_st_nmg_020(ctx: ReviewContext) -> list[Finding]:
    """ST-NMG-020: Default Studio Display Name.

    Flags any activity whose DisplayName was left at the Studio default
    (either missing or equal to the activity type). Flowchart-family nodes
    and statement-like activities (Break/Throw/...) are excluded because
    they have no meaningful descriptor to derive.

    Auto-fix renames such activities using a meaningful descriptor —
    selector content for UI Automation activities (Click/TypeInto/GetText/
    etc.), the most telling property for others (Assign's target variable,
    LogMessage's Message, InvokeWorkflowFile's filename, ...), and the
    first meaningful inner activity for containers (Sequence, TryCatch).
    """
    findings: list[Finding] = []
    for a in ctx.activities:
        if a.type_name in _STRUCTURAL_ACTIVITY_TYPES:
            continue
        # Default-named = DisplayName missing (falls back to type_name in parser)
        # or explicitly set to the type_name.
        if a.display_name != a.type_name:
            continue
        findings.append(_make_finding(
            ctx, "ST-NMG-020", "Default Studio Display Name", "LOW", "Naming",
            f"Activity of type '{a.type_name}' is still using the default Studio "
            f"display name. Rename it to describe what the activity does.",
            "Auto-fix derives a meaningful label from the activity's selector "
            "(UI Automation) or from its most telling property (Assign target, "
            "LogMessage text, etc.). Activities with no derivable descriptor "
            "are left for manual renaming.",
            activity_path=f"Activity: {a.type_name}",
            auto_fixable=True,
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
                "Auto-fix inserts a Log Message (Level=Error) inside the Catch with exception type, message, and source.",
                activity_path=f"Catch: {cb.exception_type}",
                auto_fixable=True,
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
    for type_name, count in sorted(type_counts.items()):
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
    """GEN-REL-001: Empty Sequences (standalone Sequence activities only).

    Skip Sequences that are structural TryCatch wrappers (catch handler body or
    Finally) — their emptiness is already covered by ST-DBP-003.
    """
    findings = []
    for a in ctx.activities:
        if a.type_name in ("Sequence", "NSequence") and a.child_count == 0 and a.depth > 0 and not a.is_structural_wrapper:
            findings.append(_make_finding(
                ctx, "GEN-REL-001", "Empty Sequences", "MEDIUM", "Reliability",
                f"Sequence '{a.display_name}' at depth {a.depth} has no child activities.",
                "Remove the empty sequence or add the intended activities (auto-fix removes self-closing empty Sequence elements).",
                activity_path=a.display_name,
                auto_fixable=True,
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
    _check_st_nmg_010,
    _check_st_nmg_011,
    _check_st_nmg_012,
    _check_st_nmg_016,
    _check_st_nmg_020,
    _check_st_dbp_002,
    _check_st_dbp_003,
    _check_st_dbp_007,
    _check_st_dbp_020,
    _check_st_dbp_024,
    _check_st_dbp_025,
    _check_st_dbp_026,
    _check_st_dbp_027,
    _check_st_dbp_028,
    _check_ui_dbp_006,
    _check_ui_dbp_013,
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


def review_single_file(
    ctx: ReviewContext,
    all_file_names: list[str] | None = None,
) -> list[Finding]:
    """Run all rules against a single parsed XAML context.

    Used by the auto-fix convergence loop to re-evaluate a file after each
    pass — if a fix introduced a new violation (e.g. a rename pushed the
    name over the length limit) the next pass will see the new finding.
    """
    findings: list[Finding] = []
    for rule_fn in _RULES:
        findings.extend(rule_fn(ctx))
    findings.extend(_check_gen_004(ctx, all_file_names or [ctx.file_name]))
    for i, f in enumerate(findings, start=1):
        f.id = f"CR-{i:03d}"
    return findings


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
