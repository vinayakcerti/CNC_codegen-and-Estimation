# Story: UI/UX Toolpath-Style Redesign Plan

**Epic:** UI/UX Redesign  
**Priority:** High (pre-demo readiness)  
**Status:** Planning — not yet implemented  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer or VMC machinist evaluating the app for the first time,  
> I want the navigation to follow a logical job workflow (upload → review → plan → estimate → export),  
> so that I can complete a full quotation without jumping back and forth between 10+ pages.

---

## 2. Business Value

| Value | Detail |
|-------|--------|
| Demo readiness | A clean, logical 5-page workflow is easier to demo to an operator or workshop owner than the current 11-item navigation list |
| Reduced confusion | Configuration pages (Machine, Material, Tool Library) are prerequisites — they should not appear at the same level as workflow pages |
| Toolpath parity | The competitor reference shows Upload → 3D view → Material → Setup → Tools → Strategy → Estimate → Export. Matching this flow builds credibility with professional users |
| Zero regression risk | The redesign only moves existing UI into new page wrappers and tab groups. No business logic is touched |

---

## 3. Current Page Structure

### 3.1 Current navigation list (`sidebar_nav()`)

```
1.  Upload STEP File             → page_upload_step()       lines 201–407
2.  Machine Setup                → page_machine_setup()     lines 409–455
3.  Tool Library                 → page_tool_library()      lines 457–651
4.  Material Setup               → page_material_setup()    lines 652–679
5.  Feature Input                → page_feature_input()     lines 681–938
5a. Setup & Feature Review       → page_setup_review()      lines 939–1273
6.  Operation Plan               → page_operation_plan()    lines 1274–1308
7.  Time & Effort Estimate       → page_time_estimate()     lines 1310–1586
8.  Approximate Process Preview  → page_visual_preview()    lines 1587–1626
9.  CNC Program Export           → page_cnc_export()        lines 1628–1763
10. Job Notes & History          → page_job_notes()         lines 1765–1833
```

**Total: 1,866 lines, single file (`app.py`).**

### 3.2 Current structure problems

| Problem | Impact |
|---------|--------|
| 11-item flat nav list with no grouping | User has no sense of which pages are config vs. workflow |
| Pages 2, 3, 4 (Machine/Tool/Material) appear equally important as pages 5, 6, 7 | Workshop owner sets these once; they don't need to see them on every workflow run |
| "5a" label communicates the page is an afterthought | It is actually the most important workflow page |
| Feature Input (5) and Feature Review (5a) are separate pages doing related jobs | User manually enters features on 5, then accepts CAD candidates on 5a — two separate navigations |
| Visual Preview (8) is placed between Time Estimate (7) and Export (9) | No logical reason for this position |
| Operation Plan (6) is a very short page — one table, one download button | Wastes a full nav entry |
| Job Notes (10) sits in primary navigation alongside core workflow pages | Clutters the nav for a rarely-used tool |
| No visual hierarchy between "configure once" and "do every job" | Experienced users want to skip config; new users don't know which pages matter |

---

## 4. Proposed Page Structure

### 4.1 Target navigation

```
── CONFIGURE ──────────────────────────────  (sidebar section header)
   ⚙  Machine & Material          (Machine tab + Material tab)
   🔧  Tool Library                (Tool editor tab + Speeds & Feeds tab)

── WORKFLOW ───────────────────────────────  (sidebar section header)
   1.  Upload & Overview           (Upload + geometry + part summary)
   2.  Material & Machine          (Active config summary + change links)
   3.  Setup & Feature Review      (CAD candidates + manual features + validation)
   4.  Tools                       (Active tool list + per-operation tool assignments)
   5.  Strategy & Operations       (Operation plan + machining sequence)
   6.  Estimate & Quote            (Time breakdown + pricing + currency conversion)
   7.  Export & Setup Sheet        (G-code + setup sheet + all downloads)

── HISTORY ────────────────────────────────  (sidebar section header)
   📝  Job Notes
```

### 4.2 Page-by-page content mapping

