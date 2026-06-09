"""
Regression checks for operation-plan quality.
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.data_store import get_default_materials, get_default_tools
from modules.gcode_generator import generate_gcode
from modules.operation_planner import (
    is_secondary_setup_operation,
    plan_operations,
    secondary_setup_labels,
)
from modules.setup_sheet import generate_setup_sheet


def _audit_17b_features():
    return [
        {
            "feature_name": "Face milling - top surface",
            "feature_type": "Face Milling",
            "quantity": 1,
            "x_pos": 10.0,
            "y_pos": 14.0,
            "diameter": 0.0,
            "length": 130.0,
            "width": 100.0,
            "depth": 5.0,
            "priority": 1,
            "setup_label": "Top",
        },
        {
            "feature_name": "Face milling - bottom surface",
            "feature_type": "Face Milling",
            "quantity": 1,
            "x_pos": 10.0,
            "y_pos": 14.0,
            "diameter": 0.0,
            "length": 130.0,
            "width": 100.0,
            "depth": 5.0,
            "priority": 1,
            "setup_label": "Bottom",
        },
        {
            "feature_name": "Edge milling X- stock allowance",
            "feature_type": "Edge Milling",
            "quantity": 1,
            "x_pos": -45.0,
            "y_pos": 45.0,
            "diameter": 0.0,
            "length": 90.0,
            "width": 30.0,
            "depth": 5.0,
            "priority": 1,
            "setup_label": "Left",
        },
        {
            "feature_name": "Step shoulder 90.0x90.0 depth 12.0 mm",
            "feature_type": "Step",
            "quantity": 1,
            "x_pos": 60.0,
            "y_pos": 18.0,
            "diameter": 0.0,
            "length": 90.0,
            "width": 90.0,
            "depth": 12.0,
            "priority": 3,
            "setup_label": "Top",
        },
    ]


def _unsupported_bore_feature():
    return [{
        "feature_name": "Large bore requiring review",
        "feature_type": "Large Hole / Boring",
        "quantity": 1,
        "x_pos": 30.0,
        "y_pos": 30.0,
        "diameter": 15.0,
        "length": 0.0,
        "width": 0.0,
        "depth": 20.0,
        "priority": 2,
        "setup_label": "Top",
    }]


def main():
    tools = get_default_tools()
    material = get_default_materials()[0]
    operations = plan_operations(_audit_17b_features(), tools, material)
    duplicate_operations = plan_operations(_audit_17b_features() + _audit_17b_features(), tools, material)
    if len(duplicate_operations) != len(operations):
        raise AssertionError(
            f"duplicate features should not duplicate operations "
            f"({len(duplicate_operations)} vs {len(operations)})"
        )

    step_ops = [op for op in operations if op.get("feature_type") == "Step"]
    step_names = [op.get("feature_name", "") for op in step_ops]
    step_types = [op.get("operation_type", "") for op in step_ops]
    if step_types != ["Rough End Mill", "Finish End Mill", "Finish End Mill"]:
        raise AssertionError(f"expected rough + two finish step operations, got {step_types}")
    if not any("floor finish" in name for name in step_names):
        raise AssertionError(f"missing step floor finish operation: {step_names}")
    if not any("wall finish" in name for name in step_names):
        raise AssertionError(f"missing shoulder wall finish operation: {step_names}")

    bottom_idx = next(
        i for i, op in enumerate(operations)
        if op.get("feature_type") == "Face Milling" and "bottom" in op.get("feature_name", "").lower()
    )
    if bottom_idx != len(operations) - 1:
        raise AssertionError("bottom face milling should remain last as setup-2 work")
    if operations[bottom_idx].get("setup_label") != "Bottom":
        raise AssertionError("bottom face milling should carry Bottom setup label")
    if any(not op.get("setup_label") for op in operations):
        raise AssertionError("all planned operations should carry a setup label")
    secondary_labels = secondary_setup_labels(operations)
    if secondary_labels != ["Left", "Bottom"]:
        raise AssertionError(f"expected Left and Bottom secondary setups, got {secondary_labels}")
    if not any(is_secondary_setup_operation(op) for op in operations if op.get("setup_label") == "Left"):
        raise AssertionError("left edge milling should be treated as additional setup work")

    if any(op.get("_depth", 0) > 30 for op in operations if op.get("feature_type") == "Edge Milling"):
        raise AssertionError("edge milling operation depth/height should remain physically realistic")

    bore_ops = plan_operations(_unsupported_bore_feature(), tools, material)
    boring_op = next(op for op in bore_ops if op.get("operation_type") == "Boring")
    if "min bore" not in boring_op.get("tool_warning", ""):
        raise AssertionError(f"expected boring min-bore warning, got {boring_op.get('tool_warning')!r}")
    if boring_op.get("tool_warning", "") not in boring_op.get("notes", ""):
        raise AssertionError("boring tool warning should be included in operation notes")

    html = generate_setup_sheet(
        operations,
        {"machine_name": "VMC", "controller": "Fanuc"},
        material,
        {"length": 130.0, "width": 100.0, "height": 40.0},
        _audit_17b_features(),
        {"total_machine_time_min": 1, "cutting_time_min": 1, "setup_time_min": 0},
        job_name="17b audit",
    )
    for expected in ("<th>X</th>", "<th>Y</th>", "<th>L</th>", "<th>W</th>", "<th>D</th>"):
        if expected not in html:
            raise AssertionError(f"setup sheet missing geometry column {expected}")
    if "<th>Setup</th>" not in html or "<td>Bottom</td>" not in html:
        raise AssertionError("setup sheet missing setup labels")

    gcode = generate_gcode(operations, {"machine_name": "VMC", "controller": "Fanuc"}, {
        "length": 130.0,
        "width": 100.0,
        "height": 40.0,
    })
    if "ADDITIONAL SETUP - LEFT ORIENTATION" not in gcode:
        raise AssertionError("draft G-code missing left-side setup separator")
    if "SETUP 2" not in gcode:
        raise AssertionError("draft G-code missing bottom flip separator")
    for expected in ("130.0", "100.0", "90.0", "12.0"):
        if expected not in html:
            raise AssertionError(f"setup sheet missing audit dimension {expected}")

    print("PASS operation plan regression: 17b step strategy and setup sequencing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
