# Chamfer Detection — Investigation and Analysis

**Date:** 2026-05-12  
**Branch:** v2-feature-review-engine  
**Scope:** Analysis only. No implementation changes in this document.  
**Primary sample:** `test_samples/M07_vmc_chamfered_plate.step`

---

## 1. Executive Summary

`M07_vmc_chamfered_plate.step` has four chamfer faces. All are PLANE surfaces with a 45° mixed normal (nz ≈ 0.707, and either |nx| or |ny| ≈ 0.707). All sit at z_center ≈ 24 mm — within 1 mm of the top face at z=25 mm. All have small areas (221–334 mm²) and small spans (2 mm chamfer width, full edge length in the long direction).

The current detector produces: `Face milling=2, Hole=4` — the 4 chamfer faces are invisible to Sections A–E. Chamfer detection requires a new Section F that targets this angled-PLANE-near-top-edge signature.

Additionally, `25_vmc_job_plate_all_basic_features.step` contains 6 angled PLANE faces with the same signature. These will also become Chamfer candidates after implementation, requiring a regression expectation update for that sample.

---

## 2. M07 Face Record Summary

**File:** `test_samples/M07_vmc_chamfered_plate.step`  
**Parser:** CadQuery 2.7.0  
**Total faces:** 14 (10 PLANE, 4 CYLINDER)  
**Part dimensions:** 80 mm (X) × 120 mm (Y) × 25 mm (Z)  
**XY footprint:** 9600 mm²

| # | geom_type | normal (x, y, z) | center (x, y, z) | area mm² | bbox (lx, ly, lz) | Role |
|---|-----------|-----------------|-----------------|----------|-------------------|------|
| 0 | PLANE | −1, 0, 0 | (−40, 0, 11.5) | 2760 | 0, 120, 23 | Outer left wall |
| 1 | PLANE | 0, +1, 0 | (0, 60, 11.5) | 1840 | 80, 0, 23 | Outer front wall |
| **2** | **PLANE** | **−0.707, 0, +0.707** | **(−39.01, 0, 23.99)** | **333.75** | **2, 120, 2** | **Chamfer — left-X top edge** |
| 3 | PLANE | 0, 0, −1 | (0, 0, 0) | 9398.9 | 80, 120, 0 | Bottom face |
| 4 | PLANE | 0, −1, 0 | (0, −60, 11.5) | 1840 | 80, 0, 23 | Outer rear wall |
| 5 | PLANE | +1, 0, 0 | (40, 0, 11.5) | 2760 | 0, 120, 23 | Outer right wall |
| **6** | **PLANE** | **0, +0.707, +0.707** | **(0, 59.01, 23.99)** | **220.62** | **80, 2, 2** | **Chamfer — front-Y top edge** |
| 7 | PLANE | 0, 0, +1 | (0, 0, 25) | 8614.94 | 76, 116, 0 | Top face (area reduced by chamfers) |
| **8** | **PLANE** | **0, −0.707, +0.707** | **(0, −59.01, 23.99)** | **220.62** | **80, 2, 2** | **Chamfer — rear-Y top edge** |
| 9 | CYLINDER | — | (0, 40, 12.5) | 628.3 | 8, 8, 25 | Hole Ø8mm |
| 10 | CYLINDER | — | (0, 20, 12.5) | 628.3 | 8, 8, 25 | Hole Ø8mm |
| 11 | CYLINDER | — | (0, −40, 12.5) | 628.3 | 8, 8, 25 | Hole Ø8mm |
| 12 | CYLINDER | — | (0, −20, 12.5) | 628.3 | 8, 8, 25 | Hole Ø8mm |
| **13** | **PLANE** | **+0.707, 0, +0.707** | **(39.01, 0, 23.99)** | **333.75** | **2, 120, 2** | **Chamfer — right-X top edge** |

---

## 3. Chamfer Face Identification

### The four chamfer faces

| Face # | normal | z_center | area mm² | chamfer size (mm) | edge |
|--------|--------|----------|----------|-------------------|------|
| 2 | (−0.707, 0, +0.707) | 23.99 | 333.75 | 2.0 | Left-X top edge (full 120mm length) |
| 6 | (0, +0.707, +0.707) | 23.99 | 220.62 | 2.0 | Front-Y top edge (full 80mm length) |
| 8 | (0, −0.707, +0.707) | 23.99 | 220.62 | 2.0 | Rear-Y top edge (full 80mm length) |
| 13 | (+0.707, 0, +0.707) | 23.99 | 333.75 | 2.0 | Right-X top edge (full 120mm length) |

