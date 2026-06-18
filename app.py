import streamlit as st
import pandas as pd
import json
import io
import copy
import contextlib
import hashlib
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(__file__))

from modules.data_store import (
    get_default_materials, get_default_tools, get_default_machines,
    save_tools_to_db, load_tools_from_db,
    save_features_to_db, load_features_from_db,
    add_job_note, load_job_notes, delete_job_note, clear_all_job_notes,
    get_database_status,
)
from modules.operation_planner import (
    is_secondary_setup_operation,
    plan_operations,
    secondary_setup_labels,
)
from modules.machine_capability import machine_feasibility_summary
from modules.time_estimator import estimate_time
from modules.gcode_generator import generate_gcode
from modules.visual_preview import build_top_view, build_3d_view, build_step_mesh3d, FEATURE_COLORS
from modules.step_parser import parse_step_bounding_box, parse_step_geometry, parse_step_auto
from modules.session_integrity import (
    clear_import_derived_state,
    validate_session_consistency,
    DEFAULT_STOCK,
)
from modules.geometry_transform import infer_work_transform
from modules.starting_part_policy import prepare_candidates_for_starting_part
from modules.setup_sheet import generate_setup_sheet
from modules.speeds_feeds import (
    material_list, coating_list, get_vc_range, get_chip_load_range,
    calc_rpm, calc_feed, calc_vc_from_rpm, calc_mrr,
)
from modules.tolerance_guide import (
    IT_GRADE_LIST, IT_VALUES, IT_DIAMETER_BANDS,
    get_it_tolerance_um, get_it_band_label,
    get_process_for_feature, SURFACE_FINISH_TABLE, COMMON_FITS,
)

st.set_page_config(
    page_title="CNC Plan and Process Pro",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

APP_NAME = "CNC Plan and Process Pro"
APP_TAGLINE = "Professional CNC Planning for Modern Workshops"
LOGO_PATH = os.path.join(os.path.dirname(__file__), "public", "logo.png")

# ── Navigation constants ──────────────────────────────────────────────────────
_SECTION_TABS = {
    "CONFIGURE": [
        ("Part Setup",                "🧱 Part Setup"),
        ("Select Machining Work",     "🧩 Select Work"),
        ("4. Setup & Feature Review", "✅ Feature Review"),
    ],
    "WORKFLOW": [
        ("6. Strategy / Operations",  "🛠️ Strategy"),
        ("7. Estimate / Pricing",     "💰 Estimate"),
        ("8. Export / Setup Sheet",   "📤 Export"),
    ],
    "HISTORY / ADMIN": [
        ("9. History",        "🕘 History"),
        ("5. Tools",          "🧰 Tools"),
        ("11. Data Tables",   "📊 Data Tables"),
    ],
}

# Derived: route key → section (built from _SECTION_TABS so it stays in sync)
_PAGE_TO_SECTION: dict[str, str] = {
    route_key: section
    for section, tabs in _SECTION_TABS.items()
    for route_key, _ in tabs
}
# Orphaned/hidden pages — map to their nearest section as a fallback
_PAGE_TO_SECTION.update({
    "1. Upload / Overview":  "CONFIGURE",
    "2. Material & Machine": "CONFIGURE",
    "3. Stock & Setup":      "CONFIGURE",
    "10. Tool Library":      "HISTORY / ADMIN",
})

VMC_HANDOVER_SAMPLES = [
    (
        "M03_vmc_blind_rectangular_pocket.step",
        "Pocket baseline",
        "Face milling x2, Pocket x1; rough + finish pocket operations; INR quote path.",
    ),
    (
        "M07_vmc_chamfered_plate.step",
        "Chamfer baseline",
        "Face milling x2, Hole x4, Chamfer x1; chamfer tool guidance appears.",
    ),
    (
        "M02_vmc_slot_plate.step",
        "Flat slot baseline",
        "Face milling x2, Slot x1; classified as Slot, not Pocket.",
    ),
    (
        "17b_top_milled_step_shoulder-Body.step",
        "Step shoulder baseline",
        "Face milling x2, Step x1; rough + finish step operations.",
    ),
    (
        "M05_vmc_large_bore_plate.step",
        "Boring baseline",
        "Face milling x2, Hole x2, Large hole / boring x1; boring safety notes.",
    ),
]


def render_vmc_handover_test_pack():
    with st.expander("VMC handover test pack", expanded=False):
        st.caption(
            "Run these samples before asking a machinist or customer to review the VMC flow."
        )
        st.markdown(
            """
**Standard path for every sample**

1. Part Setup: upload the STEP file and confirm the stock summary.
2. Select Work: accept only the intended machining groups.
3. Feature Review: confirm accepted features and validation notes.
4. Strategy: review operation sequence, setup split, tools, and process warnings.
5. Estimate: check time, cost, tolerance, and quote currency assumptions.
6. Export: inspect the setup sheet and draft CNC warnings. Do not run the G-code.
"""
        )
        _sample_rows = [
            "| STEP sample | Purpose | Pass signal |",
            "|---|---|---|",
        ]
        for sample, purpose, pass_signal in VMC_HANDOVER_SAMPLES:
            _sample_rows.append(f"| `{sample}` | {purpose} | {pass_signal} |")
        st.markdown("\n".join(_sample_rows))


def show_top_header():
    st.markdown(
        f"<span style='font-size:1.0rem;font-weight:600;color:#777;'>{APP_TAGLINE}</span>",
        unsafe_allow_html=True,
    )
    st.divider()


def top_tabs(page: str) -> str:
    """Render a horizontal row of workflow step buttons above the page content.

    Derives the active section from _PAGE_TO_SECTION, then renders one button
    per tab in that section.  The button matching the current _nav_page is
    highlighted primary; all others are secondary.  Clicking any button sets
    _nav_page to that route key and triggers a rerun.

    Returns st.session_state._nav_page (updated if a tab was clicked).
    """
    active_section = _PAGE_TO_SECTION.get(page, "CONFIGURE")
    tabs = _SECTION_TABS[active_section]

    _tab_cols = st.columns(len(tabs))
    for _col, (route_key, label) in zip(_tab_cols, tabs):
        with _col:
            if st.button(
                label,
                key=f"_top_tab_{route_key}",
                use_container_width=True,
                type="primary" if page == route_key else "secondary",
            ):
                st.session_state._nav_page = route_key
                st.rerun()

    st.divider()
    return st.session_state._nav_page


DEMO_FEATURES = [
    {
        "feature_name": "Hole 10mm x4",
        "feature_type": "Hole",
        "quantity": 4,
        "x_pos": 15.0,
        "y_pos": 20.0,
        "diameter": 10.0,
        "length": 0.0,
        "width": 0.0,
        "depth": 20.0,
        "tolerance_note": "H7",
        "priority": 1,
    },
    {
        "feature_name": "Pocket 60x40",
        "feature_type": "Pocket",
        "quantity": 1,
        "x_pos": 20.0,
        "y_pos": 30.0,
        "diameter": 0.0,
        "length": 60.0,
        "width": 40.0,
        "depth": 8.0,
        "tolerance_note": "+/-0.05",
        "priority": 2,
    },
    {
        "feature_name": "Face Milling Top",
        "feature_type": "Face Milling",
        "quantity": 1,
        "x_pos": 0.0,
        "y_pos": 0.0,
        "diameter": 0.0,
        "length": 150.0,
        "width": 100.0,
        "depth": 1.0,
        "tolerance_note": "Ra 1.6",
        "priority": 0,
    },
]

FEATURE_TYPES = [
    "Hole",
    "Large Hole / Boring",
    "Pocket",
    "Slot",
    "Face Milling",
    "Edge Milling",
    "Outer Profile",
    "Chamfer",
]

_FTYPE_MAP = {
    "face milling":        "Face Milling",
    "edge milling":        "Edge Milling",
    "hole":                "Hole",
    "large hole / boring": "Large Hole / Boring",
    "slot":                "Slot",
}


def _render_3d_panel(key_prefix: str, large: bool = False):
    """Render the interactive 3D preview panel with horizontal viewer controls.

    key_prefix: unique prefix for all widget keys (avoids Streamlit duplicate-key errors).
    large: when True, sets chart height=680 and omits the subheader.
    """
    if not large:
        st.subheader("3D Preview")
    _mesh      = st.session_state.get("step_mesh_data")
    _geo       = st.session_state.get("step_geometry")
    _stk       = st.session_state.get("stock", {})
    _all_cands = (
        st.session_state.get("_smw_preview_candidates")
        if key_prefix == "_smw_3d_"
        else st.session_state.get("step_candidates", [])
    ) or []

    _FACE_COLOR_DEFAULT_TYPES = {"Hole", "Large hole / boring", "Pocket", "Chamfer"}
    _has_face_colors = any(
        bool(c.get("face_mesh_data"))
        and c.get("feature_type", "") in _FACE_COLOR_DEFAULT_TYPES
        for c in _all_cands
    )

    # ── Viewer controls — compact horizontal row ──────────────────────────
    _vc1, _vc2, _vc3, _vc4, _vc5 = st.columns(5)
    _show_stock = _vc1.checkbox(
        "Show stock",
        value=False,
        key=f"{key_prefix}show_stock",
        help="Overlay the semi-transparent stock / bounding box on the part",
    )
    _show_face_colors = _vc2.checkbox(
        "CAD face colors",
        value=True,
        key=f"{key_prefix}show_face_colors",
        help="Color detected feature surfaces using actual CAD face geometry",
    )
    _show_face_milling = _vc3.checkbox(
        "Face-milling",
        value=False,
        key=f"{key_prefix}show_face_milling",
        help="Overlay top/bottom face-milling surfaces (off by default)",
        disabled=not _show_face_colors,
    )
    _show_markers = _vc4.checkbox(
        "Markers",
        value=not _has_face_colors,
        key=f"{key_prefix}show_markers",
        help="Show fallback marker outlines for features without CAD face data",
    )
    _show_labels = _vc5.checkbox(
        "Labels",
        value=False,
        key=f"{key_prefix}show_labels",
        disabled=not _show_markers,
        help="Display dimension labels next to each marker",
    )
    _vs1, _vs2 = st.columns([1.1, 1.4])
    _camera_view = _vs1.selectbox(
        "View",
        options=["Isometric", "Top", "Front", "Right"],
        key=f"{key_prefix}camera_view",
        help="Set the initial 3D camera orientation",
    )
    _part_opacity = _vs2.slider(
        "Part opacity",
        min_value=0.20,
        max_value=1.00,
        value=0.82 if key_prefix == "_smw_3d_" else 1.00,
        step=0.05,
        key=f"{key_prefix}part_opacity",
        help="Lower opacity makes colored machining surfaces easier to inspect",
    )

    # Highlight IDs scoped to Select Machining Work panel only.
    _hl_ids = (
        st.session_state.get("_smw_highlight_candidate_ids") or set()
    ) if key_prefix == "_smw_3d_" else set()

    if _mesh:
        _transform = infer_work_transform(st.session_state.get("step_parse_result", {}), _stk)
        fig_mesh = build_step_mesh3d(
            _mesh, _stk,
            candidates=_all_cands,
            show_labels=(_show_labels and _show_markers),
            show_stock_box=_show_stock,
            show_face_colors=_show_face_colors,
            show_face_milling=_show_face_milling,
            show_markers=_show_markers,
            highlighted_candidate_ids=_hl_ids or None,
            part_opacity=_part_opacity,
            camera_view=_camera_view,
            transform=_transform,
        )
        fig_mesh.update_layout(
            showlegend=True,
            legend=dict(
                orientation="h",
                x=0.02,
                y=0.02,
                xanchor="left",
                yanchor="bottom",
                font=dict(size=14),
                bgcolor="rgba(255,255,255,0.75)",
                bordercolor="rgba(0,0,0,0.15)",
                borderwidth=1,
            ),
        )
        if large:
            fig_mesh.update_layout(height=680)
        st.plotly_chart(fig_mesh, use_container_width=True)

        # ── Custom readable legend (stays on page even when chart is fullscreened) ──
        _LEGEND_ITEMS: list[tuple[str, str]] = [
            ("#9E9E9E", "Part body"),
            ("#87CEEB", "Face Milling"),
            ("#00A6A6", "Edge Milling"),
            ("#1E90FF", "Hole"),
            ("#8B008B", "Large Hole / Boring"),
            ("#FF8C00", "Slot / Slot-like opening"),
            ("#228B22", "Pocket"),
            ("#8B4513", "Step"),
            ("#DA70D6", "Chamfer"),
            ("#2F4F4F", "Outer Profile"),
        ]
        if _show_stock:
            _LEGEND_ITEMS.insert(1, ("#D3D3D3", "Stock / bounding box"))
        if _hl_ids:
            _LEGEND_ITEMS.append(("#FFD700", "Highlighted selection"))
        _swatch_html = "".join(
            f"<span style='display:inline-flex;align-items:center;gap:5px;"
            f"margin:0 14px 5px 0;white-space:nowrap;'>"
            f"<span style='width:13px;height:13px;background:{_lc};border-radius:2px;"
            f"display:inline-block;border:1px solid rgba(0,0,0,0.18);flex-shrink:0;'></span>"
            f"<span style='font-size:13px;color:#333;'>{_ll}</span></span>"
            for _lc, _ll in _LEGEND_ITEMS
        )
        st.markdown(
            f"<div style='display:flex;flex-wrap:wrap;margin:6px 0 4px;'>"
            f"{_swatch_html}</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<div style='font-size:12px;color:#666;margin-top:2px;'>"
            "Rotate: drag &nbsp;·&nbsp; Zoom: scroll &nbsp;·&nbsp; Pan: right-drag"
            " &nbsp;·&nbsp; Planning preview only — verify toolpaths in CAM.</div>",
            unsafe_allow_html=True,
        )

    elif (_geo and _geo.get("success")
          and (_geo.get("line_segments") or _geo.get("circle_traces"))):
        fig_wire = build_3d_view(_stk, [], step_geometry=_geo)
        if large:
            fig_wire.update_layout(height=680)
        st.plotly_chart(fig_wire, use_container_width=True)
        st.caption("Wireframe preview — STEP edge geometry · Planning reference only.")
    elif st.session_state.get("step_parse_result"):
        _tess_err = st.session_state.get("_tess_error")
        if _tess_err:
            st.warning(f"3D tessellation failed: {_tess_err}")
        st.info(
            "Solid 3D preview unavailable. "
            "Upload requires CadQuery/OCC-enabled Python for the solid preview."
        )
    else:
        st.info("Upload a STEP file to see the interactive 3D preview here.")


def _feature_signature(feature):
    """Stable key used to prevent duplicate accepted CAD features."""
    physical_feature_id = feature.get("physical_feature_id")
    if physical_feature_id:
        return ("physical_feature_id", str(physical_feature_id))
    return (
        str(feature.get("feature_type") or "").strip().lower(),
        str(feature.get("feature_name") or "").strip().lower(),
        round(float(feature.get("x_pos") or 0.0), 3),
        round(float(feature.get("y_pos") or 0.0), 3),
        round(float(feature.get("diameter") or 0.0), 3),
        round(float(feature.get("length") or 0.0), 3),
        round(float(feature.get("width") or 0.0), 3),
        round(float(feature.get("depth") or 0.0), 3),
    )


def _accepted_feature_signatures():
    return {
        _feature_signature(feature)
        for feature in st.session_state.get("features", [])
    }


def _candidate_identity_ids(candidate):
    return {
        str(value)
        for value in (
            candidate.get("candidate_id"),
            candidate.get("physical_feature_id"),
        )
        if value
    }


def _candidate_is_added(candidate, added_ids):
    return bool(_candidate_identity_ids(candidate) & set(added_ids or set()))


def _mark_candidate_added(candidate):
    st.session_state.added_candidate_ids.update(
        _candidate_identity_ids(candidate)
    )


def _candidate_work_value(candidate, axis):
    # When "corner" is selected and exact face geometry is available, use the
    # footprint minimum corner instead of the face centroid. Falls back to
    # centroid for candidates without tessellated face_mesh_data (e.g. holes,
    # approximate markers) since a fabricated corner would be dishonest.
    if axis in ("x", "y") and st.session_state.get("position_reference") == "corner":
        footprint_min = candidate.get("footprint_work_min") or {}
        corner_value = footprint_min.get(axis)
        if corner_value is not None:
            return float(corner_value)
    work_position = candidate.get("work_position") or {}
    value = work_position.get(axis)
    if value is None:
        value = candidate.get(f"work_{axis}_pos")
    if value is None:
        value = candidate.get(f"{axis}_pos")
    return float(value or 0.0)


def _candidate_work_setup(candidate):
    return candidate.get("work_setup_label") or candidate.get("setup_label", "Unknown")


def _feature_from_candidate(candidate, feature_type, action):
    return {
        "feature_name":           candidate.get("feature_name") or feature_type,
        "feature_type":           feature_type,
        "quantity":               int(candidate.get("quantity")  or 1),
        "x_pos":                  _candidate_work_value(candidate, "x"),
        "y_pos":                  _candidate_work_value(candidate, "y"),
        "z_pos":                  _candidate_work_value(candidate, "z"),
        "diameter":               float(candidate.get("diameter") or 0.0),
        "length":                 float(candidate.get("length")  or 0.0),
        "width":                  float(candidate.get("width")   or 0.0),
        "depth":                  float(candidate.get("depth")   or 0.0),
        "tolerance_note":         candidate.get("tolerance_note") or "",
        "priority":               int(candidate.get("priority")  or 3),
        "machining_action":       action,
        "selected_for_machining": True,
        "source_candidate_id":     candidate.get("candidate_id", ""),
        "physical_feature_id":     candidate.get("physical_feature_id", ""),
        "source_file_hash":        candidate.get("source_file_hash", ""),
        "starting_part_type":      candidate.get("starting_part_type", ""),
        "work_scope":              candidate.get("work_scope", ""),
        "allowance_source":        candidate.get("allowance_source", ""),
        "allowance_uncertainty":   candidate.get("allowance_uncertainty", ""),
        "setup_label":            _candidate_work_setup(candidate),
        "cad_position":           candidate.get("cad_position"),
        "coordinate_transform":   candidate.get("coordinate_transform"),
    }


def _commit_candidate_selections(edited_df, candidates) -> int:
    """Commit ticked candidate rows to st.session_state.features.

    Returns the number of features added.
    Skips rows already in added_candidate_ids and Reference-Only rows.
    Coerces ticked 'Existing Geometry – No Machining' rows to 'Machine'.
    """
    if "added_candidate_ids" not in st.session_state:
        st.session_state.added_candidate_ids = set()
    _lookup = {c["candidate_id"]: c for c in candidates}
    _existing_signatures = _accepted_feature_signatures()
    _n_added = 0
    for _, _row in edited_df.iterrows():
        _cid    = _row["candidate_id"]
        _action = str(_row.get("machining_action", "Machine"))
        if not _row["accept"]:
            continue
        if _action == "Reference Only":
            continue
        if _action == "Existing Geometry – No Machining":
            _action = "Machine"
        _c = _lookup.get(_cid)
        if _c is None:
            continue
        if _candidate_is_added(_c, st.session_state.added_candidate_ids):
            continue
        _ftype = _FTYPE_MAP.get(
            (_c.get("feature_type") or "").strip().lower(),
            _c.get("feature_type", ""),
        )
        _feature = _feature_from_candidate(_c, _ftype, _action)
        _sig = _feature_signature(_feature)
        if _sig in _existing_signatures:
            _mark_candidate_added(_c)
            continue
        st.session_state.features.append(_feature)
        _existing_signatures.add(_sig)
        _mark_candidate_added(_c)
        _n_added += 1
    return _n_added


# Part types that carry pre-existing geometry — grouped view defaults ON for these.
_NON_RAW_SPTS = {"Weldment / Fabricated Part", "Casting / Forging", "Existing Part / Rework"}


def _candidate_review_location_key(candidate):
    """Approximate a physical feature location for noisy review grouping."""
    return (
        round(float(candidate.get("x_pos") or candidate.get("center_x") or 0.0), 0),
        round(float(candidate.get("y_pos") or candidate.get("center_y") or 0.0), 0),
        round(float(candidate.get("z_pos") or candidate.get("center_z") or 0.0), 0),
    )


def _candidate_float(candidate, key, fallback_key=None):
    return float(candidate.get(key) or (candidate.get(fallback_key) if fallback_key else 0.0) or 0.0)


def _same_review_location(a, b):
    """Return True when two noisy slot detections represent the same place."""
    ax = _candidate_float(a, "x_pos", "center_x")
    ay = _candidate_float(a, "y_pos", "center_y")
    az = _candidate_float(a, "z_pos", "center_z")
    bx = _candidate_float(b, "x_pos", "center_x")
    by = _candidate_float(b, "y_pos", "center_y")
    bz = _candidate_float(b, "z_pos", "center_z")

    length = max(_candidate_float(a, "length"), _candidate_float(b, "length"))
    width = max(_candidate_float(a, "width"), _candidate_float(b, "width"))
    depth = max(_candidate_float(a, "depth"), _candidate_float(b, "depth"))

    long_tol = max(3.0, length * 0.12)
    short_tol = max(3.0, width * 1.5)
    z_tol = max(3.0, depth * 0.35)
    dx = abs(ax - bx)
    dy = abs(ay - by)
    dz = abs(az - bz)

    same_xy = (
        (dx <= long_tol and dy <= short_tol)
        or (dx <= short_tol and dy <= long_tol)
    )
    return same_xy and dz <= z_tol


def _representative_members_by_location(members):
    """Return one candidate per approximate physical location."""
    reps = []
    for member in members:
        if any(_same_review_location(member, rep) for rep in reps):
            continue
        reps.append(member)
    return reps or list(members)


def _build_candidate_groups(candidates, spt):
    """Group candidates by (feature_type, dia_r1, len_r1, wid_r1, dep_r1).

    Returns a sorted list of group dicts with keys:
        group_key, feature_type, display_type, description,
        count, member_ids, confidence_summary
    """
    _is_non_raw = spt in _NON_RAW_SPTS
    buckets = {}
    for c in candidates:
        ftype  = c.get("feature_type") or "Unknown"
        dia    = round(float(c.get("diameter") or 0), 1)
        length = round(float(c.get("length")   or 0), 1)
        width  = round(float(c.get("width")    or 0), 1)
        depth  = round(float(c.get("depth")    or 0), 1)
        buckets.setdefault((ftype, dia, length, width, depth), []).append(c)

    groups = []
    for key, members in buckets.items():
        ftype, dia, length, width, depth = key
        detected_count = len(members)

        # Fabricated/rework STEP files can emit several slot candidates for the
        # same physical slot because opposite wall/floor faces are paired more
        # than one way. In grouped review, keep one representative per location;
        # flat mode still exposes the original detections for inspection.
        if _is_non_raw and ftype.lower() == "slot":
            review_members = _representative_members_by_location(members)
        else:
            review_members = list(members)
        review_count = len(review_members)

        # Relabel Slot → "Slot-like opening" for fabricated/rework/casting
        if _is_non_raw and ftype.lower() == "slot":
            display_type = "Slot-like opening"
        else:
            display_type = ftype

        # Human-readable size description
        ftype_lower = ftype.lower()
        if ftype_lower in ("hole", "large hole / boring"):
            if depth > 0:
                description = f"{display_type} Ø{dia:.1f} × {depth:.1f} mm"
            else:
                description = f"{display_type} Ø{dia:.1f} mm (through)"
        elif dia > 0:
            description = f"{display_type} Ø{dia:.1f} mm"
        elif length > 0 and width > 0 and depth > 0:
            description = f"{display_type} {length:.1f} × {width:.1f} × {depth:.1f} mm"
        elif length > 0 and width > 0:
            description = f"{display_type} {length:.1f} × {width:.1f} mm"
        else:
            description = display_type

        # Dominant confidence label across members
        conf_counts = {}
        for m in members:
            cv = str(m.get("confidence") or "unknown")
            conf_counts[cv] = conf_counts.get(cv, 0) + 1
        top_conf = max(conf_counts, key=conf_counts.get)
        confidence_summary = (
            f"{top_conf} (+{len(conf_counts) - 1} other)"
            if len(conf_counts) > 1 else top_conf
        )
        if detected_count != review_count:
            count_label = f"{review_count} location(s) ({detected_count} detected faces)"
        else:
            count_label = f"{review_count} found"

        groups.append({
            "group_key":          key,
            "feature_type":       ftype,
            "display_type":       display_type,
            "description":        description,
            "count":              review_count,
            "detected_count":     detected_count,
            "count_label":        count_label,
            "member_ids":         [m["candidate_id"] for m in review_members],
            "detected_member_ids": [m["candidate_id"] for m in members],
            "confidence_summary": confidence_summary,
        })

    groups.sort(key=lambda g: (g["feature_type"], g["description"]))
    return groups


def _group_widget_suffix(group) -> str:
    """Stable suffix for grouped selection widgets."""
    raw = "|".join(str(part) for part in group["group_key"])
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:10]


