# Story: Top Outer-Edge Chamfer Detection

**Epic:** Epic 3 — Chamfer Detection  
**Priority:** 3 (after blind pocket and step detection — Epic 3 next)  
**Status:** Ready for implementation  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer or VMC machinist,  
> I want the app to detect top outer-edge chamfers on a VMC part,  
> so that the process plan includes a chamfering/deburring operation  
> and the quotation accounts for the chamfer cycle time.

---

## 2. Business Value

| Value | Detail |
|-------|--------|
| Quoting accuracy | Chamfering adds cycle time and requires a chamfer tool change. Omitting it understates cost on typical job plates where all edges are chamfered per drawing. |
| Machinist credibility | A plan for a chamfered plate that says "no chamfer operation" is visibly incomplete to any VMC operator. |
| Feature completeness | Face milling, holes, large bores, slots, pockets, and steps are now detected. Chamfers are the only remaining standard VMC feature for basic job plates. |
| Low implementation risk | The chamfer signal (angled PLANE near top, small area) is distinct from all currently detected geometries. False positive risk is low — confirmed by cross-checking all 18 existing regression samples. |

---

## 3. Technical Context

### 3.1 What the current detector does with M07

`test_samples/M07_vmc_chamfered_plate.step` currently produces:
```
Face milling=2, Hole=4
```

The 4 chamfer faces (PLANE, nz≈0.707, z_center≈24 mm) pass silently through Sections A–E:
- Section A skips them (nz < 0.92 threshold)
- Sections B/C skip them (not CYLINDER)
- Section D skips them (no vertical walls among them)
- Section E skips them (not at part boundary; no shoulder wall pairing)

### 3.2 Chamfer face geometry in M07

Part: 80×120×25 mm. All 4 outer top edges chamfered at 45°, nominal size 2mm × 2mm.

| Face # | normal (x, y, z) | z_center | area mm² | bbox (lx, ly, lz) |
|--------|-----------------|----------|----------|-------------------|
| 2 | (−0.707, 0, +0.707) | 23.99 | 333.75 | 2, 120, 2 |
| 6 | (0, +0.707, +0.707) | 23.99 | 220.62 | 80, 2, 2 |
| 8 | (0, −0.707, +0.707) | 23.99 | 220.62 | 80, 2, 2 |
| 13 | (+0.707, 0, +0.707) | 23.99 | 333.75 | 2, 120, 2 |

Confirmed chamfer size = min(small spans) = 2.0 mm.

### 3.3 Detection signal — four criteria (all must pass)

| Criterion | Guard | Rationale |
|-----------|-------|-----------|
| Geometry type | `geom_type == "PLANE"` | CONE (countersinks), CYLINDER (holes), BSPLINE (freeform) excluded |
| Angled upward | `0.40 ≤ nz ≤ 0.92` | Below Section A face-milling threshold; above horizontal |
| Significant horizontal | `max(|nx|, |ny|) ≥ 0.40` | Not a nearly-flat face accidentally tilted |
| Near top | `z_center > part_z_max − max(8.0, part_height × 0.20)` | Chamfers are at the top edge, not mid-part |
| Small face | `area < 2000 mm²` | Chamfer faces are small; large angled faces are design geometry |

### 3.4 Confirmed false-positive safety on all existing regression samples

| Sample | Angled PLANE faces? | Passes all chamfer guards? | Result |
|--------|---------------------|---------------------------|--------|
| 17b step shoulder | 0 | N/A | Safe ✓ |
| 23 mixed (slots/pockets) | 0 PLANE (3 CONE) | CONE excluded by PLANE guard | Safe ✓ |
| test5slotted | 0 | N/A | Safe ✓ |
| M03 blind pocket | 0 expected | N/A | Safe ✓ |
| M04 through pocket | 0 expected | N/A | Safe ✓ |
| 01 plain block | 0 expected | N/A | Safe ✓ |
| All other 12 samples | 0 expected | N/A | Safe ✓ |
| **M07 chamfered plate** | **4 confirmed** | **Yes — all 4 pass** | **Chamfer=1 ✓** |
| **25 all-features** | **6 confirmed** | **Yes — all 6 pass** | **Chamfer=1 (regression update)** |

