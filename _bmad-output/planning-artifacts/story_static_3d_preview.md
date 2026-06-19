# Story: Static Interactive 3D Preview on Upload Page

**Date:** 2026-05-14
**Branch:** v2-feature-review-engine
**Status:** Ready to implement — analysis complete, no code changed yet

---

## Goal

Replace the "3D Preview will appear here" placeholder on the **Upload & Overview** page with a real rotatable / zoomable / pannable Plotly Mesh3d solid viewer of the uploaded STEP model.

No animation. No toolpath simulation. No change to feature detection, operation planning, or pricing.

---

## Current State Analysis

### Where parsed STEP data lives

| Session key | Set by | Content |
|---|---|---|
| `step_parse_result` | `parse_step_auto()` on upload | Bounding box, volumes, coordinate ranges, topology counts |
| `step_geometry` | `parse_step_geometry()` on upload | Wireframe: `line_segments` + `circle_traces` (already rendered in visual_preview) |
| *(new)* `step_mesh_data` | to be added | Tessellated solid: vertex lists + triangle indices for Plotly Mesh3d |

### Existing 3D viewer

`modules/visual_preview.py` already has `build_3d_view(stock, features, step_geometry=None)` — renders a Plotly Scatter3d wireframe using `step_geometry` (edges + circles). This is rotatable/zoomable. It is used on the separate **Visual Preview** page but **not** on the Upload page.

### Upload page placeholder (lines ~366–372 of app.py)

```python
with ov_right:
    st.subheader("3D Preview")
    st.info(
        "Interactive 3D preview will appear here in the next phase. ..."
    )
```

This is the exact slot where the viewer should go.

### File bytes availability

`file_bytes` is local to the `if uploaded:` block in `page_upload_step()`. It is **not** persisted in session state after the upload widget clears. Tessellation must happen during the upload block and the result cached — the same pattern CadQuery already uses (`parse_step_auto` is called there and the result cached).

---

## Feasibility Assessment

### Plotly Mesh3d

`plotly>=5.18.0` (actual: 6.7.0) is installed. `go.Mesh3d` accepts `x`, `y`, `z` vertex arrays and `i`, `j`, `k` triangle index arrays — exactly the format CadQuery's `shape.tessellate()` returns.

### CadQuery tessellate API (confirmed)

```python
verts, tris = shape.tessellate(tolerance=0.5, angularTolerance=0.1)
# Returns:
#   verts: List[cadquery.occ_impl.geom.Vector]  — .x .y .z in mm
#   tris:  List[Tuple[int, int, int]]           — triangle vertex indices
```

### Performance benchmark on real STEP samples

| File | Vertices | Triangles | Tessellation time |
|---|---|---|---|
| `02_plate_4_through_holes_d10.step` | 2,048 | 2,044 | 0.10 s |
| `23_mixed_plate_holes_slot_pocket.step` | 4,417 | 5,869 | 0.11 s |
| `25_vmc_job_plate_all_basic_features.step` | 5,543 | 7,025 | 0.15 s |
| `M07_vmc_chamfered_plate.step` | 2,064 | 2,052 | 0.05 s |

All under 200 ms at 0.5 mm tolerance. Well within Plotly's capabilities (handles 100k+ triangles in browser). These are typical workshop VMC parts — the performance envelope is acceptable.

---

## Recommended Implementation

### Two-layer approach (graceful degradation)

```
CadQuery available + parse succeeded
    → Mesh3d solid viewer (preferred)
CadQuery NOT available OR parse failed
    → Wireframe viewer using existing build_3d_view() + step_geometry
No STEP uploaded at all
    → Fallback message: "Upload a STEP file to see the 3D preview"
```

### Implementation steps

#### Step 1 — Session state: add `step_mesh_data` key

In `init_session()` in `app.py`:
```python
if "step_mesh_data" not in st.session_state:
    st.session_state.step_mesh_data = None
```

#### Step 2 — Tessellate at upload time (app.py, inside `if uploaded:` block)

