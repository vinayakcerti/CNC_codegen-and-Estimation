import streamlit as st
import pandas as pd
import json
import io
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from modules.data_store import (
    get_default_materials, get_default_tools, get_default_machines,
    save_tools_to_db, load_tools_from_db,
    save_features_to_db, load_features_from_db,
    add_job_note, load_job_notes, delete_job_note, clear_all_job_notes,
)
from modules.operation_planner import plan_operations
from modules.time_estimator import estimate_time
from modules.gcode_generator import generate_gcode
from modules.visual_preview import build_top_view, build_3d_view
from modules.step_parser import parse_step_bounding_box, parse_step_geometry
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


def show_top_header():
    col_title, col_logo = st.columns([8, 1.2])
    with col_title:
        st.markdown(
            f"<span style='font-size:1.15rem;font-weight:600;color:#555;'>{APP_TAGLINE}</span>",
            unsafe_allow_html=True,
        )
    with col_logo:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=120)
    st.divider()

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
    "Outer Profile",
    "Chamfer",
]


def init_session():
    if "tools" not in st.session_state:
        db_tools = load_tools_from_db()
        st.session_state.tools = db_tools if db_tools else get_default_tools()
    if "features" not in st.session_state:
        db_features = load_features_from_db()
        st.session_state.features = db_features if db_features else copy.deepcopy(DEMO_FEATURES)
    if "materials" not in st.session_state:
        st.session_state.materials = get_default_materials()
    if "machines" not in st.session_state:
        st.session_state.machines = get_default_machines()
    if "selected_material" not in st.session_state:
        st.session_state.selected_material = st.session_state.materials[0]
    if "selected_machine" not in st.session_state:
        st.session_state.selected_machine = st.session_state.machines[0]
    if "stock" not in st.session_state:
        st.session_state.stock = {
            "length": 150.0, "width": 100.0, "height": 50.0,
            "part_volume": 600.0, "stock_volume": 750.0,
        }
    if "uploaded_filename" not in st.session_state:
        st.session_state.uploaded_filename = None
    if "step_uploader_key" not in st.session_state:
        st.session_state.step_uploader_key = 0


def sidebar_nav():
    with st.sidebar:
        if os.path.exists(LOGO_PATH):
            st.image(LOGO_PATH, width=160)
        st.markdown(
            f"<div style='font-size:1.05rem;font-weight:700;margin-top:0.2rem;'>⚙️ {APP_NAME}</div>",
            unsafe_allow_html=True,
        )
        st.caption("Professional CNC Planning")
        st.divider()
        pages = [
            "1. Upload STEP File",
            "2. Machine Setup",
            "3. Tool Library",
            "4. Material Setup",
            "5. Feature Input",
            "5a. Setup & Feature Review",
            "6. Operation Plan",
            "7. Time & Effort Estimate",
            "8. Approximate Process Preview",
            "9. CNC Program Export",
            "10. Job Notes & History",
        ]
        selected = st.radio("Navigation", pages, label_visibility="collapsed")
        st.divider()
        st.warning("**SAFETY NOTICE**\nAll generated CNC code is DRAFT only. Always verify in CAM/simulator before running on a machine.")
        return selected


