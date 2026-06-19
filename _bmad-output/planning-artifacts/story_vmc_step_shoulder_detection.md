# Story: VMC Step / Shoulder Candidate Detection

**Epic:** Epic 2 — Step and Shoulder Detection  
**Priority:** 2  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer or VMC machinist,  
> I want the app to detect a step or shoulder feature on a VMC part,  
> so that the process plan includes the correct profiling/shouldering operation  
> and the depth and floor dimensions are accurate.

---

## 2. Business Value

| Value | Detail |
|---|---|
| Quoting accuracy | Steps require face milling or end-mill shoulder passes. Misclassifying them as plain outer-wall geometry misses these operations. |
| Machinist credibility | A process plan for a stepped block that omits the shoulder pass looks wrong to any experienced machinist. |
| Feature completeness | Steps and shoulders appear on the majority of VMC job plates alongside holes, slots, and pockets. Detecting them completes the basic VMC feature set. |

---

## 3. Technical Context

### Reference sample geometry (17b)

`test_samples/17b_top_milled_step_shoulder-Body.step`

| Face | geom_type | normal | position | area | Notes |
|---|---|---|---|---|---|
| #0 | PLANE | −X | x=−45 | 2700 mm² | Left outer wall |
| #1 | PLANE | −Y | y=0 | 10800 mm² | Front outer wall (full) |
| #2 | PLANE | +X | x=75 | 1620 mm² | Right outer partial wall |
| **#3** | **PLANE** | **+Y** | **y=18** | **2700 mm²** | **Step floor** (x=45..75, z=0..90) |
| **#4** | **PLANE** | **+X** | **x=45** | **1080 mm²** | **Shoulder wall** (y=18..30, z=0..90) |
| #5 | PLANE | +Y | y=30 | 8100 mm² | Outer back face |
| #6 | PLANE | −Z | z=0 | 3240 mm² | Bottom face |
| #7 | PLANE | +Z | z=90 | 3240 mm² | Top face |

- Step depth = 30 − 18 = **12 mm**
- Step floor: ny=+1 face at y=18, spanning x=[45..75], z=[0..90]
- Shoulder wall: nx=+1 face at x=45, spanning y=[18..30] (the step depth in Y)

The step is a side-profile shoulder (cut from the back in the Y direction), not a Z-level top-milled step. The algorithm handles both orientations.

### What already existed

Sections A–D in `_classify_face_records()` detect face milling, holes, slots, and rectangular pockets. None of those handle stepped/shouldered geometry.

---

## 4. Files Changed

| File | Change |
|---|---|
| `modules/step_parser.py` | **Only file modified.** Three additions: (1) `_pocket_floor_indices` set definition alongside `_used_p_walls`, (2) floor index tracking in blind-pocket branch of Section D, (3) Section E — step/shoulder detection. |

No other files modified.

---

## 5. Detection Logic (Section E)

### Algorithm overview

For each axis direction (Z first, then Y, then X) and each sign (+/−):

1. Collect all PLANE faces with |normal component| > 0.92 along that axis, not in `_step_excl` (pocket walls/floors), area ≥ 400 mm².
2. Sort by position. The face at the part boundary is the **outer face**; any face farther inside is a **step floor candidate**.
3. For each step floor candidate, apply guards:
   - Step depth ≥ 1 mm
   - Step depth ≤ 60% of part span in that axis (filters cross-part outer-wall pairings)
   - No mirror face on the opposite side at the same offset (filters symmetric slot/pocket channels)
   - For Z-axis: no CYLINDER face whose bbox-Z range overlaps the step region (filters slot floors and bore bottoms)
4. Find a **shoulder wall**: a PLANE face perpendicular to the step axis, whose bbox in the step-axis direction spans [step_floor_pos → outer_pos], with centre within the step floor footprint.
5. If shoulder wall found → emit ST001, ST002, … candidate.

### Key guards and why

| Guard | Reason |
|---|---|
| `_sdepth > _ax_span * 0.60` | Prevents pairing an inner face with the opposite outer wall (e.g., y=125 paired with y=−175 in a 350mm part → 300mm "depth") |
| Mirror-symmetry check | Filters slot side walls (X=118 paired with X=−118) and pocket walls, which always appear in opposite pairs |
| Z-axis cylinder bbox guard | Prevents slot floors (nz=+1 at intermediate Z) from triggering step detection; uses bbox overlap so full-depth slot cylinders are caught |
| `_st_used` set + Z-first axis order | Prevents a shoulder wall from being re-classified as a step floor in a later axis pass |
| `_pocket_floor_indices` exclusion | Prevents blind pocket floors (already consumed by Section D) from triggering Section E |

