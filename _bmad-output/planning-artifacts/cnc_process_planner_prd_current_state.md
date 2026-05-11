# CNC Process Planner PRD and Current State

## 1. Product Vision

CNC Process Planner is a practical CNC process planning and estimation assistant for small and medium manufacturing workshops, especially Indian CNC clusters such as Peenya Bangalore, Chennai, and Coimbatore.

The product helps workshop owners, supervisors, machinists, production planners, and quotation engineers quickly understand customer-supplied STEP files, identify machinable feature candidates, choose suitable tools, estimate machining time and effort, and prepare a draft process plan.

This is not a full CAM replacement in the current phase. It is a decision-support and estimation tool for SME workshops that may not have dedicated CAM programmers or process planners.

Positioning:

> STEP-to-process-plan, tool suggestion, and machining time/effort estimation assistant for SME CNC workshops.

## 2. Target Users and Market

| Area | Current Definition |
| --- | --- |
| Primary users | CNC workshop owners, CNC supervisors, CNC machinists, production planners, quotation engineers, small job-work manufacturers |
| Initial market | India first |
| Initial clusters | Peenya Bangalore, Chennai, Coimbatore, and other SME manufacturing clusters |
| Machine environment | VMC / CNC milling, CNC turning / lathe, turn-mill machines |
| Controller context | Generic Fanuc, Haas, Siemens, Mazatrol-style environments |

Core user workflow:

1. Upload STEP file.
2. Parse geometry.
3. Review stock and part summary.
4. Review detected feature candidates.
5. Accept, edit, or ignore candidates.
6. Generate operation plan.
7. Review suggested tools.
8. Review time and effort estimate.
9. Export setup sheet and draft CNC program.
10. Verify externally before production.

## 3. Current Technology Stack

| Component | Current State |
| --- | --- |
| Language | Python |
| Frontend | Streamlit |
| Deep STEP parsing | CadQuery / OpenCascade locally |
| Fallback parsing | Lightweight regex STEP parser |
| Version control | GitHub |
| Current branch | `v2-feature-review-engine` |
| Local environment | Conda environment: `cnc-cadquery` |
| Development environment | VS Code |
| Coding assistants | Claude Code / Codex |
| BMAD use | Backlog, PRD, epics, stories, and planning only |

Deployment note:

CadQuery/OpenCascade works locally in the conda environment. Streamlit Cloud may not support CadQuery easily because of heavy binary dependencies. Advanced parsing is currently best treated as local or server-side. A Streamlit Cloud fallback may run lightweight parsing, but it will not match local deep parsing.

## 4. Current Completed Features

### STEP Upload and Parsing

- Upload STEP files.
- Use CadQuery/OpenCascade deep parsing locally.
- Fall back to lightweight parsing if CadQuery is unavailable.

### CAD Geometry Summary

When STEP parsing succeeds, the app shows:

- Parser used
- Bounding box
- Stock volume
- Part volume
- Removed volume
- Solids count
- Faces count
- Edges count
- Vertices count
- Volume source

### Feature Candidate Detection

The app currently detects these candidate features from CadQuery face records:

| Candidate Feature | Current Status |
| --- | --- |
| Face milling | Implemented |
| Holes | Implemented |
| Large holes / boring | Implemented |
| Slots | Implemented |
| Through rectangular pocket/window | Implemented |
| Blind rectangular pocket (with floor face) | Implemented |

Candidate detection is not automatically used. It is shown to the user for review.

### Setup and Feature Review Page

A page exists named `5a. Setup & Feature Review`.

It shows:

- Stock summary
- Machine/material summary
- Current manual or accepted features
- Detected CAD feature candidates
- Validation flags
- Pre-flight checklist

It supports:

- Accepting detected candidates
- Adding accepted candidates to the feature list
- Preventing duplicate addition
- Warning when old/demo/manual features exist before accepting CAD candidates
- Clearing existing features before accepting CAD candidates

### Operation Planning

Accepted features can generate operation plans.

Current operation planning includes:

- Face milling
- Pilot drilling
- Drilling
- Boring
- Rough end mill
- Finish end mill
- Slot roughing and finishing
- Pocket roughing and finishing
- Bottom face milling moved to end as Setup 2 / flip operation

