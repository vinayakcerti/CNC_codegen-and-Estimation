# CNC Process Planner — Backlog Status Dashboard

**Generated:** 2026-05-14  
**Branch:** `v2-feature-review-engine`  
**Maintained by:** BMAD planning workflow

---

## 1. Project Summary

CNC Process Planner is a STEP-to-process-plan, tool suggestion, and machining time/effort estimation assistant for SME CNC workshops (India-first: Peenya Bangalore, Chennai, Coimbatore). It parses STEP files using CadQuery/OpenCascade, detects machinable feature candidates, and produces a draft process plan, tool list, time/cost estimate, and G-code skeleton.

**Current phase:** VMC / CNC milling — feature detection baseline complete, quoting/pricing implemented, demo-path in progress.  
**Next phase:** CNC Turning (deferred until VMC demo is validated).

| Metric | Value |
|--------|-------|
| Language / framework | Python / Streamlit |
| STEP parsing | CadQuery/OpenCascade (local), lightweight regex fallback |
| Regression baseline | **18 PASS, 0 FAIL, 0 MISSING, 0 ERROR** |
| Total story files | 10 |
| Implemented stories | 10 |
| Pending stories (story files) | 0 |
| Unchecked DoD items | 12 (manual tests + PRD doc updates) |

---

## 2. Current Branch and Status

| Item | Detail |
|------|--------|
| Branch | `v2-feature-review-engine` |
| Base | `main` |
| Recent commits | See below |
| Deployment | Local only (CadQuery incompatible with Streamlit Cloud in current form) |
| Environment | Conda `cnc-cadquery`, VS Code |

**Recent commits (most recent first):**

| Commit | Summary |
|--------|---------|
| `41bd2a5` | Update VMC regression report |
| `ffefe6d` | Add VMC pricing and manual quote currency conversion |
| `4661ba3` | Prepare VMC operator validation outputs |
| `94fe8ab` | Update VMC regression samples |
| `a7a2300` | Add reset current job button |
| `08e3500` | Add chamfer operation planning |
| `1d564dd` / `30f4119` | Add chamfer candidate detection |
| `c05b991` | Add step shoulder operation planning |
| `bdce617` | Add flat-ended slot candidate detection |
| `e6a2715` | Add step shoulder candidate detection |
| `f4e4fc3` | Add blind rectangular pocket detection |

---

## 3. Completed Epics and Stories

### Epic 1 — True Blind Rectangular Pocket Detection ✅ COMPLETE

All stories implemented. Regression verified.

| Story | Status | Key Result |
|-------|--------|-----------|
| True blind rectangular pocket detection | **Implemented ✓** | M03 → 1 Pocket, confidence=medium, depth=12 mm from floor face. Through pocket (M04/13) unaffected. |
| Flat-ended slot detection | **Implemented ✓** | M02 (AR=4.0) correctly classified as Slot, not Pocket. 18 PASS regression. |

### Epic 2 — Step and Shoulder Detection ✅ COMPLETE

| Story | Status | Key Result |
|-------|--------|-----------|
| VMC step / shoulder candidate detection | **Implemented ✓** | 17b → 2 FM + 1 Step, confidence=medium, depth=12 mm, Y-shoulder detected. 12/12 regression samples clean. |
| Step / shoulder operation planning | **Implemented ✓** | Rough End Mill + Finish End Mill generated for Step features. Verify script passes. |

### Epic 3 — Chamfer Detection ✅ COMPLETE

| Story | Status | Key Result |
|-------|--------|-----------|
| Top outer-edge chamfer detection | **Implemented ✓** | M07 → 4 angled PLANE faces detected as CH001, confidence=medium, ~2.0 mm. Sample 25 gains Chamfer=1. All other 16 samples unaffected. |
| Chamfer operation planning | **Implemented ✓** | "Chamfer top edges — use chamfer mill / countersink-style tool" note. Verify script passes. |

