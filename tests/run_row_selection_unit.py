"""
Headless unit tests for the review-table row -> 3D highlight mapping.

Covers the pure helpers behind the click-a-row-to-highlight sync:
    _dataframe_selected_row_index  — st.dataframe selection event -> row index
    _row_selection_candidate_ids   — row index -> candidate id set (grouped + flat)
    _feature_row_candidate_ids     — accepted-feature row -> candidate id set
    _resolve_highlight_ids         — source precedence resolution
    _bom_row_group_id              — weldment BOM row -> group_id

Usage:
    python tests/run_row_selection_unit.py
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


class _Attr:
    """Attribute-style stand-in for Streamlit's selection event object."""

    def __init__(self, **kw):
        self.__dict__.update(kw)


def _make_candidates():
    """Synthetic candidate list: 3 identical holes, 2 identical slots, 1 pocket."""
    cands = []
    for i in range(3):
        cands.append({
            "candidate_id": f"H{i}",
            "feature_type": "Hole",
            "feature_name": f"Hole {i}",
            "diameter": 8.0,
            "depth": 10.0,
            "x_pos": 10.0 + 20 * i,
            "y_pos": 10.0,
        })
    for i in range(2):
        cands.append({
            "candidate_id": f"S{i}",
            "feature_type": "Slot",
            "feature_name": f"Slot {i}",
            "length": 40.0,
            "width": 10.0,
            "depth": 5.0,
            "x_pos": 60.0,
            "y_pos": 10.0 + 30 * i,
        })
    cands.append({
        "candidate_id": "P0",
        "feature_type": "Pocket",
        "feature_name": "Pocket 0",
        "length": 30.0,
        "width": 20.0,
        "depth": 6.0,
        "x_pos": 100.0,
        "y_pos": 40.0,
    })
    return cands


def main():
    # ── _dataframe_selected_row_index ────────────────────────────────────
    f = app._dataframe_selected_row_index
    _check("event: None", f(None), None)
    _check("event: dict row", f({"selection": {"rows": [2]}}), 2)
    _check("event: dict empty rows", f({"selection": {"rows": []}}), None)
    _check("event: dict no selection", f({}), None)
    _check("event: attr-style row",
           f(_Attr(selection=_Attr(rows=[5]))), 5)
    _check("event: attr-style empty",
           f(_Attr(selection=_Attr(rows=[]))), None)
    _check("event: junk row value", f({"selection": {"rows": ["x"]}}), None)
    _check("event: first of multi", f({"selection": {"rows": [3, 7]}}), 3)

    # ── _row_selection_candidate_ids — grouped mode ──────────────────────
    cands = _make_candidates()
    groups = app._build_candidate_groups(cands, "Raw Block / Billet")
    # Groups sort by (feature_type, description): Hole, Pocket, Slot.
    _check("groups: order sanity",
           [g["feature_type"] for g in groups], ["Hole", "Pocket", "Slot"])

    g = app._row_selection_candidate_ids
    _check("grouped: row 0 -> all hole ids",
           g(0, groups=groups, candidates=cands), {"H0", "H1", "H2"})
    _check("grouped: row 2 -> slot ids",
           g(2, groups=groups, candidates=cands), {"S0", "S1"})
    _check("grouped: row 1 -> pocket id",
           g(1, groups=groups, candidates=cands), {"P0"})
    _check("grouped: out of range", g(99, groups=groups, candidates=cands), set())
    _check("grouped: negative", g(-1, groups=groups, candidates=cands), set())
    _check("grouped: None row", g(None, groups=groups, candidates=cands), set())
    _check("grouped: junk index", g("zzz", groups=groups, candidates=cands), set())

    # ── _row_selection_candidate_ids — ungrouped (flat) mode ─────────────
    _check("flat: row 1", g(1, candidates=cands), {"H1"})
    _check("flat: row 4", g(4, candidates=cands), {"S1"})
    _check("flat: out of range", g(6, candidates=cands), set())
    _check("flat: None row", g(None, candidates=cands), set())
    _check("flat: missing candidate_id",
           g(0, candidates=[{"feature_type": "Hole"}]), set())

    # ── _feature_row_candidate_ids ───────────────────────────────────────
    feats = [
        {"feature_name": "From CAD", "source_candidate_id": "H1",
         "physical_feature_id": "PHYS-1"},
        {"feature_name": "Manual", "source_candidate_id": "",
         "physical_feature_id": ""},
    ]
    ff = app._feature_row_candidate_ids
    _check("feature row: source id only", ff(0, feats), {"H1"})
    _check("feature row: manual -> empty", ff(1, feats), set())
    _check("feature row: out of range", ff(5, feats), set())
    _check("feature row: None", ff(None, feats), set())
    # physical_feature_id re-match picks up a regenerated candidate id
    regen_cands = [{"candidate_id": "NEW-7", "physical_feature_id": "PHYS-1"}]
    _check("feature row: physical-id rematch",
           ff(0, feats, regen_cands), {"H1", "NEW-7"})

    # ── _resolve_highlight_ids precedence ────────────────────────────────
    r = app._resolve_highlight_ids
    _check("resolve: row wins", r({"A"}, {"B"}, {"C"}), {"A"})
    _check("resolve: ticks when no row", r(set(), {"B"}, {"C"}), {"B"})
    _check("resolve: selectbox fallback", r(set(), set(), {"C"}), {"C"})
    _check("resolve: all empty", r(set(), set(), set()), set())
    _check("resolve: None sources", r(None, None, None), set())

    # ── Simulated selection lifecycle (updates + clears) ─────────────────
    tick_ids = {"H0", "H1", "H2"}          # cards ticked by default
    sel_ids = set()                        # highlight selectbox on "(none)"

    # 1. no row selected -> tick union drives the highlight
    hl = r(g(None, groups=groups, candidates=cands), tick_ids, sel_ids)
    _check("lifecycle: no row -> ticks", hl, {"H0", "H1", "H2"})

    # 2. operator clicks the Slot group row -> spotlight overrides ticks
    hl = r(g(2, groups=groups, candidates=cands), tick_ids, sel_ids)
    _check("lifecycle: slot row spotlight", hl, {"S0", "S1"})

    # 3. operator moves the selection to the Pocket row -> highlight follows
    hl = r(g(1, groups=groups, candidates=cands), tick_ids, sel_ids)
    _check("lifecycle: group change follows", hl, {"P0"})

    # 4. operator deselects the row -> falls back to ticked cards
    hl = r(g(None, groups=groups, candidates=cands), tick_ids, sel_ids)
    _check("lifecycle: deselect -> ticks restore", hl, {"H0", "H1", "H2"})

    # 5. everything cleared -> empty highlight (viewer shows no gold)
    hl = r(g(None, groups=groups, candidates=cands), set(), set())
    _check("lifecycle: full clear", hl, set())

    # ── _bom_row_group_id ────────────────────────────────────────────────
    b = app._bom_row_group_id
    gids = ["plate_0", "tube_1", "gusset_2"]
    _check("bom: row 1", b(1, gids), "tube_1")
    _check("bom: None", b(None, gids), None)
    _check("bom: out of range", b(9, gids), None)
    _check("bom: empty ids", b(0, []), None)

    print(f"\n{_PASS} passed, {_FAIL} failed")
    if _FAIL:
        raise AssertionError(f"{_FAIL} row-selection unit check(s) failed")
    print("ALL ROW-SELECTION UNIT TESTS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
