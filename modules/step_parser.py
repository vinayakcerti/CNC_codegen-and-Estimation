import re
import math

# ---------------------------------------------------------------------------
# Unit detection helpers
# ---------------------------------------------------------------------------

_UNIT_FACTORS = {
    "mm": 1.0, "millimeter": 1.0, "millimetre": 1.0,
    "cm": 10.0, "centimeter": 10.0, "centimetre": 10.0,
    "m": 1000.0, "meter": 1000.0, "metre": 1000.0,
    "in": 25.4, "inch": 25.4, "inches": 25.4,
    "ft": 304.8, "foot": 304.8, "feet": 304.8,
}

_UNIT_LABELS = {
    1.0:   "mm  (millimetres — no conversion needed)",
    10.0:  "cm  (centimetres → converted to mm × 10)",
    1000.0:"m   (metres → converted to mm × 1000)",
    25.4:  "in  (inches → converted to mm × 25.4)",
    304.8: "ft  (feet → converted to mm × 304.8)",
}


def _detect_unit_factor(text: str):
    upper = text.upper()
    cbu_pattern = re.compile(r"CONVERSION_BASED_UNIT\s*\(\s*'([^']+)'", re.IGNORECASE)
    for m in cbu_pattern.finditer(text):
        name = m.group(1).strip().lower()
        for key, factor in _UNIT_FACTORS.items():
            if key == name or name.startswith(key):
                return factor, _UNIT_LABELS.get(factor, f"{name}→{factor}×mm"), "CONVERSION_BASED_UNIT"
    si_pattern = re.compile(
        r"SI_UNIT\s*\([^)]*\.(MILLI|CENTI|DECI|KILO|MEGA)?\.\s*,?\s*\.METRE\.", re.IGNORECASE)
    si_match = si_pattern.search(text)
    if si_match:
        prefix = (si_match.group(1) or "").upper()
        mapping = {
            "MILLI": (1.0,    "mm (SI_UNIT .MILLI.METRE.)"),
            "CENTI": (10.0,   "cm → ×10"),
            "DECI":  (100.0,  "dm → ×100"),
            "":      (1000.0, "m  → ×1000"),
            "KILO":  (1e6,    "km → ×1e6"),
        }
        if prefix in mapping:
            f, l = mapping[prefix]
            return f, l, "SI_UNIT entity"
    for key in ("INCH", "'IN'", "INCHES"):
        if key in upper:
            return 25.4, _UNIT_LABELS[25.4], "keyword hint"
    for key in ("MILLIMETER", "MILLIMETRE", "'MM'"):
        if key in upper:
            return 1.0, _UNIT_LABELS[1.0], "keyword hint"
    for key in ("METER", "METRE"):
        if key in upper and "MILLI" not in upper:
            return 1000.0, _UNIT_LABELS[1000.0], "keyword hint"
    return None, None, "heuristic"


def _heuristic_factor(max_span: float):
    if max_span < 0.5:
        return 1000.0, _UNIT_LABELS[1000.0], "heuristic (< 0.5 → metres)"
    if max_span < 3.0:
        return 25.4, _UNIT_LABELS[25.4], "heuristic (< 3 → inches)"
    return 1.0, _UNIT_LABELS[1.0], "assumed mm"


# ---------------------------------------------------------------------------
# Low-level entity extractors
# ---------------------------------------------------------------------------

_COORD3_RE = re.compile(
    r'#(\d+)=CARTESIAN_POINT\s*\(\s*\'[^\']*\'\s*,\s*\(\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*,\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*,\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*\)\s*\)',
    re.IGNORECASE,
)

_DIR3_RE = re.compile(
    r'#(\d+)=DIRECTION\s*\(\s*\'[^\']*\'\s*,\s*\(\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*,\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*,\s*'
    r'([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)\s*\)\s*\)',
    re.IGNORECASE,
)

_VP_RE  = re.compile(r'#(\d+)=VERTEX_POINT\s*\(\s*\'[^\']*\'\s*,\s*#(\d+)\s*\)', re.I)
_AP3_RE = re.compile(r'#(\d+)=AXIS2_PLACEMENT_3D\s*\(\s*\'[^\']*\'\s*,\s*#(\d+)\s*,\s*#(\d+)\s*,\s*#(\d+)\s*\)', re.I)
_CIRC_RE = re.compile(r'#(\d+)=CIRCLE\s*\(\s*\'[^\']*\'\s*,\s*#(\d+)\s*,\s*([0-9.Ee+-]+)\s*\)', re.I)
_EC_RE  = re.compile(r'#(\d+)=EDGE_CURVE\s*\(\s*\'[^\']*\'\s*,\s*#(\d+)\s*,\s*#(\d+)\s*,\s*#(\d+)\s*,\s*\.[TF]\.\s*\)', re.I)


