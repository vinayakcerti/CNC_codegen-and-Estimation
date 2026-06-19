"""
experiments/test_face_records.py

Extract and display raw per-face geometry data from a STEP file.
Uses _extract_face_records() from modules/step_parser.py.

Purpose: investigation only — no feature classification yet.
         Run this to understand what CadQuery/OCC reports for each
         face type before writing any detection logic.

Usage:
    python experiments/test_face_records.py <path_to_step_file>

Example:
    python experiments/test_face_records.py test_samples/test5slotted.step

Requires:
    CadQuery installed (conda install -c conda-forge cadquery)
"""

import sys
import os
from collections import Counter

# UTF-8 output — handles ² and → on Windows consoles
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Allow running from repo root or from experiments/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Argument handling ────────────────────────────────────────────────────────

def _usage():
    print()
    print("Usage:")
    print("  python experiments/test_face_records.py <path_to_step_file>")
    print()
    print("Example:")
    print("  python experiments/test_face_records.py test_samples/test5slotted.step")
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


# ── CadQuery availability check ──────────────────────────────────────────────

try:
    import cadquery as cq
    cq_version = getattr(cq, "__version__", "unknown")
except ImportError:
    print()
    print("ERROR: CadQuery is not installed.")
    print()
    print("To install:")
    print("  conda install -c conda-forge cadquery   (recommended)")
    print("  pip install cadquery                    (may have OCC issues on Windows)")
    print()
    sys.exit(1)
except Exception as exc:
    print(f"ERROR: CadQuery import failed unexpectedly: {exc}")
    sys.exit(1)


# ── Import the extractor ─────────────────────────────────────────────────────

from modules.step_parser import _extract_face_records, _OCC_ADAPTOR_AVAILABLE


# ── Header ───────────────────────────────────────────────────────────────────

file_size_kb = os.path.getsize(step_path) / 1024

print()
print("=" * 74)
print("  Face Records — CadQuery per-face geometry investigation")
print("=" * 74)
print(f"  File        : {step_path}")
print(f"  Size        : {file_size_kb:.1f} KB")
print(f"  CadQuery    : {cq_version}")
print(f"  OCC adaptor : "
      f"{'available — precise cylinder radius / axis' if _OCC_ADAPTOR_AVAILABLE else 'unavailable — cylinder fields will be None'}")
print("=" * 74)


# ── Load STEP file ───────────────────────────────────────────────────────────

print()
print("Loading STEP file via CadQuery...")
try:
    cq_result = cq.importers.importStep(step_path)
    print("OK")
except Exception as exc:
    print(f"ERROR: CadQuery could not load file: {exc}")
    sys.exit(1)


# ── Extract face records ���────────────────────────────────────────────────────

print("Extracting face records...")
records = _extract_face_records(cq_result)

if not records:
    print("No face records returned.")
    print("The file may be a surface shell, an empty STEP, or contain")
    print("no topology that CadQuery can iterate.")
    sys.exit(0)

print(f"OK — {len(records)} face(s) found")


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fv(v, width=9, dec=3):
    """Format a float value, right-aligned.  None → right-aligned dash."""
    if v is None:
        return " " * (width - 1) + "—"
    return f"{v:{width}.{dec}f}"


def _ft(x, y, z, dec=2):
    """Format an (x, y, z) triplet.  None values collapse to em-dashes."""
    if x is None:
        return "(    —,     —,     —)"
    return f"({x:8.{dec}f},{y:8.{dec}f},{z:8.{dec}f})"


# ── Main face table ───────────────────────────────────────────────────────────

# Columns: idx  type  area  center(x,y,z)  normal(x,y,z)  spans(lx,ly,lz)
HDR = (
    f"  {'#':>3}  "
    f"{'Type':<10}  "
    f"{'Area mm²':>11}  "
    f"{'Center (x, y, z)':^26}  "
    f"{'Normal (x, y, z)':^26}  "
    f"{'Spans (lx, ly, lz)':^26}"
)
SEP = "  " + "-" * (len(HDR) - 2)

print()
print("-" * 74)
print("  All faces")
print("-" * 74)
print(HDR)
print(SEP)

for r in records:
    gtype    = (r["geom_type"] or "—")[:10]
    area_str = _fv(r["area_mm2"], width=11, dec=4)
    ctr      = _ft(r["center_x"], r["center_y"], r["center_z"], dec=2)
    nrm      = _ft(r["normal_x"], r["normal_y"], r["normal_z"], dec=4)
    spn      = _ft(r["bbox_length_x"], r["bbox_length_y"], r["bbox_length_z"], dec=2)
    print(f"  {r['face_index']:>3}  {gtype:<10}  {area_str}  {ctr}  {nrm}  {spn}")


# ── Cylindrical faces detail ──────────────────────────────────────────────────

cyl_records = [r for r in records if r.get("geom_type") == "CYLINDER"]

