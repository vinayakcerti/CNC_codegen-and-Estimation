"""
experiments/test_cadquery_step_import.py

Standalone investigation script: tests whether CadQuery can read a STEP file
that fails the lightweight regex parser.

Usage:
    python experiments/test_cadquery_step_import.py path/to/file.step

Requires CadQuery. If not installed:
    pip install cadquery
or (recommended, conda):
    conda install -c conda-forge cadquery
"""

import sys
import os


# ── 1. Argument handling ─────────────────────────────────────────────────────

def _usage():
    print()
    print("Usage:")
    print("  python experiments/test_cadquery_step_import.py <path_to_step_file>")
    print()
    print("Example:")
    print("  python experiments/test_cadquery_step_import.py my_part.step")
    print()


if len(sys.argv) < 2:
    print("ERROR: No STEP file path provided.")
    _usage()
    sys.exit(1)

step_path = sys.argv[1]

if not os.path.isfile(step_path):
    print(f"ERROR: File not found: {step_path}")
    _usage()
    sys.exit(1)

file_size_kb = os.path.getsize(step_path) / 1024
print()
print("=" * 60)
print("  CadQuery STEP Import Investigation Script")
print("=" * 60)
print(f"  File  : {step_path}")
print(f"  Size  : {file_size_kb:.1f} KB")
print("=" * 60)


# ── 2. CadQuery import check ─────────────────────────────────────────────────

try:
    import cadquery as cq
    print(f"\n[OK] cadquery imported successfully (version: {cq.__version__})")
except ImportError:
    print()
    print("[FAIL] cadquery is not installed.")
    print()
    print("To install CadQuery, choose one of the following:")
    print()
    print("  Option A — pip (simplest, may have OCC dependency issues on Windows):")
    print("    pip install cadquery")
    print()
    print("  Option B — conda (recommended, bundles OpenCASCADE correctly):")
    print("    conda install -c conda-forge cadquery")
    print()
    print("  Option C — mamba (faster conda alternative):")
    print("    mamba install -c conda-forge cadquery")
    print()
    print("  After installing, re-run this script.")
    print()
    sys.exit(1)
except Exception as exc:
    print(f"\n[FAIL] cadquery import raised an unexpected error: {exc}")
    sys.exit(1)


# ── 3. Load the STEP file ─────────────────────────────────────────────────────

print(f"\nLoading STEP file...")
try:
    result = cq.importers.importStep(step_path)
    print(f"[OK] File loaded.")
except Exception as exc:
    print(f"[FAIL] CadQuery could not load the file: {exc}")
    print()
    print("Possible reasons:")
    print("  - File is corrupted or truncated")
    print("  - File uses an unsupported STEP schema")
    print("  - File is a STEP assembly with missing referenced parts")
    sys.exit(1)


# ── 4. Shape inspection ──────────────────────────────────────────────────────

print()
print("-" * 40)
print("  Shape Inspection")
print("-" * 40)

# Solids
try:
    solids = result.solids().vals()
    print(f"  Solids      : {len(solids)}")
except Exception:
    print("  Solids      : (could not count)")

# Shells
try:
    shells = result.shells().vals()
    print(f"  Shells      : {len(shells)}")
except Exception:
    print("  Shells      : (could not count)")

# Faces
try:
    faces = result.faces().vals()
    print(f"  Faces       : {len(faces)}")
except Exception:
    print("  Faces       : (could not count)")

# Edges
try:
    edges = result.edges().vals()
    print(f"  Edges       : {len(edges)}")
except Exception:
    print("  Edges       : (could not count)")

# Vertices
try:
    vertices = result.vertices().vals()
    print(f"  Vertices    : {len(vertices)}")
except Exception:
    print("  Vertices    : (could not count)")


# ── 5. Bounding box ──────────────────────────────────────────────────────────

print()
print("-" * 40)
print("  Bounding Box (mm)")
print("-" * 40)