### Epic 4 — VMC Operation Planning and Estimation Refinement ✅ COMPLETE

Delivered across multiple stories. All context notes upgraded.

| Story / Sub-task | Status | Key Result |
|-----------------|--------|-----------|
| Boring context notes | **Implemented ✓** | All boring ops carry full reach/min-bore/rigidity note. |
| Pocket context notes | **Implemented ✓** | Rough: corner radius + depth/radial note. Finish: flute length note. |
| Slot context notes | **Implemented ✓** | Rough: tool diameter ≤ slot width note. Finish: flute length + corner radius. |
| Step context notes | **Implemented ✓** | Finish: reach/flute length for shoulder wall. |
| Face milling Setup 2 note | **Implemented ✓** | "Verify workholding and fixture clearance for second setup." |

### Epic 5 — Test Matrix and Demo Readiness ✅ BASELINE COMPLETE

| Story / Task | Status | Key Result |
|-------------|--------|-----------|
| VMC regression test suite | **Implemented ✓** | 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR |
| Operator validation checklist | **Implemented ✓** | `vmc_operator_validation_checklist.md` created for 6 primary samples |
| G-code header safety warning | **Implemented ✓** | Strengthened to "DO NOT RUN — draft planning code only" |
| Setup 2 G-code separator | **Implemented ✓** | Prominent separator block before bottom face-mill G-code |
| Export page safety warning | **Implemented ✓** | Strengthened in `app.py` CNC export page |

### Epic 6 — UX / State Management ✅ COMPLETE

| Story | Status | Key Result |
|-------|--------|-----------|
| Start New Job / Reset Current Job button | **Implemented ✓** | Clears all job-specific session state + DB on click. Visible only when features or candidates exist. Success message on reset. |

### Epic 7 — VMC Operator Validation Readiness ✅ COMPLETE

| Story | Status | Key Result |
|-------|--------|-----------|
| VMC operator validation readiness | **Implemented ✓** | All 5 goals met: Setup 1/2 separation, boring notes, pocket notes, step notes, G-code headers, checklist. |

### Epic 8 — Pricing, Currency, and Tolerance Configuration ✅ COMPLETE

| Story | Status | Key Result |
|-------|--------|-----------|
| VMC estimation, pricing, currency, and tolerance config | **Implemented ✓** | 6 currencies, 4 tolerance levels, complexity factor, 10-row cost breakdown, CSV export. |
| Manual quote currency conversion | **Implemented ✓** | Manual exchange rate, costing vs. customer quote columns, Xe/Wise reference links, CSV with quote column. |

---

## 4. Pending Items (Unchecked DoD — No Story File Required)

These are checklist items left unchecked in existing story files. They do not require new story files — they are completions or verification tasks.

| Item | From Story | Priority |
|------|-----------|---------|
| Run full Streamlit manual validation: M03, M07, M02, 17b, 25 | Multiple stories | **High** |
| Update PRD current state: mark Step/Shoulder, Flat Slot, Chamfer as Implemented | story_vmc_step_shoulder_detection, story_flat_ended_slot_detection, story_chamfer_detection | **Medium** |
| Update PRD current state: mark Step Operation Planning as Implemented | story_step_operation_planning | **Medium** |
| Operator validation checklist completed by a real machinist | story_vmc_operator_validation_readiness | **High** |
| Manual test: M03 with pricing (INR quotation end-to-end) | story_vmc_pricing_currency_tolerance | **High** |
| Manual test: INR → AED currency conversion with M03 | story_manual_quote_currency_conversion | **High** |
| Decide fate of M06_vmc_top_milled_step_shoulder.step (was MISSING, now replaced by 17b) | story_flat_ended_slot_detection notes | **Low** |
| Regression: formally retire M06 from expectations or confirm 17b as replacement | regression notes | **Low** |

---

## 5. Future Epics and Stories

These are not yet started. Story files should not be created until the prior phase is validated.

