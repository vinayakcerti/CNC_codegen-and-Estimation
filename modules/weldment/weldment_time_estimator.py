"""Time estimates for weldment parts and assembly operations.

All estimates are rough order-of-magnitude — suitable for quoting, not scheduling.
"""
from __future__ import annotations
from .models import WeldmentPart, WeldmentJob


# Per-operation time table (minutes) by classification + operation type
_OP_TIME_TABLE: dict[str, dict[str, float]] = {
    "plate": {
        "Face Milling — top & bottom surfaces": 10.0,
        "Drilling": 5.0,
        "Pocket / Profile Milling": 15.0,
        "Slot Milling": 8.0,
        "default": 8.0,
    },
    "block": {
        "Face Milling — all datum faces": 15.0,
        "Drilling / Boring": 10.0,
        "Pocket Milling": 20.0,
        "default": 10.0,
    },
    "shaft": {
        "OD Turning — rough + finish": 20.0,
        "Steady rest / tailstock support": 5.0,
        "Drilling / Centre Drilling": 5.0,
        "default": 12.0,
    },
    "tube": {
        "OD Turning — rough + finish": 25.0,
        "default": 15.0,
    },
    "gusset": {
        "Face Milling — weld prep faces": 8.0,
        "default": 6.0,
    },
    "bracket": {
        "Face Milling — datum face": 10.0,
        "Drilling": 5.0,
        "default": 10.0,
    },
    "unknown": {
        "default": 10.0,
    },
}

# Assembly phase times (minutes) — for the whole assembly, not per joint
_ASSEMBLY_PHASE_TIMES: dict[str, float] = {
    "Fit-Up": 30.0,
    "Tack Welding": 20.0,
    "Full Welding": 60.0,
    "Post-Weld": 15.0,
    "Grinding / Dressing": 25.0,
    "Post-Weld Machining": 45.0,
    "Inspection": 20.0,
}

# Scale welding time with the number of unique joints (approx = unique pairs of groups)
_WELD_TIME_PER_JOINT_MIN = 15.0


def estimate_part_time(part: WeldmentPart) -> float:
    """Return estimated machining time in minutes for a single part."""
    cls = part.classification
    table = _OP_TIME_TABLE.get(cls, _OP_TIME_TABLE["unknown"])
    total = 0.0
    for op in part.operations:
        op_name = op.get("operation", "")
        # Match on first word(s) of the operation
        matched = False
        for key, t in table.items():
            if key != "default" and key.lower() in op_name.lower():
                total += t
                matched = True
                break
        if not matched:
            total += table.get("default", 10.0)

    # Size scaling: large parts take proportionally longer
    max_dim = max(part.length_mm, part.width_mm, part.height_mm)
    if max_dim > 500:
        total *= 1.4
    elif max_dim > 200:
        total *= 1.15

    # Setup time (clamping, zeroing): flat 5 min per part
    total += 5.0
    return round(total, 1)


def estimate_assembly_time(job: WeldmentJob) -> float:
    """Return estimated total assembly / welding time in minutes."""
    total = 0.0
    for op in job.assembly_operations:
        phase = op.get("phase", "")
        base  = _ASSEMBLY_PHASE_TIMES.get(phase, 20.0)
        total += base

    # Scale welding with number of groups (joints increase with more unique parts)
    n_groups = len(job.groups)
    if n_groups > 2:
        extra_joints = n_groups - 2
        total += extra_joints * _WELD_TIME_PER_JOINT_MIN

    return round(total, 1)


def apply_time_estimates(job: WeldmentJob) -> None:
    """Mutate job in place — set machining_time_min on each part, totals on job."""
    total_machining = 0.0
    for part in job.parts:
        t = estimate_part_time(part)
        part.machining_time_min = t
        total_machining += t

    job.total_machining_time_min = round(total_machining, 1)
    job.total_assembly_time_min  = estimate_assembly_time(job)
