"""Regression checks for stable CAD feature identity and idempotent acceptance."""

import shutil
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import app
from modules.step_parser import (
    assign_stable_candidate_ids,
    detect_feature_candidates_from_cadquery_file,
)


_SAMPLE = _PROJECT_ROOT / "test_samples" / "17b_top_milled_step_shoulder-Body.step"
_RUNTIME_DIR = _PROJECT_ROOT / ".codex-runtime" / "identity-regression"


def _identity_map(candidates):
    return {
        (
            candidate.get("feature_type"),
            tuple(candidate.get("face_indices") or ()),
            round(float(candidate.get("x_pos") or 0.0), 4),
            round(float(candidate.get("y_pos") or 0.0), 4),
            round(float(candidate.get("depth") or 0.0), 4),
        ): (
            candidate.get("physical_feature_id"),
            candidate.get("candidate_id"),
        )
        for candidate in candidates
    }


def _synthetic_candidate(face_indices):
    return {
        "feature_type": "Pocket",
        "feature_name": "Pocket 40 x 20 depth 8 mm",
        "quantity": 1,
        "x_pos": 12.0,
        "y_pos": 18.0,
        "z_pos": 30.0,
        "cad_position": {"x": 12.0, "y": 18.0, "z": 30.0},
        "length": 40.0,
        "width": 20.0,
        "depth": 8.0,
        "setup_label": "Top",
        "face_indices": list(face_indices),
        "detection_source": "pocket_floor",
    }


def _assert_detector_identity():
    if not _SAMPLE.exists():
        raise AssertionError(f"missing identity sample: {_SAMPLE.name}")

    _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    copied_sample = _RUNTIME_DIR / "renamed-copy.step"
    shutil.copyfile(_SAMPLE, copied_sample)

    first = detect_feature_candidates_from_cadquery_file(str(_SAMPLE))
    second = detect_feature_candidates_from_cadquery_file(str(_SAMPLE))
    copied = detect_feature_candidates_from_cadquery_file(str(copied_sample))
    for label, result in (("first", first), ("second", second), ("copy", copied)):
        if not result.get("success"):
            raise AssertionError(f"{label} detector run failed: {result.get('warnings')}")

    first_candidates = first.get("candidate_features", [])
    if not first_candidates:
        raise AssertionError("identity sample produced no candidates")
    first_map = _identity_map(first_candidates)
    if first_map != _identity_map(second.get("candidate_features", [])):
        raise AssertionError("candidate identity changed between identical reruns")
    if first_map != _identity_map(copied.get("candidate_features", [])):
        raise AssertionError("candidate identity changed when the same bytes were renamed")
    if first.get("source_file_hash") != copied.get("source_file_hash"):
        raise AssertionError("identical file bytes should produce the same source hash")

    ids = [
        candidate.get("candidate_id")
        for candidate in first_candidates
    ]
    physical_ids = [
        candidate.get("physical_feature_id")
        for candidate in first_candidates
    ]
    if not all(ids) or len(ids) != len(set(ids)):
        raise AssertionError("detected candidates require unique stable candidate IDs")
    if not all(physical_ids):
        raise AssertionError("detected candidates require physical feature IDs")


def _assert_synthetic_identity():
    first = _synthetic_candidate([10, 11])
    split = _synthetic_candidate([12, 13])
    assign_stable_candidate_ids([first, split], "source-a")
    if first["physical_feature_id"] != split["physical_feature_id"]:
        raise AssertionError("face-split detections should share physical identity")
    if first["candidate_id"] == split["candidate_id"]:
        raise AssertionError("face-split detections should retain distinct exact IDs")

    changed_source = _synthetic_candidate([10, 11])
    assign_stable_candidate_ids([changed_source], "source-b")
    if changed_source["physical_feature_id"] == first["physical_feature_id"]:
        raise AssertionError("changed source content must produce a new physical identity")

    ordered = [_synthetic_candidate([20]), _synthetic_candidate([21])]
    reversed_order = [_synthetic_candidate([21]), _synthetic_candidate([20])]
    assign_stable_candidate_ids(ordered, "source-order")
    assign_stable_candidate_ids(reversed_order, "source-order")
    ordered_map = {
        tuple(candidate["face_indices"]): candidate["candidate_id"]
        for candidate in ordered
    }
    reversed_map = {
        tuple(candidate["face_indices"]): candidate["candidate_id"]
        for candidate in reversed_order
    }
    if ordered_map != reversed_map:
        raise AssertionError("candidate identity must not depend on detector ordering")

    st.session_state.clear()
    st.session_state.features = []
    st.session_state.added_candidate_ids = set()
    first_row = pd.DataFrame([{
        "candidate_id": first["candidate_id"],
        "accept": True,
        "machining_action": "Machine",
    }])
    if app._commit_candidate_selections(first_row, [first]) != 1:
        raise AssertionError("first physical feature should be accepted")

    st.session_state.added_candidate_ids = set()
    split_row = pd.DataFrame([{
        "candidate_id": split["candidate_id"],
        "accept": True,
        "machining_action": "Machine",
    }])
    if app._commit_candidate_selections(split_row, [split]) != 0:
        raise AssertionError("face-split detection must not duplicate an accepted feature")
    if len(st.session_state.features) != 1:
        raise AssertionError("physical identity deduplication should leave one feature")
    if split["physical_feature_id"] not in st.session_state.added_candidate_ids:
        raise AssertionError("duplicate physical detection should be marked as added")


def _assert_group_acceptance():
    first = _synthetic_candidate([30])
    second = _synthetic_candidate([31])
    second["x_pos"] = 55.0
    second["cad_position"] = {"x": 55.0, "y": 18.0, "z": 30.0}
    assign_stable_candidate_ids([first, second], "group-source")

    st.session_state.clear()
    st.session_state.features = []
    st.session_state.added_candidate_ids = set()
    group = {
        "member_ids": [first["candidate_id"], second["candidate_id"]],
    }
    edited = pd.DataFrame([{
        "_group_idx": 0,
        "accept": True,
        "machining_action": "Machine",
    }])
    if app._commit_group_selections(edited, [group], [first, second]) != 2:
        raise AssertionError("first grouped commit should accept both physical features")

    split_first = _synthetic_candidate([32])
    repeated_second = _synthetic_candidate([31])
    repeated_second["x_pos"] = 55.0
    repeated_second["cad_position"] = {"x": 55.0, "y": 18.0, "z": 30.0}
    assign_stable_candidate_ids([split_first, repeated_second], "group-source")
    repeated_group = {
        "member_ids": [
            split_first["candidate_id"],
            repeated_second["candidate_id"],
        ],
    }
    st.session_state.added_candidate_ids = set()
    if (
        app._commit_group_selections(
            edited,
            [repeated_group],
            [split_first, repeated_second],
        )
        != 0
    ):
        raise AssertionError("re-detected group must not duplicate accepted features")
    if len(st.session_state.features) != 2:
        raise AssertionError("group acceptance should remain idempotent")
    expected_added = {
        split_first["physical_feature_id"],
        repeated_second["physical_feature_id"],
    }
    if not expected_added.issubset(st.session_state.added_candidate_ids):
        raise AssertionError("re-detected group should restore physical added status")


def main():
    _assert_detector_identity()
    _assert_synthetic_identity()
    _assert_group_acceptance()
    print(
        "PASS feature identity regression: stable reruns, source isolation, "
        "face-split deduplication, grouping, ordering independence"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
