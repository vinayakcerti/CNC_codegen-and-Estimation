"""Drawing-to-quote support: synthesize a STEP model from a drawing
extraction, and compare an extraction against STEP-detected features.

The vision-LLM extraction (backend/main.py /api/drawing/extract) produces a
structured dict; this module is everything deterministic downstream of it:

  synthesize_step(extraction) -> (step_bytes, warnings)
      CadQuery builds a prismatic part: envelope box + hole features. The
      synthesized STEP then flows through the EXISTING pipeline (analyze /
      strategy / estimate / G-code) — the drawing path reuses the engine
      end to end instead of duplicating it.

  compare(extraction, step_candidates, step_dims) -> report
      Deterministic matching (no ML): per drawing feature MATCHED /
      COUNT_MISMATCH / DIM_MISMATCH / MISSING_IN_STEP, per STEP feature
      EXTRA_IN_STEP, envelope check with axis permutation, and an overall
      verdict CONSISTENT / MINOR_MISMATCH / MAJOR_MISMATCH.
"""
from __future__ import annotations

import itertools
import os
import tempfile

# Matching thresholds (mm) — deliberately simple and visible.
DIA_TOL = 0.15
DIA_NEAR = 1.5          # within this of the nearest STEP dia => DIM_MISMATCH
DEPTH_TOL = 0.5
ENVELOPE_TOL = 0.5

# ISO 261 coarse-pitch tap-drill diameters: an M-thread on the drawing may
# appear in the STEP as either the nominal or the tap-drill hole.
TAP_DRILL = {
    "M3": 2.5, "M4": 3.3, "M5": 4.2, "M6": 5.0, "M8": 6.8,
    "M10": 8.5, "M12": 10.2, "M14": 12.0, "M16": 14.0, "M20": 17.5,
}

HOLE_KINDS = {"hole", "tapped_hole", "counterbore", "countersink"}


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# --------------------------------------------------------------------------
# Synthesis
# --------------------------------------------------------------------------

def synthesize_step(extraction: dict) -> tuple[bytes, list[str]]:
    """Build a prismatic STEP from an extraction. Returns (bytes, warnings).

    v1 scope: envelope box + hole-family features (through or blind, at
    stated positions; unpositioned holes are laid out on a centered grid so
    the part is still quotable — flagged in warnings). Non-hole features
    (pockets, slots, chamfers) are NOT modeled — flagged in warnings so the
    user knows the synthesized quote excludes them.
    """
    import cadquery as cq

    warnings: list[str] = []
    env = (extraction.get("part") or {}).get("envelope_mm") or {}
    length, width, height = _num(env.get("length")), _num(env.get("width")), _num(env.get("height"))
    if min(length, width, height) <= 0:
        raise ValueError("Drawing extraction has no usable envelope (L x W x H).")

    solid = cq.Workplane("XY").box(length, width, height, centered=(True, True, False))

    for feat in extraction.get("features") or []:
        kind = str(feat.get("kind") or "").lower()
        count = max(int(feat.get("count") or 1), 1)
        if kind not in HOLE_KINDS:
            warnings.append(
                f"Feature '{kind}' (x{count}) is not modeled in the synthesized part — "
                "the quote from the drawing excludes it."
            )
            continue
        dia = _num(feat.get("diameter_mm"))
        if dia <= 0 and feat.get("thread_spec"):
            # Tapped hole with only a thread callout: model the tap drill.
            spec = str(feat["thread_spec"]).upper().split("X")[0].strip()
            dia = TAP_DRILL.get(spec, 0.0)
            if dia:
                warnings.append(
                    f"{feat['thread_spec']}: modeled as tap-drill Ø{dia} — tapping is "
                    "not included in the synthesized model."
                )
        if dia <= 0:
            warnings.append(f"Hole feature with unreadable diameter skipped (x{count}).")
            continue

        # SYNTHESIS SAFETY (red-team finding): cut material ONLY when the
        # drawing explicitly says through=true or states a depth. A null
        # through + null depth means "unreadable" — never assume through.
        through = feat.get("through")
        depth = feat.get("depth_mm")
        if through is not True and depth in (None, "", 0):
            warnings.append(
                f"Ø{dia} x{count}: through/blind unconfirmed on the drawing — "
                "NOT modeled; confirm before quoting."
            )
            continue

        positions = _normalize_positions(feat.get("positions_mm"))
        if len(positions) < count:
            # Not enough stated positions: grid-place the remainder so the
            # part is still machinable/quotable. Flag it loudly.
            missing = count - len(positions)
            warnings.append(
                f"{missing} of {count} Ø{dia} holes have no position on the drawing — "
                "auto-placed on a grid; verify before quoting."
            )
            positions = positions + _grid_positions(length, width, count)[len(positions):count]
        positions = positions[:count]

        wp = solid.faces(">Z").workplane()
        pts = [(float(x), float(y)) for x, y in positions]
        if through is True:
            solid = wp.pushPoints(pts).hole(dia)
        else:
            solid = wp.pushPoints(pts).hole(dia, depth=_num(depth))

    with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tf:
        path = tf.name
    try:
        cq.exporters.export(solid, path)
        with open(path, "rb") as f:
            data = f.read()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    return data, warnings


def _normalize_positions(raw) -> list[list[float]]:
    """Accept both position shapes: {x,y} objects (schema) and [x,y] pairs."""
    out = []
    for p in raw or []:
        if isinstance(p, dict) and "x" in p and "y" in p:
            out.append([_num(p["x"]), _num(p["y"])])
        elif isinstance(p, (list, tuple)) and len(p) == 2:
            out.append([_num(p[0]), _num(p[1])])
    return out