### Epic F1 — VMC Advanced Feature Detection

| Suggested Story Name | Description | Depends On |
|---------------------|-------------|-----------|
| `story_non_axis_pocket_detection` | Detect pockets rotated at angles other than ±X/±Y | Epic 1 done ✓ |
| `story_blind_slot_detection` | Flat-ended slot with a floor face (currently falls through as Blind Pocket — may relabel) | Epic 1 done ✓ |
| `story_multiple_chamfer_zone_grouping` | Group chamfers by edge type/zone rather than one CH001 for all | Epic 3 done ✓ |
| `story_bottom_edge_chamfer_detection` | Detect under-side (Setup 2) chamfers — requires nz < 0 check | Epic 3 done ✓ |
| `story_thread_mill_detection` | Detect threaded holes from STEP metadata or diameter patterns | Epic 1 done ✓ |

### Epic F2 — Better VMC Toolpath and G-code Strategy

| Suggested Story Name | Description | Depends On |
|---------------------|-------------|-----------|
| `story_pocket_gcode_strategy` | Helical entry, zigzag clearing, wall offset path for pocket G-code output | Epics 1–4 done ✓ |
| `story_better_boring_validation` | Boring tool capability guard: check min bore, max bore, reach against available tools | Epics 1–4 done ✓ |
| `story_better_roughing_finishing_sequence` | Improve inter-feature sequencing (e.g., all roughing before all finishing) | Epics 1–4 done ✓ |
| `story_better_finishing_tool_choice` | Smaller ball-nose / finishing end mill selection for wall and floor passes | Epics 1–4 done ✓ |
| `story_setup_change_handling` | Multi-setup (Setup 1 / Setup 2 / Setup 3) tracking and summary page | Epics 1–4 done ✓ |
| `story_better_estimate_transparency` | Show per-operation depth-pass and radial-pass assumptions in the UI table | Epics 1–4 done ✓ |

### Epic F3 — Complex / Freeform and Manual Review

| Suggested Story Name | Description | Depends On |
|---------------------|-------------|-----------|
| `story_complex_freeform_surface_detection` | Detect BSPLINE/NURBS faces and flag part for specialist review | VMC baseline done ✓ |
| `story_manual_review_routing` | Route complex/flagged parts to a "Manual Review Required" summary page | VMC baseline done ✓ |
| `story_freeform_quoting_mode` | Allow quotation engineer to manually specify complexity factor for non-detected features | Pricing done ✓ |

### Epic F4 — CNC Turning (Deferred)

| Suggested Story Name | Description | Depends On |
|---------------------|-------------|-----------|
| `story_turning_axisymmetric_detection` | Detect rotational symmetry; classify as turned part vs milled part | VMC demo validated |
| `story_od_turning_region_detection` | Detect OD turning regions: shoulders, tapers, undercuts | Axisymmetric detection |
| `story_groove_detection_turning` | Detect external and internal grooves on turned parts | OD region detection |
| `story_turning_operation_planning` | Plan facing, roughing, finishing, grooving, parting operations | Turning detection |
| `story_lathe_tool_selection` | Turning insert selection: CNMG, TNMG, grooving inserts | Turning operation planning |
| `story_lathe_gcode_output` | Generate lathe-style G-code (G96, G50, G71, G70 cycles) | Turning operation planning |

### Epic F5 — Turn-Mill (Deferred)

| Suggested Story Name | Description | Depends On |
|---------------------|-------------|-----------|
| `story_turnmill_geometry_detection` | Detect mixed turning + milling features on a single part | CNC Turning done |
| `story_cross_hole_detection_shafts` | Detect cross-drilled holes on turned shafts | Turn-mill detection |
| `story_turnmill_operation_planning` | Plan turn-mill operation sequence with C-axis milling passes | Turn-mill detection |

### Epic F6 — Deployment and Packaging