def _preview_member_ids_for_group(group, candidates, max_members=12):
    """Return representative member ids for preview highlighting.

    Complex welded/rework parts can produce many duplicate slot-like candidates
    from paired face combinations. Highlighting all of them at once makes the
    model unreadable, so group preview uses one candidate per approximate
    physical location while commit still expands the full selected group.
    """
    member_ids = group.get("member_ids", [])
    if len(member_ids) <= max_members:
        return list(member_ids)

    if str(group.get("feature_type", "")).lower() != "slot":
        return list(member_ids[:max_members])

    lookup = {c.get("candidate_id"): c for c in candidates}
    reps = []
    seen_locations = set()
    for cid in member_ids:
        cand = lookup.get(cid)
        if not cand:
            continue
        key = _candidate_review_location_key(cand)
        if key in seen_locations:
            continue
        seen_locations.add(key)
        reps.append(cid)
        if len(reps) >= max_members:
            break
    return reps or list(member_ids[:max_members])


def _commit_group_selections(edited_grouped_df, groups, candidates) -> int:
    """Commit ticked group rows to st.session_state.features.

    Each ticked group expands to all its member candidates.
    Skips members already in added_candidate_ids and Reference-Only groups.
    Coerces ticked 'Existing Geometry – No Machining' groups to 'Machine'.
    Returns count of individual features added.
    """
    if "added_candidate_ids" not in st.session_state:
        st.session_state.added_candidate_ids = set()
    _cand_lookup = {c["candidate_id"]: c for c in candidates}
    _existing_signatures = _accepted_feature_signatures()
    _n_added = 0

    for _, _row in edited_grouped_df.iterrows():
        if not _row.get("accept", False):
            continue
        _action = str(_row.get("machining_action", "Machine"))
        if _action == "Reference Only":
            continue
        if _action == "Existing Geometry – No Machining":
            _action = "Machine"

        _gidx = int(_row["_group_idx"])
        if _gidx < 0 or _gidx >= len(groups):
            continue
        group = groups[_gidx]

        for _cid in group["member_ids"]:
            _c = _cand_lookup.get(_cid)
            if _c is None:
                continue
            if _candidate_is_added(_c, st.session_state.added_candidate_ids):
                continue
            _ftype = _FTYPE_MAP.get(
                (_c.get("feature_type") or "").strip().lower(),
                _c.get("feature_type", ""),
            )
            _feature = _feature_from_candidate(_c, _ftype, _action)
            _sig = _feature_signature(_feature)
            if _sig in _existing_signatures:
                _mark_candidate_added(_c)
                continue
            st.session_state.features.append(_feature)
            _existing_signatures.add(_sig)
            _mark_candidate_added(_c)
            _n_added += 1

    return _n_added


def _stock_adjusted_candidates():
    """Return candidates prepared for the selected starting-part semantics."""
    _spt = st.session_state.get("starting_part_type", "Raw Block / Billet")
    result = prepare_candidates_for_starting_part(
        st.session_state.get("step_candidates", []),
        st.session_state.get("stock", {}),
        st.session_state.get("step_parse_result", {}),
        _spt,
    )
    st.session_state._starting_part_policy_warnings = result["warnings"]
    st.session_state._starting_part_policy_errors = result["errors"]
    return result["candidates"]


def init_session():
    if "tools" not in st.session_state:
        db_tools = load_tools_from_db()
        st.session_state.tools = db_tools if db_tools else get_default_tools()
    if "features" not in st.session_state:
        db_features = load_features_from_db()
        has_active_parse = "step_parse_result" in st.session_state
        if db_features and not has_active_parse:
            # Stale features from a previous Streamlit session — clear them rather than
            # showing features without the geometry that produced them.
            save_features_to_db([])
            st.session_state.features = []
            st.session_state._restart_cleared_features = len(db_features)
        else:
            st.session_state.features = db_features if db_features else []
    if "materials" not in st.session_state:
        st.session_state.materials = get_default_materials()
    if "machines" not in st.session_state:
        st.session_state.machines = get_default_machines()
    if "selected_material" not in st.session_state:
        st.session_state.selected_material = st.session_state.materials[0]
    if "selected_machine" not in st.session_state:
        st.session_state.selected_machine = st.session_state.machines[0]
    if "stock" not in st.session_state:
        st.session_state.stock = dict(DEFAULT_STOCK)
    if "uploaded_filename" not in st.session_state:
        st.session_state.uploaded_filename = None
    if "step_uploader_key" not in st.session_state:
        st.session_state.step_uploader_key = 0
    if "step_candidates" not in st.session_state:
        st.session_state.step_candidates = []
    if "step_candidate_warnings" not in st.session_state:
        st.session_state.step_candidate_warnings = []
    if "added_candidate_ids" not in st.session_state:
        st.session_state.added_candidate_ids = set()
    if "features_from_candidates" not in st.session_state:
        st.session_state.features_from_candidates = False
    if "est_currency" not in st.session_state:
        st.session_state.est_currency = "INR (₹)"
    if "est_machine_rate" not in st.session_state:
        st.session_state.est_machine_rate = 800.0
    if "est_operator_rate" not in st.session_state:
        st.session_state.est_operator_rate = 200.0
    if "est_setup_cost" not in st.session_state:
        st.session_state.est_setup_cost = 500.0
    if "est_tool_cost" not in st.session_state:
        st.session_state.est_tool_cost = 300.0
    if "est_material_price_kg" not in st.session_state:
        st.session_state.est_material_price_kg = 80.0
    if "est_material_waste_pct" not in st.session_state:
        st.session_state.est_material_waste_pct = 15.0
    if "est_batch_qty" not in st.session_state:
        st.session_state.est_batch_qty = 1
    if "est_margin_pct" not in st.session_state:
        st.session_state.est_margin_pct = 20.0
    if "est_tolerance" not in st.session_state:
        st.session_state.est_tolerance = "General (±0.20 mm) — ×1.00"
    if "est_complexity" not in st.session_state:
        st.session_state.est_complexity = 1.0
    if "est_show_quote_currency" not in st.session_state:
        st.session_state.est_show_quote_currency = False
    if "est_quote_currency" not in st.session_state:
        st.session_state.est_quote_currency = "USD ($)"
    if "est_exchange_rate" not in st.session_state:
        st.session_state.est_exchange_rate = 1.0
    if "position_reference" not in st.session_state:
        st.session_state.position_reference = "center"
    if "step_mesh_data" not in st.session_state:
        st.session_state.step_mesh_data = None
    if "starting_part_type" not in st.session_state:
        st.session_state.starting_part_type = "Raw Block / Billet"


def reset_current_job_state():
    """Clear all current-job state. Preserves tool/material/machine libraries."""
    clear_import_derived_state(st.session_state)
    st.session_state.step_uploader_key = st.session_state.get("step_uploader_key", 0) + 1
    save_features_to_db([])
    st.session_state._nav_page = "Part Setup"
    st.session_state._job_reset_done = True


def sidebar_nav():
    with st.sidebar:
        # ── App title ─────────────────────────────────────────────────────
        st.markdown(
            "<div style='font-size:1.1rem;font-weight:700;padding:0.3rem 0 0.1rem;'>"
            "⚙️ CNC Plan & Process Pro</div>",
            unsafe_allow_html=True,
        )
        st.caption("Professional CNC planning")
        st.divider()

        # ── Workflow section buttons ──────────────────────────────────────
        if "_nav_page" not in st.session_state:
            st.session_state._nav_page = "Part Setup"

        _active_section = _PAGE_TO_SECTION.get(st.session_state._nav_page, "CONFIGURE")

        _WORKFLOW_BUTTONS = [
            ("CONFIGURE",       "⚙️ Configure",          "Part Setup"),
            ("WORKFLOW",        "📋 Workflow & Estimate", "6. Strategy / Operations"),
            ("HISTORY / ADMIN", "🕘 History / Admin",     "9. History"),
        ]

        for _sec_key, _sec_label, _default_page in _WORKFLOW_BUTTONS:
            if st.button(
                _sec_label,
                key=f"_nav_section_{_sec_key}",
                use_container_width=True,
                type="primary" if _active_section == _sec_key else "secondary",
            ):
                st.session_state._nav_page = _default_page
                st.rerun()

        # ── Branding block — directly below workflow buttons ─────────────
        st.divider()
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=75)
        st.markdown(
            "<div style='"
            "background:#fffbe6;border:1px solid #ffe58f;border-radius:4px;"
            "padding:7px 9px;margin-top:4px;"
            "'>"
            "<div style='font-size:11px;font-weight:700;color:#874d00;"
            "margin-bottom:3px;'>⚠️ SAFETY NOTICE</div>"
            "<div style='font-size:11px;color:#5c3d00;line-height:1.35;'>"
            "Generated CNC code is DRAFT only. "
            "Always verify in CAM/simulator before machining.</div>"
            "</div>",
            unsafe_allow_html=True,
        )
        db_status = get_database_status()
        if not db_status.get("available", True):
            st.warning(
                "Local database is offline. The app is using default tools and "
                "in-session job data until the database becomes available."
            )
            with st.expander("Database detail", expanded=False):
                st.caption(f"Active path: {db_status.get('path') or 'unknown'}")
                st.caption(f"Last operation: {db_status.get('last_operation') or 'unknown'}")
                st.caption(db_status.get("last_error") or "No error detail available.")
                if db_status.get("migration_error"):
                    st.caption(f"Legacy migration: {db_status['migration_error']}")
        elif "using fallback" in str(db_status.get("migration_error") or ""):
            st.info("Database recovered using safe local fallback storage.")
            with st.expander("Database storage detail", expanded=False):
                st.caption(f"Active path: {db_status.get('path') or 'unknown'}")
                st.caption(db_status.get("migration_error"))

        return st.session_state._nav_page


def _parse_and_tessellate(file_bytes: bytes, filename: str):
    """Parse a STEP file, tessellate for 3D preview, and store all results in session state.

    Returns the parse_result dict so the caller can show unit-conversion / error banners.
    """
    file_hash = hashlib.sha256(file_bytes).hexdigest()
    if (
        st.session_state.get("uploaded_file_hash") == file_hash
        and st.session_state.get("step_parse_result", {}).get("success")
    ):
        return st.session_state.step_parse_result

    clear_import_derived_state(st.session_state)
    parse_result = parse_step_auto(file_bytes)

    if parse_result["success"]:
        geo_result = parse_step_geometry(file_bytes)
        st.session_state.uploaded_filename        = filename
        st.session_state.uploaded_file_hash       = file_hash
        st.session_state.step_parse_result      = parse_result
        st.session_state.step_geometry          = geo_result
        st.session_state.stock["length"]        = parse_result["length_mm"]
        st.session_state.stock["width"]         = parse_result["width_mm"]
        st.session_state.stock["height"]        = parse_result["height_mm"]
        st.session_state.stock["stock_volume"]  = parse_result["stock_volume_cm3"]
        st.session_state.stock["part_volume"]   = parse_result["part_volume_cm3"]
        st.session_state.step_candidates         = parse_result.get("candidate_features", [])
        st.session_state.step_candidate_warnings = parse_result.get("candidate_warnings", [])
        st.session_state.added_candidate_ids     = set()

        _mesh_data     = None
        _tmp_tess_path = None
        st.session_state.pop("_tess_error", None)
        try:
            if os.environ.get("CNC_DISABLE_CADQUERY", "").strip().lower() in {"1", "true", "yes"}:
                raise ImportError("CadQuery disabled by CNC_DISABLE_CADQUERY")
            import cadquery as cq
            with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as _tmp_tess:
                _tmp_tess.write(file_bytes)
                _tmp_tess_path = _tmp_tess.name
            _cq_tess = cq.importers.importStep(_tmp_tess_path)
            _verts, _tris = _cq_tess.val().tessellate(0.5)
            if _verts:
                _mesh_data = {
                    "x": [v.x for v in _verts],
                    "y": [v.y for v in _verts],
                    "z": [v.z for v in _verts],
                    "i": [t[0] for t in _tris],
                    "j": [t[1] for t in _tris],
                    "k": [t[2] for t in _tris],
                }
        except ImportError:
            pass
        except Exception as _tess_exc:
            st.session_state._tess_error = f"{type(_tess_exc).__name__}: {_tess_exc}"
        finally:
            if _tmp_tess_path and os.path.exists(_tmp_tess_path):
                try:
                    os.unlink(_tmp_tess_path)
                except OSError:
                    pass
        st.session_state.step_mesh_data = _mesh_data

    return parse_result


