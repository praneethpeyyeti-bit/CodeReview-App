import xml.etree.ElementTree as ET
import os
import re
import html

from models.schemas import (
    ReviewContext,
    ActivitySummary,
    VariableSummary,
    ArgumentSummary,
    CatchBlockSummary,
)

# Meta element names to skip when iterating activities
_META_ELEMENTS = {
    "Variable", "Property", "Members", "TextExpression", "Literal",
    "String", "Boolean", "Int32", "Int64", "Double", "Decimal",
    "AssemblyReference", "Collection", "Dictionary",
    "DelegateInArgument", "DelegateOutArgument",
    "ActivityAction", "InArgument", "OutArgument", "InOutArgument",
    "WorkflowViewState", "ViewState",
}

# UI container activity types
_CONTAINER_TYPES = {
    "BrowserScope", "WindowsScope", "ApplicationScope",
    "AttachWindow", "AttachBrowser", "UseApplication",
    "NApplicationCard", "NBrowserScope",
}

# Interesting property names to capture from activity XML attributes
_INTERESTING_PROPS = {
    "Selector", "SimulateClick", "SimulateType", "InteractionMode",
    "DelayBefore", "DelayMS", "Duration", "TimeoutMS",
    "ContinueOnError", "Password", "WaitForReady",
    "IsIncognito", "OpenMode", "CloseMode", "BrowserType",
    "Text", "FileName", "WorkflowFileName",
}


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _get_depth(parent_map: dict[ET.Element, ET.Element], element: ET.Element) -> int:
    depth = 0
    current = element
    while current in parent_map:
        current = parent_map[current]
        depth += 1
    return depth


def _is_ancestor_type(parent_map: dict, element: ET.Element, type_name: str) -> bool:
    current = element
    while current in parent_map:
        current = parent_map[current]
        if _local_name(current.tag) == type_name:
            return True
    return False


def _is_ancestor_any(parent_map: dict, element: ET.Element, type_names: set[str]) -> bool:
    current = element
    while current in parent_map:
        current = parent_map[current]
        if _local_name(current.tag) in type_names:
            return True
    return False


def _extract_workflow_name(root: ET.Element, file_name: str) -> str:
    for attr_name, attr_val in root.attrib.items():
        if attr_name.endswith("}Class") or attr_name == "x:Class":
            return attr_val.split(".")[-1] if "." in attr_val else attr_val
    display = root.attrib.get("DisplayName", "")
    if display:
        return display
    return os.path.splitext(file_name)[0]


def _extract_variables(root: ET.Element) -> list[VariableSummary]:
    """Extract Variable declarations with a **unique scope identifier** per
    owning activity so shadowing between nested scopes can be detected.

    A Variable lives inside a property element like `<Sequence.Variables>`;
    the real owning activity is that property element's parent. We prefer the
    owner's `WorkflowViewState.IdRef` for uniqueness; if absent we fall back
    to `DisplayName` + path position so two Sequences with the same display
    name still get distinct scopes.
    """
    # Build a parent map once so we can walk up two levels (Variable ->
    # property element -> owning activity).
    parent_map: dict[ET.Element, ET.Element] = {}
    for parent in root.iter():
        for child in parent:
            parent_map[child] = parent

    # Assign each owner element a unique index so two structurally-similar
    # Sequences (same tag name, same DisplayName, missing IdRef) still produce
    # distinct scopes for their variables.
    owner_ids: dict[int, str] = {}
    variables: list[VariableSummary] = []

    for elem in root.iter():
        if _local_name(elem.tag) != "Variable":
            continue
        name = elem.attrib.get("Name", "")
        if not name:
            continue
        type_arg = ""
        for attr_name, attr_val in elem.attrib.items():
            if "TypeArguments" in attr_name:
                type_arg = attr_val
                break
        if not type_arg:
            type_arg = elem.attrib.get("Type", "String")
        if ":" in type_arg:
            type_arg = type_arg.split(":")[-1]

        # Walk up: Variable -> <Sequence.Variables> -> <Sequence>
        prop_parent = parent_map.get(elem)
        owner = parent_map.get(prop_parent) if prop_parent is not None else None

        scope = ""
        if owner is not None:
            owner_key = id(owner)
            if owner_key not in owner_ids:
                # Prefer the owner's IdRef if present; else build a stable
                # label from tag + DisplayName + a sequence counter.
                ref_val = ""
                for k, v in owner.attrib.items():
                    if k.endswith("}IdRef") or k.endswith(":IdRef") or k == "IdRef":
                        ref_val = v
                        break
                if ref_val:
                    owner_ids[owner_key] = ref_val
                else:
                    owner_tag = _local_name(owner.tag)
                    display = owner.attrib.get("DisplayName", "")
                    label = f"{owner_tag}:{display}" if display else owner_tag
                    owner_ids[owner_key] = f"{label}#{len(owner_ids)}"
            scope = owner_ids[owner_key]
        elif prop_parent is not None:
            scope = _local_name(prop_parent.tag)

        variables.append(VariableSummary(name=name, type=type_arg, scope=scope))
    return variables


