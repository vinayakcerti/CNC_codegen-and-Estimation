import re
import math
import os
import tempfile
import hashlib
import json
from itertools import permutations, product

# ---------------------------------------------------------------------------
# Optional CadQuery / OCC imports
# ---------------------------------------------------------------------------
#
# Keep CadQuery out of module import. When OpenCASCADE's native DLL state is
# broken, importing cadquery can terminate python.exe before Python exception
# handling runs. Lazy-loading lets Streamlit start and the lightweight STEP
# parser remain available.

cq = None
_CADQUERY_AVAILABLE = None
_OCC_ADAPTOR_AVAILABLE = False
_BRepAdaptor = None
_GeomAbsCylinder = None

MAX_STEP_FILE_BYTES = 200 * 1024 * 1024


_FEATURE_ID_PREFIXES = {
    "Face milling": "FACE",
    "Face Milling": "FACE",
    "Hole": "HOLE",
    "Large hole / boring": "BORE",
    "Slot": "SLOT",
    "Pocket": "POCKET",
    "Step": "STEP",
    "Chamfer": "CHAMFER",
    "Edge Milling": "EDGE",
}


def validate_step_payload(file_bytes: bytes) -> dict:
    """Validate a STEP payload before invoking native CAD libraries."""
    if not isinstance(file_bytes, (bytes, bytearray)):
        return {
            "success": False,
            "failure_reason": "INVALID_PAYLOAD",
            "message": "The uploaded file could not be read as binary data.",
            "detail": "The upload did not provide a valid byte payload.",
            "suggestion": "Choose the STEP file again and retry the upload.",
        }
    if not file_bytes:
        return {
            "success": False,
            "failure_reason": "EMPTY_FILE",
            "message": "The uploaded STEP file is empty.",
            "detail": "The file contains zero bytes, so there is no geometry to parse.",
            "suggestion": "Re-export the part from the CAD system and upload the exported file.",
        }
    if len(file_bytes) > MAX_STEP_FILE_BYTES:
        return {
            "success": False,
            "failure_reason": "FILE_TOO_LARGE",
            "message": "The STEP file is larger than the supported 200 MB limit.",
            "detail": f"Uploaded size: {len(file_bytes) / (1024 * 1024):.1f} MB.",
            "suggestion": (
                "Export only the required solid body, suppress unnecessary assemblies, "
                "or use a simplified STEP representation."
            ),
        }

    sample = bytes(file_bytes[:8192])
    if b"\x00" in sample:
        return {
            "success": False,
            "failure_reason": "BINARY_FILE",
            "message": "This file appears to be binary-encoded, not an ASCII STEP file.",
            "detail": "Null bytes were detected in the first 8 KB of the file.",
            "suggestion": "Re-export the model as an ASCII STEP AP203, AP214, or AP242 file.",
        }

    head = sample.decode("ascii", errors="ignore").upper()
    tail = bytes(file_bytes[-8192:]).decode("ascii", errors="ignore").upper()
    data_sample = bytes(file_bytes[:1024 * 1024]).upper()
    if "ISO-10303-21" not in head or "HEADER;" not in head or b"DATA;" not in data_sample:
        return {
            "success": False,
            "failure_reason": "NOT_STEP_FILE",
            "message": "This file does not contain a valid STEP exchange header.",
            "detail": "The required ISO-10303-21, HEADER, and DATA markers were not found.",
            "suggestion": "Upload an ASCII STEP AP203, AP214, or AP242 file.",
        }
    if "END-ISO-10303-21" not in tail:
        return {
            "success": False,
            "failure_reason": "TRUNCATED_STEP_FILE",
            "message": "The STEP file appears incomplete or truncated.",
            "detail": "The required END-ISO-10303-21 terminator was not found.",
            "suggestion": "Re-export or re-copy the file, then upload the complete STEP file.",
        }
    return {"success": True}


def _identity_number(value):
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None


def _candidate_physical_signature(candidate):
    position = candidate.get("cad_position") or {
        "x": candidate.get("x_pos"),
        "y": candidate.get("y_pos"),
        "z": candidate.get("z_pos"),
    }
    return {
        "feature_type": str(candidate.get("feature_type") or "").strip().lower(),
        "quantity": int(candidate.get("quantity") or 1),
        "position": {
            axis: _identity_number(position.get(axis))
            for axis in ("x", "y", "z")
        },
        "diameter": _identity_number(candidate.get("diameter")),
        "length": _identity_number(candidate.get("length")),
        "width": _identity_number(candidate.get("width")),
        "depth": _identity_number(candidate.get("depth")),
        "setup": candidate.get("setup_label"),
    }


def assign_stable_candidate_ids(candidates, source_file_hash):
    """Attach stable physical and exact-detection IDs recursively.

    Physical IDs intentionally exclude face indices, allowing split CAD faces
    that describe the same geometry to share one identity. Candidate IDs add
    sorted face provenance so each exact visual detection remains unique.
    """
    source_hash = str(source_file_hash or "unknown")
    for candidate in candidates or []:
        physical_payload = {
            "source_file_hash": source_hash,
            "geometry": _candidate_physical_signature(candidate),
        }
        physical_digest = hashlib.sha256(
            json.dumps(
                physical_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        prefix = _FEATURE_ID_PREFIXES.get(
            candidate.get("feature_type"),
            "FEATURE",
        )
        physical_id = f"{prefix}-{physical_digest[:16]}"
        exact_payload = {
            "physical_feature_id": physical_id,
            "face_indices": sorted(
                int(index)
                for index in candidate.get("face_indices", [])
            ),
            "detection_source": candidate.get("detection_source"),
        }
        exact_digest = hashlib.sha256(
            json.dumps(
                exact_payload,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        candidate["source_file_hash"] = source_hash
        candidate["physical_feature_id"] = physical_id
        candidate["candidate_id"] = f"{prefix}-{exact_digest[:16]}"

        assign_stable_candidate_ids(
            candidate.get("orientation_face_candidates", []),
            source_hash,
        )
        for candidate_set in candidate.get("detection_candidate_sets", []):
            assign_stable_candidate_ids(
                candidate_set.get("candidates", []),
                source_hash,
            )
    return candidates


def _load_cadquery():
    """Return cadquery module if available, else None."""
    global cq, _CADQUERY_AVAILABLE

    if _CADQUERY_AVAILABLE is not None:
        return cq if _CADQUERY_AVAILABLE else None

    if os.environ.get("CNC_DISABLE_CADQUERY", "").strip().lower() in {"1", "true", "yes"}:
        _CADQUERY_AVAILABLE = False
        return None

    try:
        import cadquery as _cq
        cq = _cq
        _CADQUERY_AVAILABLE = True
        _load_occ_adaptor()
        return cq
    except ImportError:
        _CADQUERY_AVAILABLE = False
        return None
    except Exception:
        # Non-native import errors can still be handled here. Native OCC crashes
        # may terminate the process before this block runs.
        _CADQUERY_AVAILABLE = False
        return None


def _load_occ_adaptor():
    """Load optional OCC surface adaptors after CadQuery is loaded."""
    global _OCC_ADAPTOR_AVAILABLE, _BRepAdaptor, _GeomAbsCylinder

    if _OCC_ADAPTOR_AVAILABLE:
        return
    try:
        from OCC.Core.BRepAdaptor import BRepAdaptor_Surface as _BRepAdaptorLocal
        from OCC.Core.GeomAbs import GeomAbs_Cylinder as _GeomAbsCylinderLocal
        _BRepAdaptor = _BRepAdaptorLocal
        _GeomAbsCylinder = _GeomAbsCylinderLocal
        _OCC_ADAPTOR_AVAILABLE = True
    except (ImportError, Exception):
        _OCC_ADAPTOR_AVAILABLE = False

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


def _setup_label_from_normal(nx=0.0, ny=0.0, nz=0.0):
    """Return a planning setup label from the dominant face normal."""
    vals = {
        "Right": float(nx or 0.0),
        "Left": -float(nx or 0.0),
        "Back": float(ny or 0.0),
        "Front": -float(ny or 0.0),
        "Top": float(nz or 0.0),
        "Bottom": -float(nz or 0.0),
    }
    label, value = max(vals.items(), key=lambda item: item[1])
    return label if value >= 0.5 else "Unknown"


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
    r'#(\d+)\s*=\s*CARTESIAN_POINT\s*\(\s*\'[^\']*\'\s*,\s*\(\s*'
    r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*,\s*'
    r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*,\s*'
    r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][+-]?\d+)?)\s*\)\s*\)',
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
    payload_status = validate_step_payload(file_bytes)
    if not payload_status["success"]:
        return payload_status

    # ── Binary file guard ────────────────────────────────────────────────────
    # Scan a sample of the file for null bytes; ASCII STEP never contains them.
    sample = file_bytes[:8192]
    if b'\x00' in sample:
        return {
            "success": False,
            "failure_reason": "BINARY_FILE",
            "message": "This file appears to be binary-encoded, not an ASCII STEP file.",
            "detail": (
                "Binary P21-encoded STEP files and other non-text formats cannot be "
                "read by this lightweight text-based parser. "
                "Null bytes were detected in the first 8 KB of the file."
            ),
            "suggestion": (
                "Re-export from your CAD software using ASCII STEP encoding "
                "(look for 'Save as ASCII', 'AP214 ASCII', or 'AP242 ASCII' in export options). "
                "In SolidWorks: File → Save As → STEP AP214, ensure 'ASCII' is selected. "
                "In Fusion 360: Export → STEP, default is ASCII. "
                "Alternatively, enter stock dimensions manually below."
            ),
        }

    try:
        text = file_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        return {
            "success": False,
            "failure_reason": "DECODE_ERROR",
            "message": f"Could not read file as text: {exc}",
            "detail": "The file could not be decoded as UTF-8 text.",
            "suggestion": (
                "Ensure the file is a valid ASCII STEP file (.step / .stp). "
                "Try re-saving the file and uploading again, or enter stock dimensions manually."
            ),
        }

    # ── STEP identity check ──────────────────────────────────────────────────
    header_sample = text[:1000].upper()
    looks_like_step = (
        "ISO-10303" in header_sample
        or "STEP" in header_sample
        or "DATA;" in header_sample
        or _COORD3_RE.search(text[:5000]) is not None
    )

    factor, unit_label, method = _detect_unit_factor(text)

    matches = _COORD3_RE.findall(text)
    if not matches:
        if not looks_like_step:
            return {
                "success": False,
                "failure_reason": "NOT_STEP_FILE",
                "message": "This file does not appear to be a valid STEP file.",
                "detail": (
                    "No standard STEP markers (ISO-10303 header, DATA section, or "
                    "CARTESIAN_POINT entities) were found in the file. "
                    "It may be a different CAD format (IGES, DXF, STL, OBJ, etc.)."
                ),
                "suggestion": (
                    "Upload a file with a .step or .stp extension exported from a CAD tool. "
                    "Accepted formats: STEP AP203, AP214, AP242 in ASCII encoding. "
                    "Other formats (IGES, DXF, STL) are not supported by this parser."
                ),
            }
        return {
            "success": False,
            "failure_reason": "NO_CARTESIAN_POINTS",
            "message": (
                "Could not extract valid 3D geometry from this STEP file. "
                "The file may use B-spline/NURBS surfaces or a STEP structure "
                "not supported by the lightweight parser."
            ),
            "detail": (
                "The file was identified as a STEP file but contains no inline "
                "CARTESIAN_POINT entities in the expected form: "
                "CARTESIAN_POINT('', (x, y, z)). "
                "This typically means the file uses B-spline or NURBS surfaces, "
                "stores coordinates via complex entity references, or was exported "
                "with a schema that this parser does not support."
            ),
            "suggestion": (
                "Try re-exporting from your CAD software as STEP AP214 or AP242 "
                "with 'B-Rep solid geometry' (not surface/mesh). "
                "In SolidWorks: File → Save As → STEP AP214. "
                "In CATIA: Export as STEP with 'Exact geometry'. "
                "In Rhino: File → Export → STEP, choose 'Solids' not 'Surfaces'. "
                "You can also enter stock dimensions manually below and continue planning."
            ),
        }

    xs, ys, zs = [], [], []
    for _, x_str, y_str, z_str in matches:
        try:
            xs.append(float(x_str)); ys.append(float(y_str)); zs.append(float(z_str))
        except ValueError:
            continue

    if not xs:
        return {
            "success": False,
            "failure_reason": "NO_VALID_COORDS",
            "message": "CARTESIAN_POINT entities were found but their coordinates could not be parsed.",
            "detail": (
                f"{len(matches):,} CARTESIAN_POINT pattern matches were found, but all "
                "coordinate values failed to convert to numbers. "
                "The file may use a non-standard number format or contain corrupted data."
            ),
            "suggestion": (
                "Try re-exporting the STEP file from the original CAD tool. "
                "If the problem persists, the file may be corrupted. "
                "Enter stock dimensions manually below to continue."
            ),
        }

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
        return {
            "success": False,
            "failure_reason": "ZERO_BBOX",
            "message": "All extracted points are coincident — bounding box has zero size.",
            "detail": (
                f"{len(xs):,} coordinate points were found but all resolve to the same "
                "location after unit conversion. "
                "This can happen with 2D drawings, empty STEP shells, or files that "
                "contain only reference geometry (axis systems, datum points, construction lines)."
            ),
            "suggestion": (
                "Confirm the STEP file contains a 3D solid body by opening it in a CAD viewer. "
                "If it is a 2D drawing, you will need to enter stock dimensions manually. "
                "If it is a 3D part, try re-exporting with 'Save solid bodies' enabled."
            ),
        }

    # ── Soft warnings for successful parse ───────────────────────────────────
    soft_warnings = []

    if method == "heuristic":
        raw_label = unit_label.split("(")[0].strip()
        soft_warnings.append(
            f"Unit detection fell back to a size heuristic "
            f"(largest raw span: {round(raw_max_span, 4)} → assumed **{raw_label}**). "
            "If the dimensions below look wrong, override the unit assumption by "
            "adjusting the values manually."
        )

    dims_sorted = sorted([length, width, height])
    if dims_sorted[2] > 0 and dims_sorted[0] < dims_sorted[2] * 0.01:
        thin_axis = (
            "Z (height)" if height == dims_sorted[0] else
            "Y (width)"  if width  == dims_sorted[0] else
            "X (length)"
        )
        soft_warnings.append(
            f"Geometry appears extremely flat: {thin_axis} is only {dims_sorted[0]} mm "
            f"against a longest span of {dims_sorted[2]} mm. "
            "This may indicate a 2D drawing, a thin sheet/plate, or an incorrectly "
            "oriented STEP export. Verify the part is the intended 3D solid."
        )

    largest_dim = max(length, width, height)
    if largest_dim > 5000:
        soft_warnings.append(
            f"Bounding box appears implausibly large: largest dimension is "
            f"**{largest_dim:,.1f} mm** ({largest_dim/1000:.2f} m). "
            "This usually means unit detection chose the wrong scale factor. "
            "Check the 'Detected Units' field below — if it shows metres or feet "
            "when the part should be in millimetres, the conversion failed. "
            "Override the dimensions manually."
        )

    # ── Build success response (all original fields preserved) ───────────────
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
        "warnings": soft_warnings,
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