def page_upload_step():
    # ── Page title ────────────────────────────────────────────────────
    st.title("Upload & Overview")
    st.caption(
        "Upload a STEP file to extract bounding box geometry and feature candidates. "
        "After parsing, proceed to **Select Machining Work** to choose what to machine."
    )
    st.divider()

    if st.session_state.pop("_job_reset_done", False):
        st.success("Job reset — all job data cleared. Upload a new STEP file to begin.")

    _cleared = st.session_state.pop("_restart_cleared_features", 0)
    if _cleared:
        st.info(
            f"**Previous session detected:** {_cleared} accepted feature(s) from a prior "
            "Streamlit session were cleared on startup because no STEP file is loaded. "
            "Upload a STEP file to begin a new job."
        )

    for _sc_warn in validate_session_consistency(st.session_state):
        if _sc_warn["key"] in ("stale_features", "stale_candidates"):
            if _sc_warn["level"] == "warning":
                st.warning(_sc_warn["message"])
            else:
                st.info(_sc_warn["message"])

    # ── Starting Part Type — visual cards ────────────────────────────
    st.subheader("What are you starting with?")
    _PART_TYPES = [
        ("Raw Block / Billet",         "🧱", "Fresh stock — detected features can be treated as machining work."),
        ("Weldment / Fabricated Part", "🔩", "Already welded/fabricated — select only final machining operations."),
        ("Casting / Forging",          "🪨", "Near-shape part — select only finishing/machining areas."),
        ("Existing Part / Rework",     "🔧", "Existing component — select only new or rework operations."),
    ]
    _current_pt = st.session_state.get("starting_part_type", "Raw Block / Billet")
    _pt_cols = st.columns(4, gap="small")
    for _pti, (_pt_val, _pt_icon, _pt_desc) in enumerate(_PART_TYPES):
        _is_sel = (_current_pt == _pt_val)
        with _pt_cols[_pti]:
            _border = "#1a73e8" if _is_sel else "#cccccc"
            _bg     = "#e8f0fe" if _is_sel else "#fafafa"
            _check  = "✅ " if _is_sel else ""
            st.markdown(
                f'<div style="border:2.5px solid {_border};border-radius:10px;'
                f'padding:14px 10px 8px;background:{_bg};text-align:center;">'
                f'<div style="font-size:2.2rem;line-height:1.2;">{_pt_icon}</div>'
                f'<div style="font-weight:700;font-size:0.85rem;margin-top:6px;">{_check}{_pt_val}</div>'
                f'<div style="font-size:0.77rem;color:#555;margin-top:5px;line-height:1.35;">{_pt_desc}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
            if _is_sel:
                st.button(
                    "✓ Selected",
                    key=f"_pt_card_{_pti}",
                    disabled=True,
                    use_container_width=True,
                    type="primary",
                )
            else:
                if st.button(
                    "Select",
                    key=f"_pt_card_{_pti}",
                    use_container_width=True,
                ):
                    st.session_state.starting_part_type = _pt_val
                    st.rerun()
    st.divider()

    # ── Clear / Start New ─────────────────────────────────────────────
    if st.session_state.get("uploaded_filename"):
        cl1, cl2 = st.columns([3, 1])
        cl1.info(f"Loaded file: **{st.session_state.uploaded_filename}**")
        if cl2.button("Clear & Start New", type="secondary"):
            reset_current_job_state()
            st.rerun()

    # ── File uploader (behaviour unchanged) ───────────────────────────
    uploaded = st.file_uploader(
        "Upload STEP / STP file",
        type=["step", "stp"],
        help="Supported: STEP AP203, AP214, AP242 (ASCII format)",
        key=f"step_uploader_{st.session_state.step_uploader_key}",
    )

    parse_result = None

    if uploaded:
        file_bytes = uploaded.read()

        col_info1, col_info2 = st.columns(2)
        col_info1.success(f"File: **{uploaded.name}**")
        col_info2.info(f"Size: **{len(file_bytes) / 1024:.1f} KB**")

        with st.spinner("Parsing STEP file geometry..."):
            parse_result = _parse_and_tessellate(file_bytes, uploaded.name)

        if parse_result["success"]:
            # Unit detection banner
            r = parse_result
            if r["converted"]:
                factor = r["conversion_factor"]
                raw_label = r["detected_unit_label"].split("(")[0].strip()
                st.warning(
                    f"Unit conversion applied: file coordinates are in **{raw_label}** "
                    f"(detected via {r['detection_method']}) — "
                    f"multiplied by **{factor}** to convert to mm. "
                    "All dimensions below are in millimetres."
                )
            else:
                st.success(
                    f"Units confirmed as **mm** "
                    f"(detected via {r['detection_method']}) — no conversion needed."
                )
            for w in r.get("warnings", []):
                st.warning(w)
            cadquery_warning = r.get("cadquery_warning")
            if cadquery_warning:
                st.warning(f"**CadQuery fallback:** {cadquery_warning}")
            if r.get("degraded_mode"):
                st.warning(
                    "**Degraded mode:** CadQuery/OpenCASCADE is not available in this "
                    "environment. Bounding-box dimensions are approximate (±10 %), "
                    "solid preview is disabled, and feature candidates cannot be detected. "
                    "Stock dimensions have been auto-filled — verify them before proceeding."
                )
        else:
            st.warning(f"**STEP parse failed:** {parse_result['message']}")
            detail     = parse_result.get("detail")
            suggestion = parse_result.get("suggestion")
            if detail or suggestion:
                with st.expander("Why did this happen? / Suggested action", expanded=True):
                    if detail:
                        st.markdown(f"**Why:** {detail}")
                    if suggestion:
                        st.markdown(f"**Action:** {suggestion}")
            st.info(
                "Stock dimensions have not been auto-filled. "
                "Enter them manually in the fields below to continue planning."
            )

    # ── Resolve display source: fresh parse or cached session result ───
    _display_r = None
    if parse_result and parse_result.get("success"):
        _display_r = parse_result
    elif parse_result is None and st.session_state.get("step_parse_result", {}).get("success"):
        _display_r = st.session_state.get("step_parse_result")

    # ── Post-parse overview: 2-column card layout ──────────────────────
    if _display_r:
        r = _display_r

        def _fmt(v):
            return f"{v:,}" if v is not None else "N/A"

        ov_left, ov_right = st.columns([1, 1])

        with ov_left:
            st.subheader("Parse Summary")
            ps1, ps2 = st.columns(2)
            ps1.metric("Parser", r.get("parser_used", "lightweight"))
            ps2.metric("Vol. Source", r.get("volume_source", "—"))
            ps3, ps4 = st.columns(2)
            ps3.metric("Units", r["detected_unit_label"].split("(")[0].strip())
            ps3.metric(
                "Conversion",
                f"× {r['conversion_factor']}" if r.get("converted") else "None (mm)",
            )
            _pt = r.get("point_count")
            ps4.metric("Points", f"{_pt:,}" if _pt is not None else "N/A")
            st.caption(
                f"File: **{st.session_state.get('uploaded_filename', '—')}**  ·  "
                f"Method: {r['detection_method']}"
            )

            st.subheader("CAD Topology")
            tc1, tc2, tc3, tc4 = st.columns(4)
            tc1.metric("Solids",   _fmt(r.get("solids_count")))
            tc2.metric("Faces",    _fmt(r.get("faces_count")))
            tc3.metric("Edges",    _fmt(r.get("edges_count")))
            tc4.metric("Vertices", _fmt(r.get("vertices_count")))
            if r.get("parser_used") == "cadquery":
                st.success("CadQuery/OpenCASCADE active — full solid geometry extracted.")
            else:
                st.info(
                    "Using lightweight parser — bounding box and volume are approximate. "
                    "Topology counts are not available."
                )

        with ov_right:
            _render_3d_panel("_upload_3d_")

        with st.expander("Coordinate Ranges", expanded=False):
            if r.get("converted"):
                raw_label = r["detected_unit_label"].split("(")[0].strip()
                range_data = {
                    "Axis": ["X (Length)", "Y (Width)", "Z (Height)"],
                    f"Raw Min ({raw_label})": [
                        r["x_range_raw"][0], r["y_range_raw"][0], r["z_range_raw"][0]
                    ],
                    f"Raw Max ({raw_label})": [
                        r["x_range_raw"][1], r["y_range_raw"][1], r["z_range_raw"][1]
                    ],
                    "Min (mm)": [r["x_range"][0], r["y_range"][0], r["z_range"][0]],
                    "Max (mm)": [r["x_range"][1], r["y_range"][1], r["z_range"][1]],
                    "Span (mm)": [r["length_mm"], r["width_mm"], r["height_mm"]],
                }
            else:
                range_data = {
                    "Axis": ["X (Length)", "Y (Width)", "Z (Height)"],
                    "Min (mm)": [r["x_range"][0], r["y_range"][0], r["z_range"][0]],
                    "Max (mm)": [r["x_range"][1], r["y_range"][1], r["z_range"][1]],
                    "Span (mm)": [r["length_mm"], r["width_mm"], r["height_mm"]],
                }
            st.dataframe(pd.DataFrame(range_data), use_container_width=True, hide_index=True)

        # ── Detected Feature Measurements ─────────────────────────────
        st.divider()
        st.subheader("Detected Feature Measurements")
        _cands_tbl = st.session_state.get("step_candidates", [])
        if _cands_tbl:
            st.caption(
                "Detected from STEP file — planning reference only. "
                "Select machinable groups on **Select Machining Work**."
            )

            def _fv(v):
                f = float(v) if v not in (None, "") else 0.0
                return round(f, 2) if f != 0.0 else None

            def _meas(c):
                """Build a compact human-readable measurement string for a candidate."""
                ft   = (c.get("feature_type") or "").lower()
                dia  = float(c.get("diameter") or 0)
                l    = float(c.get("length")   or 0)
                w    = float(c.get("width")    or 0)
                d    = float(c.get("depth")    or 0)
                if "hole" in ft or "boring" in ft:
                    parts = []
                    if dia > 0: parts.append(f"Ø{dia:.2f}")
                    if d   > 0: parts.append(f"d={d:.2f}")
                    return ("  ".join(parts) + " mm") if parts else "—"
                if "face mill" in ft:
                    if l > 0 and w > 0: return f"{l:.2f} × {w:.2f} mm"
                    return "—"
                dims = [f"{v:.2f}" for v in (l, w, d) if v > 0]
                return (" × ".join(dims) + " mm") if dims else "—"

            _pos_ref = st.session_state.get("position_reference", "center")
            _xy_label = "Work X — corner (mm)" if _pos_ref == "corner" else "Work X — center (mm)"
            _yx_label = "Work Y — corner (mm)" if _pos_ref == "corner" else "Work Y — center (mm)"
            _rows = []
            for _c in _cands_tbl:
                _rows.append({
                    "ID":              _c.get("candidate_id", "—"),
                    "Type":            _c.get("feature_type",  "—"),
                    "Name":            _c.get("feature_name",  "—"),
                    "Measurement":     _meas(_c),
                    _xy_label:         _fv(_candidate_work_value(_c, "x")),
                    _yx_label:         _fv(_candidate_work_value(_c, "y")),
                    "Diameter (mm)":   _fv(_c.get("diameter")),
                    "Length (mm)":     _fv(_c.get("length")),
                    "Width (mm)":      _fv(_c.get("width")),
                    "Depth (mm)":      _fv(_c.get("depth")),
                    "Confidence":      _c.get("confidence", "—"),
                })
            st.dataframe(
                pd.DataFrame(_rows),
                use_container_width=True,
                hide_index=True,
                column_config={
                    _xy_label:       st.column_config.NumberColumn(_xy_label,       format="%.2f"),
                    _yx_label:       st.column_config.NumberColumn(_yx_label,       format="%.2f"),
                    "Diameter (mm)": st.column_config.NumberColumn("Diameter (mm)", format="%.2f"),
                    "Length (mm)":   st.column_config.NumberColumn("Length (mm)",   format="%.2f"),
                    "Width (mm)":    st.column_config.NumberColumn("Width (mm)",    format="%.2f"),
                    "Depth (mm)":    st.column_config.NumberColumn("Depth (mm)",    format="%.2f"),
                },
            )
        else:
            st.info("Feature markers will appear after STEP feature detection.")

    # ── Stock & Part Dimensions (inputs unchanged) ────────────────────
    st.subheader("Stock & Part Dimensions")

    if parse_result is not None and parse_result.get("success"):
        st.caption("Dimensions auto-filled from STEP file — review and adjust if needed.")

    stock = st.session_state.stock
    col1, col2, col3 = st.columns(3)

    with col1:
        stock["length"] = st.number_input(
            "Stock Length (mm)", value=float(stock["length"]), min_value=0.001, step=0.5,
            help="X-axis span of the bounding box"
        )
        stock["width"] = st.number_input(
            "Stock Width (mm)", value=float(stock["width"]), min_value=0.001, step=0.5,
            help="Y-axis span of the bounding box"
        )
    with col2:
        stock["height"] = st.number_input(
            "Stock Height (mm)", value=float(stock["height"]), min_value=0.001, step=0.5,
            help="Z-axis span of the bounding box"
        )
        stock["stock_volume"] = st.number_input(
            "Stock Volume (cm³)", value=float(stock["stock_volume"]), min_value=0.001, step=0.5,
            help="Full bounding-box volume of raw stock material"
        )
    with col3:
        stock["part_volume"] = st.number_input(
            "Part Volume (cm³)", value=float(stock["part_volume"]), min_value=0.001, step=0.5,
            help="Finished part volume — estimated at 60 % of bounding box if auto-parsed"
        )

    # ── Volume Analysis (calculations unchanged) ──────────────────────
    removed = max(stock["stock_volume"] - stock["part_volume"], 0)
    removal_pct = (removed / stock["stock_volume"] * 100) if stock["stock_volume"] > 0 else 0

    st.subheader("Volume Analysis")
    c1, c2, c3 = st.columns(3)
    c1.metric("Stock Volume", f"{stock['stock_volume']:.2f} cm³")
    c2.metric("Part Volume", f"{stock['part_volume']:.2f} cm³")
    c3.metric("Removed Volume", f"{removed:.2f} cm³", delta=f"{removal_pct:.1f}% removal")

    if _display_r:
        _vol_note = (
            "Real part volume from CadQuery/OCC solid geometry."
            if _display_r.get("parser_used") == "cadquery"
            else "Part volume estimated as 60 % of bounding-box volume — "
                 "adjust if your part has significantly different geometry."
        )
        st.caption(f"Detection method: {_display_r['detection_method']}. {_vol_note}")

    # ── Next step guidance ─────────────────────────────────────────────
    if _display_r or st.session_state.get("step_candidates"):
        _n = len(st.session_state.get("step_candidates", []))
        _cand_str = f" **{_n} feature candidate(s) detected.**" if _n > 0 else ""
        st.success(
            f"STEP file loaded.{_cand_str}  "
            "**Next →** Select which features to machine, then review in Setup & Feature Review."
        )
        _ng_col1, _ = st.columns([1, 3])
        with _ng_col1:
            if st.button("Next → Select Machining Work", type="primary", key="_upload_next_smw"):
                st.session_state._nav_page = "Select Machining Work"
                st.rerun()

    st.session_state.stock = stock


def page_machine_setup():
    st.title("Material & Machine")
    st.caption(
        "Select the work material and CNC machine assumptions used for speeds, feeds, "
        "setup time, and estimates."
    )
    st.divider()

    # ── Top status cards ──────────────────────────────────────────────────────
    _mach = st.session_state.selected_machine
    _mat  = st.session_state.selected_material
    _sc1, _sc2, _sc3, _sc4 = st.columns(4)
    _sc1.metric("Material",     _mat.get("name", "—"))
    _sc2.metric("Machine",      _mach.get("machine_name", "—"))
    _sc3.metric("Machine Type", _mach.get("machine_type", "—"))
    _sc4.metric("Controller",   _mach.get("controller", "—"))

    st.info(
        "Machine and material settings are planning assumptions. "
        "Verify final speeds, feeds, and setup time with the workshop."
    )

    st.divider()

    # ── Section: Material Selection ───────────────────────────────────────────
    st.subheader("Material Selection")

    materials  = st.session_state.materials
    mat_names  = [mat["name"] for mat in materials]
    mat_sel_idx = st.selectbox(
        "Select Material",
        range(len(mat_names)),
        format_func=lambda i: mat_names[i],
        key="_mm_mat_sel",
    )
    mat_m = copy.deepcopy(materials[mat_sel_idx])

    _mc1, _mc2, _mc3 = st.columns(3)
    with _mc1:
        mat_m["density"] = st.number_input(
            "Density (g/cm³)", value=float(mat_m["density"]), step=0.1,
            key="_mm_density",
        )
    with _mc2:
        mat_m["machinability_factor"] = st.number_input(
            "Machinability Factor (0–1)",
            value=float(mat_m["machinability_factor"]),
            min_value=0.1, max_value=2.0, step=0.05,
            key="_mm_mach_factor",
        )
    with _mc3:
        mat_m["safety_factor"] = st.number_input(
            "Safety Factor",
            value=float(mat_m["safety_factor"]),
            min_value=1.0, max_value=3.0, step=0.05,
            key="_mm_safety_factor",
        )

    if st.button("Apply Material", key="_mm_apply_material"):
        st.session_state.materials[mat_sel_idx] = mat_m
        st.session_state.selected_material = mat_m
        st.success(f"Material **{mat_m['name']}** applied.")
    else:
        st.session_state.selected_material = mat_m

    st.divider()

    # ── Section: Machine Selection ────────────────────────────────────────────
    st.subheader("Machine Selection")

    machines      = st.session_state.machines
    machine_names = [m["machine_name"] for m in machines]
    sel_idx = st.selectbox(
        "Select Machine Profile",
        range(len(machine_names)),
        format_func=lambda i: machine_names[i],
    )
    m = copy.deepcopy(machines[sel_idx])

    st.divider()

    # ── Section: Machine Parameters ───────────────────────────────────────────
    st.subheader("Machine Parameters")

    col1, col2 = st.columns(2)
    with col1:
        m["machine_name"] = st.text_input("Machine Name", value=m["machine_name"])
        _MACHINE_TYPES = ["VMC", "CNC Milling", "CNC Turning", "HMC", "Turn-Mill", "Gang Turning", "Swiss Type"]
        m["machine_type"] = st.selectbox(
            "Machine Type",
            _MACHINE_TYPES,
            index=_MACHINE_TYPES.index(m["machine_type"]) if m["machine_type"] in _MACHINE_TYPES else 0,
        )
        _CONTROLLERS = [
            "Fanuc 0i-MF", "Fanuc 0i-TF", "Fanuc 31i", "Fanuc 32i",
            "Siemens 828D", "Siemens 840D", "Mazatrol",
            "Mitsubishi M70", "Mitsubishi M80",
            "Haas", "Generic",
        ]
        m["controller"] = st.selectbox(
            "Controller",
            _CONTROLLERS,
            index=_CONTROLLERS.index(m["controller"]) if m["controller"] in _CONTROLLERS else 10,
        )
        m["max_spindle_rpm"] = st.number_input(
            "Max Spindle RPM", value=int(m["max_spindle_rpm"]), min_value=100, step=100,
        )

    with col2:
        m["max_feed_rate"]      = st.number_input(
            "Max Feed Rate (mm/min)", value=int(m["max_feed_rate"]), min_value=100, step=100,
        )
        m["rapid_feed_rate"]    = st.number_input(
            "Rapid Feed Rate (mm/min)", value=int(m["rapid_feed_rate"]), min_value=100, step=100,
        )
        m["tool_change_time_s"] = st.number_input(
            "Tool Change Time (s)", value=int(m["tool_change_time_s"]), min_value=1, step=1,
        )
        m["setup_time_min"]     = st.number_input(
            "Setup Time (min)", value=int(m["setup_time_min"]), min_value=1, step=1,
        )

    if st.button("Apply Machine Settings"):
        st.session_state.machines[sel_idx] = m
        st.session_state.selected_machine = m
        st.success(f"Machine profile **{m['machine_name']}** applied.")
    else:
        st.session_state.selected_machine = m

    _pm1, _pm2, _pm3, _pm4, _pm5 = st.columns(5)
    _pm1.metric("Max Spindle RPM",      m["max_spindle_rpm"])
    _pm2.metric("Max Feed (mm/min)",    m["max_feed_rate"])
    _pm3.metric("Rapid Feed (mm/min)",  m["rapid_feed_rate"])
    _pm4.metric("Tool Change (s)",      m["tool_change_time_s"])
    _pm5.metric("Setup Time (min)",     m["setup_time_min"])

    st.info(
        f"Active machine: **{st.session_state.selected_machine['machine_name']}** — "
        f"{st.session_state.selected_machine['machine_type']} / "
        f"{st.session_state.selected_machine['controller']}"
    )

    st.divider()

    # ── Section: Planning Preferences ────────────────────────────────────────
    st.subheader("Planning Preferences")
    st.caption(
        "These settings affect how feature positions are reported in the feature table, "
        "operation plan, and G-code output."
    )
    _pos_options = {
        "center": "Center point  —  X/Y at the face centroid (tool centre path reference)",
        "corner": "Min corner  —  X/Y at the feature's nearest edge (datum/setup reference)",
    }
    _pos_current = st.session_state.get("position_reference", "center")
    _pos_sel = st.radio(
        "Feature X/Y position reference",
        options=list(_pos_options.keys()),
        format_func=lambda k: _pos_options[k],
        index=list(_pos_options.keys()).index(_pos_current),
        key="_pos_ref_radio",
        help=(
            "**Center point:** X/Y shows where the tool centre sits over the feature. "
            "Used when programming directly from the CAD centroid. "
            "\n\n**Min corner:** X/Y shows the closest edge of the feature from the "
            "work datum. Matches how most setup sheets and inspection plans describe "
            "feature location from a corner datum."
        ),
    )
    if _pos_sel != _pos_current:
        st.session_state.position_reference = _pos_sel
        st.rerun()

    if st.session_state.position_reference == "corner":
        st.info(
            "Min corner mode: X/Y uses the footprint minimum corner when exact face "
            "geometry is available. Holes and approximate features fall back to centroid "
            "automatically (no exact corner can be derived without tessellated geometry)."
        )

    st.divider()

    # ── Section: Material Machinability ───────────────────────────────────────
    st.subheader("Material Machinability")
    st.caption("Key material parameters used for feeds, speeds, and time estimates.")

    _mm1, _mm2, _mm3 = st.columns(3)
    _mm1.metric("Density (g/cm³)",       mat_m["density"])
    _mm2.metric("Machinability Factor",  mat_m["machinability_factor"])
    _mm3.metric("Safety Factor",         mat_m["safety_factor"])


def page_tool_library():
    st.title("Tools")
    st.caption(
        "Review available tools, default speeds/feeds, tool depth limits, "
        "and machining assumptions."
    )
    st.divider()

    tools = st.session_state.tools

    # ── Summary cards ─────────────────────────────────────────────────────────
    _end_mills = sum(1 for t in tools if t.get("tool_type") == "End Mill")
    _drills    = sum(1 for t in tools if t.get("tool_type") in ("Drill", "Spot Drill"))
    _special   = len(tools) - _end_mills - _drills

    _tc1, _tc2, _tc3, _tc4 = st.columns(4)
    _tc1.metric("Total Tools",     len(tools))
    _tc2.metric("End Mills",       _end_mills)
    _tc3.metric("Drills",          _drills)
    _tc4.metric("Special / Other", _special)

    st.divider()

    tab_lib, tab_sf = st.tabs(["Tool Library", "Speeds & Feeds Reference"])

    # ── Tab 1: Tool Library ───────────────────────────────────────────────────
    with tab_lib:
        st.subheader("Tool Library")
        st.info("Edit your tool library. Changes are saved to the local database.")

        st.subheader("Tool Details / Editor")

        df = pd.DataFrame(tools)
        cols_order = [
            "tool_number", "tool_name", "tool_type", "diameter_mm",
            "default_spindle_rpm", "default_feed_rate_mm_min", "max_depth_mm",
            "flute_length_mm", "overall_length_mm", "holder_diameter_mm",
            "min_bore_mm", "max_bore_mm",
        ]
        df = df[cols_order]

        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "tool_number":              st.column_config.NumberColumn("T#",             min_value=1, max_value=99),
                "tool_name":                st.column_config.TextColumn("Tool Name"),
                "tool_type":                st.column_config.SelectboxColumn("Type",        options=["Spot Drill", "Drill", "End Mill", "Face Mill", "Boring", "Chamfer"]),
                "diameter_mm":              st.column_config.NumberColumn("Dia (mm)",       format="%.1f"),
                "default_spindle_rpm":      st.column_config.NumberColumn("RPM"),
                "default_feed_rate_mm_min": st.column_config.NumberColumn("Feed (mm/min)"),
                "max_depth_mm":             st.column_config.NumberColumn("Max Depth (mm)", format="%.1f"),
                "flute_length_mm":           st.column_config.NumberColumn("Flute L (mm)", format="%.1f"),
                "overall_length_mm":         st.column_config.NumberColumn("Overall L (mm)", format="%.1f"),
                "holder_diameter_mm":        st.column_config.NumberColumn("Holder Dia (mm)", format="%.1f"),
                "min_bore_mm":               st.column_config.NumberColumn("Min Bore (mm)", format="%.1f"),
                "max_bore_mm":               st.column_config.NumberColumn("Max Bore (mm)", format="%.1f"),
            },
        )

        col1, col2 = st.columns(2)
        with col1:
            if st.button("Save Tool Library", type="primary"):
                updated = edited_df.to_dict("records")
                st.session_state.tools = updated
                save_tools_to_db(updated)
                st.success(f"Saved {len(updated)} tools to database.")
        with col2:
            if st.button("Reset to Defaults"):
                st.session_state.tools = get_default_tools()
                save_tools_to_db(st.session_state.tools)
                st.rerun()

    # ── Tab 2: Speeds & Feeds Reference ──────────────────────────────────────
    with tab_sf:
        st.subheader("Speeds & Feeds Reference")
        st.caption(
            "Calculate recommended spindle RPM and feed rate from cutting speed and chip load data. "
            "Use the results to fill in your tool library."
        )

        sf_col1, sf_col2 = st.columns(2)

        with sf_col1:
            sf_material = st.selectbox("Work Material", material_list(), key="sf_mat")
            sf_coating = st.selectbox(
                "Tool Coating / Grade",
                coating_list(sf_material),
                key="sf_coat",
            )
            sf_diameter = st.number_input(
                "Tool Diameter (mm)", value=10.0, min_value=0.1, max_value=200.0,
                step=0.5, key="sf_dia",
            )
            sf_flutes = st.number_input(
                "Number of Flutes", value=4, min_value=1, max_value=12,
                step=1, key="sf_flutes",
            )

        with sf_col2:
            vc_min, vc_max = get_vc_range(sf_material, sf_coating)
            vc_default = round((vc_min + vc_max) / 2)
            sf_vc = st.number_input(
                "Cutting Speed Vc (m/min)",
                value=float(vc_default),
                min_value=1.0, max_value=2000.0, step=5.0,
                key="sf_vc",
                help=f"Recommended range for {sf_material} / {sf_coating}: {vc_min}–{vc_max} m/min",
            )

            fz_min, fz_max = get_chip_load_range(sf_material, sf_diameter)
            fz_default = round((fz_min + fz_max) / 2, 4)
            sf_fz = st.number_input(
                "Chip Load per Tooth fz (mm/tooth)",
                value=fz_default,
                min_value=0.0001, max_value=2.0, step=0.001,
                format="%.4f",
                key="sf_fz",
                help=f"Recommended range for {sf_material} at ⌀{sf_diameter} mm: {fz_min}–{fz_max} mm/tooth",
            )

            sf_axial = st.number_input(
                "Axial Depth of Cut ap (mm)",
                value=min(sf_diameter, 10.0), min_value=0.1,
                step=0.5, key="sf_ap",
                help="Depth per pass — typically 0.5–1.5× tool diameter for roughing",
            )
            sf_radial = st.number_input(
                "Radial Depth of Cut ae (mm)",
                value=round(sf_diameter * 0.5, 1), min_value=0.1,
                step=0.5, key="sf_ae",
                help="Stepover — typically 25–75% of tool diameter",
            )

        # ── Calculations ──────────────────────────────────────────────
        rpm_calc = calc_rpm(sf_vc, sf_diameter)
        feed_calc = calc_feed(rpm_calc, sf_fz, sf_flutes)
        mrr = calc_mrr(feed_calc, sf_axial, sf_radial)

        # Recommended ranges for display
        rpm_min = calc_rpm(vc_min, sf_diameter)
        rpm_max = calc_rpm(vc_max, sf_diameter)
        feed_min = calc_feed(rpm_min, fz_min, sf_flutes)
        feed_max = calc_feed(rpm_max, fz_max, sf_flutes)

        st.divider()
        st.subheader("Calculated Results")

        r1, r2, r3, r4 = st.columns(4)
        r1.metric(
            "Spindle Speed",
            f"{rpm_calc:,.0f} RPM",
            delta=f"Range: {rpm_min:,.0f}–{rpm_max:,.0f}",
        )
        r2.metric(
            "Feed Rate",
            f"{feed_calc:,.0f} mm/min",
            delta=f"Range: {feed_min:,.0f}–{feed_max:,.0f}",
        )
        r3.metric(
            "MRR",
            f"{mrr:.1f} cm³/min",
            help="Material Removal Rate — higher = faster cutting but more load on tool",
        )
        r4.metric(
            "Surface Speed",
            f"{sf_vc:.0f} m/min",
            delta=f"Rec. {vc_min}–{vc_max} m/min",
        )

        # Reference table — all coatings for selected material
        st.subheader(f"Reference: {sf_material} — All Coatings")
        ref_rows = []
        for coat in coating_list(sf_material):
            v_lo, v_hi = get_vc_range(sf_material, coat)
            f_lo, f_hi = get_chip_load_range(sf_material, sf_diameter)
            n_lo = calc_rpm(v_lo, sf_diameter)
            n_hi = calc_rpm(v_hi, sf_diameter)
            feed_lo = calc_feed(n_lo, f_lo, sf_flutes)
            feed_hi = calc_feed(n_hi, f_hi, sf_flutes)
            ref_rows.append({
                "Coating / Grade": coat,
                "Vc min (m/min)": v_lo,
                "Vc max (m/min)": v_hi,
                "RPM min": int(n_lo),
                "RPM max": int(n_hi),
                "fz min (mm/tooth)": f_lo,
                "fz max (mm/tooth)": f_hi,
                "Feed min (mm/min)": int(feed_lo),
                "Feed max (mm/min)": int(feed_hi),
            })
        st.dataframe(pd.DataFrame(ref_rows), use_container_width=True, hide_index=True)

        # Apply to tool
        st.divider()
        st.subheader("Apply to Tool Library")
        st.caption("Overwrite the RPM and feed rate for a tool in your library with the calculated values.")

        tools_now = st.session_state.tools
        tool_options = [f"T{t['tool_number']:02d} — {t['tool_name']}" for t in tools_now]
        if tool_options:
            apply_idx = st.selectbox("Select tool to update", range(len(tool_options)),
                                     format_func=lambda i: tool_options[i], key="sf_apply_idx")
            a1, a2 = st.columns(2)
            with a1:
                apply_rpm = st.number_input(
                    "RPM to apply", value=int(rpm_calc), min_value=1, key="sf_apply_rpm"
                )
            with a2:
                apply_feed = st.number_input(
                    "Feed rate to apply (mm/min)", value=int(feed_calc), min_value=1, key="sf_apply_feed"
                )
            if st.button("Apply to Selected Tool", type="primary", key="sf_apply_btn"):
                st.session_state.tools[apply_idx]["default_spindle_rpm"] = apply_rpm
                st.session_state.tools[apply_idx]["default_feed_rate_mm_min"] = apply_feed
                save_tools_to_db(st.session_state.tools)
                st.success(
                    f"Updated **{tools_now[apply_idx]['tool_name']}**: "
                    f"{apply_rpm} RPM, {apply_feed} mm/min — saved to library."
                )
        else:
            st.info("No tools in library. Add tools in the Tool Library tab first.")

    st.divider()

    # ── Tooling Warnings ──────────────────────────────────────────────────────
    st.subheader("Tooling Warnings")
    st.warning(
        "Tool list is a planning library. Verify actual tool availability, offsets, "
        "flute length, holder clearance, and tool condition before machining."
    )
    st.info(
        "Before setting up on the machine, confirm: tool stickout and flute length are "
        "sufficient for all pockets, slots, and bored holes in this job; holder clearance "
        "is verified for each setup; and tool condition and edge sharpness are acceptable."
    )