def page_upload_step():
    st.header("1. Upload STEP File")

    # ── Clear / Start New ────────────────────────────────────────────
    if st.session_state.get("uploaded_filename"):
        cl1, cl2 = st.columns([3, 1])
        cl1.info(f"Loaded file: **{st.session_state.uploaded_filename}**")
        if cl2.button("Clear & Start New", type="secondary"):
            for key in ("uploaded_filename", "step_parse_result", "step_geometry"):
                st.session_state.pop(key, None)
            st.session_state.stock = {
                "length": 150.0, "width": 100.0, "height": 50.0,
                "part_volume": 600.0, "stock_volume": 750.0,
            }
            st.session_state.step_uploader_key += 1
            st.rerun()

    uploaded = st.file_uploader(
        "Upload STEP / STP file",
        type=["step", "stp"],
        help="Supported: STEP AP203, AP214, AP242 (ASCII format)",
        key=f"step_uploader_{st.session_state.step_uploader_key}",
    )

    parse_result = None

    if uploaded:
        st.session_state.uploaded_filename = uploaded.name
        file_bytes = uploaded.read()

        col_info1, col_info2 = st.columns(2)
        col_info1.success(f"File: **{uploaded.name}**")
        col_info2.info(f"Size: **{len(file_bytes) / 1024:.1f} KB**")

        with st.spinner("Parsing STEP file geometry..."):
            parse_result = parse_step_bounding_box(file_bytes)
            geo_result   = parse_step_geometry(file_bytes)

        if parse_result["success"]:
            st.session_state.step_parse_result = parse_result
            st.session_state.step_geometry = geo_result
            st.session_state.stock["length"] = parse_result["length_mm"]
            st.session_state.stock["width"] = parse_result["width_mm"]
            st.session_state.stock["height"] = parse_result["height_mm"]
            st.session_state.stock["stock_volume"] = parse_result["stock_volume_cm3"]
            st.session_state.stock["part_volume"] = parse_result["part_volume_cm3"]

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

    removed = max(stock["stock_volume"] - stock["part_volume"], 0)
    removal_pct = (removed / stock["stock_volume"] * 100) if stock["stock_volume"] > 0 else 0

    st.subheader("Volume Analysis")
    c1, c2, c3 = st.columns(3)
    c1.metric("Stock Volume", f"{stock['stock_volume']:.2f} cm³")
    c2.metric("Part Volume", f"{stock['part_volume']:.2f} cm³")
    c3.metric("Removed Volume", f"{removed:.2f} cm³", delta=f"{removal_pct:.1f}% removal")

    if parse_result and parse_result.get("success"):
        st.subheader("Parsed Coordinate Ranges")
        r = parse_result

        # Build table — include raw column only when conversion happened
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

        # Summary strip
        u_col1, u_col2, u_col3 = st.columns(3)
        u_col1.metric("Points Parsed", f"{r['point_count']:,}")
        u_col2.metric("Detected Units", r["detected_unit_label"].split("(")[0].strip())
        u_col3.metric(
            "Conversion Factor",
            f"× {r['conversion_factor']}" if r["converted"] else "None (already mm)",
        )

        st.caption(
            f"Detection method: {r['detection_method']}. "
            "Part volume is estimated as 60 % of bounding-box volume — "
            "adjust if your part has significantly different geometry."
        )

    st.session_state.stock = stock


def page_machine_setup():
    st.header("2. Machine Setup")
    machines = st.session_state.machines

    machine_names = [m["machine_name"] for m in machines]
    sel_idx = st.selectbox("Select Machine Profile", range(len(machine_names)),
                           format_func=lambda i: machine_names[i])
    m = copy.deepcopy(machines[sel_idx])

    st.subheader("Machine Parameters")
    col1, col2 = st.columns(2)
    with col1:
        m["machine_name"] = st.text_input("Machine Name", value=m["machine_name"])
        _MACHINE_TYPES = ["VMC", "CNC Milling", "CNC Turning", "HMC", "Turn-Mill", "Gang Turning", "Swiss Type"]
        m["machine_type"] = st.selectbox(
            "Machine Type",
            _MACHINE_TYPES,
            index=_MACHINE_TYPES.index(m["machine_type"]) if m["machine_type"] in _MACHINE_TYPES else 0
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
            index=_CONTROLLERS.index(m["controller"]) if m["controller"] in _CONTROLLERS else 10
        )
        m["max_spindle_rpm"] = st.number_input("Max Spindle RPM", value=int(m["max_spindle_rpm"]), min_value=100, step=100)

    with col2:
        m["max_feed_rate"] = st.number_input("Max Feed Rate (mm/min)", value=int(m["max_feed_rate"]), min_value=100, step=100)
        m["rapid_feed_rate"] = st.number_input("Rapid Feed Rate (mm/min)", value=int(m["rapid_feed_rate"]), min_value=100, step=100)
        m["tool_change_time_s"] = st.number_input("Tool Change Time (s)", value=int(m["tool_change_time_s"]), min_value=1, step=1)
        m["setup_time_min"] = st.number_input("Setup Time (min)", value=int(m["setup_time_min"]), min_value=1, step=1)

    if st.button("Apply Machine Settings"):
        st.session_state.machines[sel_idx] = m
        st.session_state.selected_machine = m
        st.success(f"Machine profile **{m['machine_name']}** applied.")
    else:
        st.session_state.selected_machine = m

    st.info(f"Active machine: **{st.session_state.selected_machine['machine_name']}** — {st.session_state.selected_machine['machine_type']} / {st.session_state.selected_machine['controller']}")