Improved operation notes:

- Top face milling is marked as the primary setup facing operation.
- Bottom face milling is marked as Setup 2 / flip required.
- Large bore operations warn to verify boring tool reach and minimum bore capability.
- Through pocket/window operations include notes for roughing and finishing internal walls.
- Slot roughing notes include multiple depth and radial passes.

### Tool Selection Improvements

- Pilot drill uses the smallest drill, not the closest drill to final bore size.
- End mill depth is treated as a soft preference, not a hard rejection.
- If no end mill satisfies full depth, the app chooses the largest suitable end mill and planning notes indicate multi-pass machining.

### Path-Length and Time Estimate Improvements

- Face milling path length uses a raster-style estimate, not perimeter.
- Slot roughing path length accounts for depth passes and radial passes.
- Slot finishing path uses a two-wall-pass estimate.
- Rapid movement time uses `mm / mm-per-minute = minutes`.
- Time estimates are now more believable.

### Export

The app can export:

- Draft CNC program
- Setup sheet
- CSV operation data

Generated CNC code is draft only and must be verified in CAM or a simulator before use.

## 5. Current Machine List Summary

| Machine Type | Machines Currently Included |
| --- | --- |
| VMC / CNC Milling | Ace Micromatic AMV 55, BFW Betas 500, Jyoti VMC 850, Mazak VCN 530C, Haas VF2, Siemens VMC 828D, MTAB MaxMill, HMT FN2 CNC Milling, Generic CNC Milling |
| CNC Turning | Ace Micromatic ATC 25, BFW TC 20, Jyoti DX 200, HMT Stallion 100, LMW LT2, Mazak QT Smart 200, Haas ST-20, Generic CNC Lathe |
| Turn-Mill | DMG MORI NLX 2500 |

## 6. Tested STEP Files

| STEP File | Finding |
| --- | --- |
| `01_plain_rectangular_block_100x60x30-Body.step` | Plain block detection works |
| `02_plate_4_through_holes_d10.step` | Through hole detection works |
| `03_plate_4_blind_holes_d10_depth15.step` | Blind hole detection works |
| `04_plate_mixed_holes_d6_d10_d20.step` | Mixed hole detection works |
| `05_plate_large_bore_d35_through.step` | Large bore detection works |
| `06_plate_4_large_bores_d35.step` | Multiple large bore detection works |
| `09_slotted_plate_single_center_slot.step` | Slot detection works |
| `13_rectangular_pocket_blind.step` | Sample behaves as through pocket/window because no floor face exists |
| `17_stepped_block_single_step.step` | Current sample is more like a side-profile/extruded part, not a proper top-milled step |
| `23_mixed_plate_holes_slot_pocket.step` | Mixed basic milling feature detection works |
| `25_vmc_job_plate_all_basic_features.step` | Basic VMC job feature mix works |
| `Flanges-Body.step` | Tested in prototype |
| `M03_vmc_blind_rectangular_pocket.step` | Blind pocket detection works — 1 Pocket candidate, confidence=medium, depth=12 mm |
| `test5slotted.step` | Tested in prototype |

Additional findings:

- Through rectangular pocket/window detection works.
- Blind rectangular pocket detection works (floor face confirmed, depth from top to floor).
- Face milling false positives were reduced.
- A proper top-milled step/shoulder sample is still required.

## 7. Known Gaps

### VMC / Milling Gaps

| Gap | Status |
| --- | --- |
| True blind rectangular pocket detection with floor face | Implemented ✓ |
| Step/shoulder detection | Not implemented |
| Chamfer detection | Not implemented |
| Better pocket G-code strategy | Not implemented |
| Better setup-change handling | Not implemented |
| Better roughing/finishing sequence for pockets | Not implemented |
| Better finishing tool choice | Not implemented |
| Better boring tool capability validation | Not implemented |
| Better complex/freeform surface detection | Not implemented |
| Better visual display of detected features | Not implemented |

### Turning / Lathe Gaps