| Suggested Story Name | Description | Depends On |
|---------------------|-------------|-----------|
| `story_deployment_investigation` | Investigate CadQuery on Streamlit Cloud vs Docker vs local EXE | VMC demo validated |
| `story_local_packaging_smew` | Package for offline SME workshop use (Windows installer or Docker) | Deployment investigation |
| `story_user_auth_demo` | Add basic authentication/access control for prototype sharing | Deployment investigation |

---

## 6. Blocked and Deferred Items

| Item | Status | Reason |
|------|--------|--------|
| M06_vmc_top_milled_step_shoulder.step | **Deferred / Replaced** | 17b sample covers step detection. M06 was never created. Formally retire or create it. |
| CadQuery on Streamlit Cloud | **Blocked** | Heavy binary dependencies. Unresolved risk. Defer to deployment epic. |
| Full CAM replacement | **Non-goal** | Out of scope by PRD. Not a blocker. |
| Collision detection, toolpath simulation | **Non-goal** | Out of scope by PRD. |
| LLM/API-based geometry interpretation | **Non-goal** | Out of scope by PRD. |
| 5-axis machining | **Non-goal** | Out of scope by PRD. |
| Non-axis-aligned pocket detection | **Future** | Needs separate story. Not a current gap. |
| Controller-specific post-processing | **Future** | Currently emits generic G-code. Fanuc/Haas/Siemens variants deferred. |

---

## 7. Recommended Next 10 Tasks (Ordered)

| # | Task | Type | Priority | Rationale |
|---|------|------|---------|-----------|
| 1 | Run full Streamlit demo path: upload M03 → parse → review → accept → plan → quote → export | Manual test | **Critical** | Unblocks demo. Multiple stories have this as unchecked DoD. |
| 2 | Run Streamlit test: M07 chamfer end-to-end (accept chamfer → plan → chamfer tool note appears) | Manual test | **Critical** | story_chamfer_detection and story_chamfer_operation_planning both require this. |
| 3 | Run Streamlit test: M02 flat slot (accept slot → plan → slot operations) | Manual test | **Critical** | story_flat_ended_slot_detection requires this. |
| 4 | Run Streamlit test: 17b step end-to-end (accept step → plan → rough + finish step notes) | Manual test | **Critical** | story_vmc_step_shoulder_detection and story_step_operation_planning require this. |
| 5 | Run Streamlit test: INR pricing → AED customer quote with M03 | Manual test | **High** | story_vmc_pricing_currency_tolerance and story_manual_quote_currency_conversion require this. |
| 6 | Update PRD current state doc to mark Step, Flat Slot, Chamfer as Implemented in Known Gaps table | Documentation | **Medium** | 4 unchecked PRD update items across stories. Keeps docs consistent with code. |
| 7 | Complete operator validation checklist with a real VMC machinist reviewing M03, M07, 25, M05, M02 | Operator review | **High** | story_vmc_operator_validation_readiness — final gate before demo. |
| 8 | Formally retire M06 from regression expectations (replace with 17b) or create M06 STEP file | Maintenance | **Low** | Cleans up the "MISSING" reference in older story docs. Regression is already 18 PASS. |
| 9 | Improve boring tool validation: check min bore, max bore, and reach against available tool library | Story: `story_better_boring_validation` | **Medium** | Known VMC gap; affects quoting accuracy on bore-heavy parts like M05. |
| 10 | Investigate deployment path: CadQuery on Docker or local packaged EXE | Story: `story_deployment_investigation` | **Medium** | Needed before any external workshop demo or cloud hosting. |

---

## 8. Status Table

