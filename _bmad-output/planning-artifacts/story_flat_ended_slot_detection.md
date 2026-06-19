# Story: Flat-Ended Slot Detection

**Epic:** Epic 2 — Slot Detection Completeness  
**Priority:** 3 (blocking regression — M02 currently FAIL)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer or VMC machinist,  
> I want the app to detect a flat-ended (square-cornered) through-slot correctly,  
> so that the process plan shows a slotting operation rather than a pocket window,  
> and the operation notes accurately reflect slot depth passes and wall finishing.

---

## 2. Business Value

| Value | Detail |
|-------|--------|
| Regression fix | M02_vmc_slot_plate.step currently FAILs the automated regression suite. This unblocks a clean 18-PASS / 0-FAIL regression baseline (excluding M06 which is still missing). |
| Quoting accuracy | Slotting and pocket roughing have different tool requirements, cycle times, and costs. A 80×20mm through-slot is machined with a slot mill in one or two depth passes; calling it a "through pocket" implies pocket-clearing strategy which overestimates cycle time. |
| Machinist credibility | Any experienced VMC machinist inspecting the plan will immediately recognise the difference between a slot and a rectangular window. Correct classification builds trust. |
| Feature completeness | Many VMC job plates have straight-ended slots (milled with a flat end-mill without radiused corners, or modelled in CAD without corner fillets). Rounded-slot detection already works; flat-ended is the natural complement. |

---

## 3. Technical Context

### 3.1 What already works — Section C (rounded slots)

`_classify_face_records()` in `modules/step_parser.py` — Section C:

1. Collects all CYLINDER faces.
2. Selects non-circular cylinders (bbox_lx ≠ bbox_ly > 15%) as slot-end walls.
3. Pairs two such cylinders with matching radius and axis alignment.
4. Emits a `Slot` candidate with `candidate_id = S001 …`, `feature_type = "Slot"`.

This works for slots with curved (radiused) end caps. It does not handle flat-ended slots because those have no CYLINDER faces.

### 3.2 What already works — Section D (rectangular pockets)

Section D pairs opposing ±X / ±Y internal PLANE faces. For the pair to qualify as a pocket:
- Wall gap must be within 88% of part span.
- Aspect ratio must be < `_P_MAX_ASPECT = 8.0`.
- No CYLINDER faces within the pocket footprint.
- If a floor face is found → blind pocket. If not → through pocket.

**The gap:** A flat-ended slot has four internal PLANE walls. Section D captures them and emits a "Through pocket" because the current AR threshold (8.0) is too permissive — a 4:1 slot safely passes.

### 3.3 M02 geometry summary

`test_samples/M02_vmc_slot_plate.step`:
- Part: 120 mm (X) × 200 mm (Y) × 30 mm (Z), 10 PLANE faces, 0 CYLINDER faces.
- Slot: 80 mm (Y) × 20 mm (X) × 30 mm (Z) through, centred at origin.
- Internal PLANE walls: side walls #4 (+X, area=2400 mm²) + #6 (−X, area=2400 mm²); end walls #5 (+Y, area=600 mm²) + #7 (−Y, area=600 mm²).
- Aspect ratio: 80/20 = **4.0**.

### 3.4 Aspect ratio analysis of all current samples

| Sample | Feature | Dimensions | AR |
|--------|---------|-----------|-----|
| M03 | Blind pocket | 70×35 mm | 2.00 |
| M04 | Through pocket | 70×35 mm | 2.00 |
| 13 | Through pocket | 80×30 mm | 2.67 |
| 23-P001/P002 | Through pockets | 90×40 mm | 2.25 |
| **M02 (target)** | **Flat-ended slot** | **80×20 mm** | **4.00** |
| 23-S001 | Rounded slot | 159.33×37.50 mm | 4.25 |
| 23-S002 | Rounded slot | 115.90×15.90 mm | 7.29 |

Maximum pocket AR: **2.67**. Minimum slot AR: **4.00**. Safe threshold: **3.5** (0.83 headroom on pocket side).

---

## 4. Proposed Detection Logic

### 4.1 Implementation location

Inside `_classify_face_records()` in `modules/step_parser.py`, **within the existing Section D loop**, in the floor-face classification block. This is the point after all existing guards have passed (dimension check, CYLINDER guard, used-walls check) and after the floor-face lookup has run.

### 4.2 New constant

