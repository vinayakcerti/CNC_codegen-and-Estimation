"""Regression checks for idempotent, operation-driven time estimates."""

import sys
from copy import deepcopy
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.data_store import (
    get_default_machines,
    get_default_materials,
    get_default_tools,
)
from modules.operation_planner import plan_operations
from modules.time_estimator import estimate_time


def main():
    feature = {
        "feature_name": "Slot 50 x 12 depth 6 mm",
        "feature_type": "Slot",
        "quantity": 1,
        "x_pos": 40.0,
        "y_pos": 25.0,
        "length": 50.0,
        "width": 12.0,
        "depth": 6.0,
        "priority": 2,
        "setup_label": "Top",
        "physical_feature_id": "SLOT-PHYSICAL-001",
    }
    operations = plan_operations(
        [feature],
        get_default_tools(),
        get_default_materials()[0],
    )
    machine = get_default_machines()[0]
    material = get_default_materials()[0]
    baseline = estimate_time(operations, machine, material, [feature])

    duplicated = estimate_time(
        operations + deepcopy(operations),
        machine,
        material,
        [feature, deepcopy(feature)],
    )
    if duplicated != baseline:
        raise AssertionError("duplicate operation rows should not inflate the estimate")

    reference_feature = {
        "feature_name": "Existing reference hole",
        "feature_type": "Hole",
        "x_pos": 10000.0,
        "y_pos": 10000.0,
        "selected_for_machining": False,
    }
    with_reference = estimate_time(
        operations,
        machine,
        material,
        [feature, reference_feature],
    )
    if with_reference != baseline:
        raise AssertionError("non-machining reference features should not affect estimates")

    expected_total = round(
        baseline["setup_time_min"]
        + baseline["cutting_time_min"]
        + baseline["rapid_time_min"]
        + baseline["tool_change_time_min"],
        2,
    )
    if baseline["total_machine_time_min"] != expected_total:
        raise AssertionError(
            f"estimate components do not reconcile: {baseline} vs {expected_total}"
        )
    if baseline["num_operations"] != len(operations):
        raise AssertionError("operation count should match unique planned operations")

    print("PASS estimate integrity regression: duplicate and reference inputs are neutral")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
