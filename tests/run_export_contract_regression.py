"""Regression checks for operation-plan CSV and setup-sheet traceability."""

import sys
from io import StringIO
from pathlib import Path

import pandas as pd

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.data_store import get_default_materials, get_default_tools
from modules.operation_planner import plan_operations
from modules.setup_sheet import generate_setup_sheet


def main():
    feature = {
        "feature_name": "Pocket 40 x 20 depth 8 mm",
        "feature_type": "Pocket",
        "quantity": 1,
        "x_pos": 25.0,
        "y_pos": 30.0,
        "diameter": 0.0,
        "length": 40.0,
        "width": 20.0,
        "depth": 8.0,
        "priority": 2,
        "setup_label": "Top",
        "source_candidate_id": "POCKET-CANDIDATE-001",
        "physical_feature_id": "POCKET-PHYSICAL-001",
    }
    operations = plan_operations(
        [feature],
        get_default_tools(),
        get_default_materials()[0],
    )
    if len(operations) != 2:
        raise AssertionError(f"expected pocket rough and finish operations, got {len(operations)}")

    required_columns = {
        "operation_id",
        "source_candidate_id",
        "physical_feature_id",
        "setup_label",
        "_x_pos",
        "_y_pos",
        "_length",
        "_width",
        "_depth",
    }
    frame = pd.DataFrame(operations)
    missing = required_columns - set(frame.columns)
    if missing:
        raise AssertionError(f"operation CSV contract missing columns: {sorted(missing)}")

    csv_text = frame.to_csv(index=False)
    round_trip = pd.read_csv(StringIO(csv_text), keep_default_na=False)
    if set(round_trip["operation_id"]) != {
        operation["operation_id"] for operation in operations
    }:
        raise AssertionError("operation IDs changed during CSV round trip")
    if set(round_trip["physical_feature_id"]) != {"POCKET-PHYSICAL-001"}:
        raise AssertionError("physical feature ID missing from CSV")

    html = generate_setup_sheet(
        operations,
        {"machine_name": "VMC", "controller": "Fanuc"},
        get_default_materials()[0],
        {"length": 100.0, "width": 80.0, "height": 30.0},
        [feature],
        {
            "total_machine_time_min": 10.0,
            "cutting_time_min": 2.0,
            "setup_time_min": 8.0,
            "num_operations": len(operations),
        },
        job_name="Export contract",
    )
    for expected in (
        "<th>Operation ID</th>",
        "<th>Feature ID</th>",
        "POCKET-PHYSICAL-001",
        operations[0]["operation_id"],
        operations[1]["operation_id"],
    ):
        if expected not in html:
            raise AssertionError(f"setup sheet traceability missing {expected}")

    print("PASS export contract regression: CSV and setup sheet retain traceability")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
