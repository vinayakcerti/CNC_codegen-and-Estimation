# VMC Corner-Case Validation Matrix

**Purpose:** Prevent repeated one-part-at-a-time fixes by testing failure classes
across detection, review, planning, visualization, and export.

## Validation Levels

Every supported sample must be checked at all levels:

1. **Parse:** units, solids, topology, bounding box, volume.
2. **Detect:** type, count, dimensions, depth, location, confidence, provenance.
3. **Orient:** datum, coordinate transform, setup direction, accessibility.
4. **Review:** grouping, exact highlight, accept/ignore behavior, duplicates.
5. **Plan:** operation sequence, setup, tool feasibility, warnings, estimate.
6. **Export:** setup sheet, CSV, and draft code agree with the reviewed plan.

A count-only match is not a complete pass.

## A. Coordinate and Orientation Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| CO-01 | STEP origin at part corner | Work coordinates follow the approved datum |
| CO-02 | STEP origin at part center | Negative CAD coordinates transform correctly |
| CO-03 | STEP origin outside the solid | No false stock allowance or marker displacement |
| CO-04 | Z-up model | Top/Bottom and X/Y remain consistent |
| CO-05 | Y-up model | Axis swap transforms coordinates, setup labels, dimensions, and highlights together |
| CO-06 | X-up model | Rotate into planning orientation or require manual review |
| CO-07 | One or more reversed axes | Left/Right and Front/Back remain physically correct |
| CO-08 | Mirrored component | Features retain correct handed location and setup |
| CO-09 | Part rotated 90/180/270 degrees | Same physical part produces equivalent planning result |
| CO-10 | Arbitrary off-axis rotation | Supported 3+2 orientation or explicit manual-review result |
| CO-11 | Millimetre STEP | No scaling change |
| CO-12 | Inch STEP | Convert all geometry exactly once |
| CO-13 | Mixed assembly/local coordinate systems | Resolve transforms per solid or reject unsupported assembly |
| CO-14 | Datum changed by user | Tables, hover, operations, and exports update together |
| CO-15 | Coordinates on boundaries or zero | Zero is preserved; it is not replaced by fallback values |

## B. Part and Stock Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| ST-01 | Stock exactly equals part | No stock-removal edge candidates |
| ST-02 | Symmetric allowance | Correct allowance per side |
| ST-03 | Asymmetric allowance | Do not assume the part is centered |
| ST-04 | Stock smaller than part | Blocking validation error |
| ST-05 | Only one axis has allowance | Only relevant cleanup faces generated |
| ST-06 | Zero or near-zero numerical noise | No false operations |
| ST-07 | Raw rectangular billet | Full material-removal candidates allowed |
| ST-08 | Round billet | Cylindrical stock model or manual review |
| ST-09 | Casting/forging | Only finishing allowance surfaces selected |
| ST-10 | Weldment/fabrication | Existing fabricated geometry is not treated as raw stock |
| ST-11 | Existing/rework part | Only selected rework operations are accepted |
| ST-12 | Multiple disconnected solids | Identify assembly/weldment or block unsupported planning |
| ST-13 | Internal voids already present in stock | Do not plan removal twice |
| ST-14 | User edits stock after acceptance | Recompute derived candidates without duplicating accepted work |

## C. Hole and Bore Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| HB-01 | Through hole | Correct diameter, axis, depth, and exit |
| HB-02 | Blind hole | Correct floor and usable depth |
| HB-03 | Flat-bottom blind hole | Do not add drill-tip depth silently |
| HB-04 | Conical drill bottom | Distinguish full-diameter depth from tip depth |
| HB-05 | Counterbore | Parent/child diameters and depths remain linked |
| HB-06 | Countersink | Angle and major/minor diameter represented |
| HB-07 | Stepped bore | Do not collapse into duplicate independent holes |
| HB-08 | Large bore | Boring capability, reach, and rigidity validated |
| HB-09 | Angled hole | Assign accessible setup or manual review |
| HB-10 | Cross hole/intersecting holes | Avoid duplicate cylindrical-face detections |
| HB-11 | Partial/open hole at edge | Classify as open feature, not full hole |
| HB-12 | Threaded hole metadata present/absent | Do not claim threading without evidence |
| HB-13 | Same-diameter holes at different depths | Group only when operation parameters match |
| HB-14 | Cylinder split into several CAD faces | One physical hole remains one candidate |
| HB-15 | Tiny/sliver cylinders | Suppress topology noise |

