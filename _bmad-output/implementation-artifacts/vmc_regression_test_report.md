# VMC Feature Detection Regression Report

**Date:** 2026-07-07  
**Branch:** v2-feature-review-engine  
**Options:** `(none)`  

## Summary

| Metric | Count |
|--------|-------|
| Total entries | 30 |
| PASS | 22 |
| FAIL | 8 |
| MISSING | 0 |
| ERROR | 0 |

## Per-File Results

| File | Status | Expected | Actual | Notes |
|------|--------|----------|--------|-------|
| `01_plain_rectangular_block_100x60x30-Body.step` | **PASS** | Face milling=2 | Face milling=2 | Plain block — face milling only |
| `02_plate_4_through_holes_d10.step` | **PASS** | Face milling=2, Hole=4 | Face milling=2, Hole=4 | 4 through holes Ø10 |
| `03_plate_4_blind_holes_d10_depth15.step` | **PASS** | Face milling=2, Hole=4 | Face milling=2, Hole=4 | 4 blind holes Ø10 depth 15 mm |
| `04_plate_mixed_holes_d6_d10_d20.step` | **PASS** | Face milling=2, Hole=3 | Face milling=2, Hole=3 | Mixed holes Ø6/10/20; Ø20 detected as Large hole / boring |
| `05_plate_large_bore_d35_through.step` | **PASS** | Face milling=2, Large hole / boring=1 | Face milling=2, Large hole / boring=1 | Single large bore Ø35 through |
| `06_plate_4_large_bores_d35.step` | **PASS** | Face milling=2, Large hole / boring=4 | Face milling=2, Large hole / boring=4 | 4 large bores Ø35 |
| `09_slotted_plate_single_center_slot.step` | **PASS** | Face milling=2, Slot=1 | Face milling=2, Slot=1 | Single center slot |
| `13_rectangular_pocket_blind.step` | **PASS** | Face milling=2, Pocket=1 | Face milling=2, Pocket=1 | Through pocket/window — no floor face, emitted as Pocket confidence=low |
| `17_stepped_block_single_step.step` | **PASS** | Face milling=2, Step=1 | Face milling=2, Step=1 | Legacy sample, PRD-documented as side-profile/extruded geometry rather than a representative top-milled step (superseded for that purpose by 17b). Kept here only as a stability sanity check: tall block (120x90x500mm), one Z-direction Step, depth=35mm, confidence=medium, no crash or false positives. |
| `17b_top_milled_step_shoulder-Body.step` | **PASS** | Face milling=2, Step=1 | Face milling=2, Step=1 | Official step/shoulder regression sample — Y-direction shoulder step; depth=12 mm (replaces M06) |
| `23_mixed_plate_holes_slot_pocket.step` | **PASS** | Face milling=2, Pocket=2, Slot=2 | Face milling=2, Pocket=2, Slot=2 | Mixed: face mill + 2 slots + 2 pockets |
| `25_vmc_job_plate_all_basic_features.step` | **PASS** | Chamfer=1, Face milling=2, Large hole / boring=1, Slot=2 | Chamfer=1, Face milling=2, Large hole / boring=1, Slot=2 | All basic VMC features: face mill + slot + large bore + top edge chamfer (6 faces) |
| `M01_vmc_basic_plate_holes.step` | **PASS** | Face milling=2, Hole=4 | Face milling=2, Hole=4 | Basic plate with 4 holes |
| `M02_vmc_slot_plate.step` | **PASS** | Face milling=2, Slot=1 | Face milling=2, Slot=1 | Plate with single slot (flat-ended, no cylinder faces) — detected via Section D flat-slot branch, AR=4.0 >= 3.5, confidence=medium. |
| `M03_vmc_blind_rectangular_pocket.step` | **PASS** | Face milling=2, Pocket=1 | Face milling=2, Pocket=1 | Blind pocket with floor face; depth=12 mm, confidence=medium |
| `M04_vmc_through_pocket_window.step` | **PASS** | Face milling=2, Pocket=1 | Face milling=2, Pocket=1 | Through pocket/window; no floor, confidence=low |
| `M05_vmc_large_bore_plate.step` | **PASS** | Face milling=2, Hole=2, Large hole / boring=1 | Face milling=2, Hole=2, Large hole / boring=1 | Large bore plate with pilot holes |
| `M07_vmc_chamfered_plate.step` | **PASS** | Chamfer=1, Face milling=2, Hole=4 | Chamfer=1, Face milling=2, Hole=4 | Chamfered plate; 4 angled PLANE faces on top edges detected as Chamfer (Section F), ~2.0mm |
| `test5slotted.step` | **PASS** | Face milling=2, Large hole / boring=4, Slot=1 | Face milling=2, Large hole / boring=4, Slot=1 | 5-feature slotted plate with large bores |
| `SF11_bottom_chamfer_plate.step` | **PASS** | Chamfer=1, Face milling=2 | Chamfer=1, Face milling=2 | Epic 12.4 SF-11: 80x120x25 block with 2mm chamfer on all bottom edges only. Validates bottom-edge chamfer detection (Section F nz<0 branch). Chamfer setup=Bottom, depth=2.0. |
| `SF14_top_fillet_no_chamfer.step` | **PASS** | Face milling=2, Hole=2 | Face milling=2, Hole=2 | Epic 12.4 SF-14: 80x120x25 block with 3mm fillet on all top edges. Fillets are TOROIDAL faces — Section F must NOT emit a Chamfer candidate. After the Section C lz>=8mm filter (Tenon Slot fix), toroidal fillet faces (lz=3mm) are excluded from slot detection and surface as Hole=2 instead — still a known TOROIDAL false positive tracked in Epic F3. Key assertion: Chamfer=0. |
| `SF13_variable_chamfer_top_bottom.step` | **PASS** | Chamfer=2, Face milling=2 | Chamfer=2, Face milling=2 | Epic 12.4 SF-13: 100x80x30 block with 3mm chamfer top edges and 1mm chamfer bottom edges. Validates that top and bottom chamfers are emitted as SEPARATE candidates (Chamfer=2) with correct setup labels and depths, never collapsed into one. |
| `T04_plain_cylinder_d60_l120.step` | **FAIL** | Face milling=2 | Face milling=2, Large hole / boring=1 | Epic 19 T04: plain cylinder D=60 L=120. Axisymmetric baseline — facing + OD only. Key assertion: is_axisymmetric=true, no milled features detected. |
| `T05_undercut_shaft.step` | **FAIL** | Face milling=2 | Face milling=1, Large hole / boring=3 | Epic 19 T05: stepped shaft with undercut/thread-relief groove between two shoulders. Validates undercut flagging (Story 19-5). is_axisymmetric=true. |
| `T06_short_disc_hub_d120_l20.step` | **FAIL** | Face milling=2 | Face milling=2, Large hole / boring=1 | Epic 19 T06: short disc/hub D=120 L=20 (L:D=0.17). Facing-dominant turned part. is_axisymmetric=true. |
| `T07_flange_bore_boltholes.step` | **FAIL** | Face milling=2, Hole=6 | Face milling=2, Hole=6, Large hole / boring=2 | Epic 19 T07: flange OD=150 with central through bore D=40 and 6 bolt holes on PCD=100. Mixed lathe (OD + bore) + drilling. is_axisymmetric=true. |
| `T08_shaft_internal_groove.step` | **FAIL** | Face milling=2 | Face milling=2, Hole=1, Large hole / boring=1 | Epic 19 T08: shaft with through bore containing an internal annular groove (ID grooving). Validates groove detection inside bore (Story 19-3). is_axisymmetric=true. |
| `T09_round_milled_part_not_lathe.step` | **FAIL** | Face milling=2, Pocket=1 | Face milling=2, Large hole / boring=1 | Epic 19 T09: FALSE-POSITIVE TRAP — round cylindrical stock with a rectangular pocket milled on top. Must NOT be classified as a turned part. Key assertion: is_axisymmetric=false (or lathe=false). Pocket=1. |
| `T10_long_shaft_ld7_d40_l300.step` | **FAIL** | Face milling=2 | Face milling=2, Large hole / boring=1 | Epic 19 T10: long shaft D=40 L=300 (L:D=7.5). Must trigger tailstock/steady-rest flag in operation planning (Story 19-6). is_axisymmetric=true. |
| `T11_shaft_thread_region.step` | **FAIL** | Face milling=2 | Face milling=2, Large hole / boring=3 | Epic 19 T11: stepped shaft with a narrower-diameter region representing a thread zone. Must not crash. Thread region should be flagged as unrecognised or 'Thread — verify manually' (Story 19-5). is_axisymmetric=true. |

