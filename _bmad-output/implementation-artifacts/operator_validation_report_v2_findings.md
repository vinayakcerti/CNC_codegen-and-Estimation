# Operator Validation Report V2 — Findings and Fix Status

**Source:** `Feature Detection Validation Report V2.docx` (user-supplied, 2026-06-16)
**Sample affected:** `17b_top_milled_step_shoulder-Body.step`, `M01_vmc_basic_plate_holes.step`

The report flagged three issues. All three were investigated with code-level
reproduction (no UI access was available in this session — Chrome extension
was disconnected). Findings below.

## 1. Step/shoulder dimensions and setup label — RESOLVED, was a stock-entry issue

The report showed Step width=30mm and setup=Back, expecting width=90mm and
setup=Top. Reproducing with the **same stock dimensions the report implies**
(130 × 100 × 40mm) confirms the app already produces the correct result:

```
Step  work_x=105.0 work_y=45.0 L=90.0 W=90.0 depth=12.0 setup=Top
```

This matches `tests/vmc_golden_expectations.json`'s `operator_report_v2` entry,
which is already checked into the regression suite and passing
(`tests/run_vmc_golden_regression.py`). The original report's wrong values
came from the auto-detected bounding-box stock (120×30×90, no Y/Z swap), not
from manually-entered stock matching the part's real orientation. **No code
change needed here** — `infer_work_transform()` already selects the correct
axis permutation once the operator enters stock that matches the physical
orientation.

## 2. 3D viewer hover coordinates — FIXED (Epic 9.4)

Hovering on the base mesh in the 3D viewer showed raw CAD-tessellation
coordinates (e.g. y=100, half of a 200mm-wide part) instead of corner-origin
work coordinates (y=200 at the far edge) used everywhere else in the UI
(stock dimensions, feature table).

**Root cause:** `geometry_transform.py`'s `CoordinateTransform` (built in
Epic 9) was wired into `stock_allowance.py` and `starting_part_policy.py`
(candidate table positions) but never into the 3D mesh tessellation pipeline.
`_parse_and_tessellate()` in `app.py` stored raw CadQuery vertex coordinates
directly into `step_mesh_data`, and `build_step_mesh3d()` rendered them with
no `transform` applied.

**Fix:**
- `modules/geometry_transform.py`: new `transform_mesh_and_candidates()` —
  returns work-frame copies of mesh vertices, candidate marker positions, and
  `face_mesh_data` overlay vertices, without mutating the CAD-frame originals
  (which `stock_allowance.py` still depends on).
- `modules/visual_preview.py`: `build_step_mesh3d()` accepts an optional
  `transform` parameter; applies the new helper before building any Plotly
  traces. Base mesh trace also got an explicit `hovertemplate` for clarity.
- `app.py`: `_render_3d_panel()` computes `infer_work_transform(step_parse_result, stock)`
  and passes it through.
- Regression: `tests/run_geometry_transform_regression.py` —
  `_run_mesh_and_candidate_transform()` verifies mesh/candidate/face-overlay
  vertices land in the corner-origin work frame and that inputs aren't mutated.

Verified directly: M01 sample (120×200×30mm part) mesh now reports
`x=[0,120] y=[0,200] z=[0,30]` instead of the previous CAD-centered
`x=[-60,60] y=[-100,100] z=[0,30]`.

## 3. Open question — feature X/Y position: centroid vs. corner (Epic 9.5, backlog)

Not fixed — needs a product decision before implementation.

The report's expected table implies `X`/`Y` represent the **minimum corner**
of a feature's footprint (e.g. Step `X=30` = `120(stock length) - 90(step length) - margin`).
The app's actual convention — used consistently across **every** feature type
(Face milling, Edge milling, Hole, Step, etc.) — is the **face centroid**
(`x_pos = center_x`, see `step_parser.py` Section E line ~1918, and the
equivalent in every other section).

Confirmed during this investigation: with the corrected stock (130×100×40),
Edge milling Left/Right report `work_x=0` / `work_x=120` (matches doc exactly,
because the face's plane position along its own normal axis coincides with
the boundary either way). But the in-plane axis position consistently reports
the **centroid** (e.g. `work_y=45`, half of the 90mm span) where the doc
expects the **corner** (`Y=0`).

This is not a Step-specific bug — it is the position convention used
everywhere in the app (operation planner, G-code origin references, setup
sheets). Redefining it has broad blast radius:
- Could change exact field values relied on by `tests/run_feature_identity_regression.py`,
  `tests/run_operation_plan_regression.py`, and the 18-sample feature
  detection baseline.
- G-code generation and setup-sheet rendering may already account for
  centroid semantics in their own offset math; switching conventions
  without auditing those call sites could introduce a *new* mismatch rather
  than removing one.

**Recommendation:** before implementing, confirm with the reporting operator
whether they want `X`/`Y` redefined as the footprint's minimum corner across
the whole app (high blast radius, one-time migration), or whether a
**second**, display-only field (e.g. `footprint_x_min`/`footprint_y_min`)
should be added to the candidate table without touching `x_pos`/`y_pos`
(low risk, additive). The second option is recommended.
