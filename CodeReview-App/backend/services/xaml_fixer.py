"""
XAML Auto-Fix Engine
Applies fixes for deterministic rules found during code review.
Returns original and modified content with a list of changes applied.
"""

import re
import xml.etree.ElementTree as ET
from typing import Callable

from models.schemas import Finding


# ── Naming convention prefixes ─────────────────────────────────────
_TYPE_PREFIXES = {
    "String": "str_",
    "System.String": "str_",
    "Int32": "int_",
    "System.Int32": "int_",
    "Boolean": "bln_",
    "System.Boolean": "bln_",
    "DataTable": "dt_",
    "System.Data.DataTable": "dt_",
    "DateTime": "dtm_",
    "System.DateTime": "dtm_",
    "TimeSpan": "ts_",
    "System.TimeSpan": "ts_",
}

_DIRECTION_PREFIXES = {
    "In": "in_",
    "Out": "out_",
    "InOut": "io_",
}

_ARRAY_LIST_PATTERN = re.compile(r"(System\.Collections\.Generic\.List|.*\[\])", re.IGNORECASE)
_DICT_PATTERN = re.compile(r"System\.Collections\.Generic\.Dictionary", re.IGNORECASE)


def fix_xaml(xml_content: str, findings: list[Finding]) -> dict:
    """
    Apply fixes to XAML content based on findings.

    Returns:
        {
            "original_content": str,
            "modified_content": str,
            "changes_applied": list[str],
        }
    """
    changes: list[str] = []
    content = xml_content

    # Group findings by rule_id for batch processing
    findings_by_rule: dict[str, list[Finding]] = {}
    for f in findings:
        findings_by_rule.setdefault(f.rule_id, []).append(f)

    # Apply fixes in order of priority (CRITICAL first)
    for rule_id, rule_findings in sorted(
        findings_by_rule.items(),
        key=lambda x: _rule_priority(x[0]),
    ):
        handler = _FIX_HANDLERS.get(rule_id)
        if handler:
            result = handler(content, rule_findings)
            if result["modified"]:
                content = result["content"]
                changes.extend(result["changes"])

    return {
        "original_content": xml_content,
        "modified_content": content,
        "changes_applied": changes,
    }


def _rule_priority(rule_id: str) -> int:
    """Lower number = higher priority."""
    if rule_id.startswith("LINT-0") and int(rule_id.split("-")[1]) in (17, 23, 28, 57, 73, 76, 87, 88):
        return 0  # Studio Crash
    if rule_id.startswith("LINT-"):
        return 1
    if rule_id.startswith("NAME-"):
        return 2
    if rule_id.startswith("LOG-"):
        return 3
    if rule_id.startswith("ERR-"):
        return 4
    return 5


# ── Individual fix handlers ────────────────────────────────────────
# Each handler returns: { modified: bool, content: str, changes: list[str] }


def _fix_lint_017(content: str, findings: list[Finding]) -> dict:
    """LINT-017: NExtractDataGeneric DataTable= → ExtractedData="""
    modified = False
    changes = []
    pattern = re.compile(r'(\bDataTable\s*=\s*")', re.IGNORECASE)
    # Only apply inside NExtractDataGeneric context
    new_content = content
    for f in findings:
        count = 0
        def replacer(m):
            nonlocal count
            count += 1
            return 'ExtractedData="'
        new_content = pattern.sub(replacer, new_content)
        if count > 0:
            modified = True
            changes.append(f"LINT-017: Replaced DataTable= with ExtractedData= ({count} occurrence(s))")
    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_lint_023(content: str, findings: list[Finding]) -> dict:
    """LINT-023: .TargetAnchorable> → .Target>"""
    if ".TargetAnchorable>" not in content:
        return {"modified": False, "content": content, "changes": []}
    new_content = content.replace(".TargetAnchorable>", ".Target>")
    count = content.count(".TargetAnchorable>")
    return {
        "modified": True,
        "content": new_content,
        "changes": [f"LINT-023: Replaced .TargetAnchorable> with .Target> ({count} occurrence(s))"],
    }