### 3.5 Regression impact

Two samples will change detection output:

| Sample | Before | After |
|--------|--------|-------|
| `M07_vmc_chamfered_plate.step` | Face milling=2, Hole=4 | Face milling=2, Hole=4, **Chamfer=1** |
| `25_vmc_job_plate_all_basic_features.step` | Face milling=2, Slot=2, Large hole / boring=1 | Face milling=2, Slot=2, Large hole / boring=1, **Chamfer=1** |

Both `tests/feature_detection_expectations.json` entries must be updated as part of the DoD.

### 3.6 Operation planner — no change needed

`modules/operation_planner.py` already contains:
```python
"Chamfer": [
    {"op": "Chamfer", "notes": "Chamfer edges"},
],
```

Accepted Chamfer candidates will route to a "Chamfer / Chamfer edges" operation automatically. The existing path-length estimate (`diameter * π * qty`) approximates a hole chamfer and is a reasonable starting point; a future story can improve this to a perimeter-based estimate.

---

## 4. Detection Logic

### 4.1 Implementation location

New **Section F** in `_classify_face_records()` in `modules/step_parser.py`, inserted after Section E (step detection) and before `return candidates`.

### 4.2 Constants

```python
# ── F. Chamfer candidates ─────────────────────────────────────────────────
_CH_NZ_MIN    = 0.40     # nz lower bound: ~24° from horizontal
_CH_NZ_MAX    = 0.92     # nz upper bound: just below Section A flat-face threshold
_CH_HORIZ_MIN = 0.40     # |nx| or |ny| must be significant — truly angled, not nearly flat
_CH_MAX_AREA  = 2000.0   # mm² — upper bound for a single chamfer face
_CH_Z_FRAC    = 0.20     # z_center must be within 20% of part height from top (min 8 mm)
```

### 4.3 Pseudocode

```python
_p_z_max = part_bbox.get("z_range", (0.0, 0.0))[1]
_ch_z_lo = _p_z_max - max(8.0, part_height * _CH_Z_FRAC)

_ch_faces = []
for _r in face_records:
    if _r.get("geom_type") != "PLANE":
        continue
    _nz   = _r.get("normal_z") or 0.0
    _hnx  = abs(_r.get("normal_x") or 0.0)
    _hny  = abs(_r.get("normal_y") or 0.0)
    _area = _r.get("area_mm2") or 0.0
    _cz   = _r.get("center_z") or 0.0

    if not (_CH_NZ_MIN <= _nz <= _CH_NZ_MAX):
        continue
    if max(_hnx, _hny) < _CH_HORIZ_MIN:
        continue
    if _area > _CH_MAX_AREA or _area < 50.0:
        continue
    if _cz < _ch_z_lo:
        continue

    _ch_faces.append(_r)

if _ch_faces:
    _sizes = []
    for _cf in _ch_faces:
        _dims = [v for v in [
            _cf.get("bbox_length_x") or 0.0,
            _cf.get("bbox_length_y") or 0.0,
            _cf.get("bbox_length_z") or 0.0,
        ] if v > 0.1]
        if _dims:
            _sizes.append(min(_dims))
    _ch_size = round(sum(_sizes) / len(_sizes), 1) if _sizes else 0.0
    _n = len(_ch_faces)

    candidates.append({
        "candidate_id":     "CH001",
        "feature_name":     f"Top outer edge chamfer ~{_ch_size:.1f}x{_ch_size:.1f} mm ({_n} faces)",
        "feature_type":     "Chamfer",
        "quantity":         _n,
        "x_pos":            0.0,
        "y_pos":            0.0,
        "diameter":         None,
        "length":           None,
        "width":            None,
        "depth":            _ch_size,
        "tolerance_note":   "",
        "priority":         4,
        "confidence":       "medium" if _n >= 3 else "low",
        "detection_source": "angled_plane_near_top",
        "detection_note":   (
            f"{_n} angled PLANE face(s) near top of part "
            f"(nz ∈ [{_CH_NZ_MIN}, {_CH_NZ_MAX}], max horizontal ≥ {_CH_HORIZ_MIN}); "
            f"z_center ≥ {_ch_z_lo:.1f} mm; "
            f"estimated chamfer ≈ {_ch_size:.1f} mm (bbox small span)."
        ),
        "accepted": False,
        "ignored":  False,
    })
```

