"""Conservative tool, holder, and machine-limit feasibility checks."""


def normalize_tool_profile(tool):
    tool = dict(tool or {})
    diameter = float(tool.get("diameter_mm") or 0.0)
    max_depth = float(tool.get("max_depth_mm") or 0.0)
    tool_type = str(tool.get("tool_type") or "")

    if float(tool.get("flute_length_mm") or 0.0) <= 0:
        if tool_type == "End Mill":
            tool["flute_length_mm"] = max(max_depth, diameter * 4.0)
        else:
            tool["flute_length_mm"] = max_depth
    if float(tool.get("overall_length_mm") or 0.0) <= 0:
        tool["overall_length_mm"] = max_depth + 50.0 if max_depth else 0.0
    if float(tool.get("holder_diameter_mm") or 0.0) <= 0:
        tool["holder_diameter_mm"] = (
            max(diameter * 1.5, diameter + 8.0) if diameter else 0.0
        )
    if tool_type == "Boring":
        if float(tool.get("min_bore_mm") or 0.0) <= 0:
            tool["min_bore_mm"] = diameter
        if float(tool.get("max_bore_mm") or 0.0) <= 0:
            tool["max_bore_mm"] = diameter * 10.0 if diameter else 0.0
    else:
        tool.setdefault("min_bore_mm", 0.0)
        tool.setdefault("max_bore_mm", 0.0)
    return tool


def assess_tool_feasibility(
    operation_type,
    feature,
    tool,
    machine=None,
    requested_spindle_rpm=None,
    requested_feed_rate_mm_min=None,
):
    if not tool:
        return {
            "status": "blocked",
            "blocked": True,
            "warning": (
                f"No {operation_type} tool is available in the tool library. "
                "Add and validate the required tool before release."
            ),
            "spindle_rpm": 0,
            "feed_rate_mm_min": 0,
        }

    tool = normalize_tool_profile(tool)
    warnings = []
    blocked = False
    depth = float(feature.get("depth") or 0.0)
    diameter = float(feature.get("diameter") or 0.0)
    tool_diameter = float(tool.get("diameter_mm") or 0.0)
    flute_length = float(tool.get("flute_length_mm") or 0.0)
    holder_diameter = float(tool.get("holder_diameter_mm") or 0.0)

    if operation_type not in ("Face Mill", "Face Mill Rough", "Face Mill Finish",
                              "Spot Drill", "Chamfer"):
        if flute_length > 0 and depth > flute_length:
            blocked = True
            warnings.append(
                f"Feature depth {depth:.1f} mm exceeds "
                f"{tool.get('tool_name', 'selected tool')} flute/reach "
                f"{flute_length:.1f} mm."
            )

    if operation_type == "Drill" and diameter > 0:
        mismatch = abs(tool_diameter - diameter)
        if mismatch >= 0.5:
            blocked = True
            warnings.append(
                f"Drill diameter {tool_diameter:.1f} mm does not match "
                f"feature diameter {diameter:.1f} mm."
            )

    if operation_type == "Boring" and diameter > 0:
        min_bore = float(tool.get("min_bore_mm") or tool_diameter)
        max_bore = float(tool.get("max_bore_mm") or (tool_diameter * 3.0))
        if diameter < min_bore:
            blocked = True
            warnings.append(
                f"Selected boring tool min bore is {min_bore:.1f} mm; "
                f"feature is diameter {diameter:.1f} mm."
            )
        elif max_bore > 0 and diameter > max_bore:
            blocked = True
            warnings.append(
                f"Selected boring tool range is {min_bore:.1f}-{max_bore:.1f} mm; "
                f"feature is diameter {diameter:.1f} mm."
            )

    if operation_type in ("Rough End Mill", "Finish End Mill", "End Mill"):
        feature_type = str(feature.get("feature_type") or "")
        opening_keys = (
            ("width", "length")
            if feature_type in ("Pocket", "Slot", "Step", "Edge Milling")
            else ("diameter", "width", "length")
        )
        openings = [
            float(feature.get(key) or 0.0)
            for key in opening_keys
            if float(feature.get(key) or 0.0) > 0
        ]
        opening = min(openings) if openings else 0.0
        if opening > 0 and tool_diameter > opening:
            blocked = True
            warnings.append(
                f"Tool diameter {tool_diameter:.1f} mm exceeds the smallest "
                f"feature opening {opening:.1f} mm."
            )
        if (
            opening > 0
            and holder_diameter > opening
            and flute_length > 0
            and depth > flute_length * 0.75
        ):
            warnings.append(
                f"Holder diameter {holder_diameter:.1f} mm may not clear the "
                f"{opening:.1f} mm opening at {depth:.1f} mm depth; verify in CAM."
            )

    spindle = int(
        requested_spindle_rpm
        if requested_spindle_rpm is not None
        else (tool.get("default_spindle_rpm") or 0)
    )
    feed = int(
        requested_feed_rate_mm_min
        if requested_feed_rate_mm_min is not None
        else (tool.get("default_feed_rate_mm_min") or 0)
    )
    if machine:
        max_spindle = int(machine.get("max_spindle_rpm") or 0)
        max_feed = int(machine.get("max_feed_rate") or 0)
        if max_spindle > 0 and spindle > max_spindle:
            warnings.append(
                f"Requested spindle {spindle} RPM exceeds machine limit "
                f"{max_spindle} RPM; capped to machine limit."
            )
            spindle = max_spindle
        if max_feed > 0 and feed > max_feed:
            warnings.append(
                f"Requested feed {feed} mm/min exceeds machine limit "
                f"{max_feed} mm/min; capped to machine limit."
            )
            feed = max_feed

    return {
        "status": "blocked" if blocked else ("warning" if warnings else "supported"),
        "blocked": blocked,
        "warning": " ".join(warnings),
        "spindle_rpm": spindle,
        "feed_rate_mm_min": feed,
    }