def page_material_setup():
    st.title("Stock & Setup")
    st.caption(
        "Review stock size, material assumptions, coordinate setup, "
        "and preparation notes."
    )
    st.divider()

    stock   = st.session_state.get("stock", {})
    step_ok = bool(st.session_state.get("step_parse_result"))

    # ── Summary cards ─────────────────────────────────────────────────────────
    _l  = stock.get("length", 0) or 0
    _w  = stock.get("width",  0) or 0
    _h  = stock.get("height", 0) or 0
    _sv = stock.get("stock_volume", 0) or 0
    _pv = stock.get("part_volume",  0) or 0
    _removed     = round(_sv - _pv, 2)
    _removed_pct = round((_removed / _sv) * 100, 1) if _sv > 0 else 0

    _c1, _c2, _c3, _c4 = st.columns(4)
    _c1.metric("Stock (L×W×H mm)",  f"{_l} × {_w} × {_h}")
    _c2.metric("Part Vol (cm³)",    f"{_pv:.1f}" if _pv else "—")
    _c3.metric("Removed (cm³)",     f"{_removed:.1f}", delta=f"{_removed_pct}%")
    _c4.metric("Setup Status",      "STEP loaded ✓" if step_ok else "No STEP")

    st.divider()

    # ── Section: Stock Geometry ───────────────────────────────────────────────
    st.subheader("Stock Geometry")

    if not step_ok:
        st.info(
            "No STEP file loaded. Upload a STEP file on **1. Upload / Overview** first "
            "to populate stock dimensions automatically."
        )

    if stock and any([_l, _w, _h]):
        _sg1, _sg2, _sg3 = st.columns(3)
        _sg1.metric("Length (mm)",      _l)
        _sg2.metric("Width (mm)",       _w)
        _sg3.metric("Height (mm)",      _h)

        _sg4, _sg5, _sg6 = st.columns(3)
        _sg4.metric("Stock Vol (cm³)",  f"{_sv:.3f}")
        _sg5.metric("Part Vol (cm³)",   f"{_pv:.3f}")
        _sg6.metric("Material Removed", f"{_removed:.3f} cm³  ({_removed_pct}%)")
        st.caption("Stock dimensions are set on **1. Upload / Overview**. Navigate there to update.")
    else:
        st.info("No stock data available. Go to **1. Upload / Overview** to set stock dimensions.")

    st.divider()

    # ── Section: Work Coordinate & Setup Assumptions ──────────────────────────
    st.subheader("Work Coordinate & Setup Assumptions")
    st.info(
        "**Datum assumption:** Stock bottom-left corner = WCS origin (G54 X0 Y0 Z0). "
        "Top face of stock = Z=0 for Setup 1."
    )

    if step_ok:
        _pr = st.session_state.get("step_parse_result", {})
        _xr = _pr.get("x_range", (None, None))
        _yr = _pr.get("y_range", (None, None))
        _zr = _pr.get("z_range", (None, None))
        if _xr and _xr[0] is not None:
            _co1, _co2, _co3 = st.columns(3)
            _co1.metric("X range (mm)", f"{_xr[0]} → {_xr[1]}")
            _co2.metric("Y range (mm)", f"{_yr[0]} → {_yr[1]}")
            _co3.metric("Z range (mm)", f"{_zr[0]} → {_zr[1]}")

    st.divider()

    # ── Section: Material Assumptions ────────────────────────────────────────
    st.subheader("Material Assumptions")

    materials = st.session_state.materials
    mat_names = [m["name"] for m in materials]
    sel_idx = st.selectbox("Select Material", range(len(mat_names)), format_func=lambda i: mat_names[i])
    m = copy.deepcopy(materials[sel_idx])

    col1, col2, col3 = st.columns(3)
    with col1:
        m["density"] = st.number_input("Density (g/cm³)", value=float(m["density"]), step=0.1)
    with col2:
        m["machinability_factor"] = st.number_input("Machinability Factor (0–1)", value=float(m["machinability_factor"]), min_value=0.1, max_value=2.0, step=0.05)
    with col3:
        m["safety_factor"] = st.number_input("Safety Factor", value=float(m["safety_factor"]), min_value=1.0, max_value=3.0, step=0.05)

    if st.button("Apply Material"):
        st.session_state.materials[sel_idx] = m
        st.session_state.selected_material = m
        st.success(f"Material **{m['name']}** applied.")
    else:
        st.session_state.selected_material = m

    st.subheader("All Materials")
    st.dataframe(pd.DataFrame(materials), use_container_width=True)

    st.info(f"Active material: **{st.session_state.selected_material['name']}** — Safety factor: {st.session_state.selected_material['safety_factor']}")

    st.divider()

    # ── Section: Setup Notes ──────────────────────────────────────────────────
    st.subheader("Setup Notes")
    st.warning(
        "Verify raw stock size, datum location, workholding, and setup orientation "
        "before machining."
    )
    st.info(
        "Pre-machining checklist: confirm stock dimensions match drawing; set WCS datum "
        "per setup plan; verify clamp and fixture clearance; check tool reach and "
        "overhang for all operations; confirm coolant supply and chip evacuation."
    )