---

## 5. Allowed Files for Implementation

Only the following file may be modified to implement this story:

| File | Change |
|------|--------|
| `modules/step_parser.py` | Add Section F (chamfer detection) after Section E, before `return candidates` |
| `tests/feature_detection_expectations.json` | Update M07 and sample 25 entries to include `Chamfer=1` |

**Do not modify:**
- `app.py`
- `modules/operation_planner.py` — existing Chamfer rule is already sufficient
- `modules/tool_selector.py`
- `modules/time_estimator.py`
- `modules/gcode_generator.py`
- `data/`
- `requirements.txt`
- `experiments/`

---

## 6. Acceptance Criteria

1. **M07 chamfer detected**  
   `test_samples/M07_vmc_chamfered_plate.step` → 6 candidates: 2 Face milling + 4 Hole + 1 Chamfer (CH001), `confidence = "medium"`, `feature_name` contains "2.0" (chamfer size), `quantity = 4` (faces found).

2. **Chamfer feature_type and detection_source**  
   `feature_type = "Chamfer"`, `detection_source = "angled_plane_near_top"`.

3. **Chamfer size estimate**  
   `depth = 2.0` (the bbox small-span average across 4 faces).

4. **Sample 25 chamfer detected**  
   `25_vmc_job_plate_all_basic_features.step` → previous candidates unchanged + 1 new Chamfer (CH001), `confidence = "medium"`, `quantity = 6`.

5. **All 16 other baseline samples unchanged**  
   No Chamfer candidates appear on any other sample, including:
   - 17b step shoulder (0 angled PLANE faces)
   - 23 mixed (CONE only — PLANE filter excludes)
   - M03, M04 (no angled geometry)
   - test5slotted (no angled PLANE faces)

6. **Existing candidates on M07 unchanged**  
   Still produces exactly 2 Face milling + 4 Hole. Chamfer is additive only.

7. **Existing candidates on sample 25 unchanged**  
   Face milling=2, Slot=2, Large hole / boring=1 counts all stay the same. Chamfer=1 is additive.

8. **Regression suite passes after expectations update**  
   `python tests/run_feature_detection_regression.py --allow-missing` reports **18 PASS, 0 FAIL, 1 MISSING** after updating expectations for M07 and sample 25.

9. **Operation planner routes correctly**  
   An accepted Chamfer candidate generates 1 operation: `op_type = "Chamfer"`, `notes = "Chamfer edges"`. (Verified by code inspection — no planner changes needed.)

10. **No new Python dependencies introduced.**

---

## 7. Edge Cases