## Uncovered STEP Files

These files exist in `test_samples/` but have no entry in `feature_detection_expectations.json`:

- `3100171001_01 SLIDE BASE-1812 ( FOR TOOL LOADER ).STEP`
- `Flanges-Body.step`
- `T01_lathe_stepped_shaft.step`
- `T02_lathe_shaft_with_groove.step`
- `T03_lathe_tapered_shaft.step`
- `TM01_turnmill_shaft_with_cross_hole.step`
- `X01_complex_freeform_surface_part.step`

## Failure Details


### T04_plain_cylinder_d60_l120.step — FAIL

- **Expected:** Face milling=2
- **Actual:** Face milling=2, Large hole / boring=1
- **Notes:** Epic 19 T04: plain cylinder D=60 L=120. Axisymmetric baseline — facing + OD only. Key assertion: is_axisymmetric=true, no milled features detected.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-ef40506fa9004f98 | Face milling | Face milling — top surface | high |
| FACE-2de48ce935da64f4 | Face milling | Face milling — bottom surface | high |
| BORE-0985596c7f3ac7b6 | Large hole / boring | Large hole / boring Ø60.00 mm | medium |

### T05_undercut_shaft.step — FAIL

- **Expected:** Face milling=2
- **Actual:** Face milling=1, Large hole / boring=3
- **Notes:** Epic 19 T05: stepped shaft with undercut/thread-relief groove between two shoulders. Validates undercut flagging (Story 19-5). is_axisymmetric=true.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-1eb3950876665a6d | Face milling | Face milling — bottom surface | high |
| BORE-30cdfbdc23d00e17 | Large hole / boring | Large hole / boring Ø50.00 mm | medium |
| BORE-d760e6dd88225da3 | Large hole / boring | Large hole / boring Ø38.00 mm | medium |
| BORE-995fba1efb59a0a4 | Large hole / boring | Large hole / boring Ø30.00 mm | medium |