## D. Slot and Pocket Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| SP-01 | Rounded-end through slot | One slot with correct centerline and width |
| SP-02 | Flat-ended slot | Slot, not pocket |
| SP-03 | Blind slot with floor | Correct depth and floor cleanup |
| SP-04 | Open-ended slot | Open feature and suitable entry strategy |
| SP-05 | Rotated slot | Orientation preserved in dimensions and highlight |
| SP-06 | Multiple identical slots | Correct physical count and grouping |
| SP-07 | Intersecting slots | No duplicate face-level candidates |
| SP-08 | Blind rectangular pocket | Floor-backed pocket |
| SP-09 | Through window | Through pocket/window, not blind pocket |
| SP-10 | Pocket with island | Preserve island and do not highlight/fill it as removal |
| SP-11 | Multi-level pocket | Separate linked levels and depths |
| SP-12 | Open-sided pocket | Distinguish from closed pocket |
| SP-13 | Tapered/draft walls | Flag non-vertical walls and finishing implications |
| SP-14 | Internal corner radii | Validate tool diameter and remaining material |
| SP-15 | Pocket/slot near stock boundary | No marker beyond real geometry |

## E. Step, Face, Chamfer, and Profile Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| SF-01 | Single top step | Correct floor, wall, depth, setup, and position |
| SF-02 | Multiple steps | Separate nonduplicate candidates |
| SF-03 | Nested steps | Preserve parent/child order |
| SF-04 | Step along X/Y and swapped CAD axes | Same physical result after transform |
| SF-05 | Side or bottom step | Correct additional setup or manual review |
| SF-06 | Ramp/angled design face | Not falsely classified as a step |
| SF-07 | Interrupted top face | Face milling uses actual machinable regions |
| SF-08 | Multiple coplanar top faces | Group intentionally without filling gaps |
| SF-09 | Bottom face | Explicit flip/setup requirement |
| SF-10 | Top outer chamfer | Correct edge group and approximate size |
| SF-11 | Bottom chamfer | Secondary setup, not top chamfer |
| SF-12 | Internal pocket chamfer | Linked to its parent feature |
| SF-13 | Variable or partial chamfer | Do not average into a misleading uniform chamfer |
| SF-14 | Fillet versus chamfer | Curved blend is not classified as planar chamfer |
| SF-15 | Outer profile with tabs/interruptions | Preserve actual boundary and workholding warning |

## F. Visualization and Interaction Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| VI-01 | Exact face provenance available | Highlight the actual CAD face mesh |
| VI-02 | Only approximate marker available | Label it clearly as approximate |
| VI-03 | Concave or stepped face | No bounding rectangle across empty space |
| VI-04 | Face with internal holes/islands | Highlight excludes voids |
| VI-05 | Axis-swapped planning orientation | Highlight remains attached to source CAD geometry |
| VI-06 | Bottom/hidden feature | Camera preset or transparency makes it inspectable |
| VI-07 | Overlapping candidates | Selection remains understandable and deterministic |
| VI-08 | Grouped candidates | Group highlight covers exactly its physical members |
| VI-09 | No selection | No residual gold highlight |
| VI-10 | Toggle filters/pages/reruns | Highlight state does not become stale |
| VI-11 | Hover coordinates | Coordinate system is named and values match the table |
| VI-12 | Large model | Viewer remains responsive and does not silently omit features |

## G. Acceptance, Grouping, and State Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| AS-01 | Accept candidate once | Exactly one accepted feature |
| AS-02 | Accept same candidate again | Idempotent; no duplicate |
| AS-03 | Rerun Streamlit | Stable acceptance state |
| AS-04 | Change filter/group mode | Candidate identity remains stable |
| AS-05 | Accept group then edit one member | Clear and deterministic result |
| AS-06 | Ignore then rediscover | Ignore decision remains traceable or is explicitly reset |
| AS-07 | Manual feature overlaps detected feature | Warn and prevent accidental duplication |
| AS-08 | Stock-derived candidate recomputed | Replace prior derived version, do not append |
| AS-09 | Upload new file with same filename | Content hash prevents stale state |
| AS-10 | Clear/reset job | Database, session state, and UI clear together |
| AS-11 | Candidate order changes | IDs do not depend on list order |
| AS-12 | Same physical feature split across faces | Stable physical-feature identity |