After `parse_step_auto` succeeds and CadQuery is the parser:
```python
# Tessellate for Mesh3d viewer (only when CadQuery parsed the shape)
if parse_result.get("parser_used") == "cadquery" and tmp_step_path:
    try:
        import cadquery as cq
        _cq_result = cq.importers.importStep(tmp_step_path)
        _verts, _tris = _cq_result.val().tessellate(0.5)
        st.session_state.step_mesh_data = {
            "x": [v.x for v in _verts],
            "y": [v.y for v in _verts],
            "z": [v.z for v in _verts],
            "i": [t[0] for t in _tris],
            "j": [t[1] for t in _tris],
            "k": [t[2] for t in _tris],
        }
    except Exception:
        st.session_state.step_mesh_data = None
```

Note: `parse_step_auto` already writes to a tempfile to load CadQuery. The temp file is deleted in the `finally` block. The tessellation must happen before the temp file is cleaned up — so it should be computed inside `parse_step_with_cadquery()` and returned as a key, OR the tessellation call should happen in `app.py` immediately after parse while file_bytes are still available (write own tempfile). The cleanest option is to add `mesh_data` as an optional output of `parse_step_with_cadquery()` in `modules/step_parser.py`.

**Alternative (no changes to modules/):** Pass `file_bytes` through a second tempfile write in `app.py` after parse succeeds. This is slightly less clean but keeps `modules/step_parser.py` untouched.

#### Step 3 — Add `build_step_mesh3d()` to `modules/visual_preview.py`

```python
def build_step_mesh3d(mesh_data, stock):
    """
    Build a Plotly Mesh3d figure from pre-computed tessellation data.

    Args:
        mesh_data: dict with x/y/z vertex lists and i/j/k triangle index lists
        stock: dict with length/width/height keys

    Returns: plotly.graph_objects.Figure (rotatable, zoomable, pannable)
    """
    import plotly.graph_objects as go

    sx = stock.get("length", 100)
    sy = stock.get("width", 100)
    sz = stock.get("height", 50)

    fig = go.Figure()

    # Solid mesh — the STEP shape
    fig.add_trace(go.Mesh3d(
        x=mesh_data["x"],
        y=mesh_data["y"],
        z=mesh_data["z"],
        i=mesh_data["i"],
        j=mesh_data["j"],
        k=mesh_data["k"],
        color="lightsteelblue",
        opacity=0.85,
        flatshading=False,
        lighting=dict(ambient=0.5, diffuse=0.8, specular=0.2,
                      roughness=0.5, fresnel=0.2),
        lightposition=dict(x=1, y=1, z=2),
        name="Part shape",
        showlegend=True,
    ))

    # Bounding box wireframe overlay for spatial reference
    for tr in _stock_box_traces(sx, sy, sz):
        fig.add_trace(tr)

    fig.update_layout(
        title="3D Preview — Part Shape (planning reference only)",
        scene=dict(
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Z (mm)",
            aspectmode="data",
            xaxis=dict(backgroundcolor="rgba(240,248,255,0.5)"),
            yaxis=dict(backgroundcolor="rgba(240,248,255,0.5)"),
            zaxis=dict(backgroundcolor="rgba(220,230,240,0.5)"),
        ),
        height=480,
        margin=dict(l=0, r=0, t=50, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=0),
    )
    return fig
```

#### Step 4 — Wire preview into Upload page (app.py, `ov_right` column)

Replace the placeholder:
```python
with ov_right:
    st.subheader("3D Preview")
    _mesh = st.session_state.get("step_mesh_data")
    _geo  = st.session_state.get("step_geometry")
    _stk  = st.session_state.get("stock", {})

    if _mesh:
        fig_mesh = build_step_mesh3d(_mesh, _stk)
        st.plotly_chart(fig_mesh, use_container_width=True)
        st.caption("Rotatable solid preview — CadQuery/OCC tessellation. "
                   "Planning reference only; not a machining simulation.")
    elif _geo and _geo.get("success"):
        fig_wire = build_3d_view(_stk, [], step_geometry=_geo)
        st.plotly_chart(fig_wire, use_container_width=True)
        st.caption("Wireframe preview — STEP edge geometry. "
                   "Planning reference only.")
    elif st.session_state.get("step_parse_result"):
        st.info("3D geometry not available for this file. "
                "Preview requires a CadQuery-parsed STEP file.")
    else:
        st.info("Upload a STEP file to see the interactive 3D preview here.")
```

