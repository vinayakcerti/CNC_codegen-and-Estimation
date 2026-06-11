# VMC Reliability Hardening Epics and Stories

**Branch:** `v2-feature-review-engine`  
**Priority:** Blocks turning, turn-mill, deployment, and VMC release  
**Source:** V1/V2 operator reports, current regression gaps, code review, and
`vmc_corner_case_matrix.md`

## Epic 9: Canonical Geometry Contract

**Goal:** Make every layer use an explicit, consistent coordinate and orientation model.

### Story 9.1: Define Coordinate Frames and Datum Contract

Acceptance criteria:

- Define CAD, stock, planning/work, and setup-local frames.
- Define the origin and positive directions displayed to operators.
- Define behavior for centered, negative, translated, Y-up, X-up, mirrored,
  and rotated STEP files.
- Unsupported arbitrary orientation produces `Manual review required`.
- Contract is documented and represented by serializable transform metadata.

### Story 9.2: Implement CAD-to-Planning Transform

Acceptance criteria:

- One reusable transform maps points, vectors, dimensions, face normals, and bounds.
- Axis swap, sign reversal, translation, and approved rotation use the same transform.
- Setup labels derive from transformed normals, not raw CAD normals.
- Zero coordinates are preserved correctly.
- Unit tests cover CO-01 through CO-15.

### Story 9.3: Apply Transform Across the Product

Acceptance criteria:

- Candidate tables, hover text, groups, accepted features, operations, setup
  sheets, CSV, and draft code use the same planning values.
- Raw CAD coordinates remain available for diagnostics and provenance.
- Coordinate system is visibly named in the UI and exports.
- Cross-layer consistency tests fail on any mismatch.

## Epic 10: Golden Validation Harness

**Goal:** Replace count-only regression with operator-verifiable golden records.

### Story 10.1: Define Golden Expectation Schema

Acceptance criteria:

- Schema covers file hash, units, transforms, features, geometry provenance,
  grouping, operations, tools, warnings, and exports.
- Supports exact, tolerance-based, unordered, and explicitly unsupported expectations.
- Schema validation reports actionable errors.

### Story 10.2: Add Geometry and Workflow Invariants

Acceptance criteria:

- Highlights remain on source geometry or declared approximate bounds.
- Candidate IDs are stable and unique.
- Accepted features and operations are idempotent.
- Stock cannot be smaller than the transformed finished part.
- All setups and machine requirements are feasible or explicitly blocked.
- UI/export values agree.

### Story 10.3: Build Core Golden Sample Pack

Acceptance criteria:

- Full golden records for 17B, M01, M02, M03, M05, M07, sample 25, and slide base.
- V1 and V2 report findings are represented by permanent tests.
- Golden records are reviewed by product owner/operator before being treated as truth.

### Story 10.4: Add Metamorphic Orientation Tests

Acceptance criteria:

- Generate or obtain translated, centered, mirrored, and 90-degree rotated
  equivalents of reference parts.
- Equivalent physical features remain equivalent after normalization.
- Tests catch transform drift without requiring a unique handcrafted oracle for
  every orientation.

## Epic 11: Exact Visualization and Provenance

**Goal:** Ensure the viewer never depicts nonexistent machining geometry as exact.

### Story 11.1: Stable Face Provenance

Acceptance criteria:

- Every exact candidate stores source face signatures/indices and physical-feature identity.
- Provenance survives grouping and acceptance.
- Split CAD faces can map to one physical feature without losing member faces.

### Story 11.2: Exact Highlight Rendering

Acceptance criteria:

- Face milling, holes, slots, pockets, steps, chamfers, and profiles highlight
  their actual face meshes where provenance exists.
- Concave faces, internal holes, and islands are preserved.
- No bounding rectangle crosses empty space.
- Bottom and side features can be inspected using camera/transparency controls.

### Story 11.3: Honest Approximate Markers

Acceptance criteria:

- Approximation is used only when exact provenance is unavailable.
- Approximate markers are visually distinct and explicitly labelled.
- Marker geometry remains within approved CAD bounds.
- No detached, diagonal, residual, or stale highlight survives selection changes.

