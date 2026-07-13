"""Starting-part semantics for billet, casting, weldment, and rework planning."""

import copy

from modules.geometry_transform import infer_work_transform
from modules.stock_allowance import (
    analyze_rectangular_stock,
    apply_stock_allowance_to_candidates,
)


RAW_BILLET = "Raw Block / Billet"
CASTING = "Casting / Forging"
WELDMENT = "Weldment / Fabricated Part"
REWORK = "Existing Part / Rework"


_PROFILES = {
    RAW_BILLET: {
        "work_scope": "bulk_material_removal",
        "default_action": "Machine",
        "allowance_source": "configured_rectangular_stock",
        "allowance_uncertainty": "low",
        "requires_operator_selection": False,
    },
    CASTING: {
        "work_scope": "near_net_finishing",
        "default_action": "Existing Geometry – No Machining",
        "allowance_source": "drawing_or_operator_required",
        "allowance_uncertainty": "unknown",
        "requires_operator_selection": True,
    },
    WELDMENT: {
        "work_scope": "post_fabrication_machining",
        "default_action": "Existing Geometry – No Machining",
        "allowance_source": "fabrication_state_unknown",
        "allowance_uncertainty": "unknown",
        "requires_operator_selection": True,
    },
    REWORK: {
        "work_scope": "selected_rework_only",
        "default_action": "Existing Geometry – No Machining",
        "allowance_source": "inspection_or_operator_required",
        "allowance_uncertainty": "unknown",
        "requires_operator_selection": True,
    },
}


def starting_part_profile(starting_part_type):
    return dict(_PROFILES.get(starting_part_type, _PROFILES[RAW_BILLET]))


def prepare_candidates_for_starting_part(
    candidates,
    stock,
    part_dims,
    starting_part_type,
):
    """Apply only the stock semantics valid for the selected starting part."""
    profile = starting_part_profile(starting_part_type)
    is_raw = starting_part_type == RAW_BILLET
    stock_analysis = None
    if is_raw:
        transform = infer_work_transform(part_dims or {}, stock or {})
        stock_analysis = analyze_rectangular_stock(
            stock,
            transform.work_spans,
        )
    if is_raw:
        prepared = apply_stock_allowance_to_candidates(
            candidates,
            stock,
            part_dims,
            include_edge_milling=True,
            apply_raw_stock_allowance=True,
        )
    else:
        # Casting / weldment / rework: candidates are EXISTING geometry until
        # the operator selects machining — annotate only, never run the stock
        # module. Its orientation candidate-set reselection can replace the
        # detected list wholesale (e.g. SLIDE BASE 156 -> 77 candidates),
        # which broke "weldment policy should preserve detected review
        # candidates". Non-raw semantics require the review list untouched.
        prepared = copy.deepcopy(candidates or [])

    for candidate in prepared:
        candidate["starting_part_type"] = starting_part_type
        candidate["work_scope"] = profile["work_scope"]
        candidate["default_machining_action"] = profile["default_action"]
        candidate["allowance_source"] = profile["allowance_source"]
        candidate["allowance_uncertainty"] = profile["allowance_uncertainty"]
        candidate["requires_operator_selection"] = profile["requires_operator_selection"]
        candidate["existing_geometry"] = not is_raw

    warnings = []
    errors = []
    if stock_analysis and not stock_analysis["valid"]:
        errors.extend(stock_analysis["errors"])
        warnings.append(
            "Billet planning is blocked until stock dimensions and part placement "
            "contain the complete part."
        )
    solids_count = int((part_dims or {}).get("solids_count") or 0)
    if starting_part_type == CASTING:
        warnings.append(
            "Casting/forging mode: no billet stock removal was inferred. "
            "Select only surfaces with confirmed machining allowance."
        )
    elif starting_part_type == WELDMENT:
        warnings.append(
            "Weldment mode: fabricated members, holes, and slots are treated as "
            "existing geometry until the operator selects final machining."
        )
        if solids_count > 1:
            warnings.append(
                f"This STEP contains {solids_count} solids. Review joined members "
                "and select only post-fabrication machining groups."
            )
    elif starting_part_type == REWORK:
        warnings.append(
            "Rework mode: no machining is assumed. Select only new or corrective "
            "operations confirmed by inspection or the drawing."
        )

    return {
        "candidates": prepared,
        "warnings": warnings,
        "errors": errors,
        "stock_analysis": stock_analysis,
        "profile": profile,
    }
