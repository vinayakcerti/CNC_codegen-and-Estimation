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

## 2026-06-10 - V2 Feature Review Validation

- Fixed stock-orientation inference for STEP files where the modeled vertical axis is not the planner's Z axis, covering `17b_top_milled_step_shoulder-Body.step`.
- Corrected audit-facing stock allowance outputs for the 17b sample:
  - face milling now plans against `130 x 100 x 5 mm` stock-facing work,
  - edge milling cleanup depths are `5 mm`,
  - step shoulder review dimensions are `90 x 90 x 12 mm`.
- Split step shoulder planning into roughing, floor finishing, and wall finishing operations.
- Added setup-sheet operation geometry columns (`X`, `Y`, `L`, `W`, `D`) for audit/export consistency.
- Added regressions for 17b stock orientation, operation strategy, and setup-sheet geometry export.
