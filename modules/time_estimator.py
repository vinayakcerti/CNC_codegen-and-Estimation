def estimate_time(operations, machine, material, features):
    """Estimate cutting time, rapid time, tool change time and effort."""
    safety_factor = material.get("safety_factor", 1.3)
    rapid_feed = machine.get("rapid_feed_rate", 10000)
    tc_time_s = machine.get("tool_change_time_s", 8)
    setup_min = machine.get("setup_time_min", 20)

    cutting_time_min = 0.0
    for op in operations:
        feed = op.get("feed_rate_mm_min", 200)
        path = op.get("est_path_length_mm", 50)
        if feed > 0:
            cutting_time_min += (path / feed)

    cutting_time_min *= safety_factor

    rapid_distance = 0.0
    for feature in features:
        x = feature.get("x_pos", 0) or 0
        y = feature.get("y_pos", 0) or 0
        rapid_distance += (x ** 2 + y ** 2) ** 0.5

    rapid_distance = max(rapid_distance, 200.0)
    # mm / (mm/min) = minutes — no extra multiplier needed.
    rapid_time_min = rapid_distance / rapid_feed if rapid_feed > 0 else 0.0

    tool_numbers = list({op["tool_number"] for op in operations})
    num_tool_changes = max(len(tool_numbers) - 1, 0)
    tc_time_min = (num_tool_changes * tc_time_s) / 60.0

    total_machine_time_min = setup_min + cutting_time_min + rapid_time_min + tc_time_min

    num_operations = len(operations)
    time_factor = min(total_machine_time_min / 30.0, 3.0)
    complexity_factor = len(set(op["feature_type"] for op in operations)) * 0.5
    effort_score = num_operations + num_tool_changes + time_factor + complexity_factor

    if effort_score < 8:
        effort_label = "Low"
    elif effort_score < 18:
        effort_label = "Medium"
    else:
        effort_label = "High"

    operator_effort_min = setup_min + (total_machine_time_min * 0.3)

    return {
        "cutting_time_min": round(cutting_time_min, 2),
        "rapid_time_min": round(rapid_time_min, 2),
        "tool_change_time_min": round(tc_time_min, 2),
        "setup_time_min": round(setup_min, 2),
        "total_machine_time_min": round(total_machine_time_min, 2),
        "operator_effort_min": round(operator_effort_min, 2),
        "num_tool_changes": num_tool_changes,
        "num_operations": num_operations,
        "effort_score_value": round(effort_score, 2),
        "effort_label": effort_label,
    }
