# Story: True Blind Rectangular Pocket Detection

**Epic:** Epic 1 — True Blind Rectangular Pocket Detection  
**Priority:** 1 (highest current VMC gap)  
**Status:** Implemented ✓  
**Branch:** `v2-feature-review-engine`

---

## 1. User Story

> As a CNC quotation engineer or VMC machinist,  
> I want the app to detect a rectangular blind pocket that has an actual machined floor,  
> so that the operation plan includes floor cleanup passes and the depth estimate is accurate —  
> distinguishing it from a through pocket/window which has no floor to machine.

---

## 2. Business Value

| Value | Detail |
|---|---|
| Quoting accuracy | Blind pockets require floor finishing passes. A through window does not. Misclassifying one as the other produces wrong time and cost estimates. |
| Machinist credibility | A process plan that says "finish pocket walls and floor" for a through window looks wrong to any machinist who inspects the part. Correct classification builds trust. |
| SME usability | Workshop quotation engineers in Peenya, Chennai, and Coimbatore see blind pockets on almost every VMC job plate. This is a high-frequency feature that directly affects quoting. |
| Differentiation from through window | Through pocket detection (P-series candidates) already exists. Blind pocket detection is the natural complement, completing the rectangular pocket family. |

---

## 3. Technical Context

### What already exists

**Section D** in `_classify_face_records()` (`modules/step_parser.py`) detects **through rectangular pockets / windows**:

- Pairs opposing internal PLANE walls: one `+X` wall at `xa` with one `−X` wall at `xb > xa` (and similarly for `±Y`).
- The geometry rule "the `+X` wall must sit left of the `−X` wall" naturally excludes outer-profile walls without needing the global part centre.
- Skips pairs where the gap exceeds 88% of the part span in that axis.
- Skips regions that contain CYLINDER faces (already handled as slots by Section C).
- Emits candidates with `feature_type = "Pocket"`, `detection_source = "paired_internal_walls"`, `confidence = "low"`, and `feature_name` prefixed `"Through pocket …"`.
- Uses `_p_n` counter → IDs `P001`, `P002`, …

**What is missing** is the ability to recognise that a pocket has a **floor face** — a horizontal PLANE at an intermediate Z level. When a floor is present the pocket is blind (depth < part height), not through. The detection note, depth value, and confidence should all reflect this.

### Face record signature for a true blind pocket

For a block of height H with a blind pocket of depth D milled from the top:

| Face | geom_type | normal | z position | Notes |
|---|---|---|---|---|
| Top surface (with opening) | PLANE | `+Z` | `z = H` | area = footprint − pocket opening |
| **Pocket floor** | **PLANE** | **`+Z`** | **`z = H − D`** | **area = pocket_length × pocket_width** |
| Pocket walls (×4) | PLANE | `±X / ±Y` | z range: `H−D` to `H` | wall height = D (shorter than H) |
| Bottom surface (full) | PLANE | `−Z` | `z = 0` | area = full footprint — NOT reduced |
| Outer walls (×4) | PLANE | `±X / ±Y` | z range: `0` to `H` | full height = H |

Key differences from a through pocket:

- A **floor face exists** at intermediate Z (strictly between `z_min + 1 mm` and `z_max − 1 mm`).
- **Pocket walls are shorter** than full part height: `wall_lz = D < H`.
- **Bottom face is full area** (the pocket does not break through).
- The pocket wall Z range starts at `H − D`, not at `0`.

### How the floor face is distinguished from the top surface (Section A guard)

Section A already filters out the top face as a Face Milling candidate because its area passes the 35% footprint threshold. The pocket floor will have area = pocket_length × pocket_width, which for a typical pocket is well below 35% of the footprint. So it will **not** be captured by Section A and is available for Section D (blind) to claim.

Additional guards to avoid false positives:
- `nz > 0.92` — faces upward (consistent with a machined floor).
- `area_mm2 > 400 mm²` — ignore tiny slivers.
- `z_center` strictly interior: `part_z_min + 1 < z_center < part_z_max − 1`.
- `area_mm2 < footprint_area * 0.35` — ensures it is not the top surface.

