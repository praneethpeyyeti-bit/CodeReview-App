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

    The pipeline runs in priority order (removals before renames, etc.) and
    repeats until no rule produces further changes or the iteration cap is
    reached. After each pass, the current XAML is re-reviewed so rules
    that should cascade — e.g. a prefix rename creating a new length
    violation, or an empty-Sequence removal revealing an unused variable —
    get a fresh set of findings to act on.

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
    current_findings = list(findings)

    max_passes = 5  # cascading rules usually settle in 2–3 passes
    last_content = None
    for pass_num in range(1, max_passes + 1):
        # Group findings by rule_id for batch processing. Sort keys so the
        # execution order within a priority tier is stable across runs.
        findings_by_rule: dict[str, list[Finding]] = {}
        for f in current_findings:
            if f.auto_fixable:
                findings_by_rule.setdefault(f.rule_id, []).append(f)
        ordered_rule_ids = sorted(
            findings_by_rule.keys(),
            key=lambda rid: (_rule_priority(rid), rid),
        )

        pass_modified = False
        for rule_id in ordered_rule_ids:
            handler = _FIX_HANDLERS.get(rule_id)
            if not handler:
                continue
            result = handler(content, findings_by_rule[rule_id])
            if result.get("delete"):
                delete = True
                changes.extend(result.get("changes", []))
                return {
                    "original_content": xml_content,
                    "modified_content": content,
                    "changes_applied": changes,
                    "delete": delete,
                }
            if result["modified"]:
                content = result["content"]
                changes.extend(result["changes"])
                pass_modified = True

        if not pass_modified or content == last_content:
            break  # converged

        last_content = content

        # Re-review the current content so any new violations introduced by
        # this pass (length grew after prefix add, PascalCase split revealed
        # camelCase problem, etc.) get picked up in the next iteration.
        try:
            from services.xaml_parser import parse_xaml_file
            from services.static_reviewer import review_single_file
            file_name = findings[0].file_name if findings else "unknown.xaml"
            zip_entry = findings[0].zip_entry_path if findings else ""
            ctx = parse_xaml_file(file_name, zip_entry, content)
            current_findings = review_single_file(ctx, [file_name])
        except Exception:
            # If re-review fails, fall back to the original findings for the
            # next pass — partial progress is still better than nothing.
            current_findings = list(findings)

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
    # Prefix adders run first among the renames so every downstream rule
    # sees the canonical prefixed form.
    if rule_id in ("ST-NMG-001", "ST-NMG-002", "ST-NMG-009", "ST-NMG-011"):
        return 2
    # Case correction needs to happen BEFORE length shortening so the
    # shortening step can drop whole words from a properly PascalCased name
    # instead of naively truncating a concatenated lowercase run.
    if rule_id == "ST-NMG-010":
        return 3
    # Length shortening runs after case has been normalized.
    if rule_id in ("ST-NMG-008", "ST-NMG-016"):
        return 4
    # Default-name rewrite runs LAST among the NMG rules so its descriptors
    # (which often reference variable/argument names) reflect the final
    # post-rename, post-shorten state of the XAML.
    if rule_id == "ST-NMG-020":
        return 5
    if rule_id.startswith("ST-NMG"):
        return 6
    if rule_id.startswith("UI-"):
        return 7  # UI Automation / Performance / Reliability
    if rule_id.startswith("GEN"):
        return 8  # General
    return 9


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
    """ST-NMG-008: Shorten variable names > length limit.

    Re-scans the *current* XAML for variable declarations so the rule
    composes with earlier fixers — e.g. when ST-NMG-001 adds a `str_` prefix
    and the result is still too long, or when ST-NMG-010 expands a
    concatenated lowercase run into a long PascalCase name.
    """
    if not findings:
        return {"modified": False, "content": content, "changes": []}

    modified = False
    changes: list[str] = []
    new_content = content
    seen: set[str] = set()

    # Discover current variable declarations from the XAML
    current_names: set[str] = set()
    for m in re.finditer(r'<Variable\b[^>]*\bName="([^"]+)"', new_content):
        current_names.add(m.group(1))

    for name in sorted(current_names):
        if name in seen or len(name) <= 30:
            continue
        seen.add(name)
        short = _shorten_name(name, limit=28)
        if not short or short == name:
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
    """ST-NMG-016: Shorten argument names > length limit.

    Re-scans the *current* XAML for `<x:Property>` declarations so the rule
    composes correctly after ST-NMG-002/010/011 apply their renames.
    """
    if not findings:
        return {"modified": False, "content": content, "changes": []}

    modified = False
    changes: list[str] = []
    new_content = content
    seen: set[str] = set()

    current_names: set[str] = set()
    for m in re.finditer(r'<x:Property\b[^>]*\bName="([^"]+)"', new_content):
        current_names.add(m.group(1))

    for name in sorted(current_names):
        if name in seen or len(name) <= 30:
            continue
        seen.add(name)
        short = _shorten_name(name, limit=28)
        if not short or short == name:
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
    # Structural / scaffolding types where duplicate default names are
    # usually noise (matches the reviewer's filter). Assign and If are
    # intentionally NOT here — duplicate Assigns/Ifs are real violations.
    "Sequence", "Flowchart", "FlowDecision", "FlowStep",
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


