"""Detect simple features (holes, slots, pockets) on individual solid bodies.

Uses face topology from CadQuery if available; falls back to bbox heuristics.
Detection is intentionally lightweight — it is NOT a full CAM feature recogniser.
"""
from __future__ import annotations
import math


def detect_features_on_body(body: dict) -> list[dict]:
    """Return a list of detected feature dicts for a single body dict.

    Each feature dict has: feature_type, count, note.
    This is a heuristic pass — accuracy is 'planning reference' level.
    """
    features: list[dict] = []
    faces_count = body.get("faces_count", 0)
    L = body.get("length_mm", 0.0)
    W = body.get("width_mm", 0.0)
    H = body.get("height_mm", 0.0)
    vol = body.get("volume_cm3", 0.0)

    if faces_count == 0:
        return features

    dims = sorted([L, W, H])
    flatness = dims[0] / dims[2] if dims[2] > 0 else 1.0

    # Bbox solid volume vs actual — significant hollowing suggests pockets or bores
    bbox_vol_cm3 = L * W * H / 1000.0
    fill_ratio   = vol / bbox_vol_cm3 if bbox_vol_cm3 > 0 else 1.0

    # ── Holes & slots — exact geometric classification when available ──
    # body_splitter runs slot_hole_classifier per solid: distinct hole axes
    # and paired slot end-caps. Fall back to the face-count heuristic only
    # when the OCC adaptor was unavailable.
    if body.get("cyl_classifier_available"):
        hole_count = body.get("hole_count", 0)
        slot_count = body.get("slot_count", 0)
        slot_dims  = body.get("slots", [])
        if hole_count > 0:
            features.append({
                "feature_type": "Hole",
                "count": hole_count,
                "note": f"{hole_count} hole axis/axes from exact cylinder geometry",
            })
        if slot_count > 0:
            _dims_txt = ", ".join(
                f"{s['length_mm']:.0f}×{s['width_mm']:.0f}" for s in slot_dims[:6]
            )
            features.append({
                "feature_type": "Slot",
                "count": slot_count,
                "note": f"Slot end-cap pairs (L×W mm): {_dims_txt}",
            })
    else:
        # Plate-like body with extra faces → likely has holes drilled through it
        if flatness <= 0.20 and faces_count >= 8:
            # Each through-hole adds 3 faces (cylinder + 2 circles) beyond the 6 base faces
            extra_faces = faces_count - 6
            if extra_faces >= 3:
                est_holes = extra_faces // 3
                features.append({
                    "feature_type": "Hole",
                    "count": min(est_holes, 20),
                    "note": f"~{min(est_holes, 20)} through-hole(s) estimated from face count",
                })
        # Long narrow part with many faces — could have slots
        elongation = dims[2] / dims[1] if dims[1] > 0 else 1.0
        if elongation >= 3.0 and faces_count >= 10 and flatness <= 0.25:
            features.append({
                "feature_type": "Slot",
                "count": 1,
                "note": "Elongated plate with extra faces — slot(s) possible",
            })

    # Block/shaft with significant material removal and many faces → pockets or stepped profile
    if flatness > 0.15 and fill_ratio < 0.75 and faces_count >= 12:
        features.append({
            "feature_type": "Pocket / Profile",
            "count": 1,
            "note": f"Significant material removal (fill={fill_ratio:.0%}) — pockets or stepped profile likely",
        })

    return features