if cyl_records:
    print()
    print("-" * 74)
    print("  Cylindrical faces — radius and axis detail")
    print("-" * 74)
    if not _OCC_ADAPTOR_AVAILABLE:
        print("  (OCC adaptor unavailable — cylinder_radius_mm and axis fields are None)")
        print("  (Install cadquery-ocp / use conda cadquery for full OCC access)")
    print()

    CYL_HDR = (
        f"  {'#':>3}  "
        f"{'Radius mm':>10}  "
        f"{'Axis (x, y, z)':^26}  "
        f"{'Center (x, y, z)':^26}  "
        f"{'BBox Z':>10}  "
        f"{'BBox depth':>11}"
    )
    print(CYL_HDR)
    print("  " + "-" * (len(CYL_HDR) - 2))

    for r in cyl_records:
        r_str    = _fv(r["cylinder_radius_mm"], width=10, dec=4)
        ax_str   = _ft(r["cylinder_axis_x"], r["cylinder_axis_y"],
                       r["cylinder_axis_z"], dec=4)
        ctr_str  = _ft(r["center_x"], r["center_y"], r["center_z"], dec=2)
        z_str    = _fv(r["bbox_zmin"], width=10, dec=3)
        dep_str  = _fv(r["bbox_length_z"], width=11, dec=3)
        print(f"  {r['face_index']:>3}  {r_str}  {ax_str}  {ctr_str}  {z_str}  {dep_str}")


# ── Planar faces — normal distribution ──────────────────────────────────────

plane_records = [r for r in records if r.get("geom_type") == "PLANE"]

if plane_records:
    print()
    print("-" * 74)
    print("  Planar faces — normal directions (useful for setup orientation)")
    print("-" * 74)

    # Bucket each normal into axis-aligned bins for readability
    def _normal_bucket(nx, ny, nz, tol=0.05):
        if nx is None:
            return "unknown"
        if abs(nz) > 1 - tol:
            return "+Z (top/floor)"  if nz > 0 else "-Z (bottom)"
        if abs(nx) > 1 - tol:
            return "+X (right wall)" if nx > 0 else "-X (left wall)"
        if abs(ny) > 1 - tol:
            return "+Y (front wall)" if ny > 0 else "-Y (rear wall)"
        # Angled
        if abs(nz) > 0.35:
            return f"angled  (nz={nz:.3f}, likely chamfer or draft)"
        return f"other   ({nx:.3f},{ny:.3f},{nz:.3f})"

    PLN_HDR = (
        f"  {'#':>3}  "
        f"{'Area mm²':>11}  "
        f"{'Normal':^26}  "
        f"{'Direction bucket':<36}  "
        f"{'Z center':>9}"
    )
    print(PLN_HDR)
    print("  " + "-" * (len(PLN_HDR) - 2))

    for r in sorted(plane_records, key=lambda x: -(x["area_mm2"] or 0)):
        area_str   = _fv(r["area_mm2"], width=11, dec=3)
        nrm_str    = _ft(r["normal_x"], r["normal_y"], r["normal_z"], dec=4)
        bucket_str = _normal_bucket(r["normal_x"], r["normal_y"], r["normal_z"])
        z_ctr      = _fv(r["center_z"], width=9, dec=3)
        print(f"  {r['face_index']:>3}  {area_str}  {nrm_str}  {bucket_str:<36}  {z_ctr}")


# ── Summary by surface type ───────────────────────────────────────────────────

type_counts = Counter(r.get("geom_type") or "UNKNOWN" for r in records)

print()
print("=" * 74)
print("  Summary by surface type")
print("=" * 74)
for gtype, count in sorted(type_counts.items(), key=lambda x: -x[1]):
    bar = "█" * count
    print(f"  {gtype:<14}: {count:>4}  {bar}")
print(f"  {'TOTAL':<14}: {len(records):>4}")

# Area range per type
print()
print("  Area range per type  (min → max mm²)")
print("  " + "-" * 44)
for gtype in sorted(type_counts):
    areas = [r["area_mm2"] for r in records
             if r.get("geom_type") == gtype and r["area_mm2"] is not None]
    if areas:
        print(f"  {gtype:<14}: {min(areas):>10.3f} → {max(areas):.3f}")
    else:
        print(f"  {gtype:<14}:        — → —")

print()
print("=" * 74)
print("  Notes for feature detection planning:")
print("=" * 74)
print()
print("  PLANE  + normal ≈ ±Z → facing surface (top/bottom)")
print("  PLANE  + normal ≈ ±X or ±Y → wall (outer profile, pocket wall, slot wall)")
print("  PLANE  + angled normal → chamfer or draft angle")
print("  CYLINDER (axis ≈ Z) → hole or bore (radius < ~12.5mm = drill, else bore)")
print("  CYLINDER (axis ≠ Z) → side-drilled or off-axis feature (defer)")
print("  BSPLINE / BEZIER → freeform — skip for now")
print("  CONE / TORUS → countersink, fillet — defer")
print()
print("  Dominant normal directions above indicate natural setup orientations.")
print()