# ---------------------------------------------------------------------------
# CadQuery face-level data extractor (Step 1 of feature candidate detection)
# ---------------------------------------------------------------------------

def _extract_face_records(cq_result) -> list:
    """
    Iterate every OCC face in a loaded CadQuery workplane and return a list
    of plain dicts with geometry properties — one dict per face.

    All coordinates and lengths are in millimetres (OCC native unit for STEP).
    Individual face failures are silenced: the record is still appended with
    None for any field that could not be computed.  The function never raises.

    Normal convention:
        PLANE   → face.normalAt() is the constant surface normal.
        CYLINDER→ face.normalAt() is the outward radial normal at the UV-centre
                  of that face, NOT the cylinder axis.  Use cylinder_axis_x/y/z
                  (from the OCC adaptor) for the axis direction.
        BSPLINE → normalAt() may fail; fields left as None.

    Args:
        cq_result: cadquery.Workplane as returned by
                   cadquery.importers.importStep().

    Returns:
        list[dict] with keys:
            face_index, geom_type,
            area_mm2,
            center_x, center_y, center_z,
            normal_x, normal_y, normal_z,
            bbox_xmin, bbox_xmax,
            bbox_ymin, bbox_ymax,
            bbox_zmin, bbox_zmax,
            bbox_length_x, bbox_length_y, bbox_length_z,
            cylinder_radius_mm,          # None if not CYLINDER or OCC unavail.
            cylinder_axis_x/y/z          # None same conditions
    """
    records = []

    try:
        faces = cq_result.faces().vals()
    except Exception:
        return records

    for idx, face in enumerate(faces):
        rec = {
            "face_index":         idx,
            "geom_type":          None,
            "area_mm2":           None,
            "center_x":           None,
            "center_y":           None,
            "center_z":           None,
            "normal_x":           None,
            "normal_y":           None,
            "normal_z":           None,
            "bbox_xmin":          None,
            "bbox_xmax":          None,
            "bbox_ymin":          None,
            "bbox_ymax":          None,
            "bbox_zmin":          None,
            "bbox_zmax":          None,
            "bbox_length_x":      None,
            "bbox_length_y":      None,
            "bbox_length_z":      None,
            "cylinder_radius_mm": None,
            "cylinder_axis_x":    None,
            "cylinder_axis_y":    None,
            "cylinder_axis_z":    None,
        }

        try:
            rec["geom_type"] = face.geomType()
        except Exception:
            pass

        try:
            rec["area_mm2"] = round(face.Area(), 4)
        except Exception:
            pass

        try:
            c = face.Center()
            rec["center_x"] = round(c.x, 4)
            rec["center_y"] = round(c.y, 4)
            rec["center_z"] = round(c.z, 4)
        except Exception:
            pass

        try:
            # Evaluates at the mid-point of the face's UV parameter range.
            # Reliable for PLANE; for CYLINDER gives a radial outward normal
            # at one point only.  May fail for degenerate BSPLINE surfaces.
            n = face.normalAt()
            rec["normal_x"] = round(n.x, 6)
            rec["normal_y"] = round(n.y, 6)
            rec["normal_z"] = round(n.z, 6)
        except Exception:
            pass

        try:
            bb = face.BoundingBox()
            rec["bbox_xmin"] = round(bb.xmin, 4)
            rec["bbox_xmax"] = round(bb.xmax, 4)
            rec["bbox_ymin"] = round(bb.ymin, 4)
            rec["bbox_ymax"] = round(bb.ymax, 4)
            rec["bbox_zmin"] = round(bb.zmin, 4)
            rec["bbox_zmax"] = round(bb.zmax, 4)
            # xlen / ylen / zlen are available in CadQuery's BoundBox but guard
            # against older builds that may not expose them.
            rec["bbox_length_x"] = round(
                getattr(bb, "xlen", bb.xmax - bb.xmin), 4)
            rec["bbox_length_y"] = round(
                getattr(bb, "ylen", bb.ymax - bb.ymin), 4)
            rec["bbox_length_z"] = round(
                getattr(bb, "zlen", bb.zmax - bb.zmin), 4)
        except Exception:
            pass

        # Precise cylinder geometry via OCC BRepAdaptor
        if _OCC_ADAPTOR_AVAILABLE and rec.get("geom_type") == "CYLINDER":
            try:
                adaptor = _BRepAdaptor(face.wrapped)
                if adaptor.GetType() == _GeomAbsCylinder:
                    cyl = adaptor.Cylinder()
                    rec["cylinder_radius_mm"] = round(cyl.Radius(), 4)
                    d = cyl.Axis().Direction()
                    rec["cylinder_axis_x"] = round(d.X(), 6)
                    rec["cylinder_axis_y"] = round(d.Y(), 6)
                    rec["cylinder_axis_z"] = round(d.Z(), 6)
            except Exception:
                pass

        records.append(rec)

    return records


# ---------------------------------------------------------------------------
# CadQuery-based bounding box + volume parser (optional — requires cadquery)
# ---------------------------------------------------------------------------