### Chamfer size computation

Each chamfer face has two matching small spans (lx ≈ lz ≈ 2 mm, or ly ≈ lz ≈ 2 mm). The chamfer nominal width = min(lx, ly, lz) where we exclude the span that equals the full edge length.

For a 45° chamfer of nominal size `c` mm:
- The bevel face width = c / cos(45°) = c × √2 ≈ 1.414c
- Area = bevel_width × edge_length = 1.414c × L
- For c=2, L=120: area = 1.414 × 2 × 120 = 339.4 mm² ≈ 333.75 (difference due to mitered corners)
- For c=2, L=80: area = 1.414 × 2 × 80 = 226.3 mm² ≈ 220.62 ✓

Top face area: 8614.94 mm². Full footprint: 9600 mm². Reduction = 985 mm². Consistent with chamfers removing corners.  
Top face bbox: lx=76, ly=116 (= 80−4, 120−4 — confirming 2mm chamfer removed from each edge pair).

---

## 4. Key Detection Signals

### Signal 1 — Angled normal with upward component

All 4 chamfer faces have `nz ≈ 0.707` AND `|nx| ≈ 0.707` or `|ny| ≈ 0.707`.

```
nz  ∈ (0.40, 0.92)          # above horizontal, below flat-face threshold
max(|nx|, |ny|) ≥ 0.40     # significant horizontal component
```

This range covers standard 45° chamfers and allows for 30°–65° chamfer angles commonly seen in practice.

The upper bound `nz < 0.92` is the complement of Section A's face-milling threshold (`normal_z > 0.92`). Any face that Section A would classify as a top face is excluded here.

### Signal 2 — Near the top of the part

All 4 chamfer faces have `z_center ≈ 23.99 mm` where `part_z_max = 25.0 mm`.

```
z_center  >  part_z_max - max(8.0, part_height × 0.20)
```

The guard of 8 mm (or 20% of part height, whichever is larger) ensures that only faces very close to the top surface are considered. A face at mid-height that happens to be angled (e.g., a step shoulder) would not pass.

For M07: `part_z_max − 8 = 17 mm`. Chamfer faces at z=23.99 pass comfortably.

### Signal 3 — Small area

Chamfer faces are always smaller than their adjacent walls. For a 2×2 mm chamfer on a 120mm edge, area ≈ 334 mm². A more aggressive chamfer (e.g., 5mm × 200mm edge) would give 5×√2×200 ≈ 1414 mm².

```
area < _CH_MAX_AREA   (recommended: 2000 mm²)
```

This prevents large angled design faces from triggering chamfer detection.

### Signal 4 — Small span in at least one dimension

Each chamfer face has at least two small spans (≈ chamfer size), with the third span equal to the full edge length:

| Face | Small spans | Long span |
|------|-------------|-----------|
| #2 (−X edge) | lx=2, lz=2 | ly=120 |
| #6 (+Y edge) | ly=2, lz=2 | lx=80 |
| #8 (−Y edge) | ly=2, lz=2 | lx=80 |
| #13 (+X edge) | lx=2, lz=2 | ly=120 |

The minimum span of any chamfer face = chamfer_size (≈ 2 mm here). This can be used to estimate chamfer size:

```
chamfer_size_estimate = min(bbox_lx, bbox_ly, bbox_lz)   # ignoring zero-valued spans
```

---

## 5. False Positive Analysis

### 5.1 Drafted walls (angled but vertical-ish)

Mold-draft faces run from near the bottom to near the top of the part. They have angled normals (nz ≈ 0.1–0.3 for typical 2°–10° drafts) and LARGE area (area ≈ part height × edge length).

- **nz guard** (`nz > 0.40`): eliminates most draft angles (typical drafts have nz < 0.25).
- **Area guard** (`area < 2000`): draft faces on even a 50mm-high 100mm-long part = 5000+ mm².
- **Z guard**: draft faces span the full part height, so z_center ≈ part_z_max/2, not near the top.

**Verdict: Draft walls are safely excluded by all three guards.**

### 5.2 Step shoulder walls (Section E)

17b step sample — Section E detected the shoulder wall at face #4: `normal = (+1, 0, 0)`, `nz = 0`. Step shoulder walls are vertical (nz ≈ 0), not angled upward.

`nz > 0.40` requirement **completely excludes** step shoulder walls.

Additionally: 17b has **zero angled PLANE faces** confirmed by experiment. No false positive risk.

