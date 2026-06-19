# Story: Chamfer Operation Planning

**Epic:** Epic 3 — Chamfer Detection  
**Priority:** 3 (completes chamfer feature end-to-end flow)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer or VMC machinist,  
> I want the operation plan to show a dedicated chamfering operation when a Chamfer feature is accepted,  
> so that the plan includes chamfer-specific tooling notes and a realistic cycle-time estimate.

---

## 2. Business Value

| Value | Detail |
|-------|--------|
| Quoting accuracy | A top-edge chamfer requires a chamfer mill / countersink-style tool. A generic "End Mill / General machining" fallback is visibly wrong and would produce a misleading cost estimate. |
| Machinist credibility | A plan that reads "Chamfer top edges — use chamfer mill, verify size and edge selection before machining" is immediately recognisable as correct to a VMC operator. |
| Feature completeness | Chamfer detection was implemented (story_chamfer_detection.md). This story closes the operation-planning half: accepted Chamfer candidates now flow end-to-end through the app. |

---

## 3. Technical Context

### What existed before this story

`OPERATION_RULES["Chamfer"]` already existed with a placeholder note:

```python
"Chamfer": [
    {"op": "Chamfer", "notes": "Chamfer edges"},
],
```

The `_context_note()` function had no Chamfer branch — it returned `""` for all Chamfer operations, so no additional guidance appeared in the plan.

The path-length formula already handled `ftype == "Chamfer"`:
```python
if ftype == "Chamfer":
    return (diameter or 10) * 3.14 * qty
```
This approximates a circular-edge perimeter and is acceptable as a planning estimate. No change needed.

`_sequence_key()` already places Chamfer at position 5 (after roughing/finishing, before bottom face milling) — correct for top-edge chamfers. No change needed.

### What this story adds

Two targeted changes, both in `modules/operation_planner.py`:

1. `OPERATION_RULES["Chamfer"]` notes updated: `"Chamfer edges"` → `"Chamfer top edges"`
2. `_context_note()` gains a Chamfer branch that returns the tooling/verification note.

---

## 4. Sample Reference Geometry

`test_samples/M07_vmc_chamfered_plate.step`

Detected Chamfer candidate (from Section F of step_parser):
- `feature_type = "Chamfer"`
- `feature_name = "Top edge chamfer ~2.0×2.0 mm (4 faces)"`
- `quantity = 4` (chamfer face count)
- `width = 2.0`, `depth = 2.0` (chamfer size estimate)
- `diameter = None`, `length = None`
- `confidence = "medium"`

---

## 5. Files Changed

| File | Change |
|------|--------|
| `modules/operation_planner.py` | Two additions: (1) updated notes string in `OPERATION_RULES["Chamfer"]`; (2) Chamfer branch in `_context_note()`. |

No other files modified.

---

## 6. Implementation

### OPERATION_RULES

```python
"Chamfer": [
    {"op": "Chamfer", "notes": "Chamfer top edges"},
],
```

### `_context_note()`

```python
if ftype == "Chamfer":
    return (
        "Use chamfer mill / countersink-style tool. "
        "Verify chamfer size and edge selection before machining."
    )
```

Combined final notes for an accepted Chamfer feature:

```
Chamfer top edges | Use chamfer mill / countersink-style tool. Verify chamfer size and edge selection before machining.
```

### Path length (unchanged)

```python
if ftype == "Chamfer":
    return (diameter or 10) * 3.14 * qty
```

For M07 (diameter=None, qty=4): `10 × 3.14 × 4 = 125.6 mm` — a planning-level estimate.

### Sequence (unchanged)

`_sequence_key()` returns `5` for Chamfer — after Rough/Finish End Mill (keys 3/4), before bottom face milling (key 6). Correct for top-edge chamfers.

---

## 7. Verification Output

```
python experiments/verify_chamfer_operations.py

Operations generated: 1

  Op 01  Chamfer               tool=Chamfer 45° 12mm       path=   125.6 mm
         notes: Chamfer top edges | Use chamfer mill / countersink-style tool. Verify chamfer size and edge selection before machining.

All assertions passed.
```

---

## 8. How to Test in Streamlit

1. Start the Streamlit app:
   ```
   streamlit run app.py
   ```
2. On the upload page, upload `test_samples/M07_vmc_chamfered_plate.step`.
3. Navigate to **5a. Setup & Feature Review**.
4. In the **Detected CAD Feature Candidates** section, locate the Chamfer candidate:
   - Name: `Top edge chamfer ~2.0×2.0 mm (4 faces)`
   - Type: Chamfer
   - Confidence: medium
5. Accept the Chamfer candidate → it moves to the feature list.
6. Navigate to **6. Operation Plan**.
7. Verify **one operation** appears for the Chamfer feature:
   - `Chamfer` — notes include "Chamfer top edges" and "chamfer mill / countersink-style tool"
8. Check the estimated path length is non-zero (≈125.6 mm for M07).
9. Verify no other features (Face milling, Hole) are affected.

---

## 9. Definition of Done

- [x] `OPERATION_RULES["Chamfer"]` notes updated to `"Chamfer top edges"`.
- [x] `_context_note()` returns chamfer tool/verification note for `ftype == "Chamfer"`.
- [x] `plan_operations()` produces exactly 1 Chamfer operation (not the generic "General machining" fallback) for one accepted Chamfer feature.
- [x] Combined notes include both "Chamfer top edges" and "chamfer mill / countersink-style tool".
- [x] Verification script `experiments/verify_chamfer_operations.py` passes all assertions.
- [x] No other files modified.
- [ ] Streamlit manual test with `M07_vmc_chamfered_plate.step` (perform before demo).