def parse_step_with_cadquery(file_path: str) -> dict:
    """
    Parse a STEP file using CadQuery / OpenCASCADE.

    Returns a dict with the same keys expected by app.py from
    parse_step_bounding_box, plus parser_used and removed_volume_cm3.
    Does NOT catch exceptions — callers handle fallback.

    Requires: cadquery installed (not in requirements.txt for Cloud deploy).
    Units: OCC always works in mm for STEP, so no unit conversion is needed.
    """
    _cq = _load_cadquery()
    if _cq is None:
        raise ImportError("CadQuery is not available")

    result = _cq.importers.importStep(file_path)
    bb = result.val().BoundingBox()

    length = round(bb.xmax - bb.xmin, 3)
    width  = round(bb.ymax - bb.ymin, 3)
    height = round(bb.zmax - bb.zmin, 3)

    if length < 0.001 and width < 0.001 and height < 0.001:
        raise ValueError(
            f"CadQuery bounding box is effectively zero: "
            f"{length} × {width} × {height} mm. "
            "The file may be empty or contain only 2D geometry."
        )

    stock_vol_cm3 = round(length * width * height / 1000.0, 3)

    warnings = []

    # Real solid volume — OCC returns mm³; zero means a surface shell, not a solid
    raw_vol_mm3 = result.val().Volume()
    part_vol_cm3 = round(raw_vol_mm3 / 1000.0, 3)

    if part_vol_cm3 <= 0:
        part_vol_cm3  = round(stock_vol_cm3 * 0.60, 3)
        volume_source = "bbox_estimate_fallback"
        warnings.append(
            "CadQuery reported zero part volume — the file may be a surface/shell "
            "model rather than a closed solid. "
            f"Part volume estimated as 60% of bounding box ({part_vol_cm3} cm³). "
            "Adjust manually if your part geometry is significantly different."
        )
    else:
        volume_source = "cadquery_real_solid_volume"

    removed_vol_cm3 = round(max(stock_vol_cm3 - part_vol_cm3, 0.0), 3)

    # Topology counts — wrapped individually; some STEP files lack certain types
    def _safe_count(fn):
        try:
            return len(fn().vals())
        except Exception:
            return None

    solids_count   = _safe_count(result.solids)
    shells_count   = _safe_count(result.shells)
    faces_count    = _safe_count(result.faces)
    edges_count    = _safe_count(result.edges)
    vertices_count = _safe_count(result.vertices)

    message = (
        f"CadQuery parsed: {length} × {width} × {height} mm · "
        f"Stock {stock_vol_cm3} cm³ · Part {part_vol_cm3} cm³ · "
        f"Removed {removed_vol_cm3} cm³."
    )

    # Feature candidate detection — never raises; failures surface as warnings only
    _cand = detect_feature_candidates_from_cadquery_file(file_path)

    return {
        "success": True,
        "message": message,
        "parser_used": "cadquery",
        # Core dimensions
        "length_mm": length,
        "width_mm":  width,
        "height_mm": height,
        # Volumes
        "stock_volume_cm3":   stock_vol_cm3,
        "part_volume_cm3":    part_vol_cm3,
        "removed_volume_cm3": removed_vol_cm3,
        "volume_source":      volume_source,
        # Topology counts
        "solids_count":   solids_count,
        "shells_count":   shells_count,
        "faces_count":    faces_count,
        "edges_count":    edges_count,
        "vertices_count": vertices_count,
        # Coordinate ranges derived from bounding box (mm)
        "x_range": (round(bb.xmin, 3), round(bb.xmax, 3)),
        "y_range": (round(bb.ymin, 3), round(bb.ymax, 3)),
        "z_range": (round(bb.zmin, 3), round(bb.zmax, 3)),
        # Raw ranges same as converted (no unit conversion needed)
        "x_range_raw": (round(bb.xmin, 6), round(bb.xmax, 6)),
        "y_range_raw": (round(bb.ymin, 6), round(bb.ymax, 6)),
        "z_range_raw": (round(bb.zmin, 6), round(bb.zmax, 6)),
        # Unit / conversion metadata (OCC always returns mm)
        "converted":           False,
        "detection_method":    "cadquery",
        "detected_unit_label": "mm (CadQuery/OpenCASCADE)",
        "conversion_factor":   1.0,
        # Not applicable for CadQuery path
        "point_count": None,
        "warnings": warnings,
        # Feature candidates from face-record classification
        "candidate_features":  _cand.get("candidate_features", []),
        "candidate_count":     _cand.get("candidate_count", 0),
        "candidate_warnings":  _cand.get("warnings", []),
    }


# ---------------------------------------------------------------------------
# Auto-dispatcher: try CadQuery, fall back to lightweight parser
# ---------------------------------------------------------------------------

def parse_step_auto(file_bytes: bytes) -> dict:
    """
    Primary entry point for STEP parsing in app.py (future).

    Strategy:
    - CadQuery not installed → lightweight parser (unchanged behaviour)
    - CadQuery installed, succeeds → cadquery result
    - CadQuery installed, raises → lightweight parser + cadquery_warning key

    The returned dict is always compatible with parse_step_bounding_box output.
    Extra keys (parser_used, removed_volume_cm3, cadquery_warning) are additive.
    """
    payload_status = validate_step_payload(file_bytes)
    if not payload_status["success"]:
        return payload_status

    if _load_cadquery() is None:
        result = parse_step_bounding_box(file_bytes)
        result["parser_used"]        = "lightweight"
        result["degraded_mode"]      = True
        result["deep_feature_detection_available"] = False
        result["cadquery_warning"]   = (
            "CadQuery/OpenCASCADE is unavailable. Bounding-box geometry was recovered "
            "with the lightweight parser, but solid preview and feature detection are disabled."
        )
        result["volume_source"]      = "bbox_estimate_60_percent"
        result["solids_count"]       = None
        result["shells_count"]       = None
        result["faces_count"]        = None
        result["edges_count"]        = None
        result["vertices_count"]     = None
        result["candidate_features"] = []
        result["candidate_count"]    = 0
        result["candidate_warnings"] = []
        return result

    tmp_path = None
    try:
        # Windows requires delete=False: CadQuery opens the file itself and
        # the OS blocks deletion of an open file handle.
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        result = parse_step_with_cadquery(tmp_path)
        result["degraded_mode"] = False
        result["deep_feature_detection_available"] = True
        return result

    except Exception as exc:
        result = parse_step_bounding_box(file_bytes)
        result["parser_used"]        = "lightweight_fallback"
        result["degraded_mode"]      = True
        result["deep_feature_detection_available"] = False
        result["cadquery_warning"]   = (
            f"CadQuery parsing failed ({type(exc).__name__}: {exc}). "
            "Fell back to lightweight regex parser."
        )
        result["volume_source"]      = "bbox_estimate_60_percent"
        result["solids_count"]       = None
        result["shells_count"]       = None
        result["faces_count"]        = None
        result["edges_count"]        = None
        result["vertices_count"]     = None
        result["candidate_features"] = []
        result["candidate_count"]    = 0
        result["candidate_warnings"] = []
        return result

    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Non-fatal: temp file cleanup failure on Windows


# ---------------------------------------------------------------------------
# Feature candidate classification (experiment — not wired into parse_step_auto)
# ---------------------------------------------------------------------------