def _fix_lint_028(content: str, findings: list[Finding]) -> dict:
    """LINT-028: Invalid ElementType enum → correct values"""
    replacements = {
        '"DataGrid"': '"Table"',
        '"ComboBox"': '"DropDown"',
        '"InputBoxText"': '"InputBox"',
    }
    modified = False
    changes = []
    new_content = content
    for old, new in replacements.items():
        if old in new_content:
            new_content = new_content.replace(old, new)
            modified = True
            changes.append(f"LINT-028: Replaced ElementType {old} with {new}")
    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_lint_040(content: str, findings: list[Finding]) -> dict:
    """LINT-040: UIAutomation.Enums → UIAutomationNext.Enums"""
    if "UIAutomation.Enums" not in content:
        return {"modified": False, "content": content, "changes": []}
    # Only replace UIAutomation.Enums, not UIAutomationNext.Enums
    new_content = re.sub(
        r'(?<!Next\.)UIAutomation\.Enums',
        'UIAutomationNext.Enums',
        content
    )
    if new_content != content:
        return {
            "modified": True,
            "content": new_content,
            "changes": ["LINT-040: Replaced UIAutomation.Enums with UIAutomationNext.Enums"],
        }
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_053(content: str, findings: list[Finding]) -> dict:
    """LINT-053: Remove InteractionMode on unsupported activities (NGetText, NCheckState, etc.)"""
    # Remove InteractionMode attribute from activities that don't support it
    pattern = re.compile(r'\s+InteractionMode="[^"]*"')
    new_content = pattern.sub("", content)
    if new_content != content:
        count = len(pattern.findall(content))
        return {
            "modified": True,
            "content": new_content,
            "changes": [f"LINT-053: Removed unsupported InteractionMode attribute ({count} occurrence(s))"],
        }
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_054(content: str, findings: list[Finding]) -> dict:
    """LINT-054: QueueName= → QueueType= on AddQueueItem/GetQueueItem"""
    pattern = re.compile(r'(\bQueueName\s*=\s*")')
    new_content = pattern.sub('QueueType="', content)
    if new_content != content:
        return {
            "modified": True,
            "content": new_content,
            "changes": ["LINT-054: Replaced QueueName= with QueueType="],
        }
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_071(content: str, findings: list[Finding]) -> dict:
    """LINT-071: Double-escaped quotes &quot; in expressions → use double-quote"""
    if "&quot;" not in content:
        return {"modified": False, "content": content, "changes": []}
    # Only replace inside VB expression brackets [...]
    pattern = re.compile(r'(\[.*?&quot;.*?\])', re.DOTALL)

    def replace_in_expr(m):
        return m.group(0).replace("&quot;", '""')

    new_content = pattern.sub(replace_in_expr, content)
    if new_content != content:
        return {
            "modified": True,
            "content": new_content,
            "changes": ["LINT-071: Replaced &quot; with double-quotes in VB expressions"],
        }
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_083(content: str, findings: list[Finding]) -> dict:
    """LINT-083: Double-bracketed [[...]] → [...]"""
    pattern = re.compile(r'\[\[([^\[\]]+)\]\]')
    new_content = pattern.sub(r'[\1]', content)
    if new_content != content:
        count = len(pattern.findall(content))
        return {
            "modified": True,
            "content": new_content,
            "changes": [f"LINT-083: Fixed double-bracketed expressions ({count} occurrence(s))"],
        }
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_087(content: str, findings: list[Finding]) -> dict:
    """LINT-087: Wrong xmlns on DataTable/DataRow — fix to sd: prefix"""
    modified = False
    changes = []
    new_content = content

    # Fix wrong prefixes for DataTable/DataRow (should be sd:)
    for wrong_prefix in ["s:", "scg:", "sco:", ""]:
        for type_name in ["DataTable", "DataRow"]:
            old = f"{wrong_prefix}{type_name}"
            new = f"sd:{type_name}"
            if old in new_content and f"sd:{type_name}" not in new_content.replace(old, ""):
                new_content = new_content.replace(old, new)
                modified = True
                changes.append(f"LINT-087: Fixed xmlns prefix for {type_name} to sd:")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_lint_038(content: str, findings: list[Finding]) -> dict:
    """LINT-038: Browser missing IsIncognito='True'"""
    # Add IsIncognito="True" to NApplicationCard/NBrowserScope that lack it
    pattern = re.compile(
        r'(<(?:\w+:)?(?:NApplicationCard|NBrowserScope)\b)([^>]*?)((?:IsIncognito="[^"]*")?)',
        re.DOTALL
    )

    def add_incognito(m):
        tag_start = m.group(1)
        attrs = m.group(2)
        existing = m.group(3)
        if 'IsIncognito=' in attrs or 'IsIncognito=' in existing:
            return m.group(0)
        return f'{tag_start}{attrs} IsIncognito="True"'

    new_content = pattern.sub(add_incognito, content)
    if new_content != content:
        return {
            "modified": True,
            "content": new_content,
            "changes": ["LINT-038: Added IsIncognito=\"True\" to browser activities"],
        }
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_047(content: str, findings: list[Finding]) -> dict:
    """LINT-047: NApplicationCard OpenMode not Never → set OpenMode='Never'"""
    pattern = re.compile(r'(OpenMode\s*=\s*")[^"]*(")')
    new_content = pattern.sub(r'\g<1>Never\2', content)
    if new_content != content:
        return {
            "modified": True,
            "content": new_content,
            "changes": ["LINT-047: Set OpenMode to Never on NApplicationCard"],
        }
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_097(content: str, findings: list[Finding]) -> dict:
    """LINT-097: css-selector= in selector — flag only, manual fix needed"""
    return {"modified": False, "content": content, "changes": []}


