"""Verify body-28 per-diameter hole split against Toolpath's published values.

Toolpath (same plate): 7x O5 + 4x O9.8 + 8x counterbore(O11/O18) + 2x O20
+ 1x O25 = 22 hole positions.
"""
import sys, io, math
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.path.insert(0, r'C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro')

import cadquery as cq
from modules.weldment.slot_hole_classifier import (
    _cyl_data, _axial_span, _perp_axis_distance,
    classify_cylindrical_faces, _SAME_AXIS_DIST_MM, _AXIS_PARALLEL_DOT,
)

STEP = (r'C:\Users\vinay\OneDrive\AI Apps\CNC-Plan-and-Process-Pro'
        r'\test_samples\3100171001_01 SLIDE BASE-1812 ( FOR TOOL LOADER ).STEP')
solid = cq.importers.importStep(STEP).val().Solids()[27]  # Body 28
faces = solid.Faces()
bb = solid.BoundingBox()
bbox = {"xmin": bb.xmin, "xmax": bb.xmax, "ymin": bb.ymin,
        "ymax": bb.ymax, "zmin": bb.zmin, "zmax": bb.zmax}

cls = classify_cylindrical_faces(faces, bbox=bbox)
print(f"classifier: hole_count={cls['hole_count']} slot_count={cls['slot_count']}")

# Rebuild hole AXES (merge same axis line regardless of radius = counterbore
# collapses to one position, exactly how the classifier counts).
hole_face_idx = [fi for fi, cat in cls["face_categories"].items() if cat == "hole"]
recs = []
for fi in hole_face_idx:
    d = _cyl_data(faces[fi])
    if d:
        d["fi"] = fi
        recs.append(d)

axes = []  # each: {loc, dir, radii:set}
for r in recs:
    placed = False
    for ax in axes:
        dot = abs(r["dir"][0]*ax["dir"][0] + r["dir"][1]*ax["dir"][1] + r["dir"][2]*ax["dir"][2])
        if dot >= _AXIS_PARALLEL_DOT and _perp_axis_distance(ax, r) <= _SAME_AXIS_DIST_MM:
            ax["radii"].add(round(r["radius"], 2))
            placed = True
            break
    if not placed:
        axes.append({"loc": r["loc"], "dir": r["dir"], "radii": {round(r["radius"], 2)}})

print(f"distinct hole axes: {len(axes)}")

# Per-position table: label counterbores by their radius pair
from collections import Counter
table = Counter()
for ax in axes:
    radii = sorted(ax["radii"])
    if len(radii) > 1:
        label = "cbore " + "/".join(f"O{2*r:.1f}" for r in radii)
    else:
        label = f"O{2*radii[0]:.1f}"
    table[label] += 1

print("\nOURS (per position):")
for label, n in sorted(table.items()):
    print(f"  {n}x {label}")

print("\nTOOLPATH:  7x O5.0 | 4x O9.8 | 8x cbore O11/O18 | 2x O20.0 | 1x O25.0  (= 22)")

expected = {"O5.0": 7, "O9.8": 4, "O20.0": 2, "O25.0": 1}
ours_simple = {k: v for k, v in table.items() if not k.startswith("cbore")}
cbore_total = sum(v for k, v in table.items() if k.startswith("cbore"))
print(f"\ncbore positions: ours={cbore_total} vs theirs=8 -> {'MATCH' if cbore_total==8 else 'DIFFER'}")
ok = cbore_total == 8
for k, v in expected.items():
    got = ours_simple.get(k, 0)
    status = "MATCH" if got == v else "DIFFER"
    if got != v:
        ok = False
    print(f"{k}: ours={got} vs theirs={v} -> {status}")
print(f"\nTOTAL: ours={len(axes)} vs theirs=22 -> {'MATCH' if len(axes)==22 else 'DIFFER'}")
print("\nRESULT:", "EXACT PER-DIAMETER MATCH" if ok and len(axes)==22 else "SPLIT DIFFERS — see table above")
