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
            else:
                # Surface SKIPPED-style messages even when the handler made
                # no edits — these are explicit "I considered the fix and
                # deliberately didn't apply it" signals (e.g. collision
                # guards in ST-NMG-001/002/008/016) and the user needs to
                # see them to understand why a finding wasn't auto-fixed.
                # Dedupe at the end to avoid repetition across passes.
                for c in result.get("changes", []):
                    if "SKIPPED" in c:
                        changes.append(c)

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

    # Post-convergence pass: disambiguate sibling-scope variable duplicates
    # by suffixing with `_2`, `_3`, ... per occurrence. Runs after all the
    # finding-driven rules so it sees the final post-rename names. This
    # rule has no corresponding reviewer finding (UiPath's Workflow Analyzer
    # flags it as ST-NMG-005 cross-scope; our static reviewer is more
    # conservative and only flags ancestor shadows).
    sibling_result = _fix_st_nmg_005_siblings(content, [])
    if sibling_result.get("modified"):
        content = sibling_result["content"]
        changes.extend(sibling_result["changes"])

        # Disambiguation can REVEAL orphan declarations that were previously
        # hidden by name-collision: if Scope A had `X` actually referenced
        # in expressions and Scope B had `X` declared but unreferenced, the
        # flat reviewer treated B's `X` as "used" because the name appeared
        # in expressions globally. After disambiguation B's becomes `X8`
        # with zero expression references — genuinely unused. Re-run the
        # reviewer + GEN-001 unused-variable cleanup once to remove these.
        try:
            from services.xaml_parser import parse_xaml_file
            from services.static_reviewer import review_single_file
            file_name = findings[0].file_name if findings else "unknown.xaml"
            zip_entry = findings[0].zip_entry_path if findings else ""
            ctx = parse_xaml_file(file_name, zip_entry, content)
            post_findings = review_single_file(ctx, [file_name])
            unused_findings = [f for f in post_findings if f.rule_id == "GEN-001" and f.auto_fixable]
            if unused_findings:
                cleanup = _fix_gen_001(content, unused_findings)
                if cleanup.get("modified"):
                    content = cleanup["content"]
                    changes.extend(cleanup["changes"])
        except Exception:
            pass

    # Dedupe while preserving first-seen order — collision-guard SKIPPED
    # messages can repeat across passes when the same finding is re-flagged
    # by the re-review.
    deduped: list[str] = []
    seen_changes: set[str] = set()
    for c in changes:
        if c not in seen_changes:
            seen_changes.add(c)
            deduped.append(c)

    return {
        "original_content": xml_content,
        "modified_content": content,
        "changes_applied": deduped,
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


def _collect_declared_names(content: str) -> set[str]:
    """Return the set of all variable + argument names declared in the XAML.

    Used by prefix-rename fixers to detect collisions before renaming.
    Without this guard, ST-NMG-001/002/009/011 will rename `X` to `prefix_X`
    even when `prefix_X` is already declared elsewhere — UiPath then rejects
    the file with "A variable, RuntimeArgument or DelegateArgument already
    exists with the name 'prefix_X'. Names must be unique within an
    environment scope."
    """
    names: set[str] = set()
    # Variable declarations: <Variable ... Name="X" .../>
    for m in re.finditer(r'<Variable\b[^>]*\bName="([^"]+)"', content):
        names.add(m.group(1))
    # Argument declarations: <x:Property Name="X" ... /> in x:Members
    for m in re.finditer(r'<x:Property\b[^>]*\bName="([^"]+)"', content):
        names.add(m.group(1))
    return names


def _rename_in_xaml(content: str, old_name: str, new_name: str) -> tuple[str, int]:
    """Rename a variable/argument across all locations in XAML content.

    Handles:
      1. Variable/Argument declarations:        Name="oldName"
      2. InvokeWorkflowFile argument keys:      Key="oldName"
      3. VB expression references (ALL of them):
           a. inside [...] bracketed expressions — every occurrence, not
              just the first (e.g. [oldName = oldName + 1], multi-line
              `New With {.a=oldName, .b=oldName}`).
           b. inside ExpressionText="..." attribute values on
              <mva:VisualBasicValue> / <mva:VisualBasicReference> elements
              (UiPath uses this form heavily for Import Arguments of
              InvokeWorkflowFile; our earlier bracket-only scan missed it).
           c. inside attribute-value VB expressions whose body contains
              inner brackets — e.g. Condition="[X.StartsWith(&quot;[&quot;)]"
              or Text="[String.Format(&quot;//*[{0}]&quot;, X.Select(...))]".
              The simple bracket walker in (a) cannot match these
              because the body contains `[` / `]` characters, so before this
              fix the rename silently skipped them, leaving expressions
              referencing the OLD name after the declaration was renamed —
              UiPath then errors with BC30451 "X is not declared".
           d. inside element-text VB expressions with inner brackets — e.g.
              <InArgument>[String.Format("//*[{0}]", X.Select(...))]</InArgument>.
              Same root cause as (c), but in element text instead of an
              attribute value.
      4. Attribute-form property refs on the root Activity:
           this:Main.oldName="value"

    Returns (new_content, replacement_count).
    """
    count = 0
    # Negative-lookbehind on `.` so we never rewrite property accesses — e.g.
    # `credential.Password` must stay `.Password` even when an argument named
    # `Password` is being renamed. Crossing the dot produced
    # `.out_Password` / `.str_Password` which VB rejects with BC30456
    # "X is not a member of NetworkCredential" and similar.
    word_re = re.compile(rf'(?<![\w.])\b{re.escape(old_name)}\b')

    # 1. Variable/Argument declaration: Name="oldName"
    pattern = re.compile(rf'\bName="{re.escape(old_name)}"')
    content, n = pattern.subn(f'Name="{new_name}"', content)
    count += n

    # 2. Argument key bindings: Key="oldName" (InvokeWorkflowFile argument maps)
    pattern = re.compile(rf'\bKey="{re.escape(old_name)}"')
    content, n = pattern.subn(f'Key="{new_name}"', content)
    count += n

    # 3a. VB references inside [...] bracketed expressions — rewrite the
    #     *whole* interior so every occurrence is replaced. The previous
    #     single-shot regex hit only the first match inside each bracket,
    #     which left expressions like `[BatchStart = BatchStart + 1000]`
    #     or `New With {.a = in_X, .b = in_X}` half-renamed and caused
    #     downstream "variable not declared" / BC30157 errors.
    def _rewrite_bracket(m: re.Match) -> str:
        inner = m.group(1)
        new_inner, k = word_re.subn(new_name, inner)
        nonlocal count
        count += k
        return f'[{new_inner}]'
    content = re.sub(r'\[([^\[\]]*)\]', _rewrite_bracket, content)

    # 3b. VB references inside ExpressionText="..." attribute values on
    #     <mva:VisualBasicValue> / <mva:VisualBasicReference> elements.
    #     These never have surrounding brackets in the attribute itself.
    def _rewrite_expr_attr(m: re.Match) -> str:
        prefix, inner, suffix = m.group(1), m.group(2), m.group(3)
        new_inner, k = word_re.subn(new_name, inner)
        nonlocal count
        count += k
        return f'{prefix}{new_inner}{suffix}'
    content = re.sub(
        r'(\bExpressionText=")([^"]*)(")',
        _rewrite_expr_attr,
        content,
    )

    # 3c. Attribute-value VB expressions whose body contains inner brackets.
    #     E.g. Condition="[X.StartsWith(&quot;[&quot;)]" or
    #     Items="[String.Format(&quot;//*[{0}]&quot;, X.Select(...))]".
    #     The bracket walker in (3a) only matches `[...]` chunks with no inner
    #     brackets, so it silently skips these and leaves stale references to
    #     `old_name`. We catch them by recognising the attribute-value shape
    #     `="[...]"` (body must start with `[` and end with `]`, with no `"`
    #     in between since attribute values use &quot; for literal quotes).
    #     For simple `="[X]"` cases this also runs after (3a), but word_re's
    #     lookbehind `(?<![\w.])` prevents a double rename — once `[X]` has
    #     become `[new_X]`, the `X` inside `new_X` is preceded by `_` which
    #     is `\w`, so the lookbehind blocks the second match.
    def _rewrite_attr_vb_expr(m: re.Match) -> str:
        prefix, body, suffix = m.group(1), m.group(2), m.group(3)
        new_body, k = word_re.subn(new_name, body)
        nonlocal count
        count += k
        return f'{prefix}{new_body}{suffix}'
    content = re.sub(r'(=")(\[[^"]*\])(")', _rewrite_attr_vb_expr, content)

    # 3d. Element-text VB expressions with inner brackets — same root cause
    #     as (3c), but in `<InArgument>[...]</InArgument>` style text content
    #     rather than an attribute value. Body must start with `[` and end
    #     with `]` and contain no `<` (which would mean we crossed a tag
    #     boundary). VB expressions encode `<` as `&lt;` so this is safe.
    def _rewrite_element_text_vb_expr(m: re.Match) -> str:
        prefix, body, suffix = m.group(1), m.group(2), m.group(3)
        new_body, k = word_re.subn(new_name, body)
        nonlocal count
        count += k
        return f'{prefix}{new_body}{suffix}'
    content = re.sub(
        r'(>\s*)(\[[^<]*\])(\s*<)',
        _rewrite_element_text_vb_expr,
        content,
    )

    # 4. Attribute-form property references on the Activity root:
    #    e.g. this:Main.oldName="default value"
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
    declared = _collect_declared_names(new_content)

    for f in findings:
        var_name = _extract_name_from_finding(f, "variable")
        if not var_name or var_name in seen:
            continue
        seen.add(var_name)

        if var_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + var_name
        if new_name in declared:
            changes.append(f"{f.rule_id}: SKIPPED rename '{var_name}' -> '{new_name}' (name collision: '{new_name}' is already declared)")
            continue
        new_content, count = _rename_in_xaml(new_content, var_name, new_name)
        if count > 0:
            modified = True
            declared.discard(var_name)
            declared.add(new_name)
            changes.append(f"{f.rule_id}: Renamed variable '{var_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_naming_argument(content: str, findings: list[Finding], expected_prefix: str) -> dict:
    """Generic argument naming fix — prepend expected direction prefix."""
    modified = False
    changes = []
    new_content = content
    seen = set()
    declared = _collect_declared_names(new_content)

    for f in findings:
        arg_name = _extract_name_from_finding(f, "argument")
        if not arg_name or arg_name in seen:
            continue
        seen.add(arg_name)

        if arg_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + arg_name
        if new_name in declared:
            changes.append(f"{f.rule_id}: SKIPPED rename '{arg_name}' -> '{new_name}' (name collision: '{new_name}' is already declared)")
            continue
        new_content, count = _rename_in_xaml(new_content, arg_name, new_name)
        if count > 0:
            modified = True
            declared.discard(arg_name)
            declared.add(new_name)
            changes.append(f"{f.rule_id}: Renamed argument '{arg_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


# ── ST-NMG: Naming Convention Fixes ──────────────────────────────

def _fix_st_nmg_001(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-001: Variables Naming Convention — add type prefixes."""
    modified = False
    changes = []
    new_content = content
    seen = set()

    # Trust the reviewer's prefix directly — it's already computed against the
    # full type string and placed in the `Expected prefix 'X'` section of the
    # finding. Keyword matching on the description text missed `arr_`/`dic_`
    # and defaulted to `str_`, which then caused wrong renames like
    # `str_UnprocessedQueuesDetails` on a `DataRow[]` variable.
    prefix_re = re.compile(r"Expected prefix '([a-z_]+)'")
    declared = _collect_declared_names(new_content)

    for f in findings:
        var_name = _extract_name_from_finding(f, "variable")
        if not var_name or var_name in seen:
            continue
        seen.add(var_name)

        m = prefix_re.search(f.description or "")
        if not m:
            continue  # can't determine prefix — skip rather than guess
        expected_prefix = m.group(1)

        if var_name.startswith(expected_prefix):
            continue

        new_name = expected_prefix + var_name
        # Collision guard: if `new_name` is already a declared variable or
        # argument, renaming would create a duplicate that UiPath rejects
        # ("Names must be unique within an environment scope"). Skip rather
        # than corrupt the workflow.
        if new_name in declared:
            changes.append(f"ST-NMG-001: SKIPPED rename '{var_name}' -> '{new_name}' (name collision: '{new_name}' is already declared)")
            continue
        new_content, count = _rename_in_xaml(new_content, var_name, new_name)
        if count > 0:
            modified = True
            declared.discard(var_name)
            declared.add(new_name)
            changes.append(f"ST-NMG-001: Renamed variable '{var_name}' -> '{new_name}' ({count} location(s))")

    return {"modified": modified, "content": new_content, "changes": changes}


def _fix_st_nmg_002(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-002: Arguments Naming Convention — add direction prefixes."""
    modified = False
    changes = []
    new_content = content
    seen = set()
    declared = _collect_declared_names(new_content)

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
        # Collision guard — see ST-NMG-001 for rationale.
        if new_name in declared:
            changes.append(f"ST-NMG-002: SKIPPED rename '{arg_name}' -> '{new_name}' (name collision: '{new_name}' is already declared)")
            continue
        new_content, count = _rename_in_xaml(new_content, arg_name, new_name)
        if count > 0:
            modified = True
            declared.discard(arg_name)
            declared.add(new_name)
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


# ── ST-NMG-005-SIBLINGS: Disambiguate sibling-scope duplicate variables ──

# Activity types that own a variable scope. A variable's "owner" is the
# nearest ancestor of one of these types.
_VARIABLE_OWNER_TYPES: frozenset = frozenset({
    "Sequence", "NSequence",
    "Flowchart", "StateMachine",
    "TryCatch",
    "While", "DoWhile", "ForEach", "ForEachRow",
    "If", "Switch", "Pick",
})


def _scope_bounded_rename(content: str, span_start: int, span_end: int,
                           old_name: str, new_name: str) -> tuple[str, int]:
    """Apply ``_rename_in_xaml`` semantics restricted to ``[span_start, span_end)``.

    Used by sibling-disambiguation: each duplicate-name owner has its OWN
    text range, and we must rename the variable + every reference to it
    within that range only — leaving siblings' references intact.
    """
    if span_start >= span_end:
        return content, 0
    before = content[:span_start]
    middle = content[span_start:span_end]
    after = content[span_end:]
    new_middle, n = _rename_in_xaml(middle, old_name, new_name)
    return before + new_middle + after, n


def _find_owner_text_span(content: str, owner_type: str, owner_idref: str) -> tuple[int, int] | None:
    """Find the start..end byte offsets of a specific activity element by IdRef.

    Walks raw text rather than ET so we can return positions for scope-
    bounded rewrites. Handles namespaced types (``ui:Sequence`` etc.) and
    nested same-type elements (counts depth as we scan).
    """
    # `(?=[\s/>])` excludes property elements like `<Sequence.Variables>` —
    # a `\b` boundary would let `.Variables` through as `attrs`, which then
    # increments depth without a matching `</Sequence.Variables>` (close
    # regex requires `\s*>`), corrupting the balance and making the search
    # fail entirely for any owner that comes after a property-element open.
    open_re = re.compile(
        r"<(?P<ns>\w+:)?" + re.escape(owner_type) +
        r"(?=[\s/>])(?P<attrs>[^>]*?)(?P<close>/?>)",
        re.DOTALL,
    )
    close_re = re.compile(
        r"</(?:\w+:)?" + re.escape(owner_type) + r"\s*>",
    )

    # Find the opening tag whose attributes contain the matching IdRef
    target_open = None
    for m in open_re.finditer(content):
        attrs = m.group("attrs") or ""
        if f'IdRef="{owner_idref}"' in attrs:
            target_open = m
            break
    if target_open is None:
        return None

    # Self-closing — span is just the tag itself
    if (target_open.group("close") or "").strip() == "/>":
        return target_open.start(), target_open.end()

    # Walk forward, balancing nested same-type opens against closes
    depth = 1
    pos = target_open.end()
    while pos < len(content) and depth > 0:
        next_open = open_re.search(content, pos)
        next_close = close_re.search(content, pos)
        if next_close is None:
            return None  # malformed
        if next_open is not None and next_open.start() < next_close.start():
            # Skip self-closing same-type opens (they don't increment depth)
            if (next_open.group("close") or "").strip() != "/>":
                depth += 1
            pos = next_open.end()
        else:
            depth -= 1
            pos = next_close.end()
    if depth != 0:
        return None
    return target_open.start(), pos


def _fix_st_nmg_005_siblings(content: str, findings: list[Finding]) -> dict:
    """Disambiguate variables declared with the same name in different
    sibling scopes by suffixing with `_2`, `_3`, ... per occurrence.

    UiPath's ST-NMG-005 ("Variable Overrides Variable") flags ANY cross-
    scope name reuse — even when the scopes are independent siblings rather
    than parent/child shadows. Renaming siblings is safe because variables
    in UiPath are strictly scope-local: each sibling owner has its own
    independent variable, and references inside that owner's text span
    resolve to the local declaration only.

    Algorithm:
      1. Walk every <Variable> with ET; record each with its OWNER (the
         nearest variable-holding ancestor activity) and the owner's IdRef.
      2. Group by name. The first occurrence keeps the original name. Each
         subsequent occurrence gets `name_2`, `name_3`, ... and is renamed
         within its owner's text span only.
      3. Skip true shadows (handled by `_fix_st_nmg_005`); this rule only
         disambiguates non-shadowing siblings.

    Note: this rule has no corresponding reviewer finding in our static
    reviewer (which only flags ancestor shadows). It runs unconditionally
    after the ancestor-shadow remover so it sees the post-shadow-removal
    state.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"modified": False, "content": content, "changes": []}

    def _lname(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    parent_map: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent

    SAP2010_NS = "http://schemas.microsoft.com/netfx/2010/xaml/activities/presentation"
    IDREF_ATTR = f"{{{SAP2010_NS}}}WorkflowViewState.IdRef"

    # Collect Variables with owner info, in document order
    variables: list[tuple[str, str, str]] = []  # (name, owner_type, owner_idref)
    name_owners: dict[str, list[tuple[str, str]]] = defaultdict(list)
    ancestor_names_by_owner: dict[int, set[str]] = {}

    # First pass: index every owning activity's declared variable names
    # so we can detect (and skip) ancestor-shadow cases.
    for elem in root.iter():
        if _lname(elem.tag) != "Variable":
            continue
        prop = parent_map.get(elem)
        owner = parent_map.get(prop) if prop is not None else None
        if owner is None:
            continue
        name = elem.attrib.get("Name", "")
        if name:
            ancestor_names_by_owner.setdefault(id(owner), set()).add(name)

    for elem in root.iter():
        if _lname(elem.tag) != "Variable":
            continue
        name = elem.attrib.get("Name", "")
        if not name:
            continue
        prop = parent_map.get(elem)
        owner = parent_map.get(prop) if prop is not None else None
        if owner is None:
            continue
        owner_type = _lname(owner.tag)
        if owner_type not in _VARIABLE_OWNER_TYPES:
            continue
        owner_idref = owner.attrib.get(IDREF_ATTR, "")
        if not owner_idref:
            # No IdRef = can't precisely identify the owner's text span. Skip
            # rather than risk a global rename that bleeds across scopes.
            continue

        # Skip if this is an ancestor shadow (ST-NMG-005 already handles those)
        cur: ET.Element | None = parent_map.get(owner)
        is_shadow = False
        while cur is not None:
            if name in ancestor_names_by_owner.get(id(cur), set()):
                is_shadow = True
                break
            cur = parent_map.get(cur)
        if is_shadow:
            continue

        name_owners[name].append((owner_type, owner_idref))

    # For each name with 2+ sibling owners, rename occurrences 2..N.
    # Suffix with a bare digit (no underscore) so PascalCase validity is
    # preserved — `dt_FoldersData_2` would have body `FoldersData_2` which
    # ST-NMG-010 rejects (underscore in body); `dt_FoldersData2` keeps body
    # `FoldersData2` which is valid PascalCase (digit on the end is fine).
    new_content = content
    changes: list[str] = []
    for name in sorted(name_owners):
        owners = name_owners[name]
        if len(owners) < 2:
            continue
        for n, (owner_type, owner_idref) in enumerate(owners[1:], start=2):
            new_name = f"{name}{n}"
            span = _find_owner_text_span(new_content, owner_type, owner_idref)
            if span is None:
                continue
            start, end = span
            new_content, k = _scope_bounded_rename(new_content, start, end, name, new_name)
            if k > 0:
                changes.append(
                    f"ST-NMG-005-SIBLINGS: Disambiguated sibling variable "
                    f"'{name}' -> '{new_name}' in {owner_type}#{owner_idref} "
                    f"({k} location(s))"
                )

    if not changes:
        return {"modified": False, "content": content, "changes": []}
    return {"modified": True, "content": new_content, "changes": changes}


# ── ST-NMG-005: Remove inner shadow variable declarations ──────────

def _fix_st_nmg_005(content: str, findings: list[Finding]) -> dict:
    """ST-NMG-005: Remove only the specific inner-scope Variable that
    shadows an outer declaration — never touch sibling sub-sequence
    declarations.

    Algorithm:

    1. Parse the XAML with ET and walk every ``<Variable>`` in document order.
       For each, compute the ancestor-activity chain (skipping property-
       element wrappers like ``<Sequence.Variables>``). A variable is a
       shadow iff some *strict* ancestor activity also declares the same
       name — ancestor-aware, NOT global-first-wins.

    2. Find every ``<Variable .../>`` occurrence in the raw text in document
       order. ET.iter() yields variables in the same order, so index i in
       the text list corresponds to index i in the ET list. Remove only the
       specific text spans whose corresponding ET variable was flagged as
       a nested shadow. Sibling sub-sequence declarations are left untouched.
    """
    if not findings:
        return {"modified": False, "content": content, "changes": []}

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"modified": False, "content": content, "changes": []}

    def _lname(tag: str) -> str:
        return tag.split("}", 1)[-1] if "}" in tag else tag

    parent_map: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent

    # Gather every Variable in document order with its owner and ancestor chain.
    all_vars_et: list[tuple[ET.Element, str, ET.Element | None, list[ET.Element]]] = []
    names_by_activity: dict[int, set[str]] = {}
    for elem in root.iter():
        if _lname(elem.tag) != "Variable":
            continue
        name = elem.attrib.get("Name", "")
        if not name:
            # Still track position so the ET list stays aligned with the
            # text list (which will also include nameless Variables).
            all_vars_et.append((elem, "", None, []))
            continue
        prop = parent_map.get(elem)
        owner = parent_map.get(prop) if prop is not None else None
        if owner is None:
            all_vars_et.append((elem, name, None, []))
            continue
        names_by_activity.setdefault(id(owner), set()).add(name)
        chain: list[ET.Element] = []
        cur: ET.Element | None = owner
        while cur is not None:
            if "." not in _lname(cur.tag):
                chain.append(cur)
            cur = parent_map.get(cur)
        all_vars_et.append((elem, name, owner, chain))

    # Determine which ET variables are true nested shadows.
    target_names = set()
    for f in findings:
        n = _extract_name_from_finding(f, "variable")
        if n:
            target_names.add(n)

    shadow_indices: set[int] = set()
    shadow_names_counter: dict[str, int] = {}
    for i, (_elem, name, _owner, chain) in enumerate(all_vars_et):
        if not name or name not in target_names:
            continue
        ancestors = chain[1:]  # strict ancestors only
        shadowed = any(
            name in names_by_activity.get(id(anc), set()) for anc in ancestors
        )
        if shadowed:
            shadow_indices.add(i)
            shadow_names_counter[name] = shadow_names_counter.get(name, 0) + 1

    if not shadow_indices:
        return {"modified": False, "content": content, "changes": []}

    # Find every <Variable .../> span in the raw text in document order.
    text_spans = list(re.finditer(
        r'\s*<(?:\w+:)?Variable\b[^>]*/>\s*',
        content,
        re.DOTALL,
    ))

    if len(text_spans) != len(all_vars_et):
        # Mismatch means document contains non-self-closing <Variable>...</Variable>
        # forms or CDATA oddities we didn't account for. Bail out rather than
        # risk removing the wrong element.
        return {"modified": False, "content": content, "changes": []}

    new_content = content
    # Remove from end to preserve earlier offsets.
    for i in sorted(shadow_indices, reverse=True):
        span = text_spans[i]
        new_content = new_content[:span.start()] + "\n" + new_content[span.end():]

    changes = [
        f"ST-NMG-005: Removed {count} inner-scope shadow declaration(s) of '{name}'"
        for name, count in sorted(shadow_names_counter.items())
    ]
    return {"modified": True, "content": new_content, "changes": changes}


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

    Collision guard: the middle-word-drop algorithm in ``_shorten_name`` can
    produce identical shortened names from distinct originals (e.g. both
    ``URLSpecificCredentialTarget`` and ``URLTenantSpecificCredentialTarget``
    shorten to ``URLCredentialTarget``). UiPath then refuses to load the file
    with "A variable, RuntimeArgument or DelegateArgument already exists with
    the name 'X'. Names must be unique within an environment scope." So we
    pre-compute every proposed shortening, detect collisions against (a) other
    proposed shortenings in this pass and (b) any name already declared in the
    file, and skip the colliding entries with a SKIPPED log line.
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

    # Pre-compute proposals so we can detect within-pass collisions.
    proposed: dict[str, str] = {}
    for name in sorted(current_names):
        if name in seen or len(name) <= 30:
            continue
        seen.add(name)
        short = _shorten_name(name, limit=28)
        if not short or short == name:
            continue
        proposed[name] = short

    # Group by target — any target reached by 2+ originals is a collision.
    by_target: dict[str, list[str]] = {}
    for old, new in proposed.items():
        by_target.setdefault(new, []).append(old)

    declared = _collect_declared_names(new_content)
    for new, olds in sorted(by_target.items()):
        # Collision case 1: multiple originals → same shortened name.
        if len(olds) > 1:
            for old in olds:
                changes.append(
                    f"ST-NMG-008: SKIPPED shorten '{old}' -> '{new}' "
                    f"(name collision: would also be the shortened form of {[o for o in olds if o != old]})"
                )
            continue
        old = olds[0]
        # Collision case 2: shortened name already declared (variable or arg).
        if new in declared and new != old:
            changes.append(
                f"ST-NMG-008: SKIPPED shorten '{old}' -> '{new}' "
                f"(name collision: '{new}' is already declared)"
            )
            continue
        new_content, count = _rename_in_xaml(new_content, old, new)
        if count > 0:
            modified = True
            declared.discard(old)
            declared.add(new)
            changes.append(
                f"ST-NMG-008: Shortened variable '{old}' -> '{new}' ({count} location(s))"
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

    Collision guard: same as ST-NMG-008. The middle-word-drop algorithm in
    ``_shorten_name`` can map distinct originals to the same shortened name
    (e.g. ``in_FolderMigrationTemplateFilePath`` and
    ``in_FolderMigrationWorkbookFilePath`` both shorten to
    ``in_FolderMigrationFilePath``). Without this guard the resulting XAML
    has two arguments with the same key and UiPath fails to load it with
    "An item with the same key has already been added".
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

    proposed: dict[str, str] = {}
    for name in sorted(current_names):
        if name in seen or len(name) <= 30:
            continue
        seen.add(name)
        short = _shorten_name(name, limit=28)
        if not short or short == name:
            continue
        proposed[name] = short

    by_target: dict[str, list[str]] = {}
    for old, new in proposed.items():
        by_target.setdefault(new, []).append(old)

    declared = _collect_declared_names(new_content)
    for new, olds in sorted(by_target.items()):
        if len(olds) > 1:
            for old in olds:
                changes.append(
                    f"ST-NMG-016: SKIPPED shorten '{old}' -> '{new}' "
                    f"(name collision: would also be the shortened form of {[o for o in olds if o != old]})"
                )
            continue
        old = olds[0]
        if new in declared and new != old:
            changes.append(
                f"ST-NMG-016: SKIPPED shorten '{old}' -> '{new}' "
                f"(name collision: '{new}' is already declared)"
            )
            continue
        new_content, count = _rename_in_xaml(new_content, old, new)
        if count > 0:
            modified = True
            declared.discard(old)
            declared.add(new)
            changes.append(
                f"ST-NMG-016: Shortened argument '{old}' -> '{new}' ({count} location(s))"
            )

    return {"modified": modified, "content": new_content, "changes": changes}


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

    # Form 3: no-DisplayName Sequences. When the reviewer flagged a Sequence
    # whose name fell back to the bare type ("Sequence"), the matchers above
    # can't find it — those elements have no DisplayName attribute at all,
    # only IdRef. Sweep for `<Sequence>` opening tags that LACK DisplayName
    # and either self-close or wrap metadata-only content. The metadata-only
    # guard prevents removing real activity bodies.
    if "Sequence" in flagged or "NSequence" in flagged:
        # Self-closing without DisplayName
        no_dn_self = re.compile(
            r"\s*<(?:\w+:)?[NS]equence\b(?![^>]*\bDisplayName=)[^>]*/>\s*",
            re.DOTALL,
        )
        new_text, n_self = no_dn_self.subn("\n", new_content)
        if n_self > 0:
            new_content = new_text
            changes.append(f"GEN-REL-001: Removed {n_self} self-closing Sequence(s) with no DisplayName")

        # Open-close without DisplayName, metadata-only inner
        no_dn_open = re.compile(
            r"(\s*)<(?:\w+:)?[NS]equence\b(?![^>]*\bDisplayName=)[^>]*>(.*?)</(?:\w+:)?[NS]equence>\s*",
            re.DOTALL,
        )

        removed_count = [0]
        def _maybe_drop_no_dn(m: re.Match) -> str:
            inner = m.group(2)
            if _inner_is_metadata_only(inner):
                removed_count[0] += 1
                return "\n"
            return m.group(0)

        new_text = no_dn_open.sub(_maybe_drop_no_dn, new_content)
        if removed_count[0] > 0:
            new_content = new_text
            changes.append(
                f"GEN-REL-001: Removed {removed_count[0]} empty Sequence(s) with no DisplayName"
            )

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


# Namespace URI fragments identifying elements that are never activities and
# therefore must not receive a DisplayName injection. UiPath Studio's XAML
# loader rejects DisplayName on e.g. List<AssemblyReference>, x:String, etc.
# with: "Cannot set unknown member '...List(...AssemblyReference).DisplayName'".
_NON_ACTIVITY_NS_FRAGMENTS: tuple[str, ...] = (
    "System.Collections",            # scg:List, scg:Dictionary, scg:HashSet, etc.
    "System.Collections.Generic",
    "System.Collections.ObjectModel",
    "schemas.microsoft.com/winfx/2006/xaml",  # x:String, x:Boolean, x:Reference, x:Static, x:Array…
)


def _is_non_activity_element(elem) -> bool:
    """True if the element is a typed collection, XAML primitive, VB
    expression, or a .NET Attribute class — i.e. anything that must not be
    treated as an activity for DisplayName insertion/rename purposes."""
    tag = elem.tag
    if "}" in tag:
        ns = tag.split("}", 1)[0][1:]  # strip leading '{'
        for frag in _NON_ACTIVITY_NS_FRAGMENTS:
            if frag in ns:
                return True
    # Any class whose name ends in `Attribute` is a .NET attribute type and
    # cannot accept a DisplayName. This covers RequiredArgumentAttribute,
    # OverloadGroupAttribute, DefaultValueAttribute, DescriptionAttribute, etc.
    local = tag.split("}")[-1] if "}" in tag else tag
    if local.endswith("Attribute") and local != "Attribute":
        return True
    return False


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
        "List", "HashSet", "Queue", "Stack", "LinkedList",
        "SortedList", "SortedDictionary", "ObservableCollection",
        "VisualBasicValue", "VisualBasicReference",
        "LambdaValue", "LambdaReference",
        "RequiredArgument", "RequiredArgumentAttribute",
        "OverloadGroup", "OverloadGroupAttribute",
        "DefaultValue", "DefaultValueAttribute",
        "FilterOperationArgument",
        "WorkflowViewState", "ViewState",
    }
    activities: list[tuple[str, str, bool, str | None]] = []
    for elem in root.iter():
        if _is_non_activity_element(elem):
            continue
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
    "List", "HashSet", "Queue", "Stack", "LinkedList",
    "SortedList", "SortedDictionary", "ObservableCollection",
    "VisualBasicValue", "VisualBasicReference",
    "LambdaValue", "LambdaReference",
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
        if _is_non_activity_element(elem):
            continue
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