def page_feature_input():
    st.title("Data Tables / Admin")
    st.caption(
        "Manual feature input, tolerance reference (ISO 286-1), and surface finish guide. "
        "Use this page for data entry and engineering reference."
    )
    st.divider()

    tab_feat, tab_tol, tab_sf_guide = st.tabs([
        "Manual Feature Input",
        "Tolerance & IT Grade Guide",
        "Surface Finish Guide",
    ])

    # ── Tab 1: Feature List ───────────────────────────────────────────
    with tab_feat:
        st.info(
            "Manual feature input is useful when CAD detection is unavailable or when adding features manually. "
            "Features added here flow directly into the operation plan."
        )
        col_btn1, col_btn2, _ = st.columns([1, 1, 2])
        with col_btn1:
            if st.button("Load Demo Features"):
                st.session_state.features = copy.deepcopy(DEMO_FEATURES)
                save_features_to_db(st.session_state.features)
                st.rerun()
        with col_btn2:
            if st.button("Clear All Features"):
                st.session_state.features = []
                save_features_to_db([])
                st.rerun()

        st.subheader("Add New Feature")
        with st.form("add_feature_form", clear_on_submit=True):
            fc1, fc2 = st.columns(2)
            with fc1:
                fname = st.text_input("Feature Name", value="New Feature")
                ftype = st.selectbox("Feature Type", FEATURE_TYPES)
                qty = st.number_input("Quantity", min_value=1, value=1, step=1)
                priority = st.number_input("Priority / Order", min_value=0, value=len(st.session_state.features), step=1)
            with fc2:
                x_pos = st.number_input("X Position (mm)", value=0.0, step=1.0)
                y_pos = st.number_input("Y Position (mm)", value=0.0, step=1.0)
                diameter = st.number_input("Diameter (mm) — if applicable", value=0.0, step=0.5)
                tolerance = st.text_input("Tolerance Note", value="")

            fd1, fd2, fd3 = st.columns(3)
            with fd1:
                length = st.number_input("Length (mm)", value=0.0, step=1.0)
            with fd2:
                width = st.number_input("Width (mm)", value=0.0, step=1.0)
            with fd3:
                depth = st.number_input("Depth (mm)", value=5.0, step=0.5)

            submitted = st.form_submit_button("Add Feature", type="primary")
            if submitted:
                new_feature = {
                    "feature_name": fname,
                    "feature_type": ftype,
                    "quantity": int(qty),
                    "x_pos": float(x_pos),
                    "y_pos": float(y_pos),
                    "diameter": float(diameter),
                    "length": float(length),
                    "width": float(width),
                    "depth": float(depth),
                    "tolerance_note": tolerance,
                    "priority": int(priority),
                }
                st.session_state.features.append(new_feature)
                save_features_to_db(st.session_state.features)
                st.success(f"Added: **{fname}**")

        if st.session_state.features:
            st.subheader(f"Features ({len(st.session_state.features)} total)")
            df = pd.DataFrame(st.session_state.features)
            edited = st.data_editor(
                df,
                use_container_width=True,
                num_rows="dynamic",
                column_config={
                    "feature_type": st.column_config.SelectboxColumn("Type", options=FEATURE_TYPES),
                },
            )
            if st.button("Save Feature List"):
                st.session_state.features = edited.to_dict("records")
                save_features_to_db(st.session_state.features)
                st.success("Features saved.")
        else:
            st.info("No features yet. Use the form above or load demo features.")

    # ── Tab 2: Tolerance & IT Grade Guide ─────────────────────────────
    with tab_tol:
        st.subheader("Tolerance & IT Grade Calculator")
        st.caption(
            "ISO 286-1 tolerances for holes and shafts. "
            "Select a feature type and nominal diameter to see achievable grades, "
            "required operations, and typical Indian engineering fits."
        )

        tol_c1, tol_c2, tol_c3 = st.columns(3)
        with tol_c1:
            tol_feature = st.selectbox("Feature Type", FEATURE_TYPES, key="tol_ftype")
        with tol_c2:
            tol_diameter = st.number_input(
                "Nominal Diameter / Size (mm)", value=25.0,
                min_value=0.1, max_value=500.0, step=1.0, key="tol_dia",
                help="For holes: hole diameter. For slots/pockets: width dimension."
            )
        with tol_c3:
            tol_grade = st.selectbox("IT Grade", IT_GRADE_LIST, index=IT_GRADE_LIST.index("IT7"), key="tol_grade")

        tol_um = get_it_tolerance_um(tol_grade, tol_diameter)
        tol_mm = tol_um / 1000

        band = get_it_band_label(tol_diameter)
        st.info(
            f"**{tol_grade}** tolerance for **⌀{tol_diameter:.1f} mm** (band {band}): "
            f"**{tol_um} µm  ({tol_mm:.3f} mm)**"
        )

        # Full IT table for this diameter
        st.subheader(f"IT Grade Table for ⌀{tol_diameter:.1f} mm")
        it_rows = []
        for grade in IT_GRADE_LIST:
            t_um = get_it_tolerance_um(grade, tol_diameter)
            it_rows.append({
                "IT Grade": grade,
                "Tolerance (µm)": t_um,
                "Tolerance (mm)": f"±{t_um/2000:.4f}" if grade in ("IT5","IT6") else f"0 / +{t_um/1000:.3f}",
                "Typical Application": {
                    "IT5":  "Precision grinding, gauge making",
                    "IT6":  "Fine boring, grinding — bearing housings (H6)",
                    "IT7":  "Finish CNC turning/boring — most common fit (H7)",
                    "IT8":  "Reaming, finish milling — general purpose (H8)",
                    "IT9":  "Semi-finish turning/milling — agricultural, general machinery",
                    "IT10": "Normal CNC machining — flanges, brackets",
                    "IT11": "Rough machining — structural parts",
                    "IT12": "Basic machining — non-precision, casting cleanup",
                    "IT13": "Very rough — forging, rough casting stock",
                }.get(grade, "—"),
                "Min. Process": {
                    "IT5":  "Grinding / Honing",
                    "IT6":  "Fine Boring / Grinding",
                    "IT7":  "Finish Boring / Reaming",
                    "IT8":  "Reaming / Finish Turning",
                    "IT9":  "Semi-finish Turning/Milling",
                    "IT10": "Normal CNC Milling",
                    "IT11": "Rough CNC Machining",
                    "IT12": "Basic Machining",
                    "IT13": "Rough Machining / Casting",
                }.get(grade, "—"),
                "Workshop Feasibility (India)": {
                    "IT5":  "Needs grinding machine",
                    "IT6":  "Achievable on VMC with boring bar + measuring",
                    "IT7":  "Standard VMC/Lathe capability",
                    "IT8":  "Any decent CNC",
                    "IT9":  "Any CNC",
                    "IT10": "Any CNC or semi-precision conventional",
                    "IT11": "Conventional machine capable",
                    "IT12": "Any machine",
                    "IT13": "Any machine",
                }.get(grade, "—"),
            })
        it_df = pd.DataFrame(it_rows)
        # Highlight selected grade
        def highlight_selected(row):
            return ["background-color: #fff3cd; font-weight: bold" if row["IT Grade"] == tol_grade else "" for _ in row]
        st.dataframe(it_df.style.apply(highlight_selected, axis=1), use_container_width=True, hide_index=True)

        # Process capability for this feature
        st.subheader(f"Achievable Grades by Operation — {tol_feature}")
        processes = get_process_for_feature(tol_feature)
        if processes:
            proc_rows = []
            for p in processes:
                ra_lo, ra_hi = p["ra_range_um"]
                proc_rows.append({
                    "Operation": p["operation"],
                    "IT Grades": ", ".join(p["it_grades"]),
                    "Ra (µm)": f"{ra_lo}–{ra_hi}",
                    "Typical Fit": p.get("typical_fit", "—"),
                    "Notes": p["notes"],
                })
            st.dataframe(pd.DataFrame(proc_rows), use_container_width=True, hide_index=True)

        # Common fits
        st.subheader("Common Indian Engineering Fits (IS/ISO)")
        fits_df = pd.DataFrame(COMMON_FITS)
        st.dataframe(fits_df, use_container_width=True, hide_index=True)

    # ── Tab 3: Surface Finish Guide ───────────────────────────────────
    with tab_sf_guide:
        st.subheader("Surface Finish Reference (Ra / N-Grade)")
        st.caption(
            "Ra values in µm. N-grade is the ISO surface finish designation used on Indian engineering drawings. "
            "Rz = 4–5× Ra approximately."
        )

        sf_df = pd.DataFrame(SURFACE_FINISH_TABLE)
        sf_df.columns = ["N Grade", "Ra (µm)", "Rz (µm)", "Description", "Typical Process"]
        st.dataframe(sf_df, use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Ra Requirement by Drawing Callout")
        st.caption("Common Indian drawing surface finish symbols and their Ra equivalents.")
        callout_data = {
            "Drawing Symbol / Note": [
                "▽ (one triangle)",
                "▽▽ (two triangles)",
                "▽▽▽ (three triangles)",
                "Ra 6.3",
                "Ra 3.2",
                "Ra 1.6",
                "Ra 0.8",
                "Ra 0.4",
                "N7 (on BIS drawings)",
                "N8 (on BIS drawings)",
                "N9 (on BIS drawings)",
                "√ with number (ISO 1302)",
            ],
            "Ra (µm)": [
                "≤ 12.5", "≤ 3.2", "≤ 0.8",
                "6.3", "3.2", "1.6", "0.8", "0.4",
                "1.6", "3.2", "6.3",
                "Value shown",
            ],
            "Min. Process to Achieve": [
                "Normal turning/milling",
                "Finish turning/milling, reaming",
                "Fine boring, grinding",
                "Semi-finish turning/milling",
                "Finish milling, finish turning",
                "Fine turning, finish milling, reaming",
                "Fine boring, cylindrical grinding",
                "Precision grinding, hard turning",
                "Fine turning, finish milling",
                "Finish turning/milling",
                "Normal CNC turning/milling",
                "Depends on value",
            ],
        }
        st.dataframe(pd.DataFrame(callout_data), use_container_width=True, hide_index=True)

        st.divider()
        st.subheader("Ra Checker — Required Operation")
        ra_input = st.number_input(
            "Enter required Ra (µm)", value=1.6, min_value=0.01,
            max_value=50.0, step=0.1, key="ra_checker",
        )
        matched = [r for r in SURFACE_FINISH_TABLE if r["Ra_um"] <= ra_input]
        if matched:
            best = matched[-1]
            st.success(
                f"To achieve Ra **≤ {ra_input} µm**: use **{best['typical_process']}** "
                f"(N-grade **{best['N_grade']}**, Ra {best['Ra_um']} µm)."
            )
            tighter = [r for r in SURFACE_FINISH_TABLE if r["Ra_um"] < ra_input]
            if tighter:
                st.caption(
                    "Tighter options: " +
                    " → ".join(f"{r['N_grade']} ({r['Ra_um']} µm, {r['typical_process']})" for r in reversed(tighter[-3:]))
                )
        else:
            st.warning("Ra value is above normal machining range — verify drawing specification.")


def page_setup_review():
    st.title("Setup & Feature Review")
    st.caption(
        "Review detected CAD features, accept machining candidates, and prepare the operation plan."
    )
    st.divider()

    stock    = st.session_state.get("stock", {})
    machine  = st.session_state.get("selected_machine")
    material = st.session_state.get("selected_material")
    features = st.session_state.get("features", [])
    step_ok  = bool(st.session_state.get("step_parse_result"))
    _is_raw_block    = st.session_state.get("starting_part_type", "Raw Block / Billet") == "Raw Block / Billet"
    _candidates      = _stock_adjusted_candidates()
    _cand_warns      = (
        list(st.session_state.get("step_candidate_warnings", []))
        + list(st.session_state.get("_starting_part_policy_warnings", []))
    )
    _stock_errors    = list(st.session_state.get("_starting_part_policy_errors", []))
    _added_ids       = st.session_state.get("added_candidate_ids", set())
    _from_candidates = st.session_state.get("features_from_candidates", False)
    _filename        = st.session_state.get("uploaded_filename")

    # ── Top status cards ─────────────────────────────────────────────────────
    tm1, tm2, tm3, tm4 = st.columns(4)
    tm1.metric("STEP File", _filename if _filename else "None")
    tm2.metric("CAD Candidates", len(_candidates))
    tm3.metric("Accepted Features", len(features))
    tm4.metric("Source", "From CAD" if _from_candidates else ("Manual / Demo" if features else "—"))

    st.divider()

    # ── Start New Job / Reset ────────────────────────────────────────────────
    _has_job_state = bool(features) or bool(st.session_state.get("step_candidates"))
    if _has_job_state:
        _rc1, _rc2 = st.columns([5, 1])
        _rc1.info(
            f"**{len(features)} accepted feature(s)**  ·  "
            f"**{len(st.session_state.get('step_candidates', []))} CAD candidate(s)**"
            + (f"  ·  File: **{st.session_state.uploaded_filename}**"
               if st.session_state.get("uploaded_filename") else "")
        )
        if _rc2.button("🔄 Start New Job / Reset", type="secondary", use_container_width=True):
            reset_current_job_state()
            st.rerun()

    # ── A. Stock summary ─────────────────────────────────────────────────────
    st.subheader("Stock Dimensions")
    if stock:
        sc1, sc2, sc3, sc4, sc5 = st.columns(5)
        sc1.metric("Length (mm)", stock.get("length", "—"))
        sc2.metric("Width (mm)",  stock.get("width",  "—"))
        sc3.metric("Height (mm)", stock.get("height", "—"))
        sc4.metric("Stock Vol (cm³)", stock.get("stock_volume", "—"))
        sc5.metric("Part Vol (cm³)",  stock.get("part_volume",  "—"))

        sv = stock.get("stock_volume") or 0
        pv = stock.get("part_volume")  or 0
        removed = round(sv - pv, 3)
        if sv > 0:
            pct = round((removed / sv) * 100, 1)
            st.caption(f"Estimated material removed: **{removed} cm³** ({pct}% of stock)")
    else:
        st.warning("Stock dimensions not set. Complete page 1 or 2 first.")

    st.divider()

    # ── B. Setup summary ─────────────────────────────────────────────────────
    st.subheader("Machine & Material")
    ms1, ms2 = st.columns(2)
    with ms1:
        if machine:
            st.success(f"Machine: **{machine.get('machine_name', '—')}**")
            st.caption(
                f"Type: {machine.get('machine_type','—')} · "
                f"Axes: {machine.get('axis_count', 3)} · "
                f"Indexed 3+2: {'Yes' if machine.get('indexed_3plus2') else 'No'} · "
                f"Simultaneous 5-axis: {'Yes' if machine.get('simultaneous_5_axis') else 'No'} · "
                f"Controller: {machine.get('controller','—')} · "
                f"Max spindle: {machine.get('max_spindle_rpm','—')} RPM"
            )
        else:
            st.warning("No machine selected — go to page 2.")
    with ms2:
        if material:
            st.success(f"Material: **{material.get('name', '—')}**")
            st.caption(
                f"Machinability factor: {material.get('machinability_factor','—')} · "
                f"Safety factor: {material.get('safety_factor','—')} · "
                f"Density: {material.get('density','—')} g/cm³"
            )
        else:
            st.warning("No material selected — go to page 4.")

    st.divider()

    # ── C. Current features — conflict warning + clear option ───────────────
    _has_features   = bool(features)
    _has_candidates = bool(st.session_state.get("step_candidates"))
    _show_conflict  = _has_features and _has_candidates and not _from_candidates

    if _show_conflict:
        st.warning(
            "Existing manual/demo features are currently loaded. "
            "These may not belong to the uploaded STEP file."
        )
        if st.button("Clear existing features before accepting CAD candidates"):
            st.session_state.features = []
            st.session_state.features_from_candidates = False
            save_features_to_db([])
            st.success("Feature list cleared.")
            st.rerun()

    # ── Section 1: Current Manual / Accepted Features ────────────────────────
    st.subheader("Current Manual / Accepted Features")
    if not features:
        st.info("No features accepted yet. Accept candidates below, or add features manually via Data Tables.")
    else:
        display_cols = [
            "feature_name", "feature_type", "quantity",
            "x_pos", "y_pos", "diameter", "length", "width", "depth",
            "setup_label", "tolerance_note", "priority",
            "machining_action", "selected_for_machining",
        ]
        df = pd.DataFrame(features)
        for col in display_cols:
            if col not in df.columns:
                df[col] = None
        st.dataframe(
            df[display_cols].rename(columns={
                "feature_name":           "Name",
                "feature_type":           "Type",
                "quantity":               "Qty",
                "x_pos":                  "X (mm)",
                "y_pos":                  "Y (mm)",
                "diameter":               "Dia (mm)",
                "length":                 "L (mm)",
                "width":                  "W (mm)",
                "depth":                  "Depth (mm)",
                "setup_label":            "Setup",
                "tolerance_note":         "Tolerance",
                "priority":               "Priority",
                "machining_action":       "Action",
                "selected_for_machining": "Machine?",
            }),
            column_config={
                "Machine?": st.column_config.CheckboxColumn("Machine?"),
            },
            use_container_width=True,
            hide_index=True,
        )
        _n_machining = sum(1 for f in features if f.get("selected_for_machining", True))
        _n_excluded  = len(features) - _n_machining
        if _n_excluded > 0:
            st.info(
                f"{_n_machining} feature(s) selected for machining · "
                f"{_n_excluded} excluded (Existing Geometry / Reference Only)."
            )
        st.success(
            f"{len(features)} feature(s) accepted. "
            "Machining features are already selected. "
            "Continue to **6. Strategy / Operations**, or expand "
            "**Advanced: Add more detected geometry** below if needed."
        )
        if st.button("Next → Strategy / Operations", type="primary", key="_sfr_next_ops"):
            st.session_state._nav_page = "6. Strategy / Operations"
            st.rerun()

    st.divider()

    # ── Section 2: Detected CAD Feature Candidates ───────────────────────────
    # When features already exist, collapse into an expander so the page reads
    # as a review page rather than an input page.  contextlib.nullcontext()
    # acts as a no-op context manager for the fallback (no-features) case so
    # the rendering code below is shared without duplication.
    _cand_ctx = (
        st.expander("Advanced: Add more detected geometry", expanded=False)
        if features
        else contextlib.nullcontext()
    )

    if not features:
        st.subheader("Detected CAD Feature Candidates")
        st.caption("Candidates are not used in operation planning until you accept them.")

    with _cand_ctx:
        if not _candidates:
            st.info("No CAD candidates available. Upload a STEP file on **1. Upload / Overview** first.")
        else:
            _spt = st.session_state.get("starting_part_type", "Raw Block / Billet")
            if _spt != "Raw Block / Billet":
                st.info(
                    f"**{_spt} selected.** "
                    "Detected geometry includes existing features — only tick the rows you want to machine. "
                    "Ticked rows will be added as machining features."
                )
            st.caption(
                f"{len(_candidates)} candidate(s) detected from STEP geometry. "
                "Tick rows to select, then click **Add selected machining features**."
            )
            for _w in _cand_warns:
                st.warning(_w)
            for _error in _stock_errors:
                st.error(_error)

            _default_action = "Machine" if _is_raw_block else "Existing Geometry – No Machining"
            _rows = []
            for _c in _candidates:
                _cid = _c["candidate_id"]
                _is_added = _candidate_is_added(_c, _added_ids)
                _rows.append({
                    "accept":           (not _is_added) and _is_raw_block and not _stock_errors,
                    "status":           "Added ✓" if _is_added else "",
                    "candidate_id":     _cid,
                    "machining_action": _default_action,
                    "feature_type":     _c.get("feature_type", ""),
                    "feature_name":     _c.get("feature_name", ""),
                    "confidence":       _c.get("confidence", ""),
                    "setup_label":      _candidate_work_setup(_c),
                    "x_pos":            _candidate_work_value(_c, "x"),
                    "y_pos":            _candidate_work_value(_c, "y"),
                    "diameter":         _c.get("diameter"),
                    "length":           _c.get("length"),
                    "width":            _c.get("width"),
                    "depth":            _c.get("depth"),
                    "detection_note":   _c.get("detection_note", ""),
                })

            _edited = st.data_editor(
                pd.DataFrame(_rows),
                column_config={
                    "accept":           st.column_config.CheckboxColumn("Machine this?",     default=True),
                    "status":           st.column_config.TextColumn("Status",               disabled=True, width="small"),
                    "candidate_id":     st.column_config.TextColumn("ID",                   disabled=True, width="small"),
                    "machining_action": st.column_config.SelectboxColumn(
                        "Machining Action",
                        options=["Machine", "Existing Geometry – No Machining", "Reference Only"],
                        required=True,
                    ),
                    "feature_type": st.column_config.TextColumn("Type",             disabled=True),
                    "feature_name": st.column_config.TextColumn("Name",             disabled=True),
                    "confidence":   st.column_config.TextColumn("Confidence",       disabled=True, width="small"),
                    "setup_label":  st.column_config.TextColumn("Setup",            disabled=True, width="small"),
                    "x_pos":        st.column_config.NumberColumn("X (mm)",         disabled=True, format="%.2f"),
                    "y_pos":        st.column_config.NumberColumn("Y (mm)",         disabled=True, format="%.2f"),
                    "diameter":     st.column_config.NumberColumn("Dia (mm)",       disabled=True, format="%.2f"),
                    "length":       st.column_config.NumberColumn("L (mm)",         disabled=True, format="%.2f"),
                    "width":        st.column_config.NumberColumn("W (mm)",         disabled=True, format="%.2f"),
                    "depth":        st.column_config.NumberColumn("Depth (mm)",     disabled=True, format="%.2f"),
                    "detection_note": st.column_config.TextColumn("Detection Note", disabled=True),
                },
                use_container_width=True,
                hide_index=True,
                key="cand_editor",
            )

            if st.button("Add selected machining features", type="primary"):
                _n_added = _commit_candidate_selections(_edited, _candidates)
                if _n_added > 0:
                    st.session_state.features_from_candidates = True
                    save_features_to_db(st.session_state.features)
                    st.success(f"Added {_n_added} feature(s) to the machining list.")
                    st.rerun()
                else:
                    st.info("No rows ticked — tick the checkbox for each feature you want to machine.")

    st.divider()

    # ── Section 3: Detection Notes ────────────────────────────────────────────
    st.subheader("Detection Notes")
    if not features:
        st.info("No features to validate.")
    else:
        stk_l = stock.get("length") or 0
        stk_w = stock.get("width")  or 0
        warnings_found = False
        for i, feat in enumerate(features):
            issues = []
            name  = feat.get("feature_name", "").strip()
            qty   = feat.get("quantity") or 0
            depth = feat.get("depth")    or 0
            xpos  = feat.get("x_pos")    or 0
            ypos  = feat.get("y_pos")    or 0

            if not name:
                issues.append("Missing feature name")
            if qty < 1:
                issues.append(f"Quantity is {qty} (must be ≥ 1)")
            if depth == 0 and feat.get("feature_type") != "Face Milling":
                issues.append("Depth is 0 or missing")
            if stk_l > 0 and xpos > stk_l:
                issues.append(f"X position {xpos} mm exceeds stock length {stk_l} mm")
            if stk_w > 0 and ypos > stk_w:
                issues.append(f"Y position {ypos} mm exceeds stock width {stk_w} mm")

            if issues:
                warnings_found = True
                label = name if name else f"Feature #{i + 1}"
                for msg in issues:
                    st.warning(f"**{label}:** {msg}")

        if not warnings_found:
            st.success("All features passed basic validation checks.")

    st.divider()

    # ── Pre-flight Checklist ──────────────────────────────────────────────────
    st.subheader("Pre-flight Checklist")

    tools = st.session_state.get("tools", [])

    has_stock    = bool(stock and stock.get("length") and stock.get("length") > 0)
    has_machine  = bool(machine)
    has_material = bool(material)
    has_tools    = bool(tools)
    has_features = bool(features)

    # Re-evaluate validation for checklist
    any_critical = False
    if features:
        for feat in features:
            if (not feat.get("feature_name", "").strip()
                    or (feat.get("quantity") or 0) < 1
                    or (
                        (feat.get("depth") or 0) == 0
                        and feat.get("feature_type") != "Face Milling"
                    )):
                any_critical = True
                break

    checks = [
        (has_stock or step_ok, "Stock dimensions entered or STEP file uploaded"),
        (not _stock_errors,       "Stock dimensions and placement contain the complete part"),
        (has_machine,           "Machine selected"),
        (has_material,          "Material selected"),
        (has_tools,             "Tool library loaded"),
        (has_features,          "At least one feature defined"),
        (has_features and not any_critical, "Features have no critical validation warnings"),
    ]

    all_pass = all(ok for ok, _ in checks)
    for ok, label in checks:
        icon = "✅" if ok else "⚠️"
        st.markdown(f"{icon} {label}")

    st.divider()
    if all_pass:
        st.success("All checks passed — you may proceed to **6. Strategy / Operations**.")
    else:
        st.warning("Resolve the items above before generating the operation plan.")


def page_operation_plan():
    st.title("Strategy / Operations")
    st.caption(
        "Review the proposed machining sequence, tools, feeds, setup notes, and process warnings."
    )
    st.divider()

    if not st.session_state.features:
        st.warning(
            "No features defined. Upload a STEP file and accept candidates on "
            "**Select Machining Work** first."
        )
        return

    if not st.session_state.tools:
        st.warning("No tools in library. Please go to **5. Tools** first.")
        return

    _all_features       = st.session_state.features
    _machining_features = [f for f in _all_features if f.get("selected_for_machining", True)]
    _excluded_count     = len(_all_features) - len(_machining_features)

    operations = plan_operations(
        _machining_features,
        st.session_state.tools,
        st.session_state.selected_material,
        st.session_state.selected_machine,
    )
    st.session_state.operations = operations
    _machine_feasibility = machine_feasibility_summary(operations)

    mat  = st.session_state.selected_material
    mach = st.session_state.selected_machine
    st.info(
        f"Material: **{mat['name']}** | Machine: **{mach['machine_name']}** | "
        f"Operations generated: **{len(operations)}**"
    )
    if _excluded_count > 0:
        st.info(
            f"**{_excluded_count}** existing/reference feature(s) excluded from operation planning."
        )
    if _machine_feasibility["blocked"] > 0:
        st.error(
            f"**Planning blocked:** {_machine_feasibility['blocked']} operation(s) "
            "cannot be verified on the selected machine. Resolve the machine "
            "capability or feature-orientation warnings before release."
        )
    elif _machine_feasibility["requires_setup"] > 0:
        st.warning(
            f"**Additional workholding required:** "
            f"{_machine_feasibility['requires_setup']} operation(s) need a manual "
            "flip or re-fixture on the selected machine."
        )

    # ── Summary cards ─────────────────────────────────────────────────────────
    _total_path_mm = sum(op.get("est_path_length_mm", 0) for op in operations)
    _unique_tools  = set(op.get("tool_number") for op in operations)
    _tool_changes  = max(len(_unique_tools) - 1, 0)
    _secondary_setups = secondary_setup_labels(operations)
    _has_setup2 = bool(_secondary_setups)
    _has_boring    = any(op.get("operation_type") == "Boring" for op in operations)

    sc1, sc2, sc3, sc4 = st.columns(4)
    sc1.metric("Operations",       len(operations))
    sc2.metric("Tool Changes",     _tool_changes)
    sc3.metric("Est. Path Length", f"{_total_path_mm:.0f} mm")
    sc4.metric("Additional Setups", len(_secondary_setups))

    st.divider()

    # ── Warnings ──────────────────────────────────────────────────────────────
    if _has_setup2:
        st.warning(
            "**Additional Setup Orientation Required:** "
            f"{', '.join(_secondary_setups)} operation(s) require re-fixturing or side access. "
            "Verify workholding, datum transfer, and fixture clearance before machining."
        )
    if _has_boring:
        st.warning(
            "**Boring Tool Required:** Verify boring bar minimum bore, maximum bore, reach, "
            "and rigidity before machining."
        )
    st.info(
        "**Draft / Planning Only:** These are planning-level estimates. "
        "Verify feeds, speeds, and toolpaths in your CAM system before running on the machine."
    )

    # ── Setup 1 / Setup 2 split ───────────────────────────────────────────────
    def _is_setup2_op(op):
        return is_secondary_setup_operation(op)

    _setup1_ops = [op for op in operations if not _is_setup2_op(op)]
    _setup2_ops = [op for op in operations if     _is_setup2_op(op)]

    display_cols = (
        [c for c in pd.DataFrame(operations).columns if not c.startswith("_")]
        if operations else []
    )

    st.subheader("Primary Setup Operations")
    if _setup1_ops and display_cols:
        _df1 = pd.DataFrame(_setup1_ops)[display_cols]
        _df1.columns = [c.replace("_", " ").title() for c in _df1.columns]
        st.dataframe(_df1, use_container_width=True, hide_index=True)
    else:
        st.info("No primary setup operations.")

    if _has_setup2:
        st.subheader("Additional Setup Operations")
        if _setup2_ops and display_cols:
            _df2 = pd.DataFrame(_setup2_ops)[display_cols]
            _df2.columns = [c.replace("_", " ").title() for c in _df2.columns]
            st.dataframe(_df2, use_container_width=True, hide_index=True)

    st.divider()

    # ── Full operations table ─────────────────────────────────────────────────
    st.subheader("Full Operations Table")
    if operations and display_cols:
        df = pd.DataFrame(operations)[display_cols]
        df.columns = [c.replace("_", " ").title() for c in df.columns]
        st.dataframe(df, use_container_width=True, hide_index=True)

    csv = pd.DataFrame(operations).to_csv(index=False).encode()
    st.download_button(
        "Download Operation Plan (CSV)",
        data=csv,
        file_name="operation_plan.csv",
        mime="text/csv",
    )

    st.divider()
    if _machine_feasibility["blocked"] > 0:
        st.error(
            "Operation planning requires manual engineering review before estimating "
            "or exporting this job."
        )
    else:
        st.success("Next: go to **7. Estimate / Pricing** to review machining time and quote.")


def page_time_estimate():
    st.title("Estimate / Pricing")
    st.caption(
        "Review machining time, costing assumptions, tolerance impact, "
        "currency conversion, and customer quote."
    )
    st.divider()

    if "operations" not in st.session_state or not st.session_state.operations:
        st.warning("No operations planned. Please run **6. Strategy / Operations** first.")
        return

    _machine_feasibility = machine_feasibility_summary(st.session_state.operations)
    if _machine_feasibility["blocked"] > 0:
        st.error(
            "Pricing is blocked because one or more operations require manual "
            "engineering review. Resolve the operation-plan warnings first."
        )
        return

    result = estimate_time(
        st.session_state.operations,
        st.session_state.selected_machine,
        st.session_state.selected_material,
        st.session_state.features,
    )
    st.session_state.time_result = result

    # ── Top summary cards ─────────────────────────────────────────────────────
    effort_color = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(result["effort_label"], "⚪")
    _tc1, _tc2, _tc3, _tc4 = st.columns(4)
    _tc1.metric("Total Machine Time", f"{result['total_machine_time_min']:.1f} min",
                delta=f"{result['total_machine_time_min'] / 60:.2f} hrs")
    _tc2.metric("Cutting Time",       f"{result['cutting_time_min']:.1f} min")
    _tc3.metric("Operations",         result["num_operations"])
    _tc4.metric("Effort Level",       f"{effort_color} {result['effort_label']}",
                delta=f"Score: {result['effort_score_value']:.1f}")

    st.divider()

    # ── Time & Effort Summary ─────────────────────────────────────────────────
    st.subheader("Time & Effort Summary")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Setup Time",       f"{result['setup_time_min']:.1f} min")
    c2.metric("Cutting Time",     f"{result['cutting_time_min']:.1f} min")
    c3.metric("Rapid Movement",   f"{result['rapid_time_min']:.2f} min")
    c4.metric("Tool Change Time", f"{result['tool_change_time_min']:.2f} min")

    d1, d2, d3 = st.columns(3)
    d1.metric("Total Machine Time", f"{result['total_machine_time_min']:.1f} min",
              delta=f"{result['total_machine_time_min']/60:.2f} hrs")
    d2.metric("Operator Effort Time", f"{result['operator_effort_min']:.1f} min")
    d3.metric("Effort Score", f"{effort_color} {result['effort_label']}",
              delta=f"Score: {result['effort_score_value']:.1f}")

    st.subheader("Details")
    details = {
        "Metric": [
            "Number of Operations",
            "Number of Tool Changes",
            "Safety Factor Applied",
            "Effort Score",
            "Effort Level",
        ],
        "Value": [
            result["num_operations"],
            result["num_tool_changes"],
            st.session_state.selected_material.get("safety_factor", 1.0),
            result["effort_score_value"],
            result["effort_label"],
        ],
    }
    st.table(pd.DataFrame(details))

    report_df = pd.DataFrame([{
        "Metric": k.replace("_", " ").title(),
        "Value": str(v),
    } for k, v in result.items()])
    csv = report_df.to_csv(index=False).encode()
    st.download_button(
        "Download Time & Effort Report (CSV)",
        data=csv,
        file_name="time_effort_report.csv",
        mime="text/csv",
    )

    st.divider()

    # ── Quote Configuration ───────────────────────────────────────────────────
    st.subheader("Quote Configuration")
    st.caption(
        "Enter your workshop rates and job parameters. "
        "All values persist while you navigate pages."
    )

    # ── Costing currency selector ─────────────────────────────────────
    _CURRENCY_OPTS = ["INR (₹)", "USD ($)", "EUR (€)", "AED", "OMR", "SAR"]
    _CUR_SYM = {"INR (₹)": "₹", "USD ($)": "$", "EUR (€)": "€", "AED": "AED", "OMR": "OMR", "SAR": "SAR"}
    _sym = _CUR_SYM[st.selectbox("Costing Currency", _CURRENCY_OPTS, key="est_currency")]
    st.caption(
        "All input rates are assumed to be in the selected costing currency. "
        "Changing this does not auto-convert entered rates."
    )

    # ── Rates row ────────────────────────────────────────────────────
    _qc1, _qc2, _qc3 = st.columns(3)
    with _qc1:
        st.number_input(f"Machine Hourly Rate ({_sym}/hr)",
                        min_value=0.0, step=50.0, key="est_machine_rate",
                        help="Cost to operate the VMC per hour")
        st.number_input(f"Operator Hourly Rate ({_sym}/hr)",
                        min_value=0.0, step=10.0, key="est_operator_rate",
                        help="Operator wages per hour (loaded rate)")
    with _qc2:
        st.number_input(f"Setup Fixed Cost ({_sym})",
                        min_value=0.0, step=50.0, key="est_setup_cost",
                        help="Flat cost for fixturing, zero-setting, first-off — shared across batch")
        st.number_input(f"Tool Wear / Consumables ({_sym})",
                        min_value=0.0, step=50.0, key="est_tool_cost",
                        help="Estimated insert/tool wear and coolant cost for this job — shared across batch")
    with _qc3:
        st.number_input(f"Material Price ({_sym}/kg)",
                        min_value=0.0, step=5.0, key="est_material_price_kg")
        st.number_input("Material Waste / Offcut (%)",
                        min_value=0.0, max_value=80.0, step=1.0, key="est_material_waste_pct",
                        help="Extra allowance for offcuts and setup scrap")

    # ── Job parameters row ───────────────────────────────────────────
    _qr1, _qr2, _qr3 = st.columns(3)
    with _qr1:
        st.number_input("Batch Quantity (parts)", min_value=1, step=1, key="est_batch_qty",
                        help="Setup and tooling costs are divided across the batch")
        st.number_input("Profit Margin (%)",
                        min_value=0.0, max_value=200.0, step=5.0, key="est_margin_pct")
    with _qr2:
        _TOL_OPTS = [
            "General (±0.20 mm) — ×1.00",
            "Medium (±0.10 mm) — ×1.15",
            "Tight (±0.05 mm) — ×1.35",
            "Very tight (±0.02 mm) — ×1.60",
        ]
        _TOL_MUL = {
            "General (±0.20 mm) — ×1.00":    1.00,
            "Medium (±0.10 mm) — ×1.15":     1.15,
            "Tight (±0.05 mm) — ×1.35":      1.35,
            "Very tight (±0.02 mm) — ×1.60": 1.60,
        }
        st.selectbox("Tolerance Level", _TOL_OPTS, key="est_tolerance",
                     help="Tighter tolerances require more passes, slower feeds, finer tooling")
        _tol_mul = _TOL_MUL[st.session_state.est_tolerance]
        st.caption(f"Tolerance multiplier: ×{_tol_mul:.2f} applied to subtotal")
    with _qr3:
        st.slider("Complexity Factor", min_value=1.0, max_value=2.0, step=0.05,
                  key="est_complexity",
                  help="1.0 = standard job; 1.5 = complex fixturing; 2.0 = very complex")
        st.caption(
            f"Complexity multiplier: ×{st.session_state.est_complexity:.2f}  —  "
            "reflects multi-setup, tight-access, or special-sequence jobs"
        )

    # ── Quote currency ───────────────────────────────────────────────
    st.checkbox("Show customer quote in another currency", key="est_show_quote_currency")
    _show_quote = st.session_state.est_show_quote_currency
    _cost_cur   = st.session_state.est_currency
    _qsym       = None
    _exchange_rate = 1.0

    if _show_quote:
        _qcol1, _qcol2 = st.columns(2)
        with _qcol1:
            st.selectbox("Quote Currency", _CURRENCY_OPTS, key="est_quote_currency")
        _quote_cur = st.session_state.est_quote_currency

        if _quote_cur == _cost_cur:
            st.info("Quote currency matches costing currency — no conversion needed.")
            _show_quote = False
        else:
            _cost_cur_code  = _cost_cur.split(" ")[0]
            _quote_cur_code = _quote_cur.split(" ")[0]
            with _qcol2:
                st.number_input(
                    f"Exchange rate: 1 {_quote_cur_code} = ? {_cost_cur_code}",
                    min_value=0.0001, step=0.1, format="%.4f",
                    key="est_exchange_rate",
                    help="Manual rate — no live API. Check xe.com or wise.com for current rates.",
                )
            _exchange_rate = st.session_state.est_exchange_rate
            _qsym = _CUR_SYM[_quote_cur]
            st.info(
                "Reference exchange rates: "
                "[Xe Currency Converter](https://www.xe.com/currencyconverter/) · "
                "[Wise Currency Converter](https://wise.com/gb/currency-converter/)"
            )

    # ── Calculations ─────────────────────────────────────────────────────────
    stock  = st.session_state.stock
    mat    = st.session_state.selected_material
    _density       = mat.get("density", 2.7)
    _stock_vol_cm3 = stock.get("stock_volume", 0) or 0
    _stock_wt_kg   = (_stock_vol_cm3 / 1000) * _density

    _material_cost  = _stock_wt_kg * st.session_state.est_material_price_kg * (
        1 + st.session_state.est_material_waste_pct / 100
    )
    _cutting_min    = result["total_machine_time_min"] - result["setup_time_min"]
    _machine_cost   = (_cutting_min / 60) * st.session_state.est_machine_rate
    _operator_cost  = (result["operator_effort_min"] / 60) * st.session_state.est_operator_rate
    _batch_qty      = st.session_state.est_batch_qty
    _setup_part     = st.session_state.est_setup_cost  / _batch_qty
    _tool_part      = st.session_state.est_tool_cost   / _batch_qty

    _subtotal_base  = _material_cost + _machine_cost + _operator_cost + _setup_part + _tool_part
    _tol_impact     = _subtotal_base * (_tol_mul - 1.0)
    _cplx_impact    = (_subtotal_base + _tol_impact) * (st.session_state.est_complexity - 1.0)
    _subtotal_adj   = _subtotal_base + _tol_impact + _cplx_impact
    _margin_amt     = _subtotal_adj * (st.session_state.est_margin_pct / 100)
    _price_per_part = _subtotal_adj + _margin_amt
    _batch_total    = _price_per_part * _batch_qty

    # ── Results display ───────────────────────────────────────────────────────
    st.divider()
    st.warning(
        "This is a quotation/planning estimate. "
        "Final price should be reviewed by the workshop before quoting to customer."
    )

    # ── Internal Costing Estimate ─────────────────────────────────────────────
    st.subheader(f"Internal Costing Estimate ({_sym})")

    _qm1, _qm2, _qm3, _qm4 = st.columns(4)
    _qm1.metric("Machine Time Cost",    f"{_sym} {_machine_cost:,.2f}")
    _qm2.metric("Operator Cost",        f"{_sym} {_operator_cost:,.2f}")
    _qm3.metric("Material Cost / Part", f"{_sym} {_material_cost:,.2f}",
                delta=f"{_stock_wt_kg:.3f} kg")
    _qm4.metric("Sell Price / Part",    f"{_sym} {_price_per_part:,.2f}",
                delta=f"Margin: {_sym} {_margin_amt:,.2f}")

    st.metric(
        f"Batch Total — {_batch_qty} part{'s' if _batch_qty > 1 else ''}",
        f"{_sym} {_batch_total:,.2f}",
    )

    # ── Customer Quote ────────────────────────────────────────────────────────
    if _show_quote and _qsym is not None:
        _quote_price_per_part = _price_per_part / _exchange_rate
        _quote_batch_total    = _batch_total    / _exchange_rate
        st.subheader(f"Customer Quote ({_qsym})")
        _cqm1, _cqm2 = st.columns(2)
        _cqm1.metric("Sell Price / Part (Customer)",
                     f"{_qsym} {_quote_price_per_part:,.2f}")
        _cqm2.metric(
            f"Batch Total — {_batch_qty} part{'s' if _batch_qty > 1 else ''} (Customer)",
            f"{_qsym} {_quote_batch_total:,.2f}",
        )
        st.caption(
            f"Conversion: {_sym} {_price_per_part:,.2f} / {_exchange_rate:.4f} "
            f"= {_qsym} {_quote_price_per_part:,.2f} per part"
        )

    # ── Cost Breakdown ────────────────────────────────────────────────────────
    st.divider()
    st.subheader("Cost Breakdown")

    _tol_label = st.session_state.est_tolerance.split("—")[0].strip()
    _cost_col_values = [
        round(_material_cost, 2),
        round(_machine_cost,  2),
        round(_operator_cost, 2),
        round(_setup_part,    2),
        round(_tool_part,     2),
        round(_tol_impact,    2),
        round(_cplx_impact,   2),
        round(_subtotal_adj,  2),
        round(_margin_amt,    2),
        round(_price_per_part,2),
    ]
    _cost_items = [
        "Material (incl. waste)",
        "Machine time",
        "Operator",
        f"Setup fixed (/ {_batch_qty} parts)",
        f"Tool / consumables (/ {_batch_qty} parts)",
        f"Tolerance adjustment ({_tol_label})",
        f"Complexity adjustment (x{st.session_state.est_complexity:.2f})",
        "Subtotal before margin",
        f"Profit margin ({st.session_state.est_margin_pct:.0f}%)",
        "Sell price per part",
    ]
    _breakdown_data = {
        "Cost Item": _cost_items,
        f"Per Part ({_sym})": _cost_col_values,
    }
    if _show_quote and _qsym is not None:
        _breakdown_data[f"Per Part ({_qsym}) — customer quote"] = [
            round(v / _exchange_rate, 2) for v in _cost_col_values
        ]
    _breakdown = pd.DataFrame(_breakdown_data)
    st.dataframe(_breakdown, use_container_width=True, hide_index=True)

    _cost_csv = _breakdown.to_csv(index=False).encode()
    st.download_button(
        "Download Quotation Estimate (CSV)",
        data=_cost_csv,
        file_name="quotation_estimate.csv",
        mime="text/csv",
    )

    st.divider()
    st.success("Next: go to **8. Export / Setup Sheet** to generate the setup sheet and G-code.")


def page_visual_preview():
    st.header("8. Approximate Process Preview")

    st.warning(
        "This is not the final machined part. This is an approximate planning preview "
        "based on STEP bounding geometry and manual/detected features. "
        "Verify the part and toolpath in CAM/simulation before machining."
    )

    if not st.session_state.features:
        st.info("No features defined yet. Load demo features in Feature Input.")
        return

    stock = st.session_state.stock
    features = st.session_state.features

    tab1, tab2 = st.tabs(["Top View (Planning Preview)", "3D View (Planning Preview)"])

    step_geometry = st.session_state.get("step_geometry")

    if step_geometry and step_geometry.get("success"):
        ec = step_geometry.get("edge_count", 0)
        cc = step_geometry.get("circle_count", 0)
        st.info(
            f"STEP bounding wireframe loaded — **{ec}** straight edges + **{cc}** circular edges. "
            "Showing approximate part wireframe for planning reference only. "
            "This is not a machining simulation."
        )
    else:
        st.info("No STEP file geometry available — showing approximate feature layout only. "
                "Upload a STEP file on page 1 to see the approximate part wireframe.")

    with tab1:
        fig_top = build_top_view(stock, features, step_geometry=step_geometry)
        st.plotly_chart(fig_top, use_container_width=True)

    with tab2:
        fig_3d = build_3d_view(stock, features, step_geometry=step_geometry)
        st.plotly_chart(fig_3d, use_container_width=True)


def page_cnc_export():
    st.title("Export / Setup Sheet")
    st.caption(
        "Review draft CNC output, setup notes, safety warnings, and downloadable job documents."
    )
    st.divider()

    st.error(
        "DO NOT RUN THIS PROGRAM DIRECTLY ON A MACHINE. "
        "This is draft planning code only. Verify in CAM/simulator and by a qualified "
        "CNC programmer before use on any real machine."
    )
    render_vmc_handover_test_pack()

    if "operations" not in st.session_state or not st.session_state.operations:
        st.warning("No operations available. Please run **6. Strategy / Operations** first.")
        return

    _machine_feasibility = machine_feasibility_summary(st.session_state.operations)
    if _machine_feasibility["blocked"] > 0:
        st.error(
            "CNC export is blocked because one or more operations are unsupported "
            "or have unresolved setup orientation. Resolve the operation-plan "
            "warnings and regenerate the plan."
        )
        return

    gcode = generate_gcode(
        st.session_state.operations,
        st.session_state.selected_machine,
        st.session_state.stock,
    )

    mach = st.session_state.selected_machine
    mat  = st.session_state.selected_material

    # ── Status cards ──────────────────────────────────────────────────────────
    _secondary_setups = secondary_setup_labels(st.session_state.operations)
    _has_setup2 = bool(_secondary_setups)

    _sc1, _sc2, _sc3, _sc4 = st.columns(4)
    _sc1.metric("Operations",       len(st.session_state.operations))
    _sc2.metric("Machine",          mach.get("machine_name", "—"))
    _sc3.metric("Material",         mat.get("name", "—"))
    _sc4.metric("Additional Setups", len(_secondary_setups))

    if _has_setup2:
        st.warning(
            "**Additional Setup Orientation Required:** "
            f"{', '.join(_secondary_setups)} work requires re-fixturing or side access. "
            "Re-indicate the part and verify workholding before continuing."
        )

    st.divider()

    # ── Export Readiness ──────────────────────────────────────────────────────
    st.subheader("Export Readiness")

    stat_col1, stat_col2 = st.columns(2)
    with stat_col1:
        st.markdown("**Program Statistics**")
        lines = gcode.split("\n")
        st.write(f"- Total lines: **{len(lines)}**")
        st.write(f"- Tool changes: **{gcode.count('M6')}**")
        st.write(f"- Canned cycles (G81/G76): **{gcode.count('G81') + gcode.count('G76')}**")
        st.write(f"- Coolant ON (M8): **{gcode.count('M8')}**")

    with stat_col2:
        st.markdown("**Active Configuration**")
        st.write(f"- Machine: **{mach['machine_name']}**")
        st.write(f"- Controller: **{mach['controller']}**")
        st.write(f"- Material: **{mat['name']}**")
        st.write(f"- Operations: **{len(st.session_state.operations)}**")

    st.divider()

    # ── Draft CNC Program ─────────────────────────────────────────────────────
    st.subheader("Draft CNC Program")
    st.code(gcode, language="text")

    st.divider()

    # ── Setup Sheet ───────────────────────────────────────────────────────────
    st.subheader("Operator Setup Sheet")
    st.caption(
        "A printable one-page setup sheet summarising the job, tools, operation sequence, "
        "and cost estimate. Open the downloaded file in any browser and use Print → Save as PDF."
    )

    ss_col1, ss_col2 = st.columns([2, 1])
    with ss_col1:
        job_name = st.text_input(
            "Job / Part Name",
            value=st.session_state.get("uploaded_filename", "CNC Job") or "CNC Job",
            help="Printed as the document title on the setup sheet",
        )

    # Build optional cost dict from session if available
    cost_result = None
    if "time_result" in st.session_state and st.session_state.time_result:
        tr = st.session_state.time_result
        stock_ss = st.session_state.stock
        mat_ss = st.session_state.selected_material
        density_ss = mat_ss.get("density", 2.7)
        stock_vol_ss = stock_ss.get("stock_volume", 0)
        stock_weight_ss = (stock_vol_ss / 1000) * density_ss
        cost_result = {
            "Material (incl. 15% waste)": round(stock_weight_ss * 5.0 * 1.15, 2),
            "Setup Cost": round((tr.get("setup_time_min", 20) / 60) * 100, 2),
            "Machining Cost": round(((tr.get("total_machine_time_min", 0) - tr.get("setup_time_min", 20)) / 60) * 75, 2),
            "Subtotal": round(
                stock_weight_ss * 5.0 * 1.15
                + (tr.get("setup_time_min", 20) / 60) * 100
                + ((tr.get("total_machine_time_min", 0) - tr.get("setup_time_min", 20)) / 60) * 75,
                2,
            ),
        }

    setup_html = generate_setup_sheet(
        operations=st.session_state.operations,
        machine=st.session_state.selected_machine,
        material=st.session_state.selected_material,
        stock=st.session_state.stock,
        features=st.session_state.features,
        time_result=st.session_state.get("time_result", {
            "total_machine_time_min": 0, "cutting_time_min": 0,
            "setup_time_min": 20, "effort_label": "—",
            "num_operations": len(st.session_state.operations),
            "num_tool_changes": 0,
        }),
        cost_result=cost_result,
        job_name=job_name,
        notes=load_job_notes() or None,
    )

    st.download_button(
        "Download Setup Sheet (.html)",
        data=setup_html.encode("utf-8"),
        file_name=f"setup_sheet_{job_name.replace(' ', '_')}.html",
        mime="text/html",
        type="primary",
    )

    with st.expander("Preview Setup Sheet (HTML source)"):
        st.html(setup_html)

    st.divider()

    # ── Downloads ─────────────────────────────────────────────────────────────
    st.subheader("Downloads")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.download_button(
            "Download Draft CNC Program (.nc)",
            data=gcode.encode(),
            file_name="draft_cnc_program.nc",
            mime="text/plain",
            type="primary",
        )

    if "operations" in st.session_state:
        with col2:
            ops_csv = pd.DataFrame(st.session_state.operations).to_csv(index=False).encode()
            st.download_button(
                "Download Operation Plan (CSV)",
                data=ops_csv,
                file_name="operation_plan.csv",
                mime="text/csv",
            )

    if "time_result" in st.session_state:
        with col3:
            time_df = pd.DataFrame([{
                "Metric": k.replace("_", " ").title(),
                "Value": v,
            } for k, v in st.session_state.time_result.items()])
            time_csv = time_df.to_csv(index=False).encode()
            st.download_button(
                "Download Time Report (CSV)",
                data=time_csv,
                file_name="time_effort_report.csv",
                mime="text/csv",
            )


def page_job_notes():
    st.title("History")
    st.caption("Log notes, sign-offs, and revision history for this job. All entries are saved to the local database.")
    st.divider()

    notes = load_job_notes()

    # ── Summary cards ─────────────────────────────────────────────────
    _job_fname = st.session_state.get("uploaded_filename") or "—"
    _notes_count = len(notes)
    _last_updated = notes[-1]["timestamp"] if notes else "—"

    hc1, hc2, hc3 = st.columns(3)
    hc1.metric("Current Job", _job_fname)
    hc2.metric("Notes Logged", _notes_count)
    hc3.metric("Last Entry", _last_updated)

    st.divider()

    # ── Add new note ──────────────────────────────────────────────────
    st.subheader("Add Note")
    nc1, nc2, nc3 = st.columns(3)
    author = nc1.text_input("Author / Operator", value="", placeholder="e.g. Ravi Kumar")
    stage = nc2.selectbox("Stage", [
        "Upload", "Machine Setup", "Tool Library", "Material Setup",
        "Feature Input", "Operation Plan", "Time Estimate", "Visual Preview",
        "G-code Export", "Setup Sheet", "General",
    ])
    note_type = nc3.selectbox("Note Type", [
        "Observation", "Change", "Approval", "Issue", "Sign-off", "Other"
    ])
    note_text = st.text_area("Note", placeholder="Describe the change, observation, or sign-off…", height=100)

    if st.button("Add Note", type="primary"):
        if not note_text.strip():
            st.warning("Please enter a note before saving.")
        else:
            add_job_note(
                stage=stage,
                author=author.strip() or "—",
                note_type=note_type,
                note=note_text.strip(),
            )
            st.success("Note saved.")
            st.rerun()

    st.divider()

    # ── Existing notes ────────────────────────────────────────────────
    st.subheader("Job Notes")
    if not notes:
        st.info("No notes yet. Add the first note above.")
    else:
        df = pd.DataFrame(notes)[["id", "timestamp", "stage", "author", "note_type", "note"]]
        df.columns = ["ID", "Timestamp", "Stage", "Author", "Type", "Note"]

        type_colour = {
            "Observation": "🔵", "Change": "🟡", "Approval": "🟢",
            "Issue": "🔴", "Sign-off": "✅", "Other": "⚪",
        }
        for row in notes:
            icon = type_colour.get(row["note_type"], "⚪")
            with st.expander(
                f"{icon} [{row['timestamp']}]  {row['stage']} — {row['note_type']}  ·  {row['author']}"
            ):
                st.write(row["note"])
                if st.button("Delete this note", key=f"del_note_{row['id']}"):
                    delete_job_note(row["id"])
                    st.rerun()

        st.divider()
        csv_notes = df.to_csv(index=False).encode()
        cc1, cc2 = st.columns(2)
        cc1.download_button(
            "Export Notes as CSV",
            data=csv_notes,
            file_name="job_notes.csv",
            mime="text/csv",
        )
        if cc2.button("Clear All Notes", type="secondary"):
            clear_all_job_notes()
            st.rerun()

    st.divider()

    # ── Saved / Current Job Information ──────────────────────────────
    st.subheader("Saved / Current Job Information")
    st.caption("Read-only snapshot of the current job state.")
    _ji_features  = st.session_state.get("features", [])
    _ji_ops       = st.session_state.get("operations", [])
    _ji_mat       = st.session_state.get("selected_material", {}) or {}
    _ji_machine   = st.session_state.get("selected_machine", {}) or {}
    ji1, ji2, ji3, ji4 = st.columns(4)
    ji1.metric("STEP File", st.session_state.get("uploaded_filename") or "—")
    ji2.metric("Features", len(_ji_features))
    ji3.metric("Operations", len(_ji_ops))
    ji4.metric("Material", _ji_mat.get("material_name", "—"))
    if _ji_machine:
        ji_m1, ji_m2 = st.columns(2)
        ji_m1.metric("Machine", _ji_machine.get("machine_name", "—"))
        ji_m2.metric("Controller", _ji_machine.get("controller", "—"))


def page_select_machining_work():
    st.title("Select Machining Work")
    st.caption(
        "Review detected CAD features, confirm which ones to machine, "
        "then proceed to Setup & Feature Review."
    )

    _spt          = st.session_state.get("starting_part_type", "Raw Block / Billet")
    _parse_result = st.session_state.get("step_parse_result")
    _added_ids    = st.session_state.get("added_candidate_ids", set())
    _features     = st.session_state.get("features", [])

    if not _parse_result:
        st.info("No STEP file loaded. Upload a part on **1. Upload / Overview** first.")
        if st.button("Go to Part Setup", type="primary", key="_smw_go_part_setup"):
            st.session_state._nav_page = "Part Setup"
            st.rerun()
        return

    _is_raw_block = _spt == "Raw Block / Billet"
    _candidates = _stock_adjusted_candidates()
    _cand_warns = (
        list(st.session_state.get("step_candidate_warnings", []))
        + list(st.session_state.get("_starting_part_policy_warnings", []))
    )
    _stock_errors = list(st.session_state.get("_starting_part_policy_errors", []))
    st.session_state._smw_preview_candidates = _candidates

    _job_file = st.session_state.get("uploaded_filename") or "STEP loaded"
    _jm1, _jm2, _jm3, _jm4 = st.columns(4)
    _jm1.metric("STEP File", _job_file)
    _jm2.metric("Detected", len(_candidates))
    _jm3.metric("Selected", len(_features))
    _jm4.metric("Starting From", _spt)
    st.divider()

    # Capture previous highlight IDs so the rerun-on-change guard below works
    # even though the 3D panel (left) renders before the selection panel (right).
    _prev_hl_ids = st.session_state.get("_smw_highlight_candidate_ids") or set()

    _left, _right = st.columns([2.2, 1.8])

    with _left:
        _render_3d_panel("_smw_3d_", large=True)

    with _right:
        st.subheader("Feature Candidates")

        _default_action = "Machine" if _is_raw_block else "Existing Geometry – No Machining"

        if not _is_raw_block:
            st.info(
                f"**{_spt}** — existing geometry is pre-selected as 'No Machining'. "
                "Tick only the features you want to machine."
            )

        if not _candidates:
            st.info("No feature candidates detected from STEP file.")
        else:
            for _w in _cand_warns:
                st.warning(_w)
            for _error in _stock_errors:
                st.error(_error)

            _all_types = sorted({c.get("feature_type", "Unknown") for c in _candidates})
            _sel_types = st.multiselect(
                "Filter by type",
                options=_all_types,
                default=_all_types,
                key="_smw_type_filter",
            )
            _filtered = [c for c in _candidates if c.get("feature_type", "Unknown") in _sel_types]
            _candidate_by_id = {
                candidate.get("candidate_id"): candidate
                for candidate in _filtered
            }

            def _member_is_added(member_id):
                candidate = _candidate_by_id.get(member_id)
                return bool(candidate) and _candidate_is_added(candidate, _added_ids)

            # ── Grouping toggle ─────────────────────────────────────────────
            _use_grouping = st.toggle(
                "Group similar detected geometry",
                value=True,
                key="_smw_group_toggle",
                help="Combines candidates with the same type and similar dimensions into one row.",
            )
            if _use_grouping:
                st.caption(
                    "Grouped view combines similar detected geometry. "
                    "For fabricated/rework parts, select only the groups that need machining now."
                )

            if _use_grouping:
                # ── GROUPED MODE (card-style selection) ─────────────────────
                _groups = _build_candidate_groups(_filtered, _spt)

                # Pre-seed widget keys so checkboxes/selects have correct defaults
                # before any user interaction on this render.
                for _gi, _g in enumerate(_groups):
                    _suffix = _group_widget_suffix(_g)
                    _ka = f"_smw_card_accept_{_suffix}"
                    _kx = f"_smw_card_action_{_suffix}"
                    _seed_all_added = all(
                        _member_is_added(mid)
                        for mid in _g["member_ids"]
                    )
                    if _seed_all_added:
                        st.session_state[_ka] = False
                    elif _ka not in st.session_state:
                        st.session_state[_ka] = (
                            (not _seed_all_added)
                            and _is_raw_block
                            and not _stock_errors
                        )
                    if _kx not in st.session_state:
                        st.session_state[_kx] = _default_action

                # ── Highlight selectbox (grouped) ────────────────────────────
                _hl_group_opts = ["(none)"]
                for _g in _groups:
                    _count_label = _g.get("count_label") or f"{_g['count']} found"
                    _hl_group_opts.append(f"{_g['description']} - {_count_label}")
                _hl_group_sel = st.selectbox(
                    "Preview / highlight group",
                    options=_hl_group_opts,
                    key="_smw_hl_group_sel",
                    help="Select a group to highlight it in gold in the 3D viewer.",
                )
                if _hl_group_sel == "(none)" or not _groups:
                    _hl_from_selectbox = set()
                else:
                    _hl_gi = _hl_group_opts.index(_hl_group_sel) - 1
                    _hl_from_selectbox = (
                        set(_preview_member_ids_for_group(_groups[_hl_gi], _filtered))
                        if 0 <= _hl_gi < len(_groups) else set()
                    )

                st.caption("Check groups to machine — ticked cards highlight gold in the 3D viewer.")

                _FTYPE_ICON = {
                    "Hole": "🔵", "Large Hole / Boring": "🟣",
                    "Pocket": "🟢", "Slot": "🟠", "Step": "🟡",
                    "Face Milling": "⬜", "Outer Profile": "🔷", "Chamfer": "🔸",
                }
                _ACTION_OPTS = ["Machine", "Existing Geometry – No Machining", "Reference Only"]

                with st.container(height=420):
                    for _gi, _g in enumerate(_groups):
                        _suffix = _group_widget_suffix(_g)
                        _all_added = all(
                            _member_is_added(mid)
                            for mid in _g["member_ids"]
                        )
                        _some_added = any(
                            _member_is_added(mid)
                            for mid in _g["member_ids"]
                        )
                        _icon = _FTYPE_ICON.get(_g["feature_type"], "◾")
                        if _all_added:
                            _badge = (
                                "<span style='background:#d1fae5;color:#065f46;"
                                "border-radius:3px;padding:1px 5px;font-size:10px;"
                                "font-weight:600;'>All added ✓</span>"
                            )
                        elif _some_added:
                            _nd = sum(
                                1 for _m in _g["member_ids"]
                                if _member_is_added(_m)
                            )
                            _badge = (
                                f"<span style='background:#fef3c7;color:#92400e;"
                                f"border-radius:3px;padding:1px 5px;font-size:10px;"
                                f"font-weight:600;'>Partial ✓ ({_nd}/{_g['count']})</span>"
                            )
                        else:
                            _badge = ""
                        _count_label = _g.get("count_label") or f"{_g['count']} found"
                        _member_ids = set(_g["member_ids"])
                        _setup_values = sorted({
                            str(_m.get("setup_label") or "Unknown")
                            for _m in _filtered
                            if _m.get("candidate_id") in _member_ids
                        })
                        _setup_summary = ", ".join(_setup_values) if _setup_values else "Unknown"
                        _cc1, _cc2, _cc3 = st.columns([0.45, 2.7, 1.85])
                        with _cc1:
                            st.checkbox(
                                "",
                                key=f"_smw_card_accept_{_suffix}",
                                disabled=_all_added,
                                label_visibility="collapsed",
                            )
                        with _cc2:
                            st.markdown(
                                f"**{_icon} {_g['display_type']}** &nbsp;·&nbsp; {_g['description']}"
                                f"<br><span style='font-size:11px;color:#555;'>"
                                f"{_count_label} &nbsp;·&nbsp; conf: {_g['confidence_summary']}"
                                + (f" &nbsp;{_badge}" if _badge else "")
                                + "</span>",
                                unsafe_allow_html=True,
                            )
                            st.caption(f"Setup: {_setup_summary}")
                        with _cc3:
                            st.selectbox(
                                "",
                                options=_ACTION_OPTS,
                                key=f"_smw_card_action_{_suffix}",
                                disabled=_all_added,
                                label_visibility="collapsed",
                            )
                        st.divider()

                # Collect checked state after all cards are rendered
                _hl_from_ticks = set()
                for _gi, _g in enumerate(_groups):
                    _suffix = _group_widget_suffix(_g)
                    if st.session_state.get(f"_smw_card_accept_{_suffix}", False):
                        _hl_from_ticks.update(_preview_member_ids_for_group(_g, _filtered))

                _new_hl_ids = (
                    _hl_from_ticks if _hl_from_ticks else _hl_from_selectbox
                )
                st.session_state._smw_highlight_candidate_ids = _new_hl_ids
                if _new_hl_ids != _prev_hl_ids:
                    st.rerun()

                _n_ticked = sum(
                    1 for _g in _groups
                    if st.session_state.get(f"_smw_card_accept_{_group_widget_suffix(_g)}", False)
                )

                with st.expander("Advanced: flat group table"):
                    _adv_rows = []
                    for _gi, _g in enumerate(_groups):
                        _aa = all(
                            _member_is_added(mid)
                            for mid in _g["member_ids"]
                        )
                        _sa = any(
                            _member_is_added(mid)
                            for mid in _g["member_ids"]
                        )
                        if _aa:
                            _ast = "All added ✓"
                        elif _sa:
                            _nad = sum(
                                1 for _m in _g["member_ids"]
                                if _member_is_added(_m)
                            )
                            _ast = f"Partial ✓ ({_nad}/{_g['count']})"
                        else:
                            _ast = ""
                        _suffix = _group_widget_suffix(_g)
                        _member_ids = set(_g["member_ids"])
                        _setup_values = sorted({
                            str(_m.get("setup_label") or "Unknown")
                            for _m in _filtered
                            if _m.get("candidate_id") in _member_ids
                        })
                        _adv_rows.append({
                            "accept":      st.session_state.get(f"_smw_card_accept_{_suffix}", False),
                            "status":      _ast,
                            "action":      st.session_state.get(f"_smw_card_action_{_suffix}", _default_action),
                            "type":        _g["display_type"],
                            "setup":       ", ".join(_setup_values) if _setup_values else "Unknown",
                            "description": _g["description"],
                            "count":       _g["count"],
                            "detected faces": _g.get("detected_count", _g["count"]),
                            "confidence":  _g["confidence_summary"],
                        })
                    st.dataframe(pd.DataFrame(_adv_rows), use_container_width=True, hide_index=True)

                if st.button(
                    "Confirm & proceed to Feature Review",
                    type="primary",
                    disabled=(_n_ticked == 0 or bool(_stock_errors)),
                    help="Tick at least one group to enable",
                    key="_smw_confirm_grouped",
                ):
                    _card_df = pd.DataFrame([
                        {
                            "_group_idx":       _gi,
                            "accept":           st.session_state.get(
                                f"_smw_card_accept_{_group_widget_suffix(_g)}", False
                            ),
                            "machining_action": st.session_state.get(
                                f"_smw_card_action_{_group_widget_suffix(_g)}", _default_action
                            ),
                        }
                        for _gi, _g in enumerate(_groups)
                    ])
                    _n_added = _commit_group_selections(_card_df, _groups, _filtered)
                    if _n_added > 0:
                        st.session_state.features_from_candidates = True
                        save_features_to_db(st.session_state.features)
                        st.success(f"Added {_n_added} feature(s). Navigating to Feature Review…")
                        st.session_state._nav_page = "4. Setup & Feature Review"
                        st.rerun()
                    else:
                        st.info("All ticked groups were already added. No new features added.")

            else:
                # ── FLAT / UNGROUPED MODE ───────────────────────────────────
                _rows = []
                for _c in _filtered:
                    _cid = _c["candidate_id"]
                    _is_added = _candidate_is_added(_c, _added_ids)
                    _rows.append({
                        "accept":           (not _is_added) and _is_raw_block and not _stock_errors,
                        "status":           "Added ✓" if _is_added else "",
                        "candidate_id":     _cid,
                        "machining_action": _default_action,
                        "feature_type":     _c.get("feature_type", ""),
                        "feature_name":     _c.get("feature_name", ""),
                        "confidence":       _c.get("confidence", ""),
                        "setup_label":      _candidate_work_setup(_c),
                        "x_pos":            _candidate_work_value(_c, "x"),
                        "y_pos":            _candidate_work_value(_c, "y"),
                        "diameter":         _c.get("diameter"),
                        "length":           _c.get("length"),
                        "width":            _c.get("width"),
                        "depth":            _c.get("depth"),
                        "detection_note":   _c.get("detection_note", ""),
                    })

                # ── Highlight selectbox (flat) ───────────────────────────────
                _hl_flat_opts = ["(none)"] + [
                    f"#{_ci + 1} {_c.get('feature_name', _c.get('feature_type', 'Unknown'))}"
                    for _ci, _c in enumerate(_filtered)
                ]
                _hl_flat_sel = st.selectbox(
                    "Preview / highlight feature",
                    options=_hl_flat_opts,
                    key="_smw_hl_flat_sel",
                    help="Select a feature to highlight it in gold in the 3D viewer.",
                )
                if _hl_flat_sel == "(none)" or not _filtered:
                    _hl_from_selectbox = set()
                else:
                    _hl_fi = _hl_flat_opts.index(_hl_flat_sel) - 1
                    _hl_from_selectbox = (
                        {_filtered[_hl_fi]["candidate_id"]} if 0 <= _hl_fi < len(_filtered) else set()
                    )

                st.caption("Ticked rows are highlighted in gold on the 3D model.")

                with st.container(height=460):
                    _edited = st.data_editor(
                        pd.DataFrame(_rows),
                        column_order=[
                            "accept", "status", "machining_action", "feature_type",
                            "feature_name", "confidence", "setup_label", "x_pos", "y_pos",
                            "diameter", "length", "width", "depth", "detection_note",
                        ],
                        column_config={
                            "accept":           st.column_config.CheckboxColumn("Machine this?", default=True),
                            "status":           st.column_config.TextColumn("Status",            disabled=True, width="small"),
                            "candidate_id":     st.column_config.TextColumn("ID",                disabled=True, width="small"),
                            "machining_action": st.column_config.SelectboxColumn(
                                "Action",
                                options=["Machine", "Existing Geometry – No Machining", "Reference Only"],
                                required=True,
                            ),
                            "feature_type":   st.column_config.TextColumn("Type",         disabled=True),
                            "feature_name":   st.column_config.TextColumn("Name",         disabled=True),
                            "confidence":     st.column_config.TextColumn("Conf.",        disabled=True, width="small"),
                            "setup_label":    st.column_config.TextColumn("Setup",        disabled=True, width="small"),
                            "x_pos":          st.column_config.NumberColumn("X (mm)",     disabled=True, format="%.2f"),
                            "y_pos":          st.column_config.NumberColumn("Y (mm)",     disabled=True, format="%.2f"),
                            "diameter":       st.column_config.NumberColumn("Dia (mm)",   disabled=True, format="%.2f"),
                            "length":         st.column_config.NumberColumn("L (mm)",     disabled=True, format="%.2f"),
                            "width":          st.column_config.NumberColumn("W (mm)",     disabled=True, format="%.2f"),
                            "depth":          st.column_config.NumberColumn("Depth (mm)", disabled=True, format="%.2f"),
                            "detection_note": st.column_config.TextColumn("Note",         disabled=True),
                        },
                        use_container_width=True,
                        hide_index=True,
                        key="_smw_cand_editor",
                    )

                # Auto-highlight from ticked rows; fall back to selectbox.
                _hl_from_ticks = set()
                if "candidate_id" in _edited.columns and "accept" in _edited.columns:
                    for _, _r in _edited.iterrows():
                        if _r.get("accept"):
                            _cid = _r.get("candidate_id", "")
                            if _cid:
                                _hl_from_ticks.add(_cid)
                _new_hl_ids = (
                    _hl_from_ticks if _hl_from_ticks else _hl_from_selectbox
                )
                st.session_state._smw_highlight_candidate_ids = _new_hl_ids
                if _new_hl_ids != _prev_hl_ids:
                    st.rerun()

                _n_ticked = int(_edited["accept"].sum()) if "accept" in _edited.columns else 0

                if st.button(
                    "Confirm & proceed to Feature Review",
                    type="primary",
                    disabled=(_n_ticked == 0),
                    help="Tick at least one feature to enable",
                    key="_smw_confirm_flat",
                ):
                    _n_added = _commit_candidate_selections(_edited, _filtered)
                    if _n_added > 0:
                        st.session_state.features_from_candidates = True
                        save_features_to_db(st.session_state.features)
                        st.success(f"Added {_n_added} feature(s). Navigating to Feature Review…")
                        st.session_state._nav_page = "4. Setup & Feature Review"
                        st.rerun()
                    else:
                        st.info("All ticked rows were already added. No new features added.")


def page_part_setup():
    # State reads first — needed for the header clear button
    _fname = st.session_state.get("uploaded_filename")
    _spt   = st.session_state.get("starting_part_type", "Raw Block / Billet")
    _stk   = st.session_state.get("stock") or {}
    _mesh  = st.session_state.get("step_mesh_data")

    # ── Page header: title + clear button aligned right ──────────────────
    _ph_title, _ph_clear = st.columns([5, 1])
    _ph_title.title("Part Setup")
    if _fname:
        if _ph_clear.button("Clear & Start New", type="secondary", key="ps_clear_job"):
            reset_current_job_state()
            st.rerun()
    st.caption("Upload a STEP file and configure material, machine, and stock to begin planning.")

    if st.session_state.pop("_job_reset_done", False):
        st.success("Job reset — all data cleared. Upload a new STEP file to begin.")

    _left, _right = st.columns([2.2, 1.8])

    # ── Left column: upload area or large 3D preview ──────────────────────
    with _left:
        if _mesh:
            _render_3d_panel("_ps_3d_", large=True)
        else:
            st.subheader("Upload STEP File")
            st.info(
                "Upload a STEP or STP file to extract bounding box geometry, "
                "part volume, and feature candidates."
            )
            _ps_uploaded = st.file_uploader(
                "Upload STEP / STP file",
                type=["step", "stp"],
                help="Supported: STEP AP203, AP214, AP242 (ASCII format)",
                key="ps_step_uploader",
            )
            if _ps_uploaded:
                _ps_bytes = _ps_uploaded.read()
                with st.spinner("Parsing STEP file..."):
                    _ps_result = _parse_and_tessellate(_ps_bytes, _ps_uploaded.name)
                if _ps_result["success"]:
                    if _ps_result.get("converted"):
                        _raw_lbl = _ps_result["detected_unit_label"].split("(")[0].strip()
                        st.warning(
                            f"Unit conversion applied: file coordinates are in **{_raw_lbl}** "
                            f"(detected via {_ps_result['detection_method']}) — "
                            f"multiplied by **{_ps_result['conversion_factor']}** to convert to mm."
                        )
                    else:
                        st.success(
                            f"Units confirmed as **mm** "
                            f"(detected via {_ps_result['detection_method']}) — no conversion needed."
                        )
                    for _pw in _ps_result.get("warnings", []):
                        st.warning(_pw)
                    if _ps_result.get("cadquery_warning"):
                        st.warning(f"**CadQuery fallback:** {_ps_result['cadquery_warning']}")
                    _n_cands = len(st.session_state.get("step_candidates", []))
                    st.success(f"Parsed — **{_n_cands} feature candidate(s)** detected.")
                    st.rerun()
                else:
                    st.warning(f"**STEP parse failed:** {_ps_result['message']}")
                    _pdet = _ps_result.get("detail")
                    _psug = _ps_result.get("suggestion")
                    if _pdet or _psug:
                        with st.expander("Why did this happen? / Suggested action", expanded=True):
                            if _pdet:
                                st.markdown(f"**Why:** {_pdet}")
                            if _psug:
                                st.markdown(f"**Action:** {_psug}")

    # ── Right column: part type cards + configure + next ─────────────────
    with _right:
        st.subheader("Starting Part Type")
        _PART_TYPES_PS = [
            ("Raw Block / Billet",         "🧱", "Fresh stock — detected features can be treated as machining work."),
            ("Weldment / Fabricated Part", "🔩", "Already welded/fabricated — select only final machining operations."),
            ("Casting / Forging",          "🪨", "Near-shape part — select only finishing/machining areas."),
            ("Existing Part / Rework",     "🔧", "Existing component — select only new or rework operations."),
        ]
        _ps_pt_cols = st.columns(2, gap="small")
        for _pti, (_pt_val, _pt_icon, _pt_desc) in enumerate(_PART_TYPES_PS):
            _is_sel = (_spt == _pt_val)
            with _ps_pt_cols[_pti % 2]:
                _border = "#1a73e8" if _is_sel else "#cccccc"
                _bg     = "#e8f0fe" if _is_sel else "#fafafa"
                _check  = "✅ " if _is_sel else ""
                st.markdown(
                    f'<div style="border:2.5px solid {_border};border-radius:10px;'
                    f'padding:10px 8px 6px;background:{_bg};text-align:center;margin-bottom:8px;">'
                    f'<div style="font-size:1.8rem;line-height:1.2;">{_pt_icon}</div>'
                    f'<div style="font-weight:700;font-size:0.8rem;margin-top:5px;">{_check}{_pt_val}</div>'
                    f'<div style="font-size:0.72rem;color:#555;margin-top:4px;line-height:1.3;">{_pt_desc}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if _is_sel:
                    st.button(
                        "✓ Selected",
                        key=f"ps_pt_card_{_pti}",
                        disabled=True,
                        use_container_width=True,
                        type="primary",
                    )
                else:
                    if st.button("Select", key=f"ps_pt_card_{_pti}", use_container_width=True):
                        st.session_state.starting_part_type = _pt_val
                        st.rerun()

        st.divider()

        # STEP file status
        st.markdown("**STEP File**")
        if _fname:
            st.success(f"📄 {_fname}")
        else:
            st.warning("No STEP file loaded")
        st.divider()

        # ── Material — editable expander ─────────────────────────────────
        _materials = st.session_state.materials
        _mat_names = [m["name"] for m in _materials]
        _cur_mat   = (st.session_state.get("selected_material") or {}).get("name", "")
        _ps_mat_default = next((i for i, n in enumerate(_mat_names) if n == _cur_mat), 0)

        with st.expander(f"🏭 Material — {_cur_mat or '—'}", expanded=False):
            _ps_mat_idx = st.selectbox(
                "Material profile",
                range(len(_mat_names)),
                format_func=lambda i: _mat_names[i],
                index=_ps_mat_default,
                key="ps_mat_sel",
            )
            _ps_mat = copy.deepcopy(_materials[_ps_mat_idx])
            _pmc1, _pmc2, _pmc3 = st.columns(3)
            with _pmc1:
                _ps_mat["density"] = st.number_input(
                    "Density (g/cm³)", value=float(_ps_mat["density"]), step=0.1,
                    key="ps_density",
                )
            with _pmc2:
                _ps_mat["machinability_factor"] = st.number_input(
                    "Machinability", value=float(_ps_mat["machinability_factor"]),
                    min_value=0.1, max_value=2.0, step=0.05,
                    key="ps_mach_factor",
                )
            with _pmc3:
                _ps_mat["safety_factor"] = st.number_input(
                    "Safety factor", value=float(_ps_mat["safety_factor"]),
                    min_value=1.0, max_value=3.0, step=0.05,
                    key="ps_safety_factor",
                )
            if st.button("Apply Material", key="ps_apply_material", use_container_width=True):
                st.session_state.materials[_ps_mat_idx] = _ps_mat
                st.session_state.selected_material = _ps_mat
                st.success(f"Material **{_ps_mat['name']}** applied.")
            else:
                st.session_state.selected_material = _ps_mat

        # ── Machine — editable expander ──────────────────────────────────
        _machines      = st.session_state.machines
        _machine_names = [m["machine_name"] for m in _machines]
        _cur_mach      = (st.session_state.get("selected_machine") or {}).get("machine_name", "")
        _ps_mach_default = next((i for i, n in enumerate(_machine_names) if n == _cur_mach), 0)

        with st.expander(f"🔩 Machine — {_cur_mach or '—'}", expanded=False):
            _ps_mach_idx = st.selectbox(
                "Machine profile",
                range(len(_machine_names)),
                format_func=lambda i: _machine_names[i],
                index=_ps_mach_default,
                key="ps_mach_sel",
            )
            _ps_mach = copy.deepcopy(_machines[_ps_mach_idx])
            _pmm1, _pmm2 = st.columns(2)
            with _pmm1:
                _ps_mach["machine_name"] = st.text_input(
                    "Machine name", value=_ps_mach["machine_name"], key="ps_mach_name",
                )
                _MACH_TYPES = ["VMC","CNC Milling","CNC Turning","HMC","Turn-Mill","Gang Turning","Swiss Type"]
                _ps_mach["machine_type"] = st.selectbox(
                    "Machine type", _MACH_TYPES,
                    index=_MACH_TYPES.index(_ps_mach["machine_type"]) if _ps_mach["machine_type"] in _MACH_TYPES else 0,
                    key="ps_mach_type",
                )
                _CTRLS = [
                    "Fanuc 0i-MF","Fanuc 0i-TF","Fanuc 31i","Fanuc 32i",
                    "Siemens 828D","Siemens 840D","Mazatrol",
                    "Mitsubishi M70","Mitsubishi M80","Haas","Generic",
                ]
                _ps_mach["controller"] = st.selectbox(
                    "Controller", _CTRLS,
                    index=_CTRLS.index(_ps_mach["controller"]) if _ps_mach["controller"] in _CTRLS else 10,
                    key="ps_controller",
                )
                _ps_mach["max_spindle_rpm"] = st.number_input(
                    "Max spindle RPM", value=int(_ps_mach["max_spindle_rpm"]),
                    min_value=100, step=100, key="ps_max_rpm",
                )
            with _pmm2:
                _ps_mach["max_feed_rate"] = st.number_input(
                    "Max feed (mm/min)", value=int(_ps_mach["max_feed_rate"]),
                    min_value=100, step=100, key="ps_max_feed",
                )
                _ps_mach["rapid_feed_rate"] = st.number_input(
                    "Rapid feed (mm/min)", value=int(_ps_mach["rapid_feed_rate"]),
                    min_value=100, step=100, key="ps_rapid_feed",
                )
                _ps_mach["tool_change_time_s"] = st.number_input(
                    "Tool change (s)", value=int(_ps_mach["tool_change_time_s"]),
                    min_value=1, step=1, key="ps_tool_change_time",
                )
                _ps_mach["setup_time_min"] = st.number_input(
                    "Setup time (min)", value=int(_ps_mach["setup_time_min"]),
                    min_value=1, step=1, key="ps_setup_time",
                )
            if st.button("Apply Machine Settings", key="ps_apply_machine", use_container_width=True):
                st.session_state.machines[_ps_mach_idx] = _ps_mach
                st.session_state.selected_machine = _ps_mach
                st.success(f"Machine **{_ps_mach['machine_name']}** applied.")
            else:
                st.session_state.selected_machine = _ps_mach
            st.caption(
                f"Capability: **{_ps_mach.get('axis_count', 3)}-axis** · "
                f"Indexed 3+2: **{'Yes' if _ps_mach.get('indexed_3plus2') else 'No'}** · "
                f"Simultaneous 5-axis: "
                f"**{'Yes' if _ps_mach.get('simultaneous_5_axis') else 'No'}**"
            )

        # ── Stock — editable expander ─────────────────────────────────────
        _l  = _stk.get("length", 150.0) or 150.0
        _w  = _stk.get("width",  100.0) or 100.0
        _h  = _stk.get("height",  50.0) or  50.0
        _sv = _stk.get("stock_volume", 0) or 0
        _pv = _stk.get("part_volume",  0) or 0
        _stk_label = f"📐 Stock — {_l} × {_w} × {_h} mm" if _sv else "📐 Stock — not set"
        with st.expander(_stk_label, expanded=False):
            _ps_sl, _ps_sw, _ps_sh = st.columns(3)
            _new_l = _ps_sl.number_input(
                "Length (mm)", value=float(_l), min_value=0.001, step=0.5, key="ps_stock_length",
            )
            _new_w = _ps_sw.number_input(
                "Width (mm)",  value=float(_w), min_value=0.001, step=0.5, key="ps_stock_width",
            )
            _new_h = _ps_sh.number_input(
                "Height (mm)", value=float(_h), min_value=0.001, step=0.5, key="ps_stock_height",
            )
            _new_ox = float(_stk.get("part_offset_x", 0.0) or 0.0)
            _new_oy = float(_stk.get("part_offset_y", 0.0) or 0.0)
            _new_oz = float(_stk.get("part_offset_z", 0.0) or 0.0)
            if st.session_state.get("starting_part_type") == "Raw Block / Billet":
                _psox, _psoy, _psoz = st.columns(3)
                _new_ox = _psox.number_input(
                    "Part offset X (mm)",
                    value=_new_ox,
                    step=0.5,
                    key="ps_part_offset_x",
                )
                _new_oy = _psoy.number_input(
                    "Part offset Y (mm)",
                    value=_new_oy,
                    step=0.5,
                    key="ps_part_offset_y",
                )
                _new_oz = _psoz.number_input(
                    "Part offset Z (mm)",
                    value=_new_oz,
                    step=0.5,
                    key="ps_part_offset_z",
                )
            _new_sv = (_new_l * _new_w * _new_h) / 1000.0
            if st.button("Apply Stock", key="ps_apply_stock", use_container_width=True):
                st.session_state.stock["length"]       = _new_l
                st.session_state.stock["width"]        = _new_w
                st.session_state.stock["height"]       = _new_h
                st.session_state.stock["stock_volume"] = round(_new_sv, 3)
                st.session_state.stock["part_offset_x"] = _new_ox
                st.session_state.stock["part_offset_y"] = _new_oy
                st.session_state.stock["part_offset_z"] = _new_oz
                st.success(f"Stock updated: {_new_l} × {_new_w} × {_new_h} mm")
                st.rerun()
            st.divider()
            _sm1, _sm2, _sm3 = st.columns(3)
            _sm1.metric("Stock vol (cm³)", f"{_new_sv:.2f}")
            if _pv:
                _removed     = max(_new_sv - _pv, 0)
                _removed_pct = (_removed / _new_sv * 100) if _new_sv > 0 else 0
                _sm2.metric("Part vol (cm³)", f"{_pv:.2f}")
                _sm3.metric("Removed", f"{_removed:.2f} cm³", delta=f"{_removed_pct:.1f}%")
            else:
                _sm2.metric("Part vol (cm³)", "—")
                _sm3.metric("Removed", "—")
                st.caption("Upload a STEP file to calculate part volume and removed material.")

        # ── Next → Select Machining Work ──────────────────────────────────
        st.divider()
        if _fname:
            if st.button(
                "🧩 Next → Select Machining Work",
                type="primary",
                use_container_width=True,
                key="ps_next_smw",
            ):
                st.session_state._nav_page = "Select Machining Work"
                st.rerun()
        else:
            st.button(
                "🧩 Next → Select Machining Work",
                type="primary",
                use_container_width=True,
                key="ps_next_smw",
                disabled=True,
                help="Upload a STEP file first",
            )


def main():
    init_session()
    page = sidebar_nav()
    show_top_header()
    page = top_tabs(page)

    if   page == "1. Upload / Overview":          page_upload_step()
    elif page == "Part Setup":                    page_part_setup()
    elif page == "Select Machining Work":         page_select_machining_work()
    elif page == "2. Material & Machine":         page_machine_setup()
    elif page == "3. Stock & Setup":              page_material_setup()
    elif page == "4. Setup & Feature Review":     page_setup_review()
    elif page == "5. Tools":                      page_tool_library()
    elif page == "6. Strategy / Operations":      page_operation_plan()
    elif page == "7. Estimate / Pricing":         page_time_estimate()
    elif page == "8. Export / Setup Sheet":       page_cnc_export()
    elif page == "9. History":                    page_job_notes()
    elif page == "10. Tool Library":              page_tool_library()
    elif page == "11. Data Tables":               page_feature_input()


if __name__ == "__main__":
    main()