def _perp_vectors(nx, ny, nz):
    """Return two unit vectors perpendicular to (nx,ny,nz)."""
    n = math.sqrt(nx*nx + ny*ny + nz*nz) or 1.0
    nx, ny, nz = nx/n, ny/n, nz/n
    if abs(nx) < 0.9:
        ax, ay, az = 1.0, 0.0, 0.0
    else:
        ax, ay, az = 0.0, 1.0, 0.0
    # u = n × a
    ux = ny*az - nz*ay
    uy = nz*ax - nx*az
    uz = nx*ay - ny*ax
    lu = math.sqrt(ux*ux + uy*uy + uz*uz) or 1.0
    ux, uy, uz = ux/lu, uy/lu, uz/lu
    # v = n × u
    vx = ny*uz - nz*uy
    vy = nz*ux - nx*uz
    vz = nx*uy - ny*ux
    return (ux, uy, uz), (vx, vy, vz)


def _circle_points(cx, cy, cz, r, nx, ny, nz, steps=48):
    """Generate 3D points for a circle with given center, radius, and normal."""
    (ux,uy,uz), (vx,vy,vz) = _perp_vectors(nx, ny, nz)
    pts_x, pts_y, pts_z = [], [], []
    for i in range(steps + 1):
        t = 2 * math.pi * i / steps
        c, s = math.cos(t), math.sin(t)
        pts_x.append(cx + r*(c*ux + s*vx))
        pts_y.append(cy + r*(c*uy + s*vy))
        pts_z.append(cz + r*(c*uz + s*vz))
    return pts_x, pts_y, pts_z


# ---------------------------------------------------------------------------
# Bounding-box parser (original functionality kept)
# ---------------------------------------------------------------------------

def parse_step_bounding_box(file_bytes: bytes) -> dict:
    try:
        text = file_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        return {"success": False, "message": f"Could not decode file: {exc}"}

    factor, unit_label, method = _detect_unit_factor(text)

    matches = _COORD3_RE.findall(text)
    if not matches:
        return {"success": False, "message": (
            "No CARTESIAN_POINT data found. File may be non-standard or 2D only. "
            "Please enter dimensions manually.")}

    xs, ys, zs = [], [], []
    for _, x_str, y_str, z_str in matches:
        try:
            xs.append(float(x_str)); ys.append(float(y_str)); zs.append(float(z_str))
        except ValueError:
            continue

    if not xs:
        return {"success": False, "message": "Could not parse coordinate values."}

    raw_max_span = max(max(xs)-min(xs), max(ys)-min(ys), max(zs)-min(zs))
    if factor is None:
        factor, unit_label, method = _heuristic_factor(raw_max_span)
    converted = factor != 1.0

    x_min, x_max = min(xs)*factor, max(xs)*factor
    y_min, y_max = min(ys)*factor, max(ys)*factor
    z_min, z_max = min(zs)*factor, max(zs)*factor
    length = round(x_max - x_min, 3)
    width  = round(y_max - y_min, 3)
    height = round(z_max - z_min, 3)

    if length < 0.001 and width < 0.001 and height < 0.001:
        return {"success": False, "message": "All points coincident — file may be empty or 2D only."}

    bbox_vol_cm3 = round(length * width * height / 1000.0, 3)
    part_vol_cm3 = round(bbox_vol_cm3 * 0.60, 3)

    conv_note = ""
    if converted:
        conv_note = (f" Coordinates in {unit_label.split('(')[0].strip()} "
                     f"— multiplied by {factor} to convert to mm.")
    message = (f"Extracted {len(xs):,} points · "
               f"Bounding box: {length} × {width} × {height} mm.{conv_note} "
               "Adjust volumes if needed.")

    return {
        "success": True,
        "length_mm": length, "width_mm": width, "height_mm": height,
        "stock_volume_cm3": bbox_vol_cm3, "part_volume_cm3": part_vol_cm3,
        "point_count": len(xs),
        "x_range": (round(x_min,3), round(x_max,3)),
        "y_range": (round(y_min,3), round(y_max,3)),
        "z_range": (round(z_min,3), round(z_max,3)),
        "x_range_raw": (round(min(xs),6), round(max(xs),6)),
        "y_range_raw": (round(min(ys),6), round(max(ys),6)),
        "z_range_raw": (round(min(zs),6), round(max(zs),6)),
        "detected_unit_label": unit_label,
        "conversion_factor": factor,
        "detection_method": method,
        "converted": converted,
        "message": message,
    }


# ---------------------------------------------------------------------------
# Geometry extractor — returns actual 3D wireframe data
# ---------------------------------------------------------------------------

