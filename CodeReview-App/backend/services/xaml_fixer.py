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
    if rule_id.startswith("UI-SEC") or rule_id == "UX-DBP-029":
        return 0  # Security — CRITICAL
    if rule_id.startswith("ST-DBP"):
        return 1  # Design Best Practices
    if rule_id.startswith("ST-NMG"):
        return 2  # Naming
    if rule_id.startswith("UI-"):
        return 3  # UI Automation / Performance / Reliability
    if rule_id.startswith("GEN"):
        return 4  # General
    return 5


# ── Individual fix handlers ────────────────────────────────────────
# Each handler returns: { modified: bool, content: str, changes: list[str] }


def _extract_name_from_finding(finding: Finding, kind: str = "variable") -> str | None:
    """Extract the variable/argument name from a finding's description or activity_path."""
    desc = finding.description
    activity = finding.activity_path or ""

    # Try activity_path first (e.g. "Variable: myVar" or "Argument: myArg")
    m = re.search(r"(?:Variable|Argument):\s*(\w+)", activity)
    if m:
        return m.group(1)

    # Try description patterns
    patterns = [
        rf"[Vv]ariable\s+['\"](\w+)['\"]",
        rf"[Aa]rgument\s+['\"](\w+)['\"]",
        r"named\s+['\"](\w+)['\"]",
        r"'(\w+)'",
    ]
    for pat in patterns:
        m = re.search(pat, desc)
        if m:
            return m.group(1)
    return None


def _rename_in_xaml(content: str, old_name: str, new_name: str) -> tuple[str, int]:
    """Rename a variable/argument across all locations in XAML content.

    Handles:
      1. Variable/Argument declarations:  Name="oldName"
      2. Standalone VB expression refs:   [oldName]
      3. VB expressions with members:     [oldName.ToString()] [oldName & " x"]
      4. Inside complex expressions:      [CInt(oldName)] [oldName + other]
      5. Argument key bindings:           Key="oldName"  (InvokeWorkflow arguments)
      6. Default values with variable:    Default="[oldName]"

    Returns (new_content, replacement_count).
    """
    count = 0

    # 1. Variable/Argument declaration: Name="oldName"
    pattern = re.compile(rf'\bName="{re.escape(old_name)}"')
    content, n = pattern.subn(f'Name="{new_name}"', content)
    count += n

    # 2. Argument key bindings: Key="oldName" (InvokeWorkflowFile argument maps)
    pattern = re.compile(rf'\bKey="{re.escape(old_name)}"')
    content, n = pattern.subn(f'Key="{new_name}"', content)
    count += n

    # 3. VB expression references inside [...] brackets
    #    Matches oldName as a whole word inside brackets.
    #    Handles: [oldName], [oldName.Prop], [oldName & "x"], [CInt(oldName)], etc.
    #    Uses word boundary (\b) to avoid partial matches (e.g. "oldName2" stays).
    pattern = re.compile(
        r'(\[(?:[^\[\]])*?)'           # opening [ and any content before the name
        rf'\b{re.escape(old_name)}\b'  # the variable name as a whole word
        r'((?:[^\[\]])*?\])'           # any content after the name and closing ]
    )
    content, n = pattern.subn(rf'\g<1>{new_name}\g<2>', content)
    count += n

    return content, count