def _grid_positions(length: float, width: float, count: int) -> list[list[float]]:
    """Centered grid of `count` points with sane margins."""
    import math

    cols = max(int(math.ceil(math.sqrt(count))), 1)
    rows = max(int(math.ceil(count / cols)), 1)
    mx, my = length * 0.2, width * 0.2
    xs = [(-length / 2 + mx) + i * ((length - 2 * mx) / max(cols - 1, 1)) for i in range(cols)]
    ys = [(-width / 2 + my) + j * ((width - 2 * my) / max(rows - 1, 1)) for j in range(rows)]
    pts = [[x, y] for y in ys for x in xs]
    return pts[:count]


# --------------------------------------------------------------------------
# Comparison
# --------------------------------------------------------------------------

def _step_hole_groups(candidates: list) -> list[dict]:
    """Group STEP hole candidates by (rounded dia, rounded depth)."""
    groups: dict = {}
    for c in candidates or []:
        ftype = str(c.get("feature_type") or "").lower()
        if "hole" not in ftype and "bore" not in ftype:
            continue
        dia = round(_num(c.get("diameter")), 1)
        depth = round(_num(c.get("depth")), 1)
        key = (dia, depth)
        g = groups.setdefault(key, {"diameter_mm": dia, "depth_mm": depth, "count": 0, "candidates": []})
        g["count"] += 1
        g["candidates"].append({
            "id": c.get("candidate_id"),
            "name": c.get("feature_name"),
            "x": _num(c.get("x_pos")), "y": _num(c.get("y_pos")),
        })
    return list(groups.values())


def _dia_variants(feat: dict) -> list[float]:
    """Diameters this drawing feature may present as in the STEP."""
    out = []
    d = _num(feat.get("diameter_mm"))
    if d > 0:
        out.append(d)
    spec = feat.get("thread_spec")
    if spec:
        base = str(spec).upper().split("X")[0].strip()
        td = TAP_DRILL.get(base)
        if td:
            out.append(td)
        try:
            out.append(float(base.lstrip("M")))
        except ValueError:
            pass
    return out or [0.0]


def compare(extraction: dict, step_candidates: list, step_dims: dict) -> dict:
    """Match drawing features against STEP candidates. Pure + deterministic."""
    results = []
    step_groups = _step_hole_groups(step_candidates)
    claimed: set = set()

    for feat in extraction.get("features") or []:
        kind = str(feat.get("kind") or "").lower()
        count = max(int(feat.get("count") or 1), 1)
        if kind not in HOLE_KINDS:
            results.append({
                "feature": feat, "status": "NOT_COMPARED",
                "detail": f"'{kind}' features are compared manually in v1.",
                "step_candidates": [],
            })
            continue

        variants = _dia_variants(feat)
        best, best_delta = None, None
        for gi, g in enumerate(step_groups):
            if gi in claimed:
                continue
            delta = min(abs(g["diameter_mm"] - v) for v in variants)
            if best_delta is None or delta < best_delta:
                best, best_delta = gi, delta

        if best is None or best_delta is None or best_delta > DIA_NEAR:
            results.append({
                "feature": feat, "status": "MISSING_IN_STEP",
                "detail": f"No hole near Ø{variants[0]} found in the STEP model.",
                "step_candidates": [],
            })
            continue

        g = step_groups[best]
        claimed.add(best)
        if best_delta <= DIA_TOL:
            if g["count"] == count:
                status, detail = "MATCHED", f"Ø{g['diameter_mm']} x {count} — drawing and STEP agree."
            else:
                status = "COUNT_MISMATCH"
                detail = f"Drawing says {count} x Ø{variants[0]}; STEP has {g['count']}."
        else:
            status = "DIM_MISMATCH"
            detail = f"Drawing says Ø{variants[0]}; nearest STEP hole is Ø{g['diameter_mm']} ({g['count']}x)."
        results.append({
            "feature": feat, "status": status, "detail": detail,
            "step_candidates": g["candidates"],
        })

    extras = [
        {"group": g, "status": "EXTRA_IN_STEP",
         "detail": f"STEP has {g['count']} x Ø{g['diameter_mm']} not on the drawing."}
        for gi, g in enumerate(step_groups) if gi not in claimed
    ]

    # Envelope: compare sorted dims with axis permutation allowance.
    env = (extraction.get("part") or {}).get("envelope_mm") or {}
    d_env = sorted([_num(env.get("length")), _num(env.get("width")), _num(env.get("height"))])
    s_env = sorted([_num(step_dims.get("length")), _num(step_dims.get("width")), _num(step_dims.get("height"))])
    env_ok = all(abs(a - b) <= ENVELOPE_TOL for a, b in zip(d_env, s_env)) if all(d_env) else None
    env_report = {
        "drawing_mm": d_env, "step_mm": s_env,
        "status": "MATCHED" if env_ok else ("UNKNOWN" if env_ok is None else "MISMATCH"),
    }

    statuses = [r["status"] for r in results]
    bad = [s for s in statuses if s in ("DIM_MISMATCH", "MISSING_IN_STEP")]
    minor = [s for s in statuses if s == "COUNT_MISMATCH"]
    if env_report["status"] == "MISMATCH" or bad:
        verdict = "MAJOR_MISMATCH"
    elif minor or extras:
        verdict = "MINOR_MISMATCH"
    else:
        verdict = "CONSISTENT"

    return {
        "verdict": verdict,
        "envelope": env_report,
        "features": results,
        "extra_in_step": extras,
    }
