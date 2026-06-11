"""
Regression checks for accepting CAD candidates into the feature list.

These tests focus on app-level commit behavior that is not covered by the
geometry detector regressions.
"""

import sys
from pathlib import Path

import pandas as pd
import streamlit as st

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import app


def _reset_feature_state():
    st.session_state.clear()
    st.session_state.features = []
    st.session_state.added_candidate_ids = set()


def _face_milling_candidate():
    return {
        "candidate_id": "FM_TOP",
        "feature_name": "Face milling - top surface",
        "feature_type": "Face milling",
        "quantity": 1,
        "x_pos": 10.0,
        "y_pos": 14.0,
        "work_position": {"x": 60.0, "y": 18.0, "z": 30.0},
        "work_setup_label": "Top",
        "cad_position": {"x": 10.0, "y": 14.0, "z": 90.0},
        "diameter": 0.0,
        "length": 120.0,
        "width": 30.0,
        "depth": 1.0,
        "priority": 1,
    }


def main():
    _reset_feature_state()
    candidates = [_face_milling_candidate()]
    edited = pd.DataFrame([{
        "candidate_id": "FM_TOP",
        "accept": True,
        "machining_action": "Machine",
    }])

    first_added = app._commit_candidate_selections(edited, candidates)
    if first_added != 1 or len(st.session_state.features) != 1:
        raise AssertionError("first candidate commit should add one feature")
    accepted = st.session_state.features[0]
    if (accepted["x_pos"], accepted["y_pos"], accepted["z_pos"]) != (60.0, 18.0, 30.0):
        raise AssertionError(f"accepted feature should use work coordinates, got {accepted}")
    if accepted.get("setup_label") != "Top":
        raise AssertionError("accepted feature should use work setup orientation")
    if accepted.get("cad_position") != {"x": 10.0, "y": 14.0, "z": 90.0}:
        raise AssertionError("accepted feature should preserve CAD provenance")

    # Simulate reprocessing/reloading the STEP file, which historically reset
    # added_candidate_ids and allowed the same face milling rows to append again.
    st.session_state.added_candidate_ids = set()
    second_added = app._commit_candidate_selections(edited, candidates)
    if second_added != 0 or len(st.session_state.features) != 1:
        raise AssertionError("duplicate candidate commit should not append a second feature")

    print("PASS candidate commit regression: duplicate accepted candidate is skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
