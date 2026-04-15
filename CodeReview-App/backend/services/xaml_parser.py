import xml.etree.ElementTree as ET
import os
import re

from models.schemas import (
    ReviewContext,
    ActivitySummary,
    VariableSummary,
    ArgumentSummary,
)


def _local_name(tag: str) -> str:
    """Strip namespace prefix from an XML tag."""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _build_parent_map(root: ET.Element) -> dict[ET.Element, ET.Element]:
    return {child: parent for parent in root.iter() for child in parent}


def _get_ancestors(
    parent_map: dict[ET.Element, ET.Element], element: ET.Element
) -> list[ET.Element]:
    ancestors = []
    current = element
    while current in parent_map:
        current = parent_map[current]
        ancestors.append(current)
    return ancestors


def _get_depth(
    parent_map: dict[ET.Element, ET.Element], element: ET.Element
) -> int:
    depth = 0
    current = element
    while current in parent_map:
        current = parent_map[current]
        depth += 1
    return depth


def _is_ancestor_type(
    parent_map: dict[ET.Element, ET.Element],
    element: ET.Element,
    type_name: str,
) -> bool:
    for ancestor in _get_ancestors(parent_map, element):
        if _local_name(ancestor.tag) == type_name:
            return True
    return False


def _extract_workflow_name(root: ET.Element, file_name: str) -> str:
    # Try x:Class attribute
    for attr_name, attr_val in root.attrib.items():
        if attr_name.endswith("}Class") or attr_name == "x:Class":
            return attr_val.split(".")[-1] if "." in attr_val else attr_val

    # Fall back to DisplayName
    display = root.attrib.get("DisplayName", "")
    if display:
        return display

    # Fall back to filename
    return os.path.splitext(file_name)[0]


def _extract_variables(root: ET.Element) -> list[VariableSummary]:
    variables: list[VariableSummary] = []
    for elem in root.iter():
        if _local_name(elem.tag) == "Variable":
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
            # Clean up type: extract the simple type name
            if ":" in type_arg:
                type_arg = type_arg.split(":")[-1]
            scope = elem.attrib.get("Scope", "")
            variables.append(
                VariableSummary(name=name, type=type_arg, scope=scope)
            )
    return variables


def _extract_arguments(root: ET.Element) -> list[ArgumentSummary]:
    arguments: list[ArgumentSummary] = []

    # Look for x:Property elements in x:Members
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

            # Extract the inner type
            inner_type = "Object"
            match = re.search(r"Argument\((.+?)\)", type_attr)
            if match:
                inner_type = match.group(1)
                if ":" in inner_type:
                    inner_type = inner_type.split(":")[-1]

            arguments.append(
                ArgumentSummary(name=name, direction=direction, type=inner_type)
            )

    return arguments


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
            # Skip the standard xml namespace
            if attr_name in ("xmlns:x", "xmlns:xml", "xmlns"):
                continue
            if attr_name.startswith("xmlns:"):
                namespaces.append(attr_val)
            elif attr_name.startswith("xmlns"):
                namespaces.append(attr_val)
    return namespaces


def _check_log_bookends(
    activities: list[dict], parent_map: dict, root: ET.Element
) -> tuple[bool, bool]:
    """Check for log messages near start and end of main sequence."""
    # Get activities at low depth with LogMessage type
    shallow_activities = [
        a for a in activities if a["depth"] <= 2
    ]

    has_start_log = False
    has_end_log = False

    first_five = shallow_activities[:5]
    last_five = shallow_activities[-5:] if len(shallow_activities) > 5 else shallow_activities

    for a in first_five:
        if "LogMessage" in a["type_name"] or "Log" == a["type_name"]:
            has_start_log = True
            break

    for a in last_five:
        if "LogMessage" in a["type_name"] or "Log" == a["type_name"]:
            has_end_log = True
            break

    return has_start_log, has_end_log


def parse_xaml_file(
    file_name: str, zip_entry_path: str, xml_content: str
) -> ReviewContext:
    root = ET.fromstring(xml_content)
    parent_map = _build_parent_map(root)

    workflow_name = _extract_workflow_name(root, file_name)

    # Extract all activities
    activities_raw: list[dict] = []
    activity_summaries: list[ActivitySummary] = []

    for elem in root.iter():
        local = _local_name(elem.tag)
        # Skip meta elements
        if local in (
            "Variable",
            "Property",
            "Members",
            "TextExpression",
            "Literal",
        ):
            continue

        display_name = elem.attrib.get("DisplayName", local)
        depth = _get_depth(parent_map, elem)
        inside_try = _is_ancestor_type(parent_map, elem, "TryCatch")
        inside_retry = _is_ancestor_type(parent_map, elem, "RetryScope")

        activities_raw.append(
            {"type_name": local, "display_name": display_name, "depth": depth}
        )
        activity_summaries.append(
            ActivitySummary(
                display_name=display_name,
                type_name=local,
                is_inside_try_catch=inside_try,
                is_inside_retry_scope=inside_retry,
                depth=depth,
            )
        )

    variables = _extract_variables(root)
    arguments = _extract_arguments(root)
    has_geh = _check_global_exception_handler(root)
    namespaces = _extract_namespaces(root)
    has_start_log, has_end_log = _check_log_bookends(
        activities_raw, parent_map, root
    )

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
    )
