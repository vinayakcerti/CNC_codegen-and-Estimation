"""Plan assembly-level weldment operations (fit-up, tack, full weld, grind, post-weld machining)."""
from __future__ import annotations
from .models import WeldmentJob, WeldmentGroup


_ASSEMBLY_OPS_TEMPLATE = [
    {
        "phase": "Fit-Up",
        "operation": "Mark out and position parts per drawing — check square and level",
        "tool_equipment": "Scriber, square, clamps, tack welder",
        "note": "Reference all parts from primary datum face(s) before tacking",
    },
    {
        "phase": "Tack Welding",
        "operation": "Tack weld all joints to hold assembly position",
        "tool_equipment": "MIG / TIG welder",
        "note": "Use minimum tack size; check squareness after each tack",
    },
    {
        "phase": "Full Welding",
        "operation": "Full fillet / butt welds per weld symbol drawing",
        "tool_equipment": "MIG / TIG / SMAW welder",
        "note": "Follow weld sequence to manage distortion (weld from centre outward)",
    },
    {
        "phase": "Post-Weld",
        "operation": "Allow to cool; stress relief if required",
        "tool_equipment": "Oven / natural air cool",
        "note": "Do not quench weldment — allow controlled cool to avoid residual stress",
    },
    {
        "phase": "Grinding / Dressing",
        "operation": "Grind flush all weld faces on datum / mating surfaces",
        "tool_equipment": "Angle grinder, flap disc",
        "note": "Only grind faces that will be machined or are contact surfaces",
    },
    {
        "phase": "Post-Weld Machining",
        "operation": "Machine datum faces and critical bores/holes after welding",
        "tool_equipment": "VMC / HMC",
        "note": "All post-weld machining must be after full cool and stress relief",
    },
    {
        "phase": "Inspection",
        "operation": "Dimensional check vs drawing — critical faces, holes, bores",
        "tool_equipment": "CMM / height gauge / vernier",
        "note": "",
    },
]


def plan_assembly_operations(job: WeldmentJob) -> list[dict]:
    """Return the standard assembly operation sequence for this weldment job."""
    ops = list(_ASSEMBLY_OPS_TEMPLATE)

    # If there are no complex machined features across all parts, drop the post-weld machining step
    all_parts_have_features = any(p.features for p in job.parts)
    if not all_parts_have_features:
        ops = [o for o in ops if o["phase"] != "Post-Weld Machining"]

    # Add a note about number of parts
    part_summary = f"{job.total_bodies} body/bodies; {len(job.groups)} unique part type(s)"
    ops[0]["note"] = ops[0]["note"] + f" — {part_summary}"

    return ops