### T06_short_disc_hub_d120_l20.step — FAIL

- **Expected:** Face milling=2
- **Actual:** Face milling=2, Large hole / boring=1
- **Notes:** Epic 19 T06: short disc/hub D=120 L=20 (L:D=0.17). Facing-dominant turned part. is_axisymmetric=true.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-cad3d9ce04a5ce00 | Face milling | Face milling — top surface | high |
| FACE-b8f3ee620aa66691 | Face milling | Face milling — bottom surface | high |
| BORE-d3fe53d313ce3142 | Large hole / boring | Large hole / boring Ø120.00 mm | medium |

### T07_flange_bore_boltholes.step — FAIL

- **Expected:** Face milling=2, Hole=6
- **Actual:** Face milling=2, Hole=6, Large hole / boring=2
- **Notes:** Epic 19 T07: flange OD=150 with central through bore D=40 and 6 bolt holes on PCD=100. Mixed lathe (OD + bore) + drilling. is_axisymmetric=true.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-d5444147324018e2 | Face milling | Face milling — top surface | high |
| FACE-3369315c46f37c3c | Face milling | Face milling — bottom surface | high |
| BORE-99b1e8ad9af8d821 | Large hole / boring | Large hole / boring Ø150.00 mm | medium |
| HOLE-618c7b9a826ab224 | Hole | Hole Ø10.00 mm | medium |
| HOLE-fa21107dfea19f8d | Hole | Hole Ø10.00 mm | medium |
| BORE-89ba526ecf43f2fc | Large hole / boring | Large hole / boring Ø40.00 mm | medium |
| HOLE-2e69236e97e61c64 | Hole | Hole Ø10.00 mm | medium |
| HOLE-aaafd628b479a766 | Hole | Hole Ø10.00 mm | medium |
| HOLE-d929cc946ae65255 | Hole | Hole Ø10.00 mm | medium |
| HOLE-f86c1a8a12feb85b | Hole | Hole Ø10.00 mm | medium |