def _classify_face_records_in_frame(face_records: list, part_bbox: dict) -> list:
    """
    Classify extracted face records into preliminary machinable feature candidates.

    Detects three candidate types:
        A. Face milling  — large planar faces with normal ≈ ±Z
        B. Hole / Large hole / boring — individual cylindrical faces
        C. Slot          — paired cylindrical faces with matching Z range
                           and axis alignment (slot ends)

    Args:
        face_records : list[dict] from _extract_face_records()
        part_bbox    : dict with keys length_mm, width_mm, height_mm,
                       x_range, y_range, z_range

    Returns:
        list[dict]  one candidate dict per detected feature; never raises
    """
    candidates = []

    part_length  = float(part_bbox.get("length_mm") or 0)
    part_width   = float(part_bbox.get("width_mm")  or 0)
    part_height  = float(part_bbox.get("height_mm") or 0)
    xy_footprint = part_length * part_width   # mm²

    _f_n = [0]   # facing ID counter (list for mutability inside nested scope)
    _h_n = [0]   # hole ID counter
    _s_n = [0]   # slot ID counter

    # ── A. Facing candidates ─────────────────────────────────────────────────
    # Only large setup-level horizontal faces qualify as Face milling candidates.
    # Small horizontal faces (blind hole bottoms, pocket floors, step ledges)
    # are excluded by the 35% footprint-area threshold.
    # At most one top candidate and one bottom candidate are emitted.
    _NZ_THRESH       = 0.92   # |normal_z| > 0.92 (within ~23° of ±Z)
    _MIN_AREA_MM2    = 200.0  # absolute floor — unconditional sliver filter
    _FOOTPRINT_RATIO = 0.35   # face must cover >= 35% of XY footprint to qualify

    # XY footprint computed from part bounding-box coordinate ranges.
    xr = part_bbox.get("x_range", (0.0, 0.0))
    yr = part_bbox.get("y_range", (0.0, 0.0))
    footprint_area = (xr[1] - xr[0]) * (yr[1] - yr[0])   # mm²
    min_qual_area  = (
        footprint_area * _FOOTPRINT_RATIO if footprint_area > 0 else _MIN_AREA_MM2
    )

    top_hz_faces    = []   # PLANE faces with nz > 0 that pass the area threshold
    bottom_hz_faces = []   # PLANE faces with nz < 0 that pass the area threshold

    for r in face_records:
        if r.get("geom_type") != "PLANE":
            continue
        nz = r.get("normal_z")
        if nz is None or abs(nz) <= _NZ_THRESH:
            continue
        area = r.get("area_mm2") or 0.0
        if area < _MIN_AREA_MM2:
            continue
        # Reject faces that do not cover enough of the part XY footprint.
        # This eliminates blind hole bottoms, pocket floors, and step ledges
        # which all have areas well below 35% of the part footprint.
        if footprint_area > 0 and area < min_qual_area:
            continue
        if nz > 0:
            top_hz_faces.append(r)
        else:
            bottom_hz_faces.append(r)

    # Emit at most one candidate per direction — the largest qualifying face by area.
    for face_dir, face_list in (("top", top_hz_faces), ("bottom", bottom_hz_faces)):
        if not face_list:
            continue
        best = max(face_list, key=lambda r: r.get("area_mm2") or 0.0)
        _f_n[0] += 1
        cid  = f"F{_f_n[0]:03d}"
        area = best.get("area_mm2") or 0.0
        nz   = best.get("normal_z") or 0.0
        lx   = round(best.get("bbox_length_x") or 0, 3)
        ly   = round(best.get("bbox_length_y") or 0, 3)
        pct  = (area / footprint_area * 100) if footprint_area > 0 else 0.0

        base_note = (
            f"Face #{best['face_index']}; normal_z={nz:.4f}; "
            f"area={area:.1f} mm^2 ({pct:.1f}% of XY footprint "
            f"{footprint_area:.1f} mm^2, threshold >={_FOOTPRINT_RATIO*100:.0f}%); "
            f"default facing allowance 1.0 mm."
        )
        if face_dir == "top":
            _face_note = (
                f"Top facing candidate — largest qualifying top horizontal face. "
                + base_note
            )
        else:
            _face_note = (
                f"Bottom facing candidate — largest qualifying bottom horizontal face; "
                f"likely requires flip / second setup. "
                + base_note
            )

        candidates.append({
            "candidate_id":     cid,
            "feature_name":     f"Face milling — {face_dir} surface",
            "feature_type":     "Face milling",
            "quantity":         1,
            "x_pos":            best.get("center_x"),
            "y_pos":            best.get("center_y"),
            "diameter":         None,
            "length":           lx or None,
            "width":            ly or None,
            "depth":            1.0,
            "tolerance_note":   "",
            "priority":         1,
            "confidence":       "high",
            "setup_label":      _setup_label_from_normal(0.0, 0.0, nz),
            "detection_source": "cadquery_face_records",
            "detection_note":   _face_note,
            "face_indices":     [best["face_index"]],
            "accepted": False,
            "ignored":  False,
        })

    # Retain the largest qualifying outer face in every CAD direction. The
    # stock/orientation layer later selects the pair that maps to work Top and
    # Bottom. This prevents Y-up/X-up STEP files from reusing CAD Z faces as
    # misleading planning-facing operations.
    setup_face_alternatives = []
    axis_specs = (
        ("x", "normal_x", part_width * part_height, ("bbox_length_y", "bbox_length_z")),
        ("y", "normal_y", part_length * part_height, ("bbox_length_x", "bbox_length_z")),
        ("z", "normal_z", part_length * part_width, ("bbox_length_x", "bbox_length_y")),
    )
    for axis, normal_key, cross_area, span_keys in axis_specs:
        for sign, raw_setup in ((1, {"x": "Right", "y": "Back", "z": "Top"}[axis]),
                                (-1, {"x": "Left", "y": "Front", "z": "Bottom"}[axis])):
            qualifying = []
            for record in face_records:
                if record.get("geom_type") != "PLANE":
                    continue
                normal = float(record.get(normal_key) or 0.0)
                area = float(record.get("area_mm2") or 0.0)
                if sign * normal <= _NZ_THRESH or area < _MIN_AREA_MM2:
                    continue
                if cross_area > 0 and area < cross_area * _FOOTPRINT_RATIO:
                    continue
                qualifying.append(record)
            if not qualifying:
                continue
            best = max(qualifying, key=lambda record: record.get("area_mm2") or 0.0)
            setup_face_alternatives.append({
                "candidate_id": f"ORIENT_FACE_{raw_setup.upper()}",
                "feature_name": f"Face milling - CAD {raw_setup.lower()} surface",
                "feature_type": "Face milling",
                "quantity": 1,
                "x_pos": best.get("center_x"),
                "y_pos": best.get("center_y"),
                "diameter": None,
                "length": round(float(best.get(span_keys[0]) or 0.0), 3),
                "width": round(float(best.get(span_keys[1]) or 0.0), 3),
                "depth": 1.0,
                "tolerance_note": "",
                "priority": 1,
                "confidence": "high",
                "setup_label": raw_setup,
                "detection_source": "cadquery_setup_face_alternative",
                "detection_note": (
                    f"Orientation candidate from CAD {raw_setup} face "
                    f"#{best['face_index']}; selected only if it maps to work Top/Bottom."
                ),
                "face_indices": [best["face_index"]],
                "cad_position": {
                    "x": round(float(best.get("center_x") or 0.0), 6),
                    "y": round(float(best.get("center_y") or 0.0), 6),
                    "z": round(float(best.get("center_z") or 0.0), 6),
                },
                "accepted": False,
                "ignored": False,
            })
    if candidates and setup_face_alternatives:
        candidates[0]["orientation_face_candidates"] = setup_face_alternatives

    # ── B. Hole / bore candidates ────────────────────────────────────────────
    # Only CYLINDER faces that are circular in the machining plane (XY) qualify.
    # circular_xy = bbox spans in X and Y are within 15% of each other.
    # Non-circular cylinder bboxes indicate slot-end curved walls — skipped here.
    cyl_faces = [r for r in face_records if r.get("geom_type") == "CYLINDER"]

    for r in cyl_faces:
        lx = r.get("bbox_length_x") or 0
        ly = r.get("bbox_length_y") or 0
        circular_xy = (
            lx > 0 and ly > 0
            and abs(lx - ly) / max(lx, ly) <= 0.15
        )

        if not circular_xy:
            continue   # non-circular bbox → slot-end wall, not a standalone hole

        _h_n[0] += 1
        cid = f"H{_h_n[0]:03d}"

        exact_r = r.get("cylinder_radius_mm")

        if exact_r is not None:
            diameter   = round(exact_r * 2, 3)
            confidence = "high"
            diam_note  = f"OCC adaptor radius={exact_r:.4f} mm"
        elif lx > 0 and ly > 0:
            diameter   = round((lx + ly) / 2.0, 3)
            confidence = "medium"
            diam_note  = f"bbox-estimated from spans lx={lx:.3f} ly={ly:.3f} mm"
        else:
            diameter   = None
            confidence = "medium"
            diam_note  = "diameter unknown — bbox spans unavailable"

        lz         = r.get("bbox_length_z") or 0
        depth      = round(lz, 3) if lz > 0 else None
        is_through = part_height > 0 and lz >= part_height * 0.70

        ftype = (
            "Hole" if (diameter is None or diameter < 25)
            else "Large hole / boring"
        )
        name = (
            f"{ftype} Ø{diameter:.2f} mm" if diameter is not None else ftype
        )

        candidates.append({
            "candidate_id":     cid,
            "feature_name":     name,
            "feature_type":     ftype,
            "quantity":         1,
            "x_pos":            r.get("center_x"),
            "y_pos":            r.get("center_y"),
            "diameter":         diameter,
            "length":           None,
            "width":            None,
            "depth":            depth,
            "tolerance_note":   "",
            "priority":         2,
            "confidence":       confidence,
            "setup_label":      "Top",
            "detection_source": "cadquery_face_records",
            "detection_note":   (
                f"Cylinder face #{r['face_index']}; "
                f"circular_xy=True (lx={lx:.3f} ly={ly:.3f} mm, ratio≤0.15) → treated as hole/bore; "
                f"{diam_note}; "
                f"depth={depth} mm "
                f"({'through' if is_through else 'blind or partial'})."
            ),
            "face_indices":     [r["face_index"]],
            "accepted": False,
            "ignored":  False,
        })

    # ── C. Slot candidates ───────────────────────────────────────────────────
    # Detect pairs of cylindrical faces with: similar radius, matching Z range,
    # and centers aligned primarily along one axis (X or Y slot orientation).
    # Only non-circular cylinder faces (circular_xy=False) are considered as
    # slot-end walls.  Circular cylinders are holes/bores and excluded here.
    _slot_items = []
    for r in cyl_faces:
        lx = r.get("bbox_length_x") or 0
        ly = r.get("bbox_length_y") or 0
        circular_xy = (
            lx > 0 and ly > 0
            and abs(lx - ly) / max(lx, ly) <= 0.15
        )

        if circular_xy:
            continue   # circular → already a hole/bore candidate, not a slot end

        exact_r = r.get("cylinder_radius_mm")

        if exact_r is not None:
            est_r = exact_r
        elif lx > 0 and ly > 0:
            est_r = (lx + ly) / 4.0   # (lx+ly)/2 is diameter estimate; /4 = radius
        else:
            est_r = None

        if est_r is None or est_r <= 0:
            continue

        _slot_items.append({
            "rec":        r,
            "est_radius": est_r,
            "cx":   r.get("center_x") or 0.0,
            "cy":   r.get("center_y") or 0.0,
            "zmin": r.get("bbox_zmin"),
            "zmax": r.get("bbox_zmax"),
            "lz":   r.get("bbox_length_z") or 0.0,
        })

    _RADIUS_TOL = 0.20   # pair radii must be within 20% of their average
    _Z_TOL_MM   = 2.0    # absolute mm tolerance for matching Z extents
    used        = set()
    slot_pairs  = []

    for i in range(len(_slot_items)):
        if i in used:
            continue
        a = _slot_items[i]

        for j in range(i + 1, len(_slot_items)):
            if j in used:
                continue
            b = _slot_items[j]

            # Radius similarity
            r_avg = (a["est_radius"] + b["est_radius"]) / 2.0
            if abs(a["est_radius"] - b["est_radius"]) / r_avg > _RADIUS_TOL:
                continue

            # Z-range overlap: both zmin and zmax must agree within tolerance
            if (a["zmin"] is None or b["zmin"] is None
                    or a["zmax"] is None or b["zmax"] is None):
                continue
            if (abs(a["zmin"] - b["zmin"]) > _Z_TOL_MM
                    or abs(a["zmax"] - b["zmax"]) > _Z_TOL_MM):
                continue

            # Axis alignment: one axis dominates, the other is within one diameter
            dx   = abs(a["cx"] - b["cx"])
            dy   = abs(a["cy"] - b["cy"])
            diam = r_avg * 2.0
            x_aligned = dx > diam and dy < diam * 0.6   # slot runs along X
            y_aligned = dy > diam and dx < diam * 0.6   # slot runs along Y

            if not (x_aligned or y_aligned):
                continue

            used.add(i)
            used.add(j)
            slot_pairs.append((a, b, r_avg))
            break   # face i is consumed; move to i+1

    for (a, b, r_avg) in slot_pairs:
        _s_n[0] += 1
        cid = f"S{_s_n[0]:03d}"

        diam_slot   = round(r_avg * 2.0, 3)
        ctr_dist    = math.sqrt(
            (a["cx"] - b["cx"]) ** 2 + (a["cy"] - b["cy"]) ** 2
        )
        slot_length = round(ctr_dist + diam_slot, 3)
        slot_depth  = (
            round((a["lz"] + b["lz"]) / 2.0, 3)
            if a["lz"] and b["lz"] else None
        )
        slot_cx = round((a["cx"] + b["cx"]) / 2.0, 3)
        slot_cy = round((a["cy"] + b["cy"]) / 2.0, 3)

        candidates.append({
            "candidate_id":     cid,
            "feature_name":     f"Slot {slot_length:.2f}×{diam_slot:.2f} mm",
            "feature_type":     "Slot",
            "quantity":         1,
            "x_pos":            slot_cx,
            "y_pos":            slot_cy,
            "diameter":         None,
            "length":           slot_length,
            "width":            diam_slot,
            "depth":            slot_depth,
            "tolerance_note":   "",
            "priority":         3,
            "confidence":       "medium",
            "setup_label":      "Top",
            "detection_source": "cadquery_face_records",
            "detection_note":   (
                f"Paired non-circular cylinder end faces "
                f"#{a['rec']['face_index']} and #{b['rec']['face_index']} "
                f"(circular_xy=False on both, excluded from hole detection); "
                f"est. radius={r_avg:.3f} mm; "
                f"center separation={ctr_dist:.2f} mm → "
                f"length={slot_length} mm, width={diam_slot} mm."
            ),
            "face_indices":     [a["rec"]["face_index"], b["rec"]["face_index"]],
            "accepted": False,
            "ignored":  False,
        })

    # ── D. Through rectangular pocket / window candidates ──────────────────────
    # Detect rectangular channels from pairs of opposing internal PLANE walls.
    # An internal ±X pair is identified by: +X face at xa < -X face at xb.
    # Outer-profile walls have the opposite orientation (right +X > left -X)
    # and are excluded naturally.  An 88% span guard catches edge cases.
    # Through pockets have wall lz ~= part height and no detected floor face.
    # Does not modify Sections A, B, or C.

    _P_NZ_MAX     = 0.15    # |nz| must be below this — face must be nearly vertical
    _P_NA_MIN     = 0.92    # |nx| or |ny| must exceed this for axis-aligned wall
    _P_WALL_MIN_A = 400.0   # ignore wall face slivers smaller than this (mm²)
    _P_OUTER_FRAC = 0.88    # skip pairs whose gap > 88% of part span in that axis
    _P_MIN_DIM    = 4.0     # minimum pocket dimension in mm
    _P_MAX_ASPECT    = 8.0   # max length/width — above this prefer slot territory
    _FLAT_SLOT_MIN_AR = 3.5  # no-floor region at or above this AR → flat-ended slot
    _P_THRU_FRAC  = 0.90    # wall Z span >= 90% of part height → through pocket

    _pz_span = float(part_height)   # part_height already computed at top of function
    _pzr     = part_bbox.get("z_range", (0.0, 0.0))
    _p_z_min = float(_pzr[0])      # part Z minimum — used for floor-face Z guard

    # Bucket axis-aligned vertical PLANE faces by normal direction.
    _vxp, _vxn, _vyp, _vyn = [], [], [], []   # +X, -X, +Y, -Y normals
    for _r in face_records:
        if _r.get("geom_type") != "PLANE":
            continue
        _nz = _r.get("normal_z") or 0.0
        _nx = _r.get("normal_x") or 0.0
        _ny = _r.get("normal_y") or 0.0
        if abs(_nz) >= _P_NZ_MAX:
            continue   # not vertical enough
        if (_r.get("area_mm2") or 0.0) < _P_WALL_MIN_A:
            continue
        if (_r.get("bbox_length_z") or 0.0) <= 0:
            continue
        if _nx > _P_NA_MIN:
            _vxp.append(_r)
        elif _nx < -_P_NA_MIN:
            _vxn.append(_r)
        if _ny > _P_NA_MIN:
            _vyp.append(_r)
        elif _ny < -_P_NA_MIN:
            _vyn.append(_r)

    # Build internal ±X pairs: +X wall at xa must be LEFT of -X wall at xb (xa < xb).
    # Outer right-wall (+X at x_max) and outer left-wall (-X at x_min) have the
    # opposite relationship, so xa > xb and are excluded without any extra test.
    _xpairs = []
    for _a in _vxp:
        _xa = _a.get("center_x") or 0.0
        for _b in _vxn:
            _xb = _b.get("center_x") or 0.0
            if _xb <= _xa:
                continue                               # outer-profile orientation
            _gx = _xb - _xa
            if part_length > 0 and _gx > part_length * _P_OUTER_FRAC:
                continue                               # gap spans nearly full part
            _azlo = _a.get("bbox_zmin") or 0.0;  _azhi = _a.get("bbox_zmax") or 0.0
            _bzlo = _b.get("bbox_zmin") or 0.0;  _bzhi = _b.get("bbox_zmax") or 0.0
            _zlo = max(_azlo, _bzlo);  _zhi = min(_azhi, _bzhi)
            if _zhi <= _zlo:
                continue
            _xpairs.append({"a": _a, "b": _b, "gap": _gx,
                             "cx": (_xa + _xb) / 2.0, "zlo": _zlo, "zhi": _zhi})

    # Build internal ±Y pairs: +Y wall at ya must be BELOW -Y wall at yb (ya < yb).
    _ypairs = []
    for _a in _vyp:
        _ya = _a.get("center_y") or 0.0
        for _b in _vyn:
            _yb = _b.get("center_y") or 0.0
            if _yb <= _ya:
                continue
            _gy = _yb - _ya
            if part_width > 0 and _gy > part_width * _P_OUTER_FRAC:
                continue
            _azlo = _a.get("bbox_zmin") or 0.0;  _azhi = _a.get("bbox_zmax") or 0.0
            _bzlo = _b.get("bbox_zmin") or 0.0;  _bzhi = _b.get("bbox_zmax") or 0.0
            _zlo = max(_azlo, _bzlo);  _zhi = min(_azhi, _bzhi)
            if _zhi <= _zlo:
                continue
            _ypairs.append({"a": _a, "b": _b, "gap": _gy,
                             "cy": (_ya + _yb) / 2.0, "zlo": _zlo, "zhi": _zhi})

    _used_p_walls         = set()  # face indices consumed by a pocket candidate
    _pocket_floor_indices = set()  # blind pocket floor indices — excluded from step detection
    _p_n = [0]                     # pocket ID counter

    for _xp in _xpairs:
        for _yp in _ypairs:
            # Both pairs must share a Z overlap region.
            _zlo = max(_xp["zlo"], _yp["zlo"])
            _zhi = min(_xp["zhi"], _yp["zhi"])
            if _zhi <= _zlo:
                continue

            _px = round(_xp["gap"], 3)
            _py = round(_yp["gap"], 3)
            if _px < _P_MIN_DIM or _py < _P_MIN_DIM:
                continue
            if max(_px, _py) / min(_px, _py) >= _P_MAX_ASPECT:
                continue   # high aspect ratio — slot territory

            _wall_idxs = frozenset([
                _xp["a"]["face_index"], _xp["b"]["face_index"],
                _yp["a"]["face_index"], _yp["b"]["face_index"],
            ])
            if _wall_idxs & _used_p_walls:
                continue   # a wall already used in a prior pocket candidate

            _cx_pk = round(_xp["cx"], 3)
            _cy_pk = round(_yp["cy"], 3)

            # Skip if CYLINDER faces lie within the pocket XY/Z region — rounded
            # slot ends indicate the region is already handled by Section C.
            _has_cyl = False
            for _rc in face_records:
                if _rc.get("geom_type") != "CYLINDER":
                    continue
                _rx = _rc.get("center_x") or 0.0
                _ry = _rc.get("center_y") or 0.0
                _rz = _rc.get("center_z") or 0.0
                if (abs(_rx - _cx_pk) <= _px / 2 + 2
                        and abs(_ry - _cy_pk) <= _py / 2 + 2
                        and _zlo <= _rz <= _zhi):
                    _has_cyl = True
                    break
            if _has_cyl:
                continue

            _wall_lz = round(_zhi - _zlo, 3)
            _length  = round(max(_px, _py), 3)
            _width   = round(min(_px, _py), 3)
            _ar      = _length / _width if _width > 0 else 1.0

            # ── Floor face lookup ─────────────────────────────────────────────
            # A blind pocket has a +Z PLANE face at an intermediate Z level
            # whose area matches the pocket footprint and whose XY centre lies
            # within the pocket walls.  Through pockets have no such face.
            _x_lo = _xp["a"].get("center_x") or 0.0   # left wall X position
            _x_hi = _xp["b"].get("center_x") or 0.0   # right wall X position
            _y_lo = _yp["a"].get("center_y") or 0.0   # front wall Y position
            _y_hi = _yp["b"].get("center_y") or 0.0   # rear wall Y position
            _floor_area_target = _px * _py
            _tol_xy            = max(_px, _py) * 0.20  # 20% XY position tolerance

            _floor_face = None
            for _rf in face_records:
                if _rf.get("geom_type") != "PLANE":
                    continue
                if (_rf.get("normal_z") or 0.0) < 0.92:
                    continue   # must face upward
                _fz = _rf.get("center_z") or 0.0
                # Strictly between part bottom and top of pocket walls
                if not (_p_z_min + 1.0 < _fz < _zhi - 1.0):
                    continue
                _fx = _rf.get("center_x") or 0.0
                _fy = _rf.get("center_y") or 0.0
                if not (_x_lo - _tol_xy <= _fx <= _x_hi + _tol_xy):
                    continue   # XY centre outside pocket footprint
                if not (_y_lo - _tol_xy <= _fy <= _y_hi + _tol_xy):
                    continue
                _fa = _rf.get("area_mm2") or 0.0
                if _fa < 400.0:
                    continue   # sliver
                if not (0.70 * _floor_area_target <= _fa <= 1.30 * _floor_area_target):
                    continue   # area too different from expected pocket floor
                # Keep the face whose area is closest to the expected floor area
                if _floor_face is None or abs(_fa - _floor_area_target) < abs(
                    (_floor_face.get("area_mm2") or 0.0) - _floor_area_target
                ):
                    _floor_face = _rf

            # Branch: blind pocket / flat-ended through slot / through pocket
            if _floor_face is not None:
                _floor_z    = _floor_face.get("center_z") or _zlo
                _depth      = round(_zhi - _floor_z, 3)
                _confidence = "medium"
                _fname      = f"Blind pocket {_length:.1f}x{_width:.1f} mm"
                _floor_note = (
                    f"Floor face #{_floor_face['face_index']} at "
                    f"z={_floor_z:.2f} mm "
                    f"(area={(_floor_face.get('area_mm2') or 0.0):.1f} mm^2); "
                    f"depth from top = {_depth:.2f} mm."
                )
                _pocket_floor_indices.add(_floor_face["face_index"])
                _p_n[0] += 1
                _pcid         = f"P{_p_n[0]:03d}"
                _feature_type = "Pocket"
                _dsource      = "paired_internal_walls"
            elif _ar >= _FLAT_SLOT_MIN_AR:
                # No floor face and high aspect ratio → flat-ended through slot.
                # Emitted as Slot (same feature_type as Section C rounded slots).
                _depth      = _wall_lz
                _confidence = "medium"
                _fname      = f"Flat-ended slot {_length:.1f}x{_width:.1f} mm"
                _floor_note = (
                    f"No floor face detected; aspect ratio {_ar:.2f} >= "
                    f"{_FLAT_SLOT_MIN_AR} — classified as flat-ended through slot. "
                    f"No cylindrical end faces found."
                )
                _s_n[0] += 1
                _pcid         = f"S{_s_n[0]:03d}"
                _feature_type = "Slot"
                _dsource      = "flat_ended_slot_walls"
            else:
                _depth      = _wall_lz
                _confidence = "low"
                _fname      = f"Through pocket {_length:.1f}x{_width:.1f} mm"
                _floor_note = (
                    "No floor face detected -- treated as through pocket/window."
                )
                _p_n[0] += 1
                _pcid         = f"P{_p_n[0]:03d}"
                _feature_type = "Pocket"
                _dsource      = "paired_internal_walls"

            _pnote = (
                f"Paired internal PLANE walls — "
                f"X-pair: face #{_xp['a']['face_index']} (+X, "
                f"cx={(_xp['a'].get('center_x') or 0):.2f}) and "
                f"face #{_xp['b']['face_index']} (-X, "
                f"cx={(_xp['b'].get('center_x') or 0):.2f}), "
                f"gap={_px:.2f} mm; "
                f"Y-pair: face #{_yp['a']['face_index']} (+Y, "
                f"cy={(_yp['a'].get('center_y') or 0):.2f}) and "
                f"face #{_yp['b']['face_index']} (-Y, "
                f"cy={(_yp['b'].get('center_y') or 0):.2f}), "
                f"gap={_py:.2f} mm; "
                f"Z overlap {_zlo:.2f} to {_zhi:.2f} mm "
                f"(wall lz={_wall_lz:.2f} mm). "
                + _floor_note
            )

            _used_p_walls |= {
                _xp["a"]["face_index"], _xp["b"]["face_index"],
                _yp["a"]["face_index"], _yp["b"]["face_index"],
            }

            _face_idxs = [
                _xp["a"]["face_index"], _xp["b"]["face_index"],
                _yp["a"]["face_index"], _yp["b"]["face_index"],
            ]
            if _floor_face is not None:
                _face_idxs.append(_floor_face["face_index"])

            candidates.append({
                "candidate_id":     _pcid,
                "feature_name":     _fname,
                "feature_type":     _feature_type,
                "quantity":         1,
                "x_pos":            _cx_pk,
                "y_pos":            _cy_pk,
                "diameter":         None,
                "length":           _length,
                "width":            _width,
                "depth":            _depth,
                "tolerance_note":   "",
                "priority":         3,
                "confidence":       _confidence,
                "setup_label":      "Top",
                "detection_source": _dsource,
                "detection_note":   _pnote,
                "face_indices":     _face_idxs,
                "accepted": False,
                "ignored":  False,
            })

    # ── E. Step / shoulder candidates ────────────────────────────────────────
    # Detect stepped faces: two parallel PLANE faces sharing the same normal
    # sign at different positions along the same axis.  The inner face is the
    # step floor; a shoulder wall must connect it to the outer (boundary) face.
    # Z-axis is processed first (top-milled priority), then Y, then X.
    # Any face already consumed by Section D (pocket walls/floors) is excluded.

    _ST_NORMAL_MIN = 0.92   # |normal component| to be axis-aligned
    _ST_MIN_AREA   = 400.0  # minimum step floor area mm²
    _ST_MIN_DEPTH  = 1.0    # minimum step depth mm

    _st_n    = [0]
    _st_used = set()   # face indices used in emitted Step candidates

    _xr_e = part_bbox.get("x_range", (0.0, 0.0))
    _yr_e = part_bbox.get("y_range", (0.0, 0.0))
    _zr_e = part_bbox.get("z_range", (0.0, 0.0))

    _step_excl = set(_used_p_walls) | _pocket_floor_indices

    # (normal_key, pos_key, bbox_min_key, bbox_max_key,
    #  part_min, part_max, dim1_key, dim2_key, perp_normal_keys)
    _step_axes = [
        ("normal_z", "center_z", "bbox_zmin", "bbox_zmax",
         _zr_e[0], _zr_e[1], "bbox_length_x", "bbox_length_y",
         ("normal_x", "normal_y")),
        ("normal_y", "center_y", "bbox_ymin", "bbox_ymax",
         _yr_e[0], _yr_e[1], "bbox_length_x", "bbox_length_z",
         ("normal_x", "normal_z")),
        ("normal_x", "center_x", "bbox_xmin", "bbox_xmax",
         _xr_e[0], _xr_e[1], "bbox_length_y", "bbox_length_z",
         ("normal_y", "normal_z")),
    ]

    for (_nkey, _pkey, _bmin_k, _bmax_k,
         _ax_min, _ax_max, _d1key, _d2key, _perp_keys) in _step_axes:
        _ax_span = _ax_max - _ax_min
        if _ax_span < 2.0:
            continue

        _pos_grp, _neg_grp = [], []
        for _r in face_records:
            if _r.get("geom_type") != "PLANE":
                continue
            if (_r["face_index"] in _step_excl
                    or _r["face_index"] in _st_used):
                continue
            _nv   = _r.get(_nkey) or 0.0
            _area = _r.get("area_mm2") or 0.0
            if _area < _ST_MIN_AREA:
                continue
            if _nv > _ST_NORMAL_MIN:
                _pos_grp.append(_r)
            elif _nv < -_ST_NORMAL_MIN:
                _neg_grp.append(_r)

        for _sign, _grp in ((+1, _pos_grp), (-1, _neg_grp)):
            if len(_grp) < 2:
                continue

            _grp.sort(key=lambda r: r.get(_pkey) or 0.0)

            if _sign == +1:
                _outer_f = _grp[-1]
                _inners  = _grp[:-1]
            else:
                _outer_f = _grp[0]
                _inners  = _grp[1:]

            _outer_pos = _outer_f.get(_pkey) or 0.0
            _boundary  = _ax_max if _sign == +1 else _ax_min
            if abs(_outer_pos - _boundary) > _ax_span * 0.10:
                continue

            for _sf in _inners:
                if _sf["face_index"] in _st_used:
                    continue

                _sf_pos = _sf.get(_pkey) or 0.0
                _sdepth = abs(_outer_pos - _sf_pos)
                if _sdepth < _ST_MIN_DEPTH:
                    continue
                # Reject "steps" that span more than 60% of the part in that axis
                # (indicates outer-wall vs inner-wall pairing, not a real step).
                if _ax_span > 0 and _sdepth > _ax_span * 0.60:
                    continue

                # Reject symmetric geometry: if a mirror face exists on the
                # opposite side at the same offset from its boundary, the
                # feature is a slot or pocket channel (symmetric), not a step.
                _gap_from_outer = abs(_outer_pos - _sf_pos)
                _mir_boundary   = _ax_min if _sign == +1 else _ax_max
                _mir_pos        = (_mir_boundary + _gap_from_outer
                                   if _sign == +1
                                   else _mir_boundary - _gap_from_outer)
                _mir_tol        = _gap_from_outer * 0.20 + 1.0
                _has_mirror = any(
                    _mr.get("geom_type") == "PLANE"
                    and (_mr.get(_nkey) or 0.0) * _sign < -(_ST_NORMAL_MIN - 0.1)
                    and abs((_mr.get(_pkey) or 0.0) - _mir_pos) <= _mir_tol
                    for _mr in face_records
                )
                if _has_mirror:
                    continue

                _d1     = _sf.get(_d1key) or 0.0
                _d2     = _sf.get(_d2key) or 0.0
                _sf_len = round(max(_d1, _d2), 3)
                _sf_wid = round(min(_d1, _d2), 3)
                _sf_cx  = _sf.get("center_x") or 0.0
                _sf_cy  = _sf.get("center_y") or 0.0
                _sf_bxn = _sf.get("bbox_xmin") or _sf_cx
                _sf_bxx = _sf.get("bbox_xmax") or _sf_cx
                _sf_byn = _sf.get("bbox_ymin") or _sf_cy
                _sf_byx = _sf.get("bbox_ymax") or _sf_cy

                _pos_lo = min(_sf_pos, _outer_pos)
                _pos_hi = max(_sf_pos, _outer_pos)
                _sw_tol = _sdepth * 0.20 + 1.0
                _fp_tol = max(_d1, _d2, _sdepth) * 0.25 + 2.0

                # For Z-direction steps: skip if CYLINDER faces exist in the
                # step column (slot end-caps or bore walls → not a step).
                # Use bbox Z-range overlap, not just center, so that cylinders
                # spanning the full slot depth are correctly detected.
                if _nkey == "normal_z":
                    _has_cyl = False
                    for _rc in face_records:
                        if _rc.get("geom_type") != "CYLINDER":
                            continue
                        _rc_zmin = _rc.get("bbox_zmin") or 0.0
                        _rc_zmax = _rc.get("bbox_zmax") or 0.0
                        # Cylinder Z extent must overlap the step Z region
                        if not (_rc_zmin < _pos_hi + 2.0 and _rc_zmax > _pos_lo - 2.0):
                            continue
                        _rc_cx = _rc.get("center_x") or 0.0
                        _rc_cy = _rc.get("center_y") or 0.0
                        if (_sf_bxn - _fp_tol <= _rc_cx <= _sf_bxx + _fp_tol
                                and _sf_byn - _fp_tol <= _rc_cy <= _sf_byx + _fp_tol):
                            _has_cyl = True
                            break
                    if _has_cyl:
                        continue

                # Find shoulder wall: perpendicular to step axis, spanning
                # [step_floor_pos, outer_pos] in the step-axis direction.
                _sw = None
                for _pw in face_records:
                    if _pw.get("geom_type") != "PLANE":
                        continue
                    if (_pw["face_index"] in _step_excl
                            or _pw["face_index"] in _st_used):
                        continue
                    if abs(_pw.get(_nkey) or 0.0) > 0.15:
                        continue
                    if not any(abs(_pw.get(_pk) or 0.0) > _ST_NORMAL_MIN
                               for _pk in _perp_keys):
                        continue
                    _sw_bmin = _pw.get(_bmin_k) or 0.0
                    _sw_bmax = _pw.get(_bmax_k) or 0.0
                    if not (_pos_lo - _sw_tol <= _sw_bmin <= _pos_lo + _sw_tol):
                        continue
                    if not (_pos_hi - _sw_tol <= _sw_bmax <= _pos_hi + _sw_tol):
                        continue
                    _pw_cx = _pw.get("center_x") or 0.0
                    _pw_cy = _pw.get("center_y") or 0.0
                    if _nkey == "normal_y":
                        if not (_sf_bxn - _fp_tol <= _pw_cx <= _sf_bxx + _fp_tol):
                            continue
                    elif _nkey == "normal_x":
                        if not (_sf_byn - _fp_tol <= _pw_cy <= _sf_byx + _fp_tol):
                            continue
                    elif _nkey == "normal_z":
                        if not (_sf_bxn - _fp_tol <= _pw_cx <= _sf_bxx + _fp_tol):
                            continue
                        if not (_sf_byn - _fp_tol <= _pw_cy <= _sf_byx + _fp_tol):
                            continue
                    _sw = _pw
                    break

                if _sw is None:
                    continue

                _st_n[0] += 1
                _stcid    = f"ST{_st_n[0]:03d}"
                _ax_lbl   = _nkey.replace("normal_", "").upper()
                _sdepth_r = round(_sdepth, 3)
                _st_setup_label = _setup_label_from_normal(
                    _sf.get("normal_x") or 0.0,
                    _sf.get("normal_y") or 0.0,
                    _sf.get("normal_z") or 0.0,
                )

                _stnote = (
                    f"Step floor: face #{_sf['face_index']} "
                    f"(normal_{_ax_lbl}={(_sf.get(_nkey) or 0):+.3f}, "
                    f"{_ax_lbl}={_sf_pos:.2f} mm, "
                    f"area={(_sf.get('area_mm2') or 0):.1f} mm²); "
                    f"outer face: #{_outer_f['face_index']} at "
                    f"{_ax_lbl}={_outer_pos:.2f} mm; "
                    f"step depth = {_sdepth_r:.2f} mm; "
                    f"shoulder wall: face #{_sw['face_index']} "
                    f"(area={(_sw.get('area_mm2') or 0):.1f} mm²)."
                )

                _st_used |= {
                    _sf["face_index"],
                    _sw["face_index"],
                    _outer_f["face_index"],
                }

                candidates.append({
                    "candidate_id":     _stcid,
                    "feature_name":     (
                        f"Step shoulder {_sf_len:.1f}x{_sf_wid:.1f} "
                        f"depth {_sdepth_r:.1f} mm"
                    ),
                    "feature_type":     "Step",
                    "quantity":         1,
                    "x_pos":            _sf_cx,
                    "y_pos":            _sf_cy,
                    "diameter":         None,
                    "length":           _sf_len,
                    "width":            _sf_wid,
                    "depth":            _sdepth_r,
                    "tolerance_note":   "",
                    "priority":         3,
                    "confidence":       "medium",
                    "setup_label":      _st_setup_label,
                    "detection_source": "intermediate_floor_and_shoulder_wall",
                    "detection_note":   _stnote,
                    "face_indices":     [_sf["face_index"], _sw["face_index"], _outer_f["face_index"]],
                    "accepted": False,
                    "ignored":  False,
                })

    # ── F. Chamfer candidates ─────────────────────────────────────────────────
    # Detect simple top outer-edge chamfers: PLANE faces with an angled-upward
    # normal (nz between 0.40 and 0.92) that sit near the top of the part.
    # All qualifying faces are grouped into a single CH001 candidate.

    _CH_NZ_MIN    = 0.40    # nz lower bound: ~24° from horizontal
    _CH_NZ_MAX    = 0.92    # nz upper bound: just below Section A flat-face threshold
    _CH_HORIZ_MIN = 0.40    # |nx| or |ny| must be significant
    _CH_MAX_AREA  = 2000.0  # mm² — upper bound for a single chamfer face
    _CH_MIN_AREA  = 50.0    # mm² — ignore slivers
    _CH_Z_FRAC    = 0.20    # z_center within this fraction of part height from top

    _ch_p_z_max = part_bbox.get("z_range", (0.0, 0.0))[1]
    _ch_z_lo    = _ch_p_z_max - max(8.0, part_height * _CH_Z_FRAC)

    _ch_faces = []
    for _r in face_records:
        if _r.get("geom_type") != "PLANE":
            continue
        _ch_nz  = _r.get("normal_z") or 0.0
        _ch_hnx = abs(_r.get("normal_x") or 0.0)
        _ch_hny = abs(_r.get("normal_y") or 0.0)
        _ch_a   = _r.get("area_mm2") or 0.0
        _ch_cz  = _r.get("center_z") or 0.0

        if not (_CH_NZ_MIN <= _ch_nz <= _CH_NZ_MAX):
            continue   # not angled upward in the chamfer range
        if max(_ch_hnx, _ch_hny) < _CH_HORIZ_MIN:
            continue   # no significant horizontal component
        if not (_CH_MIN_AREA <= _ch_a <= _CH_MAX_AREA):
            continue   # too small (sliver) or too large (design face / wall)
        if _ch_cz < _ch_z_lo:
            continue   # not near the top of the part

        _ch_faces.append(_r)

    if _ch_faces:
        # Estimate chamfer size from the smallest span on each face
        _ch_sizes = []
        for _cf in _ch_faces:
            _cf_dims = [
                v for v in [
                    _cf.get("bbox_length_x") or 0.0,
                    _cf.get("bbox_length_y") or 0.0,
                    _cf.get("bbox_length_z") or 0.0,
                ] if v > 0.1
            ]
            if _cf_dims:
                _ch_sizes.append(min(_cf_dims))
        _ch_size = round(sum(_ch_sizes) / len(_ch_sizes), 1) if _ch_sizes else 0.0
        _ch_n    = len(_ch_faces)
        _ch_ids  = ", ".join(f"#{_cf['face_index']}" for _cf in _ch_faces)
        _ch_areas = [_cf.get("area_mm2") or 0.0 for _cf in _ch_faces]
        _ch_nzs   = [_cf.get("normal_z") or 0.0 for _cf in _ch_faces]

        _ch_note = (
            f"{_ch_n} angled PLANE face(s) near top of part "
            f"classified as top outer-edge chamfer. "
            f"Face indices: {_ch_ids}. "
            f"normal_z range: {min(_ch_nzs):.3f}–{max(_ch_nzs):.3f}. "
            f"Area range: {min(_ch_areas):.1f}–{max(_ch_areas):.1f} mm². "
            f"z_center ≥ {_ch_z_lo:.1f} mm (top={_ch_p_z_max:.1f} mm). "
            f"Estimated chamfer size ≈ {_ch_size:.1f} mm (bbox small span average)."
        )

        candidates.append({
            "candidate_id":     "CH001",
            "feature_name":     f"Top edge chamfer ~{_ch_size:.1f}×{_ch_size:.1f} mm "
                                f"({_ch_n} face{'s' if _ch_n != 1 else ''})",
            "feature_type":     "Chamfer",
            "quantity":         _ch_n,
            "x_pos":            0.0,
            "y_pos":            0.0,
            "diameter":         None,
            "length":           None,
            "width":            _ch_size,
            "depth":            _ch_size,
            "tolerance_note":   "",
            "priority":         4,
            "confidence":       "medium" if _ch_n >= 3 else "low",
            "setup_label":      "Top",
            "detection_source": "angled_top_plane_faces",
            "detection_note":   _ch_note,
            "face_indices":     [_cf["face_index"] for _cf in _ch_faces],
            "accepted": False,
            "ignored":  False,
        })

    records_by_index = {
        record.get("face_index"): record
        for record in face_records
        if record.get("face_index") is not None
    }
    for candidate in candidates:
        source_records = [
            records_by_index[index]
            for index in candidate.get("face_indices", [])
            if index in records_by_index
        ]
        if not source_records:
            continue
        candidate["cad_position"] = {
            "x": round(float(
                candidate.get("x_pos")
                if candidate.get("x_pos") is not None
                else source_records[0].get("center_x") or 0.0
            ), 6),
            "y": round(float(
                candidate.get("y_pos")
                if candidate.get("y_pos") is not None
                else source_records[0].get("center_y") or 0.0
            ), 6),
            "z": round(
                sum(float(record.get("center_z") or 0.0) for record in source_records)
                / len(source_records),
                6,
            ),
        }

    return candidates