def page_tool_library():
    st.header("3. Tool Library")

    tab_lib, tab_sf = st.tabs(["Tool Library", "Speeds & Feeds Calculator"])

    # ── Tab 1: Tool Library ────────────────────────────────────────────
    with tab_lib:
        st.info("Edit your tool library. Changes are saved to the local database.")
        tools = st.session_state.tools

        df = pd.DataFrame(tools)
        cols_order = ["tool_number", "tool_name", "tool_type", "diameter_mm",
                      "default_spindle_rpm", "default_feed_rate_mm_min", "max_depth_mm"]
        df = df[cols_order]

        edited_df = st.data_editor(
            df,
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "tool_number": st.column_config.NumberColumn("T#", min_value=1, max_value=99),
                "tool_name": st.column_config.TextColumn("Tool Name"),
                "tool_type": st.column_config.SelectboxColumn("Type", options=[
                    "Spot Drill", "Drill", "End Mill", "Face Mill", "Boring", "Chamfer"]),
                "diameter_mm": st.column_config.NumberColumn("Dia (mm)", format="%.1f"),
                "default_spindle_rpm": st.column_config.NumberColumn("RPM"),
                "default_feed_rate_mm_min": st.column_config.NumberColumn("Feed (mm/min)"),
                "max_depth_mm": st.column_config.NumberColumn("Max Depth (mm)", format="%.1f"),
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

    # ── Tab 2: Speeds & Feeds Calculator ──────────────────────────────
    with tab_sf:
        st.subheader("Speeds & Feeds Calculator")
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


def page_material_setup():
    st.header("4. Material Setup")

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


def page_feature_input():
    st.header("5. Feature Input")

    tab_feat, tab_tol, tab_sf_guide = st.tabs([
        "Feature List",
        "Tolerance & IT Grade Guide",
        "Surface Finish Guide",
    ])

    # ── Tab 1: Feature List ───────────────────────────────────────────
    with tab_feat:
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
    st.header("5a. Setup & Feature Review")
    st.caption(
        "Review stock, setup assumptions, and detected/manual features "
        "before generating the operation plan."
    )
    st.divider()

    stock    = st.session_state.get("stock", {})
    machine  = st.session_state.get("selected_machine")
    material = st.session_state.get("selected_material")
    features = st.session_state.get("features", [])
    step_ok  = bool(st.session_state.get("step_parse_result"))

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

    # ── C. Feature summary ───────────────────────────────────────────────────
    st.subheader("Feature Summary")
    if not features:
        st.info("No features entered yet — go to page 5 to add features.")
    else:
        display_cols = [
            "feature_name", "feature_type", "quantity",
            "x_pos", "y_pos", "diameter", "length", "width", "depth",
            "tolerance_note", "priority",
        ]
        df = pd.DataFrame(features)
        for col in display_cols:
            if col not in df.columns:
                df[col] = None
        st.dataframe(
            df[display_cols].rename(columns={
                "feature_name":   "Name",
                "feature_type":   "Type",
                "quantity":       "Qty",
                "x_pos":          "X (mm)",
                "y_pos":          "Y (mm)",
                "diameter":       "Dia (mm)",
                "length":         "L (mm)",
                "width":          "W (mm)",
                "depth":          "Depth (mm)",
                "tolerance_note": "Tolerance",
                "priority":       "Priority",
            }),
            use_container_width=True,
            hide_index=True,
        )

    st.divider()

    # ── D. Validation flags ──────────────────────────────────────────────────
    st.subheader("Validation Flags")
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
            if depth == 0:
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

    # ── E. Pre-flight checklist ──────────────────────────────────────────────
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
                    or (feat.get("depth") or 0) == 0):
                any_critical = True
                break

    checks = [
        (has_stock or step_ok, "Stock dimensions entered or STEP file uploaded"),
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
        st.success("All checks passed — you may proceed to page 6: Operation Plan.")
    else:
        st.warning("Resolve the items above before generating the operation plan.")


def page_operation_plan():
    st.header("6. Operation Plan")

    if not st.session_state.features:
        st.warning("No features defined. Please go to Feature Input first.")
        return

    if not st.session_state.tools:
        st.warning("No tools in library. Please go to Tool Library first.")
        return

    operations = plan_operations(
        st.session_state.features,
        st.session_state.tools,
        st.session_state.selected_material,
    )
    st.session_state.operations = operations

    mat = st.session_state.selected_material
    mach = st.session_state.selected_machine
    st.info(f"Material: **{mat['name']}** | Machine: **{mach['machine_name']}** | Operations generated: **{len(operations)}**")

    display_cols = [c for c in pd.DataFrame(operations).columns if not c.startswith("_")]
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


def page_time_estimate():
    st.header("7. Time & Effort Estimate")

    if "operations" not in st.session_state or not st.session_state.operations:
        st.warning("No operations planned. Please run Operation Plan first.")
        return

    result = estimate_time(
        st.session_state.operations,
        st.session_state.selected_machine,
        st.session_state.selected_material,
        st.session_state.features,
    )
    st.session_state.time_result = result

    st.subheader("Time Breakdown")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Setup Time", f"{result['setup_time_min']:.1f} min")
    c2.metric("Cutting Time", f"{result['cutting_time_min']:.1f} min")
    c3.metric("Rapid Movement", f"{result['rapid_time_min']:.2f} min")
    c4.metric("Tool Change Time", f"{result['tool_change_time_min']:.2f} min")

    st.subheader("Total Estimates")
    d1, d2, d3 = st.columns(3)
    d1.metric("Total Machine Time", f"{result['total_machine_time_min']:.1f} min",
              delta=f"{result['total_machine_time_min']/60:.2f} hrs")
    d2.metric("Operator Effort Time", f"{result['operator_effort_min']:.1f} min")

    effort_color = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(result["effort_label"], "⚪")
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
    st.subheader("Job Cost Estimator")
    st.caption("Adjust rates below to produce a draft cost estimate for this job.")

    stock = st.session_state.stock
    mat = st.session_state.selected_material

    cost_col1, cost_col2, cost_col3 = st.columns(3)
    with cost_col1:
        machine_rate = st.number_input(
            "Machine Hourly Rate ($/hr)",
            value=75.0, min_value=0.0, step=5.0,
            help="Cost to run the machine per hour, including operator"
        )
        overhead_rate = st.number_input(
            "Overhead / Setup Rate ($/hr)",
            value=25.0, min_value=0.0, step=5.0,
            help="Workshop overhead allocated per hour of work"
        )
    with cost_col2:
        material_price_kg = st.number_input(
            "Material Price ($/kg)",
            value=5.0, min_value=0.0, step=0.5,
            help="Cost of raw stock material per kilogram"
        )
        material_waste_pct = st.number_input(
            "Material Waste / Offcut (%)",
            value=15.0, min_value=0.0, max_value=80.0, step=1.0,
            help="Extra material allowance for offcuts and setup scrap"
        )
    with cost_col3:
        profit_margin_pct = st.number_input(
            "Profit Margin (%)",
            value=20.0, min_value=0.0, max_value=100.0, step=1.0,
            help="Margin added on top of total cost"
        )
        quantity_parts = st.number_input(
            "Number of Parts (batch)",
            value=1, min_value=1, step=1,
            help="Quote for a batch — setup cost is shared across the batch"
        )

    # ── Calculations ──────────────────────────────────────────────────
    density = mat.get("density", 2.7)
    stock_volume_cm3 = stock.get("stock_volume", 0)
    part_volume_cm3 = stock.get("part_volume", 0)

    # Material cost per part (stock volume × density × price, + waste)
    stock_weight_kg = (stock_volume_cm3 / 1000) * density
    material_cost_per_part = stock_weight_kg * material_price_kg * (1 + material_waste_pct / 100)

    # Machine time cost (setup shared across batch, cutting per part)
    total_time_min = result["total_machine_time_min"]
    setup_time_min = result["setup_time_min"]
    cutting_time_min = total_time_min - setup_time_min

    setup_cost_per_batch = (setup_time_min / 60) * (machine_rate + overhead_rate)
    cutting_cost_per_part = (cutting_time_min / 60) * machine_rate
    overhead_cost_per_part = (cutting_time_min / 60) * overhead_rate

    cost_per_part_before_margin = (
        material_cost_per_part
        + (setup_cost_per_batch / quantity_parts)
        + cutting_cost_per_part
        + overhead_cost_per_part
    )
    margin_per_part = cost_per_part_before_margin * (profit_margin_pct / 100)
    sell_price_per_part = cost_per_part_before_margin + margin_per_part
    batch_total = sell_price_per_part * quantity_parts

    # ── Display ───────────────────────────────────────────────────────
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Material Cost / Part", f"${material_cost_per_part:.2f}",
              delta=f"{stock_weight_kg:.3f} kg stock")
    m2.metric("Setup Cost (batch)", f"${setup_cost_per_batch:.2f}",
              delta=f"${setup_cost_per_batch/quantity_parts:.2f}/part")
    m3.metric("Machining Cost / Part", f"${cutting_cost_per_part + overhead_cost_per_part:.2f}")
    m4.metric("Sell Price / Part", f"${sell_price_per_part:.2f}",
              delta=f"Margin: ${margin_per_part:.2f}")

    st.metric(
        f"Batch Total ({quantity_parts} part{'s' if quantity_parts > 1 else ''})",
        f"${batch_total:.2f}",
    )

    cost_breakdown = pd.DataFrame({
        "Cost Item": [
            "Material (incl. waste)",
            "Setup (÷ batch size)",
            "Machining",
            "Overhead",
            "Subtotal (cost)",
            f"Profit Margin ({profit_margin_pct:.0f}%)",
            "Sell Price per Part",
        ],
        "Per Part ($)": [
            round(material_cost_per_part, 2),
            round(setup_cost_per_batch / quantity_parts, 2),
            round(cutting_cost_per_part, 2),
            round(overhead_cost_per_part, 2),
            round(cost_per_part_before_margin, 2),
            round(margin_per_part, 2),
            round(sell_price_per_part, 2),
        ],
    })
    st.dataframe(cost_breakdown, use_container_width=True, hide_index=True)

    cost_csv = cost_breakdown.to_csv(index=False).encode()
    st.download_button(
        "Download Cost Estimate (CSV)",
        data=cost_csv,
        file_name="job_cost_estimate.csv",
        mime="text/csv",
    )


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
    st.header("9. CNC Program Export")

    st.error("IMPORTANT: Generated CNC code is DRAFT only. ALWAYS verify in CAM/simulator before running on a real machine.")

    if "operations" not in st.session_state or not st.session_state.operations:
        st.warning("No operations available. Please run Operation Plan first.")
        return

    gcode = generate_gcode(
        st.session_state.operations,
        st.session_state.selected_machine,
        st.session_state.stock,
    )

    st.subheader("Generated Draft CNC Program")
    st.code(gcode, language="text")

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

    stat_col1, stat_col2 = st.columns(2)
    with stat_col1:
        st.subheader("Program Statistics")
        lines = gcode.split("\n")
        st.write(f"- Total lines: **{len(lines)}**")
        st.write(f"- Tool changes: **{gcode.count('M6')}**")
        st.write(f"- Canned cycles (G81/G76): **{gcode.count('G81') + gcode.count('G76')}**")
        st.write(f"- Coolant ON (M8): **{gcode.count('M8')}**")

    with stat_col2:
        st.subheader("Active Configuration")
        mach = st.session_state.selected_machine
        mat = st.session_state.selected_material
        st.write(f"- Machine: **{mach['machine_name']}**")
        st.write(f"- Controller: **{mach['controller']}**")
        st.write(f"- Material: **{mat['name']}**")
        st.write(f"- Operations: **{len(st.session_state.operations)}**")

    # ── Setup Sheet ────────────────────────────────────────────────────
    st.divider()
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


def page_job_notes():
    st.header("10. Job Notes & Revision History")
    st.caption("Log notes, changes, and sign-offs against this job. All entries are saved to the local database.")

    notes = load_job_notes()

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
    st.subheader("Revision History")
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


def main():
    init_session()
    page = sidebar_nav()
    show_top_header()

    if page == "1. Upload STEP File":
        page_upload_step()
    elif page == "2. Machine Setup":
        page_machine_setup()
    elif page == "3. Tool Library":
        page_tool_library()
    elif page == "4. Material Setup":
        page_material_setup()
    elif page == "5. Feature Input":
        page_feature_input()
    elif page == "5a. Setup & Feature Review":
        page_setup_review()
    elif page == "6. Operation Plan":
        page_operation_plan()
    elif page == "7. Time & Effort Estimate":
        page_time_estimate()
    elif page == "8. Approximate Process Preview":
        page_visual_preview()
    elif page == "9. CNC Program Export":
        page_cnc_export()
    elif page == "10. Job Notes & History":
        page_job_notes()


if __name__ == "__main__":
    main()