## Epic 12: Feature-Family Hardening

**Goal:** Cover topology variations instead of tuning only current samples.

### Story 12.1: Hole and Bore Hardening

Acceptance criteria:

- Cover HB-01 through HB-15.
- Counterbores, countersinks, stepped bores, intersecting holes, angled holes,
  and edge-open holes are correctly represented or routed to manual review.
- Split cylindrical faces do not create duplicate physical holes.

### Story 12.2: Slot and Pocket Hardening

Acceptance criteria:

- Cover SP-01 through SP-15.
- Blind/through/open, rounded/flat, rotated, multi-level, island, and draft-wall
  cases are differentiated.
- Highlights and operation linkage preserve actual removal regions.

### Story 12.3: Step and Shoulder Hardening

Acceptance criteria:

- Cover SF-01 through SF-06.
- Multiple, nested, side, bottom, and axis-swapped steps remain distinct.
- Ramps and unrelated angled faces are not false steps.

### Story 12.4: Face, Chamfer, and Profile Hardening

Acceptance criteria:

- Cover SF-07 through SF-15.
- Interrupted/coplanar face regions do not fill gaps.
- Top, bottom, internal, partial, and variable chamfers are not collapsed into
  one misleading candidate.
- Fillets are not chamfers.

## Epic 13: Stock-Type and Starting-Part Semantics

**Goal:** Stop applying billet assumptions to castings, weldments, and rework parts.

### Story 13.1: Billet Allowance Model

Acceptance criteria:

- Equal, symmetric, asymmetric, one-axis, and invalid stock cases are handled.
- Part placement within stock is explicit, not always centered.
- Editing stock recomputes derived candidates idempotently.

### Story 13.2: Casting and Forging Mode

Acceptance criteria:

- Only specified finishing/machining surfaces are selected by default.
- Existing near-net geometry is not interpreted as bulk material to remove.
- Allowance source and uncertainty are shown.

### Story 13.3: Weldment/Fabrication Mode

Acceptance criteria:

- Existing fabricated members and slots are not automatically treated as new machining.
- Operator can select final machining groups and obtain exact highlights.
- Multi-solid and joined-body behavior is explicit.

### Story 13.4: Existing Part/Rework Mode

Acceptance criteria:

- No machining is assumed without operator selection.
- New/rework operations are traceable separately from existing geometry.
- Reset and re-upload cannot retain stale selections.

## Epic 14: Candidate Identity and Acceptance Integrity

**Goal:** Make review state deterministic across reruns, grouping, and recomputation.

### Story 14.1: Stable Physical-Feature IDs

Acceptance criteria:

- IDs derive from geometry signature and source file hash, not list order.
- Same physical feature has the same ID across reruns.
- Changed source content with the same filename cannot reuse stale state.

### Story 14.2: Idempotent Acceptance and Grouping

Acceptance criteria:

- Cover AS-01 through AS-12.
- Accepting, grouping, filtering, editing, and recomputing never duplicate features.
- Manual/detected overlap is surfaced before commit.
- Accepted and ignored decisions have visible provenance.

### Story 14.3: Idempotent Operation Generation

Acceptance criteria:

- Regenerating a plan produces the same operations exactly once.
- Changed features replace affected operations without duplicating unaffected work.
- Estimates and exports cannot contain stale operations.

## Epic 15: Setup and Machine Feasibility

**Goal:** Clearly separate supported 3-axis planning from indexed or simultaneous multi-axis needs.

### Story 15.1: Machine Capability Model

Acceptance criteria:

- Record axes, indexed 3+2 capability, simultaneous 5-axis capability, travel,
  spindle, tool, and setup constraints.
- A VMC record cannot silently receive a 5-axis plan.

### Story 15.2: Accessibility and Setup Assignment

Acceptance criteria:

- Cover PM-01 through PM-15.
- Feature normals map to explicit setup orientations.
- Side/bottom features require re-fixture or capable indexed machine.
- Inaccessible/unsupported work is blocked or routed to manual review.

