"""Verify feature detection is invariant to axis-aligned STEP orientation."""

import collections
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import cadquery as cq

from modules.step_parser import (
    detect_feature_candidates_from_cadquery_file,
    parse_step_auto,
)
from modules.stock_allowance import apply_stock_allowance_to_candidates


_SAMPLES = {
    "M01_vmc_basic_plate_holes.step": {
        "counts": {"Face milling": 2, "Hole": 4},
    },
    "M02_vmc_slot_plate.step": {
        "counts": {"Face milling": 2, "Slot": 1},
    },
    "M03_vmc_blind_rectangular_pocket.step": {
        "counts": {"Face milling": 2, "Pocket": 1},
    },
    "M07_vmc_chamfered_plate.step": {
        "counts": {"Face milling": 2, "Hole": 4, "Chamfer": 1},
    },
    "17b_top_milled_step_shoulder-Body.step": {
        "counts": {"Face Milling": 2, "Step": 1},
        "stock": {"length": 130.0, "width": 100.0, "height": 40.0},
    },
}

_ROTATIONS = {
    "x_neg90": ((1, 0, 0), -90),
    "x_pos90": ((1, 0, 0), 90),
    "y_neg90": ((0, 1, 0), -90),
    "y_pos90": ((0, 1, 0), 90),
}


def _counts(candidates):
    return dict(collections.Counter(
        candidate.get("feature_type")
        for candidate in candidates
        if candidate.get("feature_type") != "Edge Milling"
    ))


def _stock_from_bbox(bbox):
    return {
        "length": float(bbox["length_mm"]),
        "width": float(bbox["width_mm"]),
        "height": float(bbox["height_mm"]),
    }


def _rounded(value):
    return None if value is None else round(float(value), 3)


def _signature(candidates, mirror_x=False, mirror_y=False):
    transform = next(
        (
            candidate.get("coordinate_transform")
            for candidate in candidates
            if candidate.get("coordinate_transform")
        ),
        {},
    )
    spans = transform.get("work_spans") or (0.0, 0.0, 0.0)
    rows = []
    for candidate in candidates:
        work = candidate.get("work_position") or {}
        work_x = _rounded(work.get("x"))
        work_y = _rounded(work.get("y"))
        if mirror_x and work_x is not None:
            work_x = _rounded(float(spans[0]) - work_x)
        if mirror_y and work_y is not None:
            work_y = _rounded(float(spans[1]) - work_y)
        setup = candidate.get("work_setup_label") or candidate.get("setup_label")
        if mirror_x:
            setup = {"Left": "Right", "Right": "Left"}.get(setup, setup)
        if mirror_y:
            setup = {"Front": "Back", "Back": "Front"}.get(setup, setup)
        rows.append((
            candidate.get("feature_type"),
            _rounded(candidate.get("diameter")),
            _rounded(candidate.get("length")),
            _rounded(candidate.get("width")),
            _rounded(candidate.get("depth")),
            setup,
            work_x,
            work_y,
            _rounded(work.get("z")),
        ))
    return sorted(rows, key=lambda row: tuple("" if value is None else str(value) for value in row))


def _detect_with_stock(path, stock):
    bbox = parse_step_auto(path.read_bytes())
    detection = detect_feature_candidates_from_cadquery_file(str(path))
    adjusted = apply_stock_allowance_to_candidates(
        detection.get("candidate_features", []),
        stock,
        bbox,
        include_edge_milling=True,
    )
    return adjusted


def _rotated_copy(source, target, axis, angle):
    imported = cq.importers.importStep(str(source))
    rotated = imported.rotate((0, 0, 0), axis, angle)
    cq.exporters.export(rotated.val(), str(target), exportType="STEP")
    if not target.exists():
        raise AssertionError(f"CadQuery did not create rotated STEP file: {target}")


def main():
    samples_dir = _PROJECT_ROOT / "test_samples"
    failures = []
    temp_root = _PROJECT_ROOT / ".codex-runtime" / "orientation-metamorphic"
    temp_root.mkdir(parents=True, exist_ok=True)
    for name, expectation in _SAMPLES.items():
        source = samples_dir / name
        source_bbox = parse_step_auto(source.read_bytes())
        stock = expectation.get("stock") or _stock_from_bbox(source_bbox)
        baseline_candidates = _detect_with_stock(source, stock)
        baseline = _counts(baseline_candidates)

        if baseline != expectation["counts"]:
            failures.append(
                f"{name}: baseline expected {expectation['counts']}, got {baseline}"
            )
            continue
        for rotation_name, (axis, angle) in _ROTATIONS.items():
            rotated_path = temp_root / f"{rotation_name}_{name}"
            _rotated_copy(source, rotated_path, axis, angle)
            rotated_candidates = _detect_with_stock(rotated_path, stock)
            rotated = _counts(rotated_candidates)

            if rotated != baseline:
                failures.append(
                    f"{name} [{rotation_name}]: result differs; "
                    f"baseline={baseline}, rotated={rotated}"
                )
                continue
            baseline_signature = _signature(baseline_candidates)
            equivalent_signatures = {
                tuple(_signature(
                    rotated_candidates,
                    mirror_x=mirror_x,
                    mirror_y=mirror_y,
                ))
                for mirror_x in (False, True)
                for mirror_y in (False, True)
            }
            if tuple(baseline_signature) not in equivalent_signatures:
                failures.append(
                    f"{name} [{rotation_name}]: geometry/setup signature differs; "
                    f"baseline={baseline_signature}, "
                    f"rotated={_signature(rotated_candidates)}"
                )
                continue
            print(f"PASS {name} [{rotation_name}]: {rotated}")

    if failures:
        print("\n".join(f"FAIL {failure}" for failure in failures))
        return 1
    print("PASS orientation metamorphic regression")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
