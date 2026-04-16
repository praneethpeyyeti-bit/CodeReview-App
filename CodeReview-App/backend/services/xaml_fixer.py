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
            match = re.search(r"'(\w+)'", desc)
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
            changes.append(f"{f.rule_id}: Renamed variable '{var_name}' -> '{new_name}'")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_naming_argument(content: str, findings: list[Finding], expected_prefix: str) -> dict:
    """Generic argument naming fix — prepend expected direction prefix."""
    modified = False
    changes = []
    new_content = content

    for f in findings:
        desc = f.description
        match = re.search(r"[Aa]rgument\s+['\"](\w+)['\"]", desc)
        if not match:
            match = re.search(r"named\s+['\"](\w+)['\"]", desc)
        if not match:
            match = re.search(r"'(\w+)'", desc)
        if not match:
            continue

        arg_name = match.group(1)
        if arg_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + arg_name
        old_patterns = [
            f'Name="{arg_name}"',
            f"[{arg_name}]",
            f'"{arg_name}"',
        ]
        for old_pat in old_patterns:
            new_pat = old_pat.replace(arg_name, new_name)
            if old_pat in new_content:
                new_content = new_content.replace(old_pat, new_pat)
                modified = True

        if modified:
            changes.append(f"{f.rule_id}: Renamed argument '{arg_name}' -> '{new_name}'")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG: Naming Convention Fixes ──────────────────────────────

def _fix_st_nmg_001(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-001: Variables Naming Convention — add type prefixes."""
    modified = False
    changes = []
    new_content = content

    for f in findings:
        desc = f.description
        match = re.search(r"[Vv]ariable\s+['\"](\w+)['\"]", desc)
        if not match:
            match = re.search(r"'(\w+)'", desc)
        if not match:
            continue

        var_name = match.group(1)

        # Determine expected prefix from the variable type mentioned in description
        expected_prefix = "str_"  # default
        desc_lower = desc.lower()
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
            changes.append(f"ST-NMG-001: Renamed variable '{var_name}' -> '{new_name}'")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_st_nmg_002(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-002: Arguments Naming Convention — add direction prefixes."""
    modified = False
    changes = []
    new_content = content

    for f in findings:
        desc = f.description
        match = re.search(r"[Aa]rgument\s+['\"](\w+)['\"]", desc)
        if not match:
            match = re.search(r"'(\w+)'", desc)
        if not match:
            continue

        arg_name = match.group(1)

        # Determine direction prefix from description
        expected_prefix = "in_"  # default
        desc_lower = desc.lower()
        if "inout" in desc_lower or "io_" in desc_lower:
            expected_prefix = "io_"
        elif "out" in desc_lower and "inout" not in desc_lower:
            expected_prefix = "out_"

        if arg_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + arg_name
        old_patterns = [
            f'Name="{arg_name}"',
            f"[{arg_name}]",
            f'"{arg_name}"',
        ]
        for old_pat in old_patterns:
            new_pat = old_pat.replace(arg_name, new_name)
            if old_pat in new_content:
                new_content = new_content.replace(old_pat, new_pat)
                modified = True

        if modified:
            changes.append(f"ST-NMG-002: Renamed argument '{arg_name}' -> '{new_name}'")

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