**Verdict: Zero overlap with step geometry.**

### 5.3 Pocket walls and slot side walls

All vertical inner walls (Section C/D geometry) have `nz ≈ 0`. Excluded by `nz > 0.40`.

**Verdict: Zero overlap.**

### 5.4 Freeform / BSPLINE / BEZIER surfaces

`geom_type == "PLANE"` filter already excludes all non-planar surfaces.

**Verdict: Zero overlap.**

### 5.5 Angled design faces (intentional oblique planes)

A part with a designed angled feature (e.g., a 45° cut for clearance) could produce a false positive. Guards:

- **Area < 2000 mm²**: if the angled face is large, it's excluded.
- **Z guard (near top)**: if the face is at mid-part, it's excluded.
- **Confidence "low"** when only 1 face found: single-face detection flagged for user review.

This is the primary residual risk. Mitigation: emit confidence="low" for single chamfer faces, "medium" for 3+ faces forming a consistent pattern.

### 5.6 Countersink faces (CONE geometry)

CONE faces can have angled normals but are `geom_type == "CONE"`, not `"PLANE"`.

**Verdict: Zero overlap.**

### 5.7 Sample 25 — Unintended chamfer detection in regression baseline

`25_vmc_job_plate_all_basic_features.step` **does contain** top-edge angled PLANE faces with nz=0.707:
- 6 faces confirmed: areas 254–984 mm², all at z_center ≈ 49 mm (part height ≈ 50 mm)

These are legitimate chamfers on the 25-sample part. After chamfer detection is implemented, sample 25 will produce `Chamfer=1` in addition to its existing candidates.

**Impact:** The regression expectation for sample 25 must be updated from `{Face milling=2, Slot=2, Large hole / boring=1}` to `{Face milling=2, Slot=2, Large hole / boring=1, Chamfer=1}`.

Sample M07 expectation must also be updated from `{Face milling=2, Hole=4}` to `{Face milling=2, Hole=4, Chamfer=1}`.

---

## 6. Proposed Detection Heuristic

### 6.1 Algorithm overview (pseudocode)

```python
# Section F — Chamfer candidates
# Runs after Sections A–E (face milling, holes, slots, pockets, steps).
# Collects PLANE faces with angled-upward normals that sit near the top of the part.
# Groups all qualifying faces into a single Chamfer candidate per detection pass.

_CH_NZ_MIN     = 0.40    # nz lower bound (~24° from horizontal)
_CH_NZ_MAX     = 0.92    # nz upper bound (just below Section A face-milling threshold)
_CH_HORIZ_MIN  = 0.40    # |nx| or |ny| must be significant — truly angled, not nearly flat
_CH_MAX_AREA   = 2000.0  # mm² — single-face area upper bound
_CH_Z_FRAC     = 0.20    # z_center must be within this fraction of part height from top
                          # or within 8 mm — whichever is larger

p_z_max = part_bbox["z_range"][1]
_ch_z_threshold = p_z_max - max(8.0, part_height * _CH_Z_FRAC)

_ch_faces = []
for _r in face_records:
    if _r.get("geom_type") != "PLANE":
        continue
    _nz  = _r.get("normal_z") or 0.0
    _nx  = abs(_r.get("normal_x") or 0.0)
    _ny  = abs(_r.get("normal_y") or 0.0)
    _area = _r.get("area_mm2") or 0.0
    _cz   = _r.get("center_z") or 0.0

    if not (_CH_NZ_MIN <= _nz <= _CH_NZ_MAX):
        continue    # nz out of angled range
    if max(_nx, _ny) < _CH_HORIZ_MIN:
        continue    # no significant horizontal component
    if _area > _CH_MAX_AREA:
        continue    # face too large to be a simple chamfer
    if _cz < _ch_z_threshold:
        continue    # face not near the top of the part

    _ch_faces.append(_r)

if _ch_faces:
    # Estimate chamfer size from small spans
    _sizes = []
    for _cf in _ch_faces:
        _lx = _cf.get("bbox_length_x") or 0.0
        _ly = _cf.get("bbox_length_y") or 0.0
        _lz = _cf.get("bbox_length_z") or 0.0
        _non_zero = [v for v in [_lx, _ly, _lz] if v > 0.1]
        if _non_zero:
            _sizes.append(min(_non_zero))
    _ch_size  = round(sum(_sizes) / len(_sizes), 1) if _sizes else 0.0
    _n_faces  = len(_ch_faces)
    _conf     = "medium" if _n_faces >= 3 else "low"
    _ch_note  = (
        f"{_n_faces} angled PLANE face(s) near top of part "
        f"(nz ≈ 0.707 ± 0.3, z_center ≥ {_ch_z_threshold:.1f} mm); "
        f"estimated chamfer width ≈ {_ch_size:.1f} mm from bbox small span."
    )
    candidates.append({
        "candidate_id":     "CH001",
        "feature_name":     f"Top outer edge chamfer ~{_ch_size:.1f}×{_ch_size:.1f} mm "
                            f"({_n_faces} faces)",
        "feature_type":     "Chamfer",
        "quantity":         _n_faces,
        "confidence":       _conf,
        "detection_source": "angled_plane_near_top",
        "detection_note":   _ch_note,
        "length": None, "width": None,
        "depth":  _ch_size,
        "diameter": None,
        "x_pos": 0.0, "y_pos": 0.0,
        "tolerance_note": "",
        "priority": 4,
        "accepted": False, "ignored": False,
    })
```

