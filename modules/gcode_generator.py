import math


def _format_coord(v):
    return f"{v:.3f}"


def generate_gcode(operations, machine, stock):
    """Generate draft Fanuc-style G-code / M-code program using actual feature geometry."""
    controller = machine.get("controller", "Fanuc")
    machine_name = machine.get("machine_name", "CNC Machine")
    stock_x = stock.get("length", 100)
    stock_y = stock.get("width", 100)
    stock_z = stock.get("height", 50)
    safe_z = 50.0
    clearance_z = 5.0
    retract_z = 2.0

    lines = []

    lines.append("; ============================================================")
    lines.append("; DO NOT RUN THIS PROGRAM DIRECTLY ON A MACHINE.")
    lines.append("; THIS IS DRAFT PLANNING CODE ONLY.")
    lines.append("; VERIFY IN CAM/SIMULATOR AND BY A QUALIFIED CNC PROGRAMMER")
    lines.append("; BEFORE RUNNING ON ANY REAL MACHINE.")
    lines.append("; Tool numbers, offsets, speeds, and feeds MUST be verified.")
    lines.append("; ============================================================")
    lines.append(";")
    lines.append(f"; Machine   : {machine_name}  ({controller})")
    lines.append(f"; Stock     : {stock_x} x {stock_y} x {stock_z} mm")
    lines.append(f"; Operations: {len(operations)}")
    lines.append(";")
    lines.append("O0001  (CNC PROCESS PLANNER - DRAFT PROGRAM)")
    lines.append(";")
    lines.append("; --- SAFETY SETUP ---")
    lines.append("G21        (Metric mode)")
    lines.append("G17        (XY plane selection)")
    lines.append("G90        (Absolute positioning)")
    lines.append("G94        (Feed per minute)")
    lines.append("G54        (Work coordinate system)")
    lines.append("G49        (Cancel tool length offset)")
    lines.append("G80        (Cancel canned cycles)")
    lines.append("G40        (Cancel cutter comp)")
    lines.append(f"G0 Z{_format_coord(safe_z)}  (Move to safe Z)")
    lines.append(";")

    current_tool = None
    _announced_setup_labels = set()
    _setup2_announced = False

    for op in operations:
        tool_num = op["tool_number"]
        tool_name = op["tool_name"]
        spindle = op["spindle_rpm"]
        feed = op["feed_rate_mm_min"]
        op_type = op["operation_type"]
        feature_name = op["feature_name"]

        # Real geometry from feature
        x = op.get("_x_pos", 0.0)
        y = op.get("_y_pos", 0.0)
        depth = op.get("_depth", 5.0)
        diameter = op.get("_diameter", 0.0)
        length = op.get("_length", 0.0)
        width = op.get("_width", 0.0)
        qty = op.get("_quantity", 1)

        setup_label = op.get("setup_label") or "Unknown"
        if setup_label not in ("Top", "Unknown", "Bottom") and setup_label not in _announced_setup_labels:
            lines.append(";")
            lines.append("; ============================================================")
            lines.append(f"; ADDITIONAL SETUP - {setup_label.upper()} ORIENTATION")
            lines.append("; Stop here. Re-fixture/re-orient the part as required.")
            lines.append("; Re-indicate datums and verify workholding and fixture clearance.")
            lines.append("; ============================================================")
            lines.append(";")
            _announced_setup_labels.add(setup_label)

        # ── Setup 2 separator ──────────────────────────────────────────
        if (op_type == "Face Mill"
                and "bottom" in feature_name.lower()
                and not _setup2_announced):
            lines.append(";")
            lines.append("; ============================================================")
            lines.append("; SETUP 2 — FLIP PART BEFORE CONTINUING")
            lines.append("; Remove from fixture. Flip part. Re-indicate and re-zero Z.")
            lines.append("; Verify workholding and fixture clearance for second setup.")
            lines.append("; ============================================================")
            lines.append(";")
            _setup2_announced = True

        # ── Tool change block ───────────────────────────────────────────
        if tool_num != current_tool:
            if current_tool is not None:
                lines.append("; --- END OF PREVIOUS TOOL ---")
                lines.append("M9         (Coolant OFF)")
                lines.append("M5         (Spindle STOP)")
                lines.append(f"G91 G28 Z0 (Return Z to home)")
                lines.append(";")

            lines.append(f"; === TOOL CHANGE: T{tool_num:02d} - {tool_name} ===")
            lines.append(f"T{tool_num:02d} M6     (Tool change: {tool_name})")
            lines.append(f"G43 H{tool_num:02d}    (Tool length offset T{tool_num:02d})")
            lines.append(f"M3 S{spindle}   (Spindle ON CW {spindle} RPM)")
            lines.append("M8         (Coolant ON)")
            lines.append(f"G0 Z{_format_coord(safe_z)}  (Safe Z)")
            lines.append(";")
            current_tool = tool_num

        lines.append(f"; -- [{op['op_num']:02d}] {feature_name} : {op_type} --")

        # ── Drilling / Spot Drill ───────────────────────────────────────
        if op_type == "Spot Drill":
            for i in range(qty):
                xi = x + i * max(diameter + 5, 10)
                lines.append(f"G0 X{_format_coord(xi)} Y{_format_coord(y)}  (Rapid to hole {i+1})")
                lines.append(f"G0 Z{_format_coord(clearance_z)}  (Clearance Z)")
                lines.append(f"G81 X{_format_coord(xi)} Y{_format_coord(y)} Z-3.000 R{_format_coord(retract_z)} F{feed}  (Spot drill)")
                lines.append("G80            (Cancel cycle)")

        elif op_type in ("Drill", "Pilot Drill"):
            for i in range(qty):
                xi = x + i * max(diameter + 5, 10)
                lines.append(f"G0 X{_format_coord(xi)} Y{_format_coord(y)}  (Rapid to hole {i+1})")
                lines.append(f"G0 Z{_format_coord(clearance_z)}  (Clearance Z)")
                if depth > 3 * (diameter or 10):
                    # Deep hole — use peck cycle
                    peck = round(diameter * 1.5, 1) if diameter > 0 else 5.0
                    lines.append(f"G83 X{_format_coord(xi)} Y{_format_coord(y)} Z-{_format_coord(depth)} R{_format_coord(retract_z)} Q{_format_coord(peck)} F{feed}  (Peck drill — deep)")
                else:
                    lines.append(f"G81 X{_format_coord(xi)} Y{_format_coord(y)} Z-{_format_coord(depth)} R{_format_coord(retract_z)} F{feed}  (Drill cycle)")
                lines.append("G80            (Cancel cycle)")

        # ── Boring ──────────────────────────────────────────────────────
        elif op_type == "Boring":
            lines.append(f"G0 X{_format_coord(x)} Y{_format_coord(y)}  (Rapid to bore centre)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Clearance Z)")
            lines.append(f"G76 X{_format_coord(x)} Y{_format_coord(y)} Z-{_format_coord(depth)} R{_format_coord(retract_z)} Q0.500 F{feed}  (Fine boring cycle)")
            lines.append("G80            (Cancel cycle)")

        # ── Pocket / Slot roughing and finishing ─────────────────────────
        elif op_type in ("Rough End Mill", "Finish End Mill"):
            l = length if length > 0 else 20.0
            w = width if width > 0 else 20.0
            stepdown = 3.0 if op_type == "Rough End Mill" else depth
            passes = max(1, math.ceil(depth / stepdown))
            stepover_count = max(1, math.ceil(w / 8.0))

            lines.append(f"G0 X{_format_coord(x)} Y{_format_coord(y)}  (Rapid to pocket start)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Clearance Z)")

            current_depth = 0.0
            for p in range(passes):
                current_depth = min((p + 1) * stepdown, depth)
                plunge_feed = max(int(feed * 0.4), 50)
                lines.append(f"G1 Z-{_format_coord(current_depth)} F{plunge_feed}  (Plunge pass {p+1}/{passes})")
                for s in range(stepover_count):
                    yo = y + s * (w / stepover_count)
                    if s % 2 == 0:
                        lines.append(f"G1 X{_format_coord(x + l)} Y{_format_coord(yo)} F{feed}  (Pass {p+1} row {s+1} fwd)")
                    else:
                        lines.append(f"G1 X{_format_coord(x)} Y{_format_coord(yo)} F{feed}  (Pass {p+1} row {s+1} back)")

            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Retract)")

        # ── General End Mill (Slot / Profile) ───────────────────────────
        elif op_type == "End Mill":
            l = length if length > 0 else 50.0
            w = width if width > 0 else 0.0
            plunge_feed = max(int(feed * 0.4), 50)
            lines.append(f"G0 X{_format_coord(x)} Y{_format_coord(y)}  (Rapid to start)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Clearance Z)")
            lines.append(f"G1 Z-{_format_coord(depth)} F{plunge_feed}  (Plunge)")
            lines.append(f"G1 X{_format_coord(x + l)} F{feed}  (Cut along X)")
            if w > 0:
                lines.append(f"G1 Y{_format_coord(y + w)} F{feed}  (Cut along Y)")
                lines.append(f"G1 X{_format_coord(x)} F{feed}  (Return X)")
                lines.append(f"G1 Y{_format_coord(y)} F{feed}  (Close profile)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Retract)")

        # ── Face Milling ─────────────────────────────────────────────────
        elif op_type == "Face Mill":
            sx = stock_x
            sy = stock_y
            step_y = 40.0
            rows = max(1, math.ceil(sy / step_y))
            plunge_feed = max(int(feed * 0.4), 50)
            lines.append(f"G0 X-10.000 Y{_format_coord(y)}  (Rapid to face mill start)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Clearance Z)")
            lines.append(f"G1 Z-{_format_coord(depth)} F{plunge_feed}  (Engage face mill)")
            for r in range(rows):
                y_row = y + r * step_y
                if r % 2 == 0:
                    lines.append(f"G1 X{_format_coord(sx + 10)} Y{_format_coord(y_row)} F{feed}  (Face row {r+1} fwd)")
                else:
                    lines.append(f"G1 X-10.000 Y{_format_coord(y_row)} F{feed}  (Face row {r+1} back)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Retract)")

        # ── Chamfer ──────────────────────────────────────────────────────
        elif op_type == "Chamfer":
            dia = diameter if diameter > 0 else 10.0
            plunge_feed = max(int(feed * 0.4), 50)
            lines.append(f"G0 X{_format_coord(x)} Y{_format_coord(y)}  (Rapid to chamfer start)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Clearance Z)")
            lines.append(f"G1 Z-{_format_coord(depth)} F{plunge_feed}  (Plunge chamfer)")
            # Circular chamfer move
            r = dia / 2
            lines.append(f"G2 X{_format_coord(x)} Y{_format_coord(y)} I{_format_coord(r)} J0.000 F{feed}  (Chamfer arc)")
            lines.append(f"G0 Z{_format_coord(clearance_z)}  (Retract)")

        lines.append(";")

    # ── End of program ──────────────────────────────────────────────────
    lines.append("; --- PROGRAM END ---")
    lines.append("M9         (Coolant OFF)")
    lines.append("M5         (Spindle STOP)")
    lines.append("G91 G28 Z0 (Return Z to home)")
    lines.append("G91 G28 X0 Y0 (Return XY to home)")
    lines.append("G90        (Back to absolute)")
    lines.append("M30        (End of program)")
    lines.append("%")

    return "\n".join(lines)