def parse_step_geometry(file_bytes: bytes) -> dict:
    """
    Extract 3D wireframe geometry (straight edges + circular edges) from a STEP file.
    All coordinates returned in millimetres.

    Returns:
        success (bool)
        line_segments: list of (x1,y1,z1, x2,y2,z2)  — straight edges
        circle_traces: list of (xs, ys, zs, label)    — circle / arc polylines
        bbox: (xmin, xmax, ymin, ymax, zmin, zmax) in mm
        edge_count, circle_count
    """
    try:
        text = file_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        return {"success": False, "message": str(exc), "line_segments": [], "circle_traces": []}

    # ── Unit factor ──────────────────────────────────────────────────────────
    factor, unit_label, method = _detect_unit_factor(text)

    # ── CARTESIAN_POINT map: id → (x,y,z) raw ───────────────────────────────
    cp_map = {}
    for m in _COORD3_RE.finditer(text):
        cp_map[m.group(1)] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))

    if not cp_map:
        return {"success": False, "message": "No geometry found.", "line_segments": [], "circle_traces": []}

    # Finalise factor via heuristic if needed
    if factor is None:
        all_vals = [v for pt in cp_map.values() for v in pt]
        rng = max(all_vals) - min(all_vals) if all_vals else 1.0
        factor, _, _ = _heuristic_factor(rng)

    def pt_mm(eid):
        """Return (x,y,z) in mm for a cartesian point entity id."""
        if eid in cp_map:
            x,y,z = cp_map[eid]
            return (x*factor, y*factor, z*factor)
        return None

    # ── DIRECTION map: id → (dx,dy,dz) ──────────────────────────────────────
    dir_map = {}
    for m in _DIR3_RE.finditer(text):
        dir_map[m.group(1)] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))

    # ── VERTEX_POINT map: id → (x,y,z) mm ───────────────────────────────────
    vp_map = {}
    for m in _VP_RE.finditer(text):
        vid, pid = m.group(1), m.group(2)
        p = pt_mm(pid)
        if p:
            vp_map[vid] = p

    # ── AXIS2_PLACEMENT_3D: id → (cx,cy,cz, nx,ny,nz) mm ───────────────────
    ap_map = {}
    for m in _AP3_RE.finditer(text):
        apid, cid, axid = m.group(1), m.group(2), m.group(3)
        center = pt_mm(cid)
        if center:
            normal = dir_map.get(axid, (0.0, 0.0, 1.0))
            ap_map[apid] = (*center, *normal)

    # ── CIRCLE map: id → (cx,cy,cz, r, nx,ny,nz) mm ─────────────────────────
    circle_curve_map = {}
    for m in _CIRC_RE.finditer(text):
        cid, apid, r_str = m.group(1), m.group(2), m.group(3)
        r_mm = float(r_str) * factor
        if apid in ap_map:
            cx, cy, cz, nx, ny, nz = ap_map[apid]
            circle_curve_map[cid] = (cx, cy, cz, r_mm, nx, ny, nz)

    # ── EDGE_CURVE → build segments and circle traces ─────────────────────────
    line_segments  = []   # (x1,y1,z1, x2,y2,z2)
    circle_traces  = []   # (xs, ys, zs)
    seen_circles   = set()

    for m in _EC_RE.finditer(text):
        _, v1id, v2id, curveid = m.group(1), m.group(2), m.group(3), m.group(4)

        # Straight edge: both vertices different
        if v1id != v2id and v1id in vp_map and v2id in vp_map:
            x1,y1,z1 = vp_map[v1id]
            x2,y2,z2 = vp_map[v2id]
            line_segments.append((x1,y1,z1, x2,y2,z2))

        # Circular edge
        if curveid in circle_curve_map and curveid not in seen_circles:
            seen_circles.add(curveid)
            cx,cy,cz,r,nx,ny,nz = circle_curve_map[curveid]
            px,py,pz = _circle_points(cx, cy, cz, r, nx, ny, nz)
            circle_traces.append((px, py, pz))

    # ── Bounding box of geometry ──────────────────────────────────────────────
    all_x = [s[0] for s in line_segments] + [s[3] for s in line_segments]
    all_y = [s[1] for s in line_segments] + [s[4] for s in line_segments]
    all_z = [s[2] for s in line_segments] + [s[5] for s in line_segments]
    for px,py,pz in circle_traces:
        all_x.extend(px); all_y.extend(py); all_z.extend(pz)

    bbox = None
    if all_x:
        bbox = (min(all_x), max(all_x), min(all_y), max(all_y), min(all_z), max(all_z))

    return {
        "success": True,
        "line_segments": line_segments,
        "circle_traces": circle_traces,
        "bbox": bbox,
        "edge_count": len(line_segments),
        "circle_count": len(circle_traces),
        "factor": factor,
    }