def _strip_vb_brackets(s: str) -> str:
    """Strip surrounding VB expression brackets and common quote noise."""
    s = s.strip()
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1].strip()
    # Trim outer quoted strings like: "some literal"
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        s = s[1:-1].strip()
    return s


def _extract_activity_descriptor(elem: ET.Element) -> str | None:
    """Derive a meaningful label for an activity.

    Priority ladder:
      1. UI selector (Click, TypeInto, etc.): pick aaname/innertext/title/name
         from the target selector — most descriptive when present.
      2. Activity-type fallback: use the property that best identifies what
         the activity does (e.g. Assign target variable, LogMessage text,
         InvokeWorkflowFile filename, Delay duration, If/While condition).
      3. None: caller will fall back to a numeric suffix.
    """
    # 1. Selector path (UI Automation activities)
    selector = _find_activity_selector(elem)
    if selector:
        desc = _extract_selector_descriptor(selector)
        if desc:
            return desc

    local = _local_tag(elem.tag)

    # 2a. Assign → target variable from <Assign.To><OutArgument>[X]</OutArgument>...
    if local == "Assign":
        for child in elem:
            if _local_tag(child.tag) != "Assign.To":
                continue
            for gc in child:
                text = (gc.text or "").strip()
                if not text:
                    continue
                cleaned = _strip_vb_brackets(text)
                if cleaned:
                    return f"to {cleaned}"
        return None

    # 2b. LogMessage / Log → Level + Message hint
    if local in ("LogMessage", "Log"):
        for attr_name, attr_val in elem.attrib.items():
            if attr_name.split("}")[-1] == "Message" and attr_val:
                cleaned = _strip_vb_brackets(html.unescape(attr_val))
                # Take the first ~30 chars of meaningful content
                if cleaned:
                    return cleaned[:40].strip()
        level = elem.attrib.get("Level", "")
        if level:
            return f"Level={level}"
        return None

    # 2c. WriteLine → Text
    if local == "WriteLine":
        text = elem.attrib.get("Text", "")
        if text:
            return _strip_vb_brackets(html.unescape(text))[:40]
        return None

    # 2d. InvokeWorkflowFile → workflow filename (basename, no extension)
    if local == "InvokeWorkflowFile":
        path = elem.attrib.get("WorkflowFileName", "")
        if path:
            base = path.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            if base.lower().endswith(".xaml"):
                base = base[:-5]
            return base
        return None

    # 2e. Delay → Duration
    if local in ("Delay", "NDelay"):
        dur = elem.attrib.get("Duration", "")
        if dur:
            return _strip_vb_brackets(dur)[:30]
        return None

    # 2f. If / While / DoWhile → Condition
    if local in ("If", "While", "DoWhile"):
        cond = elem.attrib.get("Condition", "")
        if cond:
            return _strip_vb_brackets(html.unescape(cond))[:40]
        return None

    # 2g. ForEach → collection being iterated
    if local in ("ForEach", "ForEachRow"):
        values = elem.attrib.get("Values", "") or elem.attrib.get("DataTable", "")
        if values:
            return _strip_vb_brackets(html.unescape(values))[:40]
        return None

    # 2h. Switch → Expression
    if local == "Switch":
        expr = elem.attrib.get("Expression", "")
        if expr:
            return _strip_vb_brackets(html.unescape(expr))[:40]
        return None

    return None


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

    # Walk document order, collect (effective_dn, type_name, explicit_dn, descriptor)
    # An implicit DisplayName (no attribute set, e.g. Assign activities in
    # Studio default) resolves to the type name — matching what the reviewer
    # sees in ctx.activities. The fixer handles both cases:
    #   - explicit dn: positional replace of the existing attribute
    #   - implicit dn: INSERT a DisplayName attribute into the opening tag
    skip_tags = {
        "Activity", "Members", "Property", "Variable",
        "ActivityAction", "DelegateInArgument", "DelegateOutArgument",
        "InArgument", "OutArgument", "InOutArgument",
        "TextExpression", "Literal", "AssemblyReference",
        "String", "Boolean", "Int32", "Int64", "Double", "Decimal",
        "Collection", "Dictionary",
        "WorkflowViewState", "ViewState",
    }
    activities: list[tuple[str, str, bool, str | None]] = []
    for elem in root.iter():
        type_name = _local_tag(elem.tag)
        if type_name in skip_tags or "." in type_name:
            continue
        if type_name.startswith("x:") or type_name.startswith("sap"):
            continue
        explicit = elem.attrib.get("DisplayName")
        effective_dn = explicit if explicit is not None else type_name
        if effective_dn in _GENERIC_DISPLAY_NAMES:
            continue
        descriptor = _extract_activity_descriptor(elem)
        activities.append((effective_dn, type_name, explicit is not None, descriptor))

    # Group activity indices by display name
    groups: dict[str, list[int]] = defaultdict(list)
    for i, (dn, _, _, _) in enumerate(activities):
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
        # Determine whether this group is explicit (DisplayName set on every
        # occurrence) or implicit (none have it — the reviewer inferred the
        # name from the type). Mixed cases: handle each occurrence per-item.
        type_name = activities[idxs[0]][1]
        group_explicit_flags = [activities[i][2] for i in idxs]

        if all(group_explicit_flags):
            # All explicit: positional replace of existing DisplayName attribute
            escaped_attr = _xml_escape(name, {'"': '&quot;'})
            pattern = re.compile(r'\bDisplayName="' + re.escape(escaped_attr) + r'"')
            matches = list(pattern.finditer(content))
            if len(matches) < len(idxs):
                continue
            for rank, idx in enumerate(idxs[1:], start=2):
                _, _, _, descriptor = activities[idx]
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

        elif not any(group_explicit_flags):
            # All implicit: insert DisplayName attribute into opening tag #2..N
            # of this type. Match only opening tags that lack DisplayName.
            # Require the char after the type name to be whitespace/`/`/`>`.
            # This excludes property elements like <Assign.To> or
            # <Assign.Value> which would otherwise be matched by \b.
            tag_re = re.compile(
                r"<(?P<ns>\w+:)?" + re.escape(type_name) + r"(?=[\s/>])(?P<attrs>[^>]*?)(?P<close>/?>)",
                re.DOTALL,
            )
            raw = [m for m in tag_re.finditer(content) if "DisplayName=" not in m.group("attrs")]
            if len(raw) < len(idxs):
                continue
            for rank, idx in enumerate(idxs[1:], start=2):
                _, _, _, descriptor = activities[idx]
                new_name = _build_unique_displayname(type_name, descriptor, used_names, rank)
                used_names.add(new_name)
                escaped_new = _xml_escape(new_name, {'"': '&quot;'})
                m = raw[rank - 1]
                ns = m.group("ns") or ""
                attrs = m.group("attrs") or ""
                close = m.group("close")
                # Insert DisplayName as the first attribute after the tag name
                sep = " " if attrs and not attrs.startswith(" ") else ""
                new_tag = f'<{ns}{type_name} DisplayName="{escaped_new}"{sep}{attrs}{close}'
                replacements.append((
                    m.start(),
                    m.end(),
                    new_tag,
                    f"ST-NMG-004: Added DisplayName '{new_name}' to duplicate {type_name} (occurrence #{rank})",
                ))
        # mixed: skip for now — rare in practice; can iterate per-item later.

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


