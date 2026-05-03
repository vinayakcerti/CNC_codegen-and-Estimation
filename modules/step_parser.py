import re


# ---------------------------------------------------------------------------
# Unit detection helpers
# ---------------------------------------------------------------------------

# Conversion factors → millimetres
_UNIT_FACTORS = {
    "mm": 1.0,
    "millimeter": 1.0,
    "millimetre": 1.0,
    "cm": 10.0,
    "centimeter": 10.0,
    "centimetre": 10.0,
    "m": 1000.0,
    "meter": 1000.0,
    "metre": 1000.0,
    "in": 25.4,
    "inch": 25.4,
    "inches": 25.4,
    "ft": 304.8,
    "foot": 304.8,
    "feet": 304.8,
}

_UNIT_LABELS = {
    1.0:   "mm  (millimetres — no conversion needed)",
    10.0:  "cm  (centimetres → converted to mm × 10)",
    1000.0:"m   (metres → converted to mm × 1000)",
    25.4:  "in  (inches → converted to mm × 25.4)",
    304.8: "ft  (feet → converted to mm × 304.8)",
}


def _detect_unit_factor(text: str):
    """
    Scan the STEP file for length-unit declarations and return
    (factor_to_mm, detected_unit_label, detection_method).

    Strategies tried in order of reliability:
      1. CONVERSION_BASED_UNIT with a quoted name  e.g. 'INCH', 'MM'
      2. SI_UNIT prefix  .MILLI. / .CENTI. / (none = base metre)
      3. FILE_DESCRIPTION / SCHEMA keyword hints
      4. Heuristic: if the largest coordinate span is huge (> 10 000) → likely mm already;
         if very small (< 1) → likely metres.
    Returns (factor, label, method_string).
    """

    upper = text.upper()

    # --- Strategy 1: CONVERSION_BASED_UNIT('NAME', ...) --------------------
    cbu_pattern = re.compile(
        r"CONVERSION_BASED_UNIT\s*\(\s*'([^']+)'", re.IGNORECASE
    )
    for m in cbu_pattern.finditer(text):
        name = m.group(1).strip().lower()
        for key, factor in _UNIT_FACTORS.items():
            if key == name or name.startswith(key):
                label = _UNIT_LABELS.get(factor, f"{name} → {factor}× mm")
                return factor, label, "CONVERSION_BASED_UNIT declaration"

    # --- Strategy 2: SI_UNIT prefix ----------------------------------------
    # Patterns like: SI_UNIT($,.MILLI.,.METRE.)  or  SI_UNIT(.MILLI.,.METRE.)
    si_pattern = re.compile(
        r"SI_UNIT\s*\([^)]*\.(MILLI|CENTI|DECI|KILO|MEGA)?\.\s*,?\s*\.METRE\.",
        re.IGNORECASE,
    )
    si_match = si_pattern.search(text)
    if si_match:
        prefix = (si_match.group(1) or "").upper()
        mapping = {
            "MILLI": (1.0,    "mm (SI_UNIT .MILLI.METRE.)"),
            "CENTI": (10.0,   "cm (SI_UNIT .CENTI.METRE.) → converted × 10"),
            "DECI":  (100.0,  "dm (SI_UNIT .DECI.METRE.) → converted × 100"),
            "":      (1000.0, "m  (SI_UNIT .METRE., no prefix) → converted × 1000"),
            "KILO":  (1e6,    "km → converted × 1 000 000"),
        }
        if prefix in mapping:
            factor, label = mapping[prefix]
            return factor, label, "SI_UNIT entity in file"

    # --- Strategy 3: keyword scan in header ---------------------------------
    # AP242 sometimes lists 'INCH' or 'MM' in FILE_DESCRIPTION
    for key in ("INCH", "'IN'", "INCHES"):
        if key in upper:
            return 25.4, _UNIT_LABELS[25.4], "keyword hint in file header"

    for key in ("MILLIMETER", "MILLIMETRE", "'MM'"):
        if key in upper:
            return 1.0, _UNIT_LABELS[1.0], "keyword hint in file header"

    for key in ("METER", "METRE"):
        if key in upper and "MILLI" not in upper:
            return 1000.0, _UNIT_LABELS[1000.0], "keyword hint in file header"

    # --- Strategy 4: heuristic on coordinate magnitudes --------------------
    # (applied after parsing; caller passes max_span)
    return None, None, "heuristic"  # signal caller to apply heuristic


