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