### VMC Baseline

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| Epic 1 | True blind rectangular pocket detection | **Completed** | P1 | `modules/step_parser.py` | M03 → Pocket, confidence=medium, depth=12 mm |
| Epic 1 | Flat-ended slot detection (M02 fix) | **Completed** | P2 | `modules/step_parser.py`, `tests/feature_detection_expectations.json` | AR threshold 3.5 distinguishes slot from pocket |
| Epic 2 | VMC step / shoulder candidate detection | **Completed** | P2 | `modules/step_parser.py` | Section E; 12/12 regression clean |
| Epic 2 | Step / shoulder operation planning | **Completed** | P2 | `modules/operation_planner.py` | Rough + Finish End Mill for Step |
| Epic 3 | Top outer-edge chamfer detection | **Completed** | P3 | `modules/step_parser.py`, `tests/feature_detection_expectations.json` | Section F; M07 + sample 25 updated |
| Epic 3 | Chamfer operation planning | **Completed** | P3 | `modules/operation_planner.py` | "Chamfer top edges" note + chamfer mill guidance |
| Epic 5 | VMC regression test suite (18 PASS) | **Completed** | P1 | `tests/run_feature_detection_regression.py` | **18 PASS, 0 FAIL, 0 MISSING, 0 ERROR** |
| Epic 5 | Operator validation checklist | **Completed** | P2 | `_bmad-output/implementation-artifacts/vmc_operator_validation_checklist.md` | Created; machinist sign-off pending |
| — | Streamlit demo path validation (all samples) | **Pending** | P1 | — | Multiple stories require manual Streamlit test |
| — | PRD current state document updates | **Pending** | P2 | `cnc_process_planner_prd_current_state.md` | Mark Step, Flat Slot, Chamfer, Step Planning as Implemented |
| — | M06 STEP file (or retirement) | **Deferred** | P4 | `test_samples/`, expectations JSON | Replaced by 17b in regression |
| F1 | Non-axis-aligned pocket detection | **Future** | P3 | `modules/step_parser.py` | Off-axis pockets currently undetected |
| F1 | Blind slot detection (flat-ended with floor) | **Future** | P3 | `modules/step_parser.py` | Currently falls through as Blind Pocket |
| F1 | Multiple chamfer zone grouping | **Future** | P4 | `modules/step_parser.py` | Group by edge type/position |
| F2 | Better pocket G-code strategy | **Future** | P2 | `modules/gcode_generator.py`, `modules/operation_planner.py` | Helical entry, zigzag clearing |
| F2 | Better boring tool validation | **Future** | P2 | `modules/operation_planner.py`, `modules/tool_selector.py` | Min bore, max bore, reach guard |
| F2 | Better roughing/finishing sequence | **Future** | P3 | `modules/operation_planner.py` | All roughing before all finishing |
| F2 | Better finishing tool choice | **Future** | P3 | `modules/tool_selector.py` | Ball-nose / smaller finish end mill |
| F2 | Setup change handling | **Future** | P3 | `app.py`, `modules/operation_planner.py` | Multi-setup summary |
| F3 | Complex/freeform surface detection | **Future** | P2 | `modules/step_parser.py` | BSPLINE/NURBS → manual review flag |
| F3 | Manual review routing | **Future** | P3 | `app.py` | "Manual Review Required" page |

### VMC Operator Validation

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| Epic 7 | VMC operator validation readiness | **Completed** | P1 | `modules/operation_planner.py`, `modules/gcode_generator.py`, `app.py` | All 5 goals met |
| Epic 7 | G-code header strengthened | **Completed** | P1 | `modules/gcode_generator.py` | "DO NOT RUN — draft planning code only" |
| Epic 7 | Setup 2 G-code separator block | **Completed** | P1 | `modules/gcode_generator.py` | Separator before bottom face-mill G-code |
| Epic 7 | Export page safety text | **Completed** | P1 | `app.py` | Strengthened error message on CNC export page |
| — | Machinist sign-off on checklist | **Pending** | P1 | `vmc_operator_validation_checklist.md` | Human review step; not a code change |