```python
_FLAT_SLOT_MIN_AR = 3.5   # below this, high-AR region stays a Pocket; above, classify as flat-ended Slot
```

Place alongside `_P_MAX_ASPECT` at the top of Section D's constants block.

### 4.3 Logic change in the floor-face block

```python
# Compute aspect ratio (already available as _length / _width, or max/min of _px, _py)
_ar = max(_px, _py) / min(_px, _py)

if _floor_face is not None:
    # ── Blind pocket (existing logic, unchanged) ──────────────────────────
    _is_blind   = True
    _depth      = round(wall_z_hi - _floor_z, 3)
    _confidence = "medium"
    _fname      = f"Pocket {_length:.1f}x{_width:.1f} mm"
    _floor_note = (...)
    _pocket_floor_indices.add(_floor_face["face_index"])
    _feature_type_d = "Pocket"
    _candidate_id_d = f"P{_p_n[0]+1:03d}"
    _p_n[0] += 1

elif _ar >= _FLAT_SLOT_MIN_AR:
    # ── Flat-ended through slot (new branch) ──────────────────────────────
    _s_n[0] += 1
    _depth      = round(_wall_lz, 3)
    _confidence = "medium"
    _fname      = f"Flat-ended slot {_length:.1f}x{_width:.1f} mm"
    _floor_note = (
        f"No floor face detected; aspect ratio {_ar:.2f} >= {_FLAT_SLOT_MIN_AR} — "
        f"classified as flat-ended through slot."
    )
    _feature_type_d = "Slot"
    _candidate_id_d = f"S{_s_n[0]:03d}"

else:
    # ── Through pocket / window (existing logic, unchanged) ───────────────
    _is_blind   = False
    _depth      = round(_wall_lz, 3)
    _confidence = "low"
    _fname      = f"Through pocket {_length:.1f}x{_width:.1f} mm"
    _floor_note = "No floor face detected -- treated as through pocket/window."
    _feature_type_d = "Pocket"
    _candidate_id_d = f"P{_p_n[0]+1:03d}"
    _p_n[0] += 1
```

### 4.4 Candidate dict for flat-ended slot

| Field | Value |
|-------|-------|
| `candidate_id` | `S001`, `S002`, … (shared counter with Section C rounded slots) |
| `feature_name` | `"Flat-ended slot 80.0x20.0 mm"` |
| `feature_type` | `"Slot"` |
| `depth` | Wall Z span (= full part height for through slot) |
| `length` | Longer gap dimension |
| `width` | Shorter gap dimension |
| `confidence` | `"medium"` (four walls confirmed, AR unambiguous) |
| `detection_source` | `"flat_ended_slot_walls"` |
| `detection_note` | Wall pair details + AR + "No floor face — through slot" |

### 4.5 Shared `_s_n` counter note

`_s_n` is defined at the top of `_classify_face_records()` and is in scope in Section D. The new flat-slot branch increments `_s_n[0]` directly, exactly as Section C does. No new counter variable is needed.

### 4.6 `_used_p_walls` interaction

Flat-ended slot wall indices are added to `_used_p_walls` (same as pocket walls), preventing any re-processing by subsequent iterations of Section D or by Section E (which excludes `_used_p_walls`).

---

## 5. Allowed Files for Implementation

Only the following file may be modified to implement this story:

| File | Change |
|------|--------|
| `modules/step_parser.py` | Add `_FLAT_SLOT_MIN_AR` constant; add flat-ended slot elif branch in Section D floor-face block |

**Do not modify:**
- `app.py`
- `modules/operation_planner.py` — already handles `feature_type = "Slot"` correctly; flat slots route through the same slot planning path.
- `modules/tool_selector.py`
- `modules/time_estimator.py`
- `modules/gcode_generator.py`
- `data/`
- `requirements.txt`
- `experiments/`
- `tests/` — only update `feature_detection_expectations.json` to change M02 notes after implementation confirms the fix. Do not change expected counts before verification.

---

## 6. Acceptance Criteria

1. **M02 correctly classified as Slot**  
   `test_samples/M02_vmc_slot_plate.step` → 3 candidates: 2 Face milling + 1 Slot (S001), `confidence = "medium"`, `feature_name = "Flat-ended slot 80.0x20.0 mm"`, `detection_source = "flat_ended_slot_walls"`.

2. **M02 candidate ID is S001**  
   The flat-ended slot uses the `_s_n` counter, producing S001 (since M02 has no rounded-end slots to claim S001 first).

