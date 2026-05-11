# VMC Feature Detection Regression Report

**Date:** 2026-05-12  
**Branch:** v2-feature-review-engine  
**Options:** `--allow-missing`  

## Summary

| Metric | Count |
|--------|-------|
| Total entries | 19 |
| PASS | 17 |
| FAIL | 1 |
| MISSING | 1 |
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
| `17b_top_milled_step_shoulder-Body.step` | **PASS** | Face milling=2, Step=1 | Face milling=2, Step=1 | Y-direction shoulder step; depth=12 mm |
| `23_mixed_plate_holes_slot_pocket.step` | **PASS** | Face milling=2, Pocket=2, Slot=2 | Face milling=2, Pocket=2, Slot=2 | Mixed: face mill + 2 slots + 2 pockets |
| `25_vmc_job_plate_all_basic_features.step` | **PASS** | Face milling=2, Large hole / boring=1, Slot=2 | Face milling=2, Large hole / boring=1, Slot=2 | All basic VMC features: face mill + slot + large bore |
| `M01_vmc_basic_plate_holes.step` | **PASS** | Face milling=2, Hole=4 | Face milling=2, Hole=4 | Basic plate with 4 holes |
| `M02_vmc_slot_plate.step` | **FAIL** | Face milling=2, Slot=1 | Face milling=2, Pocket=1 | Plate with single slot |
| `M03_vmc_blind_rectangular_pocket.step` | **PASS** | Face milling=2, Pocket=1 | Face milling=2, Pocket=1 | Blind pocket with floor face; depth=12 mm, confidence=medium |
| `M04_vmc_through_pocket_window.step` | **PASS** | Face milling=2, Pocket=1 | Face milling=2, Pocket=1 | Through pocket/window; no floor, confidence=low |
| `M05_vmc_large_bore_plate.step` | **PASS** | Face milling=2, Hole=2, Large hole / boring=1 | Face milling=2, Hole=2, Large hole / boring=1 | Large bore plate with pilot holes |
| `M06_vmc_top_milled_step_shoulder.step` | **MISSING** | Face milling=2, Step=1 | (none) | Top-milled Z-direction step; file not yet created |
| `M07_vmc_chamfered_plate.step` | **PASS** | Face milling=2, Hole=4 | Face milling=2, Hole=4 | Chamfered plate; chamfer not yet detected, only holes expected |
| `test5slotted.step` | **PASS** | Face milling=2, Large hole / boring=4, Slot=1 | Face milling=2, Large hole / boring=4, Slot=1 | 5-feature slotted plate with large bores |

## Uncovered STEP Files

These files exist in `test_samples/` but have no entry in `feature_detection_expectations.json`:

- `17_stepped_block_single_step.step`
- `Flanges-Body.step`
- `T01_lathe_stepped_shaft.step`
- `T02_lathe_shaft_with_groove.step`
- `T03_lathe_tapered_shaft.step`
- `TM01_turnmill_shaft_with_cross_hole.step`
- `X01_complex_freeform_surface_part.step`

## Failure Details


### M02_vmc_slot_plate.step — FAIL

- **Expected:** Face milling=2, Slot=1
- **Actual:** Face milling=2, Pocket=1
- **Notes:** Plate with single slot

Candidates detected:

| ID | Type | Name | Confidence |
|----|------|------|------------|
| F001 | Face milling | Face milling — top surface | high |
| F002 | Face milling | Face milling — bottom surface | high |
| P001 | Pocket | Through pocket 80.0x20.0 mm | low |
