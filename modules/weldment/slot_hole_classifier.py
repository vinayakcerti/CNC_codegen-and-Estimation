"""Classify cylindrical faces on a solid as round holes vs slot end-caps.

A round hole is a full cylinder (one 360-degree face, or several faces that
share the SAME axis line and together close the cylinder — CAD seams often
split a bore into two halves).

A slot has two end-caps: partial (roughly half) cylinders of the SAME radius
whose axes are PARALLEL but OFFSET from each other, joined by parallel planar
walls. This mirrors the end-cap pairing idea used by step_parser.py Section C
(slot detection on the billet path), applied per-solid for weldment bodies.
"""
from __future__ import annotations
import math

# Surface adaptor for exact cylinder geometry. CadQuery bundles the OCP
# bindings; classic pythonocc exposes the same API under OCC.Core. Try both.
_BRepAdaptor = None
_GeomAbsCylinder = None
_OCC_OK = False
try:
    from OCP.BRepAdaptor import BRepAdaptor_Surface as _BRepAdaptor
    from OCP.GeomAbs import GeomAbs_Cylinder as _GeomAbsCylinder
    _OCC_OK = True
except Exception:
    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Surface as _BRepAdaptor
        from OCC.Core.GeomAbs import GeomAbs_Cylinder as _GeomAbsCylinder
        _OCC_OK = True
    except Exception:
        pass

_RADIUS_TOL_FRAC = 0.02   # 2 % radius match for slot end-cap pairing
_AXIS_PARALLEL_DOT = 0.999
_SAME_AXIS_DIST_MM = 0.05  # axes closer than this = same axis line (one hole)
_FULL_CYL_AREA_FRAC = 0.85  # group area >= 85 % of full cylinder -> round hole


def _cyl_data(face):
    """Extract (radius, axis_dir, axis_loc) from a cylindrical face, or None."""
    if not _OCC_OK:
        return None
    try:
        adaptor = _BRepAdaptor(face.wrapped)
        if adaptor.GetType() != _GeomAbsCylinder:
            return None
        cyl = adaptor.Cylinder()
        d = cyl.Axis().Direction()
        p = cyl.Axis().Location()
        rec = {
            "radius": cyl.Radius(),
            "dir": (d.X(), d.Y(), d.Z()),
            "loc": (p.X(), p.Y(), p.Z()),
            "bulge": None,
        }
        # Arc "bulge": direction from the axis to the face centroid,
        # perpendicular to the axis. A slot's two end-caps bulge AWAY
        # from each other; this disambiguates pairing when several
        # collinear slots put many caps in a row.
        try:
            c = face.Center()
            v = (c.x - rec["loc"][0], c.y - rec["loc"][1], c.z - rec["loc"][2])
            along = v[0] * rec["dir"][0] + v[1] * rec["dir"][1] + v[2] * rec["dir"][2]
            perp = (v[0] - along * rec["dir"][0],
                    v[1] - along * rec["dir"][1],
                    v[2] - along * rec["dir"][2])
            n = math.sqrt(perp[0] ** 2 + perp[1] ** 2 + perp[2] ** 2)
            if n > 1e-9:
                rec["bulge"] = (perp[0] / n, perp[1] / n, perp[2] / n)
        except Exception:
            pass
        return rec
    except Exception:
        return None


def _cone_data(face):
    """Extract axis/semi-angle from a conical face (drill tip, countersink,
    or revolved chamfer), or None."""
    if not _OCC_OK:
        return None
    try:
        adaptor = _BRepAdaptor(face.wrapped)
        cone = adaptor.Cone()
        d = cone.Axis().Direction()
        p = cone.Axis().Location()
        rec = {
            "dir": (d.X(), d.Y(), d.Z()),
            "loc": (p.X(), p.Y(), p.Z()),
            "semi_deg": abs(math.degrees(cone.SemiAngle())),
        }
        rec["span"] = _axial_span(face, rec)
        try:
            rec["area"] = face.Area()
        except Exception:
            rec["area"] = 0.0
        return rec
    except Exception:
        return None


def _perp_axis_distance(a, b):
    """Perpendicular distance between two parallel axis lines a and b."""
    dx = (b["loc"][0] - a["loc"][0],
          b["loc"][1] - a["loc"][1],
          b["loc"][2] - a["loc"][2])
    d = a["dir"]
    along = dx[0] * d[0] + dx[1] * d[1] + dx[2] * d[2]
    perp = (dx[0] - along * d[0], dx[1] - along * d[1], dx[2] - along * d[2])
    return math.sqrt(perp[0] ** 2 + perp[1] ** 2 + perp[2] ** 2)