### Relationship between blind and through detection

The blind pocket detection logic is **Section D-extended**, not a replacement:

- If a pocket candidate has matching internal walls **and** a qualifying floor face → **blind pocket**.
- If it has matching internal walls but **no** qualifying floor face → **through pocket / window** (current behaviour, unchanged).
- Both use the same `P001`, `P002`, … counter sequence.
- The two paths are mutually exclusive for any given set of walls.

---

## 4. Files Likely Affected

| File | Change |
|---|---|
| `modules/step_parser.py` | **Only file to modify.** Add floor-face lookup inside Section D of `_classify_face_records()`. |
| `modules/operation_planner.py` | No change needed. `_is_through_pocket` detection already handles the through case. The blind pocket uses the standard "Rough pocket clearance" / "Finish pocket walls and floor" notes, which are already correct. |
| `experiments/test_feature_candidates.py` | No change required. The existing script will display blind pocket candidates as-is. |
| `app.py` | No change required. Blind pocket candidates are `feature_type = "Pocket"`, same as through pocket. The review page and operation planner handle Pocket features already. |

---

## 5. Detection Logic

### Where to add the code

Inside `_classify_face_records()` in `modules/step_parser.py`, within the existing **Section D** for/for loop that iterates `_xpairs × _ypairs`.

The floor lookup runs **after** the cylinder guard and **before** `candidates.append()`. It determines whether the pocket is blind or through and sets the appropriate fields.

### Floor face lookup (pseudocode)

```python
# After passing all existing Section D guards (dimension, cylinder, used-walls)...

# Pocket XY bounds from the paired walls
x_lo = _xp["a"].get("center_x")   # left inner wall X
x_hi = _xp["b"].get("center_x")   # right inner wall X
y_lo = _yp["a"].get("center_y")   # front inner wall Y
y_hi = _yp["b"].get("center_y")   # rear inner wall Y

# Z range of the pocket from the wall overlap
wall_z_lo = _zlo          # bottom of wall Z overlap
wall_z_hi = _zhi          # top of wall Z overlap (≈ part top surface)

# Pocket floor candidate: a +Z PLANE face at intermediate Z
# with area matching pocket footprint, centre within pocket XY bounds
_floor_face = None
_floor_area_target = _px * _py   # px = X gap, py = Y gap

for _rf in face_records:
    if _rf.get("geom_type") != "PLANE":
        continue
    if (_rf.get("normal_z") or 0.0) < 0.92:
        continue                             # must face upward
    _fz = _rf.get("center_z") or 0.0
    # Strictly between the bottom of part and the top of the pocket walls
    if not (p_z_min + 1.0 < _fz < wall_z_hi - 1.0):
        continue
    # Centre must lie within the pocket XY footprint (with small tolerance)
    _fx = _rf.get("center_x") or 0.0
    _fy = _rf.get("center_y") or 0.0
    _tol_xy = max(_px, _py) * 0.20          # 20% tolerance on each axis
    if not (x_lo - _tol_xy <= _fx <= x_hi + _tol_xy):
        continue
    if not (y_lo - _tol_xy <= _fy <= y_hi + _tol_xy):
        continue
    # Area must be plausible for this pocket (within 30% of wall-pair area)
    _fa = _rf.get("area_mm2") or 0.0
    if _fa < 400.0:
        continue
    if _fa > _floor_area_target * 1.30:
        continue                             # too large — probably not this pocket's floor
    # Prefer the face with area closest to the expected pocket floor area
    if _floor_face is None or abs(_fa - _floor_area_target) < abs(
        (_floor_face.get("area_mm2") or 0) - _floor_area_target
    ):
        _floor_face = _rf

# Classify based on floor presence
if _floor_face is not None:
    _is_blind   = True
    _floor_z    = _floor_face.get("center_z") or wall_z_lo
    _depth      = round(wall_z_hi - _floor_z, 3)
    _confidence = "medium"
    _fname      = f"Pocket {_length:.1f}x{_width:.1f} mm"
    _floor_note = (
        f"Floor face #{_floor_face['face_index']} at z={_floor_z:.2f} mm "
        f"(area={(_floor_face.get('area_mm2') or 0):.1f} mm^2). "
        f"Depth from top = {_depth:.2f} mm."
    )
else:
    _is_blind   = False
    _depth      = round(_wall_lz, 3)         # existing through-pocket logic
    _confidence = "low"
    _fname      = f"Through pocket {_length:.1f}x{_width:.1f} mm"
    _floor_note = "No floor face detected -- treated as through pocket/window."

# Detection note
_pnote = (
    f"Paired internal PLANE walls — "
    f"X-pair: face #{...} (+X, cx={...:.2f}) and face #{...} (-X, cx={...:.2f}), "
    f"gap={_px:.2f} mm; "
    f"Y-pair: face #{...} (+Y, cy={...:.2f}) and face #{...} (-Y, cy={...:.2f}), "
    f"gap={_py:.2f} mm; "
    f"Z overlap {_zlo:.2f} to {_zhi:.2f} mm (wall lz={_wall_lz:.2f} mm). "
    + _floor_note
)
```