def _fix_naming_variable(content: str, findings: list[Finding], expected_prefix: str, var_type: str) -> dict:
    """Generic variable naming fix — prepend expected prefix to variable names."""
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        var_name = _extract_name_from_finding(f, "variable")
        if not var_name or var_name in seen:
            continue
        seen.add(var_name)

        if var_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + var_name
        new_content, count = _rename_in_xaml(new_content, var_name, new_name)
        if count > 0:
            modified = True
            changes.append(f"{f.rule_id}: Renamed variable '{var_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_naming_argument(content: str, findings: list[Finding], expected_prefix: str) -> dict:
    """Generic argument naming fix — prepend expected direction prefix."""
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        arg_name = _extract_name_from_finding(f, "argument")
        if not arg_name or arg_name in seen:
            continue
        seen.add(arg_name)

        if arg_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + arg_name
        new_content, count = _rename_in_xaml(new_content, arg_name, new_name)
        if count > 0:
            modified = True
            changes.append(f"{f.rule_id}: Renamed argument '{arg_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG: Naming Convention Fixes ──────────────────────────────

def _fix_st_nmg_001(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-001: Variables Naming Convention — add type prefixes."""
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        var_name = _extract_name_from_finding(f, "variable")
        if not var_name or var_name in seen:
            continue
        seen.add(var_name)

        # Determine expected prefix from the variable type mentioned in description
        expected_prefix = "str_"  # default
        desc_lower = f.description.lower()
        if "int32" in desc_lower or "int64" in desc_lower or "integer" in desc_lower:
            expected_prefix = "int_"
        elif "boolean" in desc_lower or "bool" in desc_lower:
            expected_prefix = "bln_"
        elif "datatable" in desc_lower:
            expected_prefix = "dt_"
        elif "datetime" in desc_lower:
            expected_prefix = "dtm_"
        elif "timespan" in desc_lower:
            expected_prefix = "ts_"
        elif "array" in desc_lower or "list" in desc_lower:
            expected_prefix = "arr_"
        elif "dictionary" in desc_lower:
            expected_prefix = "dic_"

        if var_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + var_name
        new_content, count = _rename_in_xaml(new_content, var_name, new_name)
        if count > 0:
            modified = True
            changes.append(f"ST-NMG-001: Renamed variable '{var_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_st_nmg_002(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-002: Arguments Naming Convention — add direction prefixes."""
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        arg_name = _extract_name_from_finding(f, "argument")
        if not arg_name or arg_name in seen:
            continue
        seen.add(arg_name)

        # Determine direction prefix from description
        expected_prefix = "in_"  # default
        desc_lower = f.description.lower()
        if "inout" in desc_lower or "io_" in desc_lower:
            expected_prefix = "io_"
        elif "out" in desc_lower and "inout" not in desc_lower:
            expected_prefix = "out_"

        if arg_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + arg_name
        new_content, count = _rename_in_xaml(new_content, arg_name, new_name)
        if count > 0:
            modified = True
            changes.append(f"ST-NMG-002: Renamed argument '{arg_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_st_nmg_009(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-009: Datatable Variable Prefix — add dt_ prefix."""
    return _fix_naming_variable(content, findings, "dt_", "DataTable")


def _fix_st_nmg_011(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-011: Datatable Argument Prefix — add dt_ prefix."""
    return _fix_naming_argument(content, findings, "dt_")


# ── No-op handlers (manual fix required) ─────────────────────────

def _noop_fix(content: str, findings: list[Finding]) -> dict:
    """No-op fix for rules that require manual intervention."""
    return {"modified": False, "content": content, "changes": []}


# ── Handler registry ───────────────────────────────────────────────
_FIX_HANDLERS: dict[str, Callable] = {
    # Naming — auto-fixable (renaming only)
    "ST-NMG-001": _fix_st_nmg_001,
    "ST-NMG-002": _fix_st_nmg_002,
    "ST-NMG-009": _fix_st_nmg_009,
    "ST-NMG-011": _fix_st_nmg_011,
    # Naming — manual fix required
    "ST-NMG-004": _noop_fix,
    "ST-NMG-005": _noop_fix,
    "ST-NMG-006": _noop_fix,
    "ST-NMG-008": _noop_fix,
    "ST-NMG-012": _noop_fix,
    "ST-NMG-016": _noop_fix,
    # Design Best Practices — manual fix required
    "ST-DBP-002": _noop_fix,
    "ST-DBP-003": _noop_fix,
    "ST-DBP-007": _noop_fix,
    "ST-DBP-020": _noop_fix,
    "ST-DBP-023": _noop_fix,
    "ST-DBP-024": _noop_fix,
    "ST-DBP-025": _noop_fix,
    "ST-DBP-026": _noop_fix,
    "ST-DBP-027": _noop_fix,
    "ST-DBP-028": _noop_fix,
    # UI Automation — manual fix required
    "UI-DBP-006": _noop_fix,
    "UI-DBP-013": _noop_fix,
    "UI-DBP-030": _noop_fix,
    "UI-PRR-004": _noop_fix,
    "UI-REL-001": _noop_fix,
    "UI-SEC-004": _noop_fix,
    "UI-SEC-010": _noop_fix,
    # Performance — manual fix required
    "UI-PRR-001": _noop_fix,
    "UI-PRR-002": _noop_fix,
    "UI-PRR-003": _noop_fix,
    # Reliability — manual fix required
    "GEN-REL-001": _noop_fix,
    # Security — manual fix required
    "UX-DBP-029": _noop_fix,
    # General — manual fix required
    "GEN-001": _noop_fix,
    "GEN-002": _noop_fix,
    "GEN-003": _noop_fix,
    "GEN-004": _noop_fix,
    "GEN-005": _noop_fix,
}
