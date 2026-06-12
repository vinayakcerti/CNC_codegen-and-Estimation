import math
import hashlib
import json
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
    "Step": [
        {"op": "Rough End Mill", "notes": "Rough step floor and shoulder"},
        {"op": "Finish End Mill", "notes": "Finish step floor", "feature_name_suffix": " - floor finish"},
        {"op": "Finish End Mill", "notes": "Finish shoulder wall", "feature_name_suffix": " - wall finish"},
    ],
    "Face Milling": [
        {"op": "Face Mill", "notes": "Face mill stock surface"},
    ],
    "Edge Milling": [
        {"op": "End Mill", "notes": "Mill side/edge stock allowance"},
    ],
    "Outer Profile": [
        {"op": "End Mill", "notes": "Profile outer contour"},
    ],
    "Chamfer": [
        {"op": "Chamfer", "notes": "Chamfer top edges"},
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

    # ── Step / shoulder ──────────────────────────────────────────────────────
    if ftype == "Step":
        step_len = length or 50

        if operation_type == "Rough End Mill":
            # Raster estimate: depth passes × radial passes × step length.
            # DOC = 0.5 × D (axial),  stepover = 0.6 × D (radial).
            dia           = tool_dia if tool_dia > 0 else 12.0
            stepdown      = dia * 0.5
            stepover      = dia * 0.6
            depth_passes  = max(1, math.ceil(depth / stepdown)) if depth > 0 else 1
            radial_passes = max(1, math.ceil(width / stepover)) if width > 0 else 1
            return depth_passes * radial_passes * step_len * qty

        if operation_type == "Finish End Mill":
            # Step floor and shoulder wall finish are planned as separate ops.
            return step_len * qty

        return step_len * qty

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

    if ftype == "Edge Milling":
        side_length = length or 50
        axial_height = width or depth or 10
        dia = tool_dia if tool_dia > 0 else 12.0
        stepdown = max(dia * 0.75, 1.0)
        depth_passes = max(1, math.ceil(axial_height / stepdown))
        return side_length * depth_passes * qty

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
            return (
                "Setup 2 required — flip part before machining this face. "
                "Verify workholding and fixture clearance for second setup."
            )
        if "top" in fname_lower:
            return "Primary setup facing operation."

    if ftype == "Edge Milling":
        return (
            "Derived from raw-stock side allowance. Verify side access, "
            "workholding clearance, and datum before programming."
        )

    if ftype == "Large Hole / Boring" and op_type == "Boring":
        dia_note = f" Final diameter: Ø{diameter:.1f} mm." if (diameter or 0) > 0 else ""
        return (
            "Verify boring tool minimum bore, maximum bore, reach, and rigidity "
            f"before machining.{dia_note}"
        )

    if ftype == "Pocket":
        if op_type == "Rough End Mill":
            return (
                "Rough pocket using multiple depth/radial passes. "
                "Verify tool diameter and corner radius suitability."
            )
        if op_type == "Finish End Mill":
            return (
                "Finishing pass cleans pocket walls and floor. "
                "Verify tool flute length >= pocket depth."
            )

    if ftype == "Slot":
        if op_type == "Rough End Mill":
            return (
                "Use multiple depth passes and radial stepovers. "
                "Verify tool diameter <= slot width and corner radius suitability."
            )
        if op_type == "Finish End Mill":
            return (
                "Finish slot walls and floor. "
                "Verify tool flute length >= slot depth and corner radius suitability."
            )

    if ftype == "Step":
        if op_type == "Rough End Mill":
            return "Rough lower step level using multiple depth/radial passes."
        if op_type == "Finish End Mill":
            return "Verify tool reach and flute length for shoulder wall finish pass."

    if ftype == "Chamfer":
        return (
            "Use chamfer mill / countersink-style tool. "
            "Verify chamfer size and edge selection before machining."
        )

    return ""


def _setup_sort_rank(label):
    return {
        "Top": 0,
        "Front": 1,
        "Right": 2,
        "Back": 3,
        "Left": 4,
        "Unknown": 5,
        "Bottom": 6,
    }.get(label or "Unknown", 5)


def setup_labels_for_operations(operations):
    labels = {
        (op.get("setup_label") or "Unknown")
        for op in operations
        if op.get("setup_label") is not None
    }
    return sorted(labels, key=_setup_sort_rank)


def is_secondary_setup_operation(op):
    label = op.get("setup_label") or "Unknown"
    if label not in ("Top", "Unknown"):
        return True
    return (
        op.get("feature_type") == "Face Milling"
        and "bottom" in op.get("feature_name", "").lower()
    )


def secondary_setup_labels(operations):
    return [
        label
        for label in setup_labels_for_operations(operations)
        if label not in ("Top", "Unknown")
    ]


def _tool_capability_warning(op_type, feature, tool):
    """Return a planning warning when selected tool capability looks doubtful."""
    diameter = float(feature.get("diameter", 0) or 0)
    depth = float(feature.get("depth", 0) or 0)
    tool_dia = float(tool.get("diameter_mm", 0) or 0)
    max_depth = float(tool.get("max_depth_mm", 0) or 0)

    warnings = []
    if max_depth > 0 and depth > max_depth:
        warnings.append(
            f"WARNING: feature depth {depth:.1f} mm exceeds "
            f"{tool.get('tool_name', 'selected tool')} reach {max_depth:.1f} mm."
        )

    if op_type == "Boring" and diameter > 0 and tool_dia > 0:
        # The default tool library only has nominal diameter and reach. Use a
        # conservative planning envelope so undersized/oversized bores are not
        # silently treated as ready for CAM.
        min_bore = tool_dia
        max_bore = tool_dia * 3.0
        if diameter < min_bore:
            warnings.append(
                f"WARNING: selected boring tool min bore is about {min_bore:.1f} mm; "
                f"feature is Ø{diameter:.1f} mm."
            )
        elif diameter > max_bore:
            warnings.append(
                f"WARNING: selected boring tool planning range is about "
                f"Ø{min_bore:.1f}-Ø{max_bore:.1f} mm; feature is Ø{diameter:.1f} mm."
            )

    return " ".join(warnings)


def _sequence_key(op):
    """Return a sort key for practical machining order.

    Planning-level sequence heuristic — groups ops by phase so the operator
    completes Setup 1 before any flip is required.  Not a substitute for full
    CAM setup planning.
    """
    ftype = op.get("feature_type", "")
    fname = op.get("feature_name", "").lower()
    op_type = op.get("operation_type", "")
    setup_label = op.get("setup_label", "Unknown")

    # Bottom face milling needs a flip — always goes last (Setup 2)
    if setup_label == "Bottom" or (ftype == "Face Milling" and "bottom" in fname):
        return (6, _setup_sort_rank(setup_label))

    if ftype == "Face Milling":                          # top / primary facing first
        return (0, _setup_sort_rank(setup_label))
    if ftype == "Edge Milling":
        return (1, _setup_sort_rank(setup_label))
    if op_type in ("Spot Drill", "Pilot Drill", "Drill"):
        return (2, _setup_sort_rank(setup_label))
    if op_type == "Boring":
        return (3, _setup_sort_rank(setup_label))
    if op_type == "Rough End Mill":
        return (4, _setup_sort_rank(setup_label))
    if op_type == "Finish End Mill":
        return (5, _setup_sort_rank(setup_label))
    return (6, _setup_sort_rank(setup_label))


def _operation_signature(feature, op_type, operation_variant=""):
    """Stable key used to skip exact duplicate operation inputs."""
    physical_feature_id = feature.get("physical_feature_id")
    if physical_feature_id:
        return (
            "physical",
            str(physical_feature_id),
            str(op_type).strip().lower(),
            str(operation_variant).strip().lower(),
        )
    return (
        "geometry",
        str(feature.get("feature_type", "")).strip().lower(),
        str(feature.get("feature_name", "")).strip().lower(),
        str(op_type).strip().lower(),
        str(operation_variant).strip().lower(),
        str(feature.get("setup_label", "Unknown")).strip().lower(),
        round(float(feature.get("x_pos", 0) or 0), 3),
        round(float(feature.get("y_pos", 0) or 0), 3),
        round(float(feature.get("diameter", 0) or 0), 3),
        round(float(feature.get("length", 0) or 0), 3),
        round(float(feature.get("width", 0) or 0), 3),
        round(float(feature.get("depth", 0) or 0), 3),
    )


def _operation_id(operation_signature):
    digest = hashlib.sha256(
        json.dumps(
            operation_signature,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return f"OP-{digest[:16]}"


def _feature_sort_key(feature):
    return (
        int(feature.get("priority", 99) or 99),
        _setup_sort_rank(feature.get("setup_label", "Unknown")),
        str(feature.get("feature_type", "")).strip().lower(),
        round(float(feature.get("x_pos", 0) or 0), 3),
        round(float(feature.get("y_pos", 0) or 0), 3),
        round(float(feature.get("depth", 0) or 0), 3),
        str(feature.get("physical_feature_id") or feature.get("feature_name") or ""),
    )


def plan_operations(features, tools, material):
    """Generate operation plan from features."""
    operations = []
    seen_operations = set()
    op_num = 1

    for feature in sorted(features, key=_feature_sort_key):
        ftype = feature["feature_type"]
        rules = OPERATION_RULES.get(ftype, [{"op": "End Mill", "notes": "General machining"}])

        for rule in rules:
            op_type = rule["op"]
            op_feature_name = feature["feature_name"] + rule.get("feature_name_suffix", "")
            op_sig = _operation_signature(feature, op_type, rule.get("feature_name_suffix", ""))
            if op_sig in seen_operations:
                continue
            seen_operations.add(op_sig)
            tool = select_tool_for_operation(op_type, feature, tools)
            spindle, feed = get_spindle_and_feed(tool, material)
            path_len = estimate_path_length(feature, op_type, tool)
            tool_warning = _tool_capability_warning(op_type, feature, tool)

            _fname_lower = feature.get("feature_name", "").lower()
            _is_through_pocket = (
                ftype == "Pocket"
                and ("through pocket" in _fname_lower or "window" in _fname_lower)
            )

            if _is_through_pocket and op_type == "Rough End Mill":
                note = "Rough through pocket/window using multiple depth/radial passes"
            elif _is_through_pocket and op_type == "Finish End Mill":
                note = "Finish internal walls of through pocket/window"
            else:
                extra = _context_note(
                    ftype,
                    feature.get("feature_name", ""),
                    feature.get("diameter") or 0,
                    op_type,
                )
                note = rule["notes"] + (" | " + extra if extra else "")
            if tool_warning:
                note = note + " | " + tool_warning

            operations.append({
                "operation_id": _operation_id(op_sig),
                "op_num": op_num,
                "source_candidate_id": feature.get("source_candidate_id", ""),
                "physical_feature_id": feature.get("physical_feature_id", ""),
                "feature_name": op_feature_name,
                "feature_type": ftype,
                "setup_label": feature.get("setup_label", "Unknown"),
                "operation_type": op_type,
                "tool_name": tool["tool_name"],
                "tool_number": tool["tool_number"],
                "spindle_rpm": spindle,
                "feed_rate_mm_min": feed,
                "est_path_length_mm": round(path_len, 1),
                "tool_warning": tool_warning,
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
