import copy

from modules.geometry_transform import attach_work_coordinates, infer_work_transform

def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _range_center(bounds, fallback=0.0):
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
        return (_num(bounds[0]) + _num(bounds[1])) / 2
    return fallback


def _range_min(bounds, fallback):
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
        return _num(bounds[0], fallback)
    return fallback


def _range_max(bounds, fallback):
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
        return _num(bounds[1], fallback)
    return fallback


def _is_face_milling(candidate):
    return "face mill" in str(candidate.get("feature_type") or "").lower()


def _normalise_part_axes_for_stock(part_l, part_w, part_h, stock_l, stock_w, stock_h, part_dims, tolerance):
    """Return part axes adjusted when STEP width/height are clearly swapped.

    Some customer STEP files are modeled with the VMC vertical axis in Y rather
    than Z. The bounding-box parser then reports a physically impossible setup,
    for example finished height 90 mm inside 40 mm stock while finished width is
    only 30 mm inside 100 mm stock. If swapping width/height makes the part fit
    the configured stock, treat that as the planning orientation.
    """
    if not (part_l and part_w and part_h and stock_l and stock_w and stock_h):
        return part_l, part_w, part_h, part_dims, False

    original_fits = (
        part_l <= stock_l + tolerance
        and part_w <= stock_w + tolerance
        and part_h <= stock_h + tolerance
    )
    swapped_fits = (
        part_l <= stock_l + tolerance
        and part_h <= stock_w + tolerance
        and part_w <= stock_h + tolerance
    )
    if original_fits or not swapped_fits:
        return part_l, part_w, part_h, part_dims, False

    normalised_dims = dict(part_dims or {})
    normalised_dims["width_mm"] = part_h
    normalised_dims["width"] = part_h
    normalised_dims["height_mm"] = part_w
    normalised_dims["height"] = part_w
    if part_dims.get("z_range") is not None:
        normalised_dims["y_range"] = part_dims.get("z_range")
    return part_l, part_h, part_w, normalised_dims, True


