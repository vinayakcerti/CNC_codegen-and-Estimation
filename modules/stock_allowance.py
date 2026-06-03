import copy


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
    adjusted = copy.deepcopy(candidates or [])

    part_l = _num(part_dims.get("length_mm") or part_dims.get("length"))
    part_w = _num(part_dims.get("width_mm") or part_dims.get("width"))
    part_h = _num(part_dims.get("height_mm") or part_dims.get("height"))
    stock_l = _num(stock.get("length"))
    stock_w = _num(stock.get("width"))
    stock_h = _num(stock.get("height"))

    z_allow = max((stock_h - part_h) / 2, 0.0) if stock_h and part_h else 0.0
    if z_allow > tolerance:
        for cand in adjusted:
            if _is_face_milling(cand):
                cand["feature_type"] = "Face Milling"
                cand["depth"] = round(z_allow, 3)
                note = cand.get("detection_note") or ""
                stock_note = (
                    f"Depth adjusted from configured stock height: "
                    f"({stock_h:.1f} - {part_h:.1f}) / 2 = {z_allow:.3f} mm."
                )
                cand["detection_note"] = f"{note} {stock_note}".strip()

    if not include_edge_milling:
        return adjusted

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
                "detection_source": "stock_allowance",
                "edge_axis": "X",
                "edge_side": side,
                "detection_note": (
                    f"Derived from configured stock length: "
                    f"({stock_l:.1f} - {part_l:.1f}) / 2 = {x_allow:.3f} mm per side."
                ),
            })

    if y_allow > tolerance and part_l > 0 and part_h > 0:
        for side, ypos in (("Y-", y_min), ("Y+", y_max)):
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
                "detection_source": "stock_allowance",
                "edge_axis": "Y",
                "edge_side": side,
                "detection_note": (
                    f"Derived from configured stock width: "
                    f"({stock_w:.1f} - {part_w:.1f}) / 2 = {y_allow:.3f} mm per side."
                ),
            })

    existing_ids = {c.get("candidate_id") for c in adjusted}
    adjusted.extend(c for c in edge_candidates if c["candidate_id"] not in existing_ids)
    return adjusted
