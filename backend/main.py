"""CNC Plan & Process Pro — REST API.

Wraps the existing deterministic engine (STEP parsing, feature detection,
weldment splitting, DFM scoring, operation planning, time estimation) as
JSON endpoints. This is the data layer for the React frontend and, by
design, is fully functional WITHOUT any AI — the "no-AI tier" is just
these endpoints. AI features live in a separate optional service.

Run (from repo root, cnc-cadquery env):
    conda run -n cnc-cadquery uvicorn backend.main:app --port 8000 --reload
"""
from __future__ import annotations

import os
import sys
import tempfile

# Make the repo-root modules/ importable regardless of launch dir
_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from modules.step_parser import parse_step_auto
from modules.dfm_score import compute_dfm_score
from modules.operation_planner import plan_operations
from modules.time_estimator import estimate_time, estimate_time_per_operation
from modules.data_store import (
    get_default_tools, get_default_materials, get_default_machines,
)
from modules.weldment.weldment_analyzer import analyze_weldment

app = FastAPI(title="CNC Plan & Process Pro API", version="0.1.0")

# Local React dev server + future prod origin
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _tessellate(file_bytes: bytes):
    """Tessellate the whole part for the 3D viewer (x/y/z/i/j/k)."""
    tmp_path = None
    try:
        import cadquery as cq
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        shape = cq.importers.importStep(tmp_path).val()
        verts, tris = shape.tessellate(0.5)
        if not verts:
            return None
        return {
            "x": [round(v.x, 3) for v in verts],
            "y": [round(v.y, 3) for v in verts],
            "z": [round(v.z, 3) for v in verts],
            "i": [t[0] for t in tris],
            "j": [t[1] for t in tris],
            "k": [t[2] for t in tris],
        }
    except Exception:
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _default_context():
    return (
        get_default_tools(),
        get_default_materials()[0],
        get_default_machines()[0],
    )


@app.get("/api/health")
def health():
    tools, material, machine = _default_context()
    return {
        "status": "ok",
        "service": "cnc-plan-process-pro",
        "tools": len(tools),
        "material": material.get("name"),
        "machine": machine.get("name"),
    }


@app.post("/api/analyze")
async def analyze(file: UploadFile = File(...)):
    """Single entry point: parse a STEP file and return the full overview
    (dimensions, topology, detected features, machinability, mesh, and a
    weldment flag). Everything the Overview screen needs, in one call."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    parse = parse_step_auto(data)
    if not parse.get("success"):
        raise HTTPException(status_code=400, detail=parse.get("message", "Parse failed."))

    tools, material, machine = _default_context()
    candidates = parse.get("candidate_features", [])
    dfm = compute_dfm_score(candidates, tools, material, machine)
    mesh = _tessellate(data)
    solids = parse.get("solids_count") or 1

    return {
        "success": True,
        "filename": file.filename,
        "dimensions_mm": {
            "length": parse.get("length_mm"),
            "width": parse.get("width_mm"),
            "height": parse.get("height_mm"),
        },
        "volumes_cm3": {
            "stock": parse.get("stock_volume_cm3"),
            "part": parse.get("part_volume_cm3"),
        },
        "topology": {
            "solids": solids,
            "faces": parse.get("faces_count"),
            "edges": parse.get("edges_count"),
            "vertices": parse.get("vertices_count"),
        },
        "parser": parse.get("parser_used"),
        "candidates": candidates,
        "candidate_count": len(candidates),
        "dfm": dfm,
        "is_multibody": solids > 1,
        "mesh": mesh,
        "material": material.get("name"),
        "machine": machine.get("name"),
    }


@app.post("/api/weldment")
async def weldment(file: UploadFile = File(...)):
    """Full weldment breakdown: split bodies, group, per-part ops, assembly
    ops, time. Serialized for the frontend BOM + group inspector."""
    data = await file.read()
    result = analyze_weldment(data, file.filename)
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("message", "Weldment analysis failed."))

    job = result["job"]
    bodies_raw = {b["body_index"]: b for b in result.get("bodies_raw", [])}

    def _group_json(g):
        rep = g.representative
        return {
            "group_id": g.group_id,
            "classification": g.classification,
            "quantity": g.quantity,
            "body_indices": g.body_indices,
            "dims_mm": {"length": rep.length_mm, "width": rep.width_mm, "height": rep.height_mm},
            "volume_cm3": rep.volume_cm3,
            "faces": rep.faces_count,
            "machining_min_per_pc": rep.machining_time_min,
            "features": rep.features,
            "operations": rep.operations,
            "mesh": (bodies_raw.get(rep.body_index) or {}).get("mesh_data"),
        }

    return {
        "success": True,
        "filename": job.filename,
        "total_bodies": job.total_bodies,
        "total_machining_time_min": job.total_machining_time_min,
        "total_assembly_time_min": job.total_assembly_time_min,
        "total_time_min": job.total_time_min,
        "groups": [_group_json(g) for g in job.groups],
        "assembly_operations": job.assembly_operations,
        "warnings": job.warnings,
    }


@app.post("/api/strategy")
async def strategy(file: UploadFile = File(...)):
    """Operation plan grouped by setup with per-op tool + cycle time —
    the Strategy screen's data."""
    data = await file.read()
    parse = parse_step_auto(data)
    if not parse.get("success"):
        raise HTTPException(status_code=400, detail=parse.get("message", "Parse failed."))

    tools, material, machine = _default_context()
    candidates = parse.get("candidate_features", [])
    features = [
        {
            "feature_type": c.get("feature_type", ""),
            "feature_name": c.get("feature_name") or f"Feature {i + 1}",
            "diameter": c.get("diameter") or 0,
            "length": c.get("length") or 0,
            "width": c.get("width") or 0,
            "depth": c.get("depth") or 0,
            "x_pos": c.get("x_pos", 0) or 0,
            "y_pos": c.get("y_pos", 0) or 0,
            "setup_label": c.get("setup") or c.get("setup_label") or "Top",
        }
        for i, c in enumerate(candidates)
    ]
    ops = plan_operations(features, tools, material, machine)
    per_op = estimate_time_per_operation(ops, machine, material)
    totals = estimate_time(ops, machine, material, features)

    # Group per-op rows by setup, preserving first-appearance order
    setups: list = []
    index: dict = {}
    for row in per_op:
        label = row["setup"]
        if label not in index:
            index[label] = {"setup_label": label, "ops": [], "subtotal_min": 0.0}
            setups.append(index[label])
        index[label]["ops"].append(row)
        index[label]["subtotal_min"] = round(index[label]["subtotal_min"] + row["cut_min"], 2)

    return {
        "success": True,
        "filename": file.filename,
        "setups": setups,
        "totals": totals,
    }
