"""Helpers for keeping uploaded-part state isolated between jobs."""


DEFAULT_STOCK = {
    "length": 150.0,
    "width": 100.0,
    "height": 50.0,
    "part_volume": 600.0,
    "stock_volume": 750.0,
    "part_offset_x": 0.0,
    "part_offset_y": 0.0,
    "part_offset_z": 0.0,
}


_IMPORT_DERIVED_KEYS = (
    "uploaded_filename",
    "uploaded_file_hash",
    "step_parse_result",
    "step_geometry",
    "step_mesh_data",
    "features_from_candidates",
    "operations",
    "time_result",
    "_tess_error",
    "_smw_preview_candidates",
)


def clear_import_derived_state(state, *, reset_stock=True):
    """Remove results belonging to the previously uploaded part."""
    for key in _IMPORT_DERIVED_KEYS:
        state.pop(key, None)

    state["features"] = []
    state["step_candidates"] = []
    state["step_candidate_warnings"] = []
    state["added_candidate_ids"] = set()
    if reset_stock:
        state["stock"] = dict(DEFAULT_STOCK)


def validate_session_consistency(state) -> list:
    """Return a list of consistency warnings for the current session state.

    Each warning is a dict with keys: level ("warning" or "info"), message, key.
    An empty list means the session is consistent.
    """
    warnings = []

    features = state.get("features", [])
    parse_ok  = state.get("step_parse_result", {}).get("success", False)

    if features and not parse_ok:
        warnings.append({
            "level": "warning",
            "key":   "stale_features",
            "message": (
                f"{len(features)} accepted feature(s) are present in this session "
                "but no STEP file has been successfully parsed. "
                "These features may be left over from a previous Streamlit restart. "
                "Upload a STEP file or use Reset Current Job to start fresh."
            ),
        })

    candidates = state.get("step_candidates", [])
    if candidates and not parse_ok:
        warnings.append({
            "level": "info",
            "key":   "stale_candidates",
            "message": (
                "Feature candidates are present without an active STEP parse result. "
                "Re-upload the STEP file to restore geometry."
            ),
        })

    degraded = state.get("step_parse_result", {}).get("degraded_mode", False)
    if degraded:
        warnings.append({
            "level": "info",
            "key":   "degraded_mode",
            "message": (
                "CadQuery/OpenCASCADE is unavailable. "
                "Bounding-box geometry is approximate and feature detection is disabled. "
                "The 3D solid preview is not available in this mode."
            ),
        })

    return warnings