### Candidate fields for blind pocket

| Field | Value |
|---|---|
| `candidate_id` | `P001`, `P002`, … (shared counter with through pockets) |
| `feature_name` | `"Pocket 80.0x30.0 mm"` (no "Through" prefix) |
| `feature_type` | `"Pocket"` |
| `depth` | `wall_z_hi − floor_z` (top surface Z minus floor Z) |
| `confidence` | `"medium"` (floor face confirmed) |
| `detection_source` | `"paired_internal_walls"` |
| `detection_note` | Includes floor face index, floor Z, area, and computed depth |

### Candidate fields for through pocket (unchanged)

| Field | Value |
|---|---|
| `feature_name` | `"Through pocket 80.0x30.0 mm"` |
| `depth` | Wall Z span |
| `confidence` | `"low"` |
| `detection_note` | "No floor face detected -- treated as through pocket/window." |

---

## 6. Acceptance Criteria

1. **Blind pocket detected from a valid test sample**  
   Given a STEP file of a rectangular block with a blind pocket (depth < part height), one `Pocket` candidate is emitted with `confidence = "medium"` and `feature_name` not containing `"Through"`.

2. **Depth is computed from the floor face, not from wall span**  
   The candidate's `depth` field equals `(top surface Z) − (floor face Z)`, not the full part height.

3. **Detection note references the floor face**  
   The `detection_note` includes the floor face index, its Z position, and its area.

4. **Through pocket/window is not reclassified as blind**  
   Given `13_rectangular_pocket_blind.step` (no floor face), the candidate retains `feature_name = "Through pocket …"`, `confidence = "low"`, and the note says "No floor face detected".

5. **Face milling candidates are unaffected**  
   The top `+Z` surface and bottom `−Z` surface remain as Face Milling candidates (Section A). The pocket floor is not emitted as a Face Milling candidate because its area is below the 35% footprint threshold.

6. **Hole and slot candidates are unaffected**  
   Sections B and C produce the same output before and after this change.

7. **Operation planning produces correct notes**  
   A blind pocket accepted from the review page generates:  
   - Rough End Mill: `"Rough pocket clearance"` (existing note, correct for blind pocket)  
   - Finish End Mill: `"Finish pocket walls and floor"` (existing note, correct for blind pocket)  
   These are not `"through pocket/window"` notes.

8. **No new dependencies introduced**  
   The implementation uses only existing face record fields (`geom_type`, `normal_z`, `center_x/y/z`, `area_mm2`, `face_index`) already populated by `_extract_face_records()`.

---

## 7. Test Files