3. **Depth equals full part height (through slot)**  
   M02 slot depth = 30.0 mm (= wall Z span = part Z height; correctly reported as through).

4. **Detection note references aspect ratio**  
   The `detection_note` includes the AR value and the threshold, and states "classified as flat-ended through slot".

5. **M03 blind pocket unchanged**  
   Still produces 2 Face milling + 1 Pocket (Blind pocket), no Slot candidate. AR = 2.0 < 3.5.

6. **M04 through pocket unchanged**  
   Still produces 2 Face milling + 1 Pocket (Through pocket), no Slot candidate. AR = 2.0 < 3.5.

7. **Sample 13 through pocket unchanged**  
   Still produces 2 Face milling + 1 Pocket (Through pocket). AR = 2.67 < 3.5.

8. **Sample 23 mixed unchanged**  
   Still produces 2 Face milling + 2 Slot (rounded) + 2 Pocket. The rounded slots (Section C) still claim S001/S002; the pockets remain (AR = 2.25 < 3.5).

9. **All 17 other baseline regression samples unchanged**  
   `tests/run_feature_detection_regression.py --allow-missing` reports **18 PASS, 0 FAIL, 1 MISSING** (M06).

10. **No new Python dependencies introduced.**

---

## 7. Edge Cases

| Case | Expected behaviour |
|------|--------------------|
| **Flat-ended blind slot** (slot milled partially through with a floor) | Floor face is found → AR check is not reached → emitted as Blind Pocket, confidence=medium. This is an acceptable classification: a blind flat-ended slot is geometrically a blind pocket; user can relabel on the review page. Future story can add "Blind slot" as a distinct type if needed. |
| **Very high AR through pocket** (designer's intent is a pocket, but AR ≥ 3.5) | Emitted as Flat-ended slot. The user can override on the review page. Confidence = medium (not high), prompting inspection. |
| **Very short flat-ended slot** (e.g., 20×5 mm, AR=4.0) | Emitted as flat-ended slot if dimensions pass `_P_MIN_DIM = 4.0` guard. No special handling needed — end mill can still slot a 5mm-wide channel. |
| **Flat-ended slot coincides with a rounded slot** | Impossible: a slot either has CYLINDER end faces (Section C takes it) or does not. Section D's CYLINDER guard prevents overlap. |
| **Flat-ended slot near the part boundary** (gap > 88% of part span) | `_P_OUTER_FRAC` guard already rejects this; the geometry is not detected at all. Acceptable — a slot spanning 88%+ of the part width is arguably an outer profile step, not a slot. |
| **M02 run after a sample with rounded slots** | `_s_n` counter increments cumulatively. If M02 is parsed after a file with 2 rounded slots, the flat-ended slot would be S003. This is per-parse-call state and resets with each call — no issue. |
| **Two flat-ended slots on one part** | Each qualifying (X-pair, Y-pair) iteration runs the flat-slot branch independently. `_used_p_walls` prevents double-claiming the same walls. Two slots → S001, S002. |
| **Flat-ended slot on 23-mixed** | 23-mixed's pockets have AR=2.25. No flat-slot false positive introduced. The rounded-end slots already consume their cylinder faces before Section D runs; flat-slot branch is not reached. |

---

## 8. Regression Tests

### Pass/fail matrix after implementation

| Sample | Type | Expected | Notes |
|--------|------|---------|-------|
| `M02_vmc_slot_plate.step` | **Changed** | Face milling=2, Slot=1 | The failing test, now fixed |
| `M03_vmc_blind_rectangular_pocket.step` | Unchanged | Face milling=2, Pocket=1 | AR=2.0, blind |
| `M04_vmc_through_pocket_window.step` | Unchanged | Face milling=2, Pocket=1 | AR=2.0, through |
| `13_rectangular_pocket_blind.step` | Unchanged | Face milling=2, Pocket=1 | AR=2.67, through |
| `23_mixed_plate_holes_slot_pocket.step` | Unchanged | Face milling=2, Slot=2, Pocket=2 | Pockets AR=2.25 |
| `01_plain_rectangular_block_100x60x30-Body.step` | Unchanged | Face milling=2 | — |
| `02_plate_4_through_holes_d10.step` | Unchanged | Face milling=2, Hole=4 | — |
| `03_plate_4_blind_holes_d10_depth15.step` | Unchanged | Face milling=2, Hole=4 | — |
| `04_plate_mixed_holes_d6_d10_d20.step` | Unchanged | Face milling=2, Hole=3 | — |
| `05_plate_large_bore_d35_through.step` | Unchanged | Face milling=2, Large hole / boring=1 | — |
| `06_plate_4_large_bores_d35.step` | Unchanged | Face milling=2, Large hole / boring=4 | — |
| `09_slotted_plate_single_center_slot.step` | Unchanged | Face milling=2, Slot=1 | Rounded |
| `17b_top_milled_step_shoulder-Body.step` | Unchanged | Face milling=2, Step=1 | — |
| `25_vmc_job_plate_all_basic_features.step` | Unchanged | Face milling=2, Slot=2, Large hole / boring=1 | Rounded |
| `M01_vmc_basic_plate_holes.step` | Unchanged | Face milling=2, Hole=4 | — |
| `M05_vmc_large_bore_plate.step` | Unchanged | Face milling=2, Hole=2, Large hole / boring=1 | — |
| `M07_vmc_chamfered_plate.step` | Unchanged | Face milling=2, Hole=4 | — |
| `test5slotted.step` | Unchanged | Face milling=2, Large hole / boring=4, Slot=1 | — |
| `M06_vmc_top_milled_step_shoulder.step` | MISSING | Face milling=2, Step=1 | File not yet created |

Run command: `python tests/run_feature_detection_regression.py --allow-missing`  
Expected result: **18 PASS, 0 FAIL, 1 MISSING**

### After-fix step for `feature_detection_expectations.json`

Update the M02 notes field from the current KNOWN FAIL note to:
```json
"notes": "Plate with single slot (flat-ended, no cylinder faces) — detected via Section D flat-slot branch, AR=4.0"
```

---

## 9. Definition of Done

- [x] `_classify_face_records()` in `modules/step_parser.py` updated:
  - [x] `_FLAT_SLOT_MIN_AR = 3.5` constant added to Section D constants block.
  - [x] `elif _ar >= _FLAT_SLOT_MIN_AR` branch added after the floor-face `if _floor_face is not None` block.
  - [x] Flat-ended slot uses `_s_n[0]` counter and emits `feature_type = "Slot"`, `detection_source = "flat_ended_slot_walls"`.
- [x] `python experiments/test_feature_candidates.py test_samples/M02_vmc_slot_plate.step` produces exactly 3 candidates: F001 Face milling, F002 Face milling, S001 Flat-ended slot, `confidence = medium`.
- [x] M03 and M04 still produce Pocket=1 (no Slot candidates introduced).
- [x] Sample 13 still produces Pocket=1 (AR=2.67 < 3.5).
- [x] Sample 23 still produces Slot=2 + Pocket=2 (no change to existing detections).
- [x] `python tests/run_feature_detection_regression.py --allow-missing` reports **18 PASS, 0 FAIL, 1 MISSING**.
- [x] `tests/feature_detection_expectations.json` M02 notes updated to reflect fixed detection.
- [x] No new Python dependencies introduced.
- [x] `modules/operation_planner.py`, `app.py`, and all other application files not modified.
- [ ] PRD current-state document updated: note flat-ended slot detection as Implemented.

---

## 10. Notes for Implementer

### Where exactly in step_parser.py to make the change

The target location is inside `_classify_face_records()`, in Section D, within the `for _xp in _xpairs: for _yp in _ypairs:` double loop.

The change is at the **floor-face classification block**: the section that begins with `if _floor_face is not None:` and currently ends with `else: (through pocket)`. Add the `elif _ar >= _FLAT_SLOT_MIN_AR:` between the existing `if` and `else`.

The AR value `_ar = max(_px, _py) / min(_px, _py)` can be computed at the top of the inner loop body (after gap dimensions `_px` and `_py` are known) or inline at the elif.

### Counter visibility

`_s_n` is defined at the very top of `_classify_face_records()` alongside `_f_n` and `_h_n`:
```python
_f_n = [0]   # facing ID counter
_h_n = [0]   # hole ID counter
_s_n = [0]   # slot ID counter
```
It is in scope throughout the function, including inside Section D.

### Operation planner compatibility

`modules/operation_planner.py` dispatches on `feature_type`. The `"Slot"` case is already handled with:
- Rough End Mill: "Slot roughing …"
- Finish End Mill: "Slot finishing …"

Flat-ended slots emitted as `feature_type = "Slot"` will follow the same planning path as rounded slots. No change needed in the planner.
