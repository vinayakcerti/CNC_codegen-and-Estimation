"""
VMC handover smoke test.

Runs the operator-handover samples through the non-UI pipeline:
detect CAD candidates -> convert to machining features -> plan operations ->
estimate time -> generate draft G-code.

Usage:
    python tests/run_vmc_handover_smoke.py
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.data_store import get_default_materials, get_default_machines, get_default_tools
from modules.gcode_generator import generate_gcode
from modules.operation_planner import plan_operations
from modules.step_parser import detect_feature_candidates_from_cadquery_file
from modules.time_estimator import estimate_time

_TEST_SAMPLES_DIR = _PROJECT_ROOT / "test_samples"

HANDOVER_SAMPLES = [
    "M03_vmc_blind_rectangular_pocket.step",
    "M07_vmc_chamfered_plate.step",
    "M02_vmc_slot_plate.step",
    "17b_top_milled_step_shoulder-Body.step",
    "M05_vmc_large_bore_plate.step",
    "25_vmc_job_plate_all_basic_features.step",
]


def _candidate_to_feature(candidate, priority):
    ftype = candidate.get("feature_type") or "Unknown"
    return {
        "feature_name": candidate.get("feature_name") or ftype,
        "feature_type": ftype,
        "quantity": int(candidate.get("quantity") or 1),
        "x_pos": float(candidate.get("x_pos") or 0.0),
        "y_pos": float(candidate.get("y_pos") or 0.0),
        "diameter": float(candidate.get("diameter") or 0.0),
        "length": float(candidate.get("length") or 0.0),
        "width": float(candidate.get("width") or 0.0),
        "depth": float(candidate.get("depth") or 0.0),
        "tolerance_note": candidate.get("tolerance_note") or "",
        "priority": priority,
        "machining_action": "Machine",
        "selected_for_machining": True,
    }


def _stock_from_features(features):
    length = max((f.get("length") or 0.0) for f in features) if features else 150.0
    width = max((f.get("width") or 0.0) for f in features) if features else 100.0
    depth = max((f.get("depth") or 0.0) for f in features) if features else 50.0
    return {
        "length": max(length, 150.0),
        "width": max(width, 100.0),
        "height": max(depth, 50.0),
        "part_volume": 0.0,
        "stock_volume": 0.0,
    }


def main():
    tools = get_default_tools()
    material = get_default_materials()[0]
    machine = get_default_machines()[0]
    failures = []

    print("=" * 72)
    print("VMC Handover Smoke Test")
    print(f"Samples dir: {_TEST_SAMPLES_DIR}")
    print("=" * 72)

    for sample in HANDOVER_SAMPLES:
        path = _TEST_SAMPLES_DIR / sample
        print(f"\n[RUN] {sample}")

        if not path.exists():
            failures.append((sample, "missing STEP file"))
            print("  FAIL: missing STEP file")
            continue

        try:
            detection = detect_feature_candidates_from_cadquery_file(str(path))
            if not detection.get("success"):
                warnings = detection.get("warnings") or ["parser returned success=False"]
                raise RuntimeError("; ".join(warnings))

            candidates = detection.get("candidate_features", [])
            if not candidates:
                raise RuntimeError("no CAD candidates detected")

            features = [
                _candidate_to_feature(candidate, priority=i + 1)
                for i, candidate in enumerate(candidates)
            ]
            operations = plan_operations(features, tools, material)
            if not operations:
                raise RuntimeError("operation planner returned no operations")

            estimate = estimate_time(operations, machine, material, features)
            if estimate.get("total_machine_time_min", 0) <= 0:
                raise RuntimeError("time estimate is not positive")

            gcode = generate_gcode(operations, machine, _stock_from_features(features))
            if "DO NOT RUN" not in gcode:
                raise RuntimeError("draft G-code safety header missing")
            if "M30" not in gcode:
                raise RuntimeError("draft G-code program end missing")

            print(
                "  PASS: "
                f"{len(candidates)} candidate(s), "
                f"{len(operations)} operation(s), "
                f"{estimate['total_machine_time_min']:.2f} min"
            )
        except Exception as exc:
            failures.append((sample, str(exc)))
            print(f"  FAIL: {exc}")

    print("\n" + "=" * 72)
    if failures:
        print(f"Result: {len(failures)} FAILURE(S)")
        for sample, reason in failures:
            print(f"  {sample}: {reason}")
        return 1

    print("Result: ALL HANDOVER SMOKE TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