### Pricing and Currency

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| Epic 8 | Pricing, currency, and tolerance configuration | **Completed** | P1 | `app.py` | 6 currencies, 4 tolerance levels, 10-row breakdown |
| Epic 8 | Manual quote currency conversion | **Completed** | P1 | `app.py` | Manual exchange rate; costing vs. customer quote |
| — | Manual test: INR → AED with M03 | **Pending** | P1 | — | Verify full quote export end-to-end |
| — | Live exchange rate API integration | **Future** | P4 | `app.py` | Currently manual only — acceptable for now |

### UI/UX and State Management

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| Epic 6 | Start New Job / Reset Current Job button | **Completed** | P1 | `app.py` | Clears 12 session keys + DB; visible only when state exists |
| — | Streamlit manual test: reset across 2 STEP files | **Pending** | P1 | — | story_reset_current_job DoD item |
| F2 | Better visual display of detected features | **Future** | P3 | `app.py` | Visual/graphical feature summary on review page |
| F6 | User auth / access control for demo | **Future** | P4 | `app.py` | Basic login for external sharing |

### Static 3D Viewer

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| — | Static 3D geometry viewer in Streamlit | **Future** | P3 | `app.py` | Show part bounding box + detected features overlaid |
| — | Highlighted feature display | **Future** | P4 | `app.py` | Color-coded feature candidates on 3D view |

### CNC Turning

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| F4 | Axisymmetric turned part detection | **Future** | P1 (in phase) | `modules/step_parser.py` | Phase start: detect rotationally symmetric parts |
| F4 | OD turning region detection | **Future** | P2 (in phase) | `modules/step_parser.py` | Shoulders, tapers, undercuts |
| F4 | Groove detection (turning) | **Future** | P2 (in phase) | `modules/step_parser.py` | External/internal grooves |
| F4 | Turning operation planning | **Future** | P2 (in phase) | `modules/operation_planner.py` | Facing, rough turn, finish turn, grooving |
| F4 | Lathe-specific tool selection | **Future** | P3 (in phase) | `modules/tool_selector.py` | CNMG, TNMG, grooving inserts |
| F4 | Lathe-style G-code output | **Future** | P3 (in phase) | `modules/gcode_generator.py` | G96, G50, G71/G70 canned cycles |
| — | Test samples: T01, T02, T03 | **Future** | P1 (in phase) | `test_samples/` | Files exist; no regression coverage yet |

### Turn-Mill

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| F5 | Turn-mill geometry detection | **Future** | P1 (in phase) | `modules/step_parser.py` | After Turning phase done |
| F5 | Cross-hole detection on shafts | **Future** | P2 (in phase) | `modules/step_parser.py` | TM01 test sample exists |
| F5 | Turn-mill operation planning | **Future** | P3 (in phase) | `modules/operation_planner.py` | C-axis milling passes |
| F5 | Setup/orientation logic for turn-mill | **Future** | P3 (in phase) | `modules/operation_planner.py`, `app.py` | Sub-spindle, live tooling notation |

### Complex / Freeform / Manual Review

| Epic | Story / Task | Status | Priority | Files Affected | Notes |
|------|-------------|--------|---------|----------------|-------|
| F3 | BSPLINE/NURBS face detection | **Future** | P2 | `modules/step_parser.py` | X01 test sample exists |
| F3 | Manual review routing flag | **Future** | P2 | `app.py` | Route to "needs specialist" page |
| F3 | Freeform manual quoting mode | **Future** | P3 | `app.py` | Let user enter complexity factor manually |

---

## 9. VMC Detection Baseline — COMPLETE ✅

> **Regression result (2026-05-14): 18 PASS, 0 FAIL, 0 MISSING, 0 ERROR**

