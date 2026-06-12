# Changelog

## 2026-06-11

- Added a canonical CAD-to-work coordinate transform with axis permutation,
  origin translation, reversed-axis support, and setup-normal mapping.
- Preserved raw CAD feature positions while attaching work coordinates and
  transform provenance.
- Accepted machining features now use work coordinates and work setup labels.
- Added 17B orientation and candidate-coordinate regressions.
- Retained setup-face alternatives for every CAD axis and selected the true
  work Top/Bottom faces after orientation inference.
- Added a golden regression pack covering eight representative milling parts,
  including the 17B rotated-axis part and the complex slide-base weldment.
- Added geometry, provenance, determinism, grouping, and exact-highlight
  invariants to prevent previously corrected behavior from regressing.
- Made hole, slot, pocket, step, and facing detection invariant across
  axis-aligned STEP permutations and reversed machining directions.
- Added stock-aware selection among ambiguous detection frames while preserving
  original CAD coordinates, exact face provenance, and work coordinates.
- Generalized stock allowance and edge-milling geometry to all coordinate
  permutations using forward and inverse CAD/work transforms.
- Added metamorphic regression coverage for five representative parts across
  positive/negative X and Y rotations, including dimensions, setups, positions,
  stock edges, and lateral-mirror equivalence.
- Added content-derived physical feature IDs and exact detection IDs so
  re-detection, candidate reordering, and CAD face splitting cannot duplicate
  accepted milling work.
- Made flat and grouped feature review status physical-identity aware and added
  acceptance regressions for reruns, renamed file copies, changed sources,
  face-split candidates, and repeated group commits.
- Added stable operation IDs and physical-feature traceability, deterministic
  feature ordering, setup-aware fallback deduplication, and regressions proving
  repeated planning does not duplicate work or suppress distinct features.
- Carried operation and physical-feature IDs into operation CSV and setup-sheet
  exports, with a round-trip export contract regression and smoke-test checks.
- Made time estimates consume unique planned operations and physical-feature
  positions, preventing duplicate rows or excluded/reference geometry from
  inflating time, effort, operation counts, or tool-change counts.
- Added starting-part policies for billet, casting/forging, weldment, and
  rework workflows. Non-billet modes now retain oriented CAD candidates without
  applying rectangular-stock facing depths or generating edge cleanup work.
- Added explicit operator-selection, allowance-source, uncertainty, work-scope,
  and multi-solid weldment warnings with regression coverage on the 28-solid
  slide-base sample.
- Added explicit billet part-placement offsets and per-side X/Y/Z allowances,
  including unequal top/bottom facing and side-cleanup depths.
- Added blocking validation for undersized stock and offsets that place the part
  outside the stock envelope; invalid stock no longer creates derived work.
- Added explicit machine-axis capability profiles and setup-accessibility
  assessment for direct 3-axis, indexed 3+2, manual re-fixture, part-flip, and
  simultaneous 5-axis requirements.
- Unknown feature types now create blocked manual-review operations instead of
  silently receiving a generic end-mill plan.

## 2026-06-10 - V2 Feature Review Validation

- Fixed stock-orientation inference for STEP files where the modeled vertical axis is not the planner's Z axis, covering `17b_top_milled_step_shoulder-Body.step`.
- Corrected audit-facing stock allowance outputs for the 17b sample:
  - face milling now plans against `130 x 100 x 5 mm` stock-facing work,
  - edge milling cleanup depths are `5 mm`,
  - step shoulder review dimensions are `90 x 90 x 12 mm`.
- Split step shoulder planning into roughing, floor finishing, and wall finishing operations.
- Added setup-sheet operation geometry columns (`X`, `Y`, `L`, `W`, `D`) for audit/export consistency.
- Added regressions for 17b stock orientation, operation strategy, and setup-sheet geometry export.