#### Page 1 — Upload & Overview

**Content source:** `page_upload_step()` (unchanged)

| Section | Source | Change? |
|---------|--------|---------|
| STEP file uploader | Current page 1 | None |
| Stock & Part Dimensions | Current page 1 | None |
| Volume Analysis (3 metrics) | Current page 1 | None |
| Parsed Coordinate Ranges table | Current page 1 | None |
| CAD Geometry Summary (parser, solids, faces, edges) | Current page 1 | None |
| Unit conversion/detection banner | Current page 1 | None |
| Clear & Start New button | Current page 1 | None |

**3D viewer:** Not in this phase. A placeholder section reading  
`"3D preview coming soon — upload a STEP file to view part geometry here."` will be added  
as a deferred block inside a `st.expander` so the vertical space is reserved but visually unobtrusive.  
See Section 9 (Separate later story).

---

#### Page 2 — Material & Machine

**Content source:** `page_machine_setup()` + `page_material_setup()` merged with `st.tabs()`

| Tab | Source | Change? |
|-----|--------|---------|
| Machine | Current page 2 content | None — identical logic |
| Material | Current page 4 content | None — identical logic |

**Purpose of this page in the workflow:** After uploading the STEP, the user confirms the target machine and material before reviewing features. This mirrors the Toolpath flow (Upload → Material → Setup).

**Active config strip:** A read-only info strip at the top of this page shows:  
`Machine: [name] / [type] / [controller] | Material: [name] | Safety factor: [x]`

---

#### Page 3 — Setup & Feature Review

**Content source:** `page_setup_review()` (primary) + tabs from `page_feature_input()`

| Tab | Source | Change? |
|-----|--------|---------|
| CAD Candidates | Current `page_setup_review()` main content | None — identical logic |
| Manual Features | Current `page_feature_input()` Feature List tab | None — move only |
| Tolerance & Finish Guide | Current `page_feature_input()` Tolerance + Surface Finish tabs | None — move only |

**This is the central workflow page.** The Reset button and pre-flight checklist remain in the "CAD Candidates" tab.  
Candidate detection, acceptance, duplicate prevention, and conflict warnings are **not changed**.

---

#### Page 4 — Tools

**Content source:** `page_tool_library()` (same as current "Tool Library" in Configure section)

This page is the *workflow view* of tools — presented here in the job sequence so the user can confirm the tool list and speeds/feeds before generating the operation plan.

| Tab | Source | Change? |
|-----|--------|---------|
| Active Tool List | Current Tool Library tab 1 content | None |
| Speeds & Feeds Calculator | Current Tool Library tab 2 content | None |

**Note:** The same tool library is accessible from the Configure section (for setup) and from this workflow page (for job-time review). Both routes point to the same `page_tool_library()` function — just two nav entries calling the same function.

---

#### Page 5 — Strategy & Operations

**Content source:** `page_operation_plan()`

| Section | Source | Change? |
|---------|--------|---------|
| Machine + Material context info strip | Current page 6 info strip | None |
| Operation table | Current page 6 | None |
| CSV download button | Current page 6 | None |

**Layout improvement:** The operation table is wide — this page benefits from using `layout="wide"` fully with the table filling the content area. No logic change.

---

#### Page 6 — Estimate & Quote

**Content source:** `page_time_estimate()` (unchanged)

| Section | Source | Change? |
|---------|--------|---------|
| Time Breakdown metrics (4 columns) | Current page 7 | None |
| Total Estimates | Current page 7 | None |
| Quote Configuration (currency, rates, tolerance, complexity) | Current page 7 | None |
| 10-row cost breakdown table | Current page 7 | None |
| Customer quote currency conversion | Current page 7 | None |
| CSV export | Current page 7 | None |
| Disclaimer | Current page 7 | None |

---

#### Page 7 — Export & Setup Sheet

**Content source:** `page_cnc_export()` (unchanged)

