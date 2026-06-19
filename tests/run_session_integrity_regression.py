"""Regression checks for session state consistency and restart isolation."""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from modules.session_integrity import (
    DEFAULT_STOCK,
    clear_import_derived_state,
    validate_session_consistency,
)


def test_validate_clean_session():
    """Empty session is consistent — no warnings."""
    state = {"features": [], "step_candidates": [], "stock": dict(DEFAULT_STOCK)}
    warnings = validate_session_consistency(state)
    assert warnings == [], warnings


def test_validate_healthy_session():
    """Features + active parse result is consistent."""
    state = {
        "features": [{"id": "FACE-001"}],
        "step_parse_result": {"success": True},
    }
    warnings = validate_session_consistency(state)
    stale = [w for w in warnings if w["key"] == "stale_features"]
    assert stale == [], warnings


def test_validate_stale_features_detected():
    """Features without a parse result → stale_features warning."""
    state = {
        "features": [{"id": "FACE-001"}, {"id": "HOLE-002"}],
        "step_parse_result": {"success": False},
    }
    warnings = validate_session_consistency(state)
    keys = [w["key"] for w in warnings]
    assert "stale_features" in keys, warnings
    w = next(w for w in warnings if w["key"] == "stale_features")
    assert w["level"] == "warning"
    assert "2 accepted" in w["message"]


def test_validate_stale_features_no_parse_at_all():
    """Features present but step_parse_result entirely missing → still detected."""
    state = {"features": [{"id": "FACE-001"}]}
    warnings = validate_session_consistency(state)
    keys = [w["key"] for w in warnings]
    assert "stale_features" in keys, warnings


def test_validate_degraded_mode():
    """parse_result with degraded_mode=True triggers info notice."""
    state = {
        "features": [],
        "step_parse_result": {"success": True, "degraded_mode": True},
    }
    warnings = validate_session_consistency(state)
    keys = [w["key"] for w in warnings]
    assert "degraded_mode" in keys, warnings
    w = next(w for w in warnings if w["key"] == "degraded_mode")
    assert w["level"] == "info"


def test_validate_degraded_mode_off():
    """degraded_mode=False produces no degraded_mode warning."""
    state = {
        "features": [],
        "step_parse_result": {"success": True, "degraded_mode": False},
    }
    warnings = validate_session_consistency(state)
    keys = [w["key"] for w in warnings]
    assert "degraded_mode" not in keys, warnings


def test_clear_import_derived_state_uses_default_stock():
    """clear_import_derived_state resets stock to DEFAULT_STOCK, not a different dict."""
    state = {
        "stock": {"length": 999.0, "width": 999.0, "height": 999.0},
        "features": [{"id": "X"}],
    }
    clear_import_derived_state(state)
    assert state["stock"] == DEFAULT_STOCK, state["stock"]


def test_default_stock_not_mutated():
    """clear_import_derived_state produces a copy of DEFAULT_STOCK, not the same object."""
    state = {}
    clear_import_derived_state(state)
    state["stock"]["length"] = 9999.0
    assert DEFAULT_STOCK["length"] != 9999.0, "DEFAULT_STOCK was mutated"


def main():
    test_validate_clean_session()
    test_validate_healthy_session()
    test_validate_stale_features_detected()
    test_validate_stale_features_no_parse_at_all()
    test_validate_degraded_mode()
    test_validate_degraded_mode_off()
    test_clear_import_derived_state_uses_default_stock()
    test_default_stock_not_mutated()
    print("PASS: session integrity regression — all consistency checks pass")


if __name__ == "__main__":
    main()