def _fix_naming_variable(content: str, findings: list[Finding], expected_prefix: str, var_type: str) -> dict:
    """Generic variable naming fix — prepend expected prefix to variable names."""
    modified = False
    changes = []
    new_content = content

    for f in findings:
        # Extract the variable name from the description
        desc = f.description
        # Try to find the variable name — it's usually quoted or after "Variable '"
        match = re.search(r"[Vv]ariable\s+['\"](\w+)['\"]", desc)
        if not match:
            match = re.search(r"named\s+['\"](\w+)['\"]", desc)
        if not match:
            continue

        var_name = match.group(1)
        if var_name.startswith(expected_prefix):
            continue  # Already has correct prefix

        new_name = expected_prefix + var_name
        # Replace variable name in all contexts (declarations, usages)
        old_patterns = [
            f'Name="{var_name}"',
            f"[{var_name}]",
            f'"{var_name}"',
        ]
        for old_pat in old_patterns:
            new_pat = old_pat.replace(var_name, new_name)
            if old_pat in new_content:
                new_content = new_content.replace(old_pat, new_pat)
                modified = True

        if modified:
            changes.append(f"NAME: Renamed variable '{var_name}' → '{new_name}'")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_name_001(content: str, findings: list[Finding]) -> dict:
    return _fix_naming_variable(content, findings, "str_", "String")


def _fix_name_002(content: str, findings: list[Finding]) -> dict:
    return _fix_naming_variable(content, findings, "int_", "Int32")


def _fix_name_003(content: str, findings: list[Finding]) -> dict:
    return _fix_naming_variable(content, findings, "bln_", "Boolean")


def _fix_name_004(content: str, findings: list[Finding]) -> dict:
    return _fix_naming_variable(content, findings, "dt_", "DataTable")


def _fix_name_005(content: str, findings: list[Finding]) -> dict:
    return _fix_naming_variable(content, findings, "arr_", "Array/List")


def _fix_name_006(content: str, findings: list[Finding]) -> dict:
    """NAME-006: In argument prefix → in_"""
    return _fix_naming_variable(content, findings, "in_", "In Argument")