def _extract_arguments(root: ET.Element) -> list[ArgumentSummary]:
    arguments: list[ArgumentSummary] = []

    # First pass: collect argument names that carry a default value.
    # UiPath serializes these two ways:
    #   (a) ELEMENT-FORM: a property element like
    #        <this:WorkflowName.argName><InArgument .../></this:WorkflowName.argName>
    #   (b) ATTRIBUTE-FORM: a flattened attribute on the root Activity
    #        <Activity this:WorkflowName.argName="some value" ...>
    default_arg_names: set[str] = set()

    # (a) Element-form defaults
    for elem in root.iter():
        local = _local_name(elem.tag)
        if "." not in local:
            continue
        _, _, arg_name = local.partition(".")
        if not arg_name or arg_name in ("Variables", "Triggers", "Resources", "Target", "DisplayName"):
            continue
        has_arg_child = False
        for child in elem:
            child_local = _local_name(child.tag)
            if child_local in ("InArgument", "OutArgument", "InOutArgument"):
                has_arg_child = True
                break
        if has_arg_child:
            default_arg_names.add(arg_name)

    # (b) Attribute-form defaults on the root Activity element.
    # Attribute names have the form "{ns}ClassName.argName" after ET canonicalizes.
    for attr_name in root.attrib.keys():
        local_attr = attr_name.split("}")[-1] if "}" in attr_name else attr_name
        if "." not in local_attr:
            continue
        _, _, arg_name = local_attr.partition(".")
        if not arg_name or arg_name in ("Variables", "Triggers", "Resources", "Target", "DisplayName"):
            continue
        default_arg_names.add(arg_name)

    # Second pass: build the argument list, marking which have defaults.
    for elem in root.iter():
        if _local_name(elem.tag) == "Property":
            name = elem.attrib.get("Name", "")
            type_attr = ""
            for attr_name, attr_val in elem.attrib.items():
                if "Type" in attr_name:
                    type_attr = attr_val
                    break
            if not name or not type_attr:
                continue
            if "InOutArgument" in type_attr:
                direction = "InOut"
            elif "OutArgument" in type_attr:
                direction = "Out"
            elif "InArgument" in type_attr:
                direction = "In"
            else:
                continue
            inner_type = "Object"
            match = re.search(r"Argument\((.+?)\)", type_attr)
            if match:
                inner_type = match.group(1)
                if ":" in inner_type:
                    inner_type = inner_type.split(":")[-1]
            arguments.append(ArgumentSummary(
                name=name,
                direction=direction,
                type=inner_type,
                has_default=name in default_arg_names,
            ))
    return arguments


def _extract_properties(elem: ET.Element) -> dict[str, str]:
    """Extract interesting properties from an element's attributes."""
    props: dict[str, str] = {}
    for attr_name, attr_val in elem.attrib.items():
        # Get the local attribute name
        local_attr = attr_name.split("}")[-1] if "}" in attr_name else attr_name
        if local_attr in _INTERESTING_PROPS:
            props[local_attr] = attr_val
    # Also check child elements for selectors (e.g. <Target Selector="..."/>)
    for child in elem:
        child_local = _local_name(child.tag)
        if child_local == "Target" or child_local.endswith(".Target"):
            selector = child.attrib.get("Selector", "")
            if selector:
                props["Selector"] = html.unescape(selector)
            timeout = child.attrib.get("TimeoutMS", "")
            if timeout:
                props["TimeoutMS"] = timeout
            wfr = child.attrib.get("WaitForReady", "")
            if wfr:
                props["WaitForReady"] = wfr
        # Check nested Target inside .Target wrapper
        for grandchild in child:
            gc_local = _local_name(grandchild.tag)
            if gc_local == "Target":
                selector = grandchild.attrib.get("Selector", "")
                if selector:
                    props["Selector"] = html.unescape(selector)
    return props