---

## 6. Acceptance Criteria

1. **Step detected from 17b sample**  
   `test_samples/17b_top_milled_step_shoulder-Body.step` → 3 candidates: 2 Face milling + 1 Step (ST001), `confidence = "medium"`, `depth = 12.0 mm`.

2. **Detection note references floor face and shoulder wall**  
   The `detection_note` includes the step floor face index, Y position, area, outer face index, depth, and shoulder wall face index.

3. **M03 blind pocket unchanged**  
   Still produces 2 Face milling + 1 Pocket (Blind pocket), no Step candidate.

4. **M04 through pocket unchanged**  
   Still produces 2 Face milling + 1 Pocket (Through pocket), no Step candidate.

5. **All baseline regression samples unchanged**  
   Counts: 02→6, 03→6, 04→5, 05→3, 06→6, 09→3, 13→3, 23→6, 25→5, M03→3, M04→3, test5slotted→7.  
   Zero Step candidates on any baseline sample.

6. **feature_type = "Step"**  
   The candidate uses `feature_type = "Step"` and `detection_source = "intermediate_floor_and_shoulder_wall"`.

7. **No new Python dependencies.**

---

## 7. Test Results

### 17b step sample

```
Total candidates : 3

F001  Face milling  Face milling — top surface   high
F002  Face milling  Face milling — bottom surface  high
ST001 Step          Step shoulder 90.0x30.0 depth 12.0 mm  medium
  Step floor: face #3 (normal_Y=+1.000, Y=18.00 mm, area=2700.0 mm²);
  outer face: #5 at Y=30.00 mm; step depth = 12.00 mm;
  shoulder wall: face #4 (area=1080.0 mm²).
```

### Regression (all passing)

| Sample | Expected | Actual | Step FP |
|---|---|---|---|
| 02 through holes | 6 | 6 | 0 |
| 03 blind holes | 6 | 6 | 0 |
| 04 mixed holes | 5 | 5 | 0 |
| 05 large bore | 3 | 3 | 0 |
| 06 large bores | 6 | 6 | 0 |
| 09 slot | 3 | 3 | 0 |
| 13 through pocket | 3 | 3 | 0 |
| 23 mixed | 6 | 6 | 0 |
| 25 all basic | 5 | 5 | 0 |
| M03 blind pocket | 3 | 3 | 0 |
| M04 through pocket | 3 | 3 | 0 |
| test5slotted | 7 | 7 | 0 |

---

## 8. Edge Cases

| Case | Behaviour |
|---|---|
| **Top-milled step (nz floor)** | Handled by Z-axis pass. Cylinder guard prevents slot floors triggering this path. |
| **Side step in Y (like 17b)** | Handled by Y-axis pass after Z. |
| **Side step in X** | Handled by X-axis pass after Y. |
| **Symmetric slots (X=±118)** | Mirror-symmetry guard filters them. |
| **Cross-part outer wall pairing (300 mm depth)** | 60%-span guard filters them. |
| **Blind pocket floor** | Already consumed by Section D; excluded via `_pocket_floor_indices`. |
| **No shoulder wall found** | Step candidate not emitted. Keeps false-positive rate low at cost of recall. |
| **Multiple steps on one part** | Each axis pass is independent. `_st_used` prevents double-emitting the same face. |

---

## 9. Definition of Done

- [x] `_classify_face_records()` in `modules/step_parser.py` updated with Section E.
- [x] `17b_top_milled_step_shoulder-Body.step` produces 2 FM + 1 Step, `confidence = medium`, `depth = 12.0 mm`.
- [x] M03 and M04 unchanged (no Step candidates introduced).
- [x] All 12 baseline regression samples produce same candidate counts as before.
- [x] No new Python dependencies introduced.
- [x] `modules/operation_planner.py` and all other files not modified.
- [ ] PRD current-state document updated to mark step/shoulder detection as Implemented.
- [ ] Operation planner updated to handle `feature_type = "Step"` (separate story — Step currently routes to generic "End Mill" fallback).