### Story 15.3: Tool and Holder Feasibility

Acceptance criteria:

- Diameter, reach, flute length, bore range, holder clearance, and spindle
  limitations are checked.
- Missing tools remain unresolved; no unsafe silent substitution.

## Epic 16: Cross-Layer Planning, Estimate, and Export Consistency

**Goal:** Ensure approved machining intent remains unchanged through handover.

### Story 16.1: Operation Traceability

Acceptance criteria:

- Every generated operation references its source accepted feature and setup.
- Parent/child and rough/finish relationships are explicit.
- Unsupported features cannot disappear silently.

### Story 16.2: Estimate Integrity

Acceptance criteria:

- Cover EX-01 through EX-05.
- Pass, setup, tool-change, material, machine, and tolerance assumptions are visible.
- Duplicate operations cannot double-count time or cost.

### Story 16.3: Export Contract Tests

Acceptance criteria:

- Cover EX-06 through EX-10.
- Setup sheet, CSV, and draft code match reviewed coordinates, setup order,
  accepted features, tools, and warnings.
- Export failure cannot produce a misleading success state.

## Epic 17: Runtime and Data Resilience

**Goal:** Make local operation reliable enough for unattended regression and demos.

### Story 17.1: STEP Failure and Degraded-Mode Handling

Acceptance criteria:

- Cover RT-01 through RT-04.
- Malformed, unsupported, missing-CadQuery, and large files fail safely.
- Previous-job state is never shown as the new result.

### Story 17.2: Database and OneDrive Safety

Acceptance criteria:

- Cover RT-05 and RT-06.
- Runtime SQLite data uses a safe local location or robust retry/recovery.
- Disk I/O and lock errors show recovery instructions without crashing the app.

### Story 17.3: Session and Restart Integrity

Acceptance criteria:

- Cover RT-07 through RT-10.
- Browser sessions do not share job state.
- Restart/reset behavior is explicit and testable.
- Missing libraries and partial exports block downstream claims.

## Epic 18: Operator Release Gate

**Goal:** End the correction loop with measurable sign-off.

### Story 18.1: Adversarial Operator Test Pack

Acceptance criteria:

- Test at least one sample from every supported feature and starting-part family.
- Include transformed/oriented variants and intentionally unsupported cases.
- Record expected and actual results in the golden schema.

### Story 18.2: Automated Release Report

Acceptance criteria:

- One command runs schema checks, targeted tests, full golden regression,
  workflow smoke tests, and export consistency checks.
- Report distinguishes supported pass, expected manual review, regression
  failure, and missing coverage.

### Story 18.3: VMC Sign-off

Acceptance criteria:

- Product owner and experienced operator approve coordinate convention,
  visual meaning, operation intent, and export readability.
- No P0/P1 defect remains.
- Known limitations are documented in-product.
- Only then may VMC baseline status return to `operator-ready`.

## Execution Order

| Order | Stories | Reason |
|---|---|---|
| 1 | 9.1-9.3 | Geometry contract prevents repeated coordinate/setup fixes |
| 2 | 10.1-10.4 | Strong oracle must exist before broad code changes |
| 3 | 11.1-11.3 | Removes misleading visual feedback |
| 4 | 14.1-14.3 | Stabilizes identity, acceptance, and operation regeneration |
| 5 | 12.1-12.4 | Hardens feature families against topology variation |
| 6 | 13.1-13.4 | Handles billet, casting, weldment, and rework correctly |
| 7 | 15.1-15.3 | Defines 3-axis/3+2/5-axis capability boundaries |
| 8 | 16.1-16.3 | Locks consistency through estimate and export |
| 9 | 17.1-17.3 | Improves runtime resilience |
| 10 | 18.1-18.3 | Final automated and operator release gate |

## Definition of Done for Every Story

- Reproduction test exists first.
- Implementation uses the canonical geometry contract.
- Targeted tests pass.
- Golden regression passes.
- Smoke test passes when UI/workflow is affected.
- Failure is added to the permanent corner-case matrix.
- No unrelated user changes are reverted.
