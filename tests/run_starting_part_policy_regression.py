"""Regression checks for billet, casting, weldment, and rework semantics."""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.starting_part_policy import (
    CASTING,
    RAW_BILLET,
    REWORK,
    WELDMENT,
    prepare_candidates_for_starting_part,
)
from modules.step_parser import (
    detect_feature_candidates_from_cadquery_file,
    parse_step_auto,
)


def _load(sample):
    path = _PROJECT_ROOT / "test_samples" / sample
    part = parse_step_auto(path.read_bytes())
    detection = detect_feature_candidates_from_cadquery_file(str(path))
    if not detection.get("success"):
        raise AssertionError(f"{sample}: detection failed: {detection.get('warnings')}")
    return part, detection.get("candidate_features", [])


def _assert_non_raw(prepared, starting_part_type):
    candidates = prepared["candidates"]
    if any(c.get("feature_type") == "Edge Milling" for c in candidates):
        raise AssertionError(f"{starting_part_type}: must not infer billet edge milling")
    if any(c.get("detection_source") == "stock_allowance" for c in candidates):
        raise AssertionError(f"{starting_part_type}: stock-derived candidates are invalid")
    for candidate in candidates:
        if candidate.get("starting_part_type") != starting_part_type:
            raise AssertionError(f"{starting_part_type}: candidate policy annotation missing")
        if not candidate.get("requires_operator_selection"):
            raise AssertionError(f"{starting_part_type}: operator selection must be required")
        if not candidate.get("existing_geometry"):
            raise AssertionError(f"{starting_part_type}: geometry must default to existing")
        if candidate.get("default_machining_action") != "Existing Geometry – No Machining":
            raise AssertionError(f"{starting_part_type}: incorrect default action")
        if candidate.get("allowance_uncertainty") != "unknown":
            raise AssertionError(f"{starting_part_type}: allowance must remain uncertain")


def main():
    part, candidates = _load("M03_vmc_blind_rectangular_pocket.step")
    oversized_stock = {
        "length": float(part["length_mm"]) + 10.0,
        "width": float(part["width_mm"]) + 10.0,
        "height": float(part["height_mm"]) + 5.0,
    }

    billet = prepare_candidates_for_starting_part(
        candidates,
        oversized_stock,
        part,
        RAW_BILLET,
    )
    billet_edges = [
        candidate
        for candidate in billet["candidates"]
        if candidate.get("feature_type") == "Edge Milling"
    ]
    if len(billet_edges) != 4:
        raise AssertionError(f"billet mode should derive four edge candidates, got {len(billet_edges)}")
    billet_face_depths = {
        round(float(candidate.get("depth") or 0.0), 3)
        for candidate in billet["candidates"]
        if candidate.get("feature_type") == "Face Milling"
    }
    if billet_face_depths != {2.5}:
        raise AssertionError(f"billet face allowance should be 2.5 mm, got {billet_face_depths}")

    invalid_billet = prepare_candidates_for_starting_part(
        candidates,
        {
            "length": float(part["length_mm"]) - 1.0,
            "width": float(part["width_mm"]),
            "height": float(part["height_mm"]),
        },
        part,
        RAW_BILLET,
    )
    if not invalid_billet["errors"]:
        raise AssertionError("undersized billet should return blocking errors")
    if any(
        candidate.get("detection_source") == "stock_allowance"
        for candidate in invalid_billet["candidates"]
    ):
        raise AssertionError("invalid billet must not create stock-derived work")

    for starting_part_type in (CASTING, REWORK):
        prepared = prepare_candidates_for_starting_part(
            candidates,
            oversized_stock,
            part,
            starting_part_type,
        )
        _assert_non_raw(prepared, starting_part_type)
        non_raw_depths = {
            round(float(candidate.get("depth") or 0.0), 3)
            for candidate in prepared["candidates"]
            if "face mill" in str(candidate.get("feature_type") or "").lower()
        }
        if non_raw_depths == {2.5}:
            raise AssertionError(
                f"{starting_part_type}: oversized stock must not change face depth"
            )
        if not prepared["warnings"]:
            raise AssertionError(f"{starting_part_type}: operator guidance warning missing")

    slide_part, slide_candidates = _load(
        "3100171001_01 SLIDE BASE-1812 ( FOR TOOL LOADER ).STEP"
    )
    weldment = prepare_candidates_for_starting_part(
        slide_candidates,
        {
            "length": slide_part["length_mm"],
            "width": slide_part["width_mm"],
            "height": slide_part["height_mm"],
        },
        slide_part,
        WELDMENT,
    )
    _assert_non_raw(weldment, WELDMENT)
    if len(weldment["candidates"]) != len(slide_candidates):
        raise AssertionError("weldment policy should preserve detected review candidates")
    warning_text = " ".join(weldment["warnings"])
    if "28 solids" not in warning_text:
        raise AssertionError(f"multi-solid weldment warning missing: {weldment['warnings']}")
    if not any(c.get("feature_type") == "Slot" for c in weldment["candidates"]):
        raise AssertionError("weldment review must retain slot candidates for selection")

    print(
        "PASS starting-part policy regression: billet allowance isolated; "
        "casting, weldment, and rework require explicit selection"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
