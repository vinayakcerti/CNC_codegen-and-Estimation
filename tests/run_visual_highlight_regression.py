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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
