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

### Update: additive backend field implemented, NOT yet surfaced in UI

Implemented `transform_mesh_and_candidates`'s sibling,
`geometry_transform._footprint_work_bounds()`, wired into
`attach_work_coordinates()` as new additive `footprint_work_min` /
`footprint_work_max` keys. Derived strictly from real tessellated
`face_mesh_data` vertices (never fabricated from length/width heuristics —
candidates without exact face geometry get no footprint, consistent with
Epic 11.3's "honest approximate markers" principle). `x_pos`/`y_pos`
semantics are untouched everywhere; this is purely additive. Covered by a
new synthetic regression case in `run_geometry_transform_regression.py`
using an axis-reversed transform (catches a naive "transform both corners
directly" bug that would get min/max backwards).

**Not wired into the UI table yet.** Testing against the 17b sample with
corrected stock (130×100×40) exposed a separate, unresolved finding:

| Feature | footprint_work_min/max | Expected (full part footprint) |
|---|---|---|
| Face Milling — Bottom | (0,0,0) – (120,90,0) | matches — full footprint ✓ |
| Face Milling — Top | (0,0,30) – (90,90,30) | full footprint would be (0,0,30)–(120,90,30) |
| Step | (0,0,30) – (90,90,30) | n/a (step floor is legitimately smaller) |

The "Top" face milling candidate's exact face geometry is only 90×90 instead
of spanning the full 120×90 footprint that "Bottom" correctly shows. This
*could* be:
1. Geometrically correct — if the step's cut genuinely interrupts the
   physical surface that becomes "work Top" after the Y/Z axis reinterpretation
   (`stock_allowance.py`'s `_orient_transform_to_feature_side` /
   `orientation_face_candidates` selection, lines ~196–223), so the real
   machinable Top face really is smaller there.
2. A face-selection bug — the wrong orientation-candidate face got attached
   to "Top" face milling, meaning the colored 3D highlight for that
   operation may not show the true exact extent (Epic 11.2 implication).

**Resolved — not a bug.** Direct CAD topology inspection (8 total faces in
17b, dumped with CadQuery `Faces()`/`BoundingBox()`/`normalAt()`) settled it
without needing a 3D viewer:

- `face[5]`: CAD-Y=30 plane, x=[-45,45] (90mm), z=[0,90] — the raised plateau
- `face[3]`: CAD-Y=18 plane, x=[45,75] (30mm), z=[0,90] — a genuinely lower
  shelf, 12mm down from face[5] (matches the Step candidate's depth=12mm
  exactly)

The part has a real step cut into the top surface. "Top" face milling's
`face_mesh_data` (90×90, face[5] only) is geometrically correct — it's the
flat, un-stepped plateau. The lower shelf is correctly classified as the
separate Step feature, not face milling. The `length`/`width` fields showing
full stock dimensions (130×100) are intentional, not a bug either —
`stock_allowance.py` widens those specifically for operation-planning
purposes (a face-mill pass must traverse the full stock width even where
the geometry has a step), while the exact face mesh correctly shows only
the true flat region for the 3D highlight. Display fields = toolpath
extent; exact mesh = true geometry. This is the honest-visualization
principle (Epic 11.2/11.3) working as designed.

`footprint_work_min/max` can be safely surfaced in the UI for any
candidate that has exact `face_mesh_data` — there is no remaining
correctness concern blocking that.

## 4. Regression coverage gap found while investigating — fixed

While chasing this report, found `17_stepped_block_single_step.step` existed
in `test_samples/` with zero coverage in
`tests/feature_detection_expectations.json` (flagged under "Uncovered STEP
Files" in every regression report run). Verified detection output is
self-consistent (single Z-direction step, depth=35mm, in a 120×90×500mm
block — matches the file name and produces exactly one Step + two Face
milling candidates, confidence=medium) and added it to the expectations
baseline. Regression is now 19/19 PASS (was 18/18 + 1 uncovered).

Note: `cnc_process_planner_prd_current_state.md` line 185 documents this
sample as "more like a side-profile/extruded part, not a proper top-milled
step" — it was historically deprioritized as non-representative VMC
geometry (17b later became the representative top-milled step sample).
The baseline entry's notes field reflects this — it's a stability sanity
check (no crash, no false positives, consistent counts across reruns),
not a claim that this is exemplary milling geometry.

`Flanges-Body.step` and `X01_complex_freeform_surface_part.step` remain
uncovered intentionally:
- `Flanges-Body.step` has no documented ground-truth geometry to verify
  detected counts against (Face milling=2, Hole=4, Slot=2, Step=1) —
  adding it without verification risks baking in an undetected bug as a
  blessed baseline.
- `X01_complex_freeform_surface_part.step` is the dedicated BSPLINE/NURBS
  test sample for the not-yet-started Epic F3 (complex/freeform detection +
  manual-review routing, see `backlog_status.md` §5). It currently reports
  `Slot=4`, which is very likely a misclassification of freeform surfaces as
  slots — exactly the gap Epic F3 exists to close. Adding it to the baseline
  now would cement that misclassification as "correct" and block the real
  fix later.
- Turning/turn-mill samples (`T01`-`T03`, `TM01`) are explicitly frozen
  pending Epic 18 sign-off per `backlog_status.md` line 13.
- The SLIDE BASE weldment is already covered separately in
  `tests/vmc_golden_expectations.json`.
