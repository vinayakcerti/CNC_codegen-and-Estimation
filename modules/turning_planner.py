"""Turning operation planning (Epic 20 v1).

Plans lathe operations for the turned-region candidates that Story 19-2/19-3
detection emits (OD Turning, ID Turning / Bore, ID Groove) and estimates
cycle times from surface speed and feed-per-rev. These are planning
estimates for quoting — not CAM toolpaths.

Deliberately separate from operation_planner.py: lathe tools and cutting
models share nothing with the milling selector, and keeping the module
boundary clean means the VMC path cannot regress from lathe work.
"""
from __future__ import annotations
import math

# ── Lathe tool library (metric, insert-style) ──────────────────────────────
TURNING_TOOLS = [
    {"tool_number": "L1", "tool_name": "CNMG 120408 OD Rough",
     "tool_type": "OD Turning", "insert": "CNMG", "feed_mm_rev": 0.25,
     "doc_mm": 2.0},
    {"tool_number": "L2", "tool_name": "DNMG 110404 OD Finish",
     "tool_type": "OD Turning", "insert": "DNMG", "feed_mm_rev": 0.10,
     "doc_mm": 0.4},
    {"tool_number": "L3", "tool_name": "S16R Boring Bar Rough (min Ø18)",
     "tool_type": "ID Boring", "insert": "CCMT", "feed_mm_rev": 0.15,
     "doc_mm": 1.5, "min_bore_mm": 18.0},
    {"tool_number": "L4", "tool_name": "S12M Boring Bar Finish (min Ø14)",
     "tool_type": "ID Boring", "insert": "CCMT", "feed_mm_rev": 0.08,
     "doc_mm": 0.3, "min_bore_mm": 14.0},
    {"tool_number": "L5", "tool_name": "MGMN300 Groove 3mm",
     "tool_type": "Grooving", "insert": "MGMN", "feed_mm_rev": 0.05,
     "width_mm": 3.0},
    {"tool_number": "L6", "tool_name": "CNMG 120408 Facing",
     "tool_type": "Facing", "insert": "CNMG", "feed_mm_rev": 0.20,
     "doc_mm": 1.5},
]

_LATHE_MAX_RPM = 3500.0
_BASE_VC_M_MIN = 220.0        # carbide on free-machining aluminium
_ROUGH_ALLOWANCE_MM = 2.0     # radial stock to remove before finish
_STEADY_REST_LD = 5.0         # part L/D above this needs tailstock support


def _vc_for(material: dict | None) -> float:
    """Surface speed scaled by the material's machinability factor."""
    m = float((material or {}).get("machinability_factor") or
              (material or {}).get("machinability") or 1.0)
    return max(60.0, _BASE_VC_M_MIN * min(m, 1.5))


def _rpm(vc: float, dia_mm: float) -> float:
    if dia_mm <= 0:
        return _LATHE_MAX_RPM
    return min(_LATHE_MAX_RPM, (vc * 1000.0) / (math.pi * dia_mm))


def _pass_minutes(length_mm: float, feed_mm_rev: float, rpm: float) -> float:
    if feed_mm_rev <= 0 or rpm <= 0:
        return 0.0
    return length_mm / (feed_mm_rev * rpm)