try:
    bb = result.val().BoundingBox()
    length = round(bb.xmax - bb.xmin, 4)
    width  = round(bb.ymax - bb.ymin, 4)
    height = round(bb.zmax - bb.zmin, 4)
    print(f"  X (length)  : {bb.xmin:.4f} → {bb.xmax:.4f}  span = {length} mm")
    print(f"  Y (width)   : {bb.ymin:.4f} → {bb.ymax:.4f}  span = {width} mm")
    print(f"  Z (height)  : {bb.zmin:.4f} → {bb.zmax:.4f}  span = {height} mm")
    print()
    print(f"  Bounding box: {length} × {width} × {height} mm")
    bbox_vol = round(length * width * height / 1000.0, 4)
    print(f"  Bbox volume : {bbox_vol} cm³")
except Exception as exc:
    print(f"  [FAIL] Could not compute bounding box: {exc}")


# ── 6. Volume ────────────────────────────────────────────────────────────────

print()
print("-" * 40)
print("  Volume")
print("-" * 40)

try:
    # CadQuery returns volume in mm³ from the underlying OCC shape
    volume_mm3 = result.val().Volume()
    volume_cm3 = round(volume_mm3 / 1000.0, 4)
    print(f"  Part volume : {volume_mm3:.2f} mm³  ({volume_cm3} cm³)")
    try:
        bbox_vol_check = length * width * height / 1000.0
        ratio = round(volume_cm3 / bbox_vol_check * 100, 1) if bbox_vol_check > 0 else "—"
        print(f"  Vol/Bbox    : {ratio}%  (our parser hardcodes 60% — real value is above)")
    except Exception:
        pass
except Exception as exc:
    print(f"  [FAIL] Could not compute volume: {exc}")
    print("  Note: volume requires a closed solid, not just a surface shell.")


# ── 7. Face type breakdown ───────────────────────────────────────────────────

print()
print("-" * 40)
print("  Face Type Breakdown")
print("-" * 40)

try:
    from OCC.Core.BRep import BRep_Tool
    from OCC.Core.GeomAbs import (
        GeomAbs_Plane, GeomAbs_Cylinder, GeomAbs_Cone,
        GeomAbs_Sphere, GeomAbs_Torus, GeomAbs_BSplineSurface,
        GeomAbs_BezierSurface, GeomAbs_OtherSurface,
    )
    from OCC.Core.BRepAdaptor import BRepAdaptor_Surface

    type_names = {
        GeomAbs_Plane:          "Planar",
        GeomAbs_Cylinder:       "Cylindrical",
        GeomAbs_Cone:           "Conical",
        GeomAbs_Sphere:         "Spherical",
        GeomAbs_Torus:          "Toroidal",
        GeomAbs_BSplineSurface: "B-Spline",
        GeomAbs_BezierSurface:  "Bezier",
        GeomAbs_OtherSurface:   "Other",
    }

    type_counts = {}
    for face in result.faces().vals():
        adaptor = BRepAdaptor_Surface(face.wrapped)
        surf_type = adaptor.GetType()
        label = type_names.get(surf_type, f"Unknown({surf_type})")
        type_counts[label] = type_counts.get(label, 0) + 1

    for label, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        print(f"  {label:<20}: {count}")

    cyl_count = type_counts.get("Cylindrical", 0)
    if cyl_count > 0:
        print()
        print(f"  → {cyl_count} cylindrical face(s) detected.")
        print("    These likely correspond to drilled holes or turned features.")

except ImportError:
    print("  (OCC surface type analysis not available — skipping face breakdown)")
    print("  Install python-occ or use conda cadquery for full OCC access.")
except Exception as exc:
    print(f"  (Face type breakdown failed: {exc})")


# ── 8. Summary ───────────────────────────────────────────────────────────────

print()
print("=" * 60)
print("  Summary")
print("=" * 60)
print()
print("  CadQuery successfully loaded this file.")
print("  Our lightweight regex parser failed on it because it likely")
print("  uses B-spline/NURBS surfaces or a STEP schema where")
print("  CARTESIAN_POINTs are not in the expected inline format.")
print()
print("  Next steps:")
print("  1. Note the bounding box and volume above.")
print("  2. Compare with what our parser reports (or fails to report).")
print("  3. If the numbers look correct, CadQuery is a viable upgrade")
print("     for the bounding box extraction path.")
print("  4. Report findings before modifying app.py or step_parser.py.")
print()
