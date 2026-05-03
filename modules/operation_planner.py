import math
from modules.tool_selector import select_tool_for_operation, get_spindle_and_feed


OPERATION_RULES = {
    "Hole": [
        {"op": "Spot Drill", "notes": "Centre drill before drilling"},
        {"op": "Drill", "notes": "Drill to depth"},
    ],
    "Large Hole / Boring": [
        {"op": "Pilot Drill", "notes": "Pilot hole first"},
        {"op": "Boring", "notes": "Bore to final diameter"},
    ],
    "Pocket": [
        {"op": "Rough End Mill", "notes": "Rough pocket clearance"},
        {"op": "Finish End Mill", "notes": "Finish pocket walls and floor"},
    ],
    "Slot": [
        {"op": "End Mill", "notes": "Full slot cut"},
    ],
    "Face Milling": [
        {"op": "Face Mill", "notes": "Face mill stock surface"},
    ],
    "Outer Profile": [
        {"op": "End Mill", "notes": "Profile outer contour"},
    ],
    "Chamfer": [
        {"op": "Chamfer", "notes": "Chamfer edges"},
    ],
}


def estimate_path_length(feature, operation_type):
    """Estimate cutting path length in mm."""
    ftype = feature.get("feature_type", "")
    length = feature.get("length", 0) or 0
    width = feature.get("width", 0) or 0
    depth = feature.get("depth", 0) or 0
    diameter = feature.get("diameter", 0) or 0
    qty = feature.get("quantity", 1) or 1

    if ftype in ("Hole", "Large Hole / Boring"):
        if operation_type in ("Spot Drill",):
            return 5.0 * qty
        return depth * qty

    if ftype == "Pocket":
        if length > 0 and width > 0:
            passes = math.ceil(depth / 3.0)
            path_per_pass = (length * width) / 8.0
            return path_per_pass * passes * qty
        return 100.0 * qty

    if ftype == "Slot":
        return (length or 50) * qty

    if ftype == "Face Milling":
        if length > 0 and width > 0:
            return (length + width) * 2
        return 300.0

    if ftype == "Outer Profile":
        if length > 0 and width > 0:
            return (length + width) * 2 * qty
        return 200.0 * qty

    if ftype == "Chamfer":
        return (diameter or 10) * 3.14 * qty

    return 50.0 * qty


def plan_operations(features, tools, material):
    """Generate operation plan from features."""
    operations = []
    op_num = 1

    for feature in sorted(features, key=lambda x: x.get("priority", 99)):
        ftype = feature["feature_type"]
        rules = OPERATION_RULES.get(ftype, [{"op": "End Mill", "notes": "General machining"}])

        for rule in rules:
            op_type = rule["op"]
            tool = select_tool_for_operation(op_type, feature, tools)
            spindle, feed = get_spindle_and_feed(tool, material)
            path_len = estimate_path_length(feature, op_type)

            operations.append({
                "op_num": op_num,
                "feature_name": feature["feature_name"],
                "feature_type": ftype,
                "operation_type": op_type,
                "tool_name": tool["tool_name"],
                "tool_number": tool["tool_number"],
                "spindle_rpm": spindle,
                "feed_rate_mm_min": feed,
                "est_path_length_mm": round(path_len, 1),
                "notes": rule["notes"],
                # Carry feature geometry for G-code generation
                "_x_pos": float(feature.get("x_pos", 0) or 0),
                "_y_pos": float(feature.get("y_pos", 0) or 0),
                "_depth": float(feature.get("depth", 5) or 5),
                "_diameter": float(feature.get("diameter", 0) or 0),
                "_length": float(feature.get("length", 0) or 0),
                "_width": float(feature.get("width", 0) or 0),
                "_quantity": int(feature.get("quantity", 1) or 1),
            })
            op_num += 1

    return operations
