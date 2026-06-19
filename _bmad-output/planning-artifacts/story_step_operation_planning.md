# Story: Step / Shoulder Operation Planning

**Epic:** Epic 2 — Step and Shoulder Detection  
**Priority:** 2 (completes step feature end-to-end flow)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer or VMC machinist,  
> I want the operation plan to show dedicated step milling operations when a Step feature is accepted,  
> so that the plan includes realistic rough and finish shoulder passes instead of a generic fallback.

---

## 2. Business Value

| Value | Detail |
|-------|--------|
| Quoting accuracy | A step/shoulder requires a profiling/shouldering pass, not a generic end-mill fallback. Correct operations produce believable cycle-time and cost estimates. |
| Machinist credibility | A plan that shows "Rough step floor and shoulder" with depth/radial pass notes is immediately recognisable to a VMC operator as correct. |
| Feature completeness | Step detection was implemented (Epic 2, story_vmc_step_shoulder_detection.md). This story closes the operation-planning half of that epic so accepted Step candidates flow end-to-end through the app. |

---

## 3. Technical Context

### What existed before

`OPERATION_RULES` in `modules/operation_planner.py` did not include a `"Step"` key.  
When a Step feature was accepted, `plan_operations()` fell through to the default:

```python
rules = OPERATION_RULES.get(ftype, [{"op": "End Mill", "notes": "General machining"}])
```

This produced a single generic "End Mill / General machining" operation for every Step feature — wrong operation type, wrong count, no notes about depth passes or shoulder walls.

### Sample reference geometry

`test_samples/17b_top_milled_step_shoulder-Body.step`

Detected Step candidate:
- `feature_type = "Step"`
- `feature_name = "Step shoulder 90.0x30.0 depth 12.0 mm"`
- `length = 90` mm (step floor length)
- `width  = 30` mm (shoulder wall height / step width)
- `depth  = 12` mm (step drop depth)

---

## 4. Files Changed

| File | Change |
|------|--------|
| `modules/operation_planner.py` | Only file modified. Three additions: (1) `"Step"` entry in `OPERATION_RULES`; (2) Step path-length formula in `estimate_path_length()`; (3) Step Rough context note in `_context_note()`. |

No other files modified.

---

## 5. Implementation

### OPERATION_RULES

```python
"Step": [
    {"op": "Rough End Mill", "notes": "Rough step floor and shoulder"},
    {"op": "Finish End Mill", "notes": "Finish step floor and shoulder wall"},
],
```

### Path length — `estimate_path_length()`

```python
if ftype == "Step":
    step_len = length or 50

    if operation_type == "Rough End Mill":
        dia           = tool_dia if tool_dia > 0 else 12.0
        stepdown      = dia * 0.5
        stepover      = dia * 0.6
        depth_passes  = max(1, math.ceil(depth / stepdown)) if depth > 0 else 1
        radial_passes = max(1, math.ceil(width / stepover)) if width > 0 else 1
        return depth_passes * radial_passes * step_len * qty

    if operation_type == "Finish End Mill":
        # One pass along step floor + one pass along shoulder wall.
        return 2 * step_len * qty

    return step_len * qty
```

For the 17b sample (length=90, width=30, depth=12, tool=12mm end mill):
- Rough: depth_passes=ceil(12/6)=2, radial_passes=ceil(30/7.2)=5, path=2×5×90=**900 mm**
- Finish: 2×90=**180 mm**

### Context note — `_context_note()`

```python
if ftype == "Step":
    if op_type == "Rough End Mill":
        return "Rough lower step level using multiple depth/radial passes."
```

Combined final notes:
- Rough: `"Rough step floor and shoulder | Rough lower step level using multiple depth/radial passes."`
- Finish: `"Finish step floor and shoulder wall"`

---

## 6. Verification Output

```
python experiments/verify_step_operations.py

Operations generated: 2

  Op 01  Rough End Mill        tool=End Mill 12mm         path=  900.0 mm
         notes: Rough step floor and shoulder | Rough lower step level using multiple depth/radial passes.

  Op 02  Finish End Mill       tool=End Mill 12mm         path=  180.0 mm
         notes: Finish step floor and shoulder wall

All assertions passed.
```

---

## 7. Sequencing

`_sequence_key()` already dispatches by `operation_type` (`"Rough End Mill"` → key 3, `"Finish End Mill"` → key 4), so Step operations slot into the correct position in the machining sequence without any changes to that function:

1. Face milling (Setup 1)
2. Spot Drill / Pilot Drill / Drill
3. Boring
4. Rough End Mill (pockets, slots, **steps**)
5. Finish End Mill (pockets, slots, **steps**)
6. Face milling (Setup 2 / flip)

---

## 8. How to Test in Streamlit

1. Start the Streamlit app:
   ```
   streamlit run app.py
   ```
2. On the upload page, upload `test_samples/17b_top_milled_step_shoulder-Body.step`.
3. Navigate to **5a. Setup & Feature Review**.
4. In the **Detected CAD Feature Candidates** section, locate the Step candidate:
   - Name: `Step shoulder 90.0x30.0 depth 12.0 mm`
   - Type: Step
   - Confidence: medium
5. Accept the Step candidate → it moves to the feature list.
6. Navigate to **6. Operation Plan**.
7. Verify two operations appear for the Step feature:
   - `Rough End Mill` — notes include "Rough step floor and shoulder" and "multiple depth/radial passes"
   - `Finish End Mill` — notes: "Finish step floor and shoulder wall"
8. Check the estimated path lengths are non-zero and plausible.
9. Verify no other features (Face milling, holes, slots accepted from other samples) are affected.

---

## 9. Definition of Done

- [x] `OPERATION_RULES["Step"]` added with Rough End Mill and Finish End Mill entries.
- [x] `estimate_path_length()` handles `ftype == "Step"` with a raster-style rough estimate and a 2×length finish estimate.
- [x] `_context_note()` returns "Rough lower step level using multiple depth/radial passes." for Step + Rough End Mill.
- [x] `plan_operations()` produces exactly 2 operations for one accepted Step feature (not the generic "General machining" fallback).
- [x] Verification script `experiments/verify_step_operations.py` passes all assertions.
- [x] No other files modified (step_parser.py, app.py, tool_selector.py, time_estimator.py, gcode_generator.py unchanged).
- [ ] Streamlit manual test with `17b_top_milled_step_shoulder-Body.step` (perform before demo).
- [ ] PRD current-state document updated: note Step operation planning as Implemented.
