"""Regression checks for the canonical CAD-to-work coordinate transform."""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.geometry_transform import (
    attach_work_coordinates,
    build_transform,
    infer_work_transform,
    transform_mesh_and_candidates,
)
from modules.step_parser import (
    detect_feature_candidates_from_cadquery_file,
    parse_step_auto,
)
from modules.stock_allowance import apply_stock_allowance_to_candidates


def _assert_close(actual, expected, label):
    if len(actual) != len(expected) or any(
        abs(float(a) - float(e)) > 1e-6
        for a, e in zip(actual, expected)
    ):
        raise AssertionError(f"{label}: expected {expected}, got {actual}")


def _run_basic_transforms():
    dims = {
        "x_range": (-60.0, 60.0),
        "y_range": (-100.0, 100.0),
        "z_range": (0.0, 30.0),
    }
    transform = build_transform(dims)
    _assert_close(transform.point(-60, -100, 0), (0, 0, 0), "minimum corner")
    _assert_close(transform.point(60, 100, 30), (120, 200, 30), "maximum corner")
    _assert_close(transform.inverse_point(0, 0, 0), (-60, -100, 0), "inverse minimum")
    _assert_close(transform.inverse_point(120, 200, 30), (60, 100, 30), "inverse maximum")
    if transform.setup_label(0, 0, 1) != "Top":
        raise AssertionError("positive CAD Z normal should map to Top")

    reversed_x = build_transform(dims, signs=(-1, 1, 1))
    _assert_close(reversed_x.point(60, -100, 0), (0, 0, 0), "reversed X origin")
    _assert_close(reversed_x.inverse_point(0, 0, 0), (60, -100, 0), "inverse reversed X")
    _assert_close(reversed_x.inverse_vector(1, 0, 0), (-1, 0, 0), "inverse vector")
    if reversed_x.setup_label(1, 0, 0) != "Left":
        raise AssertionError("positive CAD X normal should map to Left after X reversal")


def _run_17b_orientation():
    sample = _PROJECT_ROOT / "test_samples" / "17b_top_milled_step_shoulder-Body.step"
    bbox = parse_step_auto(sample.read_bytes())
    transform = infer_work_transform(
        bbox,
        {"length": 130.0, "width": 100.0, "height": 40.0},
    )
    if transform.work_axes != ("x", "z", "y"):
        raise AssertionError(f"17b should use CAD X/Z/Y work axes, got {transform.work_axes}")
    _assert_close(transform.work_spans, (120, 90, 30), "17b work spans")
    _assert_close(transform.point(-45, 0, 0), (0, 0, 0), "17b minimum corner")
    _assert_close(transform.point(75, 30, 90), (120, 90, 30), "17b maximum corner")
    if transform.setup_label(0, 1, 0) != "Top":
        raise AssertionError("17b positive CAD Y normal should map to work Top")

    detection = detect_feature_candidates_from_cadquery_file(str(sample))
    adjusted = apply_stock_allowance_to_candidates(
        detection.get("candidate_features", []),
        {"length": 130.0, "width": 100.0, "height": 40.0},
        bbox,
        include_edge_milling=True,
    )
    exact_candidates = [
        candidate for candidate in adjusted
        if candidate.get("cad_position")
    ]
    if len(exact_candidates) < 3:
        raise AssertionError("17b exact candidates should retain CAD positions")
    face_setups = {
        candidate.get("work_setup_label") or candidate.get("setup_label")
        for candidate in adjusted
        if candidate.get("feature_type") == "Face Milling"
    }
    if face_setups != {"Top", "Bottom"}:
        raise AssertionError(f"17b should select work Top/Bottom faces, got {face_setups}")
    for face in [
        candidate for candidate in adjusted
        if candidate.get("feature_type") == "Face Milling"
    ]:
        if not face.get("face_mesh_data"):
            raise AssertionError("17b work-oriented face milling should retain exact face mesh")
    for candidate in exact_candidates:
        work = candidate.get("work_position")
        if not work:
            raise AssertionError(f"{candidate.get('candidate_id')}: missing work position")
        spans = transform.work_spans
        for axis, span in zip(("x", "y", "z"), spans):
            if not (-1e-6 <= float(work[axis]) <= span + 1e-6):
                raise AssertionError(
                    f"{candidate.get('candidate_id')}: work {axis}={work[axis]} "
                    f"outside 0..{span}"
                )

    step = next(candidate for candidate in exact_candidates if candidate.get("feature_type") == "Step")
    source_setup = step.get("cad_setup_label")
    transformed_setup = step.get("work_setup_label")
    if source_setup != "Back" or transformed_setup != "Top":
        raise AssertionError(
            f"17b setup mapping should preserve CAD Back and expose work Top, "
            f"got {source_setup}/{transformed_setup}"
        )