_FRAME_FEATURE_WEIGHTS = {
    "Hole": 5,
    "Large hole / boring": 5,
    "Slot": 8,
    "Pocket": 10,
    "Step": 7,
    "Chamfer": 4,
}


def _record_in_frame(record, work_axes, signs=(1, 1, 1)):
    """Return a face record expressed in an axis-permuted detection frame."""
    framed = dict(record)
    for target_axis, source_axis, sign in zip(("x", "y", "z"), work_axes, signs):
        for prefix in ("center", "normal", "cylinder_axis"):
            value = record.get(f"{prefix}_{source_axis}")
            framed[f"{prefix}_{target_axis}"] = (
                None if value is None else sign * value
            )
        source_min = record.get(f"bbox_{source_axis}min")
        source_max = record.get(f"bbox_{source_axis}max")
        if source_min is None or source_max is None:
            framed[f"bbox_{target_axis}min"] = None
            framed[f"bbox_{target_axis}max"] = None
        elif sign >= 0:
            framed[f"bbox_{target_axis}min"] = source_min
            framed[f"bbox_{target_axis}max"] = source_max
        else:
            framed[f"bbox_{target_axis}min"] = -source_max
            framed[f"bbox_{target_axis}max"] = -source_min
        framed[f"bbox_length_{target_axis}"] = record.get(
            f"bbox_length_{source_axis}"
        )
    return framed