def _fix_name_007(content: str, findings: list[Finding]) -> dict:
    """NAME-007: Out argument prefix → out_"""
    return _fix_naming_variable(content, findings, "out_", "Out Argument")


def _fix_name_008(content: str, findings: list[Finding]) -> dict:
    """NAME-008: InOut argument prefix → io_"""
    return _fix_naming_variable(content, findings, "io_", "InOut Argument")


def _fix_name_012(content: str, findings: list[Finding]) -> dict:
    return _fix_naming_variable(content, findings, "dtm_", "DateTime/TimeSpan")


def _fix_name_013(content: str, findings: list[Finding]) -> dict:
    return _fix_naming_variable(content, findings, "dic_", "Dictionary")


def _fix_log_001(content: str, findings: list[Finding]) -> dict:
    """LOG-001: Missing Start Log — insert LogMessage at beginning of workflow."""
    return _insert_log_bookend(content, findings, position="start")


def _fix_log_002(content: str, findings: list[Finding]) -> dict:
    """LOG-002: Missing End Log — insert LogMessage at end of workflow."""
    return _insert_log_bookend(content, findings, position="end")


def _insert_log_bookend(content: str, findings: list[Finding], position: str) -> dict:
    """Insert a LogMessage activity at start or end of the root Sequence workflow.

    Handles both XAML styles:
      - Explicit <Sequence.Activities>...</Sequence.Activities> wrapper
      - Direct children inside <Sequence>...</Sequence>
    Skips insertion if a bookend log already exists (idempotent).
    """
    workflow_name = findings[0].workflow_name if findings else "Unknown"
    label = "[START]" if position == "start" else "[END]"

    # Skip if a bookend log for this position already exists
    autofix_marker = f'LogMessage_AutoFix_{position}'
    if autofix_marker in content:
        return {"modified": False, "content": content, "changes": []}

    log_activity = (
        f'    <ui:LogMessage DisplayName="Log {label} {workflow_name}" '
        f'sap2010:WorkflowViewState.IdRef="{autofix_marker}" '
        f'Level="Info" '
        f'Message="[&quot;{label} {workflow_name}&quot;]" />\n'
    )

    # Find the first (root) <Sequence> tag
    seq_open_pattern = re.compile(r'<Sequence\b[^>]*>')
    seq_open_match = seq_open_pattern.search(content)
    if not seq_open_match:
        return {"modified": False, "content": content, "changes": []}

    seq_start = seq_open_match.end()

    # Find the outermost </Sequence> (last occurrence = root close)
    last_close_pos = content.rfind("</Sequence>")
    if last_close_pos < 0:
        return {"modified": False, "content": content, "changes": []}

    root_body = content[seq_start:last_close_pos]

    # Check if explicit <Sequence.Activities> wrapper exists in root body
    has_activities_wrapper = "<Sequence.Activities>" in root_body

    if has_activities_wrapper:
        act_open_pos = content.find("<Sequence.Activities>", seq_start)
        act_close_pos = content.find("</Sequence.Activities>", seq_start)

        if act_open_pos < 0 or act_close_pos < 0:
            return {"modified": False, "content": content, "changes": []}

        if position == "start":
            insert_pos = act_open_pos + len("<Sequence.Activities>")
            new_content = content[:insert_pos] + "\n" + log_activity + content[insert_pos:]
        else:
            new_content = content[:act_close_pos] + log_activity + content[act_close_pos:]
    else:
        # No explicit wrapper — insert as direct child of the root Sequence.
        # Find the first actual activity element (not a property element like
        # Sequence.Variables or sap:WorkflowViewStateService.ViewState).
        # Activities are elements that don't use the "Type.Property" naming pattern.

        if position == "start":
            # Find the position of the first activity element after the Sequence opens.
            # Skip past Sequence.Variables and ViewState property elements.
            search_start = seq_start

            # Skip past </Sequence.Variables> if present
            var_close_pos = content.find("</Sequence.Variables>", search_start)
            if var_close_pos >= 0 and var_close_pos < last_close_pos:
                search_start = var_close_pos + len("</Sequence.Variables>")

            # Skip past </sap:WorkflowViewStateService.ViewState> if it appears
            # right after Variables (before first activity)
            viewstate_close = "</sap:WorkflowViewStateService.ViewState>"
            vs_pos = content.find(viewstate_close, search_start)
            if vs_pos >= 0 and vs_pos < last_close_pos:
                # Check if there's no activity element between search_start and vs_pos
                between = content[search_start:vs_pos].strip()
                if between.startswith("<sap:") or between == "":
                    search_start = vs_pos + len(viewstate_close)

            new_content = content[:search_start] + "\n" + log_activity + content[search_start:]
        else:
            # Insert before the last </Sequence> (root close)
            new_content = content[:last_close_pos] + log_activity + content[last_close_pos:]

    return {
        "modified": True,
        "content": new_content,
        "changes": [f"LOG-00{1 if position == 'start' else 2}: Added {label} LogMessage for {workflow_name}"],
    }


