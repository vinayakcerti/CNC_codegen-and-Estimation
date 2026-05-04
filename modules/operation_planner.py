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
        {"op": "Rough End Mill", "notes": "Rough slot using multiple depth/radial passes"},
        {"op": "Finish End Mill", "notes": "Finish slot walls and floor"},
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


def estimate_path_length(feature, operation_type, tool=None):
    """Estimate cutting path length in mm.

    These are planning estimates for time/cost approximation — not CAM toolpaths.
    Actual NC programs will differ based on CAM strategy, lead-in/out, and fixturing.

    Args:
        feature       : feature dict from session state
        operation_type: operation string, e.g. "Face Mill", "Rough End Mill"
        tool          : selected tool dict (optional); used where tool diameter
                        affects the number of passes.  Falls back to sensible
                        defaults when None.
    """
    ftype    = feature.get("feature_type", "")
    length   = feature.get("length",   0) or 0
    width    = feature.get("width",    0) or 0
    depth    = feature.get("depth",    0) or 0
    diameter = feature.get("diameter", 0) or 0
    qty      = feature.get("quantity", 1) or 1

    # Tool diameter — used by Face Mill and End Mill formulas below.
    tool_dia = (tool or {}).get("diameter_mm") or 0

    # ── Holes / boring ───────────────────────────────────────────────────────
    if ftype in ("Hole", "Large Hole / Boring"):
        if operation_type == "Spot Drill":
            return 5.0 * qty          # constant centre-drill engagement
        return depth * qty             # drill/bore travel = hole depth

    # ── Pocket ───────────────────────────────────────────────────────────────
    if ftype == "Pocket":
        if length > 0 and width > 0:
            passes = math.ceil(depth / 3.0)
            path_per_pass = (length * width) / 8.0
            return path_per_pass * passes * qty
        return 100.0 * qty

    # ── Slot ─────────────────────────────────────────────────────────────────
    if ftype == "Slot":
        slot_len = length or 50

        if operation_type == "Rough End Mill":
            # Raster estimate: depth passes × radial passes × slot length.
            # DOC = 0.5 × D (axial),  stepover = 0.6 × D (radial).
            dia = tool_dia if tool_dia > 0 else 12.0   # default: T7 12 mm
            stepdown      = dia * 0.5
            stepover      = dia * 0.6
            depth_passes  = max(1, math.ceil(depth  / stepdown))  if depth  > 0 else 1
            radial_passes = max(1, math.ceil(width  / stepover))  if width  > 0 else 1
            return depth_passes * radial_passes * slot_len * qty

        if operation_type == "Finish End Mill":
            # Two finishing passes — one along each slot wall.
            return 2 * slot_len * qty

        # Fallback for any other op type on a slot feature
        return slot_len * qty

    # ── Face Milling ─────────────────────────────────────────────────────────
    if ftype == "Face Milling":
        if length > 0 and width > 0:
            # Raster estimate: passes across the face width, each pass = face length
            # plus one tool-diameter approach/exit.
            # Stepover = 0.75 × D (standard face milling overlap).
            dia      = tool_dia if tool_dia > 0 else 50.0   # default: T8 50 mm
            stepover = dia * 0.75
            passes   = max(1, math.ceil(width / stepover))
            return passes * (length + dia) * qty
        return 300.0

    # ── Outer Profile ────────────────────────────────────────────────────────
    if ftype == "Outer Profile":
        if length > 0 and width > 0:
            return (length + width) * 2 * qty
        return 200.0 * qty

    # ── Chamfer ──────────────────────────────────────────────────────────────
    if ftype == "Chamfer":
        return (diameter or 10) * 3.14 * qty

    return 50.0 * qty


def _context_note(ftype, feature_name, diameter, op_type):
    """Return an additional note string for a specific feature/operation context.

    Returns an empty string when no extra note applies.  Callers append this to
    the base rule note with a single space separator.
    """
    fname_lower = (feature_name or "").lower()

    if ftype == "Face Milling":
        if "bottom" in fname_lower:
            return "Setup 2 required — flip part before machining this face."
        if "top" in fname_lower:
            return "Primary setup facing operation."

    if ftype == "Large Hole / Boring" and op_type == "Boring" and (diameter or 0) >= 25:
        return (
            "Verify boring tool reach and minimum bore capability "
            f"for final diameter Ø{diameter:.1f} mm."
        )

    if ftype == "Slot":
        if op_type == "Rough End Mill":
            return "Use multiple depth passes and radial stepovers."
        if op_type == "Finish End Mill":
            return "Finish slot walls and floor after roughing."

    return ""


def _sequence_key(op):
    """Return a sort key for practical machining order.

    Planning-level sequence heuristic — groups ops by phase so the operator
    completes Setup 1 before any flip is required.  Not a substitute for full
    CAM setup planning.
    """
    ftype  = op.get("feature_type", "")
    fname  = op.get("feature_name", "").lower()
    op_type = op.get("operation_type", "")

    # Bottom face milling needs a flip — always goes last (Setup 2)
    if ftype == "Face Milling" and "bottom" in fname:
        return 6

    if ftype == "Face Milling":                          # top / primary facing first
        return 0
    if op_type in ("Spot Drill", "Pilot Drill", "Drill"):
        return 1
    if op_type == "Boring":
        return 2
    if op_type == "Rough End Mill":
        return 3
    if op_type == "Finish End Mill":
        return 4
    return 5                                             # chamfer, profile, other


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
            path_len = estimate_path_length(feature, op_type, tool)

            extra = _context_note(
                ftype,
                feature.get("feature_name", ""),
                feature.get("diameter") or 0,
                op_type,
            )
            note = rule["notes"] + (" | " + extra if extra else "")

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
                "notes": note,
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

    # Re-sequence into practical machining order, then renumber from 1.
    operations.sort(key=_sequence_key)
    for i, op in enumerate(operations, start=1):
        op["op_num"] = i

    return operations