| Section | Source | Change? |
|---------|--------|---------|
| Safety error banner | Current page 9 | None |
| G-code viewer + download | Current page 9 | None |
| Operation plan CSV download | Current page 9 | None |
| Time report CSV download | Current page 9 | None |
| Program statistics | Current page 9 | None |
| Active configuration summary | Current page 9 | None |
| Operator Setup Sheet generation | Current page 9 (bottom half) | None |

---

#### Configure — Machine & Material (sidebar section)

Same as Page 2 above but accessed from the sidebar "Configure" section header. This gives power users a shortcut to config without navigating through the workflow. Both routes call the same underlying code.

---

#### Configure — Tool Library (sidebar section)

Same as Page 4 above. Accessible both from the workflow (page 4) and from the sidebar configure section.

---

#### History — Job Notes

**Content source:** `page_job_notes()` (unchanged, just demoted in navigation)

---

### 4.3 What is retired / merged

| Page removed from main nav | Reason | Fate |
|---------------------------|--------|------|
| `2. Machine Setup` | Absorbed into Page 2 Machine & Material | Function stays in code, called from new wrapper |
| `4. Material Setup` | Absorbed into Page 2 Machine & Material | Function stays in code, called from new wrapper |
| `5. Feature Input` | Absorbed into Page 3 Setup & Feature Review as tabs | Function stays in code, content moved to tabs |
| `6. Operation Plan` | Renamed to Page 5 Strategy & Operations | Function unchanged |
| `7. Time & Effort Estimate` | Renamed to Page 6 Estimate & Quote | Function unchanged |
| `8. Approximate Process Preview` | Deferred — content will move to Upload page in Phase 3 | Function stays in code |
| `9. CNC Program Export` | Renamed to Page 7 Export & Setup Sheet | Function unchanged |

**No functions are deleted in this phase. Only routing and labels change.**

---

## 5. Phase 0 — Baseline Validation (Before Any Code Change)

**Purpose:** Confirm the regression baseline is clean before touching any UI code.

**Command:**
```powershell
C:\Users\vinay\miniforge3\envs\cnc-cadquery\python.exe tests/run_feature_detection_regression.py
```

**Expected result:**
```
18 PASS, 0 FAIL, 0 MISSING, 0 ERROR
```

**Also verify the app starts:**
```powershell
C:\Users\vinay\miniforge3\envs\cnc-cadquery\python.exe -m streamlit run app.py
```

- Open in browser
- Confirm 11-item nav list is visible
- Upload M03_vmc_blind_rectangular_pocket.step
- Navigate to 5a. Setup & Feature Review
- Confirm candidates appear

**Gate:** Do not proceed to Phase 1 until both checks pass.

**Files checked:** None (read-only verification step)

---

## 6. Phase 1 — Navigation and Page Naming Only

**Goal:** Change only the sidebar label list and the `main()` dispatcher. No function logic changes. No content moves.

**Scope:** `app.py` — two functions only: `sidebar_nav()` and `main()`.

### 6.1 sidebar_nav() change

Replace the current flat `pages` list with a grouped structure using `st.sidebar.markdown` as section headers:

```python
# BEFORE (current):
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

# AFTER (target):
# Section headers via st.sidebar.markdown, radio for workflow pages only
st.sidebar.markdown("**⚙ Configure**")
config_pages = ["Machine & Material", "Tool Library"]
# ...
st.sidebar.markdown("**Workflow**")
workflow_pages = [
    "1. Upload & Overview",
    "2. Material & Machine",
    "3. Setup & Feature Review",
    "4. Tools",
    "5. Strategy & Operations",
    "6. Estimate & Quote",
    "7. Export & Setup Sheet",
]
# ...
st.sidebar.markdown("**History**")
history_pages = ["Job Notes"]
```

**Implementation note:** Streamlit does not support section headers inside `st.radio`. The pattern is to use separate `st.radio` calls for each section, or use `st.sidebar.selectbox` groups. The simplest approach for Phase 1 is a single `st.radio` with the section headers rendered as non-selectable caption dividers above groups. A workable low-risk implementation uses multiple `st.radio` calls each with `label_visibility="collapsed"` and `st.sidebar.caption()` headers between them.

