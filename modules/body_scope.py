"""Scope STEP feature candidates to individual weldment bodies.

Multi-body weldment STEP files are feature-detected as one compound, so the
candidate list mixes features from every body. The Part Setup weldment
breakdown lets the operator select one part group; this module maps candidates
onto that group's bodies so the review pages (Select Machining Work, Setup &
Feature Review) can isolate the selected part instead of showing
whole-assembly numbers as if they were single-part.

Membership test: the candidate's reference point in the RAW CAD frame
(``cad_position`` with fallbacks) must fall inside the body's axis-aligned
bounding box expanded by a small tolerance. Both the candidate positions
(restored to CAD frame by the step parser) and the body bboxes (from the
weldment body splitter) live in the same untransformed STEP coordinate frame.

Conservative rule: candidates whose position cannot be determined are KEPT
(never silently dropped) and reported via the ``unpositioned`` count so the
UI can flag them.

Pure Python — no Streamlit or CadQuery imports; safe for headless tests.
"""

DEFAULT_TOLERANCE_MM = 2.0

_BBOX_KEYS = ("xmin", "xmax", "ymin", "ymax", "zmin", "zmax")


def _first_number(*values):
    """First value coercible to float, honouring 0.0 as a real coordinate."""
    for value in values:
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def candidate_reference_point(candidate):
    """Best-effort raw-CAD reference point ``(x, y, z)`` for a candidate.

    x/y/z fall back through ``cad_position`` → ``x_pos``/``y_pos``/``z_pos`` →
    ``cx``/``cy``/``cz`` → ``center_x``/``center_y``/``center_z``. ``z`` may be
    None (some candidates carry no height reference). Returns None when x or y
    is unknown — the candidate cannot be position-tested at all.
    """
    if not isinstance(candidate, dict):
        return None
    cad = candidate.get("cad_position")
    cad = cad if isinstance(cad, dict) else {}
    x = _first_number(
        cad.get("x"), candidate.get("x_pos"),
        candidate.get("cx"), candidate.get("center_x"),
    )
    y = _first_number(
        cad.get("y"), candidate.get("y_pos"),
        candidate.get("cy"), candidate.get("center_y"),
    )
    z = _first_number(
        cad.get("z"), candidate.get("z_pos"),
        candidate.get("cz"), candidate.get("center_z"),
    )
    if x is None or y is None:
        return None
    return (x, y, z)


def _body_bounds(body):
    """Normalise a body descriptor to a float bbox dict, or None.

    Accepts either a ``bodies_raw`` entry (dict with a ``bbox`` key) or a bare
    bbox dict with xmin..zmax keys.
    """
    if not isinstance(body, dict):
        return None
    bbox = body.get("bbox") if isinstance(body.get("bbox"), dict) else None
    if bbox is None and all(key in body for key in _BBOX_KEYS):
        bbox = body
    if not bbox:
        return None
    bounds = {}
    for key in _BBOX_KEYS:
        value = _first_number(bbox.get(key))
        if value is None:
            return None
        bounds[key] = value
    return bounds


def candidate_in_body(candidate, body, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Test one candidate against one body bbox.

    Returns True / False when the test could be performed, or None when the
    candidate has no usable position data or the body has no usable bbox
    (undetermined — callers should treat as "keep").

    The bbox is expanded by ``tolerance_mm`` on every side. When the candidate
    has no z reference, only x/y membership is required.
    """
    bounds = _body_bounds(body)
    point = candidate_reference_point(candidate)
    if bounds is None or point is None:
        return None
    x, y, z = point
    tol = float(tolerance_mm)
    if not (bounds["xmin"] - tol <= x <= bounds["xmax"] + tol):
        return False
    if not (bounds["ymin"] - tol <= y <= bounds["ymax"] + tol):
        return False
    if z is not None and not (bounds["zmin"] - tol <= z <= bounds["zmax"] + tol):
        return False
    return True


def scope_candidates_to_bodies(candidates, bodies, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Scope a candidate list to a set of bodies (a weldment part group).

    A candidate is kept when its reference point falls inside ANY of the given
    bodies' bboxes (expanded by tolerance). Candidates that cannot be
    position-tested against every body are kept conservatively.

    Returns a dict::

        {
            "kept":         [...],  # candidates in scope (originals, not copies)
            "excluded":     [...],  # provably outside every testable body
            "unpositioned": int,    # kept without a decidable position test
        }

    Input lists are never mutated.
    """
    kept, excluded, unpositioned = [], [], 0
    body_list = list(bodies or [])
    for candidate in candidates or []:
        statuses = [
            candidate_in_body(candidate, body, tolerance_mm)
            for body in body_list
        ]
        if any(status is True for status in statuses):
            kept.append(candidate)
        elif not statuses or any(status is None for status in statuses):
            # No bodies to test, or at least one undetermined test and no
            # positive match — cannot prove the candidate is out of scope.
            kept.append(candidate)
            unpositioned += 1
        else:
            excluded.append(candidate)
    return {"kept": kept, "excluded": excluded, "unpositioned": unpositioned}


def filter_candidates_to_body(candidates, body, tolerance_mm=DEFAULT_TOLERANCE_MM):
    """Candidates whose reference point lies inside one body's bbox.

    Convenience wrapper over :func:`scope_candidates_to_bodies` for a single
    body. Candidates lacking position data stay included (conservative).
    """
    return scope_candidates_to_bodies(candidates, [body], tolerance_mm)["kept"]