def apply_stock_allowance_to_candidates(
    candidates,
    stock,
    part_dims,
    include_edge_milling=True,
    tolerance=0.01,
):
    """Return CAD candidates adjusted for configured raw stock allowance."""
    stock = stock or {}
    part_dims = part_dims or {}
    source_part_dims = dict(part_dims)
    adjusted = copy.deepcopy(candidates or [])
    work_transform = infer_work_transform(source_part_dims, stock, tolerance)
    orientation_faces = []
    for candidate in adjusted:
        orientation_faces.extend(candidate.pop("orientation_face_candidates", []) or [])
    if work_transform.work_axes != ("x", "y", "z") and orientation_faces:
        selected_faces = []
        for candidate in orientation_faces:
            transformed = attach_work_coordinates(candidate, work_transform)
            work_setup = transformed.get("work_setup_label")
            if work_setup not in {"Top", "Bottom"}:
                continue
            transformed["candidate_id"] = "F001" if work_setup == "Top" else "F002"
            transformed["feature_name"] = f"Face milling - {work_setup.lower()} surface"
            selected_faces.append(transformed)
        if {candidate.get("work_setup_label") for candidate in selected_faces} == {"Top", "Bottom"}:
            adjusted = [
                candidate
                for candidate in adjusted
                if not _is_face_milling(candidate)
            ] + selected_faces

    part_l = _num(part_dims.get("length_mm") or part_dims.get("length"))
    part_w = _num(part_dims.get("width_mm") or part_dims.get("width"))
    part_h = _num(part_dims.get("height_mm") or part_dims.get("height"))
    stock_l = _num(stock.get("length"))
    stock_w = _num(stock.get("width"))
    stock_h = _num(stock.get("height"))
    original_part_w = part_w
    source_x_min = _range_min(source_part_dims.get("x_range"), -part_l / 2)
    source_x_max = _range_max(source_part_dims.get("x_range"), part_l / 2)
    source_y_min = _range_min(source_part_dims.get("y_range"), -part_w / 2)
    source_y_max = _range_max(source_part_dims.get("y_range"), part_w / 2)
    source_z_min = _range_min(source_part_dims.get("z_range"), 0.0)
    source_z_max = _range_max(source_part_dims.get("z_range"), part_h)
    part_l, part_w, part_h, part_dims, axes_swapped = _normalise_part_axes_for_stock(
        part_l, part_w, part_h, stock_l, stock_w, stock_h, part_dims, tolerance
    )

    z_allow = max((stock_h - part_h) / 2, 0.0) if stock_h and part_h else 0.0
    if z_allow > tolerance or axes_swapped:
        for cand in adjusted:
            ftype_lower = str(cand.get("feature_type") or "").lower()
            if _is_face_milling(cand) and z_allow > tolerance:
                cand["feature_type"] = "Face Milling"
                cand["depth"] = round(z_allow, 3)
                if stock_l > 0:
                    cand["length"] = round(stock_l, 3)
                elif part_l > 0:
                    cand["length"] = round(part_l, 3)
                if stock_w > 0:
                    cand["width"] = round(stock_w, 3)
                elif part_w > 0:
                    cand["width"] = round(part_w, 3)
                note = cand.get("detection_note") or ""
                stock_note = (
                    f"Depth adjusted from configured stock height: "
                    f"({stock_h:.1f} - {part_h:.1f}) / 2 = {z_allow:.3f} mm."
                )
                cand["detection_note"] = f"{note} {stock_note}".strip()
            elif axes_swapped and ftype_lower == "step":
                width = _num(cand.get("width"))
                if original_part_w > 0 and part_w > 0 and abs(width - original_part_w) <= tolerance:
                    cand["width"] = round(part_w, 3)
                    length = _num(cand.get("length"))
                    depth = _num(cand.get("depth"))
                    if length > 0 and depth > 0:
                        cand["feature_name"] = (
                            f"Step shoulder {length:.1f}x{part_w:.1f} "
                            f"depth {depth:.1f} mm"
                        )
                    note = cand.get("detection_note") or ""
                    orient_note = "Width adjusted to planning orientation from configured stock."
                    cand["detection_note"] = f"{note} {orient_note}".strip()

    if not include_edge_milling:
        return [
            attach_work_coordinates(candidate, work_transform)
            for candidate in adjusted
        ]

    x_allow = max((stock_l - part_l) / 2, 0.0) if stock_l and part_l else 0.0
    y_allow = max((stock_w - part_w) / 2, 0.0) if stock_w and part_w else 0.0
    cx = _range_center(part_dims.get("x_range"), 0.0)
    cy = _range_center(part_dims.get("y_range"), 0.0)
    x_min = _range_min(part_dims.get("x_range"), cx - part_l / 2)
    x_max = _range_max(part_dims.get("x_range"), cx + part_l / 2)
    y_min = _range_min(part_dims.get("y_range"), cy - part_w / 2)
    y_max = _range_max(part_dims.get("y_range"), cy + part_w / 2)

    edge_candidates = []
    if x_allow > tolerance and part_w > 0 and part_h > 0:
        for side, xpos in (("X-", x_min), ("X+", x_max)):
            edge_candidates.append({
                "candidate_id": f"STK_EDGE_{side}",
                "feature_name": f"Edge milling {side} stock allowance",
                "feature_type": "Edge Milling",
                "quantity": 1,
                "x_pos": xpos,
                "y_pos": cy,
                "diameter": None,
                "length": round(part_w, 3),
                "width": round(part_h, 3),
                "depth": round(x_allow, 3),
                "tolerance_note": "",
                "priority": 1,
                "confidence": "derived",
                "setup_label": "Left" if side == "X-" else "Right",
                "detection_source": "stock_allowance",
                "edge_axis": "X",
                "edge_side": side,
                "visual_bounds": {
                    "x_min": xpos,
                    "x_max": xpos,
                    "y_min": source_y_min,
                    "y_max": source_y_max,
                    "z_min": source_z_min,
                    "z_max": source_z_max,
                },
                "detection_note": (
                    f"Derived from configured stock length: "
                    f"({stock_l:.1f} - {part_l:.1f}) / 2 = {x_allow:.3f} mm per side."
                ),
            })

    if y_allow > tolerance and part_l > 0 and part_h > 0:
        for side, ypos in (("Y-", y_min), ("Y+", y_max)):
            if axes_swapped:
                visual_bounds = {
                    "x_min": source_x_min,
                    "x_max": source_x_max,
                    "y_min": source_y_min,
                    "y_max": source_y_max,
                    "z_min": ypos,
                    "z_max": ypos,
                }
            else:
                visual_bounds = {
                    "x_min": source_x_min,
                    "x_max": source_x_max,
                    "y_min": ypos,
                    "y_max": ypos,
                    "z_min": source_z_min,
                    "z_max": source_z_max,
                }
            edge_candidates.append({
                "candidate_id": f"STK_EDGE_{side}",
                "feature_name": f"Edge milling {side} stock allowance",
                "feature_type": "Edge Milling",
                "quantity": 1,
                "x_pos": cx,
                "y_pos": ypos,
                "diameter": None,
                "length": round(part_l, 3),
                "width": round(part_h, 3),
                "depth": round(y_allow, 3),
                "tolerance_note": "",
                "priority": 1,
                "confidence": "derived",
                "setup_label": "Front" if side == "Y-" else "Back",
                "detection_source": "stock_allowance",
                "edge_axis": "Y",
                "edge_side": side,
                "visual_bounds": visual_bounds,
                "detection_note": (
                    f"Derived from configured stock width: "
                    f"({stock_w:.1f} - {part_w:.1f}) / 2 = {y_allow:.3f} mm per side."
                ),
            })

    existing_ids = {c.get("candidate_id") for c in adjusted}
    adjusted.extend(c for c in edge_candidates if c["candidate_id"] not in existing_ids)
    return [
        attach_work_coordinates(candidate, work_transform)
        for candidate in adjusted
    ]
