def select_tool_for_operation(operation_type, feature, tools):
    """Select the best tool from the library for a given operation type."""
    tool_type_map = {
        "Spot Drill": ["Spot Drill"],
        "Drill": ["Drill"],
        "Pilot Drill": ["Drill"],
        "Boring": ["Boring"],
        "Rough End Mill": ["End Mill"],
        "Finish End Mill": ["End Mill"],
        "End Mill": ["End Mill"],
        "Face Mill": ["Face Mill"],
        "Chamfer": ["Chamfer"],
    }

    preferred_types = tool_type_map.get(operation_type, ["End Mill"])
    diameter = feature.get("diameter", 0) or 0
    depth = feature.get("depth", 0) or 0

    candidates = [t for t in tools if t["tool_type"] in preferred_types]

    if not candidates:
        candidates = tools

    # Drill: exact or closest diameter match to the feature's bore/hole diameter.
    if operation_type == "Drill" and diameter > 0:
        exact = [t for t in candidates if abs(t["diameter_mm"] - diameter) < 0.5]
        if exact:
            return exact[0]
        return min(candidates, key=lambda t: abs(t["diameter_mm"] - diameter))

    # Pilot Drill: intentionally small — a pilot hole centres the boring bar and
    # provides clearance, so it must NOT be matched to the final bore diameter.
    # Always pick the smallest available drill regardless of feature diameter.
    if operation_type == "Pilot Drill":
        return min(candidates, key=lambda t: t["diameter_mm"])

    if operation_type in ("Rough End Mill", "Finish End Mill", "End Mill"):
        # max_depth_mm is a soft preference, not a hard capability gate.
        # A tool that exceeds the feature depth in a single pass is ideal, but
        # any end mill can reach greater depths if programmed in multiple passes.
        # Prefer tools that cover depth in one pass; fall back to largest diameter.
        max_dep = lambda t: t.get("max_depth_mm") or 0
        suitable = [t for t in candidates if max_dep(t) >= depth or depth == 0]
        pool = suitable if suitable else candidates   # fall back to full set
        if operation_type == "Finish End Mill":
            return min(pool, key=lambda t: t["diameter_mm"])
        return max(pool, key=lambda t: t["diameter_mm"])

    return candidates[0] if candidates else tools[0]


def get_spindle_and_feed(tool, material):
    """Adjust spindle and feed based on material machinability factor."""
    factor = material.get("machinability_factor", 1.0)
    spindle = int(tool["default_spindle_rpm"] * factor)
    feed = int(tool["default_feed_rate_mm_min"] * factor)
    return spindle, feed