### 6.2 main() dispatcher change

Update the `elif` chain to route the new page names to existing functions:

```python
# New routes:
if   page == "1. Upload & Overview":          page_upload_step()
elif page == "Machine & Material":             page_configuration()    # new wrapper, Phase 2
elif page == "Tool Library":                   page_tool_library()
elif page == "2. Material & Machine":          page_configuration()    # same wrapper
elif page == "3. Setup & Feature Review":      page_setup_review()
elif page == "4. Tools":                       page_tool_library()     # same function, two routes
elif page == "5. Strategy & Operations":       page_operation_plan()
elif page == "6. Estimate & Quote":            page_time_estimate()
elif page == "7. Export & Setup Sheet":        page_cnc_export()
elif page == "Job Notes":                      page_job_notes()
```

### 6.3 Files affected in Phase 1

| File | Functions changed | Nature of change |
|------|------------------|-----------------|
| `app.py` | `sidebar_nav()` | Rewrite labels and grouping only |
| `app.py` | `main()` | Update elif routing to new page names |

**No other files touched. No function bodies changed.**

### 6.4 Phase 1 verification

- App starts without error
- All 7 workflow pages are reachable
- Both configure pages are reachable
- Regression still passes: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR
- M03 demo path works end-to-end through new navigation labels

---

## 7. Phase 2 — Layout Polish Only

**Goal:** Improve the visual presentation of existing content without changing any logic. Tab groups, column layouts, section headers.

**Scope:** `app.py` — specific page functions only. No module files touched.

### 7.1 Machine & Material — merge into tabs

Add `page_configuration()`:

```python
def page_configuration():
    st.header("Machine & Material Configuration")
    tab_machine, tab_material = st.tabs(["Machine", "Material"])
    with tab_machine:
        # copy body of page_machine_setup() here, OR call a helper
        _machine_setup_body()
    with tab_material:
        # copy body of page_material_setup() here, OR call a helper
        _material_setup_body()
```

The existing `page_machine_setup()` and `page_material_setup()` functions are refactored so their bodies are in private helper functions (`_machine_setup_body`, `_material_setup_body`) that both the old and new routes can call.

### 7.2 Setup & Feature Review — add Manual Features tab

Add `st.tabs()` wrapper to `page_setup_review()`:

```python
def page_setup_review():
    # Reset button stays at TOP, outside tabs
    # ... (existing reset logic, unchanged)

    tab_cad, tab_manual, tab_guide = st.tabs([
        "CAD Candidates & Review",
        "Manual Features",
        "Tolerance & Finish Guide",
    ])
    with tab_cad:
        # existing page_setup_review body (unchanged)
    with tab_manual:
        # existing page_feature_input() Feature List tab body (unchanged)
    with tab_guide:
        # existing page_feature_input() Tolerance + Surface Finish tab bodies (unchanged)
```

**Risk note:** The tolerance and surface finish guide widgets have Streamlit `key=` values. When moved into a new function context, duplicate key errors can occur if those keys are already registered from page 5 Feature Input being loaded in the same session. Resolution: prefix all moved widget keys with `"rev_"` (e.g., `key="rev_it_grade"` instead of `key="it_grade"`). This is the only logic-adjacent change in Phase 2 and must be tested.

### 7.3 Upload & Overview — add deferred 3D viewer placeholder

Add a `st.expander("3D Preview (coming soon)", expanded=False)` at the bottom of `page_upload_step()`:

```python
with st.expander("3D Preview (coming soon)", expanded=False):
    st.info(
        "A static rotatable 3D view of the uploaded part will appear here in a future update. "
        "Use the '8. Approximate Process Preview' page for the current bounding-box preview."
    )
```

This reserves the visual space and communicates the roadmap without any implementation work.

### 7.4 Files affected in Phase 2