## H. Planning and Machine Capability Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| PM-01 | 3-axis top-accessible features | Supported normally |
| PM-02 | Side features on 3-axis | Explicit re-fixture/setup |
| PM-03 | 3+2 indexed feature | Only supported when machine capability exists |
| PM-04 | Simultaneous 5-axis/freeform need | Manual CAM review; no false 3-axis plan |
| PM-05 | Feature inaccessible due to workholding | Warning/block |
| PM-06 | Tool diameter too large | Reject or select alternate strategy |
| PM-07 | Tool reach/flute length insufficient | Reject or warn before plan approval |
| PM-08 | No matching tool | Explicit unresolved tool, not silent fallback |
| PM-09 | Tool holder/spindle limits exceeded | Capability warning |
| PM-10 | Multiple setups | Ordered setup summary with datum and orientation |
| PM-11 | Roughing/finishing duplicates | One intentional sequence only |
| PM-12 | Interdependent operations | Parent operation precedes finish/child operation |
| PM-13 | Through feature breakout | Fixture/support warning where relevant |
| PM-14 | Casting/weldment cleanup | No raw-billet bulk-removal assumption |
| PM-15 | Unsupported geometry | Manual-review route instead of invented operation |

## I. Estimate and Export Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| EX-01 | Multi-depth/radial passes | Estimate exposes pass assumptions |
| EX-02 | Setup change | Setup time included once |
| EX-03 | Duplicate operation prevention | Estimate does not double-count |
| EX-04 | Machine/material changed | Feeds, time, and cost recompute |
| EX-05 | Tolerance changed | Complexity/finishing assumptions update |
| EX-06 | UI versus setup sheet | Same feature coordinates and setup |
| EX-07 | UI versus CSV | Same accepted features and operation order |
| EX-08 | UI versus draft code | Same setup sequence and tool assignment |
| EX-09 | Unsupported feature | Export contains a visible unresolved warning |
| EX-10 | Locale/decimal formatting | Numeric values remain machine-readable |

## J. Parser, Data, and Runtime Resilience Cases

| ID | Corner case | Expected behavior |
|---|---|---|
| RT-01 | Malformed/truncated STEP | Controlled error without stale prior job |
| RT-02 | Unsupported STEP entity/exporter variation | Warning and fallback/manual review |
| RT-03 | CadQuery unavailable | Clearly degraded mode; no claim of deep detection |
| RT-04 | Very large STEP | Timeout/progress behavior and bounded memory |
| RT-05 | SQLite locked or disk I/O error | Recoverable message, retry, and no data corruption |
| RT-06 | OneDrive sync interference | Database/runtime files use safe local location |
| RT-07 | Streamlit process restart | Job recovery behavior is explicit |
| RT-08 | Two browser sessions | Session data does not cross-contaminate |
| RT-09 | Missing/corrupt tool library | Pre-flight blocks planning |
| RT-10 | Partial export failure | No misleading success message |

## Required Test Oracles

Each golden sample record must contain:

- file hash and unit
- CAD bounding box and planning bounding box
- selected datum and transform matrix
- expected physical features and stable IDs
- feature type, count, coordinates, dimensions, depth, setup, confidence
- expected source face indices or face signatures
- expected grouping and default acceptance
- expected operations, tools, setups, and critical warnings
- expected export values
- known unsupported/manual-review conditions

## Representative Sample Families Still Needed

- Asymmetric-stock part
- Y-up and X-up copies of the same reference geometry
- Inch-unit STEP
- Counterbore/countersink/stepped bore
- Angled and edge-open hole
- Pocket with island and multi-level pocket
- Rotated/blind/open slot
- Multiple/nested/bottom step
- Casting/forging finishing sample
- Weldment with only selected final machining
- Rework part
- Multi-solid assembly
- Deliberately malformed and very large STEP