_NMG020_STRUCTURAL: frozenset = frozenset({
    "Sequence", "NSequence",
    "Flowchart", "FlowDecision", "FlowStep", "FlowSwitch",
    "Body", "TryCatch", "Try", "Catch", "Finally",
    "Activity", "StateMachine",
})

_NMG020_SKIP_TAGS: frozenset = frozenset({
    "Members", "Property", "Variable",
    "ActivityAction", "DelegateInArgument", "DelegateOutArgument",
    "InArgument", "OutArgument", "InOutArgument",
    "TextExpression", "Literal", "AssemblyReference",
    "String", "Boolean", "Int32", "Int64", "Double", "Decimal",
    "Collection", "Dictionary",
    "WorkflowViewState", "ViewState",
})


def _fix_st_nmg_020(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-020: Rename activities still using the default Studio name.

    For each non-structural activity whose DisplayName is missing or equals
    its type name, derive a meaningful descriptor (selector for UI
    activities, type-specific property for others) and either INSERT or
    REPLACE the DisplayName attribute. Activities with no derivable
    descriptor are skipped (left for manual renaming).
    """
    if not findings:
        return {"modified": False, "content": content, "changes": []}

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"modified": False, "content": content, "changes": []}

    # Walk doc order and collect activities to rename plus their descriptors
    to_rename: list[tuple[str, str, bool, str]] = []  # (type, effective_dn, explicit, descriptor)
    for elem in root.iter():
        tn = _local_tag(elem.tag)
        if tn in _NMG020_STRUCTURAL or tn in _NMG020_SKIP_TAGS or "." in tn:
            continue
        if tn.startswith("x:") or tn.startswith("sap"):
            continue
        explicit_dn = elem.attrib.get("DisplayName")
        is_default = explicit_dn is None or explicit_dn == tn
        if not is_default:
            continue
        descriptor = _extract_activity_descriptor(elem)
        if not descriptor:
            continue  # can't derive — leave for manual rename
        to_rename.append((tn, explicit_dn if explicit_dn is not None else tn, explicit_dn is not None, descriptor))

    if not to_rename:
        return {"modified": False, "content": content, "changes": []}

    # Group by type so we can iterate raw-text tag occurrences for each type.
    # For each type, enumerate opening tags of that type in the raw text, then
    # zip with ET occurrences to apply targeted changes.
    from collections import defaultdict
    by_type: dict[str, list[int]] = defaultdict(list)
    for idx, (tn, _, _, _) in enumerate(to_rename):
        by_type[tn].append(idx)

    used_names: set[str] = set()
    for tn in set(tn for tn, *_ in to_rename):
        # Collect all existing DisplayNames in the doc for uniqueness checks
        for m in re.finditer(r'\bDisplayName="([^"]+)"', content):
            used_names.add(m.group(1))

    replacements: list[tuple[int, int, str, str]] = []  # start, end, replacement, msg

    for type_name, indices in sorted(by_type.items()):
        # Raw-text opening tags of this type, excluding property elements
        tag_re = re.compile(
            r"<(?P<ns>\w+:)?" + re.escape(type_name) + r"(?=[\s/>])(?P<attrs>[^>]*?)(?P<close>/?>)",
            re.DOTALL,
        )
        raw_matches = list(tag_re.finditer(content))

        # Separate matches with vs without DisplayName
        typed_matches: list[tuple[re.Match, bool]] = []  # (match, has_dn)
        for m in raw_matches:
            attrs = m.group("attrs") or ""
            typed_matches.append((m, "DisplayName=" in attrs))

        if len(typed_matches) < len(indices):
            continue  # safety — raw-text count can't explain all ET occurrences

        # For each ET-flagged default-named activity of this type, find the
        # corresponding raw-text occurrence by walking both in doc order.
        ranked = 0
        for m, has_dn in typed_matches:
            if ranked >= len(indices):
                break
            # All ET-flagged activities are default-named. The raw-text match
            # is the same occurrence iff its DisplayName attr is missing OR
            # equals the type name.
            attrs = m.group("attrs") or ""
            dn_m = re.search(r'\bDisplayName="([^"]+)"', attrs)
            current_dn = dn_m.group(1) if dn_m else None
            is_default_raw = current_dn is None or current_dn == type_name
            if not is_default_raw:
                continue  # already-custom-named; skip, not one of our ET flags

            idx = indices[ranked]
            _, _, _, descriptor = to_rename[idx]
            new_name = _build_unique_displayname(type_name, descriptor, used_names, ranked + 1)
            used_names.add(new_name)
            escaped_new = _xml_escape(new_name, {'"': '&quot;'})

            ns = m.group("ns") or ""
            close = m.group("close")
            if has_dn:
                # Replace existing DisplayName="type_name" with DisplayName="new_name"
                new_attrs = re.sub(
                    r'\bDisplayName="[^"]+"',
                    f'DisplayName="{escaped_new}"',
                    attrs,
                    count=1,
                )
                new_tag = f"<{ns}{type_name}{new_attrs}{close}"
                msg = f"ST-NMG-020: Renamed default {type_name} -> '{new_name}'"
            else:
                # Insert DisplayName as the first attribute after the tag name
                sep = " " if attrs and not attrs.startswith(" ") else ""
                new_tag = f'<{ns}{type_name} DisplayName="{escaped_new}"{sep}{attrs}{close}'
                msg = f"ST-NMG-020: Named default {type_name} as '{new_name}'"
            replacements.append((m.start(), m.end(), new_tag, msg))
            ranked += 1

    if not replacements:
        return {"modified": False, "content": content, "changes": []}

    # Apply in reverse position so earlier offsets stay valid
    replacements.sort(key=lambda r: r[0], reverse=True)
    new_content = content
    for start, end, rep, _ in replacements:
        new_content = new_content[:start] + rep + new_content[end:]

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

        # Deterministic id — tied to the catch position, so re-running the
        # fix on the same input produces byte-identical output.
        uid = f"{modified_count + 1:03d}"
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
    "ST-NMG-020": _fix_st_nmg_020,
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