| Gap | Status |
| --- | --- |
| Axisymmetric turned part detection | Not implemented |
| OD turning region detection | Not implemented |
| Shoulder detection | Not implemented |
| Groove detection | Not implemented |
| Taper detection | Not implemented |
| Turning operation planning | Not implemented |
| Lathe-specific tool selection | Not implemented |
| Lathe-style draft code/output | Not implemented |

### Turn-Mill Gaps

| Gap | Status |
| --- | --- |
| Mixed turning and milling geometry detection | Not implemented |
| Cross-hole detection on shafts | Not implemented |
| Mill-turn operation planning | Not implemented |
| Setup/orientation logic for turn-mill | Not implemented |

### Deployment Gaps

| Gap | Status |
| --- | --- |
| CadQuery support on Streamlit Cloud | Risk / unresolved |
| Production server-side deployment plan | Needed |
| Local/offline packaging for SME workshops | Needed |
| User/auth strategy for demo/prototype | Needed |
| Sample test matrix | Needed |

## 8. Immediate Priorities

Do not move to CNC turning yet.

Current priority: stabilize the VMC / CNC milling workflow first.

Priority order:

1. True blind rectangular pocket detection.
2. Step/shoulder detection using a proper top-milled step sample.
3. Chamfer detection.
4. VMC operation planning refinement.
5. Estimation refinement.
6. Test matrix.
7. Demo readiness.
8. Turning/lathe phase later.

## 9. 2-Week BMAD Backlog Focus

Assumption: 2-3 hours per day.

### Epic 1: True Blind Rectangular Pocket Detection

Goal: Detect rectangular pockets with a floor face and distinguish them from through windows.

| Story | Acceptance Criteria | Test Cases |
| --- | --- | --- |
| Detect floor-backed rectangular pockets | Candidate is created only when a pocket has side walls and a valid floor face; depth is calculated from top plane to floor; through windows are not classified as blind pockets | `M03_vmc_blind_rectangular_pocket.step`, `M04_vmc_through_pocket_window.step`, `13_rectangular_pocket_blind.step` |
| Add review metadata for blind pockets | Review page shows pocket length, width, depth, floor status, and confidence/validation flags | New blind pocket sample and existing through pocket sample |
| Route accepted blind pockets to operation planning | Accepted blind pocket creates roughing and finishing operations with multi-depth notes | Blind pocket accepted from review page |

### Epic 2: Step and Shoulder Detection

Goal: Detect top-milled step/shoulder geometry after receiving a proper test sample.

| Story | Acceptance Criteria | Test Cases |
| --- | --- | --- |
| Detect top-milled step | Candidate is created for a lowered top region with a clear vertical shoulder wall | `M06_vmc_top_milled_step_shoulder.step` |
| Avoid side-profile false positives | Side-profile/extruded samples are not incorrectly classified as top-milled steps | `17_stepped_block_single_step.step` |
| Add step operation plan | Accepted step creates roughing/facing operation notes suitable for VMC milling | `M06_vmc_top_milled_step_shoulder.step` |

### Epic 3: Chamfer Detection

Goal: Detect simple top-edge chamfers and route them to review.

| Story | Acceptance Criteria | Test Cases |
| --- | --- | --- |
| Detect top outer-edge chamfers | Chamfer candidates identify approximate chamfer size and edge count | `M07_vmc_chamfered_plate.step` |
| Avoid classifying normal vertical faces as chamfers | Vertical walls and pocket walls are not marked as chamfers | Basic plate and pocket samples |
| Add chamfer operation note | Accepted chamfer creates a chamfering/deburring operation suggestion | `M07_vmc_chamfered_plate.step` |

### Epic 4: VMC Operation Planning and Estimation Refinement

Goal: Improve planning credibility for milling jobs before demo.

| Story | Acceptance Criteria | Test Cases |
| --- | --- | --- |
| Refine blind pocket roughing sequence | Pocket operation includes roughing, depth passes, finishing walls, and floor cleanup notes | `M03_vmc_blind_rectangular_pocket.step` |
| Improve boring validation | Large bore operations show clearer boring tool capability warnings | `M05_vmc_large_bore_plate.step` |
| Improve estimate transparency | Operation time notes show assumptions for depth passes, radial passes, and rapid movement | Slot, bore, pocket samples |

