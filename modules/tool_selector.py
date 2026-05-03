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

    if operation_type in ("Drill", "Pilot Drill") and diameter > 0:
        exact = [t for t in candidates if abs(t["diameter_mm"] - diameter) < 0.5]
        if exact:
            return exact[0]
        closest = min(candidates, key=lambda t: abs(t["diameter_mm"] - diameter))
        return closest

    if operation_type in ("Rough End Mill", "Finish End Mill", "End Mill"):
        suitable = [t for t in candidates if t["max_depth_mm"] >= depth or depth == 0]
        if suitable:
            if operation_type == "Finish End Mill":
                return min(suitable, key=lambda t: t["diameter_mm"])
            return max(suitable, key=lambda t: t["diameter_mm"])
        return candidates[0] if candidates else tools[0]

    return candidates[0] if candidates else tools[0]


def get_spindle_and_feed(tool, material):
    """Adjust spindle and feed based on material machinability factor."""
    factor = material.get("machinability_factor", 1.0)
    spindle = int(tool["default_spindle_rpm"] * factor)
    feed = int(tool["default_feed_rate_mm_min"] * factor)
    return spindle, feed