def _bbox_in_frame(part_bbox, work_axes, signs=(1, 1, 1)):
    spans = {
        "x": float(part_bbox.get("length_mm") or 0.0),
        "y": float(part_bbox.get("width_mm") or 0.0),
        "z": float(part_bbox.get("height_mm") or 0.0),
    }
    framed = {}
    for target_axis, source_axis, sign in zip(("x", "y", "z"), work_axes, signs):
        framed[{"x": "length_mm", "y": "width_mm", "z": "height_mm"}[target_axis]] = (
            spans[source_axis]
        )
        source_range = part_bbox.get(
            f"{source_axis}_range",
            (0.0, spans[source_axis]),
        )
        framed[f"{target_axis}_range"] = (
            source_range
            if sign >= 0
            else (-source_range[1], -source_range[0])
        )
    return framed


def _frame_score(candidates):
    """Prefer frames that explain more exact machinable geometry."""
    score = 0
    for candidate in candidates:
        feature_type = candidate.get("feature_type")
        weight = _FRAME_FEATURE_WEIGHTS.get(feature_type, 0)
        confidence = str(candidate.get("confidence") or "").lower()
        if confidence == "high":
            weight += 2
        elif confidence == "low":
            weight = max(weight - 2, 0)
        score += weight * max(int(candidate.get("quantity") or 1), 1)
    return score


