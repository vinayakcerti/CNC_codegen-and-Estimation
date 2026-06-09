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
from modules.operation_planner import plan_operations


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
        },
    ]


def main():
    tools = get_default_tools()
    material = get_default_materials()[0]
    operations = plan_operations(_audit_17b_features(), tools, material)

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

    if any(op.get("_depth", 0) > 30 for op in operations if op.get("feature_type") == "Edge Milling"):
        raise AssertionError("edge milling operation depth/height should remain physically realistic")

    print("PASS operation plan regression: 17b step strategy and setup sequencing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
