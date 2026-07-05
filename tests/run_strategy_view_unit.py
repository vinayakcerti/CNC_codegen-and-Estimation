"""
Headless unit tests for the Strategy-by-Setup grouping helper.

Covers the pure helper behind the per-setup sequenced operation view:
    _group_operations_by_setup — operations + per-op time rows -> setup groups
        (first-appearance setup order, op order preserved inside each group,
         per-setup cutting subtotals, blocked-op counts)

Usage:
    python tests/run_strategy_view_unit.py
"""

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import app  # noqa: E402  (bare-mode streamlit import is fine headless)

_PASS = 0
_FAIL = 0


def _check(label, actual, expected):
    global _PASS, _FAIL
    if actual == expected:
        _PASS += 1
        print(f"PASS {label}")
    else:
        _FAIL += 1
        print(f"FAIL {label}: expected {expected!r}, got {actual!r}")


def _make_fake_plan():
    """3 setups, 6 ops (interleaved arrival), one blocked — plus per-op rows."""
    ops = [
        {"op_num": 1, "operation_type": "Face Mill",       "feature_name": "Top Face",
         "setup_label": "Top",    "tool_name": "50mm Face Mill", "tool_number": 1,
         "source_candidate_id": "C1", "planning_blocked": False},
        {"op_num": 2, "operation_type": "Rough End Mill",  "feature_name": "Pocket 1",
         "setup_label": "Top",    "tool_name": "12mm End Mill",  "tool_number": 2,
         "source_candidate_id": "C2", "planning_blocked": False},
        {"op_num": 3, "operation_type": "Drill",           "feature_name": "Hole B1",
         "setup_label": "Bottom", "tool_name": "8mm Drill",      "tool_number": 3,
         "source_candidate_id": "C3", "planning_blocked": False},
        {"op_num": 4, "operation_type": "Finish End Mill", "feature_name": "Pocket 1",
         "setup_label": "Top",    "tool_name": "10mm End Mill",  "tool_number": 4,
         "source_candidate_id": "C2", "planning_blocked": False},
        {"op_num": 5, "operation_type": "Chamfer",         "feature_name": "Edge B",
         "setup_label": "Bottom", "tool_name": "Chamfer Mill",   "tool_number": 5,
         "source_candidate_id": "C4", "planning_blocked": False},
        {"op_num": 6, "operation_type": "Manual Review",   "feature_name": "Weird Boss",
         "setup_label": "Side A", "tool_name": "UNRESOLVED",     "tool_number": 0,
         "source_candidate_id": "",   "planning_blocked": True,
         "tool_warning": "WARNING: no validated operation/tool rule exists."},
    ]
    per_op_rows = [
        {"op_num": 1, "cut_min": 1.50, "blocked": False},
        {"op_num": 2, "cut_min": 2.25, "blocked": False},
        {"op_num": 3, "cut_min": 3.00, "blocked": False},
        {"op_num": 4, "cut_min": 0.75, "blocked": False},
        {"op_num": 5, "cut_min": 1.25, "blocked": False},
        {"op_num": 6, "cut_min": 0.00, "blocked": True},
    ]
    return ops, per_op_rows


def main():
    grp = app._group_operations_by_setup
    ops, per_op_rows = _make_fake_plan()
    groups = grp(ops, per_op_rows)

    # ── Structure: 3 setups in first-appearance order ────────────────────
    _check("group count", len(groups), 3)
    _check("setup order (first appearance)",
           [g["setup_label"] for g in groups], ["Top", "Bottom", "Side A"])

    # ── Op order preserved inside each group ─────────────────────────────
    _check("Top op order",    [o["op_num"] for o in groups[0]["ops"]], [1, 2, 4])
    _check("Bottom op order", [o["op_num"] for o in groups[1]["ops"]], [3, 5])
    _check("Side A op order", [o["op_num"] for o in groups[2]["ops"]], [6])

    # ── Subtotals: per-setup sums of cut_min ─────────────────────────────
    _check("Top subtotal",    groups[0]["subtotal_min"], 4.5)   # 1.5+2.25+0.75
    _check("Bottom subtotal", groups[1]["subtotal_min"], 4.25)  # 3.0+1.25
    _check("Side A subtotal", groups[2]["subtotal_min"], 0.0)

    _all_cut = round(sum(r["cut_min"] for r in per_op_rows), 2)
    _sub_sum = round(sum(g["subtotal_min"] for g in groups), 2)
    _check("subtotals reconcile to total cut_min", _sub_sum, _all_cut)

    # ── Per-op cut_min attached ──────────────────────────────────────────
    _check("op 2 _cut_min attached", groups[0]["ops"][1]["_cut_min"], 2.25)
    _check("op 5 _cut_min attached", groups[1]["ops"][1]["_cut_min"], 1.25)

    # ── Blocked op flagged ───────────────────────────────────────────────
    _check("Top blocked count",    groups[0]["blocked_count"], 0)
    _check("Bottom blocked count", groups[1]["blocked_count"], 0)
    _check("Side A blocked count", groups[2]["blocked_count"], 1)
    _check("blocked op keeps planning_blocked",
           groups[2]["ops"][0]["planning_blocked"], True)
    _check("blocked op keeps warning text",
           groups[2]["ops"][0]["tool_warning"],
           "WARNING: no validated operation/tool rule exists.")

    # ── Inputs are not mutated ───────────────────────────────────────────
    _check("input ops not mutated", "_cut_min" in ops[0], False)

    # ── Degenerate inputs ────────────────────────────────────────────────
    _check("empty ops -> empty groups", grp([], per_op_rows), [])
    _check("None ops -> empty groups", grp(None, per_op_rows), [])

    no_rows = grp(ops, None)
    _check("no per-op rows: groups still form", len(no_rows), 3)
    _check("no per-op rows: zero subtotals",
           [g["subtotal_min"] for g in no_rows], [0.0, 0.0, 0.0])

    missing_row = grp(ops, per_op_rows[:2])  # rows only for ops 1-2
    _check("missing rows default cut_min 0",
           missing_row[1]["subtotal_min"], 0.0)
    _check("missing rows keep matched subtotal",
           missing_row[0]["subtotal_min"], 3.75)  # 1.5 + 2.25 + 0

    unlabeled = grp([{"op_num": 9, "planning_blocked": False}], [])
    _check("missing setup_label -> Unknown",
           unlabeled[0]["setup_label"], "Unknown")

    fp = grp(
        [{"op_num": 1, "setup_label": "S"}, {"op_num": 2, "setup_label": "S"}],
        [{"op_num": 1, "cut_min": 0.1}, {"op_num": 2, "cut_min": 0.2}],
    )
    _check("subtotal rounded to 2dp", fp[0]["subtotal_min"], 0.3)

    junk_cut = grp([{"op_num": 1, "setup_label": "S"}],
                   [{"op_num": 1, "cut_min": "n/a"}])
    _check("junk cut_min treated as 0", junk_cut[0]["subtotal_min"], 0.0)

    print(f"\n{_PASS} passed, {_FAIL} failed")
    if _FAIL:
        raise AssertionError(f"{_FAIL} strategy-view unit check(s) failed")
    print("ALL STRATEGY VIEW UNIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