### T08_shaft_internal_groove.step — FAIL

- **Expected:** Face milling=2
- **Actual:** Face milling=2, Hole=1, Large hole / boring=1
- **Notes:** Epic 19 T08: shaft with through bore containing an internal annular groove (ID grooving). Validates groove detection inside bore (Story 19-3). is_axisymmetric=true.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-6ca492a667de72ee | Face milling | Face milling — top surface | high |
| FACE-f67661d30fe84224 | Face milling | Face milling — bottom surface | high |
| BORE-8552a08bbe800fea | Large hole / boring | Large hole / boring Ø60.00 mm | medium |
| HOLE-3b305041c445e5be | Hole | Hole Ø20.00 mm | medium |

### T09_round_milled_part_not_lathe.step — FAIL

- **Expected:** Face milling=2, Pocket=1
- **Actual:** Face milling=2, Large hole / boring=1
- **Notes:** Epic 19 T09: FALSE-POSITIVE TRAP — round cylindrical stock with a rectangular pocket milled on top. Must NOT be classified as a turned part. Key assertion: is_axisymmetric=false (or lathe=false). Pocket=1.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-14f74d608263f401 | Face milling | Face milling — top surface | high |
| FACE-a1cacad5d3495b03 | Face milling | Face milling — bottom surface | high |
| BORE-5f05c7aa8a947220 | Large hole / boring | Large hole / boring Ø100.00 mm | medium |

### T10_long_shaft_ld7_d40_l300.step — FAIL

- **Expected:** Face milling=2
- **Actual:** Face milling=2, Large hole / boring=1
- **Notes:** Epic 19 T10: long shaft D=40 L=300 (L:D=7.5). Must trigger tailstock/steady-rest flag in operation planning (Story 19-6). is_axisymmetric=true.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-9024b6fdacc37655 | Face milling | Face milling — top surface | high |
| FACE-d42f21cf961662a5 | Face milling | Face milling — bottom surface | high |
| BORE-9de6f82b325d51ac | Large hole / boring | Large hole / boring Ø40.00 mm | medium |

### T11_shaft_thread_region.step — FAIL

- **Expected:** Face milling=2
- **Actual:** Face milling=2, Large hole / boring=3
- **Notes:** Epic 19 T11: stepped shaft with a narrower-diameter region representing a thread zone. Must not crash. Thread region should be flagged as unrecognised or 'Thread — verify manually' (Story 19-5). is_axisymmetric=true.

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| FACE-52b1f4d8048f82e0 | Face milling | Face milling — top surface | high |
| FACE-eefb32e42c526958 | Face milling | Face milling — bottom surface | high |
| BORE-29252ec40f083c7a | Large hole / boring | Large hole / boring Ø50.00 mm | medium |
| BORE-21036ac2c6af2490 | Large hole / boring | Large hole / boring Ø44.00 mm | medium |
| BORE-9dae09fab3751056 | Large hole / boring | Large hole / boring Ø40.00 mm | medium |
