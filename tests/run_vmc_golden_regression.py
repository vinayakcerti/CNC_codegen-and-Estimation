"""Golden and invariant regression for representative VMC milling samples."""

import hashlib
import json
import sys
from collections import Counter
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.step_parser import (
    detect_feature_candidates_from_cadquery_file,
    parse_step_auto,
)
from modules.stock_allowance import apply_stock_allowance_to_candidates


_EXPECTATIONS = _SCRIPT_DIR / "vmc_golden_expectations.json"
_SAMPLES = _PROJECT_ROOT / "test_samples"


def _counts(candidates):
    return dict(Counter(candidate.get("feature_type") for candidate in candidates))


def _assert_close(actual, expected, label, tolerance=0.01):
    if abs(float(actual) - float(expected)) > tolerance:
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _candidate_signature(candidate):
    return (
        candidate.get("candidate_id"),
        candidate.get("feature_type"),
        round(float(candidate.get("x_pos") or 0.0), 4),
        round(float(candidate.get("y_pos") or 0.0), 4),
        round(float(candidate.get("diameter") or 0.0), 4),
        round(float(candidate.get("length") or 0.0), 4),
        round(float(candidate.get("width") or 0.0), 4),
        round(float(candidate.get("depth") or 0.0), 4),
        tuple(candidate.get("face_indices") or ()),
    )


def _validate_schema(data):
    if data.get("schema_version") != 1:
        raise AssertionError("unsupported golden schema version")
    samples = data.get("samples")
    if not isinstance(samples, list) or not samples:
        raise AssertionError("golden schema requires non-empty samples")
    required = {
        "file", "sha256", "review_status", "bbox_mm", "stock_mm",
        "work_axes_from_cad", "detected_counts", "adjusted_counts",
    }
    for index, entry in enumerate(samples):
        missing = required - set(entry)
        if missing:
            raise AssertionError(f"sample #{index + 1} missing fields: {sorted(missing)}")


def _match_required_feature(candidates, expected):
    matches = [
        candidate for candidate in candidates
        if candidate.get("feature_type") == expected["type"]
        and (candidate.get("work_setup_label") or candidate.get("setup_label")) == expected["setup"]
    ]
    for candidate in matches:
        if all(
            abs(float(candidate.get(key) or 0.0) - float(expected[key])) <= 0.01
            for key in ("length", "width", "depth")
        ):
            return
    raise AssertionError(f"missing required feature {expected}; matches={matches}")


def _validate_candidate_invariants(entry, bbox, detected, adjusted):
    ids = [candidate.get("candidate_id") for candidate in detected]
    if len(ids) != len(set(ids)):
        raise AssertionError(f"{entry['file']}: duplicate candidate IDs")
    if any(not candidate.get("face_indices") for candidate in detected):
        missing = [
            candidate.get("candidate_id")
            for candidate in detected
            if not candidate.get("face_indices")
        ]
        raise AssertionError(f"{entry['file']}: missing CAD provenance for {missing}")
    if any(not candidate.get("cad_position") for candidate in detected):
        raise AssertionError(f"{entry['file']}: detected candidate missing CAD position")

    transform = next(
        (
            candidate.get("coordinate_transform")
            for candidate in adjusted
            if candidate.get("coordinate_transform")
        ),
        None,
    )
    if not transform:
        raise AssertionError(f"{entry['file']}: missing coordinate transform")
    if transform.get("work_axes_from_cad") != entry["work_axes_from_cad"]:
        raise AssertionError(
            f"{entry['file']}: expected axes {entry['work_axes_from_cad']}, "
            f"got {transform.get('work_axes_from_cad')}"
        )
    spans = transform.get("work_spans") or []
    for candidate in adjusted:
        position = candidate.get("work_position")
        if not position:
            continue
        for axis, span in zip(("x", "y", "z"), spans):
            value = float(position[axis])
            if value < -0.01 or value > float(span) + 0.01:
                raise AssertionError(
                    f"{entry['file']} {candidate.get('candidate_id')}: "
                    f"work {axis}={value} outside 0..{span}"
                )

    exact_types = {"Face milling", "Face Milling", "Hole", "Large hole / boring", "Pocket", "Chamfer"}
    missing_mesh = [
        candidate.get("candidate_id")
        for candidate in adjusted
        if candidate.get("feature_type") in exact_types
        and candidate.get("detection_source") != "stock_allowance"
        and not candidate.get("face_mesh_data")
    ]
    if missing_mesh:
        raise AssertionError(f"{entry['file']}: exact candidates missing face mesh {missing_mesh}")


def _run_sample(entry):
    path = _SAMPLES / entry["file"]
    if not path.exists():
        raise AssertionError(f"missing golden sample: {entry['file']}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != entry["sha256"]:
        raise AssertionError(f"{entry['file']}: file hash changed")

    bbox = parse_step_auto(path.read_bytes())
    actual_bbox = [bbox.get("length_mm"), bbox.get("width_mm"), bbox.get("height_mm")]
    for axis, actual, expected in zip("XYZ", actual_bbox, entry["bbox_mm"]):
        _assert_close(actual, expected, f"{entry['file']} bbox {axis}")

    first = detect_feature_candidates_from_cadquery_file(str(path))
    second = detect_feature_candidates_from_cadquery_file(str(path))
    if not first.get("success") or not second.get("success"):
        raise AssertionError(f"{entry['file']}: detection failed")
    detected = first.get("candidate_features", [])
    if _counts(detected) != entry["detected_counts"]:
        raise AssertionError(
            f"{entry['file']}: detected counts expected {entry['detected_counts']}, "
            f"got {_counts(detected)}"
        )
    if sorted(map(_candidate_signature, detected)) != sorted(
        map(_candidate_signature, second.get("candidate_features", []))
    ):
        raise AssertionError(f"{entry['file']}: candidate identity is unstable across reruns")

    stock = dict(zip(("length", "width", "height"), entry["stock_mm"]))
    adjusted = apply_stock_allowance_to_candidates(
        detected,
        stock,
        bbox,
        include_edge_milling=True,
    )
    if _counts(adjusted) != entry["adjusted_counts"]:
        raise AssertionError(
            f"{entry['file']}: adjusted counts expected {entry['adjusted_counts']}, "
            f"got {_counts(adjusted)}"
        )
    _validate_candidate_invariants(entry, bbox, detected, adjusted)
    for expected in entry.get("required_features", []):
        _match_required_feature(adjusted, expected)

    grouping = entry.get("grouping")
    if grouping:
        # Grouping logic moved out of the retired Streamlit app.py into a module.
        from modules import review_grouping as app
        groups = app._build_candidate_groups(adjusted, grouping["starting_part_type"])
        locations = sum(
            group.get("count", 0)
            for group in groups
            if group.get("feature_type") == "Slot"
        )
        if locations != grouping["slot_review_locations"]:
            raise AssertionError(
                f"{entry['file']}: expected {grouping['slot_review_locations']} "
                f"slot review locations, got {locations}"
            )

    return len(detected), len(adjusted), entry["review_status"]


def main():
    data = json.loads(_EXPECTATIONS.read_text(encoding="utf-8"))
    _validate_schema(data)
    print("=" * 72)
    print("VMC Golden Regression")
    print("=" * 72)
    for entry in data["samples"]:
        detected, adjusted, review_status = _run_sample(entry)
        print(
            f"PASS {entry['file']}: {detected} detected, {adjusted} adjusted "
            f"[{review_status}]"
        )
    print("=" * 72)
    print(f"Result: {len(data['samples'])} GOLDEN SAMPLES PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