| File | Functions changed | Nature of change |
|------|------------------|-----------------|
| `app.py` | Add `page_configuration()` | New wrapper, tabs only |
| `app.py` | `page_machine_setup()`, `page_material_setup()` | Extract body into `_machine_setup_body()`, `_material_setup_body()` helpers |
| `app.py` | `page_setup_review()` | Add `st.tabs()` wrapper; absorb feature input tabs |
| `app.py` | `page_upload_step()` | Add 3D preview placeholder expander at bottom |
| `app.py` | `main()` | Route "Machine & Material" and "2. Material & Machine" to `page_configuration()` |

**No module files touched.**

### 7.5 Phase 2 verification

- All tabs render without error
- CAD candidate acceptance works from the "CAD Candidates & Review" tab
- Manual feature add/delete works from the "Manual Features" tab
- Tolerance guide renders without duplicate key errors
- Machine and Material config saves correctly from the merged tab page
- Regression still passes: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR

---

## 8. Phase 3 — Demo-Path Validation

**Goal:** Run the full end-to-end demo path through the new navigation and confirm every step works. No code changes in this phase — it is a testing and sign-off phase.

### 8.1 Demo path (M03 — Blind Pocket)

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Start app fresh (no prior state) | Nav shows grouped sections |
| 2 | Navigate to Configure → Machine & Material | Both tabs visible; active machine shown |
| 3 | Navigate to Configure → Tool Library | Tool editor + Speeds & Feeds tab visible |
| 4 | Navigate to 1. Upload & Overview | STEP uploader shown; 3D placeholder visible |
| 5 | Upload M03_vmc_blind_rectangular_pocket.step | Parse succeeds; geometry summary shows |
| 6 | Navigate to 2. Material & Machine | Active machine + material shown |
| 7 | Navigate to 3. Setup & Feature Review → CAD Candidates tab | 3 candidates shown (FM×2, Pocket×1) |
| 8 | Accept Pocket candidate → Add accepted candidates | Feature list shows 1 accepted feature |
| 9 | Navigate to 4. Tools | Tool list visible |
| 10 | Navigate to 5. Strategy & Operations | Operation plan generates (Rough + Finish End Mill for pocket) |
| 11 | Navigate to 6. Estimate & Quote | Time breakdown + quote config visible |
| 12 | Set currency to INR, enter rates, compute quote | Breakdown table shows 10 rows |
| 13 | Navigate to 7. Export & Setup Sheet | G-code visible + draft safety warning |
| 14 | Download Draft CNC Program | .nc file downloads |
| 15 | Generate Setup Sheet | HTML/PDF setup sheet generated |
| 16 | Click Start New Job / Reset on page 3 | State clears; candidates gone |

### 8.2 Demo path (M07 — Chamfer)

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Upload M07_vmc_chamfered_plate.step | Parse succeeds |
| 2 | Page 3 → CAD Candidates | 7 candidates (FM×2, Hole×4, Chamfer×1) |
| 3 | Accept Chamfer → Add | Feature list shows Chamfer |
| 4 | Page 5 → Operation Plan | Chamfer operation: "Chamfer top edges | Use chamfer mill…" |

### 8.3 Demo path (M02 — Flat Slot)

| Step | Action | Expected result |
|------|--------|----------------|
| 1 | Upload M02_vmc_slot_plate.step | Parse succeeds |
| 2 | Page 3 → CAD Candidates | 3 candidates (FM×2, S001 Flat-ended slot) |
| 3 | Accept S001 → Add | Slot operation plan generated |

### 8.4 Regression gate

```powershell
C:\Users\vinay\miniforge3\envs\cnc-cadquery\python.exe tests/run_feature_detection_regression.py
```

Expected: **18 PASS, 0 FAIL, 0 MISSING, 0 ERROR**

---

## 9. Separate Later Story — Static Rotatable 3D Preview

**Story name (do not create yet):** `story_static_3d_viewer`

**Scope:** This is a follow-on story, not part of the current UI/UX redesign. It is listed here to define the boundary clearly.

### What this story will do