| Case | Expected behaviour |
|------|--------------------|
| **No chamfer on part** (plain block, holes-only plate) | No qualifying angled PLANE faces → no Chamfer candidate emitted. Confirmed for all non-chamfer baseline samples. |
| **Single chamfer face only** (unusual geometry) | 1 face qualifies → Chamfer candidate emitted with `confidence = "low"`, prompting user to verify. |
| **Non-45° chamfer (30° or 60°)** | nz = sin(30°) = 0.500 or sin(60°) = 0.866, both within [0.40, 0.92] range → detected. |
| **Bottom-face chamfer** (under-side deburring) | Would need nz < 0 (facing downward). Not detected by this algorithm, which requires nz > 0.40. Acceptable for first pass — bottom chamfers require Setup 2 and are less common on typical VMC plates. |
| **Very deep chamfer (>5mm)** | Larger area, but if still < 2000 mm² and near top → detected. For a 5mm chamfer on a 200mm edge: 5×√2×200 ≈ 1414 mm² < 2000 ✓ |
| **Very small chamfer (0.5mm)** | Area ≈ 0.5×√2×100 ≈ 71 mm² > 50 mm² minimum → detected. Size estimate = 0.5mm. |
| **Part with intentional 45° angled face** (design feature, not a chamfer) | If area < 2000 AND z_center near top → could be a false positive. Confidence will be "low" if only 1 face, prompting review. Acceptable for first pass; user can ignore on review page. |
| **Multiple independent chamfer zones** (top + bottom, or different chamfer sizes) | Only top-face chamfers captured (z guard). All qualifying faces grouped into one CH001 candidate. Multiple distinct groups are a future story — grouping by edge position. |
| **Chamfer on slot opening edge** (sample 25 faces #35, #36) | Grouped into the same CH001 candidate as outer-plate chamfers. Acceptable for first pass; future story can distinguish edge types. |
| **Chamfer faces consumed by Section D/E** | No Section D/E rule consumes chamfer faces (they're not vertical for Section D, not step-floor-like for Section E). No conflict. |

---

## 8. Regression Tests

### Expected outcome after implementation + expectations update

| Sample | Before | After | Status change |
|--------|--------|-------|---------------|
| `M07_vmc_chamfered_plate.step` | FM=2, H=4 | FM=2, H=4, **Ch=1** | FAIL → PASS (with updated expectations) |
| `25_vmc_job_plate_all_basic_features.step` | FM=2, S=2, LHB=1 | FM=2, S=2, LHB=1, **Ch=1** | FAIL → PASS (with updated expectations) |
| `01_plain_rectangular_block_100x60x30-Body.step` | FM=2 | FM=2 | PASS unchanged |
| `02_plate_4_through_holes_d10.step` | FM=2, H=4 | FM=2, H=4 | PASS unchanged |
| `03_plate_4_blind_holes_d10_depth15.step` | FM=2, H=4 | FM=2, H=4 | PASS unchanged |
| `04_plate_mixed_holes_d6_d10_d20.step` | FM=2, H=3 | FM=2, H=3 | PASS unchanged |
| `05_plate_large_bore_d35_through.step` | FM=2, LHB=1 | FM=2, LHB=1 | PASS unchanged |
| `06_plate_4_large_bores_d35.step` | FM=2, LHB=4 | FM=2, LHB=4 | PASS unchanged |
| `09_slotted_plate_single_center_slot.step` | FM=2, S=1 | FM=2, S=1 | PASS unchanged |
| `13_rectangular_pocket_blind.step` | FM=2, P=1 | FM=2, P=1 | PASS unchanged |
| `17b_top_milled_step_shoulder-Body.step` | FM=2, St=1 | FM=2, St=1 | PASS unchanged |
| `23_mixed_plate_holes_slot_pocket.step` | FM=2, S=2, P=2 | FM=2, S=2, P=2 | PASS unchanged |
| `M01_vmc_basic_plate_holes.step` | FM=2, H=4 | FM=2, H=4 | PASS unchanged |
| `M02_vmc_slot_plate.step` | FM=2, S=1 | FM=2, S=1 | PASS unchanged |
| `M03_vmc_blind_rectangular_pocket.step` | FM=2, P=1 | FM=2, P=1 | PASS unchanged |
| `M04_vmc_through_pocket_window.step` | FM=2, P=1 | FM=2, P=1 | PASS unchanged |
| `M05_vmc_large_bore_plate.step` | FM=2, H=2, LHB=1 | FM=2, H=2, LHB=1 | PASS unchanged |
| `M06_vmc_top_milled_step_shoulder.step` | MISSING | MISSING | Still missing |
| `M07_vmc_chamfered_plate.step` | FM=2, H=4 | FM=2, H=4, Ch=1 | (see above) |

Legend: FM=Face milling, H=Hole, LHB=Large hole / boring, S=Slot, P=Pocket, St=Step, Ch=Chamfer

Run command: `python tests/run_feature_detection_regression.py --allow-missing`  
Expected: **18 PASS, 0 FAIL, 1 MISSING** (after expectations update)

---

## 9. Definition of Done

- [ ] `_classify_face_records()` in `modules/step_parser.py` has a new Section F:
  - [ ] Constants `_CH_NZ_MIN`, `_CH_NZ_MAX`, `_CH_HORIZ_MIN`, `_CH_MAX_AREA`, `_CH_Z_FRAC` defined.
  - [ ] Loop collects qualifying angled PLANE faces.
  - [ ] Single CH001 candidate emitted if any qualifying faces found.
  - [ ] `feature_type = "Chamfer"`, `detection_source = "angled_plane_near_top"`.
  - [ ] `confidence = "medium"` if ≥ 3 faces, `"low"` if 1–2.
- [ ] `python experiments/test_feature_candidates.py test_samples/M07_vmc_chamfered_plate.step` produces 6 candidates (2 FM + 4 H + 1 Chamfer CH001, confidence=medium, ~2.0mm size).
- [ ] `python experiments/test_feature_candidates.py test_samples/25_vmc_job_plate_all_basic_features.step` produces Chamfer=1 in addition to existing candidates.
- [ ] `17b_top_milled_step_shoulder-Body.step` produces 0 Chamfer candidates.
- [ ] `tests/feature_detection_expectations.json` updated:
  - [ ] M07 entry: add `"Chamfer": 1` to expected_counts.
  - [ ] Sample 25 entry: add `"Chamfer": 1` to expected_counts.
  - [ ] M07 notes field updated to describe chamfer detection.
- [ ] `python tests/run_feature_detection_regression.py --allow-missing` → **18 PASS, 0 FAIL, 1 MISSING**.
- [ ] No new Python dependencies introduced.
- [ ] `modules/operation_planner.py`, `app.py`, and all other application files **not modified**.
- [ ] PRD current-state document updated: Chamfer detection → Implemented.

---

## 10. Notes for Implementer

### Exact insertion point in step_parser.py

Section F belongs at the very end of `_classify_face_records()`, after the existing Section E step detection loop (after the `_st_used |= ...` lines), and before `return candidates`.

The pattern:
```python
    # ── E. Step / shoulder candidates ─────────────────────────────────────
    ...
    return candidates    # ← CURRENTLY HERE

    # BECOMES:

    # ── E. Step / shoulder candidates ─────────────────────────────────────
    ...

    # ── F. Chamfer candidates ──────────────────────────────────────────────
    _p_z_max = part_bbox.get("z_range", (0.0, 0.0))[1]
    ...
    # (Section F code here)

    return candidates
```

### Variables available from earlier in the function

- `part_bbox` — already passed as parameter
- `part_height` — computed at the top of `_classify_face_records()` from z_range
- `face_records` — the input list
- `candidates` — the list being accumulated

### Counter

Only one Chamfer candidate is emitted per call (CH001 hardcoded). If future stories require multiple independent chamfer zones, a `_ch_n = [0]` counter can be added then. For this story, hardcode "CH001".

### Verification commands

```bash
python experiments/test_feature_candidates.py test_samples/M07_vmc_chamfered_plate.step
python experiments/test_feature_candidates.py test_samples/25_vmc_job_plate_all_basic_features.step
python experiments/test_feature_candidates.py test_samples/17b_top_milled_step_shoulder-Body.step
python tests/run_feature_detection_regression.py --allow-missing
```
