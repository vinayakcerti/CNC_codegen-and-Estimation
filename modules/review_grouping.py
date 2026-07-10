"""Candidate review grouping — relocated verbatim from the retired Streamlit
app.py (Jul 2026) because the golden/visual regression suites assert on this
grouping behaviour. Pure logic, no UI dependencies.

Groups noisy CAD candidates for operator review: bucket by
(feature_type, dia, length, width, depth) rounded to 0.1, then — for
fabricated/rework parts — collapse duplicate slot detections to one
representative per approximate physical location.
"""

_NON_RAW_SPTS = {"Weldment / Fabricated Part", "Casting / Forging", "Existing Part / Rework"}


def _candidate_review_location_key(candidate):
    """Approximate a physical feature location for noisy review grouping."""
    return (
        round(float(candidate.get("x_pos") or candidate.get("center_x") or 0.0), 0),
        round(float(candidate.get("y_pos") or candidate.get("center_y") or 0.0), 0),
        round(float(candidate.get("z_pos") or candidate.get("center_z") or 0.0), 0),
    )


def _candidate_float(candidate, key, fallback_key=None):
    return float(candidate.get(key) or (candidate.get(fallback_key) if fallback_key else 0.0) or 0.0)


def _same_review_location(a, b):
    """Return True when two noisy slot detections represent the same place."""
    ax = _candidate_float(a, "x_pos", "center_x")
    ay = _candidate_float(a, "y_pos", "center_y")
    az = _candidate_float(a, "z_pos", "center_z")
    bx = _candidate_float(b, "x_pos", "center_x")
    by = _candidate_float(b, "y_pos", "center_y")
    bz = _candidate_float(b, "z_pos", "center_z")

    length = max(_candidate_float(a, "length"), _candidate_float(b, "length"))
    width = max(_candidate_float(a, "width"), _candidate_float(b, "width"))
    depth = max(_candidate_float(a, "depth"), _candidate_float(b, "depth"))

    long_tol = max(3.0, length * 0.12)
    short_tol = max(3.0, width * 1.5)
    z_tol = max(3.0, depth * 0.35)
    dx = abs(ax - bx)
    dy = abs(ay - by)
    dz = abs(az - bz)

    same_xy = (
        (dx <= long_tol and dy <= short_tol)
        or (dx <= short_tol and dy <= long_tol)
    )
    return same_xy and dz <= z_tol


def _representative_members_by_location(members):
    """Return one candidate per approximate physical location."""
    reps = []
    for member in members:
        if any(_same_review_location(member, rep) for rep in reps):
            continue
        reps.append(member)
    return reps or list(members)


def _build_candidate_groups(candidates, spt):
    """Group candidates by (feature_type, dia_r1, len_r1, wid_r1, dep_r1).

    Returns a sorted list of group dicts with keys:
        group_key, feature_type, display_type, description,
        count, member_ids, confidence_summary
    """
    _is_non_raw = spt in _NON_RAW_SPTS
    buckets = {}
    for c in candidates:
        ftype  = c.get("feature_type") or "Unknown"
        dia    = round(float(c.get("diameter") or 0), 1)
        length = round(float(c.get("length")   or 0), 1)
        width  = round(float(c.get("width")    or 0), 1)
        depth  = round(float(c.get("depth")    or 0), 1)
        buckets.setdefault((ftype, dia, length, width, depth), []).append(c)

    groups = []
    for key, members in buckets.items():
        ftype, dia, length, width, depth = key
        detected_count = len(members)

        # Fabricated/rework STEP files can emit several slot candidates for the
        # same physical slot because opposite wall/floor faces are paired more
        # than one way. In grouped review, keep one representative per location;
        # flat mode still exposes the original detections for inspection.
        if _is_non_raw and ftype.lower() == "slot":
            review_members = _representative_members_by_location(members)
        else:
            review_members = list(members)
        review_count = len(review_members)

        # Relabel Slot → "Slot-like opening" for fabricated/rework/casting
        if _is_non_raw and ftype.lower() == "slot":
            display_type = "Slot-like opening"
        else:
            display_type = ftype

        # Human-readable size description
        ftype_lower = ftype.lower()
        if ftype_lower in ("hole", "large hole / boring"):
            if depth > 0:
                description = f"{display_type} Ø{dia:.1f} × {depth:.1f} mm"
            else:
                description = f"{display_type} Ø{dia:.1f} mm (through)"
        elif dia > 0:
            description = f"{display_type} Ø{dia:.1f} mm"
        elif length > 0 and width > 0 and depth > 0:
            description = f"{display_type} {length:.1f} × {width:.1f} × {depth:.1f} mm"
        elif length > 0 and width > 0:
            description = f"{display_type} {length:.1f} × {width:.1f} mm"
        else:
            description = display_type

        # Dominant confidence label across members
        conf_counts = {}
        for m in members:
            cv = str(m.get("confidence") or "unknown")
            conf_counts[cv] = conf_counts.get(cv, 0) + 1
        top_conf = max(conf_counts, key=conf_counts.get)
        confidence_summary = (
            f"{top_conf} (+{len(conf_counts) - 1} other)"
            if len(conf_counts) > 1 else top_conf
        )
        if detected_count != review_count:
            count_label = f"{review_count} location(s) ({detected_count} detected faces)"
        else:
            count_label = f"{review_count} found"

        groups.append({
            "group_key":          key,
            "feature_type":       ftype,
            "display_type":       display_type,
            "description":        description,
            "count":              review_count,
            "detected_count":     detected_count,
            "count_label":        count_label,
            "member_ids":         [m["candidate_id"] for m in review_members],
            "detected_member_ids": [m["candidate_id"] for m in members],
            "confidence_summary": confidence_summary,
        })

    groups.sort(key=lambda g: (g["feature_type"], g["description"]))
    return groups
