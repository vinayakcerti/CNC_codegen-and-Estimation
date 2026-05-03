"""
experiments/test_parse_step_auto.py

Tests parse_step_auto() — the new dispatcher that tries CadQuery first
and falls back to the lightweight regex parser.

Usage:
    python experiments/test_parse_step_auto.py <path_to_step_file>

Works whether or not CadQuery is installed:
  - With CadQuery   → reports which parser ran and shows real solid volume
  - Without CadQuery → runs lightweight parser exactly as app.py does today
"""

import sys
import os

# Force UTF-8 output on Windows consoles (handles → and other non-ASCII chars)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Allow running from the repo root or from experiments/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from modules.step_parser import parse_step_auto, _CADQUERY_AVAILABLE


# ── Argument handling ────────────────────────────────────────────────────────

def _usage():
    print()
    print("Usage:")
    print("  python experiments/test_parse_step_auto.py <path_to_step_file>")
    print()
    print("Example:")
    print("  python experiments/test_parse_step_auto.py test_samples/my_part.step")
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


# ── Environment banner ───────────────────────────────────────────────────────

file_size_kb = os.path.getsize(step_path) / 1024

print()
print("=" * 62)
print("  parse_step_auto() — dispatcher test")
print("=" * 62)
print(f"  File           : {step_path}")
print(f"  Size           : {file_size_kb:.1f} KB")
print(f"  CadQuery avail : {'YES' if _CADQUERY_AVAILABLE else 'NO  (will use lightweight parser)'}")
print("=" * 62)


# ── Read file bytes ──────────────────────────────────────────────────────────

with open(step_path, "rb") as f:
    file_bytes = f.read()


# ── Run the dispatcher ───────────────────────────────────────────────────────

print("\nRunning parse_step_auto() ...")
result = parse_step_auto(file_bytes)
print("Done.\n")


# ── Results ──────────────────────────────────────────────────────────────────

sep = "-" * 40

print(sep)
print("  Core result")
print(sep)
print(f"  success      : {result.get('success')}")
print(f"  parser_used  : {result.get('parser_used', '(not set)')}")
print(f"  message      : {result.get('message', '—')}")

if not result.get("success"):
    print()
    print("  Parse failed.")
    print(f"  failure_reason : {result.get('failure_reason', '—')}")
    print(f"  detail         : {result.get('detail', '—')}")
    print(f"  suggestion     : {result.get('suggestion', '—')}")
    sys.exit(0)

print()
print(sep)
print("  Dimensions")
print(sep)
print(f"  length_mm    : {result.get('length_mm')} mm")
print(f"  width_mm     : {result.get('width_mm')} mm")
print(f"  height_mm    : {result.get('height_mm')} mm")

print()
print(sep)
print("  Coordinate ranges (mm)")
print(sep)
x = result.get("x_range", ("—", "—"))
y = result.get("y_range", ("—", "—"))
z = result.get("z_range", ("—", "—"))
print(f"  X            : {x[0]} → {x[1]}")
print(f"  Y            : {y[0]} → {y[1]}")
print(f"  Z            : {z[0]} → {z[1]}")

print()
print(sep)
print("  Volumes")
print(sep)
print(f"  stock_volume_cm3   : {result.get('stock_volume_cm3')} cm³")
print(f"  part_volume_cm3    : {result.get('part_volume_cm3')} cm³")
removed = result.get("removed_volume_cm3")
if removed is None:
    # lightweight parser doesn't compute this — derive it
    sv = result.get("stock_volume_cm3") or 0
    pv = result.get("part_volume_cm3") or 0
    removed = round(max(sv - pv, 0), 3)
    print(f"  removed_volume_cm3 : {removed} cm³  (derived)")
else:
    print(f"  removed_volume_cm3 : {removed} cm³")

print()
print(sep)
print("  Unit / detection metadata")
print(sep)
print(f"  detection_method   : {result.get('detection_method', '—')}")
print(f"  detected_unit_label: {result.get('detected_unit_label', '—')}")
print(f"  conversion_factor  : {result.get('conversion_factor', '—')}")
print(f"  converted          : {result.get('converted', '—')}")
print(f"  point_count        : {result.get('point_count', '—')}")

# CadQuery fallback warning (only present when CadQuery was tried but failed)
cadquery_warning = result.get("cadquery_warning")
if cadquery_warning:
    print()
    print(sep)
    print("  CadQuery fallback warning")
    print(sep)
    print(f"  {cadquery_warning}")

# Soft warnings from parser
warnings = result.get("warnings", [])
if warnings:
    print()
    print(sep)
    print(f"  Warnings ({len(warnings)})")
    print(sep)
    for i, w in enumerate(warnings, 1):
        print(f"  [{i}] {w}")

print()
print("=" * 62)
print("  Test complete.")
print("=" * 62)
print()