def _frame_top_score(candidates):
    return sum(
        _FRAME_FEATURE_WEIGHTS.get(candidate.get("feature_type"), 0)
        * max(int(candidate.get("quantity") or 1), 1)
        for candidate in candidates
        if candidate.get("setup_label") == "Top"
    )


def _cad_setup_from_frame_setup(setup_label, work_axes, signs):
    frame_vectors = {
        "Right": (1.0, 0.0, 0.0),
        "Left": (-1.0, 0.0, 0.0),
        "Back": (0.0, 1.0, 0.0),
        "Front": (0.0, -1.0, 0.0),
        "Top": (0.0, 0.0, 1.0),
        "Bottom": (0.0, 0.0, -1.0),
    }
    vector = frame_vectors.get(setup_label)
    if vector is None:
        return setup_label
    cad = {"x": 0.0, "y": 0.0, "z": 0.0}
    for component, source_axis, sign in zip(vector, work_axes, signs):
        cad[source_axis] = component * sign
    return _setup_label_from_normal(cad["x"], cad["y"], cad["z"])


def _restore_candidate_cad_frame(
    candidate,
    raw_records_by_index,
    work_axes,
    signs,
):
    """Keep frame-derived dimensions while restoring raw CAD positions/setups."""
    restored = dict(candidate)
    source_records = [
        raw_records_by_index[index]
        for index in restored.get("face_indices", [])
        if index in raw_records_by_index
    ]
    if source_records:
        frame_position = (
            float(restored.get("x_pos") or 0.0),
            float(restored.get("y_pos") or 0.0),
            sum(
                signs[2] * float(
                    record.get(f"center_{work_axes[2]}") or 0.0
                )
                for record in source_records
            ) / len(source_records),
        )
        cad_position = {"x": 0.0, "y": 0.0, "z": 0.0}
        for value, source_axis, sign in zip(
            frame_position,
            work_axes,
            signs,
        ):
            cad_position[source_axis] = sign * value
        cad_position = {
            axis: round(cad_position[axis], 6)
            for axis in ("x", "y", "z")
        }
        restored["cad_position"] = cad_position
        restored["x_pos"] = cad_position["x"]
        restored["y_pos"] = cad_position["y"]

    frame_setup = restored.get("setup_label")
    restored["detection_frame_setup_label"] = frame_setup
    restored["setup_label"] = _cad_setup_from_frame_setup(
        frame_setup,
        work_axes,
        signs,
    )
    restored["detection_frame"] = {
        "work_axes_from_cad": list(work_axes),
        "axis_signs": list(signs),
        "selection": "highest weighted exact-feature score",
    }
    note = restored.get("detection_note") or ""
    if work_axes != ("x", "y", "z") or signs != (1, 1, 1):
        restored["detection_note"] = (
            f"{note} Detected in axis frame X/Y/Z <- "
            f"{signs[0]:+d}{work_axes[0].upper()}/"
            f"{signs[1]:+d}{work_axes[1].upper()}/"
            f"{signs[2]:+d}{work_axes[2].upper()}."
        ).strip()
    return restored


