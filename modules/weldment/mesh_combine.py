"""Combine multiple Plotly Mesh3d dicts into a single mesh.

Used by the Weldment page to render the full assembly (all bodies) in a
single Mesh3d trace instead of one chart per body.
"""
from __future__ import annotations


def combine_meshes(mesh_list: list[dict | None]) -> dict | None:
    """Merge a list of Plotly Mesh3d data dicts into one combined dict.

    Each input dict must contain vertex arrays ``x``/``y``/``z`` and
    triangle index arrays ``i``/``j``/``k``.  Vertices are concatenated
    and the triangle indices of each subsequent body are offset by the
    running vertex count, so the combined dict is a valid single mesh.

    ``None`` or empty entries are skipped.  Returns ``None`` if no valid
    mesh data is present.
    """
    combined: dict[str, list] = {"x": [], "y": [], "z": [], "i": [], "j": [], "k": []}
    offset = 0
    for mesh in mesh_list or []:
        if not mesh:
            continue
        x = mesh.get("x") or []
        if len(x) == 0:
            continue
        combined["x"].extend(x)
        combined["y"].extend(mesh.get("y") or [])
        combined["z"].extend(mesh.get("z") or [])
        combined["i"].extend(int(idx) + offset for idx in (mesh.get("i") or []))
        combined["j"].extend(int(idx) + offset for idx in (mesh.get("j") or []))
        combined["k"].extend(int(idx) + offset for idx in (mesh.get("k") or []))
        offset += len(x)
    if offset == 0:
        return None
    return combined


def mesh_bbox_dims(mesh: dict) -> dict:
    """Return a stock-style dict {length, width, height} for a mesh's bounding box."""
    xs, ys, zs = mesh.get("x") or [0], mesh.get("y") or [0], mesh.get("z") or [0]
    return {
        "length": float(max(xs) - min(xs)),
        "width": float(max(ys) - min(ys)),
        "height": float(max(zs) - min(zs)),
    }
