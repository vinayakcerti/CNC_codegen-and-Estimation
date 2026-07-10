"""Lathe draft G-code regression (Story 19-10 / Epic 20 20-4).

Runs the T04/T07/T08/T10/T11/TM01/T09 turning samples through the real
production pipeline — parse_step_auto() (same entry point backend/main.py
uses), then modules.turning_planner.plan_turning_operations(), then
modules.gcode_generator.generate_turning_gcode() — and checks the emitted
draft lathe program is well-formed and traceable back to the plan:
  - safety header / program-end markers present
  - lathe-specific G-codes present (G18 XZ plane, G97 constant-rpm mode)
  - every planned op appears once as a tool-change/comment block
  - no operation collapses to a Z-length-0 cutting move (that would mean
    the emitter silently lost the feature's own axial span and fell back
    to a wrong default)
  - T09 (false-positive milled-round-stock trap) plans ZERO turning ops
    and the generator returns an empty-program comment, not a crash

Usage:
    python tests/run_lathe_gcode_regression.py
"""
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from modules.step_parser import parse_step_auto
from modules.turning_planner import plan_turning_operations
from modules.gcode_generator import generate_turning_gcode
from modules.data_store import get_default_materials, get_default_machines

_TEST_SAMPLES_DIR = _PROJECT_ROOT / "test_samples"

_TURN_TYPES = ("OD Turning", "ID Turning / Bore", "ID Groove")

# (file, expected minimum turning op count) — TM01 and T09 expect 0 (T09 is
# the false-positive guard; TM01's single cross-drilled hole is milled, not
# turned, so its 2 OD Turning regions still yield turning ops via the OD
# path but no ID/groove ops).
SAMPLES = [
    ("T04_plain_cylinder_d60_l120.step", 1),   # Face + OD Rough + OD Finish
    ("T06_short_disc_hub_d120_l20.step", 1),
    ("T07_flange_bore_boltholes.step", 2),     # OD + ID bore
    ("T08_shaft_internal_groove.step", 3),     # OD + ID bore + ID groove
    ("T09_round_milled_part_not_lathe.step", 0),  # false-positive guard
    ("T10_long_shaft_ld7_d40_l300.step", 1),   # tailstock/steady-rest flag
    ("T11_shaft_thread_region.step", 1),
    ("TM01_turnmill_shaft_with_cross_hole.step", 1),
]


def _run_one(fname, min_turn_cands, material, machine):
    path = _TEST_SAMPLES_DIR / fname
    if not path.exists():
        return f"missing STEP file: {path}"

    with open(path, "rb") as f:
        file_bytes = f.read()
    parsed = parse_step_auto(file_bytes)
    if not parsed.get("success", True) and parsed.get("candidate_features") is None:
        return f"parse failed: {parsed.get('message')}"

    candidates = parsed.get("candidate_features") or []
    turn_cands = [c for c in candidates if (c.get("feature_type") or "") in _TURN_TYPES]
    if len(turn_cands) < min_turn_cands:
        return (f"expected >= {min_turn_cands} turning candidate(s), "
                f"got {len(turn_cands)}")

    dims = sorted([parsed.get("length_mm") or 0.0,
                   parsed.get("width_mm") or 0.0,
                   parsed.get("height_mm") or 0.0])
    ops = plan_turning_operations(
        turn_cands, material,
        part_length_mm=dims[2], part_max_od_mm=dims[1],
    )

    if min_turn_cands == 0:
        if ops:
            return f"expected NO turning ops on a false-positive sample, got {len(ops)}"
        gcode = generate_turning_gcode(ops, machine, part_length_mm=dims[2],
                                        part_max_od_mm=dims[1])
        if "No turning operations planned" not in gcode:
            return "empty-plan gcode should say so explicitly, not emit a blank/partial program"
        return None

    if not ops:
        return "turning candidates present but planner produced no ops"

    gcode = generate_turning_gcode(ops, machine, part_length_mm=dims[2],
                                    part_max_od_mm=dims[1])

    if "DO NOT RUN" not in gcode:
        return "draft G-code safety header missing"
    if "M30" not in gcode:
        return "draft G-code program end missing"
    if "G18" not in gcode:
        return "lathe XZ-plane selection (G18) missing"
    if "G97" not in gcode:
        return "constant-RPM mode (G97) missing"
    if "G90" not in gcode:
        return "absolute positioning (G90) missing"

    # Every planned op's (op, feature) pair must appear once as a comment
    # line — this is the traceability check: the emitted program must be
    # generated FROM the plan, not some independent hardcoded template.
    for op in ops:
        marker = f"{op['feature']} : {op['op']}"
        if marker not in gcode:
            return f"op not traceable in gcode output: {marker!r}"

    # No OD/ID cutting move should degrade to a literal zero-length Z pass —
    # that indicates the emitter fell back to a missing/zero part dimension
    # instead of the feature's own axial span.
    bad_zero_z = [ln for ln in gcode.splitlines()
                  if ("Turn pass along Z" in ln or "Bore pass along Z" in ln)
                  and "Z-0.000" in ln]
    if bad_zero_z:
        return f"zero-length Z cutting move(s) found: {bad_zero_z}"

    # Tool station numbers must be valid Fanuc T-addresses (T<station><offset>,
    # purely numeric, never the turning_planner internal "L#" label).
    for ln in gcode.splitlines():
        if ln.startswith("T") and " " not in ln.split("(")[0]:
            token = ln.split("(")[0].strip()
            if not (token.startswith("T") and token[1:].isdigit()):
                return f"malformed T-address in gcode: {token!r}"

    return None


def main():
    material = get_default_materials()[0]
    machine = get_default_machines()[0]
    failures = []

    print("=" * 72)
    print("Lathe Draft G-code Regression (Story 19-10)")
    print(f"Samples dir: {_TEST_SAMPLES_DIR}")
    print("=" * 72)

    for fname, min_turn in SAMPLES:
        print(f"\n[RUN] {fname}")
        err = _run_one(fname, min_turn, material, machine)
        if err:
            failures.append((fname, err))
            print(f"  FAIL: {err}")
        else:
            print("  PASS")

    print("\n" + "=" * 72)
    if failures:
        print(f"Result: {len(failures)} FAILURE(S)")
        for sample, reason in failures:
            print(f"  {sample}: {reason}")
        return 1

    print("Result: ALL LATHE G-CODE REGRESSION TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
