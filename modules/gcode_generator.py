import math

from modules.turning_planner import TURNING_TOOLS, _LATHE_MAX_RPM


def _format_coord(v):
    return f"{v:.3f}"


def _parse_feature_dims(feature_name):
    """Pull (diameter_mm, length_mm) out of a turning_planner feature label.

    turning_planner.py names turned candidates "<label> Øxx.xx mm x yy.y mm"
    (see step_parser.py Section 19-2/19-3 candidate naming). Returns
    (None, None) for either value the string doesn't carry rather than
    guessing — callers fall back to part-envelope values explicitly so the
    "no data" case is never silently indistinguishable from "real zero".
    """
    dia = length = None
    if "Ø" in feature_name:
        try:
            after = feature_name.split("Ø", 1)[1]
            dia = float(after.split(" ")[0].replace("mm", "").strip())
        except (ValueError, IndexError):
            dia = None
    if "×" in feature_name:
        try:
            after = feature_name.rsplit("×", 1)[1]
            length = float(after.replace("mm", "").replace("wide", "").strip())
        except (ValueError, IndexError):
            length = None
    return dia, length


def _turning_tool_slot(tool_name):
    """Map a turning tool's display name to a numeric turret station.

    modules/turning_planner.py TURNING_TOOLS is fixed and ordered (library
    slots L1..L6, used as internal ids); op dicts carry only the human-
    readable tool_name string. G-code T-addresses must be numeric (Fanuc
    lathe convention T<station><offset>, e.g. T0101), so this returns the
    tool's 1-based position in TURNING_TOOLS as the station number — NOT
    the "L#" label, which is not valid inside a T-address.
    Falls back to station 0 (UNRESOLVED) for anything not in the library
    rather than guessing a number.
    """
    for _idx, _t in enumerate(TURNING_TOOLS, start=1):
        if _t["tool_name"] == tool_name:
            return _idx, _t
    return 0, None


