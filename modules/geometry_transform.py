from dataclasses import dataclass
from itertools import permutations, product


_AXES = ("x", "y", "z")
_SETUP_BY_AXIS = {
    (0, 1): "Right",
    (0, -1): "Left",
    (1, 1): "Back",
    (1, -1): "Front",
    (2, 1): "Top",
    (2, -1): "Bottom",
}


def _num(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _axis_range(part_dims, axis):
    bounds = (part_dims or {}).get(f"{axis}_range")
    if isinstance(bounds, (list, tuple)) and len(bounds) >= 2:
        return _num(bounds[0]), _num(bounds[1])
    span = _num((part_dims or {}).get({
        "x": "length_mm",
        "y": "width_mm",
        "z": "height_mm",
    }[axis]))
    return 0.0, span


@dataclass(frozen=True)
class CoordinateTransform:
    """Axis-aligned CAD-to-work transform.

    ``work_axes`` gives the CAD axis used for work X, Y, and Z. ``signs``
    supports mirrored/reversed axes. The work origin is the minimum transformed
    corner, so supported parts occupy non-negative work coordinates.
    """

    work_axes: tuple = ("x", "y", "z")
    signs: tuple = (1, 1, 1)
    cad_origin: tuple = (0.0, 0.0, 0.0)
    work_spans: tuple = (0.0, 0.0, 0.0)
    reason: str = "CAD axes already match planning axes"

    def point(self, x, y, z):
        cad = {"x": _num(x), "y": _num(y), "z": _num(z)}
        origin = dict(zip(_AXES, self.cad_origin))
        values = []
        for axis, sign in zip(self.work_axes, self.signs):
            if sign >= 0:
                values.append(cad[axis] - origin[axis])
            else:
                values.append(origin[axis] - cad[axis])
        return tuple(values)

    def vector(self, x, y, z):
        cad = {"x": _num(x), "y": _num(y), "z": _num(z)}
        return tuple(
            sign * cad[axis]
            for axis, sign in zip(self.work_axes, self.signs)
        )

    def inverse_point(self, x, y, z):
        work = (_num(x), _num(y), _num(z))
        origin = dict(zip(_AXES, self.cad_origin))
        cad = dict(origin)
        for value, axis, sign in zip(work, self.work_axes, self.signs):
            cad[axis] = origin[axis] + sign * value
        return tuple(cad[axis] for axis in _AXES)

    def inverse_vector(self, x, y, z):
        work = (_num(x), _num(y), _num(z))
        cad = {axis: 0.0 for axis in _AXES}
        for value, axis, sign in zip(work, self.work_axes, self.signs):
            cad[axis] = sign * value
        return tuple(cad[axis] for axis in _AXES)

    def setup_label(self, nx, ny, nz, threshold=0.5):
        work_normal = self.vector(nx, ny, nz)
        axis = max(range(3), key=lambda idx: abs(work_normal[idx]))
        value = work_normal[axis]
        if abs(value) < threshold:
            return "Unknown"
        return _SETUP_BY_AXIS[(axis, 1 if value > 0 else -1)]

    def to_dict(self):
        return {
            "coordinate_frame": "work",
            "work_origin": "minimum transformed part corner",
            "work_axes_from_cad": list(self.work_axes),
            "axis_signs": list(self.signs),
            "cad_origin": list(self.cad_origin),
            "work_spans": list(self.work_spans),
            "reason": self.reason,
        }


def build_transform(part_dims, work_axes=("x", "y", "z"), signs=(1, 1, 1), reason=""):
    ranges = {axis: _axis_range(part_dims, axis) for axis in _AXES}
    origins = {}
    spans = []
    for axis, sign in zip(work_axes, signs):
        low, high = ranges[axis]
        origins[axis] = low if sign >= 0 else high
        spans.append(abs(high - low))
    return CoordinateTransform(
        work_axes=tuple(work_axes),
        signs=tuple(signs),
        cad_origin=tuple(origins[axis] for axis in _AXES),
        work_spans=tuple(spans),
        reason=reason or "Explicit CAD-to-work axis mapping",
    )


def infer_work_transform(part_dims, stock=None, tolerance=0.01):
    """Choose the least-disruptive axis permutation that fits configured stock.

    Identity is preferred. Y/Z swap is next because many VMC STEP exports use
    Y as the vertical axis. Other permutations are retained as metadata but are
    marked as requiring manual orientation review by the caller.
    """
    stock = stock or {}
    stock_spans = (
        _num(stock.get("length")),
        _num(stock.get("width")),
        _num(stock.get("height")),
    )
    cad_spans = {
        axis: abs(_axis_range(part_dims, axis)[1] - _axis_range(part_dims, axis)[0])
        for axis in _AXES
    }

    preferred = [
        ("x", "y", "z"),
        ("x", "z", "y"),
        ("z", "y", "x"),
        ("y", "x", "z"),
        ("y", "z", "x"),
        ("z", "x", "y"),
    ]
    candidates = preferred + [
        axes for axes in permutations(_AXES)
        if axes not in preferred
    ]

    chosen = ("x", "y", "z")
    if all(value > 0 for value in stock_spans):
        for axes in candidates:
            spans = tuple(cad_spans[axis] for axis in axes)
            if all(span <= limit + tolerance for span, limit in zip(spans, stock_spans)):
                chosen = axes
                break

    if chosen == ("x", "y", "z"):
        reason = "CAD axes already match configured stock"
    elif chosen == ("x", "z", "y"):
        reason = "CAD Y/Z axes swapped to fit configured stock"
    else:
        reason = (
            "CAD axes permuted to fit configured stock; operator orientation "
            "confirmation required"
        )
    return build_transform(part_dims, chosen, reason=reason)


def transform_mesh_and_candidates(mesh_data, candidates, transform):
    """Return work-frame copies of a tessellated mesh and its candidate overlays.

    mesh_data and candidates are read-only here — new dicts/lists are returned
    so callers (e.g. the 3D viewer) can render in the same corner-origin work
    frame used by the stock dimensions and feature table, without disturbing
    the CAD-frame data that stock_allowance.py relies on elsewhere.
    """
    new_mesh = dict(mesh_data or {})
    xs, ys, zs = mesh_data.get("x", []), mesh_data.get("y", []), mesh_data.get("z", [])
    pts = [transform.point(x, y, z) for x, y, z in zip(xs, ys, zs)]
    new_mesh["x"] = [p[0] for p in pts]
    new_mesh["y"] = [p[1] for p in pts]
    new_mesh["z"] = [p[2] for p in pts]

    new_candidates = []
    for cand in (candidates or []):
        new_cand = dict(cand)
        x0, y0, z0 = cand.get("x_pos") or 0, cand.get("y_pos") or 0, cand.get("z_pos") or 0
        wx, wy, wz = transform.point(x0, y0, z0)
        new_cand["x_pos"], new_cand["y_pos"], new_cand["z_pos"] = wx, wy, wz

        face_mesh_data = cand.get("face_mesh_data")
        if face_mesh_data:
            new_face_mesh_data = []
            for face_mesh in face_mesh_data:
                verts = face_mesh.get("vertices", [])
                new_verts = [list(transform.point(v[0], v[1], v[2])) for v in verts]
                new_face_mesh = dict(face_mesh)
                new_face_mesh["vertices"] = new_verts
                new_face_mesh_data.append(new_face_mesh)
            new_cand["face_mesh_data"] = new_face_mesh_data

        vb = cand.get("visual_bounds")
        if vb and all(vb.get(k) is not None for k in ("x_min", "x_max", "y_min", "y_max", "z_min", "z_max")):
            corners = [
                transform.point(x, y, z)
                for x in (float(vb["x_min"]), float(vb["x_max"]))
                for y in (float(vb["y_min"]), float(vb["y_max"]))
                for z in (float(vb["z_min"]), float(vb["z_max"]))
            ]
            new_cand["visual_bounds"] = {
                "x_min": min(c[0] for c in corners), "x_max": max(c[0] for c in corners),
                "y_min": min(c[1] for c in corners), "y_max": max(c[1] for c in corners),
                "z_min": min(c[2] for c in corners), "z_max": max(c[2] for c in corners),
            }

        new_candidates.append(new_cand)

    return new_mesh, new_candidates


def _footprint_work_bounds(candidate, transform):
    """Return (work_min, work_max) corner dicts for a candidate's actual face
    geometry, or None if no exact face_mesh_data is available.

    Only derived from real tessellated vertices — never fabricated from
    length/width heuristics — so an absent result honestly means "no exact
    footprint known" rather than guessing one (see Epic 11.3).
    """
    face_mesh_data = candidate.get("face_mesh_data")
    if not face_mesh_data:
        return None

    cad_verts = [
        vertex
        for face_mesh in face_mesh_data
        for vertex in face_mesh.get("vertices", [])
    ]
    if not cad_verts:
        return None

    cxmin = min(v[0] for v in cad_verts)
    cxmax = max(v[0] for v in cad_verts)
    cymin = min(v[1] for v in cad_verts)
    cymax = max(v[1] for v in cad_verts)
    czmin = min(v[2] for v in cad_verts)
    czmax = max(v[2] for v in cad_verts)

    # Transform all 8 CAD-frame corners — a transform with reversed axis
    # signs can flip which CAD corner becomes the work-frame minimum.
    work_corners = [
        transform.point(x, y, z)
        for x, y, z in product((cxmin, cxmax), (cymin, cymax), (czmin, czmax))
    ]
    work_min = tuple(min(corner[i] for corner in work_corners) for i in range(3))
    work_max = tuple(max(corner[i] for corner in work_corners) for i in range(3))
    return (
        {axis: round(value, 6) for axis, value in zip(_AXES, work_min)},
        {axis: round(value, 6) for axis, value in zip(_AXES, work_max)},
    )


def attach_work_coordinates(candidate, transform):
    """Attach raw CAD and transformed work coordinates without losing either."""
    result = dict(candidate)
    cad_position = result.get("cad_position") or {
        "x": result.get("x_pos"),
        "y": result.get("y_pos"),
        "z": result.get("z_pos"),
    }
    if all(cad_position.get(axis) is not None for axis in _AXES):
        work = transform.point(
            cad_position["x"],
            cad_position["y"],
            cad_position["z"],
        )
        result["cad_position"] = {
            axis: round(_num(cad_position[axis]), 6)
            for axis in _AXES
        }
        result["work_position"] = {
            axis: round(value, 6)
            for axis, value in zip(_AXES, work)
        }
        result["work_x_pos"], result["work_y_pos"], result["work_z_pos"] = work
    footprint = _footprint_work_bounds(result, transform)
    if footprint is not None:
        result["footprint_work_min"], result["footprint_work_max"] = footprint
    setup_vectors = {
        "Right": (1, 0, 0),
        "Left": (-1, 0, 0),
        "Back": (0, 1, 0),
        "Front": (0, -1, 0),
        "Top": (0, 0, 1),
        "Bottom": (0, 0, -1),
    }
    source_setup = result.get("setup_label")
    if source_setup in setup_vectors:
        result["cad_setup_label"] = source_setup
        result["work_setup_label"] = transform.setup_label(*setup_vectors[source_setup])
    result["coordinate_transform"] = transform.to_dict()
    return result
