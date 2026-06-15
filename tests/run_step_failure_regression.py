"""Regression checks for controlled STEP import failures and stale-state cleanup."""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import modules.step_parser as step_parser
from modules.session_integrity import DEFAULT_STOCK, clear_import_derived_state


def _assert_failure(payload, reason):
    result = step_parser.parse_step_auto(payload)
    assert result["success"] is False, result
    assert result["failure_reason"] == reason, result
    assert result.get("message")
    assert result.get("suggestion")


def main():
    _assert_failure(b"", "EMPTY_FILE")
    _assert_failure(b"this is not a CAD file", "NOT_STEP_FILE")
    _assert_failure(
        b"ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\n"
        b"#1=CARTESIAN_POINT('',(0.,0.,0.));",
        "TRUNCATED_STEP_FILE",
    )

    original_limit = step_parser.MAX_STEP_FILE_BYTES
    try:
        step_parser.MAX_STEP_FILE_BYTES = 16
        _assert_failure(b"x" * 17, "FILE_TOO_LARGE")
    finally:
        step_parser.MAX_STEP_FILE_BYTES = original_limit

    state = {
        "uploaded_filename": "old.step",
        "uploaded_file_hash": "old",
        "step_parse_result": {"success": True},
        "step_geometry": {"success": True},
        "step_mesh_data": {"x": [1]},
        "step_candidates": [{"candidate_id": "OLD"}],
        "step_candidate_warnings": ["old"],
        "added_candidate_ids": {"OLD"},
        "features": [{"id": "OLD"}],
        "features_from_candidates": True,
        "operations": [{"operation": "old"}],
        "time_result": {"minutes": 1},
        "_tess_error": "old",
        "_smw_preview_candidates": [{"candidate_id": "OLD"}],
        "machine": {"name": "keep"},
    }
    clear_import_derived_state(state)
    assert state["machine"] == {"name": "keep"}
    assert state["stock"] == DEFAULT_STOCK
    assert state["features"] == []
    assert state["step_candidates"] == []
    for key in (
        "uploaded_filename",
        "uploaded_file_hash",
        "step_parse_result",
        "step_geometry",
        "step_mesh_data",
        "operations",
        "_smw_preview_candidates",
    ):
        assert key not in state, key

    sample = PROJECT_ROOT / "test_samples" / "M03_vmc_blind_rectangular_pocket.step"
    assert sample.exists()
    old_disable = os.environ.get("CNC_DISABLE_CADQUERY")
    old_available = step_parser._CADQUERY_AVAILABLE
    old_cq = step_parser.cq
    try:
        os.environ["CNC_DISABLE_CADQUERY"] = "1"
        step_parser._CADQUERY_AVAILABLE = None
        step_parser.cq = None
        result = step_parser.parse_step_auto(sample.read_bytes())
        assert result["success"] is True, result
        assert result["degraded_mode"] is True
        assert result["deep_feature_detection_available"] is False
        assert result["candidate_features"] == []
        assert result.get("cadquery_warning")
    finally:
        if old_disable is None:
            os.environ.pop("CNC_DISABLE_CADQUERY", None)
        else:
            os.environ["CNC_DISABLE_CADQUERY"] = old_disable
        step_parser._CADQUERY_AVAILABLE = old_available
        step_parser.cq = old_cq

    print("PASS: STEP failures are controlled and prior-part state is cleared")


if __name__ == "__main__":
    main()
