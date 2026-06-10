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

from modules.step_parser import detect_feature_candidates_from_cadquery_file, parse_step_auto, parse_step_bounding_box
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


def _run_helper_edges():
    candidates = [{
        "candidate_id": "F001",
        "feature_name": "Face milling top surface",
        "feature_type": "Face milling",
        "quantity": 1,
        "length": 100.0,
        "width": 50.0,
        "depth": 1.0,
    }]
    part = {
        "length_mm": 100.0,
        "width_mm": 50.0,
        "height_mm": 20.0,
        "x_range": (0.0, 100.0),
        "y_range": (0.0, 50.0),
    }

    non_raw = apply_stock_allowance_to_candidates(
        candidates,
        {"length": 110.0, "width": 60.0, "height": 25.0},
        part,
        include_edge_milling=False,
    )
    if any(c.get("feature_type") == "Edge Milling" for c in non_raw):
        raise AssertionError("non-raw workflow should not auto-add edge milling")

    review_visible = apply_stock_allowance_to_candidates(
        candidates,
        {"length": 110.0, "width": 60.0, "height": 25.0},
        part,
        include_edge_milling=True,
    )
    review_edge_count = sum(1 for c in review_visible if c.get("feature_type") == "Edge Milling")
    if review_edge_count != 4:
        raise AssertionError(
            f"review-mode allowance should surface 4 edge candidates, got {review_edge_count}"
        )
    edge_setups = {
        c.get("setup_label")
        for c in review_visible
        if c.get("feature_type") == "Edge Milling"
    }
    if edge_setups != {"Left", "Right", "Front", "Back"}:
        raise AssertionError(f"edge milling should carry side setup labels, got {sorted(edge_setups)}")

    tiny_allowance = apply_stock_allowance_to_candidates(
        candidates,
        {"length": 100.005, "width": 50.005, "height": 20.005},
        part,
        include_edge_milling=True,
    )
    if any(c.get("feature_type") == "Edge Milling" for c in tiny_allowance):
        raise AssertionError("tiny stock noise should not create edge milling")
    tiny_depths = {round(float(c.get("depth") or 0), 3) for c in tiny_allowance}
    if tiny_depths != {1.0}:
        raise AssertionError(f"tiny stock noise should preserve detected depth, got {tiny_depths}")

    x_only = apply_stock_allowance_to_candidates(
        candidates,
        {"length": 110.0, "width": 50.0, "height": 25.0},
        part,
        include_edge_milling=True,
    )
    edge_count = sum(1 for c in x_only if c.get("feature_type") == "Edge Milling")
    if edge_count != 2:
        raise AssertionError(f"X-only allowance should create 2 edge candidates, got {edge_count}")


def _run_17b_audit_stock_orientation():
    sample = "17b_top_milled_step_shoulder-Body.step"
    path = _PROJECT_ROOT / "test_samples" / sample
    bbox = parse_step_auto(path.read_bytes())
    detection = detect_feature_candidates_from_cadquery_file(str(path))
    adjusted = apply_stock_allowance_to_candidates(
        detection.get("candidate_features", []),
        {"length": 130.0, "width": 100.0, "height": 40.0},
        bbox,
        include_edge_milling=True,
    )

    face_rows = [c for c in adjusted if c.get("feature_type") == "Face Milling"]
    if len(face_rows) != 2:
        raise AssertionError(f"{sample}: expected 2 face milling candidates, got {len(face_rows)}")
    for face in face_rows:
        dims = (
            round(float(face.get("length") or 0), 3),
            round(float(face.get("width") or 0), 3),
            round(float(face.get("depth") or 0), 3),
        )
        if dims != (130.0, 100.0, 5.0):
            raise AssertionError(f"{sample}: expected face milling 130x100 depth 5, got {dims}")

    step = next((c for c in adjusted if c.get("feature_type") == "Step"), None)
    if step is None:
        raise AssertionError(f"{sample}: missing step candidate")
    step_dims = (
        round(float(step.get("length") or 0), 3),
        round(float(step.get("width") or 0), 3),
        round(float(step.get("depth") or 0), 3),
    )
    if step_dims != (90.0, 90.0, 12.0):
        raise AssertionError(f"{sample}: expected step 90x90 depth 12, got {step_dims}")

    edge_depths = {
        round(float(c.get("depth") or 0), 3)
        for c in adjusted
        if c.get("feature_type") == "Edge Milling"
    }
    if edge_depths != {5.0}:
        raise AssertionError(f"{sample}: expected all edge depths 5 mm, got {sorted(edge_depths)}")
    edge_setups = {
        c.get("setup_label")
        for c in adjusted
        if c.get("feature_type") == "Edge Milling"
    }
    if edge_setups != {"Left", "Right", "Front", "Back"}:
        raise AssertionError(f"{sample}: expected side setup labels, got {sorted(edge_setups)}")

    y_edges = {
        c.get("edge_side"): c
        for c in adjusted
        if c.get("feature_type") == "Edge Milling" and c.get("edge_axis") == "Y"
    }
    expected_visual_bounds = {
        "Y-": {
            "x_min": -45.0, "x_max": 75.0,
            "y_min": 0.0, "y_max": 30.0,
            "z_min": 0.0, "z_max": 0.0,
        },
        "Y+": {
            "x_min": -45.0, "x_max": 75.0,
            "y_min": 0.0, "y_max": 30.0,
            "z_min": 90.0, "z_max": 90.0,
        },
    }
    for side, expected in expected_visual_bounds.items():
        actual = y_edges.get(side, {}).get("visual_bounds")
        if actual != expected:
            raise AssertionError(
                f"{sample}: {side} visual bounds should follow CAD axes, got {actual}"
            )


def main():
    print("=" * 72)
    print("Stock Allowance Regression")
    print("=" * 72)
    for sample in SAMPLES:
        total, edge_count = _run_sample(sample)
        print(f"PASS {sample}: {total} adjusted candidates, {edge_count} edge milling")
    _run_helper_edges()
    print("PASS helper edge cases: non-raw, review-visible, tiny allowance, one-axis allowance")
    _run_17b_audit_stock_orientation()
    print("PASS 17b audit stock orientation: face, edge, and step dimensions corrected")
    print("=" * 72)
    print("Result: STOCK ALLOWANCE REGRESSION PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