def _count_activity_children(elem: ET.Element) -> int:
    """Count direct child elements that are activities (not meta/property elements)."""
    count = 0
    for child in elem:
        local = _local_name(child.tag)
        if local in _META_ELEMENTS:
            continue
        # Skip property wrappers like Sequence.Variables, TryCatch.Try, etc.
        if "." in local:
            continue
        # Skip ViewState and other metadata
        if "ViewState" in local or "WorkflowViewState" in local:
            continue
        if "Dictionary" in local or "Collection" in local:
            continue
        count += 1
    return count


def _extract_catch_blocks(root: ET.Element) -> list[CatchBlockSummary]:
    """Extract catch block summaries from TryCatch activities."""
    catch_blocks: list[CatchBlockSummary] = []
    for elem in root.iter():
        local = _local_name(elem.tag)
        if local == "Catch":
            # Get exception type
            exc_type = "Exception"
            for attr_name, attr_val in elem.attrib.items():
                if "TypeArguments" in attr_name:
                    exc_type = attr_val.split(":")[-1] if ":" in attr_val else attr_val
                    break

            # Count activities inside the catch block.
            # Every <Catch> wraps its handler in
            #   <ActivityAction><ActivityAction.Argument/><Sequence>...</Sequence></ActivityAction>
            # The wrapping ActivityAction and Sequence are *structural* — they exist
            # even when the catch is empty — so we must not count them. We also
            # skip the Body/NSequence variants and any Flowchart container node.
            activity_count = 0
            has_log = False
            has_rethrow = False
            structural_containers = {
                "ActivityAction", "DelegateInArgument", "Catch",
                "Sequence", "NSequence", "Body", "Flowchart",
            }
            for descendant in elem.iter():
                desc_local = _local_name(descendant.tag)
                if desc_local in _META_ELEMENTS or "." in desc_local:
                    continue
                if desc_local in structural_containers:
                    continue
                if "Dictionary" in desc_local or "Collection" in desc_local:
                    continue
                activity_count += 1
                if "LogMessage" in desc_local or desc_local == "Log":
                    has_log = True
                if desc_local == "Rethrow":
                    has_rethrow = True

            catch_blocks.append(CatchBlockSummary(
                exception_type=exc_type,
                activity_count=activity_count,
                has_log_message=has_log,
                has_rethrow=has_rethrow,
            ))
    return catch_blocks


def _scan_expressions(xml_content: str) -> tuple[list[str], list[str]]:
    """Scan all [...] bracket expressions in the XAML content.

    Returns (all_expression_strings, referenced_identifiers).
    """
    # Find all bracket expressions like [variable1], [CInt(var)], [var.ToString()]
    expressions = re.findall(r'\[([^\[\]]+)\]', xml_content)

    # Extract identifiers from expressions (word characters that could be variable/argument names)
    identifiers: set[str] = set()
    for expr in expressions:
        # Skip XML-like content and pure strings
        if expr.startswith("<") or expr.startswith("&") or expr.startswith('"'):
            continue
        # Extract all word tokens that look like variable/argument names
        tokens = re.findall(r'\b([a-zA-Z_]\w*)\b', expr)
        for token in tokens:
            # Skip common VB.NET keywords and types
            if token.lower() in {
                "true", "false", "nothing", "new", "not", "and", "or",
                "if", "then", "else", "end", "dim", "as", "string",
                "integer", "int32", "int64", "boolean", "double", "decimal",
                "object", "byte", "char", "date", "datetime", "timespan",
                "datatable", "datarow", "cint", "cstr", "cdbl", "ctype",
                "typeof", "gettype", "directcast", "trycast",
                "tostring", "tolower", "toupper", "trim", "split",
                "contains", "replace", "substring", "length", "count",
                "rows", "columns", "value", "text", "name", "key",
                "add", "remove", "clear", "item", "index",
                "now", "today", "format", "parse", "tryparse",
                "environment", "path", "system", "io", "math",
                "convert", "array", "list", "dictionary",
                "exception", "message", "stacktrace", "innerexception",
                "fromminutes", "fromseconds", "frommilliseconds",
            }:
                continue
            identifiers.add(token)

    return expressions, sorted(identifiers)


def _check_global_exception_handler(root: ET.Element) -> bool:
    for elem in root.iter():
        if _local_name(elem.tag) == "GlobalExceptionHandler":
            return True
    for attr_name in root.attrib:
        if "OnUnhandledException" in attr_name:
            return True
    return False