def _axial_range(face, axis):
    """(min, max) projection of a face's bbox corners onto the axis dir."""
    try:
        bb = face.BoundingBox()
        corners = [
            (x, y, z)
            for x in (bb.xmin, bb.xmax)
            for y in (bb.ymin, bb.ymax)
            for z in (bb.zmin, bb.zmax)
        ]
        d = axis["dir"]
        proj = [c[0] * d[0] + c[1] * d[1] + c[2] * d[2] for c in corners]
        return (min(proj), max(proj))
    except Exception:
        return None


def _axial_span(face, axis):
    """Approximate extent of a face along the cylinder axis via its bbox."""
    rng = _axial_range(face, axis)
    return (rng[1] - rng[0]) if rng else 0.0


def _bbox_range_along(direction, bbox):
    """(min, max) projection of an axis-aligned bbox onto a direction."""
    corners = [
        (x, y, z)
        for x in (bbox["xmin"], bbox["xmax"])
        for y in (bbox["ymin"], bbox["ymax"])
        for z in (bbox["zmin"], bbox["zmax"])
    ]
    proj = [c[0] * direction[0] + c[1] * direction[1] + c[2] * direction[2]
            for c in corners]
    return (min(proj), max(proj))


def _dist_to_bbox_edge(loc, direction, bbox):
    """Ray-box exit distance from loc along direction, or None."""
    t_exit = None
    for k, (lo_key, hi_key) in enumerate((("xmin", "xmax"), ("ymin", "ymax"),
                                          ("zmin", "zmax"))):
        d = direction[k]
        if abs(d) < 1e-9:
            continue
        t = ((bbox[hi_key] if d > 0 else bbox[lo_key]) - loc[k]) / d
        if t >= 0 and (t_exit is None or t < t_exit):
            t_exit = t
    return t_exit