def _run_candidate_attachment():
    transform = build_transform({
        "x_range": (10.0, 20.0),
        "y_range": (30.0, 50.0),
        "z_range": (-5.0, 5.0),
    })
    candidate = attach_work_coordinates({
        "candidate_id": "TEST",
        "x_pos": 15.0,
        "y_pos": 40.0,
        "z_pos": 0.0,
    }, transform)
    if candidate["cad_position"] != {"x": 15.0, "y": 40.0, "z": 0.0}:
        raise AssertionError("candidate CAD position changed")
    if candidate["work_position"] != {"x": 5.0, "y": 10.0, "z": 5.0}:
        raise AssertionError(f"candidate work position incorrect: {candidate['work_position']}")


def _run_mesh_and_candidate_transform():
    """Epic 19: 3D-viewer mesh and face overlays must render in work frame.

    Regression for the operator-reported bug where the mesh hover tooltip
    showed raw CAD-centered coordinates (e.g. y=100, half of a 200mm-wide
    part) instead of corner-origin work coordinates (y=200 at the far edge).
    """
    dims = {
        "x_range": (-60.0, 60.0),
        "y_range": (-100.0, 100.0),
        "z_range": (0.0, 30.0),
    }
    transform = build_transform(dims)

    mesh_data = {
        "x": [-60.0, 60.0, 60.0],
        "y": [-100.0, 100.0, -100.0],
        "z": [0.0, 30.0, 0.0],
        "i": [0], "j": [1], "k": [2],
    }
    candidates = [{
        "candidate_id": "H001",
        "feature_type": "Hole",
        "x_pos": 45.0,
        "y_pos": 85.0,
        "z_pos": 30.0,
        "face_mesh_data": [{
            "vertices": [[45.0, 85.0, 30.0], [50.0, 85.0, 30.0]],
            "triangles": [[0, 1, 0]],
            "face_index": 7,
        }],
    }]

    new_mesh, new_candidates = transform_mesh_and_candidates(mesh_data, candidates, transform)

    _assert_close(
        (min(new_mesh["x"]), max(new_mesh["x"])), (0.0, 120.0), "mesh x work-frame range",
    )
    _assert_close(
        (min(new_mesh["y"]), max(new_mesh["y"])), (0.0, 200.0), "mesh y work-frame range",
    )
    _assert_close(
        (min(new_mesh["z"]), max(new_mesh["z"])), (0.0, 30.0), "mesh z work-frame range",
    )
    if new_mesh["i"] != mesh_data["i"]:
        raise AssertionError("triangle indices must pass through unchanged")

    cand = new_candidates[0]
    _assert_close((cand["x_pos"], cand["y_pos"], cand["z_pos"]), (105.0, 185.0, 30.0),
                  "candidate position transformed to work frame")
    new_verts = cand["face_mesh_data"][0]["vertices"]
    _assert_close(new_verts[0], (105.0, 185.0, 30.0), "face mesh vertex 0 transformed")
    _assert_close(new_verts[1], (110.0, 185.0, 30.0), "face mesh vertex 1 transformed")

    # Original inputs must not be mutated — other code paths (stock_allowance.py)
    # depend on x_pos/y_pos/face_mesh_data staying in the raw CAD frame.
    if mesh_data["x"] != [-60.0, 60.0, 60.0]:
        raise AssertionError("input mesh_data was mutated")
    if candidates[0]["x_pos"] != 45.0:
        raise AssertionError("input candidate was mutated")
    if candidates[0]["face_mesh_data"][0]["vertices"][0] != [45.0, 85.0, 30.0]:
        raise AssertionError("input face_mesh_data vertices were mutated")


def main():
    _run_basic_transforms()
    print("PASS basic coordinate transforms")
    _run_candidate_attachment()
    print("PASS candidate CAD/work coordinate preservation")
    _run_17b_orientation()
    print("PASS 17b CAD-to-work orientation and candidate bounds")
    _run_mesh_and_candidate_transform()
    print("PASS mesh and face-overlay transform to work frame (Epic 19)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
