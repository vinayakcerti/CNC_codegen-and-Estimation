def _operation_identity(operation):
    operation_id = operation.get("operation_id")
    if operation_id:
        return ("operation_id", str(operation_id))
    return (
        str(operation.get("feature_name") or "").strip().lower(),
        str(operation.get("operation_type") or "").strip().lower(),
        str(operation.get("setup_label") or "").strip().lower(),
        int(operation.get("tool_number") or 0),
        round(float(operation.get("_x_pos") or 0.0), 3),
        round(float(operation.get("_y_pos") or 0.0), 3),
        round(float(operation.get("_depth") or 0.0), 3),
    )


def _unique_operations(operations):
    unique = []
    seen = set()
    for operation in operations or []:
        identity = _operation_identity(operation)
        if identity in seen:
            continue
        seen.add(identity)
        unique.append(operation)
    return unique


def _unique_feature_positions(operations):
    positions = []
    seen = set()
    for operation in operations:
        feature_identity = operation.get("physical_feature_id") or (
            str(operation.get("feature_name") or "").strip().lower(),
            str(operation.get("setup_label") or "").strip().lower(),
            round(float(operation.get("_x_pos") or 0.0), 3),
            round(float(operation.get("_y_pos") or 0.0), 3),
        )
        if feature_identity in seen:
            continue
        seen.add(feature_identity)
        positions.append((
            float(operation.get("_x_pos") or 0.0),
            float(operation.get("_y_pos") or 0.0),
        ))
    return positions


def estimate_time(operations, machine, material, features):
    """Estimate cutting time, rapid time, tool change time and effort."""
    operations = _unique_operations(operations)
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
    for x, y in _unique_feature_positions(operations):
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


def estimate_time_per_operation(operations, machine, material):
    """Per-operation cycle-time rows for the estimate breakdown table.

    Additive companion to estimate_time(): same feed/path/safety-factor
    model, itemised per operation so a quote can show where the minutes go.
    Returns a list of dicts sorted by op_num.
    """
    operations = _unique_operations(operations)
    safety_factor = material.get("safety_factor", 1.3)
    rows = []
    for op in operations:
        feed = op.get("feed_rate_mm_min", 200)
        path = op.get("est_path_length_mm", 50)
        cut_min = (path / feed) * safety_factor if feed > 0 else 0.0
        rows.append({
            "op_num": op.get("op_num", 0),
            "operation": op.get("operation_type", "—"),
            "feature": op.get("feature_name", "—"),
            "setup": op.get("setup_label", "—"),
            "tool": op.get("tool_name", "—"),
            "spindle_rpm": op.get("spindle_rpm", 0),
            "feed_mm_min": feed,
            "path_mm": path,
            "cut_min": round(cut_min, 2),
            "blocked": bool(op.get("planning_blocked")),
        })
    rows.sort(key=lambda r: r["op_num"])
    return rows