def plan_turning_operations(features: list, material: dict | None = None,
                            part_length_mm: float = 0.0,
                            part_max_od_mm: float = 0.0) -> list:
    """Plan lathe ops for turned-region features.

    Args:
        features: candidate dicts; only feature types OD Turning,
                  ID Turning / Bore, ID Groove are planned here.
        material: material dict (machinability scales surface speed).
        part_length_mm / part_max_od_mm: whole-part envelope for the
                  tailstock / steady-rest rule (Story 19-6).
    Returns list of op dicts (op, feature, tool, rpm, feed_mm_rev,
    path_mm, cut_min, setup, notes).
    """
    vc = _vc_for(material)
    ops: list = []
    ld = (part_length_mm / part_max_od_mm) if part_max_od_mm > 0 else 0.0
    steady = ld > _STEADY_REST_LD
    setup = "Lathe Chuck + Tailstock" if steady else "Lathe Chuck"
    steady_note = (
        f" | L/D {ld:.1f} > {_STEADY_REST_LD:g}: tailstock or steady rest "
        "required — check deflection on finish pass."
        if steady else ""
    )

    turned = [f for f in features if (f.get("feature_type") or "") in
              ("OD Turning", "ID Turning / Bore", "ID Groove")]
    if not turned:
        return ops

    # One facing op pair bookends the job (both ends).
    face_dia = part_max_od_mm or max(
        (f.get("diameter") or 0.0) for f in turned
    )
    t_face = TURNING_TOOLS[5]
    rpm_f = _rpm(vc, face_dia)
    face_path = face_dia / 2.0
    ops.append({
        "op": "Face", "feature": "End face (x2)",
        "tool": t_face["tool_name"], "rpm": round(rpm_f),
        "feed_mm_rev": t_face["feed_mm_rev"],
        "path_mm": round(2 * face_path, 1),
        "cut_min": round(2 * _pass_minutes(face_path, t_face["feed_mm_rev"], rpm_f), 2),
        "setup": setup,
        "notes": "Face both ends to length before turning.",
    })

    for f in turned:
        ftype = f.get("feature_type")
        dia = float(f.get("diameter") or 0.0)
        length = float(f.get("depth") or 0.0)  # detection stores axial span in depth
        name = f.get("feature_name") or ftype

        if ftype == "OD Turning":
            rough, finish = TURNING_TOOLS[0], TURNING_TOOLS[1]
            n_pass = max(1, math.ceil(_ROUGH_ALLOWANCE_MM / rough["doc_mm"]))
            rpm_r = _rpm(vc, dia + 2 * _ROUGH_ALLOWANCE_MM)
            rough_min = n_pass * _pass_minutes(length, rough["feed_mm_rev"], rpm_r)
            rpm_fin = _rpm(vc, dia)
            fin_min = _pass_minutes(length, finish["feed_mm_rev"], rpm_fin)
            ops.append({
                "op": "OD Rough Turn", "feature": name,
                "tool": rough["tool_name"], "rpm": round(rpm_r),
                "feed_mm_rev": rough["feed_mm_rev"],
                "path_mm": round(n_pass * length, 1),
                "cut_min": round(rough_min, 2), "setup": setup,
                "notes": (f"{n_pass} pass(es) at {rough['doc_mm']:g} mm DOC, "
                          f"{_ROUGH_ALLOWANCE_MM:g} mm radial allowance."
                          + steady_note),
            })
            ops.append({
                "op": "OD Finish Turn", "feature": name,
                "tool": finish["tool_name"], "rpm": round(rpm_fin),
                "feed_mm_rev": finish["feed_mm_rev"],
                "path_mm": round(length, 1),
                "cut_min": round(fin_min, 2), "setup": setup,
                "notes": "Single finish pass to size." + steady_note
                + (" | Flagged region — verify undercut/thread callout first."
                   if f.get("verify_manually") else ""),
            })

        elif ftype == "ID Turning / Bore":
            rough, finish = TURNING_TOOLS[2], TURNING_TOOLS[3]
            bar_fits = dia >= (rough.get("min_bore_mm") or 0.0)
            rpm_r = _rpm(vc, max(dia - 2 * _ROUGH_ALLOWANCE_MM, 2.0))
            n_pass = max(1, math.ceil(_ROUGH_ALLOWANCE_MM / rough["doc_mm"]))
            rough_min = n_pass * _pass_minutes(length, rough["feed_mm_rev"], rpm_r)
            rpm_fin = _rpm(vc, dia)
            fin_min = _pass_minutes(length, finish["feed_mm_rev"], rpm_fin)
            pre = ("Pre-drill to near size, then bore."
                   if bar_fits else
                   f"Ø{dia:g} below Ø{rough.get('min_bore_mm'):g} bar minimum — "
                   "drill/ream only; boring not planned.")
            ops.append({
                "op": "ID Rough Bore", "feature": name,
                "tool": rough["tool_name"], "rpm": round(rpm_r),
                "feed_mm_rev": rough["feed_mm_rev"],
                "path_mm": round(n_pass * length, 1),
                "cut_min": round(rough_min if bar_fits else 0.0, 2),
                "setup": setup, "notes": pre,
            })
            if bar_fits:
                ops.append({
                    "op": "ID Finish Bore", "feature": name,
                    "tool": finish["tool_name"], "rpm": round(rpm_fin),
                    "feed_mm_rev": finish["feed_mm_rev"],
                    "path_mm": round(length, 1),
                    "cut_min": round(fin_min, 2), "setup": setup,
                    "notes": "Finish bore to size and surface callout.",
                })

        elif ftype == "ID Groove":
            tool = TURNING_TOOLS[4]
            width = length or float(f.get("depth") or 0.0)
            plunges = max(1, math.ceil(width / tool["width_mm"]))
            rpm_g = _rpm(vc, dia)
            # radial plunge per pass ~ (groove dia - bore dia)/2; without the
            # bore dia here, use a conservative 3 mm radial engagement
            plunge_depth = 3.0
            g_min = plunges * _pass_minutes(plunge_depth, tool["feed_mm_rev"], rpm_g)
            ops.append({
                "op": "ID Groove", "feature": name,
                "tool": tool["tool_name"], "rpm": round(rpm_g),
                "feed_mm_rev": tool["feed_mm_rev"],
                "path_mm": round(plunges * plunge_depth, 1),
                "cut_min": round(g_min, 2), "setup": setup,
                "notes": (f"{plunges} plunge(s) with {tool['width_mm']:g} mm "
                          "insert; verify groove width/corner callout."),
            })

    return ops


def turning_summary(ops: list) -> dict:
    """Route-tab summary: total minutes incl. a setup/handling factor."""
    cut = sum(o.get("cut_min") or 0.0 for o in ops)
    # chuck + face + tool changes + inspection — flat lathe handling
    handling = 10.0 if ops else 0.0
    return {
        "op_count": len(ops),
        "cut_min": round(cut, 2),
        "est_minutes": round(cut + handling, 1),
        "setup": ops[0]["setup"] if ops else None,
    }
