"""Workholding recommendation and per-setup configuration for 3-axis milling.

Mirrors the competitor's Setup-tab workholding panel: recommend a holding
method per setup from stock geometry, let the operator override, and surface
grip/clearance warnings that feed the setup sheet.
"""
from __future__ import annotations

# Catalogue of supported workholding methods with basic capacity data (mm).
WORKHOLDING_OPTIONS = {
    "6\" Fixed Jaw Vise": {
        "max_jaw_opening": 200.0, "jaw_width": 150.0,
        "min_grip": 6.0, "typical_grip": 10.0,
        "note": "General-purpose milling vise; parallels under part",
    },
    "4\" Fixed Jaw Vise": {
        "max_jaw_opening": 125.0, "jaw_width": 100.0,
        "min_grip": 5.0, "typical_grip": 8.0,
        "note": "Small parts; lighter clamping force",
    },
    "Double Station Vise": {
        "max_jaw_opening": 160.0, "jaw_width": 130.0,
        "min_grip": 6.0, "typical_grip": 10.0,
        "note": "Two parts per cycle or long part across stations",
    },
    "Fixture Plate + Toe Clamps": {
        "max_jaw_opening": None, "jaw_width": None,
        "min_grip": 0.0, "typical_grip": 0.0,
        "note": "Plates and large parts; watch clamp-to-tool clearance",
    },
    "Vacuum / Magnetic Chuck": {
        "max_jaw_opening": None, "jaw_width": None,
        "min_grip": 0.0, "typical_grip": 0.0,
        "note": "Thin plates, full-face support; verify holding force vs cut",
    },
    "Soft Jaws (machined)": {
        "max_jaw_opening": 200.0, "jaw_width": 150.0,
        "min_grip": 4.0, "typical_grip": 6.0,
        "note": "2nd-op holding on finished contours; machine jaws first",
    },
    "Custom Fixture": {
        "max_jaw_opening": None, "jaw_width": None,
        "min_grip": 0.0, "typical_grip": 0.0,
        "note": "Dedicated fixture — cost and lead time apply",
    },
}

JAW_MODES = ["Hard jaws", "Soft jaws", "Parallels + hard jaws"]


def recommend_workholding(stock: dict, setup_label: str = "") -> dict:
    """Recommend a workholding method for a setup from stock geometry.

    Returns {"method", "jaw_mode", "reason"}.
    """
    L = float(stock.get("length") or 0)
    W = float(stock.get("width") or 0)
    H = float(stock.get("height") or 0)
    dims = sorted([L, W, H])
    label = (setup_label or "").lower()

    # Secondary setups holding on machined geometry -> soft jaws
    is_secondary = any(k in label for k in ("bottom", "back", "2", "flip"))

    # Thin large plate — vise jaws can't reach across; plate work
    if dims[2] > 400 and dims[0] < 30:
        return {
            "method": "Fixture Plate + Toe Clamps",
            "jaw_mode": JAW_MODES[0],
            "reason": f"Large thin plate ({L:.0f}×{W:.0f}×{H:.0f}) — vise span insufficient",
        }
    # Fits a 6" vise across its smallest horizontal dimension?
    grip_dim = min(L, W)
    if grip_dim <= 200 and H <= 150:
        method = "Soft Jaws (machined)" if is_secondary else "6\" Fixed Jaw Vise"
        return {
            "method": method,
            "jaw_mode": JAW_MODES[1] if is_secondary else JAW_MODES[2],
            "reason": (
                f"Grip width {grip_dim:.0f} mm within 200 mm jaw opening"
                + ("; secondary setup on machined faces" if is_secondary else "")
            ),
        }
    return {
        "method": "Fixture Plate + Toe Clamps",
        "jaw_mode": JAW_MODES[0],
        "reason": f"Part {L:.0f}×{W:.0f}×{H:.0f} exceeds vise capacity",
    }


def workholding_warnings(method: str, stock: dict) -> list[str]:
    """Static clearance/grip warnings for the chosen method on this stock."""
    spec = WORKHOLDING_OPTIONS.get(method) or {}
    H = float(stock.get("height") or 0)
    L = float(stock.get("length") or 0)
    W = float(stock.get("width") or 0)
    warns = []
    if spec.get("max_jaw_opening") is not None:
        if min(L, W) > spec["max_jaw_opening"]:
            warns.append(
                f"Grip dimension {min(L, W):.0f} mm exceeds {method} max opening "
                f"{spec['max_jaw_opening']:.0f} mm."
            )
        grip = spec.get("typical_grip", 10.0)
        if H > 0 and grip > 0 and H < grip * 1.5:
            warns.append(
                f"Part height {H:.0f} mm leaves little material above jaws with "
                f"{grip:.0f} mm grip — verify tool clearance."
            )
    if method == "Fixture Plate + Toe Clamps":
        warns.append("Plan clamp positions clear of toolpaths; reposition mid-cycle if needed.")
    if method == "Vacuum / Magnetic Chuck":
        warns.append("Verify holding force against roughing cutting forces.")
    return warns
