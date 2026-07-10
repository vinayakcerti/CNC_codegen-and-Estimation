"""
Visual-preview regression checks for feature highlighting.

Uses a tiny synthetic mesh so this catches UI marker regressions without needing
CadQuery or a real STEP file.
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.visual_preview import build_step_mesh3d
from modules.step_parser import (
    detect_feature_candidates_from_cadquery_file,
    parse_step_auto,
)
from modules.stock_allowance import apply_stock_allowance_to_candidates


def _box_mesh():
    return {
        "x": [0, 100, 100, 0, 0, 100, 100, 0],
        "y": [0, 0, 60, 60, 0, 0, 60, 60],
        "z": [0, 0, 0, 0, 20, 20, 20, 20],
        "i": [0, 0, 0, 4, 4, 4, 0, 1, 2, 3, 0, 1],
        "j": [1, 2, 4, 5, 6, 7, 4, 5, 6, 7, 1, 2],
        "k": [2, 3, 5, 6, 7, 3, 1, 2, 5, 6, 5, 6],
    }


def main():
    slot = {
        "candidate_id": "S001",
        "feature_name": "Flat-ended slot 40x10 mm",
        "feature_type": "Slot",
        "x_pos": 50.0,
        "y_pos": 30.0,
        "length": 40.0,
        "width": 10.0,
        "depth": 8.0,
        "detection_source": "flat_ended_slot_walls",
        "detection_note": "X-pair: gap=40.0 mm; Y-pair: gap=10.0 mm",
    }
    fig = build_step_mesh3d(
        _box_mesh(),
        {"length": 100.0, "width": 60.0, "height": 20.0},
        candidates=[slot],
        highlighted_candidate_ids={"S001"},
    )
    highlighted_meshes = [
        tr for tr in fig.data
        if tr.type == "mesh3d" and getattr(tr, "name", "") == "Highlighted"
    ]
    if not highlighted_meshes:
        raise AssertionError("highlighted slot should render a filled Mesh3d patch")

    print("PASS visual highlight regression: slot highlight has filled patch")
    _run_17b_edge_highlight_check()
    _run_slide_base_highlight_check()
    return 0


def _run_17b_edge_highlight_check():
    sample = _PROJECT_ROOT / "test_samples" / "17b_top_milled_step_shoulder-Body.step"
    detection = detect_feature_candidates_from_cadquery_file(str(sample))
    bbox = parse_step_auto(sample.read_bytes())
    candidates = apply_stock_allowance_to_candidates(
        detection.get("candidate_features", []),
        {"length": 120.0, "width": 100.0, "height": 40.0},
        bbox,
        include_edge_milling=True,
    )
    edge_candidates = [
        candidate
        for candidate in candidates
        if candidate.get("feature_type") == "Edge Milling"
    ]
    if len(edge_candidates) != 2:
        raise AssertionError(f"17b should expose 2 Y-edge candidates, got {len(edge_candidates)}")

    import cadquery as cq
    cq_result = cq.importers.importStep(str(sample))
    verts, tris = cq_result.val().tessellate(0.5)
    mesh = {
        "x": [v.x for v in verts],
        "y": [v.y for v in verts],
        "z": [v.z for v in verts],
        "i": [t[0] for t in tris],
        "j": [t[1] for t in tris],
        "k": [t[2] for t in tris],
    }
    fig = build_step_mesh3d(
        mesh,
        {},
        candidates=edge_candidates,
        highlighted_candidate_ids={
            candidate["candidate_id"] for candidate in edge_candidates
        },
    )
    traces = [
        trace
        for trace in fig.data
        if trace.type == "scatter3d" and getattr(trace, "name", "") == "Highlighted"
    ]
    if len(traces) != 2:
        raise AssertionError(f"expected 2 highlighted edge perimeters, got {len(traces)}")

    ranges = {
        "x": (min(mesh["x"]), max(mesh["x"])),
        "y": (min(mesh["y"]), max(mesh["y"])),
        "z": (min(mesh["z"]), max(mesh["z"])),
    }
    for trace in traces:
        points = list(zip(trace.x, trace.y, trace.z))
        for axis, values in zip(("x", "y", "z"), (trace.x, trace.y, trace.z)):
            lower, upper = ranges[axis]
            if any(value < lower - 1e-6 or value > upper + 1e-6 for value in values):
                raise AssertionError(
                    f"17b edge highlight escaped mesh {axis}-range {ranges[axis]}: {list(values)}"
                )
        for start, end in zip(points, points[1:]):
            changed_axes = sum(
                abs(float(a) - float(b)) > 1e-6
                for a, b in zip(start, end)
            )
            if changed_axes > 1:
                raise AssertionError(
                    f"17b edge perimeter contains detached diagonal segment: {start} -> {end}"
                )

    print("PASS 17b edge highlight regression: CAD-bound axis-aligned perimeters")


def _run_slide_base_highlight_check():
    sample = _PROJECT_ROOT / "test_samples" / "3100171001_01 SLIDE BASE-1812 ( FOR TOOL LOADER ).STEP"
    detection = detect_feature_candidates_from_cadquery_file(str(sample))
    if not detection.get("success"):
        raise AssertionError(f"slide-base detection failed: {detection.get('warnings')}")

    candidates = detection.get("candidate_features", [])
    hole = next((c for c in candidates if c.get("feature_type") == "Hole"), None)
    slot = next((c for c in candidates if c.get("feature_type") == "Slot"), None)
    if hole is None:
        raise AssertionError("slide-base sample should expose at least one hole candidate")
    if slot is None:
        raise AssertionError("slide-base sample should expose at least one slot candidate")
    if not hole.get("face_mesh_data"):
        raise AssertionError("slide-base hole candidate should have CAD face mesh data")

    import cadquery as cq
    cq_result = cq.importers.importStep(str(sample))
    verts, tris = cq_result.val().tessellate(0.5)
    mesh = {
        "x": [v.x for v in verts],
        "y": [v.y for v in verts],
        "z": [v.z for v in verts],
        "i": [t[0] for t in tris],
        "j": [t[1] for t in tris],
        "k": [t[2] for t in tris],
    }

    hole_fig = build_step_mesh3d(
        mesh,
        {},
        candidates=[hole],
        highlighted_candidate_ids={hole["candidate_id"]},
    )
    if not any(tr.type == "mesh3d" and getattr(tr, "name", "") == "Highlighted" for tr in hole_fig.data):
        raise AssertionError("slide-base hole highlight should render a highlighted CAD face mesh")

    slot_fig = build_step_mesh3d(
        mesh,
        {},
        candidates=[slot],
        highlighted_candidate_ids={slot["candidate_id"]},
    )
    if not any(tr.type == "mesh3d" and getattr(tr, "name", "") == "Highlighted" for tr in slot_fig.data):
        raise AssertionError("slide-base slot highlight should render a highlighted marker patch")

    print("PASS slide-base highlight regression: hole and slot highlights render")
    _run_slide_base_grouping_check(candidates)


def _run_slide_base_grouping_check(candidates):
    # Grouping logic moved out of the retired Streamlit app.py into a module.
    from modules import review_grouping as app

    groups = app._build_candidate_groups(candidates, "Weldment / Fabricated Part")
    slot_candidates = [c for c in candidates if c.get("feature_type") == "Slot"]
    slot_groups = [g for g in groups if g.get("feature_type") == "Slot"]
    review_locations = sum(g.get("count", 0) for g in slot_groups)
    detected_slots = len(slot_candidates)

    if detected_slots <= 0:
        raise AssertionError("slide-base grouping check needs slot candidates")
    if review_locations >= detected_slots:
        raise AssertionError(
            f"slide-base grouped review should reduce noisy slot detections "
            f"({review_locations} review locations from {detected_slots} detections)"
        )
    if not any(g.get("detected_count", g.get("count", 0)) > g.get("count", 0) for g in slot_groups):
        raise AssertionError("slide-base grouped review should expose collapsed detected-face counts")

    print(
        "PASS slide-base grouped review regression: "
        f"{detected_slots} slot detections -> {review_locations} review locations"
    )


if __name__ == "__main__":
    raise SystemExit(main())