- Add a "3D Viewer" tab on Page 1 (Upload & Overview) that shows the actual part geometry from the OCC solid
- Geometry is extracted from CadQuery tessellation (not just bounding box wireframe)
- View is static and rotatable using Plotly `go.Mesh3d`
- No animation, no toolpath simulation, no real-time updates
- Detected features are optionally highlighted by type (color-coded faces)

### What this story will NOT do

- No animation or motion
- No toolpath simulation
- No collision detection
- No 5-axis view
- No real-time part update during planning

### Files likely affected (future)

| File | Change |
|------|--------|
| `modules/visual_preview.py` | New function `build_step_3d_from_solid()` using OCC tessellation |
| `app.py` | Activate the "3D Viewer" tab on Upload & Overview; replace placeholder with real view |

### Constraint

The viewer will only work when CadQuery parser is active. When using the lightweight fallback, the tab shows:  
`"3D viewer requires CadQuery/OpenCASCADE. Install the cnc-cadquery conda environment to enable this view."`

### When to start

After Phase 3 demo-path validation is signed off by the operator/machinist.

---

## 10. Protected Files and Functions

The following must **not be modified** in any phase of this redesign:

| File / Function | Reason |
|----------------|--------|
| `modules/step_parser.py` — `_classify_face_records()`, all Sections A–F | Feature detection baseline is stable at 18 PASS |
| `modules/operation_planner.py` — `plan_operations()`, `OPERATION_RULES`, `estimate_path_length()`, `_context_note()`, `_sequence_key()` | Operation planning logic is correct and validated |
| `modules/time_estimator.py` — `estimate_time()` | Time calculation is correct |
| `modules/gcode_generator.py` — `generate_gcode()` | G-code generation and safety headers are correct |
| `modules/tool_selector.py` — `select_tool()` | Tool selection logic is correct |
| `modules/setup_sheet.py` — `generate_setup_sheet()` | Setup sheet output is correct |
| `modules/data_store.py` | All database operations |
| `modules/speeds_feeds.py` | Speeds and feeds calculations |
| `modules/tolerance_guide.py` | Tolerance and surface finish reference data |
| `modules/visual_preview.py` | 2D and 3D bounding-box preview (until 3D viewer story) |
| `app.py` — `init_session()` | All session state keys |
| `app.py` — `page_time_estimate()` body | Pricing and currency calculation logic |
| `app.py` — candidate acceptance logic in `page_setup_review()` | Acceptance, duplicate prevention, conflict warning |
| `tests/` — all regression files and expectations | Regression baseline |
| `test_samples/` — all STEP files | Test data |
| `data/` — all JSON data files | Tool/material/machine data |

---

## 11. Manual Test Checklist

To be completed after each phase before sign-off.

### Phase 1 checklist (navigation only)

- [ ] App starts without Python error
- [ ] New grouped nav structure visible in sidebar
- [ ] All 7 workflow pages reachable and load without error
- [ ] Both configure pages reachable
- [ ] Job Notes page reachable
- [ ] No duplicate key Streamlit errors in browser console
- [ ] Regression: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR

### Phase 2 checklist (layout/tabs)

- [ ] Machine tab: machine selector, parameters, Apply button all work
- [ ] Material tab: material selector, parameters, Apply button all work
- [ ] Machine + Material changes persist across page navigation
- [ ] Page 3 — CAD Candidates tab: candidates appear, Accept + Add buttons work
- [ ] Page 3 — Manual Features tab: Add Feature form works, features appear in list
- [ ] Page 3 — Tolerance Guide tab: IT grade table loads, no key errors
- [ ] Reset button on Page 3 clears all state as before
- [ ] Upload page: 3D preview placeholder visible after upload
- [ ] Regression: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR

### Phase 3 checklist (demo path)

- [ ] Full M03 demo path: upload → review → plan → estimate → export (Section 8.1)
- [ ] M07 chamfer demo path (Section 8.2)
- [ ] M02 flat slot demo path (Section 8.3)
- [ ] INR → AED currency conversion works on page 6
- [ ] Setup sheet generates and downloads
- [ ] Operator validation checklist reviewed by a machinist
- [ ] Regression: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR

---

## 12. Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Streamlit duplicate `key=` errors when tolerance/surface finish widgets move from page 5 to page 3 | Medium | Medium — Streamlit shows a visible error | Prefix moved widget keys with `"rev_"` before moving; test in Phase 2 |
| Multiple `st.radio` calls in sidebar create unexpected interaction (one radio selection resets another) | Low | Low — cosmetic | Use `st.session_state` key for each radio to isolate state |
| Tool Library appearing in both Configure section and workflow Page 4 causes confusion | Low | Low | Use the same function body; add a caption distinguishing "configuration library" vs "active job tools" |
| Phase 2 `page_configuration()` wrapper calling helper functions introduces subtle import/scope errors | Low | Low | Test immediately after each helper extraction |
| The `page_visual_preview()` function is left orphaned (no nav route) and its imports remain | None — no impact | None | Leave the function in the file; it is still importable and callable for regression purposes |
| Candidate acceptance state is tied to specific session keys; moving the UI into tabs does not affect session keys | None — no impact | None | The tabs are purely visual wrappers; `st.session_state` keys remain unchanged |

---

## 13. Definition of Done

### Phase 1 Done When

- [ ] `sidebar_nav()` uses grouped sections with section header labels
- [ ] `main()` dispatcher routes all new page names correctly
- [ ] All 11 previous page functions are still reachable (some via new names)
- [ ] App starts and runs without error
- [ ] Regression: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR
- [ ] No code in `modules/` is modified

### Phase 2 Done When

- [ ] `page_configuration()` added with Machine and Material tabs
- [ ] `page_setup_review()` has CAD Candidates / Manual Features / Tolerance Guide tabs
- [ ] No duplicate Streamlit key errors
- [ ] All widget interactions in all tabs work correctly
- [ ] Machine/Material/Tool config saves and persists as before
- [ ] CAD candidate acceptance and manual feature add/delete work from their new tab locations
- [ ] 3D preview placeholder visible on Upload page
- [ ] Regression: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR
- [ ] No code in `modules/` is modified

### Phase 3 Done When

- [ ] Full M03, M07, M02 demo paths complete without error (Section 8)
- [ ] Operator validation checklist reviewed and signed off by a machinist
- [ ] No regressions observed in any demo path step
- [ ] Regression: 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR

---

## 14. Recommended First Implementation Story

**Start with:** Phase 1 — Navigation and page naming only.

**Why Phase 1 first:**

1. It is the smallest possible change — two functions in one file
2. It delivers visible user-facing improvement immediately (new nav structure)
3. It has zero risk to feature detection, operation planning, or pricing
4. It can be reviewed and approved in one sitting
5. It establishes the routing structure that Phase 2 builds on

**Exact scope of the first coding task:**

```
File:     app.py
Functions: sidebar_nav(), main()
Changes:
  - sidebar_nav(): Replace flat 11-item pages list with grouped navigation
    (section headers as st.sidebar.caption() dividers, workflow pages as st.radio)
  - main(): Update elif chain to route new page names to existing functions
  - No other changes in this commit
```

**Acceptance criteria for first coding task:**

1. App starts and all pages are reachable
2. Nav shows three visual groups: Configure / Workflow / History
3. Workflow pages are numbered 1–7
4. Configure and History items appear below the workflow group
5. `python tests/run_feature_detection_regression.py` → 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR
6. No `modules/` files modified

---

## 15. File and Story Metadata

| Field | Value |
|-------|-------|
| Story file | `story_uiux_toolpath_style_redesign_plan.md` |
| Created | 2026-05-14 |
| Branch | `v2-feature-review-engine` |
| Related stories | `story_reset_current_job.md`, `story_vmc_operator_validation_readiness.md` |
| Blocks | `story_static_3d_viewer` (future) |
| Does NOT block | Any feature detection or pricing story |
| Estimated effort | Phase 1: 1–2 hours. Phase 2: 3–4 hours. Phase 3: 1–2 hours (testing only). |
