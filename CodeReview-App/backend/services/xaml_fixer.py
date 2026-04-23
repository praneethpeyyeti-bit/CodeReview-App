"""
XAML Auto-Fix Engine
Applies fixes for deterministic rules found during code review.
Returns original and modified content with a list of changes applied.
"""

import html
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from typing import Callable
from xml.sax.saxutils import escape as _xml_escape

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

def fix_xaml(xml_content: str, findings: list[Finding]) -> dict:
    """
    Apply fixes to XAML content based on findings.

    Returns:
        {
            "original_content": str,
            "modified_content": str,
            "changes_applied": list[str],
            "delete": bool,        # True when the whole file should be removed
        }
    """
    changes: list[str] = []
    content = xml_content
    delete = False

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
            if result.get("delete"):
                delete = True
                changes.extend(result.get("changes", []))
                # Deletion overrides further per-file edits; stop processing this file.
                break
            if result["modified"]:
                content = result["content"]
                changes.extend(result["changes"])

    return {
        "original_content": xml_content,
        "modified_content": content,
        "changes_applied": changes,
        "delete": delete,
    }


def _rule_priority(rule_id: str) -> int:
    """Lower number = higher priority."""
    if rule_id.startswith("UI-SEC") or rule_id == "UX-DBP-029":
        return 0  # Security — CRITICAL
    # Removal rules must run before renames so that stale references don't
    # survive. Argument defaults (ST-NMG-012), unused variables (GEN-001),
    # and shadow declarations (ST-NMG-005/006) all delete declarations whose
    # names would otherwise be rewritten by ST-NMG-001/002/010.
    if rule_id in ("ST-NMG-012", "GEN-001", "ST-NMG-005", "ST-NMG-006"):
        return 1
    if rule_id.startswith("ST-DBP"):
        return 1  # Design Best Practices
    if rule_id.startswith("ST-NMG"):
        return 2  # Naming (renames)
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
      4. Inside complex expressions:      [CInt(oldName)], [oldName + other]
      5. Argument key bindings:           Key="oldName"  (InvokeWorkflow arguments)
      6. Default values with variable:    Default="[oldName]"
      7. Attribute-form property refs:    this:Main.oldName="value" on the root
         Activity element (UiPath stores argument defaults this way).

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
    pattern = re.compile(
        r'(\[(?:[^\[\]])*?)'
        rf'\b{re.escape(old_name)}\b'
        r'((?:[^\[\]])*?\])'
    )
    content, n = pattern.subn(rf'\g<1>{new_name}\g<2>', content)
    count += n

    # 4. Attribute-form property references on the Activity root:
    #    e.g. this:Main.oldName="default value"
    #    These flatten the property element syntax into an attribute, and
    #    reference the argument by class-name.argName. When the argument is
    #    renamed, the attribute suffix must track the new name or UiPath
    #    Studio raises "The property (oldName) is either invalid or not defined".
    pattern = re.compile(
        r'(\s[\w]+:[\w]+\.)' + re.escape(old_name) + r'(=")'
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
    """ST-NMG-011: DataTable Argument Naming — add direction prefix.

    Per UiPath convention, arguments use direction prefixes (in_/out_/io_) only.
    """
    direction_prefixes = {"In": "in_", "Out": "out_", "InOut": "io_"}
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        arg_name = _extract_name_from_finding(f, "argument")
        if not arg_name or arg_name in seen:
            continue
        seen.add(arg_name)

        # Determine direction from description (e.g. "direction: In", "direction: Out")
        desc_lower = f.description.lower()
        if "inout" in desc_lower:
            expected = "io_"
        elif "out" in desc_lower:
            expected = "out_"
        else:
            expected = "in_"

        if arg_name.startswith(expected):
            continue

        new_name = expected + arg_name
        new_content, count = _rename_in_xaml(new_content, arg_name, new_name)
        if count > 0:
            modified = True
            changes.append(f"ST-NMG-011: Renamed DataTable argument '{arg_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── UI-PRR-001: Set SimulateClick="True" on Click activities ──────

def _fix_ui_prr_001(content: str, findings: list[Finding]) -> dict:
    """UI-PRR-001: Set SimulateClick=True on Click/NClick activities."""
    modified = False
    changes = []
    new_content = content

    # Add SimulateClick="True" where missing or set to False/{x:Null}
    # Match Click/NClick elements that don't already have SimulateClick="True"
    pattern = re.compile(
        r'(<(?:\w+:)?(?:Click|NClick)\b)'   # opening tag
        r'((?:(?!SimulateClick)[^>])*)'      # attributes before (no SimulateClick yet)
        r'(?:SimulateClick="(?:False|\{x:Null\})")?'  # optional False/{x:Null} to replace
        r'([^>]*>)',                          # rest of tag
    )

    def replacer(m):
        tag_start = m.group(1)
        before = m.group(2)
        after = m.group(3)
        full = m.group(0)
        if 'SimulateClick="True"' in full:
            return full
        # Remove existing False/{x:Null} and add True
        cleaned = re.sub(r'\s*SimulateClick="[^"]*"', '', full)
        # Insert attribute before the closing > or />
        if cleaned.endswith("/>"):
            return cleaned[:-2] + ' SimulateClick="True" />'
        elif cleaned.endswith(">"):
            return cleaned[:-1] + ' SimulateClick="True">'
        return cleaned

    new_content = pattern.sub(replacer, content)
    if new_content != content:
        count = content.count("<Click ") + content.count("<NClick ") + content.count("<ui:Click ") + content.count("<ui:NClick ")
        modified = True
        changes.append(f"UI-PRR-001: Set SimulateClick=True on Click activities")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── UI-PRR-002: Set SimulateType="True" on TypeInto activities ────

def _fix_ui_prr_002(content: str, findings: list[Finding]) -> dict:
    """UI-PRR-002: Set SimulateType=True on TypeInto/NTypeInto activities."""
    modified = False
    changes = []
    new_content = content

    pattern = re.compile(
        r'(<(?:\w+:)?(?:TypeInto|NTypeInto)\b)'
        r'((?:(?!SimulateType)[^>])*)'
        r'(?:SimulateType="(?:False|\{x:Null\})")?'
        r'([^>]*>)',
    )

    def replacer(m):
        full = m.group(0)
        if 'SimulateType="True"' in full:
            return full
        cleaned = re.sub(r'\s*SimulateType="[^"]*"', '', full)
        if cleaned.endswith("/>"):
            return cleaned[:-2] + ' SimulateType="True" />'
        elif cleaned.endswith(">"):
            return cleaned[:-1] + ' SimulateType="True">'
        return cleaned

    new_content = pattern.sub(replacer, content)
    if new_content != content:
        modified = True
        changes.append(f"UI-PRR-002: Set SimulateType=True on TypeInto activities")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── GEN-001: Remove unused variable declarations ─────────────────

def _fix_gen_001(content: str, findings: list[Finding]) -> dict:
    """GEN-001: Remove unused Variable declarations from XAML."""
    modified = False
    changes = []
    new_content = content

    for f in findings:
        var_name = _extract_name_from_finding(f, "variable")
        if not var_name:
            continue

        # Remove the <Variable ... Name="varName" ... /> line
        # Handles both self-closing and multi-line Variable elements
        pattern = re.compile(
            r'\s*<Variable\b[^>]*\bName="' + re.escape(var_name) + r'"[^>]*/>\s*',
            re.DOTALL,
        )
        new_content, n = pattern.subn('\n', new_content)
        if n > 0:
            modified = True
            changes.append(f"GEN-001: Removed unused variable '{var_name}'")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── Name shortening helper (used by ST-NMG-008 / ST-NMG-016) ────────

_NAME_PREFIXES = (
    "in_str_", "in_int_", "in_bln_", "in_dt_", "in_dtm_", "in_ts_", "in_arr_", "in_dic_",
    "out_str_", "out_int_", "out_bln_", "out_dt_", "out_dtm_", "out_ts_", "out_arr_", "out_dic_",
    "io_str_", "io_int_", "io_bln_", "io_dt_", "io_dtm_", "io_ts_", "io_arr_", "io_dic_",
    "in_", "out_", "io_",
    "str_", "int_", "bln_", "dt_", "dtm_", "ts_", "arr_", "dic_",
)


def _shorten_name(name: str, limit: int = 28) -> str | None:
    """Shorten a name to <= limit chars while preserving the prefix and meaning.

    Strategy: keep the known prefix, split the body into camelCase/underscore
    words, and drop middle words until it fits. Returns None if the name is
    already short enough or can't be shortened meaningfully.
    """
    if len(name) <= limit:
        return None

    prefix = ""
    for p in _NAME_PREFIXES:
        if name.startswith(p):
            prefix = p
            break

    body = name[len(prefix):]
    budget = limit - len(prefix)
    if budget < 4:
        return None  # No room for meaningful body

    # Split body into camelCase words / alnum tokens
    words = re.findall(r"[A-Z][a-z0-9]*|[a-z]+[0-9]*|\d+", body)
    if len(words) <= 1:
        short = body[:budget]
    else:
        # Drop middle words one at a time until it fits
        while sum(len(w) for w in words) > budget and len(words) > 2:
            words.pop(len(words) // 2)
        short = "".join(words)
        if len(short) > budget:
            short = short[:budget]

    short = short.rstrip("_")
    new_name = prefix + short
    if new_name == name or not short:
        return None
    return new_name


# ── ST-NMG-005: Remove inner shadow variable declarations ──────────

def _fix_st_nmg_005(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-005: Keep the outermost Variable declaration, remove shadows.

    A variable declared in multiple scopes shadows itself. We keep the first
    occurrence (outermost in document order) and remove the rest. References
    in inner scopes resolve to the outer variable instead.
    """
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        name = _extract_name_from_finding(f, "variable")
        if not name or name in seen:
            continue
        seen.add(name)

        pattern = re.compile(
            r'\s*<Variable\b[^>]*\bName="' + re.escape(name) + r'"[^>]*/>\s*',
            re.DOTALL,
        )
        matches = list(pattern.finditer(new_content))
        if len(matches) < 2:
            continue

        # Remove all but the first, from end to preserve offsets
        removed = 0
        for m in reversed(matches[1:]):
            new_content = new_content[:m.start()] + "\n" + new_content[m.end():]
            removed += 1
        if removed:
            modified = True
            changes.append(
                f"ST-NMG-005: Removed {removed} inner-scope shadow declaration(s) of '{name}'"
            )

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG-006: Remove variable that collides with an argument ─────

def _fix_st_nmg_006(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-006: Remove the variable; keep only the argument.

    When a variable and argument share a name the variable silently wins
    inside its scope. Removing the variable makes references resolve to the
    argument (the usual intent).
    """
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        name = _extract_name_from_finding(f, "variable")
        if not name or name in seen:
            continue
        seen.add(name)

        pattern = re.compile(
            r'\s*<Variable\b[^>]*\bName="' + re.escape(name) + r'"[^>]*/>\s*',
            re.DOTALL,
        )
        new_content, n = pattern.subn("\n", new_content)
        if n > 0:
            modified = True
            changes.append(
                f"ST-NMG-006: Removed variable '{name}' (conflicted with argument of the same name)"
            )

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG-010: PascalCase convention for variable/argument bodies ─

def _split_prefix_for_rename(name: str) -> tuple[str, str]:
    for p in _NAME_PREFIXES:
        if name.startswith(p):
            return p, name[len(p):]
    return "", name


try:
    import wordninja as _wordninja
except ImportError:
    _wordninja = None


def _split_concat_words(single_word: str) -> list[str]:
    """Split a lowercase concatenation into component words using wordninja.

    Returns the single word as-is if wordninja is unavailable or if it fails
    to produce a meaningful split.
    """
    if _wordninja is None or not single_word:
        return [single_word] if single_word else []
    parts = _wordninja.split(single_word.lower())
    # Reject if the splitter produced no useful boundary (still just one token
    # that equals the input), otherwise keep the split.
    if not parts:
        return [single_word]
    return parts


def _to_pascal_case(body: str) -> str:
    """Convert snake_case / camelCase / concatenated-lowercase body to PascalCase.

    Rules:
      1. Split on underscores first (snake_case).
      2. If only one token remains, further split case boundaries we already
         have (a lowercase run followed by an uppercase letter).
      3. If the result is still a single token >= 10 chars with no internal
         case change, delegate to wordninja to split into English words.
      4. Join each component with its first letter capitalized.
    """
    if not body:
        return body

    # Split on underscores first
    parts = [p for p in body.split("_") if p]
    if not parts:
        return body

    # Split camelCase boundaries within each part (e.g. "fooBarBaz" -> foo,Bar,Baz)
    expanded: list[str] = []
    for part in parts:
        cam_split = re.findall(r"[A-Z]+[a-z0-9]*|[a-z]+[0-9]*|\d+", part)
        if cam_split:
            expanded.extend(cam_split)
        else:
            expanded.append(part)

    # If we still have a long single token with no word boundaries, use wordninja
    if len(expanded) == 1 and len(expanded[0]) >= 10:
        tail = expanded[0][1:]
        if not any(c.isupper() or c.isdigit() for c in tail):
            words = _split_concat_words(expanded[0])
            if len(words) > 1:
                expanded = words

    return "".join(p[0].upper() + p[1:] for p in expanded if p)


def _body_is_pascal(body: str) -> bool:
    """True when a name's body is proper PascalCase.

    Mirrors the reviewer's _body_is_pascal_case: long all-lowercase bodies
    (no internal uppercase or digits) are NOT considered PascalCase, since
    they're concatenated words that the auto-fix should still split.
    """
    if not body:
        return True
    if "_" in body:
        return False
    if not body[0].isalpha() or not body[0].isupper():
        return False
    if len(body) >= 10:
        tail = body[1:]
        if not any(c.isupper() or c.isdigit() for c in tail):
            return False
    return True


def _fix_st_nmg_010(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-010: Rename variables/arguments so the body is PascalCase.

    Re-scans the *current* XAML for all variable/argument declarations (so it
    composes correctly with earlier fixers like ST-NMG-001/002 that may have
    already prepended prefixes). For any name whose post-prefix body isn't
    PascalCase, renames across all XAML locations.
    """
    if not findings:
        return {"modified": False, "content": content, "changes": []}

    modified = False
    changes = []
    new_content = content
    seen: set[str] = set()

    # Discover current variable + argument declarations from the XAML itself
    current_names: set[str] = set()
    for pat in (
        r'<Variable\b[^>]*\bName="([^"]+)"',
        r'<x:Property\b[^>]*\bName="([^"]+)"',
    ):
        for m in re.finditer(pat, new_content):
            current_names.add(m.group(1))

    for name in sorted(current_names):
        if name in seen:
            continue
        seen.add(name)
        prefix, body = _split_prefix_for_rename(name)
        if _body_is_pascal(body):
            continue
        new_body = _to_pascal_case(body)
        if not new_body or new_body == body:
            continue
        new_name = prefix + new_body
        if new_name == name:
            continue
        new_content, count = _rename_in_xaml(new_content, name, new_name)
        if count > 0:
            modified = True
            changes.append(
                f"ST-NMG-010: Renamed '{name}' -> '{new_name}' ({count} location(s))"
            )

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG-008: Shorten overlong variable names ────────────────────

def _fix_st_nmg_008(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-008: Shorten variable names that exceed the length limit."""
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        name = _extract_name_from_finding(f, "variable")
        if not name or name in seen:
            continue
        seen.add(name)

        short = _shorten_name(name, limit=28)
        if not short:
            continue
        new_content, count = _rename_in_xaml(new_content, name, short)
        if count > 0:
            modified = True
            changes.append(
                f"ST-NMG-008: Shortened variable '{name}' -> '{short}' ({count} location(s))"
            )

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG-012: Remove default values for Out/InOut arguments ──────

def _fix_st_nmg_012(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-012: Remove default values for the flagged In arguments.

    UiPath serializes argument defaults two ways; we strip both:
      1. ELEMENT-FORM: `<this:WorkflowName.argName>...</this:WorkflowName.argName>`
         — a property-element block outside the main body.
      2. ATTRIBUTE-FORM: a flattened attribute on the root `<Activity ...>`
         like `this:WorkflowName.argName="value"`. Leaving these behind after
         the argument is renamed causes UiPath Studio to error with
         "The property (argName) is either invalid or not defined."
    """
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        name = _extract_name_from_finding(f, "argument")
        if not name or name in seen:
            continue
        seen.add(name)
        removed_any = False

        # 1. Element-form default block
        pattern = re.compile(
            r"\s*<[\w:]+\." + re.escape(name) + r">.*?</[\w:]+\." + re.escape(name) + r">\s*",
            re.DOTALL,
        )
        new_content, n = pattern.subn("\n", new_content)
        if n > 0:
            removed_any = True

        # 2. Attribute-form default on the Activity root
        attr_pattern = re.compile(
            r'\s[\w]+:[\w]+\.' + re.escape(name) + r'="[^"]*"'
        )
        new_content, n2 = attr_pattern.subn("", new_content)
        if n2 > 0:
            removed_any = True

        if removed_any:
            modified = True
            changes.append(
                f"ST-NMG-012: Removed default value for argument '{name}'"
            )

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG-016: Shorten overlong argument names ────────────────────

def _fix_st_nmg_016(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-016: Shorten argument names that exceed the length limit."""
    modified = False
    changes = []
    new_content = content
    seen = set()

    for f in findings:
        name = _extract_name_from_finding(f, "argument")
        if not name or name in seen:
            continue
        seen.add(name)

        short = _shorten_name(name, limit=28)
        if not short:
            continue
        new_content, count = _rename_in_xaml(new_content, name, short)
        if count > 0:
            modified = True
            changes.append(
                f"ST-NMG-016: Shortened argument '{name}' -> '{short}' ({count} location(s))"
            )

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-DBP-023: Mark empty workflow for deletion ──────────────────

def _fix_st_dbp_023(content: str, findings: list[Finding]) -> dict:
    """ST-DBP-023: Mark the file for deletion.

    Empty workflows have no meaningful activities. The fix is to delete the
    whole file. This handler signals the deletion via the `delete` key in the
    result; the orchestrator in main.py turns that into a filesystem delete
    on accept.
    """
    if not findings:
        return {"modified": False, "content": content, "changes": []}
    return {
        "modified": False,
        "content": content,
        "changes": [f"ST-DBP-023: Marked empty workflow for deletion ({len(findings)} finding(s))"],
        "delete": True,
    }


# ── GEN-REL-001 / GEN-003: Remove empty Sequence elements ─────────

def _fix_gen_rel_001(content: str, findings: list[Finding]) -> dict:
    """GEN-REL-001 / GEN-003: Remove empty Sequence elements.

    Handles both forms:
      1. Self-closing:        <Sequence DisplayName="X" ... />
      2. Open-tag empty:      <Sequence DisplayName="X" ...>[metadata only]</Sequence>

    For form 2 the inner content is considered "empty" when it contains only
    metadata wrappers (ViewState, Dictionary, Collection, or property-element
    pairs) and no real activity elements.
    """
    if not findings:
        return {"modified": False, "content": content, "changes": []}

    # Collect flagged DisplayNames to scope the removal
    flagged = set()
    for f in findings:
        ap = f.activity_path or ""
        if ap:
            flagged.add(ap)
        m = re.search(r"Sequence '([^']+)'", f.description)
        if m:
            flagged.add(m.group(1))
    if not flagged:
        return {"modified": False, "content": content, "changes": []}

    def _inner_is_metadata_only(inner: str) -> bool:
        stripped = re.sub(
            r"<sap:WorkflowViewStateService\.ViewState>.*?</sap:WorkflowViewStateService\.ViewState>",
            "", inner, flags=re.DOTALL,
        )
        stripped = re.sub(r"<scg:Dictionary\b[^>]*>.*?</scg:Dictionary>", "", stripped, flags=re.DOTALL)
        stripped = re.sub(r"<sco:Collection\b[^>]*>.*?</sco:Collection>", "", stripped, flags=re.DOTALL)
        stripped = re.sub(r"<[\w:]+\.[\w.:]+\b[^>]*>.*?</[\w:]+\.[\w.:]+>", "", stripped, flags=re.DOTALL)
        stripped = stripped.strip()
        return not re.search(r"<(?!/)(?!\?)[\w:]+(?!\.)\b", stripped)

    new_content = content
    changes: list[str] = []

    for name in flagged:
        escaped = _xml_escape(name, {'"': "&quot;"})
        name_removed = False

        # Form 1: self-closing
        self_closing = re.compile(
            r"\s*<(?:\w+:)?[NS]equence\b(?=[^>]*\bDisplayName=\""
            + re.escape(escaped)
            + r"\")[^>]*/>\s*",
            re.DOTALL,
        )
        new_content, n1 = self_closing.subn("\n", new_content)
        if n1 > 0:
            name_removed = True

        # Form 2: open-tag empty. Non-greedy to the next </Sequence>; confirm
        # inner is metadata-only before removing.
        open_close = re.compile(
            r"(\s*)<(?:\w+:)?[NS]equence\b(?=[^>]*\bDisplayName=\""
            + re.escape(escaped)
            + r"\")[^>]*>(.*?)</(?:\w+:)?[NS]equence>\s*",
            re.DOTALL,
        )

        def _maybe_drop(m: re.Match) -> str:
            inner = m.group(2)
            if _inner_is_metadata_only(inner):
                return "\n"
            return m.group(0)

        new_text, n_open = open_close.subn(_maybe_drop, new_content)
        if new_text != new_content:
            name_removed = True
        new_content = new_text

        if name_removed:
            changes.append(f"GEN-REL-001: Removed empty Sequence '{name}'")

    if not changes:
        return {"modified": False, "content": content, "changes": []}

    return {"modified": True, "content": new_content, "changes": changes}


# ═══════════════════════════════════════════════════════════════════
# HYBRID FIXES: Use ET to find elements, string ops to modify content.
# Never re-serialize the full document (ET.tostring drops xmlns decls).
# ═══════════════════════════════════════════════════════════════════


# ── ST-NMG-004: Rename duplicate DisplayNames with selector-derived labels ──

_SELECTOR_PRIORITY = ("aaname", "innertext", "title", "name")
_GENERIC_DISPLAY_NAMES = {
    "Sequence", "Assign", "If", "Flowchart", "FlowDecision", "FlowStep",
    "Body", "TryCatch", "Try", "Catch", "Finally",
}


def _local_tag(tag: str) -> str:
    return tag.split("}")[-1] if "}" in tag else tag


def _extract_selector_descriptor(selector: str) -> str | None:
    """Pick the most meaningful descriptor from a UiPath selector string.

    Prefers aaname > innertext > title > name on the most specific (last) node.
    Falls back to regex when the selector isn't valid XML.
    """
    if not selector:
        return None
    sel = html.unescape(selector).strip()
    if not sel:
        return None

    # Try structured parse first
    try:
        root = ET.fromstring(f"<root>{sel}</root>")
        nodes = list(root)
        for node in reversed(nodes):
            for key in _SELECTOR_PRIORITY:
                val = (node.attrib.get(key) or "").strip()
                if val and val not in ("*",) and "*" not in val:
                    return val
    except ET.ParseError:
        pass

    # Regex fallback — pick the last occurrence of the highest-priority key
    for key in _SELECTOR_PRIORITY:
        matches = re.findall(rf"{key}\s*=\s*['\"]([^'\"]+)['\"]", sel)
        for val in reversed(matches):
            val = val.strip()
            if val and val not in ("*",) and "*" not in val:
                return val
    return None


def _sanitize_descriptor(descriptor: str) -> str:
    """Trim whitespace, collapse newlines, cap length so names stay readable."""
    d = re.sub(r"\s+", " ", descriptor).strip()
    if len(d) > 40:
        d = d[:37].rstrip() + "..."
    return d


def _build_unique_displayname(
    type_name: str,
    descriptor: str | None,
    used_names: set[str],
    fallback_counter: int,
) -> str:
    """Build a unique meaningful display name, with counter fallback."""
    if descriptor:
        desc = _sanitize_descriptor(descriptor)
        if desc:
            candidate = f"{type_name} '{desc}'"
            if candidate not in used_names:
                return candidate
            i = 2
            while f"{candidate} ({i})" in used_names:
                i += 1
            return f"{candidate} ({i})"
    # No selector descriptor → numeric suffix
    base = f"{type_name} ({fallback_counter})"
    i = fallback_counter
    while base in used_names:
        i += 1
        base = f"{type_name} ({i})"
    return base


def _find_activity_selector(elem: ET.Element) -> str:
    """Look for a Selector attribute on the activity or its Target descendants."""
    direct = elem.attrib.get("Selector") or ""
    if direct:
        return direct
    for child in elem:
        local = _local_tag(child.tag)
        if local == "Target" or local.endswith(".Target"):
            sel = child.attrib.get("Selector") or ""
            if sel:
                return sel
            for gc in child:
                if _local_tag(gc.tag) == "Target":
                    sel = gc.attrib.get("Selector") or ""
                    if sel:
                        return sel
    return ""


def _fix_st_nmg_004(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-004: Rename duplicate DisplayNames.

    Strategy:
      1. Parse XAML with ET; collect activities in document order with their
         DisplayName + selector.
      2. Group by DisplayName; keep the first occurrence as-is and rename the
         rest using a selector-derived descriptor when available, else a
         numeric suffix.
      3. Apply positional regex replacements on the raw text so the Nth
         `DisplayName="X"` occurrence is replaced in place. Never re-serialize.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"modified": False, "content": content, "changes": []}

    # Walk document order, collect (display_name, type_name, selector)
    activities: list[tuple[str, str, str]] = []
    for elem in root.iter():
        dn = elem.attrib.get("DisplayName")
        if dn is None:
            continue
        type_name = _local_tag(elem.tag)
        if dn in _GENERIC_DISPLAY_NAMES:
            continue
        selector = _find_activity_selector(elem)
        activities.append((dn, type_name, selector))

    # Group activity indices by display name
    groups: dict[str, list[int]] = defaultdict(list)
    for i, (dn, _, _) in enumerate(activities):
        groups[dn].append(i)

    # Only act on names that appear >1 time (matching the reviewer's definition)
    duplicates = {name: idxs for name, idxs in groups.items() if len(idxs) > 1}
    if not duplicates:
        return {"modified": False, "content": content, "changes": []}

    # Restrict to names flagged by the reviewer (safer + avoids unintended renames)
    flagged_names: set[str] = set()
    for f in findings:
        # activity_path format: "DisplayName: {name}"
        if f.activity_path.startswith("DisplayName:"):
            flagged_names.add(f.activity_path.split(":", 1)[1].strip())
        else:
            # Description: "Display name '{name}' is used..."
            m = re.search(r"Display name '([^']+)'", f.description)
            if m:
                flagged_names.add(m.group(1))
    if flagged_names:
        duplicates = {n: idxs for n, idxs in duplicates.items() if n in flagged_names}

    if not duplicates:
        return {"modified": False, "content": content, "changes": []}

    used_names: set[str] = set(groups.keys())
    replacements: list[tuple[int, int, str, str]] = []  # start, end, new_str, msg

    for name, idxs in duplicates.items():
        # Match the Nth DisplayName="{name}" in raw text. Use the attribute's
        # XML-escaped form to align with the file.
        escaped_attr = _xml_escape(name, {'"': '&quot;'})
        pattern = re.compile(r'\bDisplayName="' + re.escape(escaped_attr) + r'"')
        matches = list(pattern.finditer(content))
        if len(matches) < len(idxs):
            # Raw text has fewer matches than ET found — skip to stay safe.
            continue

        # Keep occurrence #1 (idxs[0]); rename occurrences #2..N.
        for rank, idx in enumerate(idxs[1:], start=2):
            _, type_name, selector = activities[idx]
            descriptor = _extract_selector_descriptor(selector)
            new_name = _build_unique_displayname(type_name, descriptor, used_names, rank)
            used_names.add(new_name)
            escaped_new = _xml_escape(new_name, {'"': '&quot;'})
            m = matches[rank - 1]
            replacements.append((
                m.start(),
                m.end(),
                f'DisplayName="{escaped_new}"',
                f"ST-NMG-004: Renamed duplicate DisplayName '{name}' -> '{new_name}' (occurrence #{rank})",
            ))

    if not replacements:
        return {"modified": False, "content": content, "changes": []}

    # Apply in reverse so earlier offsets stay valid
    replacements.sort(key=lambda r: r[0], reverse=True)
    new_content = content
    for start, end, new_str, _ in replacements:
        new_content = new_content[:start] + new_str + new_content[end:]

    # Show changes in document order (reverse of apply order)
    changes = [msg for _, _, _, msg in sorted(replacements, key=lambda r: r[0])]
    return {"modified": True, "content": new_content, "changes": changes}


def _fix_st_dbp_003(content: str, findings: list[Finding]) -> dict:
    """ST-DBP-003: Insert a LogMessage inside empty Catch blocks.

    UiPath always wraps catch handler content in a Sequence:
      <Catch><ActivityAction>
        <ActivityAction.Argument><DelegateInArgument Name="exception"/></ActivityAction.Argument>
        <Sequence DisplayName="Body">[metadata only]</Sequence>
      </ActivityAction></Catch>

    We walk the document with ET to find empty Catches + their exception
    variable names in document order, then do positional raw-text insertion
    inside the Body Sequence — right before its closing tag. ET is only used
    for discovery; string substitution preserves xmlns declarations.
    """
    import uuid
    if not findings:
        return {"modified": False, "content": content, "changes": []}

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"modified": False, "content": content, "changes": []}

    def local(tag: str) -> str:
        return tag.split("}")[-1] if "}" in tag else tag

    # Discover Catch blocks in document order; record (is_empty, exc_var).
    # Skip the full set of non-activity element types: structural containers,
    # metadata primitives (x:Boolean, x:String, etc.), property elements, and
    # view-state / collection wrappers. Otherwise XAML metadata like
    # <x:Boolean x:Key="IsExpanded">True</x:Boolean> inside a Dictionary
    # gets mis-counted as a real activity.
    catches_info: list[tuple[bool, str]] = []
    meta_elements = {
        # Structural workflow / try-catch wrappers
        "ActivityAction", "DelegateInArgument", "DelegateOutArgument",
        "Catch", "Sequence", "NSequence", "Body", "Flowchart",
        # Primitive data types commonly found under ViewState / Dictionary
        "Variable", "Property", "Members", "TextExpression", "Literal",
        "String", "Boolean", "Int32", "Int64", "Double", "Decimal",
        "AssemblyReference", "Collection", "Dictionary",
        "InArgument", "OutArgument", "InOutArgument",
        "WorkflowViewState", "ViewState",
    }
    for elem in root.iter():
        if local(elem.tag) != "Catch":
            continue
        exc_var = "exception"
        activity_count = 0
        for desc in elem.iter():
            dl = local(desc.tag)
            if dl == "DelegateInArgument":
                exc_var = desc.attrib.get("Name", exc_var)
                continue
            if dl in meta_elements:
                continue
            if "." in dl or "ViewState" in dl or "Dictionary" in dl or "Collection" in dl:
                continue
            activity_count += 1
        catches_info.append((activity_count == 0, exc_var))

    if not any(is_empty for is_empty, _ in catches_info):
        return {"modified": False, "content": content, "changes": []}

    # Raw-text enumeration of Catch blocks in the same doc order
    catch_re = re.compile(r"<Catch\b.*?</Catch>", re.DOTALL)
    matches = list(catch_re.finditer(content))
    if len(matches) != len(catches_info):
        return {"modified": False, "content": content, "changes": []}

    # Match the inner body Sequence of an ActivityAction (allow optional
    # ViewState/Dictionary metadata but *no* real activities). Inserts
    # a LogMessage right before the closing </Sequence>.
    body_seq_re = re.compile(
        r"(</ActivityAction\.Argument>\s*<(?:\w+:)?[NS]equence\b[^>]*>)"  # 1: open through Sequence
        r"(.*?)"                                                           # 2: inner content
        r"(</(?:\w+:)?[NS]equence>\s*</ActivityAction>)",                 # 3: close Sequence + ActivityAction
        re.DOTALL,
    )

    def body_is_empty(inner: str) -> bool:
        # Strip ViewState and Dictionary blocks
        stripped = re.sub(
            r"<sap:WorkflowViewStateService\.ViewState>.*?</sap:WorkflowViewStateService\.ViewState>",
            "", inner, flags=re.DOTALL,
        )
        stripped = re.sub(r"<scg:Dictionary\b[^>]*>.*?</scg:Dictionary>", "", stripped, flags=re.DOTALL)
        stripped = re.sub(r"<sco:Collection\b[^>]*>.*?</sco:Collection>", "", stripped, flags=re.DOTALL)
        # Strip any remaining property-element pairs (tag names containing a dot)
        stripped = re.sub(r"<[\w:]+\.[\w.:]+\b[^>]*>.*?</[\w:]+\.[\w.:]+>", "", stripped, flags=re.DOTALL)
        stripped = stripped.strip()
        # Any remaining opening element that's not a property-element is a real activity
        return not re.search(r"<(?!/)(?!\?)[\w:]+(?!\.)\b", stripped)

    # Build replacements (start_abs, end_abs, replacement_text) for empty catches
    replacements: list[tuple[int, int, str]] = []
    modified_count = 0
    for (is_empty, exc_var), cm in zip(catches_info, matches):
        if not is_empty:
            continue
        catch_text = cm.group(0)
        body_m = body_seq_re.search(catch_text)
        if not body_m:
            continue
        open_part = body_m.group(1)
        inner = body_m.group(2)
        close_part = body_m.group(3)
        if not body_is_empty(inner):
            continue

        uid = uuid.uuid4().hex[:6]
        indent = "          "
        log_msg = (
            f"{indent}<ui:LogMessage "
            f'DisplayName="Log Error" '
            f'sap:VirtualizedContainerService.HintSize="350,120" '
            f'sap2010:WorkflowViewState.IdRef="LogMessage_AutoFix_{uid}" '
            f'Level="Error" '
            f'Message="[&quot;Exception: &quot; &amp; {exc_var}.GetType().Name '
            f"&amp; &quot; - &quot; &amp; {exc_var}.Message "
            f'&amp; &quot; | Source: &quot; &amp; {exc_var}.Source]" />\n        '
        )

        # Insert the LogMessage between inner metadata and the closing Sequence tag
        # We keep everything in body_m up to the inner, add our LogMessage, then the close.
        replacement = open_part + inner + "\n" + log_msg + close_part
        abs_start = cm.start() + body_m.start()
        abs_end = cm.start() + body_m.end()
        replacements.append((abs_start, abs_end, replacement))
        modified_count += 1

    if not replacements:
        return {"modified": False, "content": content, "changes": []}

    # Apply in reverse order to keep offsets valid
    new_content = content
    for start, end, rep in reversed(replacements):
        new_content = new_content[:start] + rep + new_content[end:]

    # Ensure xmlns:ui is declared on the root Activity element (our injected
    # LogMessage uses the `ui:` prefix). Skip if already present.
    if 'xmlns:ui=' not in new_content:
        new_content = re.sub(
            r"(<Activity\b[^>]*?)(\s*>)",
            r'\1 xmlns:ui="http://schemas.uipath.com/workflow/activities"\2',
            new_content,
            count=1,
        )

    return {
        "modified": True,
        "content": new_content,
        "changes": [f"ST-DBP-003: Added LogMessage to {modified_count} empty Catch block(s)"],
    }


def _fix_ui_prr_001(content: str, findings: list[Finding]) -> dict:
    """UI-PRR-001: Set SimulateClick=True on Click activities.

    Strategy: Find Click/NClick opening tags and add SimulateClick="True"
    if not already present.
    """
    modified = False
    changes = []
    new_content = content

    # Match Click or NClick elements (with namespace prefix) that don't have SimulateClick="True"
    pattern = re.compile(
        r'(<(?:\w+:)?(?:Click|NClick)\b)([^>]*?)(/?>\s*)',
        re.DOTALL,
    )

    fixed = 0
    def replacer(m):
        nonlocal fixed
        tag_open = m.group(1)
        attrs = m.group(2)
        tag_close = m.group(3)

        if 'SimulateClick="True"' in attrs or 'SimulateClick="true"' in attrs:
            return m.group(0)

        # Remove existing SimulateClick="False" or SimulateClick="{x:Null}"
        attrs = re.sub(r'\s*SimulateClick="[^"]*"', '', attrs)
        fixed += 1
        return f'{tag_open}{attrs} SimulateClick="True"{tag_close}'

    new_content = pattern.sub(replacer, new_content)

    if fixed > 0:
        modified = True
        changes.append(f"UI-PRR-001: Set SimulateClick=True on {fixed} Click activity(ies)")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_ui_prr_002(content: str, findings: list[Finding]) -> dict:
    """UI-PRR-002: Set SimulateType=True on TypeInto activities.

    Strategy: Find TypeInto/NTypeInto opening tags and add SimulateType="True"
    if not already present.
    """
    modified = False
    changes = []
    new_content = content

    pattern = re.compile(
        r'(<(?:\w+:)?(?:TypeInto|NTypeInto)\b)([^>]*?)(/?>\s*)',
        re.DOTALL,
    )

    fixed = 0
    def replacer(m):
        nonlocal fixed
        tag_open = m.group(1)
        attrs = m.group(2)
        tag_close = m.group(3)

        if 'SimulateType="True"' in attrs or 'SimulateType="true"' in attrs:
            return m.group(0)

        attrs = re.sub(r'\s*SimulateType="[^"]*"', '', attrs)
        fixed += 1
        return f'{tag_open}{attrs} SimulateType="True"{tag_close}'

    new_content = pattern.sub(replacer, new_content)

    if fixed > 0:
        modified = True
        changes.append(f"UI-PRR-002: Set SimulateType=True on {fixed} TypeInto activity(ies)")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── No-op handlers (manual fix required) ─────────────────────────

def _noop_fix(content: str, findings: list[Finding]) -> dict:
    """No-op fix for rules that require manual intervention."""
    return {"modified": False, "content": content, "changes": []}


# ── Handler registry ───────────────────────────────────────────────
_FIX_HANDLERS: dict[str, Callable] = {
    # Naming — auto-fixable (renaming / declaration removal)
    "ST-NMG-001": _fix_st_nmg_001,
    "ST-NMG-002": _fix_st_nmg_002,
    "ST-NMG-004": _fix_st_nmg_004,
    "ST-NMG-005": _fix_st_nmg_005,
    "ST-NMG-006": _fix_st_nmg_006,
    "ST-NMG-008": _fix_st_nmg_008,
    "ST-NMG-009": _fix_st_nmg_009,
    "ST-NMG-010": _fix_st_nmg_010,
    "ST-NMG-011": _fix_st_nmg_011,
    "ST-NMG-012": _fix_st_nmg_012,
    "ST-NMG-016": _fix_st_nmg_016,
    # Design Best Practices
    "ST-DBP-002": _noop_fix,
    "ST-DBP-003": _fix_st_dbp_003,
    "ST-DBP-007": _noop_fix,
    "ST-DBP-020": _noop_fix,
    "ST-DBP-023": _fix_st_dbp_023,
    "ST-DBP-024": _noop_fix,
    "ST-DBP-025": _noop_fix,
    "ST-DBP-026": _noop_fix,
    "ST-DBP-027": _noop_fix,
    "ST-DBP-028": _noop_fix,
    # UI Automation — manual fix required
    "UI-DBP-006": _noop_fix,
    "UI-DBP-013": _noop_fix,
    "UI-PRR-004": _noop_fix,
    "UI-REL-001": _noop_fix,
    "UI-SEC-004": _noop_fix,
    "UI-SEC-010": _noop_fix,
    # Performance — detection only (adding attributes to Click/TypeInto
    # corrupts property child elements like Click.Target in complex XAML)
    "UI-PRR-001": _noop_fix,
    "UI-PRR-002": _noop_fix,
    "UI-PRR-003": _noop_fix,
    # Reliability — auto-fixable (self-closing empty sequences only)
    "GEN-REL-001": _fix_gen_rel_001,
    # Security — manual fix required
    "UX-DBP-029": _noop_fix,
    # General — auto-fixable
    "GEN-001": _fix_gen_001,
    "GEN-002": _noop_fix,
    "GEN-003": _fix_gen_rel_001,
    "GEN-004": _noop_fix,
    "GEN-005": _noop_fix,
}
