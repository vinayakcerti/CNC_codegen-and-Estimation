"""Split a multi-body STEP file into individual solid bodies using CadQuery."""
from __future__ import annotations
import os
import tempfile
from typing import Optional


def split_step_bodies(file_bytes: bytes) -> dict:
    """Parse a STEP file and extract each solid body as separate geometry data.

    Returns a dict with:
      success: bool
      bodies: list of dicts — one per solid, with bbox + topology counts
      total_bodies: int
      message: str (on failure)
      warnings: list[str]
    """
    try:
        import cadquery as cq
    except ImportError:
        return {
            "success": False,
            "message": "CadQuery is not available — weldment body splitting requires CadQuery.",
            "bodies": [],
            "total_bodies": 0,
            "warnings": [],
        }

    tmp_path = None
    warnings: list[str] = []
    try:
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name

        result = cq.importers.importStep(tmp_path)
        compound = result.val()

        # Extract individual solids
        try:
            solids = compound.Solids()
        except Exception:
            solids = [compound]

        if not solids:
            return {
                "success": False,
                "message": "No solid bodies found in STEP file.",
                "bodies": [],
                "total_bodies": 0,
                "warnings": warnings,
            }

        bodies = []
        for idx, solid in enumerate(solids):
            try:
                bb = solid.BoundingBox()
                length = round(bb.xmax - bb.xmin, 3)
                width  = round(bb.ymax - bb.ymin, 3)
                height = round(bb.zmax - bb.zmin, 3)

                vol_mm3 = solid.Volume()
                vol_cm3 = round(vol_mm3 / 1000.0, 3) if vol_mm3 > 0 else round(length * width * height / 1000.0 * 0.6, 3)

                try:
                    faces = solid.Faces()
                    faces_count = len(faces)
                    # Estimate surface area from face areas
                    sa_mm2 = sum(f.Area() for f in faces)
                except Exception:
                    faces_count = 0
                    sa_mm2 = 0.0

                # Tessellate for 3D mesh preview
                mesh_data = None
                try:
                    verts, tris = solid.tessellate(0.5)
                    if verts:
                        mesh_data = {
                            "x": [v.x for v in verts],
                            "y": [v.y for v in verts],
                            "z": [v.z for v in verts],
                            "i": [t[0] for t in tris],
                            "j": [t[1] for t in tris],
                            "k": [t[2] for t in tris],
                        }
                except Exception as te:
                    warnings.append(f"Body {idx + 1}: tessellation failed — {te}")

                bodies.append({
                    "body_index": idx,
                    "label": f"Body {idx + 1}",
                    "length_mm": length,
                    "width_mm": width,
                    "height_mm": height,
                    "volume_cm3": vol_cm3,
                    "surface_area_mm2": round(sa_mm2, 1),
                    "faces_count": faces_count,
                    "mesh_data": mesh_data,
                    "bbox": {
                        "xmin": round(bb.xmin, 3), "xmax": round(bb.xmax, 3),
                        "ymin": round(bb.ymin, 3), "ymax": round(bb.ymax, 3),
                        "zmin": round(bb.zmin, 3), "zmax": round(bb.zmax, 3),
                    },
                })
            except Exception as be:
                warnings.append(f"Body {idx + 1}: extraction failed — {be}")
                bodies.append({
                    "body_index": idx,
                    "label": f"Body {idx + 1}",
                    "length_mm": 0.0, "width_mm": 0.0, "height_mm": 0.0,
                    "volume_cm3": 0.0, "surface_area_mm2": 0.0, "faces_count": 0,
                    "mesh_data": None, "bbox": {},
                })

        return {
            "success": True,
            "bodies": bodies,
            "total_bodies": len(bodies),
            "warnings": warnings,
        }

    except Exception as exc:
        return {
            "success": False,
            "message": f"STEP body splitting failed: {exc}",
            "bodies": [],
            "total_bodies": 0,
            "warnings": warnings,
        }
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
