"""Top-level orchestrator: parse STEP → split bodies → classify → group → plan → estimate."""
from __future__ import annotations

from .models import WeldmentPart, WeldmentJob
from .body_splitter import split_step_bodies
from .part_classifier import classify_body, material_guess
from .part_feature_detector import detect_features_on_body
from .part_grouper import group_parts
from .part_operation_planner import plan_part_operations
from .weldment_process_planner import plan_assembly_operations
from .weldment_time_estimator import apply_time_estimates


def analyze_weldment(file_bytes: bytes, filename: str) -> dict:
    """Run the full weldment analysis pipeline.

    Returns a dict:
      success: bool
      job: WeldmentJob (on success)
      message: str (on failure)
      warnings: list[str]
    """
    # 1. Split STEP into bodies
    split = split_step_bodies(file_bytes)
    warnings = list(split.get("warnings", []))

    if not split["success"]:
        return {
            "success": False,
            "message": split["message"],
            "job": None,
            "warnings": warnings,
        }

    bodies = split["bodies"]
    if not bodies:
        return {
            "success": False,
            "message": "No solid bodies found in STEP file.",
            "job": None,
            "warnings": warnings,
        }

    # 2. Build WeldmentPart objects
    parts: list[WeldmentPart] = []
    for body in bodies:
        cls  = classify_body(body)
        mat  = material_guess(body)
        feats = detect_features_on_body(body)
        part = WeldmentPart(
            body_index=body["body_index"],
            label=body["label"],
            classification=cls,
            length_mm=body["length_mm"],
            width_mm=body["width_mm"],
            height_mm=body["height_mm"],
            volume_cm3=body["volume_cm3"],
            surface_area_mm2=body["surface_area_mm2"],
            faces_count=body["faces_count"],
            material_guess=mat,
            features=feats,
        )
        parts.append(part)

    # 3. Group similar parts
    groups = group_parts(parts)

    # 4. Plan per-part operations
    for part in parts:
        part.operations = plan_part_operations(part)

    # 5. Build WeldmentJob
    job = WeldmentJob(
        filename=filename,
        total_bodies=len(bodies),
        parts=parts,
        groups=groups,
        warnings=warnings,
    )

    # 6. Plan assembly operations
    job.assembly_operations = plan_assembly_operations(job)

    # 7. Time estimates
    apply_time_estimates(job)

    # Attach mesh data back to each part for 3D preview (stored in body dict)
    _body_mesh_map = {b["body_index"]: b.get("mesh_data") for b in bodies}
    for part in parts:
        part.__dict__["_mesh_data"] = _body_mesh_map.get(part.body_index)

    return {
        "success": True,
        "job": job,
        "warnings": warnings,
        "bodies_raw": bodies,  # keep for 3D viewer
    }
