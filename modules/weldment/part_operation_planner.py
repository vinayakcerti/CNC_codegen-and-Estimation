"""Recommend per-part machining operations for a WeldmentPart."""
from __future__ import annotations
from .models import WeldmentPart


def plan_part_operations(part: WeldmentPart) -> list[dict]:
    """Return a list of recommended machining operation dicts for one part.

    Each op dict: operation, tool_type, note.
    """
    ops: list[dict] = []
    cls = part.classification
    L, W, H = part.length_mm, part.width_mm, part.height_mm
    dims = sorted([L, W, H])
    flatness = dims[0] / dims[2] if dims[2] > 0 else 1.0

    if cls == "plate":
        ops.append({
            "operation": "Face Milling — top & bottom surfaces",
            "tool_type": "Face Mill Ø50–Ø80",
            "note": "Clean reference surfaces before assembly",
        })
        if part.features:
            for feat in part.features:
                if feat["feature_type"] == "Hole":
                    ops.append({
                        "operation": f"Drilling — {feat['count']} hole(s)",
                        "tool_type": "Drill + Counterbore/sink as required",
                        "note": feat.get("note", ""),
                    })
                elif "Pocket" in feat["feature_type"]:
                    ops.append({
                        "operation": "Pocket / Profile Milling",
                        "tool_type": "End Mill Ø10–Ø20",
                        "note": feat.get("note", ""),
                    })
                elif feat["feature_type"] == "Slot":
                    ops.append({
                        "operation": "Slot Milling",
                        "tool_type": "Slot Drill / End Mill",
                        "note": feat.get("note", ""),
                    })

    elif cls == "block":
        ops.append({
            "operation": "Face Milling — all datum faces",
            "tool_type": "Face Mill Ø50–Ø80",
            "note": "Square up block to drawing datums",
        })
        if part.features:
            for feat in part.features:
                if feat["feature_type"] == "Hole":
                    ops.append({
                        "operation": f"Drilling / Boring — {feat['count']} hole(s)",
                        "tool_type": "Drill + Boring Bar",
                        "note": feat.get("note", ""),
                    })
                elif "Pocket" in feat["feature_type"]:
                    ops.append({
                        "operation": "Pocket Milling",
                        "tool_type": "End Mill Ø10–Ø20",
                        "note": feat.get("note", ""),
                    })

    elif cls in ("shaft", "tube"):
        ops.append({
            "operation": "OD Turning — rough + finish",
            "tool_type": "Turning Insert CNMG/DCMT",
            "note": "CNC lathe; face and turn OD to drawing",
        })
        if dims[2] > 200:
            ops.append({
                "operation": "Steady rest / tailstock support",
                "tool_type": "Steady rest",
                "note": "L/D > 4 — slender part needs support",
            })
        if part.features:
            for feat in part.features:
                if feat["feature_type"] == "Hole":
                    ops.append({
                        "operation": "Drilling / Centre Drilling",
                        "tool_type": "Drill",
                        "note": feat.get("note", ""),
                    })

    elif cls == "gusset":
        ops.append({
            "operation": "Face Milling — weld prep faces",
            "tool_type": "Face Mill Ø50",
            "note": "Clean flat contact faces for fillet weld",
        })

    elif cls == "bracket":
        ops.append({
            "operation": "Face Milling — datum face",
            "tool_type": "Face Mill Ø50–Ø80",
            "note": "",
        })
        if part.features:
            for feat in part.features:
                if feat["feature_type"] == "Hole":
                    ops.append({
                        "operation": f"Drilling — {feat['count']} hole(s)",
                        "tool_type": "Drill",
                        "note": feat.get("note", ""),
                    })

    else:
        ops.append({
            "operation": "Face Milling — datum surface",
            "tool_type": "Face Mill",
            "note": "Verify required surfaces with drawing",
        })

    return ops
