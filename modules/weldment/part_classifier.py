"""Classify a solid body as plate / block / tube / shaft / gusset / bracket / unknown.

Rules are geometric — no CAD metadata required.
"""
from __future__ import annotations
import math


def classify_body(body: dict) -> str:
    """Return a classification string for a body dict from body_splitter.

    Classification priority:
      shaft   — very long cylinder-ish (AR ≥ 4, approx square cross-section)
      tube    — thin-walled hollow (estimated from SA vs volume)
      plate   — very flat (min_dim / max_dim ≤ 0.15)
      gusset  — flat AND roughly triangular face count signature
      bracket — moderate aspect ratio with high face count (≥ 20)
      block   — roughly equidimensional
      unknown — fallback
    """
    L = body.get("length_mm", 0.0)
    W = body.get("width_mm", 0.0)
    H = body.get("height_mm", 0.0)
    vol = body.get("volume_cm3", 0.0)
    sa  = body.get("surface_area_mm2", 0.0)
    nf  = body.get("faces_count", 0)

    dims = sorted([L, W, H])
    if dims[2] < 0.001:
        return "unknown"

    d_min, d_mid, d_max = dims
    flatness   = d_min / d_max if d_max > 0 else 1.0   # → 0 means very flat
    elongation = d_max / d_mid if d_mid > 0 else 1.0   # → high means bar/shaft

    # SA-to-volume ratio: thin-walled parts have a high ratio
    sa_vol_ratio = (sa / (vol * 1000.0)) if vol > 0 else 0.0  # SA in mm², vol in mm³

    # Shaft / bar — long and roughly round cross-section
    cross_ar = d_mid / d_min if d_min > 0 else 1.0
    if elongation >= 4.0 and cross_ar <= 1.5:
        return "shaft"

    # Plate — very flat
    if flatness <= 0.15:
        # Gusset heuristic: plate with ≤ 8 faces and aspect ratio > 1.4 in the plane
        plane_ar = d_mid / d_min if d_min > 0 else 1.0
        if nf <= 8 and plane_ar >= 1.4 and d_max > 0:
            in_plane = d_max / d_mid if d_mid > 0 else 1.0
            if in_plane >= 1.4:
                return "gusset"
        return "plate"

    # Bracket — moderate aspect ratio but complex (many faces)
    if nf >= 20 and flatness > 0.15 and elongation < 4.0:
        return "bracket"

    # Tube / hollow section — high SA/vol ratio suggests thin walls
    # Solid steel block has ~6 mm⁻¹; thin plates/tubes much higher
    if sa_vol_ratio > 20.0 and flatness > 0.15:
        return "tube"

    # Block — roughly equidimensional
    if flatness > 0.30 and elongation < 3.0:
        return "block"

    # Elongated bar that didn't meet shaft threshold
    if elongation >= 2.5:
        return "shaft"

    return "block"


def material_guess(body: dict) -> str:
    """Return a material guess — currently always 'Steel' (no CAD metadata)."""
    return "Steel"