def _extract_namespaces(root: ET.Element) -> list[str]:
    namespaces = []
    for attr_name, attr_val in root.attrib.items():
        if attr_name.startswith("{") or attr_name.startswith("xmlns"):
            if attr_name in ("xmlns:x", "xmlns:xml", "xmlns"):
                continue
            if attr_name.startswith("xmlns:") or attr_name.startswith("xmlns"):
                namespaces.append(attr_val)
    return namespaces


def _check_log_bookends(activities: list[dict]) -> tuple[bool, bool]:
    shallow = [a for a in activities if a["depth"] <= 2]
    has_start = any(
        "LogMessage" in a["type_name"] or a["type_name"] == "Log"
        for a in shallow[:5]
    )
    has_end = any(
        "LogMessage" in a["type_name"] or a["type_name"] == "Log"
        for a in shallow[-5:]
    ) if len(shallow) > 5 else has_start
    return has_start, has_end


def parse_xaml_file(
    file_name: str, zip_entry_path: str, xml_content: str,
    project_dependencies: dict[str, str] | None = None,
) -> ReviewContext:
    root = ET.fromstring(xml_content)
    parent_map = _build_parent_map(root)

    workflow_name = _extract_workflow_name(root, file_name)

    # Extract all activities with enhanced data
    activities_raw: list[dict] = []
    activity_summaries: list[ActivitySummary] = []

    for elem in root.iter():
        local = _local_name(elem.tag)
        if local in _META_ELEMENTS:
            continue
        # Skip property wrapper elements (e.g. Sequence.Variables, TryCatch.Try)
        if "." in local:
            continue
        # Skip ViewState, sap metadata, and generic XML containers
        if "ViewState" in local or "WorkflowViewState" in local:
            continue
        if local.startswith("x:") or local.startswith("sap"):
            continue

        display_name = elem.attrib.get("DisplayName", local)
        depth = _get_depth(parent_map, elem)
        inside_try = _is_ancestor_type(parent_map, elem, "TryCatch")
        inside_retry = _is_ancestor_type(parent_map, elem, "RetryScope")
        inside_container = _is_ancestor_any(parent_map, elem, _CONTAINER_TYPES)
        child_count = _count_activity_children(elem)
        props = _extract_properties(elem)

        # Mark only Catch-handler body Sequences (direct children of
        # ActivityAction) as structural. Those are always present even for
        # empty handlers and are instead covered by ST-DBP-003. Sequences
        # inside TryCatch.Try / TryCatch.Finally are user-authored — an empty
        # Finally (or empty Try) should still be flagged by GEN-REL-001.
        is_structural = False
        if local in ("Sequence", "NSequence"):
            parent = parent_map.get(elem)
            if parent is not None and _local_name(parent.tag) == "ActivityAction":
                is_structural = True

        activities_raw.append(
            {"type_name": local, "display_name": display_name, "depth": depth}
        )
        activity_summaries.append(ActivitySummary(
            display_name=display_name,
            type_name=local,
            is_inside_try_catch=inside_try,
            is_inside_retry_scope=inside_retry,
            depth=depth,
            child_count=child_count,
            properties=props,
            is_inside_container=inside_container,
            is_structural_wrapper=is_structural,
        ))

    variables = _extract_variables(root)
    arguments = _extract_arguments(root)
    has_geh = _check_global_exception_handler(root)
    namespaces = _extract_namespaces(root)
    has_start_log, has_end_log = _check_log_bookends(activities_raw)
    catch_blocks = _extract_catch_blocks(root)

    # Scan expressions for variable/argument usage
    _, identifiers = _scan_expressions(xml_content)
    var_names = {v.name for v in variables}
    arg_names = {a.name for a in arguments}
    var_usages = sorted(set(identifiers) & var_names)
    arg_usages = sorted(set(identifiers) & arg_names)

    return ReviewContext(
        file_name=file_name,
        zip_entry_path=zip_entry_path,
        workflow_name=workflow_name,
        activities=activity_summaries,
        variables=variables,
        arguments=arguments,
        has_global_exception_handler=has_geh,
        has_start_log=has_start_log,
        has_end_log=has_end_log,
        imported_namespaces=namespaces,
        catch_blocks=catch_blocks,
        variable_usages=var_usages,
        argument_usages=arg_usages,
        project_dependencies=project_dependencies or {},
    )
