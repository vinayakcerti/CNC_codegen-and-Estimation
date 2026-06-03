"""
Regression for V1 stock-allowance feedback.

Configured raw stock allowance should update face-milling depth and create
selectable edge-milling work for side stock cleanup.
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.step_parser import detect_feature_candidates_from_cadquery_file, parse_step_bounding_box
from modules.stock_allowance import apply_stock_allowance_to_candidates


SAMPLES = [
    "M03_vmc_blind_rectangular_pocket.step",
    "M07_vmc_chamfered_plate.step",
    "M02_vmc_slot_plate.step",
    "17b_top_milled_step_shoulder-Body.step",
]


def _run_sample(sample):
    path = _PROJECT_ROOT / "test_samples" / sample
    bbox = parse_step_bounding_box(path.read_bytes())
    if not bbox.get("success"):
        raise AssertionError(f"{sample}: bbox parse failed: {bbox.get('message')}")

    detection = detect_feature_candidates_from_cadquery_file(str(path))
    if not detection.get("success"):
        raise AssertionError(f"{sample}: detection failed: {detection.get('warnings')}")

    stock = {
        "length": bbox["length_mm"] + 10.0,
        "width": bbox["width_mm"] + 10.0,
        "height": bbox["height_mm"] + 5.0,
    }
    adjusted = apply_stock_allowance_to_candidates(
        detection.get("candidate_features", []),
        stock,
        bbox,
        include_edge_milling=True,
    )

    face_depths = {
        round(float(c.get("depth") or 0), 3)
        for c in adjusted
        if c.get("feature_type") == "Face Milling"
    }
    edge_count = sum(1 for c in adjusted if c.get("feature_type") == "Edge Milling")

    if face_depths != {2.5}:
        raise AssertionError(f"{sample}: expected face depth 2.5 mm, got {sorted(face_depths)}")
    if edge_count != 4:
        raise AssertionError(f"{sample}: expected 4 edge milling candidates, got {edge_count}")

    return len(adjusted), edge_count


def main():
    print("=" * 72)
    print("Stock Allowance Regression")
    print("=" * 72)
    for sample in SAMPLES:
        total, edge_count = _run_sample(sample)
        print(f"PASS {sample}: {total} adjusted candidates, {edge_count} edge milling")
    print("=" * 72)
    print("Result: STOCK ALLOWANCE REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