| Sample File | Features Detected | Status |
|-------------|------------------|--------|
| `01_plain_rectangular_block_100x60x30-Body.step` | Face milling=2 | PASS |
| `02_plate_4_through_holes_d10.step` | Face milling=2, Hole=4 | PASS |
| `03_plate_4_blind_holes_d10_depth15.step` | Face milling=2, Hole=4 | PASS |
| `04_plate_mixed_holes_d6_d10_d20.step` | Face milling=2, Hole=3 | PASS |
| `05_plate_large_bore_d35_through.step` | Face milling=2, Large hole / boring=1 | PASS |
| `06_plate_4_large_bores_d35.step` | Face milling=2, Large hole / boring=4 | PASS |
| `09_slotted_plate_single_center_slot.step` | Face milling=2, Slot=1 | PASS |
| `13_rectangular_pocket_blind.step` | Face milling=2, Pocket=1 | PASS |
| `17b_top_milled_step_shoulder-Body.step` | Face milling=2, Step=1 | PASS |
| `23_mixed_plate_holes_slot_pocket.step` | Face milling=2, Pocket=2, Slot=2 | PASS |
| `25_vmc_job_plate_all_basic_features.step` | Chamfer=1, Face milling=2, Large hole / boring=1, Slot=2 | PASS |
| `M01_vmc_basic_plate_holes.step` | Face milling=2, Hole=4 | PASS |
| `M02_vmc_slot_plate.step` | Face milling=2, Slot=1 | PASS |
| `M03_vmc_blind_rectangular_pocket.step` | Face milling=2, Pocket=1 | PASS |
| `M04_vmc_through_pocket_window.step` | Face milling=2, Pocket=1 | PASS |
| `M05_vmc_large_bore_plate.step` | Face milling=2, Hole=2, Large hole / boring=1 | PASS |
| `M07_vmc_chamfered_plate.step` | Chamfer=1, Face milling=2, Hole=4 | PASS |
| `test5slotted.step` | Face milling=2, Large hole / boring=4, Slot=1 | PASS |

**Feature types with confirmed detection:**

| Feature Type | Detected | Implementation |
|-------------|---------|---------------|
| Face milling (top and bottom) | ✅ | Section A, `step_parser.py` |
| Hole (small drill) | ✅ | Section B, `step_parser.py` |
| Large hole / boring | ✅ | Section B (diameter threshold), `step_parser.py` |
| Slot (rounded end, CYLINDER) | ✅ | Section C, `step_parser.py` |
| Through pocket / window | ✅ | Section D, `step_parser.py` |
| Blind rectangular pocket (floor face) | ✅ | Section D extended, `step_parser.py` |
| Flat-ended slot (AR ≥ 3.5) | ✅ | Section D elif, `step_parser.py` |
| Step / shoulder | ✅ | Section E, `step_parser.py` |
| Chamfer (top outer edge) | ✅ | Section F, `step_parser.py` |

---

## 10. Suggested Next Story Names

These story names are ready to be created as story files when needed. Do not create the files yet.

| # | Story Name | Epic | When to Create |
|---|-----------|------|---------------|
| 1 | `story_demo_preparation_vmc` | Epic 5 wrap-up | Immediately after manual tests pass |
| 2 | `story_prd_current_state_updates` | Documentation | After demo preparation |
| 3 | `story_better_boring_validation` | Epic F2 | After demo validated |
| 4 | `story_pocket_gcode_strategy` | Epic F2 | After demo validated |
| 5 | `story_complex_freeform_surface_detection` | Epic F3 | After demo validated |
| 6 | `story_manual_review_routing` | Epic F3 | After freeform detection |
| 7 | `story_deployment_investigation` | Epic F6 | After demo validated |
| 8 | `story_turning_axisymmetric_detection` | Epic F4 | After VMC deployment decided |
| 9 | `story_non_axis_pocket_detection` | Epic F1 | If customer feedback warrants |
| 10 | `story_multiple_chamfer_zone_grouping` | Epic F1 | If customer feedback warrants |

---

*Dashboard generated from: `cnc_process_planner_prd_current_state.md`, all `story_*.md` files, `vmc_regression_test_report.md`, git log.*