### 6.2 Expected output for M07

| Signal | Value |
|--------|-------|
| Faces collected | 4 (#2, #6, #8, #13) |
| All pass nz guard? | Yes — nz=0.707 ∈ [0.40, 0.92] |
| All pass horiz guard? | Yes — max(|nx|,|ny|) = 0.707 ≥ 0.40 |
| All pass area guard? | Yes — max area = 334 mm² < 2000 |
| All pass z guard? | Yes — z_center=24 > 25−max(8,25×0.2)=25−8=17 |
| Estimated chamfer size | 2.0 mm |
| Confidence | "medium" (≥ 3 faces) |
| feature_name | "Top outer edge chamfer ~2.0×2.0 mm (4 faces)" |

### 6.3 Expected output for sample 25

| Signal | Value |
|--------|-------|
| Faces collected | 6 (#1, #20, #22, #32, #35, #36) |
| Part height | ≈ 50 mm |
| z guard threshold | 50 − max(8, 50×0.2) = 50 − 10 = 40 mm |
| All pass? | Yes — z_center ≈ 49 > 40 |
| Confidence | "medium" |
| feature_name | "Top outer edge chamfer ~2.0×2.0 mm (6 faces)" |

---

## 7. Threshold Calibration Table

| Sample | Angled PLANE faces? | Expected result after implementation |
|--------|---------------------|--------------------------------------|
| M07 chamfered plate | 4 (confirmed) | Chamfer=1 ✓ |
| 25 all-features | 6 (confirmed) | Chamfer=1 (regression update needed) |
| 17b step shoulder | 0 (confirmed) | No chamfer candidates ✓ |
| 23 mixed | 0 PLANE (3 CONE) | No chamfer candidates ✓ |
| test5slotted | 0 (confirmed) | No chamfer candidates ✓ |
| 01 plain block | None expected | No chamfer candidates ✓ |
| M03 blind pocket | None expected | No chamfer candidates ✓ |
| M04 through pocket | None expected | No chamfer candidates ✓ |

---

## 8. Operation Planner Compatibility

`modules/operation_planner.py` already contains:

```python
"Chamfer": [
    {"op": "Chamfer", "notes": "Chamfer edges"},
],
```

And in `estimate_path_length()`:
```python
if ftype == "Chamfer":
    return (diameter or 10) * 3.14 * qty
```

The existing Chamfer rule is designed for hole-edge chamfers (using diameter). For outer-edge chamfers, the path length should be perimeter-based (2 × (part_length + part_width)). This is a known gap but out of scope for the detection story — the planner already produces a usable (if approximate) estimate.

The `_context_note` function has no Chamfer case yet. Could add later as an improvement.

---

## 9. Summary of Key Findings

| Finding | Detail |
|---------|--------|
| Signal | PLANE, nz ∈ (0.40, 0.92), max(|nx|,|ny|) ≥ 0.40, area < 2000, z_center near top |
| Chamfer size | min(small bbox spans) — 2.0 mm for M07 |
| Grouping | All qualifying faces → single CH001 candidate |
| Confidence | "medium" if ≥ 3 faces; "low" if 1–2 |
| Implementation file | `modules/step_parser.py` only |
| False positive risk | Low — PLANE filter, area guard, Z guard eliminate all known non-chamfer geometries |
| Regression impact | M07 and sample 25 need updated expectations; all other 16 samples unchanged |
| Op planner | No change needed — existing "Chamfer" rule already handles it |