#### Step 5 — Clear `step_mesh_data` on reset

Add `st.session_state.step_mesh_data = None` to every reset/clear flow:
- "Clear & Start New" button in `page_upload_step()`
- "🔄 Start New Job / Reset" button in `page_setup_review()`

---

## Files to Change

| File | Change | Risk |
|---|---|---|
| `app.py` | Add `step_mesh_data` to `init_session()` | Trivial |
| `app.py` | Tessellate inside `if uploaded:` block after successful parse | Low — new code, wrapped in try/except |
| `app.py` | Replace 3D Preview placeholder in `ov_right` with viewer | Low — display only |
| `app.py` | Add `step_mesh_data` to both reset flows | Low |
| `modules/visual_preview.py` | Add `build_step_mesh3d()` function | Low — new function, no changes to existing functions |

**No changes to:** `modules/step_parser.py`, `modules/operation_planner.py`, `modules/tool_selector.py`, pricing/timing modules, export/gcode modules, any regression test files.

---

## Risks and Mitigations

| Risk | Likelihood | Severity | Mitigation |
|---|---|---|---|
| CadQuery not available in deploy environment | Medium | Medium | Fallback to wireframe viewer already in place |
| Tessellation fails on surface-shell STEP (zero volume) | Low | Low | try/except → `step_mesh_data = None` → wireframe fallback |
| Large complex part: >50k triangles | Low for workshop parts | Medium | Increase tolerance to 1.0 or 2.0 mm if triangle count > 30k; add warning message |
| File bytes not available on page revisit | N/A | N/A | Tessellation cached in `step_mesh_data` at upload time — persists for whole session |
| `step_mesh_data` large in session state | Low | Low | 7000 tris × 5543 verts ~= 600 KB as Python lists — acceptable |
| Widget key conflicts | N/A | N/A | No new input widgets — only `st.plotly_chart()` which requires no key |

---

## Test Cases

| # | Scenario | Expected behaviour |
|---|---|---|
| 1 | Upload simple plate STEP (CadQuery env) | Mesh3d solid viewer appears in ov_right column; rotatable, zoomable, pannable |
| 2 | Upload plate with holes (CadQuery env) | Holes visible as topology in the solid |
| 3 | Upload complex part `25_vmc_job_plate_all_basic_features.step` | Renders in < 2 s total; all features visible in solid |
| 4 | Navigate away to another page, then back to Upload | Preview persists from session state (mesh_data cached) |
| 5 | Click "Clear & Start New" | Preview disappears (step_mesh_data = None) |
| 6 | Upload in a lightweight-only environment (CadQuery absent) | Wireframe fallback shown with caption |
| 7 | Upload surface-shell STEP (no solid body) | Wireframe fallback or info message; no crash |
| 8 | Upload binary STEP (parse fails) | "Upload a STEP file to see the preview" info shown |
| 9 | Run VMC regression suite | 18 PASS / 0 FAIL / 0 MISSING / 0 ERROR |
| 10 | 3D viewer does not interfere with feature detection flow | Accepted features, operation plan, pricing unchanged |

---

## Out of Scope

- Animation
- Toolpath simulation
- Feature highlighting in the 3D viewer (deferred to a future story)
- Level-of-detail switching
- Any change to feature detection, operation planning, pricing, gcode generation

---

## Recommended Approach Summary

**Minimum viable (Phase A):** Wire existing `build_3d_view()` into the Upload page placeholder — one line of code in `app.py`. No new functions. Wireframe only. Fast.

**Preferred (Phase B, this story):** Plotly Mesh3d solid viewer using CadQuery tessellation at upload time. Triangle counts confirmed acceptable (2k–7k tris, <0.2s). Degrades gracefully to wireframe if CadQuery absent. Changes are limited to `app.py` (display + caching) and one new function in `modules/visual_preview.py`. No regression risk.

**Recommended to implement Phase B directly** — it is only marginally more complex than Phase A and delivers a significantly better result.