def _classify_face_records(face_records: list, part_bbox: dict) -> list:
    """Classify in the strongest axis-aligned machining frame.

    STEP exporters do not consistently use CAD Z as the VMC tool axis. Running
    the same deterministic classifier in every axis permutation prevents holes,
    slots, and pockets from changing type merely because the model was exported
    Y-up or X-up.
    """
    raw_records_by_index = {
        record.get("face_index"): record
        for record in face_records
        if record.get("face_index") is not None
    }
    frame_results = []
    for work_axes in permutations(("x", "y", "z")):
        for signs in product((-1, 1), repeat=3):
            framed_records = [
                _record_in_frame(record, work_axes, signs)
                for record in face_records
            ]
            framed_bbox = _bbox_in_frame(part_bbox, work_axes, signs)
            candidates = _classify_face_records_in_frame(
                framed_records,
                framed_bbox,
            )
            frame_results.append((
                _frame_score(candidates),
                work_axes == ("x", "y", "z") and signs == (1, 1, 1),
                work_axes,
                signs,
                candidates,
            ))

    best_by_axes = {}
    for result in frame_results:
        axes = result[2]
        current = best_by_axes.get(axes)
        result_key = (
            result[0],
            _frame_top_score(result[4]),
            result[1],
        )
        current_key = (
            current[0],
            _frame_top_score(current[4]),
            current[1],
        ) if current else None
        if current is None or result_key > current_key:
            best_by_axes[axes] = result

    identity_result = next(
        result for result in frame_results
        if result[2] == ("x", "y", "z") and result[3] == (1, 1, 1)
    )
    best_result = max(
        best_by_axes.values(),
        key=lambda result: (
            result[0],
            _frame_top_score(result[4]),
            result[1],
        ),
    )
    # Keep the source frame unless another frame is materially better. This
    # prevents symmetric slot walls from winning merely by being misread as a
    # slightly larger number of circular bores in a sideways frame.
    identity_score = identity_result[0]
    best_score = best_result[0]
    if (
        not best_result[1]
        and best_score > identity_score
        and (identity_score == 0 or best_score >= identity_score * 1.20)
    ):
        selected_result = best_result
    else:
        selected_result = identity_result
    def _restore_set(result):
        _, _, axes, signs, candidates = result
        restored_candidates = [
            _restore_candidate_cad_frame(
                candidate,
                raw_records_by_index,
                axes,
                signs,
            )
            for candidate in candidates
        ]
        for restored_candidate in restored_candidates:
            alternatives = restored_candidate.get(
                "orientation_face_candidates",
                [],
            )
            restored_candidate["orientation_face_candidates"] = [
                _restore_candidate_cad_frame(
                    alternative,
                    raw_records_by_index,
                    axes,
                    signs,
                )
                for alternative in alternatives
            ]
        return restored_candidates

    restored = _restore_set(selected_result)
    if restored:
        restored[0]["detection_candidate_sets"] = [
            {
                "work_axes_from_cad": list(result[2]),
                "axis_signs": list(result[3]),
                "score": result[0],
                "top_score": _frame_top_score(result[4]),
                "candidates": _restore_set(result),
            }
            for result in best_by_axes.values()
        ]
    return restored


def detect_feature_candidates_from_cadquery_file(file_path: str) -> dict:
    """
    Load a STEP file with CadQuery and return preliminary machinable feature
    candidates classified from per-face geometry records.

    Never raises — all exceptions are caught and returned as success=False
    with a populated warnings list.  Does NOT wire into parse_step_auto.

    Returns:
        {
            "success":            bool,
            "candidate_features": list[dict],
            "candidate_count":    int,
            "warnings":           list[str]
        }
    """
    warnings_out = []

    try:
        _cq = _load_cadquery()
        if _cq is None:
            return {
                "success": False,
                "candidate_features": [],
                "candidate_count": 0,
                "warnings": [
                    "CadQuery is not installed — cannot detect feature candidates. "
                    "Install via: conda install -c conda-forge cadquery"
                ],
            }

        if not os.path.isfile(file_path):
            return {
                "success": False,
                "candidate_features": [],
                "candidate_count": 0,
                "warnings": [f"File not found: {file_path}"],
            }

        with open(file_path, "rb") as source_file:
            source_file_hash = hashlib.sha256(source_file.read()).hexdigest()
        cq_result = _cq.importers.importStep(file_path)

        bb = cq_result.val().BoundingBox()
        part_bbox = {
            "length_mm": round(bb.xmax - bb.xmin, 3),
            "width_mm":  round(bb.ymax - bb.ymin, 3),
            "height_mm": round(bb.zmax - bb.zmin, 3),
            "x_range":   (bb.xmin, bb.xmax),
            "y_range":   (bb.ymin, bb.ymax),
            "z_range":   (bb.zmin, bb.zmax),
        }

        face_records = _extract_face_records(cq_result)

        if not face_records:
            warnings_out.append(
                "No face records extracted — "
                "file may be a surface shell or CadQuery found no topology."
            )

        candidates = _classify_face_records(face_records, part_bbox)

        if not candidates:
            warnings_out.append(
                "No feature candidates detected. "
                "The file may lack planar ±Z faces or cylindrical features."
            )

        # ── Per-face tessellation for colored face overlays ────────────────────
        # Tessellate only the CAD faces referenced by each candidate so that
        # build_step_mesh3d() can render exact colored surfaces instead of
        # approximate marker shapes.  Failures per-face are silenced; the
        # candidate falls back to its marker representation.
        _FACE_COLOR_TYPES = {
            "Face milling", "Hole", "Large hole / boring", "Pocket", "Chamfer",
        }
        try:
            _faces_list = cq_result.faces().vals()
            _n_faces    = len(_faces_list)
            _mesh_targets = list(candidates)
            for _candidate in candidates:
                _mesh_targets.extend(_candidate.get("orientation_face_candidates", []))
            _catalog_targets = list(_mesh_targets)
            if candidates:
                for _candidate_set in candidates[0].get("detection_candidate_sets", []):
                    for _candidate in _candidate_set.get("candidates", []):
                        _catalog_targets.append(_candidate)
                        _catalog_targets.extend(
                            _candidate.get("orientation_face_candidates", [])
                        )
            _face_mesh_catalog = {}
            for _fi in {
                face_index
                for _candidate in _catalog_targets
                if _candidate.get("feature_type") in _FACE_COLOR_TYPES
                for face_index in _candidate.get("face_indices", [])
                if 0 <= face_index < _n_faces
            }:
                try:
                    _fverts, _ftris = _faces_list[_fi].tessellate(0.15)
                    if _fverts:
                        _face_mesh_catalog[_fi] = {
                            "vertices": [[_v.x, _v.y, _v.z] for _v in _fverts],
                            "triangles": [[_t[0], _t[1], _t[2]] for _t in _ftris],
                            "face_index": _fi,
                        }
                except Exception:
                    pass
            for _cand in _mesh_targets:
                _ftype = _cand.get("feature_type", "")
                _fidxs = _cand.get("face_indices", [])
                if _ftype not in _FACE_COLOR_TYPES or not _fidxs:
                    _cand["face_mesh_data"] = []
                    continue
                _cand["face_mesh_data"] = [
                    _face_mesh_catalog[_fi]
                    for _fi in _fidxs
                    if _fi in _face_mesh_catalog
                ]
            if candidates:
                candidates[0]["face_mesh_catalog"] = _face_mesh_catalog
        except Exception as _tess_exc:
            warnings_out.append(
                f"Per-face tessellation skipped: {type(_tess_exc).__name__}: {_tess_exc}"
            )
            for _cand in candidates:
                if "face_mesh_data" not in _cand:
                    _cand["face_mesh_data"] = []

        assign_stable_candidate_ids(candidates, source_file_hash)
        return {
            "success":            True,
            "candidate_features": candidates,
            "candidate_count":    len(candidates),
            "source_file_hash":   source_file_hash,
            "warnings":           warnings_out,
        }

    except Exception as exc:
        return {
            "success":            False,
            "candidate_features": [],
            "candidate_count":    0,
            "warnings":           [f"Detection failed — {type(exc).__name__}: {exc}"],
        }
