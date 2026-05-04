"""
experiments/test_feature_candidates.py

Detect and display preliminary machinable feature candidates from a STEP file
using CadQuery face records.

Calls detect_feature_candidates_from_cadquery_file() from
modules/step_parser.py.  Experiment only — does not modify the main app.

Usage:
    python experiments/test_feature_candidates.py <path_to_step_file>

Example:
    python experiments/test_feature_candidates.py test_samples/test5slotted.step

Requires:
    CadQuery installed (conda install -c conda-forge cadquery)
"""

import sys
import os
from collections import Counter

# UTF-8 output on Windows consoles (handles ×, Ø, → etc.)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Allow running from repo root or from experiments/
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Argument handling ────────────────────────────────────────────────────────

def _usage():
    print()
    print("Usage:")
    print("  python experiments/test_feature_candidates.py <path_to_step_file>")
    print()
    print("Example:")
    print("  python experiments/test_feature_candidates.py test_samples/test5slotted.step")
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


# ── Import ───────────────────────────────────────────────────────────────────

from modules.step_parser import (
    detect_feature_candidates_from_cadquery_file,
    _OCC_ADAPTOR_AVAILABLE,
)


# ── Header ───────────────────────────────────────────────────────────────────

file_size_kb = os.path.getsize(step_path) / 1024

print()
print("=" * 80)
print("  Feature Candidate Detection — CadQuery face-record experiment")
print("=" * 80)
print(f"  File        : {step_path}")
print(f"  Size        : {file_size_kb:.1f} KB")
print(f"  OCC adaptor : "
      f"{'available — precise cylinder radius' if _OCC_ADAPTOR_AVAILABLE else 'unavailable — bbox-estimated diameter only'}")
print("=" * 80)


# ── Run detection ────────────────────────────────────────────────────────────

print()
print("Running feature candidate detection...")
result = detect_feature_candidates_from_cadquery_file(step_path)

if not result["success"]:
    print()
    print("DETECTION FAILED")
    for w in result["warnings"]:
        print(f"  ! {w}")
    sys.exit(1)

print(f"Done — {result['candidate_count']} candidate(s) detected.")

if result["warnings"]:
    print()
    print("Warnings:")
    for w in result["warnings"]:
        print(f"  ! {w}")

candidates = result["candidate_features"]

if not candidates:
    print()
    print("No candidates to display.")
    sys.exit(0)


# ── Formatting helpers ────────────────────────────────────────────────────────

def _fv(v, width=8, dec=2):
    """Format float value right-aligned; None → right-aligned dash."""
    if v is None:
        return " " * (width - 1) + "—"
    return f"{v:{width}.{dec}f}"


def _trunc(s, n):
    """Truncate string to n chars, appending ellipsis if needed."""
    s = str(s) if s is not None else ""
    return s if len(s) <= n else s[: n - 1] + "…"


def _wrap(text, indent, width=72):
    """Wrap a long string to lines of `width` chars, with `indent` prefix."""
    text = str(text) if text else ""
    words = text.split()
    lines = []
    line = indent
    for word in words:
        if len(line) + len(word) + 1 > width:
            lines.append(line)
            line = indent + word
        else:
            line += ("" if line == indent else " ") + word
    if line.strip():
        lines.append(line)
    return "\n".join(lines) if lines else indent


# ── Candidate table ───────────────────────────────────────────────────────────

_SEP = "─" * 108

print()
print(_SEP)
HDR = (
    f"  {'ID':<6}  "
    f"{'Type':<22}  "
    f"{'Feature name':<28}  "
    f"{'Conf':<6}  "
    f"{'X':>8}  "
    f"{'Y':>8}  "
    f"{'Diam':>8}  "
    f"{'Length':>8}  "
    f"{'Width':>8}  "
    f"{'Depth':>8}"
)
print(HDR)
print("  " + "─" * (len(HDR) - 4))

for c in candidates:
    print(
        f"  {c['candidate_id']:<6}  "
        f"{_trunc(c['feature_type'], 22):<22}  "
        f"{_trunc(c['feature_name'], 28):<28}  "
        f"{c['confidence']:<6}  "
        f"{_fv(c['x_pos'])}  "
        f"{_fv(c['y_pos'])}  "
        f"{_fv(c['diameter'])}  "
        f"{_fv(c['length'])}  "
        f"{_fv(c['width'])}  "
        f"{_fv(c['depth'])}"
    )

print(_SEP)


# ── Detection notes ───────────────────────────────────────────────────────────

print()
print(_SEP)
print("  Detection notes")
print(_SEP)

for c in candidates:
    note = c.get("detection_note") or "(no note)"
    name = c.get("feature_name") or ""
    print()
    print(f"  [{c['candidate_id']}]  {name}")
    print(_wrap(note, indent="    "))

print()
print(_SEP)


# ── Summary ───────────────────────────────────────────────────────────────────

type_counts = Counter(c["feature_type"] for c in candidates)
conf_counts = Counter(c["confidence"]   for c in candidates)

print()
print("=" * 80)
print("  Summary")
print("=" * 80)
print(f"  Total candidates : {result['candidate_count']}")
print()
print("  By feature type:")
for ft, n in sorted(type_counts.items(), key=lambda x: -x[1]):
    bar = "█" * n
    print(f"    {ft:<26}: {n:>3}  {bar}")
print()
print("  By confidence:")
for conf, n in sorted(conf_counts.items(), key=lambda x: -x[1]):
    bar = "█" * n
    print(f"    {conf:<10}: {n:>3}  {bar}")
print()
