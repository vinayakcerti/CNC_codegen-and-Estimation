import copy

from modules.geometry_transform import (
    attach_work_coordinates,
    build_transform,
    infer_work_transform,
)
from modules.step_parser import assign_stable_candidate_ids

def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_face_milling(candidate):
    return "face mill" in str(candidate.get("feature_type") or "").lower()


def _setup_from_vector(vector):
    axis = max(range(3), key=lambda index: abs(vector[index]))
    sign = 1 if vector[axis] >= 0 else -1
    return {
        (0, 1): "Right",
        (0, -1): "Left",
        (1, 1): "Back",
        (1, -1): "Front",
        (2, 1): "Top",
        (2, -1): "Bottom",
    }[(axis, sign)]


def _raw_bounds_from_work_plane(transform, points):
    raw = [transform.inverse_point(*point) for point in points]
    return {
        f"{axis}_{bound}": round(
            (min if bound == "min" else max)(point[index] for point in raw),
            6,
        )
        for index, axis in enumerate(("x", "y", "z"))
        for bound in ("min", "max")
    }


def _orient_transform_to_feature_side(transform, candidates, part_dims):
    """Flip work Z when the dominant exact machining side currently faces down."""
    weights = {
        "hole": 2,
        "large hole / boring": 2,
        "slot": 3,
        "pocket": 3,
        "step": 3,
        "chamfer": 1,
    }
    top_score = 0
    bottom_score = 0
    for candidate in candidates or []:
        feature_type = str(candidate.get("feature_type") or "").lower()
        weight = weights.get(feature_type, 0)
        if not weight:
            continue
        transformed = attach_work_coordinates(candidate, transform)
        setup = transformed.get("work_setup_label")
        quantity = max(int(candidate.get("quantity") or 1), 1)
        if setup == "Top":
            top_score += weight * quantity
        elif setup == "Bottom":
            bottom_score += weight * quantity

    if bottom_score <= top_score or bottom_score == 0:
        return transform
    signs = list(transform.signs)
    signs[2] *= -1
    return build_transform(
        part_dims,
        work_axes=transform.work_axes,
        signs=tuple(signs),
        reason=f"{transform.reason}; work Z reversed to place dominant machining side on Top",
    )


def _work_top_score(transform, candidates):
    weights = {
        "hole": 2,
        "large hole / boring": 2,
        "slot": 3,
        "pocket": 3,
        "step": 3,
        "chamfer": 1,
    }
    score = 0
    for candidate in candidates or []:
        weight = weights.get(str(candidate.get("feature_type") or "").lower(), 0)
        if not weight:
            continue
        transformed = attach_work_coordinates(candidate, transform)
        if transformed.get("work_setup_label") == "Top":
            score += weight * max(int(candidate.get("quantity") or 1), 1)
    return score


def _hydrate_face_meshes(candidate, mesh_catalog):
    if candidate.get("face_mesh_data"):
        return
    candidate["face_mesh_data"] = [
        mesh_catalog[index]
        for index in candidate.get("face_indices", [])
        if index in mesh_catalog
    ]


def analyze_rectangular_stock(stock, work_spans, tolerance=0.01):
    """Validate rectangular stock and return explicit per-side allowances."""
    stock = stock or {}
    dimensions = (
        ("X", _num(stock.get("length")), _num(work_spans[0]), _num(stock.get("part_offset_x"))),
        ("Y", _num(stock.get("width")), _num(work_spans[1]), _num(stock.get("part_offset_y"))),
        ("Z", _num(stock.get("height")), _num(work_spans[2]), _num(stock.get("part_offset_z"))),
    )
    allowances = {}
    errors = []
    for axis, stock_size, part_size, offset in dimensions:
        total = stock_size - part_size
        if stock_size <= 0 or part_size <= 0:
            errors.append(f"{axis}: stock and part dimensions must be positive.")
            continue
        if total < -tolerance:
            errors.append(
                f"{axis}: stock {stock_size:.3f} mm is smaller than "
                f"part {part_size:.3f} mm."
            )
            continue
        total = max(total, 0.0)
        minus = (total / 2.0) + offset
        plus = (total / 2.0) - offset
        if minus < -tolerance or plus < -tolerance:
            errors.append(
                f"{axis}: part offset {offset:.3f} mm places the part "
                "outside the stock envelope."
            )
            continue
        allowances[f"{axis.lower()}_minus"] = max(minus, 0.0)
        allowances[f"{axis.lower()}_plus"] = max(plus, 0.0)
    return {
        "valid": not errors,
        "errors": errors,
        "allowances": allowances,
        "part_offsets": {
            "x": _num(stock.get("part_offset_x")),
            "y": _num(stock.get("part_offset_y")),
            "z": _num(stock.get("part_offset_z")),
        },
    }


