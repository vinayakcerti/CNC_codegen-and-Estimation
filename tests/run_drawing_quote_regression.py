"""Drawing-quote regression: synthesis + comparison against known fixtures.

Gates:
 1. Ground-truth extraction (D01) synthesizes a valid STEP whose parsed
    geometry matches the original 02_plate part (envelope + 4 x Ø10 thru).
 2. compare(D01 truth, 02_plate STEP candidates) -> CONSISTENT, all MATCHED.
 3. compare(D02 mismatch fixture, same STEP) -> MAJOR_MISMATCH with a
    DIM/COUNT mismatch on the hole group and an envelope MISMATCH.

Run:  conda run -n cnc-cadquery python -B tests/run_drawing_quote_regression.py
"""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from modules.drawing_quote import compare, synthesize_step  # noqa: E402
from modules.step_parser import parse_step_auto  # noqa: E402

SAMPLES = os.path.join(ROOT, "test_samples")
failures = []


def check(name, cond, detail=""):
    if cond:
        print(f"PASS {name}")
    else:
        failures.append(name)
        print(f"FAIL {name} {detail}")


truth = json.load(open(os.path.join(SAMPLES, "D01_plate_drawing.extract.json"), encoding="utf-8"))
mismatch = json.load(open(os.path.join(SAMPLES, "D02_plate_drawing_mismatch.extract.json"), encoding="utf-8"))
step_bytes = open(os.path.join(SAMPLES, "02_plate_4_through_holes_d10.step"), "rb").read()

# ---- Gate 1: synthesis produces a valid, matching part ----
syn_bytes, warnings = synthesize_step(truth)
check("synthesis produced STEP bytes", len(syn_bytes) > 1000, f"{len(syn_bytes)} bytes")
check("synthesis clean for fully-specified drawing", not warnings, str(warnings))

syn_parse = parse_step_auto(syn_bytes)
check("synthesized STEP parses", bool(syn_parse.get("success")), syn_parse.get("message", ""))
dims = sorted([
    round(syn_parse.get("length_mm") or 0),
    round(syn_parse.get("width_mm") or 0),
    round(syn_parse.get("height_mm") or 0),
])
check("synthesized envelope 30x60x100", dims == [30, 60, 100], str(dims))

syn_holes = [
    c for c in syn_parse.get("candidate_features") or []
    if "hole" in str(c.get("feature_type") or "").lower()
    and abs(float(c.get("diameter") or 0) - 10.0) < 0.2
]
check("synthesized part detects 4 x Ø10 holes", len(syn_holes) == 4, f"found {len(syn_holes)}")

# ---- Gate 2: truth vs original STEP => CONSISTENT ----
orig_parse = parse_step_auto(step_bytes)
cands = orig_parse.get("candidate_features") or []
step_dims = {
    "length": orig_parse.get("length_mm"),
    "width": orig_parse.get("width_mm"),
    "height": orig_parse.get("height_mm"),
}
report = compare(truth, cands, step_dims)
check("truth vs STEP verdict CONSISTENT", report["verdict"] == "CONSISTENT", report["verdict"])
hole_rows = [r for r in report["features"] if r["status"] != "NOT_COMPARED"]
check("truth hole group MATCHED", all(r["status"] == "MATCHED" for r in hole_rows),
      str([r["status"] for r in hole_rows]))
check("envelope MATCHED", report["envelope"]["status"] == "MATCHED", str(report["envelope"]))

# ---- Gate 3: mismatch fixture => MAJOR_MISMATCH ----
report2 = compare(mismatch, cands, step_dims)
check("mismatch fixture verdict MAJOR_MISMATCH", report2["verdict"] == "MAJOR_MISMATCH", report2["verdict"])
st = [r["status"] for r in report2["features"]]
check("mismatch detected on hole group",
      any(s in ("DIM_MISMATCH", "COUNT_MISMATCH", "MISSING_IN_STEP") for s in st), str(st))
check("mismatch envelope flagged", report2["envelope"]["status"] == "MISMATCH", str(report2["envelope"]))

# ---- Gate 4: mismatch fixture still synthesizes (both-estimates path) ----
syn2, warn2 = synthesize_step(mismatch)
p2 = parse_step_auto(syn2)
holes2 = [
    c for c in p2.get("candidate_features") or []
    if "hole" in str(c.get("feature_type") or "").lower()
    and abs(float(c.get("diameter") or 0) - 12.0) < 0.2
]
check("mismatch fixture synthesizes 6 x Ø12", len(holes2) == 6, f"found {len(holes2)}")

# ---- Gate 5: synthesis safety — unreadable through/blind is NOT cut ----
unsafe = json.loads(json.dumps(truth))
unsafe["features"][0]["through"] = None
unsafe["features"][0]["depth_mm"] = None
syn3, warn3 = synthesize_step(unsafe)
p3 = parse_step_auto(syn3)
holes3 = [
    c for c in p3.get("candidate_features") or []
    if "hole" in str(c.get("feature_type") or "").lower()
]
check("unconfirmed through/blind feature NOT machined", len(holes3) == 0,
      f"found {len(holes3)} holes")
check("safety warning emitted", any("unconfirmed" in w for w in warn3), str(warn3))

print("=" * 60)
if failures:
    print(f"Result: DRAWING QUOTE REGRESSION FAILED ({len(failures)}): {failures}")
    sys.exit(1)
print("Result: DRAWING QUOTE REGRESSION PASSED")
