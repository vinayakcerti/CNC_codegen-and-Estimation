# Flat-Ended Slot Detection — Investigation and Analysis

**Date:** 2026-05-12  
**Branch:** v2-feature-review-engine  
**Trigger:** M02_vmc_slot_plate.step fails regression — expected Slot=1, actual Pocket=1  
**Scope:** Analysis only. No implementation changes in this document.

---

## 1. Executive Summary

`M02_vmc_slot_plate.step` is a rectangular plate with a single through-slot milled in the Y direction. The slot has flat (PLANE) end faces — no curved cylinder end caps. The current slot detector (Section C) requires CYLINDER faces to detect slots, so M02 is invisible to it. Section D (pocket detector) then claims the four flat walls and emits "Through pocket 80.0×20.0 mm, confidence=low".

The fix is to detect flat-ended slots inside Section D: when paired internal walls have a high aspect ratio (≥ 3.5) and no floor face, emit as `feature_type="Slot"` rather than `"Pocket"`. This requires a one-branch addition to existing Section D logic and no new data structures.

---

## 2. M02 Face Record Summary

**File:** `test_samples/M02_vmc_slot_plate.step`  
**Parser:** CadQuery 2.7.0  
**Total faces:** 10 (all PLANE — zero CYLINDER faces)  
**Part dimensions:** 120 mm (X) × 200 mm (Y) × 30 mm (Z)

| # | geom_type | normal dir | center (x, y, z) | area mm² | bbox spans (lx, ly, lz) | Role |
|---|-----------|------------|-----------------|----------|------------------------|------|
| 0 | PLANE | −X | (−60, 0, 15) | 6000 | 0, 200, 30 | Outer left wall |
| 1 | PLANE | −Y | (0, −100, 15) | 3600 | 120, 0, 30 | Outer front wall |
| 2 | PLANE | +X | (60, 0, 15) | 6000 | 0, 200, 30 | Outer right wall |
| 3 | PLANE | +Y | (0, 100, 15) | 3600 | 120, 0, 30 | Outer back wall |
| **4** | **PLANE** | **+X** | **(−10, 0, 15)** | **2400** | **0, 80, 30** | **Slot side wall (left)** |
| **5** | **PLANE** | **+Y** | **(0, −40, 15)** | **600** | **20, 0, 30** | **Slot end wall (front)** |
| **6** | **PLANE** | **−X** | **(10, 0, 15)** | **2400** | **0, 80, 30** | **Slot side wall (right)** |
| **7** | **PLANE** | **−Y** | **(0, 40, 15)** | **600** | **20, 0, 30** | **Slot end wall (rear)** |
| 8 | PLANE | −Z | (0, 0, 0) | 22400 | 120, 200, 0 | Bottom face |
| 9 | PLANE | +Z | (0, 0, 30) | 22400 | 120, 200, 0 | Top face |

**Slot geometry (from face records):**
- Slot axis: Y direction
- Slot length (Y gap between end walls): 40 − (−40) = **80 mm**
- Slot width (X gap between side walls): 10 − (−10) = **20 mm**
- Slot depth (Z span of side walls): **30 mm** (full part height = through slot)
- Aspect ratio: 80 / 20 = **4.0**
- End wall area: 600 mm² each (= 20 × 30 mm)
- Side wall area: 2400 mm² each (= 80 × 30 mm)
- Side/end area ratio: 4.0

---

## 3. Why Section C (Slot Detector) Misses M02

Section C's algorithm:
1. Collects all CYLINDER faces from face_records.
2. Identifies non-circular cylinder faces (bbox_lx ≠ bbox_ly beyond 15%) as slot-end walls.
3. Pairs two such cylinders with matching radius and axis alignment.
4. Emits a Slot candidate from the paired cylinder ends.