def apply_stock_allowance_to_candidates(
    candidates,
    stock,
    part_dims,
    include_edge_milling=True,
    apply_raw_stock_allowance=True,
    tolerance=0.01,
):
    """Return oriented candidates, optionally with rectangular billet allowance."""
    stock = stock or {}
    part_dims = part_dims or {}
    source_part_dims = dict(part_dims)
    adjusted = copy.deepcopy(candidates or [])
    work_transform = infer_work_transform(source_part_dims, stock, tolerance)
    candidate_sets = []
    mesh_catalog = {}
    for candidate in adjusted:
        candidate_sets.extend(candidate.pop("detection_candidate_sets", []) or [])
        mesh_catalog.update(candidate.pop("face_mesh_catalog", {}) or {})
    matching_sets = [
        candidate_set
        for candidate_set in candidate_sets
        if tuple(candidate_set.get("work_axes_from_cad") or ()) == work_transform.work_axes
    ]
    if matching_sets:
        selected_set = max(
            matching_sets,
            key=lambda candidate_set: (
                _work_top_score(
                    work_transform,
                    candidate_set.get("candidates", []),
                ),
                _num(candidate_set.get("score")),
                _num(candidate_set.get("top_score")),
            ),
        )
        adjusted = copy.deepcopy(selected_set.get("candidates", []))
    for candidate in adjusted:
        _hydrate_face_meshes(candidate, mesh_catalog)
        for orientation_face in candidate.get("orientation_face_candidates", []) or []:
            _hydrate_face_meshes(orientation_face, mesh_catalog)
    work_transform = _orient_transform_to_feature_side(
        work_transform,
        adjusted,
        source_part_dims,
    )
    orientation_faces = []
    for candidate in adjusted:
        orientation_faces.extend(candidate.pop("orientation_face_candidates", []) or [])
    if (
        work_transform.work_axes != ("x", "y", "z")
        or work_transform.signs != (1, 1, 1)
    ) and orientation_faces:
        selected_faces = []
        for candidate in orientation_faces:
            transformed = attach_work_coordinates(candidate, work_transform)
            work_setup = transformed.get("work_setup_label")
            if work_setup not in {"Top", "Bottom"}:
                continue
            transformed["feature_name"] = f"Face milling - {work_setup.lower()} surface"
            selected_faces.append(transformed)
        if {candidate.get("work_setup_label") for candidate in selected_faces} == {"Top", "Bottom"}:
            adjusted = [
                candidate
                for candidate in adjusted
                if not _is_face_milling(candidate)
            ] + selected_faces

    part_l, part_w, part_h = (
        _num(value) for value in work_transform.work_spans
    )
    stock_l = _num(stock.get("length"))
    stock_w = _num(stock.get("width"))
    stock_h = _num(stock.get("height"))
    stock_analysis = analyze_rectangular_stock(
        stock,
        work_transform.work_spans,
        tolerance,
    )
    allowances = stock_analysis["allowances"]
    x_minus = allowances.get("x_minus", 0.0)
    x_plus = allowances.get("x_plus", 0.0)
    y_minus = allowances.get("y_minus", 0.0)
    y_plus = allowances.get("y_plus", 0.0)
    z_minus = allowances.get("z_minus", 0.0)
    z_plus = allowances.get("z_plus", 0.0)
    if apply_raw_stock_allowance:
        if not stock_analysis["valid"]:
            return [
                attach_work_coordinates(candidate, work_transform)
                for candidate in adjusted
            ]
        for cand in adjusted:
            ftype_lower = str(cand.get("feature_type") or "").lower()
            if _is_face_milling(cand):
                cand["length"] = round(stock_l or part_l, 3)
                cand["width"] = round(stock_w or part_w, 3)
                work_setup = (
                    cand.get("work_setup_label")
                    or attach_work_coordinates(cand, work_transform).get("work_setup_label")
                )
                face_allowance = z_plus if work_setup == "Top" else z_minus
                cand["feature_type"] = "Face Milling"
                # Sub-tolerance stock noise (e.g. stock 100.005 vs part 100.0)
                # must not overwrite a real detected facing depth with ~0 —
                # mirror the edge-milling tolerance gate: only allowances
                # above tolerance restate the facing depth.
                if face_allowance > tolerance:
                    cand["depth"] = round(face_allowance, 3)
                    note = cand.get("detection_note") or ""
                    stock_note = (
                        f"Depth adjusted from configured stock placement: "
                        f"{work_setup} allowance = {face_allowance:.3f} mm."
                    )
                    cand["detection_note"] = f"{note} {stock_note}".strip()
            elif ftype_lower == "step":
                width = _num(cand.get("width"))
                if (
                    max(y_minus, y_plus) > tolerance
                    and part_w > part_h + tolerance
                    and abs(width - part_h) <= tolerance
                ):
                    cand["width"] = round(part_w, 3)
                    length = _num(cand.get("length"))
                    depth = _num(cand.get("depth"))
                    if length > 0 and depth > 0:
                        cand["feature_name"] = (
                            f"Step shoulder {length:.1f}x{part_w:.1f} "
                            f"depth {depth:.1f} mm"
                        )
                    note = cand.get("detection_note") or ""
                    orient_note = (
                        "Width adjusted from the oriented work envelope for "
                        "stock-facing step planning."
                    )
                    cand["detection_note"] = f"{note} {orient_note}".strip()

    if not apply_raw_stock_allowance or not include_edge_milling:
        return [
            attach_work_coordinates(candidate, work_transform)
            for candidate in adjusted
        ]

    edge_candidates = []
    if part_w > 0 and part_h > 0:
        for side, work_x, work_normal, side_allowance in (
            ("X-", 0.0, (-1.0, 0.0, 0.0), x_minus),
            ("X+", part_l, (1.0, 0.0, 0.0), x_plus),
        ):
            if side_allowance <= tolerance:
                continue
            raw_position = work_transform.inverse_point(
                work_x,
                part_w / 2,
                part_h / 2,
            )
            raw_normal = work_transform.inverse_vector(*work_normal)
            edge_candidates.append({
                "candidate_id": f"STK_EDGE_{side}",
                "feature_name": f"Edge milling {side} stock allowance",
                "feature_type": "Edge Milling",
                "quantity": 1,
                "x_pos": raw_position[0],
                "y_pos": raw_position[1],
                "z_pos": raw_position[2],
                "diameter": None,
                "length": round(part_w, 3),
                "width": round(part_h, 3),
                "depth": round(side_allowance, 3),
                "tolerance_note": "",
                "priority": 1,
                "confidence": "derived",
                "setup_label": _setup_from_vector(raw_normal),
                "detection_source": "stock_allowance",
                "edge_axis": "X",
                "edge_side": side,
                "visual_bounds": _raw_bounds_from_work_plane(
                    work_transform,
                    [
                        (work_x, 0.0, 0.0),
                        (work_x, part_w, 0.0),
                        (work_x, 0.0, part_h),
                        (work_x, part_w, part_h),
                    ],
                ),
                "detection_note": (
                    f"Derived from configured stock length: "
                    f"{side} allowance = {side_allowance:.3f} mm."
                ),
            })

    if part_l > 0 and part_h > 0:
        for side, work_y, work_normal, side_allowance in (
            ("Y-", 0.0, (0.0, -1.0, 0.0), y_minus),
            ("Y+", part_w, (0.0, 1.0, 0.0), y_plus),
        ):
            if side_allowance <= tolerance:
                continue
            raw_position = work_transform.inverse_point(
                part_l / 2,
                work_y,
                part_h / 2,
            )
            raw_normal = work_transform.inverse_vector(*work_normal)
            edge_candidates.append({
                "candidate_id": f"STK_EDGE_{side}",
                "feature_name": f"Edge milling {side} stock allowance",
                "feature_type": "Edge Milling",
                "quantity": 1,
                "x_pos": raw_position[0],
                "y_pos": raw_position[1],
                "z_pos": raw_position[2],
                "diameter": None,
                "length": round(part_l, 3),
                "width": round(part_h, 3),
                "depth": round(side_allowance, 3),
                "tolerance_note": "",
                "priority": 1,
                "confidence": "derived",
                "setup_label": _setup_from_vector(raw_normal),
                "detection_source": "stock_allowance",
                "edge_axis": "Y",
                "edge_side": side,
                "visual_bounds": _raw_bounds_from_work_plane(
                    work_transform,
                    [
                        (0.0, work_y, 0.0),
                        (part_l, work_y, 0.0),
                        (0.0, work_y, part_h),
                        (part_l, work_y, part_h),
                    ],
                ),
                "detection_note": (
                    f"Derived from configured stock width: "
                    f"{side} allowance = {side_allowance:.3f} mm."
                ),
            })

    existing_ids = {c.get("candidate_id") for c in adjusted}
    source_file_hash = next(
        (
            candidate.get("source_file_hash")
            for candidate in adjusted
            if candidate.get("source_file_hash")
        ),
        "stock-derived",
    )
    assign_stable_candidate_ids(edge_candidates, source_file_hash)
    adjusted.extend(c for c in edge_candidates if c["candidate_id"] not in existing_ids)
    return [
        attach_work_coordinates(candidate, work_transform)
        for candidate in adjusted
    ]