def _heuristic_factor(max_span: float):
    """
    Guess unit from the size of the largest dimension.
    - > 5 000  → probably already mm (large part)
    - 50–5 000 → probably mm (normal machined parts)
    - 1–50     → could be cm (10×) or large inches
    - < 1      → probably metres (1000×)
    """
    if max_span < 0.5:
        return 1000.0, _UNIT_LABELS[1000.0], "heuristic (coordinates < 0.5 → assumed metres)"
    if max_span < 3.0:
        return 25.4, _UNIT_LABELS[25.4], "heuristic (coordinates < 3 → assumed inches)"
    # Default: assume mm — most CAD exports use mm
    return 1.0, _UNIT_LABELS[1.0], "assumed mm (no unit declaration found)"


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_step_bounding_box(file_bytes: bytes) -> dict:
    """
    Parse a STEP file (AP203/AP214/AP242) and return bounding-box dimensions
    converted to millimetres, along with unit-detection metadata.

    Returned dict keys:
      success, length_mm, width_mm, height_mm,
      stock_volume_cm3, part_volume_cm3, point_count,
      x_range, y_range, z_range,
      detected_unit_label, conversion_factor, detection_method,
      converted (bool), message
    """
    # ── decode ──────────────────────────────────────────────────────────────
    try:
        text = file_bytes.decode("utf-8", errors="replace")
    except Exception as exc:
        return {"success": False, "message": f"Could not decode file: {exc}"}

    # ── detect units before parsing coordinates ──────────────────────────────
    factor, unit_label, method = _detect_unit_factor(text)

    # ── extract CARTESIAN_POINT coordinates ──────────────────────────────────
    point_pattern = re.compile(
        r"CARTESIAN_POINT\s*\(\s*'[^']*'\s*,\s*\(\s*"
        r"([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)"
        r"\s*,\s*"
        r"([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)"
        r"\s*,\s*"
        r"([+-]?\d+(?:\.\d+)?(?:[Ee][+-]?\d+)?)"
        r"\s*\)\s*\)",
        re.IGNORECASE,
    )

    matches = point_pattern.findall(text)

    if not matches:
        return {
            "success": False,
            "message": (
                "No CARTESIAN_POINT data found. "
                "The file may use a non-standard format or contain only 2D data. "
                "Please enter dimensions manually."
            ),
        }

    xs, ys, zs = [], [], []
    for x_str, y_str, z_str in matches:
        try:
            xs.append(float(x_str))
            ys.append(float(y_str))
            zs.append(float(z_str))
        except ValueError:
            continue

    if not xs:
        return {"success": False, "message": "Could not parse coordinate values."}

    # ── apply heuristic if unit not detected ─────────────────────────────────
    raw_max_span = max(
        max(xs) - min(xs),
        max(ys) - min(ys),
        max(zs) - min(zs),
    )

    if factor is None:
        factor, unit_label, method = _heuristic_factor(raw_max_span)

    converted = factor != 1.0

    # ── compute bounding box in native units ──────────────────────────────────
    x_min_raw, x_max_raw = min(xs), max(xs)
    y_min_raw, y_max_raw = min(ys), max(ys)
    z_min_raw, z_max_raw = min(zs), max(zs)

    # ── convert to mm ─────────────────────────────────────────────────────────
    x_min = round(x_min_raw * factor, 3)
    x_max = round(x_max_raw * factor, 3)
    y_min = round(y_min_raw * factor, 3)
    y_max = round(y_max_raw * factor, 3)
    z_min = round(z_min_raw * factor, 3)
    z_max = round(z_max_raw * factor, 3)

    length = round(x_max - x_min, 3)
    width  = round(y_max - y_min, 3)
    height = round(z_max - z_min, 3)

    if length < 0.001 and width < 0.001 and height < 0.001:
        return {
            "success": False,
            "message": (
                "All extracted points are coincident — file may be empty, "
                "contain only 2D data, or have all geometry at a single point."
            ),
        }

    # ── volumes ───────────────────────────────────────────────────────────────
    bbox_vol_mm3  = length * width * height
    bbox_vol_cm3  = round(bbox_vol_mm3 / 1000.0, 3)
    part_vol_cm3  = round(bbox_vol_cm3 * 0.60, 3)

    # ── build message ─────────────────────────────────────────────────────────
    conv_note = ""
    if converted:
        conv_note = (
            f" Coordinates were in {unit_label.split('(')[0].strip()} "
            f"and multiplied by {factor} to convert to mm."
        )

    message = (
        f"Extracted {len(xs):,} points · "
        f"Bounding box: {length} × {width} × {height} mm.{conv_note} "
        "Adjust volumes if needed."
    )

    return {
        "success": True,
        "length_mm": length,
        "width_mm":  width,
        "height_mm": height,
        "stock_volume_cm3": bbox_vol_cm3,
        "part_volume_cm3":  part_vol_cm3,
        "point_count": len(xs),
        "x_range": (x_min, x_max),
        "y_range": (y_min, y_max),
        "z_range": (z_min, z_max),
        # Raw (pre-conversion) ranges for reference
        "x_range_raw": (round(x_min_raw, 6), round(x_max_raw, 6)),
        "y_range_raw": (round(y_min_raw, 6), round(y_max_raw, 6)),
        "z_range_raw": (round(z_min_raw, 6), round(z_max_raw, 6)),
        # Unit info
        "detected_unit_label": unit_label,
        "conversion_factor":   factor,
        "detection_method":    method,
        "converted":           converted,
        "message": message,
    }