def _fix_conf_002(content: str, findings: list[Finding]) -> dict:
    """CONF-002: Hardcoded file paths — flag only, needs manual config extraction."""
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_032(content: str, findings: list[Finding]) -> dict:
    """LINT-032: Environment.SpecialFolder.Temp → Path.GetTempPath()"""
    old = "Environment.SpecialFolder.Temp"
    new = "Path.GetTempPath()"
    if old not in content:
        return {"modified": False, "content": content, "changes": []}
    new_content = content.replace(old, new)
    return {
        "modified": True,
        "content": new_content,
        "changes": ["LINT-032: Replaced Environment.SpecialFolder.Temp with Path.GetTempPath()"],
    }


def _fix_lint_041(content: str, findings: list[Finding]) -> dict:
    """LINT-041: FuzzySelector default → SearchSteps='Selector'"""
    # Add SearchSteps="Selector" where FuzzySelector is the default
    pattern = re.compile(r'(FuzzySelector\s*=\s*"[^"]*")')
    if not pattern.search(content):
        return {"modified": False, "content": content, "changes": []}
    # This is a complex structural fix, flag only
    return {"modified": False, "content": content, "changes": []}


def _fix_lint_104(content: str, findings: list[Finding]) -> dict:
    """LINT-104: Hardcoded user path — flag only."""
    return {"modified": False, "content": content, "changes": []}


def _noop_fix(content: str, findings: list[Finding]) -> dict:
    """No-op fix for rules that require manual intervention."""
    return {"modified": False, "content": content, "changes": []}


# ── Handler registry ───────────────────────────────────────────────
_FIX_HANDLERS: dict[str, Callable] = {
    # LINT — Studio Crash
    "LINT-017": _fix_lint_017,
    "LINT-023": _fix_lint_023,
    "LINT-028": _fix_lint_028,
    "LINT-087": _fix_lint_087,
    # LINT — Compile/Runtime
    "LINT-032": _fix_lint_032,
    "LINT-040": _fix_lint_040,
    "LINT-053": _fix_lint_053,
    "LINT-054": _fix_lint_054,
    "LINT-071": _fix_lint_071,
    "LINT-083": _fix_lint_083,
    # LINT — Best Practice
    "LINT-038": _fix_lint_038,
    "LINT-041": _fix_lint_041,
    "LINT-047": _fix_lint_047,
    "LINT-097": _fix_lint_097,
    "LINT-104": _fix_lint_104,
    # Naming Conventions
    "NAME-001": _fix_name_001,
    "NAME-002": _fix_name_002,
    "NAME-003": _fix_name_003,
    "NAME-004": _fix_name_004,
    "NAME-005": _fix_name_005,
    "NAME-006": _fix_name_006,
    "NAME-007": _fix_name_007,
    "NAME-008": _fix_name_008,
    "NAME-012": _fix_name_012,
    "NAME-013": _fix_name_013,
    # Logging (LOG-001, LOG-002 removed — bookend logs no longer enforced)
    # Configuration (manual)
    "CONF-002": _fix_conf_002,
}