### Epic 5: Test Matrix and Demo Readiness

Goal: Make the VMC prototype easier to validate and demonstrate.

| Story | Acceptance Criteria | Test Cases |
| --- | --- | --- |
| Create VMC test matrix | Matrix lists sample file, expected detected features, expected operations, and pass/fail notes | M01-M07 samples |
| Confirm existing regression samples | Existing tested STEP files still produce expected candidates | Current tested files |
| Prepare demo workflow | Demo sequence covers upload, parse summary, candidate review, operation plan, estimate, and export | `M05` or `M03` plus one mixed-feature sample |

### Suggested 2-Week Plan

| Day Range | Focus |
| --- | --- |
| Days 1-2 | Implement and test true blind pocket geometry rules |
| Days 3-4 | Wire blind pocket candidates into review page and operation planning |
| Days 5-6 | Add regression checks for through window vs blind pocket |
| Days 7-8 | Implement first step/shoulder detection pass using proper sample |
| Days 9-10 | Implement first chamfer detection pass |
| Days 11-12 | Refine pocket planning and time-estimate notes |
| Days 13-14 | Build test matrix, run demo path, document remaining gaps |

### Risks

| Risk | Mitigation |
| --- | --- |
| STEP geometry varies by CAD exporter | Use candidate confidence and require user approval |
| Blind pocket and through window classification may be fragile | Require floor-face validation and regression tests |
| Step detection may produce false positives | Use proper top-milled sample and reject side-profile cases |
| Chamfer detection may confuse angled design faces | Start with simple top outer-edge chamfers only |
| Time estimates can be misread as guaranteed machining time | Keep estimates explicitly marked as planning estimates |
| Draft G-code may be mistaken for production-ready code | Maintain visible safety disclaimers and verification requirements |

## 10. Safety and Disclaimer Requirements

The app must always communicate:

- CNC code is draft only.
- Generated code must be verified in CAM or a simulator.
- Detected features are suggestions.
- A user or machinist must approve detected features.
- Tool selection must be verified.
- Time estimates are planning estimates.

The product must never present output as production-ready CNC code.

Non-goals for the current phase:

- Full CAM replacement
- Collision detection
- True toolpath simulation
- Fixture planning
- 5-axis machining
- Production-safe G-code
- Controller-perfect post-processing
- Automatic machining without user review
- LLM/API-based geometry interpretation

## 11. Next Development Story: True Blind Rectangular Pocket Detection

### Story

As a CNC quotation engineer or machinist, I want the app to detect a true blind rectangular pocket with a clear floor face so that I can distinguish it from a through pocket/window and generate a more realistic VMC process plan.

### Acceptance Criteria

1. Given `M03_vmc_blind_rectangular_pocket.step`, the app identifies one blind rectangular pocket candidate.
2. The candidate includes approximate length, width, depth, top opening, side walls, and floor-face evidence.
3. Given `M04_vmc_through_pocket_window.step`, the app identifies a through pocket/window candidate, not a blind pocket.
4. Given the existing `13_rectangular_pocket_blind.step`, the app does not misclassify it as a true blind pocket if no floor face exists.
5. The Setup & Feature Review page displays the blind pocket candidate for user review.
6. Accepting the candidate adds one feature and prevents duplicate addition.
7. Operation planning creates roughing and finishing operations for the accepted blind pocket.
8. Planning notes explain multi-depth machining, wall finishing, and floor cleanup.
9. Safety disclaimers remain visible for detected features, tool selection, time estimates, and draft CNC code.

### Suggested Test Cases

| Test | Expected Result |
| --- | --- |
| Upload `M03_vmc_blind_rectangular_pocket.step` | One blind pocket candidate detected |
| Upload `M04_vmc_through_pocket_window.step` | Through pocket/window detected; no blind pocket classification |
| Upload `13_rectangular_pocket_blind.step` | No true blind pocket if floor face is absent |
| Accept blind pocket candidate | Feature list adds one accepted pocket |
| Accept same candidate twice | Duplicate is prevented |
| Generate operations | Pocket roughing and finishing operations are created |
| Export outputs | Setup sheet and draft CNC output retain safety disclaimers |