**M02 has zero CYLINDER faces.** The flat end walls (#5, #7) are PLANE faces, not CYLINDER faces. Section C's cylinder collection is empty; no slots are detected.

This is correct behavior for rounded-end slots (the intended scope of Section C). The gap is that flat-ended rectangular slots — produced by CAD tools that don't add fillet radii at slot ends, or by end-mill paths that stop flat — are a distinct and common geometry that Section C does not cover.

---

## 4. Why Section D (Pocket Detector) Captures M02 as Pocket

Section D's algorithm for pairing opposing internal PLANE walls:

1. Buckets PLANE faces by normal direction (±X, ±Y).
2. Pairs opposing +X/−X faces that are interior (left wall sits left of right wall) and within 88% of part span.
3. Pairs opposing +Y/−Y faces similarly.
4. For each (X-pair, Y-pair) combination:
   a. Computes gap dimensions: `_px` = X gap, `_py` = Y gap.
   b. Checks `max(_px, _py) / min(_px, _py) < _P_MAX_ASPECT` (currently 8.0) — rejects very elongated pairs as slot territory.
   c. Runs CYLINDER guard: if any CYLINDER face is centred within the pocket XY region → skip (already a Section C slot).
   d. Searches for a floor face at intermediate Z → blind vs through classification.
   e. Emits Pocket candidate.

For M02:
- X-pair: face #4 (+X, cx=−10) paired with face #6 (−X, cx=10) → gap = 20 mm ✓
- Y-pair: face #5 (+Y, cy=−40) paired with face #7 (−Y, cy=40) → gap = 80 mm ✓
- AR = max(80,20) / min(80,20) = 4.0 < 8.0 → **passes AR guard** (threshold too high)
- No CYLINDER faces → CYLINDER guard passes
- No floor face at intermediate Z → confidence = low, "Through pocket 80.0×20.0 mm"

**The failure mode is that `_P_MAX_ASPECT = 8.0` is too permissive for distinguishing slots from pockets.** A flat-ended slot with AR = 4.0 comfortably passes the current threshold.

---

## 5. Distinguishing Flat-Ended Slot from Rectangular Through Pocket

### 5.1 Aspect Ratio Analysis — All Existing Samples

| Sample | Feature | Dimensions (length × width) | AR = L/W |
|--------|---------|------------------------------|----------|
| M03 blind pocket | Pocket | 70.0 × 35.0 mm | **2.00** |
| M04 through pocket | Pocket | 70.0 × 35.0 mm | **2.00** |
| 13 through pocket | Pocket | 80.0 × 30.0 mm | **2.67** |
| 23-P001 through pocket | Pocket | 90.0 × 40.0 mm | **2.25** |
| 23-P002 through pocket | Pocket | 90.0 × 40.0 mm | **2.25** |
| **M02 flat-ended slot** | **Slot (target)** | **80.0 × 20.0 mm** | **4.00** |
| 23-S001 rounded slot | Slot | 159.33 × 37.50 mm | 4.25 |
| 23-S002 rounded slot | Slot | 115.90 × 15.90 mm | 7.29 |

**Observation:**
- Maximum pocket AR in all current passing samples: **2.67** (sample 13)
- Minimum slot AR in all current samples: **4.00** (M02 target)
- Gap between highest pocket AR and lowest slot AR: **1.33**
- Midpoint of gap: **3.33**
- Recommended threshold: **3.5** (places 0.83 safety margin above highest pocket, 0.5 below lowest slot)

### 5.2 Secondary Discriminator — End Wall Area Ratio

For M02:
- Side wall area: 2400 mm²
- End wall area: 600 mm²
- Ratio side/end: 4.0 (same as AR, because all walls have equal height)

This ratio would be an alternative or confirming discriminator: if side walls are ≥ 3× larger in area than end walls → slot-like geometry. However, this is redundant with AR when all walls have the same Z span, so AR alone is sufficient as the primary discriminator.

### 5.3 Why No CYLINDER Guard Is Needed

Section D already has a CYLINDER guard: "if any CYLINDER face is centred within the pocket XY region → skip". This guard was designed to let rounded-end slots (Section C) take priority. For flat-ended slots, there are no CYLINDER faces, so the guard is irrelevant — it won't fire for M02. The flat-ended slot classification decision is purely based on AR.

---

## 6. Proposed Heuristic

### Primary approach: Classify inside Section D based on AR

After Section D determines that a paired-wall region has no floor face (through geometry), check the aspect ratio:

```
if (no floor face) AND (AR ≥ _FLAT_SLOT_MIN_AR):
    feature_type = "Slot"
    feature_name = "Flat-ended slot {length}×{width} mm"
    candidate_id = S-series (shared with Section C rounded-slot counter)
    confidence   = "medium"   # all 4 walls found; shape is unambiguous
    detection_source = "flat_ended_slot_walls"
else:
    feature_type = "Pocket"
    feature_name = "Through pocket …"
    candidate_id = P-series
    confidence   = "low"
```

Where `_FLAT_SLOT_MIN_AR = 3.5`.

### Alternative approach: Add dedicated Section C-flat before Section D

A separate sub-section after Section C could scan for paired side walls + end walls with high AR, mark the face indices in a `_flat_slot_used` set, then union that set into `_used_p_walls` before Section D's loop. Section D would never see those walls.

**Recommendation: Use the Section D branch approach.** It is more surgical — the wall-pairing and XY gap computation is already complete at that point, making the AR check a one-line condition. A separate section would duplicate all the wall-pairing logic.

---

## 7. Guard Analysis and False Positive Risks

### Guard 1 — AR threshold (new)
`max(px, py) / min(px, py) >= 3.5`
- Risk: a valid wide rectangular pocket with AR = 3.5–4.0 would be misclassified as a slot.
- Mitigation: All current test pocket samples have AR ≤ 2.67, leaving a large safety margin. The threshold can be tuned per future evidence.

### Guard 2 — No floor face (existing)
The flat-ended slot classification only applies when `_floor_face is None`. A blind pocket (floor face found) is never reclassified as a slot.
- Risk: zero. A flat-ended BLIND slot (open on one end, closed on the other with a floor) would have a floor face and would be emitted as a blind Pocket, which is arguably correct — it's a closed pocket feature, not a through slot.

### Guard 3 — CYLINDER guard (existing, unchanged)
If CYLINDER faces are present within the region, Section D already skips it entirely (Section C handles those). The flat-slot classification is therefore always for zero-cylinder geometry.

### Guard 4 — _P_OUTER_FRAC = 0.88 (existing)
Wall pairs whose gap exceeds 88% of the part span in that axis are excluded. This prevents an outer-wall pairing from being classified as a slot.
- Risk: a very long through-slot spanning more than 88% of the part Y dimension would be missed. This is acceptable — such wide through-slots would look like face milling from above.

### Guard 5 — _P_MAX_ASPECT = 8.0 (existing, unchanged)
Currently excludes pairs with AR ≥ 8.0 from pocket detection. Since any AR ≥ 3.5 now takes the flat-slot path, pairs with AR in [3.5, 8.0) become slots, and pairs with AR ≥ 8.0 remain excluded (neither pocket nor slot). The 8.0 upper guard remains as a sanity ceiling for extreme aspect ratios.

### False positive scenario 1 — Very elongated through pocket
A designer draws a 200mm × 50mm through pocket (AR=4.0). With the proposed rule, this would be emitted as a slot rather than a pocket. The user would see "Flat-ended slot 200×50 mm" instead of "Through pocket 200×50 mm". The operation plan (slotting vs pocket roughing/finishing) would differ. **Mitigation:** This is a judgment call best left to user review. The candidate confidence is "medium" and the user can override on the review page. The AR=3.5 threshold minimises this risk for typical workshop pocket dimensions.

### False positive scenario 2 — Step geometry already consumed by Section E
Section E (step detection) uses `_step_excl = set(_used_p_walls) | _pocket_floor_indices`. If the flat-ended slot walls go into `_used_p_walls`, they are excluded from Section E. However, since these are interior faces (not at the part boundary), Section E's shoulder-wall search would not select them anyway.

---

## 8. Recommended Heuristic — Precise Specification

```
_FLAT_SLOT_MIN_AR = 3.5

# Inside Section D, after floor-face lookup:
_ar = max(_px, _py) / min(_px, _py)   # already computed from _length / _width
if _floor_face is None and _ar >= _FLAT_SLOT_MIN_AR:
    # Flat-ended through slot
    _s_n[0] += 1
    _scid = f"S{_s_n[0]:03d}"
    _is_flat_slot = True
    _confidence   = "medium"
    _fname        = f"Flat-ended slot {_length:.1f}x{_width:.1f} mm"
    _dsource      = "flat_ended_slot_walls"
    _snote        = (
        f"Flat-ended slot detected via paired internal PLANE walls — "
        f"X-pair: face #{...} / face #{...}, gap={_px:.2f} mm; "
        f"Y-pair: face #{...} / face #{...}, gap={_py:.2f} mm; "
        f"Z overlap {_zlo:.2f} to {_zhi:.2f} mm (depth={_wall_lz:.2f} mm); "
        f"aspect ratio={_ar:.2f} >= {_FLAT_SLOT_MIN_AR}; "
        f"No floor face — treated as through slot."
    )
    _feature_type = "Slot"
elif _floor_face is not None:
    # Blind pocket (unchanged existing logic)
    ...
else:
    # Through pocket (unchanged existing logic)
    ...
```

**Shared `_s_n` counter:** The flat-ended slot detection uses the existing `_s_n[0]` counter from Section C. This produces S001, S002, … IDs that are consistent regardless of whether slots come from curved ends (Section C) or flat ends (Section D path). The `_s_n` counter must be accessible in Section D — currently it is defined at the top of `_classify_face_records()` and is in scope.

**`_used_p_walls`:** Flat-ended slot wall indices ARE added to `_used_p_walls` (same as pocket walls) to prevent re-processing. Section E already excludes `_used_p_walls` faces from step detection.

---

## 9. Test Cases

| Test file | Change expected | Pre-change actual | Post-change expected |
|-----------|----------------|------------------|----------------------|
| `M02_vmc_slot_plate.step` | **Slot=1** (was Pocket=1) | Pocket=1 | Face milling=2, Slot=1 |
| `M03_vmc_blind_rectangular_pocket.step` | No change | Pocket=1 | Pocket=1 (AR=2.0 < 3.5) |
| `M04_vmc_through_pocket_window.step` | No change | Pocket=1 | Pocket=1 (AR=2.0 < 3.5) |
| `13_rectangular_pocket_blind.step` | No change | Pocket=1 | Pocket=1 (AR=2.67 < 3.5) |
| `23_mixed_plate_holes_slot_pocket.step` | No change | Pocket=2, Slot=2 | Pocket=2, Slot=2 (pocket AR=2.25) |
| All remaining 14 baseline samples | No change | as per regression | unchanged |

Regression requirement: run `tests/run_feature_detection_regression.py --allow-missing` after implementation. With M02 fixed, result should be **18 PASS, 0 FAIL, 1 MISSING** (M06 still absent).

---

## 10. Summary of Findings

| Finding | Detail |
|---------|--------|
| Root cause | Section C requires CYLINDER faces; M02 has none |
| Current misclassification path | Section D claims 4 flat walls; AR=4.0 < _P_MAX_ASPECT=8.0 threshold |
| Fix location | Section D of `_classify_face_records()` in `modules/step_parser.py` |
| Fix type | One new AR threshold constant + one additional elif branch in the floor-face classification |
| Threshold value | `_FLAT_SLOT_MIN_AR = 3.5` |
| Safety margin | 0.83 AR units above highest known pocket (AR=2.67), 0.5 below lowest known slot (AR=4.0) |
| Files changed | `modules/step_parser.py` only |
| Other files | No changes to app.py, operation_planner.py, tool_selector.py, time_estimator.py, gcode_generator.py |
| Operation planner impact | None — operation_planner.py already handles feature_type="Slot" identically for rounded and flat slots |
| Regression risk | Low — clean AR gap between all existing pocket samples (max 2.67) and target slot (4.0) |
