# Sprint Change Proposal: VMC Reliability Hardening

**Date:** 2026-06-11  
**Branch:** `v2-feature-review-engine`  
**Change scope:** Major technical hardening before further feature expansion  
**Mode:** Batch proposal requested by product owner

## 1. Issue Summary

Four weeks of operator testing have repeatedly found defects after the automated
regression suite reported a clean result. The individual fixes were valid, but
the regression oracle was incomplete: it primarily checked feature type counts
and selected dimensions. It did not consistently verify coordinate frames,
setup orientation, exact highlighted geometry, accepted-feature state,
operation-plan traceability, or export consistency.

The V2 validation report demonstrates the pattern on
`17b_top_milled_step_shoulder-Body.step`:

- CAD coordinates and expected machining coordinates use different origins or
  orientations.
- Setup labels can disagree with the operator's view of the part.
- Approximate marker geometry can look like nonexistent machining geometry.
- A feature-count regression can pass while the operator-facing result is
  misleading.

This is not one isolated detector bug. It is a missing system-wide geometry and
validation contract.

## 2. Impact Analysis

### Epic impact

- Freeze CNC turning, turn-mill, cloud deployment, and advanced G-code work.
- Reopen VMC baseline status. It is feature-complete but not yet reliability-complete.
- Add a dedicated VMC Reliability Hardening epic set.
- Treat operator sign-off as a release gate rather than an informational review.

### Artifact impact

- **PRD:** define coordinate semantics, supported machine scope, confidence
  behavior, and operator-verification boundaries.
- **Architecture:** introduce an explicit CAD-to-planning coordinate transform
  and stable candidate identity/provenance.
- **UX:** distinguish CAD coordinates from work coordinates and distinguish
  exact CAD-face highlights from approximate markers.
- **Tests:** replace count-only expectations with golden end-to-end expectations
  and invariant/property checks.
- **Exports:** require the same coordinate and setup values as the review UI.

### Technical impact

Affected components include:

- `modules/step_parser.py`
- `modules/stock_allowance.py`
- `modules/visual_preview.py`
- `modules/operation_planner.py`
- `modules/setup_sheet.py`
- `modules/gcode_generator.py`
- `modules/data_store.py`
- `app.py`
- all regression scripts and expectation data

## 3. Recommended Approach

Use a hybrid of direct adjustment and MVP clarification:

1. Define one canonical geometry contract.
2. Build a golden validation harness around that contract.
3. Correct each feature family against the harness.
4. Run cross-layer consistency checks from detection through export.
5. Obtain operator sign-off on representative and adversarial parts.

Rollback is not recommended. Existing detection and planning work remains useful,
but it must be placed behind stronger transforms, provenance, and validation.

## 4. Two-Run Execution Plan

### Run 1: Foundation and proof

Goal: prevent entire classes of coordinate, identity, and visualization defects.

1. Establish canonical CAD, planning, stock, and setup coordinate frames.
2. Add explicit transforms and datum/orientation metadata.
3. Create golden expectation schema and invariant test utilities.
4. Convert 17B, M01, M02, M03, M05, M07, mixed plate, and slide base into
   full golden cases.
5. Replace approximate highlighting with exact-face highlighting where face
   provenance exists; visibly label any remaining approximation.
6. Make accepted-feature state idempotent and stable across reruns.
7. Verify UI, operation plan, setup sheet, CSV, and draft code use the same
   transformed values.

### Run 2: Feature-family and workflow hardening

Goal: systematically exercise the corner-case matrix and close detected gaps.

1. Harden holes and bores.
2. Harden slots, pockets, steps, face milling, chamfers, and profiles.
3. Harden stock types: billet, casting/forging, weldment, and rework.
4. Add machine-capability and setup-feasibility gates.
5. Add parser, database, session-state, and large-file resilience tests.
6. Run complete golden regression, smoke test, and operator checkpoint.

Two runs means two coordinated development campaigns, not two individual
commits. Any unsupported case must produce an explicit `Manual review required`
result rather than a confident but incorrect plan.

## 5. Release Gates

The VMC baseline may be called operator-ready only when:

- Every golden sample passes feature, coordinate, setup, visualization,
  operation, and export assertions.
- No highlighted point lies outside its source CAD face or approved approximate
  marker bounds.
- Re-running or revisiting pages does not duplicate accepted features or
  operations.
- Unsupported orientations and inaccessible features are clearly blocked or
  routed to manual review.
- At least one operator validates each supported feature family and starting
  part type.
- All discovered failures are represented by permanent regression tests.

## 6. Handoff

- **Product owner/operator:** approve datum and coordinate conventions and
  validate golden expected results.
- **Architect/developer:** implement transform, provenance, and validation
  foundations.
- **Developer:** execute stories in priority order from
  `vmc_reliability_hardening_epics.md`.
- **Reviewer/tester:** run adversarial and edge-case review after each epic.

## 7. Approval State

The product owner requested this hardening plan and BMad task breakdown. The
proposal is ready for task-by-task execution. Implementation changes should
remain on `v2-feature-review-engine`; do not merge to `main` until release gates
are met.
