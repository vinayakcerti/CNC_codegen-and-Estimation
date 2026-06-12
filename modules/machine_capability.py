"""Conservative machine-axis and setup accessibility model."""


_SIDE_SETUPS = {"Left", "Right", "Front", "Back"}
_KNOWN_SETUPS = {"Top", "Bottom", "Unknown"} | _SIDE_SETUPS


def normalize_machine_capabilities(machine):
    machine = dict(machine or {})
    machine_type = str(machine.get("machine_type") or "").strip()
    defaults = {
        "VMC": (3, False, False),
        "CNC Milling": (3, False, False),
        "HMC": (4, True, False),
        "Turn-Mill": (4, True, False),
        "CNC Turning": (2, False, False),
        "Gang Turning": (2, False, False),
        "Swiss Type": (3, False, False),
    }
    axis_count, indexed, simultaneous = defaults.get(
        machine_type,
        (3, False, False),
    )
    machine.setdefault("axis_count", axis_count)
    machine.setdefault("indexed_3plus2", indexed)
    machine.setdefault("simultaneous_5_axis", simultaneous)
    machine.setdefault("travel_x_mm", None)
    machine.setdefault("travel_y_mm", None)
    machine.setdefault("travel_z_mm", None)
    machine.setdefault("setup_constraints", "Verify fixture, access, and travel.")
    return machine


def assess_setup_access(machine, setup_label, requires_simultaneous_5_axis=False):
    capability = normalize_machine_capabilities(machine)
    setup = str(setup_label or "Unknown")
    if requires_simultaneous_5_axis:
        if capability["simultaneous_5_axis"]:
            return {
                "status": "supported",
                "method": "simultaneous_5_axis",
                "blocked": False,
                "warning": "",
            }
        return {
            "status": "manual_review",
            "method": "unsupported_simultaneous_5_axis",
            "blocked": True,
            "warning": (
                "This operation requires simultaneous 5-axis machining, but the "
                "selected machine profile does not support it."
            ),
        }
    if setup == "Top":
        return {
            "status": "supported",
            "method": "direct_3_axis",
            "blocked": False,
            "warning": "",
        }
    if setup in _SIDE_SETUPS:
        if capability["indexed_3plus2"]:
            return {
                "status": "supported",
                "method": "indexed_3plus2",
                "blocked": False,
                "warning": "",
            }
        return {
            "status": "requires_setup",
            "method": "manual_refixure",
            "blocked": False,
            "warning": (
                f"{setup} access requires a separate fixture/setup on this "
                f"{capability['axis_count']}-axis machine."
            ),
        }
    if setup == "Bottom":
        return {
            "status": "requires_setup",
            "method": "manual_flip",
            "blocked": False,
            "warning": "Bottom access requires a part flip and a verified second setup.",
        }
    if setup not in _KNOWN_SETUPS or setup == "Unknown":
        return {
            "status": "manual_review",
            "method": "unresolved_orientation",
            "blocked": True,
            "warning": "Feature orientation is unresolved; assign a verified setup manually.",
        }
    return {
        "status": "manual_review",
        "method": "unsupported",
        "blocked": True,
        "warning": "Machine accessibility could not be verified.",
    }


def apply_machine_feasibility(operations, machine):
    capability = normalize_machine_capabilities(machine)
    assessed = []
    for operation in operations or []:
        operation = dict(operation)
        existing_blocked = bool(operation.get("planning_blocked"))
        access = assess_setup_access(
            capability,
            operation.get("setup_label"),
            bool(operation.get("requires_simultaneous_5_axis")),
        )
        if operation.get("operation_type") == "Manual Review":
            access = {
                "status": "manual_review",
                "method": "unsupported_geometry",
                "blocked": True,
                "warning": (
                    "No validated planning rule exists for this feature type. "
                    "Route it to CAM/process engineering."
                ),
            }
        operation["machine_axis_count"] = capability["axis_count"]
        operation["machine_indexed_3plus2"] = capability["indexed_3plus2"]
        operation["machine_simultaneous_5_axis"] = capability["simultaneous_5_axis"]
        operation["accessibility_status"] = access["status"]
        operation["setup_method"] = access["method"]
        operation["planning_blocked"] = existing_blocked or access["blocked"]
        operation["capability_warning"] = access["warning"]
        if access["warning"]:
            notes = str(operation.get("notes") or "")
            operation["notes"] = f"{notes} | {access['warning']}".strip(" |")
        assessed.append(operation)
    return assessed


def machine_feasibility_summary(operations):
    operations = list(operations or [])
    return {
        "blocked": sum(1 for operation in operations if operation.get("planning_blocked")),
        "manual_review": sum(
            1
            for operation in operations
            if operation.get("accessibility_status") == "manual_review"
        ),
        "requires_setup": sum(
            1
            for operation in operations
            if operation.get("accessibility_status") == "requires_setup"
        ),
        "indexed": sum(
            1
            for operation in operations
            if operation.get("setup_method") == "indexed_3plus2"
        ),
    }