def generate_turning_gcode(turning_ops, machine, part_length_mm=0.0,
                            part_max_od_mm=0.0):
    """Generate draft Fanuc-style lathe G-code from a turning_planner.py plan.

    Consumes the op dicts produced by modules.turning_planner.plan_turning_
    operations() directly (op, feature, tool, rpm, feed_mm_rev, path_mm,
    cut_min, setup, notes) — these already carry a real Vc/feed-per-rev
    derived rpm and feed, so this function does not invent any cutting
    parameters; it only turns them into move blocks.

    Lathe programming conventions used (distinct from the mill generator):
      - G18 XZ plane (vs G17 XY on the mill)
      - X programmed on DIAMETER (lathe convention), Z along the turning
        axis from a Z0 datum at the finished right-face of the part
      - G97 constant-RPM mode + G99 feed-per-rev — the planner already
        resolves a single representative rpm per op (surface-speed-derived,
        capped at the machine's max rpm), so G97 with that value is the
        honest choice: it doesn't require the controller to hold constant
        surface speed across a diameter change this function has no
        per-pass profile for.

    NOTE ON FIDELITY: turning_planner op dicts store path_mm/cut_min as
    totals across all passes for an operation (e.g. rough pass count folded
    into path_mm), not a discrete per-pass list. Emitting a literal G-code
    line per physical pass would require inventing per-pass stepdown
    geometry this module was never given. Each op therefore emits ONE
    representative cutting move plus a comment carrying the planner's own
    pass-count note verbatim — consistent with turning_planner's own
    docstring: "planning estimates for quoting — not CAM toolpaths."
    """
    controller = machine.get("controller", "Fanuc")
    machine_name = machine.get("machine_name", "CNC Machine")
    safe_x = (part_max_od_mm or 100.0) + 20.0
    safe_z = 5.0
    clearance_x = (part_max_od_mm or 100.0) + 5.0

    lines = []
    lines.append("; ============================================================")
    lines.append("; DO NOT RUN THIS PROGRAM DIRECTLY ON A MACHINE.")
    lines.append("; THIS IS DRAFT PLANNING CODE ONLY.")
    lines.append("; VERIFY IN CAM/SIMULATOR AND BY A QUALIFIED CNC PROGRAMMER")
    lines.append("; BEFORE RUNNING ON ANY REAL MACHINE.")
    lines.append("; Tool numbers, offsets, speeds, and feeds MUST be verified.")
    lines.append("; Each cutting move below is ONE representative pass per")
    lines.append("; operation — see the inline note for the planner's actual")
    lines.append("; pass count. This is not a multi-pass CAM toolpath.")
    lines.append("; ============================================================")
    lines.append(";")
    lines.append(f"; Machine   : {machine_name}  ({controller})")
    lines.append(f"; Part      : L={part_length_mm:g} mm  max OD={part_max_od_mm:g} mm")
    lines.append(f"; Operations: {len(turning_ops)}")
    lines.append(";")

    if not turning_ops:
        lines.append("; No turning operations planned — nothing to emit.")
        return "\n".join(lines)

    lines.append("O0002  (CNC PROCESS PLANNER - DRAFT LATHE PROGRAM)")
    lines.append(";")
    lines.append("; --- SAFETY SETUP ---")
    lines.append("G21        (Metric mode)")
    lines.append("G18        (XZ plane selection — lathe)")
    lines.append("G90        (Absolute positioning, X on diameter)")
    lines.append("G99        (Feed per revolution)")
    lines.append("G54        (Work coordinate system)")
    lines.append("G80        (Cancel canned cycles)")
    lines.append("G40        (Cancel tool nose radius comp)")
    lines.append(f"G50 S{int(_LATHE_MAX_RPM)}   (Spindle speed clamp — machine max rpm)")
    lines.append(f"G0 X{_format_coord(safe_x)} Z{_format_coord(safe_z)}  "
                  "(Move to safe position, clear of chuck/tailstock)")
    lines.append(";")

    current_tool_slot = None
    current_setup = None

    for i, op in enumerate(turning_ops, start=1):
        op_type = op.get("op", "")
        tool_name = op.get("tool", "")
        rpm = op.get("rpm") or 0
        feed = op.get("feed_mm_rev") or 0.0
        feature = op.get("feature", "")
        notes = op.get("notes", "")
        setup = op.get("setup", "Lathe Chuck")

        if setup != current_setup:
            lines.append(";")
            lines.append("; ============================================================")
            lines.append(f"; SETUP — {setup.upper()}")
            if current_setup is not None:
                lines.append("; Re-fixture as required; re-indicate and re-zero.")
            lines.append("; ============================================================")
            lines.append(";")
            current_setup = setup

        tool_slot, tool_meta = _turning_tool_slot(tool_name)
        if tool_slot != current_tool_slot:
            if current_tool_slot is not None:
                lines.append("; --- END OF PREVIOUS TOOL ---")
                lines.append("M9         (Coolant OFF)")
                lines.append("M5         (Spindle STOP)")
                lines.append(f"G0 X{_format_coord(safe_x)} Z{_format_coord(safe_z)}  (Retract to safe position)")
                lines.append(";")
            lines.append(f"; === TOOL CHANGE: T{tool_slot:02d} - {tool_name} ===")
            lines.append(f"T{tool_slot:02d}{tool_slot:02d}  (Tool change: station {tool_slot:02d}, offset {tool_slot:02d} — {tool_name})")
            lines.append(f"G97 S{int(rpm)} M3   (Constant RPM, spindle ON CW, {int(rpm)} rpm)")
            lines.append("M8         (Coolant ON)")
            lines.append(";")
            current_tool_slot = tool_slot

        lines.append(f"; -- [{i:02d}] {feature} : {op_type} --")
        if notes:
            lines.append(f"; {notes}")

        if op_type == "Face":
            # Facing pass: rapid clear of the OD, feed in from OD to centreline
            # at Z0 (finished-length datum), retract clear.
            lines.append(f"G0 X{_format_coord(clearance_x)} Z{_format_coord(safe_z)}  (Rapid to facing start)")
            lines.append(f"G0 Z0.000  (Approach Z0 — finished face datum)")
            lines.append(f"G1 X0.000 F{feed:g}  (Face to centreline)")
            lines.append(f"G0 X{_format_coord(clearance_x)}  (Retract X)")

        elif op_type in ("OD Rough Turn", "OD Finish Turn"):
            # Prefer the feature's OWN axial span (parsed from its label);
            # only fall back to the whole-part length when the label carries
            # no length. Using part_length_mm unconditionally is wrong for
            # any OD region shorter than the full part (a shoulder/journal).
            _parsed_dia, _parsed_len = _parse_feature_dims(feature)
            length = _parsed_len if _parsed_len is not None else (part_length_mm or 0.0)
            target_dia = _parsed_dia if _parsed_dia is not None else (part_max_od_mm or 0.0)
            lines.append(f"G0 X{_format_coord(clearance_x)} Z{_format_coord(safe_z)}  (Rapid to OD start)")
            lines.append(f"G0 Z0.000  (Approach right face)")
            lines.append(f"G1 X{_format_coord(target_dia)} F{feed:g}  (Feed to diameter)")
            lines.append(f"G1 Z-{_format_coord(length)} F{feed:g}  (Turn pass along Z)")
            lines.append(f"G0 X{_format_coord(clearance_x)}  (Retract X clear of part)")
            lines.append(f"G0 Z{_format_coord(safe_z)}  (Retract Z)")

        elif op_type in ("ID Rough Bore", "ID Finish Bore"):
            # Same fix as OD above: a bore's own axial extent (e.g. T07's
            # Ø40 x 30mm central bore inside a 150mm-long flange) is almost
            # always shorter than the whole part — never assume full length.
            _parsed_dia, _parsed_len = _parse_feature_dims(feature)
            length = _parsed_len if _parsed_len is not None else (part_length_mm or 0.0)
            bore_dia = _parsed_dia if _parsed_dia is not None else 0.0
            if feed <= 0:
                lines.append("; SKIPPED — no boring bar fits this bore per the plan (see note above).")
            else:
                lines.append(f"G0 X0.000 Z{_format_coord(safe_z)}  (Rapid, bar centred on axis)")
                lines.append(f"G0 Z0.000  (Approach right face)")
                lines.append(f"G1 X{_format_coord(bore_dia)} F{feed:g}  (Feed bar to bore diameter)")
                lines.append(f"G1 Z-{_format_coord(length)} F{feed:g}  (Bore pass along Z)")
                lines.append(f"G0 X0.000  (Retract bar to centreline)")
                lines.append(f"G0 Z{_format_coord(safe_z)}  (Retract Z)")

        elif op_type == "ID Groove":
            _parsed_dia, _ = _parse_feature_dims(feature)
            groove_dia = _parsed_dia if _parsed_dia is not None else 0.0
            # Groove Z position is NOT in the planner's op dict (only diameter
            # and axial width are known — see turning_planner.py plan_turning_
            # operations) — do not fabricate an axial position from part
            # length. Z is left as an explicit placeholder the programmer
            # must fill in from the drawing/model before this is usable.
            lines.append(f"G0 X0.000 Z{_format_coord(safe_z)}  (Rapid, groove tool on axis)")
            lines.append("G0 Z-[GROOVE_Z]  (Z NOT COMPUTED BY PLANNER — set from drawing before use)")
            lines.append(f"G1 X{_format_coord(groove_dia)} F{feed:g}  (Plunge to groove diameter)")
            lines.append("G4 P500    (Dwell at groove floor)")
            lines.append("G0 X0.000  (Retract tool to centreline)")
            lines.append(f"G0 Z{_format_coord(safe_z)}  (Retract Z)")

        else:
            lines.append(f"; UNRECOGNISED TURNING OP TYPE '{op_type}' — no move emitted; verify manually.")

        lines.append(";")

    lines.append("; --- END OF PROGRAM ---")
    lines.append("M9         (Coolant OFF)")
    lines.append("M5         (Spindle STOP)")
    lines.append(f"G0 X{_format_coord(safe_x)} Z{_format_coord(safe_z)}  (Retract to safe position)")
    lines.append("M30        (End of program)")
    lines.append("%")

    return "\n".join(lines)


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
        if (op_type in ("Face Mill", "Face Mill Rough", "Face Mill Finish")
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
        elif op_type in ("Face Mill", "Face Mill Rough", "Face Mill Finish"):
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