| File | Expected result |
|---|---|
| `M03_vmc_blind_rectangular_pocket.step` *(to be created)* | 1 blind Pocket candidate, `confidence = "medium"`, depth = actual pocket depth, floor face referenced in note |
| `13_rectangular_pocket_blind.step` *(existing)* | 1 through Pocket candidate unchanged, `confidence = "low"`, note says no floor face |
| `M04_vmc_through_pocket_window.step` *(to be created)* | 1 through Pocket candidate, no blind pocket emitted |
| `23_mixed_plate_holes_slot_pocket.step` *(existing)* | Holes and slot detected as before; any pocket in this file correctly classified |
| `25_vmc_job_plate_all_basic_features.step` *(existing)* | No false pocket candidates introduced; existing 5 candidates (F001, F002, H001, S001, S002) unchanged |
| `03_plate_4_blind_holes_d10_depth15.step` *(existing)* | No pocket candidates; blind hole bottoms do not trigger floor detection |

### Regression requirement

Run `test_feature_candidates.py` against all existing passing samples before and after the change. Candidate counts and types must match the pre-change baseline.

---

## 8. Edge Cases

| Case | Expected behaviour |
|---|---|
| **Floor face area ≠ exact pocket XY area** (corner fillets, chamfers on pocket floor) | Allow up to 30% tolerance on floor area relative to `pocket_length × pocket_width`. Pick the closest-matching face by area. |
| **Multiple horizontal faces at different Z levels** (stepped pockets, multiple floors) | Pick the floor face whose Z is closest to the pocket wall bottom Z. Emit one candidate per complete wall-set + floor pair. |
| **Very shallow pocket** (depth < 2 mm) | Still emit if wall Z span ≥ 2 mm. Depth is reported as-is. User can judge if it is a facing operation rather than a pocket. |
| **Floor face partially outside wall XY bounds** (pocket with island, partial floor) | XY tolerance (20%) accommodates slight misalignment. If no qualifying floor is found, emit as through pocket at `confidence = "low"`. |
| **Full-depth pocket (wall lz = part height)** with a bottom face that happens to be +Z | The bottom face is at `z = z_min`. The guard `z_center > part_z_min + 1` excludes it. Emitted as through pocket. |
| **Pocket walls also used by another feature** | `_used_p_walls` set prevents the same wall faces from being reused across two candidates. |
| **Part with no blind pockets (plain block, holes-only plate)** | Section D produces no pocket candidates. No regression on existing detections. |
| **CYLINDER faces within pocket bounds** | The existing CYLINDER guard already skips this region (slot territory). No blind pocket candidate is emitted for regions with rounded ends. |
| **Very high aspect-ratio pocket** (length/width ≥ 8) | Already excluded by `_P_MAX_ASPECT = 8.0`. Treated as slot territory. |
| **Off-axis pocket** (walls at 45°, not ±X/±Y) | Not detected. Section D only handles axis-aligned rectangular pockets. Non-axis-aligned pockets remain a known gap. |

---

## 9. Definition of Done

- [x] `_classify_face_records()` in `modules/step_parser.py` updated with floor-face lookup inside Section D.
- [x] `M03_vmc_blind_rectangular_pocket.step` test sample created (or sourced) and placed in `test_samples/`.
- [x] `python experiments/test_feature_candidates.py test_samples/M03_vmc_blind_rectangular_pocket.step` produces exactly one `Pocket` candidate with `confidence = medium` and the correct depth.
- [x] `python experiments/test_feature_candidates.py test_samples/13_rectangular_pocket_blind.step` still produces `"Through pocket 80.0x30.0 mm"` at `confidence = low` (no regression).
- [x] All existing passing STEP samples (`02`, `03`, `04`, `05`, `06`, `09`, `23`, `25`, `test5slotted`) produce the same candidate counts and types as before the change.
- [x] The blind pocket accepted from the Streamlit review page generates Rough + Finish End Mill operations with correct notes (not through-pocket notes). *(Verified by code inspection: blind pocket name does not contain "through pocket"/"window", so planner uses default notes "Rough pocket clearance" / "Finish pocket walls and floor".)*
- [x] No new Python dependencies introduced.
- [x] `modules/operation_planner.py`, `app.py`, `tool_selector.py`, `time_estimator.py`, and all other files are **not modified**.
- [x] PRD current-state document (`cnc_process_planner_prd_current_state.md`) updated to mark "True blind rectangular pocket detection" as Implemented in the Known Gaps table.