def classify_cylindrical_faces(faces: list, bbox: dict | None = None) -> dict:
    """Classify each cylindrical face in `faces` as part of a hole or a slot.

    Slots come in two forms:
      closed — two end-caps of the same radius, parallel offset axes,
               each bulging AWAY from the other;
      open   — a single end-cap whose arc opens toward a nearby body
               boundary (slot machined in from the part edge).

    Args:
        faces: the solid's face list (solid.Faces()) — indices in the result
               refer to positions in THIS list.
        bbox:  optional solid bounding box {xmin..zmax}; enables open-slot
               detection.

    Returns dict:
        face_categories: {face_index: "hole" | "slot"}
        hole_count: int   — distinct hole axes (not raw face count)
        slot_count: int   — closed pairs + open single-cap slots
        slots: list of {"length_mm", "width_mm", "open"}
        available: bool   — False when the OCC/OCP adaptor is unavailable
    """
    if not _OCC_OK:
        return {"face_categories": {}, "hole_count": 0, "slot_count": 0,
                "slots": [], "holes": [], "available": False}

    # 1. Collect cylindrical faces with exact geometry. Also sweep cone and
    #    torus faces in the same pass: cones coaxial with a hole are drill
    #    tips / countersinks, standalone narrow cones and 45-degree bevel
    #    planes are chamfers, torus faces are fillets.
    cyl = {}
    cones = []   # {"dir", "loc", "semi_deg", "span", "area", "fi"}
    fillet_faces = 0
    chamfer_faces = 0
    for fi, face in enumerate(faces):
        try:
            gtype = face.geomType()
        except Exception:
            continue
        if gtype == "TORUS":
            fillet_faces += 1
            continue
        if gtype == "CONE":
            c = _cone_data(face)
            if c:
                c["fi"] = fi
                cones.append(c)
            continue
        if gtype != "CYLINDER":
            continue
        data = _cyl_data(face)
        if data is None:
            continue
        try:
            data["area"] = face.Area()
        except Exception:
            data["area"] = 0.0
        data["prange"] = _axial_range(face, data)
        data["span"] = (data["prange"][1] - data["prange"][0]) if data["prange"] else 0.0
        cyl[fi] = data

    if not cyl:
        return {"face_categories": {}, "hole_count": 0, "slot_count": 0,
                "slots": [], "holes": [], "available": True}

    # 2. Group faces that lie on the SAME axis line with the same radius —
    #    a bore split into halves by a CAD seam is still one hole.
    indices = sorted(cyl.keys())
    group_of = {}
    groups = []  # each: {"members": [fi..], "radius", "dir", "loc"}
    for fi in indices:
        a = cyl[fi]
        placed = False
        for g in groups:
            if abs(a["radius"] - g["radius"]) > max(0.05, _RADIUS_TOL_FRAC * g["radius"]):
                continue
            dot = abs(a["dir"][0] * g["dir"][0] + a["dir"][1] * g["dir"][1]
                      + a["dir"][2] * g["dir"][2])
            if dot < _AXIS_PARALLEL_DOT:
                continue
            if _perp_axis_distance(g, a) > _SAME_AXIS_DIST_MM:
                continue
            g["members"].append(fi)
            placed = True
            break
        if not placed:
            groups.append({"members": [fi], "radius": a["radius"],
                           "dir": a["dir"], "loc": a["loc"]})
        group_of[fi] = None  # filled below
    for gi, g in enumerate(groups):
        for fi in g["members"]:
            group_of[fi] = gi
        g["area"] = sum(cyl[fi]["area"] for fi in g["members"])
        g["span"] = max(cyl[fi]["span"] for fi in g["members"])
        # Union of member axial ranges in the GROUP's dir frame (a member
        # whose axis dir is sign-flipped vs the group has mirrored projections)
        pmin = pmax = None
        for fi in g["members"]:
            pr = cyl[fi].get("prange")
            if not pr:
                continue
            d = cyl[fi]["dir"]
            flip = (d[0] * g["dir"][0] + d[1] * g["dir"][1]
                    + d[2] * g["dir"][2]) < 0
            lo, hi = (-pr[1], -pr[0]) if flip else pr
            pmin = lo if pmin is None else min(pmin, lo)
            pmax = hi if pmax is None else max(pmax, hi)
        g["prange"] = (pmin, pmax) if pmin is not None else None
        # Group bulge = normalised mean of member bulges (may be None)
        bx = by = bz = 0.0
        nb = 0
        for fi in g["members"]:
            b = cyl[fi].get("bulge")
            if b:
                bx += b[0]; by += b[1]; bz += b[2]
                nb += 1
        bn = math.sqrt(bx * bx + by * by + bz * bz)
        g["bulge"] = (bx / bn, by / bn, bz / bn) if (nb and bn > 1e-9) else None

    # 3. Split groups: full cylinders -> holes; partial -> slot end-cap candidates
    hole_groups, cap_groups = [], []
    for g in groups:
        full_area = 2.0 * math.pi * g["radius"] * max(g["span"], 1e-6)
        if g["area"] >= _FULL_CYL_AREA_FRAC * full_area:
            hole_groups.append(g)
        else:
            cap_groups.append(g)

    def _entry_dir_for(group):
        """Signed outward direction of the surface a slot is cut from:
        the end of the cap's axial range nearer the body boundary."""
        if not bbox or not group.get("prange"):
            return None
        bmin, bmax = _bbox_range_along(group["dir"], bbox)
        gap_lo = max(0.0, group["prange"][0] - bmin)
        gap_hi = max(0.0, bmax - group["prange"][1])
        sign = 1.0 if gap_hi <= gap_lo else -1.0
        return tuple(round(sign * v, 4) for v in group["dir"])

    # 4. Pair end-cap groups into slots: same radius, parallel offset axes.
    #    Greedy nearest-distance matching; each cap joins at most one slot.
    face_categories = {}
    slots = []
    used = set()
    pairs = []
    for i in range(len(cap_groups)):
        for j in range(i + 1, len(cap_groups)):
            a, b = cap_groups[i], cap_groups[j]
            if abs(a["radius"] - b["radius"]) > max(0.05, _RADIUS_TOL_FRAC * a["radius"]):
                continue
            dot = abs(a["dir"][0] * b["dir"][0] + a["dir"][1] * b["dir"][1]
                      + a["dir"][2] * b["dir"][2])
            if dot < _AXIS_PARALLEL_DOT:
                continue
            dist = _perp_axis_distance(a, b)
            if dist <= max(1.0, 0.3 * a["radius"]):
                continue  # too close — same feature, not opposite slot ends
            # Opposite-facing check: each cap must bulge AWAY from its partner.
            # delta_perp points from a to b (perpendicular to the axis).
            if a.get("bulge") and b.get("bulge"):
                dx = (b["loc"][0] - a["loc"][0], b["loc"][1] - a["loc"][1],
                      b["loc"][2] - a["loc"][2])
                d = a["dir"]
                along = dx[0] * d[0] + dx[1] * d[1] + dx[2] * d[2]
                dp = (dx[0] - along * d[0], dx[1] - along * d[1], dx[2] - along * d[2])
                dpn = math.sqrt(dp[0] ** 2 + dp[1] ** 2 + dp[2] ** 2)
                if dpn > 1e-9:
                    dp = (dp[0] / dpn, dp[1] / dpn, dp[2] / dpn)
                    dot_a = (a["bulge"][0] * dp[0] + a["bulge"][1] * dp[1]
                             + a["bulge"][2] * dp[2])
                    dot_b = (b["bulge"][0] * dp[0] + b["bulge"][1] * dp[1]
                             + b["bulge"][2] * dp[2])
                    # a must face away from b (against delta) and b away from a
                    if not (dot_a < -0.5 and dot_b > 0.5):
                        continue
            pairs.append((dist, i, j))
    pairs.sort()
    for dist, i, j in pairs:
        if i in used or j in used:
            continue
        used.add(i)
        used.add(j)
        r = cap_groups[i]["radius"]
        _mid = tuple(
            (cap_groups[i]["loc"][k] + cap_groups[j]["loc"][k]) / 2 for k in range(3)
        )
        slots.append({"length_mm": round(dist + 2 * r, 2),
                      "width_mm": round(2 * r, 2), "open": False,
                      "x": round(_mid[0], 2), "y": round(_mid[1], 2),
                      "z": round(_mid[2], 2),
                      "depth_mm": round(max(cap_groups[i]["span"], cap_groups[j]["span"]), 2),
                      "axis_dir": tuple(round(v, 4) for v in cap_groups[i]["dir"]),
                      "open_dir": None,
                      "entry_dir": _entry_dir_for(cap_groups[i]),
                      "face_indices": sorted(
                          cap_groups[i]["members"] + cap_groups[j]["members"]
                      )})
        for fi in cap_groups[i]["members"] + cap_groups[j]["members"]:
            face_categories[fi] = "slot"

    # 5. Open slots: an unpaired cap whose arc opens (-bulge direction)
    #    toward a nearby body boundary is the closed end of a slot machined
    #    in from the part edge — e.g. edge tenon slots on a base plate.
    if bbox:
        body_max = max(bbox.get("xmax", 0) - bbox.get("xmin", 0),
                       bbox.get("ymax", 0) - bbox.get("ymin", 0),
                       bbox.get("zmax", 0) - bbox.get("zmin", 0), 1e-6)
        for i, g in enumerate(cap_groups):
            if i in used or not g.get("bulge"):
                continue
            open_dir = (-g["bulge"][0], -g["bulge"][1], -g["bulge"][2])
            t = _dist_to_bbox_edge(g["loc"], open_dir, bbox)
            if t is not None and t <= 0.45 * body_max:
                used.add(i)
                r = g["radius"]
                slots.append({"length_mm": round(t + r, 2),
                              "width_mm": round(2 * r, 2), "open": True,
                              "x": round(g["loc"][0], 2), "y": round(g["loc"][1], 2),
                              "z": round(g["loc"][2], 2),
                              "depth_mm": round(g["span"], 2),
                              # Tool axis for machining an open slot = the cap's
                              # cylinder axis (endmill plunges along it); the
                              # opening direction is where the cutter exits.
                              "axis_dir": tuple(round(v, 4) for v in g["dir"]),
                              "open_dir": tuple(round(v, 4) for v in open_dir),
                              "entry_dir": _entry_dir_for(g),
                              "face_indices": sorted(g["members"])})
                for fi in g["members"]:
                    face_categories[fi] = "slot"

    # 6. Everything else cylindrical is a hole: full cylinders + unpaired caps
    #    (an unpaired partial cylinder is most likely a hole seam remnant or
    #    fillet; counting it as a hole is the conservative choice).
    hole_like = list(hole_groups) + [
        g for i, g in enumerate(cap_groups) if i not in used
    ]
    for g in hole_like:
        for fi in g["members"]:
            face_categories[fi] = "hole"

    # Count DISTINCT hole positions: merge groups on the same axis line even
    # when radii differ — a counterbored/countersunk hole is one hole, not two.
    # Each axis line carries drilling data: largest radius (counterbore OD),
    # smallest radius (through/pilot dia), max axial span (depth) and axis dir.
    axis_lines = []
    for g in hole_like:
        merged = None
        for al in axis_lines:
            dot = abs(g["dir"][0] * al["dir"][0] + g["dir"][1] * al["dir"][1]
                      + g["dir"][2] * al["dir"][2])
            if dot >= _AXIS_PARALLEL_DOT and _perp_axis_distance(al, g) <= _SAME_AXIS_DIST_MM:
                merged = al
                break
        if merged is None:
            axis_lines.append({
                "loc": g["loc"], "dir": g["dir"],
                "radii": [g["radius"]], "span": g["span"],
                "prange": g.get("prange"),
                "members": list(g["members"]),
            })
        else:
            merged["radii"].append(g["radius"])
            merged["span"] = max(merged["span"], g["span"])
            merged["members"].extend(g["members"])
            pr = g.get("prange")
            if pr:
                d = g["dir"]
                flip = (d[0] * merged["dir"][0] + d[1] * merged["dir"][1]
                        + d[2] * merged["dir"][2]) < 0
                lo, hi = (-pr[1], -pr[0]) if flip else pr
                mp = merged.get("prange")
                merged["prange"] = (
                    (min(mp[0], lo), max(mp[1], hi)) if mp else (lo, hi)
                )
    leftover_axes = len(axis_lines)

    # Match cone faces to hole axis lines: a coaxial cone is the hole's
    # drill tip (tip angle 100-160 deg => blind) or countersink (~90 deg).
    # Cones matched to a hole are consumed; leftover narrow cones with
    # ~45 deg semi-angle are edge chamfers.
    cone_used = set()
    for al in axis_lines:
        al["tip_angle_deg"] = None
        al["countersink"] = False
        for ci, c in enumerate(cones):
            if ci in cone_used:
                continue
            dot = abs(c["dir"][0] * al["dir"][0] + c["dir"][1] * al["dir"][1]
                      + c["dir"][2] * al["dir"][2])
            if dot < _AXIS_PARALLEL_DOT:
                continue
            if _perp_axis_distance(al, c) > _SAME_AXIS_DIST_MM * 4:
                continue
            tip = round(2 * c["semi_deg"], 1)
            if 100.0 <= tip <= 165.0:
                al["tip_angle_deg"] = tip
                cone_used.add(ci)
            elif 80.0 <= tip < 100.0:
                al["countersink"] = True
                cone_used.add(ci)
    for ci, c in enumerate(cones):
        if ci not in cone_used and 30.0 <= c["semi_deg"] <= 60.0 \
                and c["span"] <= 8.0:
            chamfer_faces += 1

    # Body extent along each hole axis -> through/blind, depth below the
    # entry surface (0 for a hole starting at the outer face; >0 when the
    # hole starts on a recessed floor), and the signed entry direction
    # (outward normal of the face the tool enters from — drives setup
    # routing).
    body_range_cache = {}
    for al in axis_lines:
        al["through"] = None
        al["depth_below_top_mm"] = None
        al["entry_dir"] = None
        if not bbox or not al.get("prange"):
            continue
        dkey = tuple(round(v, 3) for v in al["dir"])
        if dkey not in body_range_cache:
            body_range_cache[dkey] = _bbox_range_along(al["dir"], bbox)
        bmin, bmax = body_range_cache[dkey]
        gap_lo = max(0.0, al["prange"][0] - bmin)
        gap_hi = max(0.0, bmax - al["prange"][1])
        al["through"] = gap_lo < 0.5 and gap_hi < 0.5
        if al["tip_angle_deg"] is not None:
            al["through"] = False  # a drill-tip cone means the hole ends inside
        al["depth_below_top_mm"] = round(min(gap_lo, gap_hi), 2)
        # Entry = the axis end nearer the body surface. Tool enters there;
        # entry_dir is the outward direction on that side.
        sign = 1.0 if gap_hi <= gap_lo else -1.0
        al["entry_dir"] = tuple(round(sign * v, 4) for v in al["dir"])

    holes_detail = []
    for al in axis_lines:
        dia = round(2 * min(al["radii"]), 2)
        depth = round(al["span"], 2)
        holes_detail.append({
            "x": round(al["loc"][0], 2), "y": round(al["loc"][1], 2),
            "z": round(al["loc"][2], 2),
            "dir": tuple(round(v, 4) for v in al["dir"]),
            "diameter_mm": dia,
            "cbore_diameter_mm": (
                round(2 * max(al["radii"]), 2) if len(set(
                    round(r, 2) for r in al["radii"]
                )) > 1 else None
            ),
            "depth_mm": depth,
            "ld_ratio": round(depth / dia, 2) if dia > 0 else None,
            "through": al["through"],
            "depth_below_top_mm": al["depth_below_top_mm"],
            "tip_angle_deg": al["tip_angle_deg"],
            "countersink": al["countersink"],
            "entry_dir": al["entry_dir"],
            "face_indices": sorted(al.get("members") or []),
        })

    return {
        "face_categories": face_categories,
        "hole_count": leftover_axes,
        "slot_count": len(slots),
        "slots": slots,
        "holes": holes_detail,
        "fillet_faces": fillet_faces,
        "chamfer_faces": chamfer_faces,
        "available": True,
    }
