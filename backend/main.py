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

import json

from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from modules.machine_capability import normalize_machine_capabilities

from modules.step_parser import parse_step_auto
from modules.dfm_score import compute_dfm_score
from modules.operation_planner import plan_operations
from modules.time_estimator import estimate_time, estimate_time_per_operation
from modules.data_store import (
    get_default_tools, get_default_materials, get_default_machines,
)
from modules.weldment.weldment_analyzer import analyze_weldment
from modules.workholding import recommend_workholding
from modules.body_scope import filter_candidates_to_body

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
    """Tessellate the whole part for the 3D viewer (x/y/z/i/j/k) and collect
    per-face areas (index-aligned with the parser's face records) for the
    machinable-surface-area metric. Returns (mesh|None, face_areas)."""
    tmp_path = None
    try:
        import cadquery as cq
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        shape = cq.importers.importStep(tmp_path).val()
        try:
            face_areas = [f.Area() for f in shape.Faces()]
        except Exception:
            face_areas = []
        verts, tris = shape.tessellate(0.5)
        if not verts:
            return None, face_areas
        return {
            "x": [round(v.x, 3) for v in verts],
            "y": [round(v.y, 3) for v in verts],
            "z": [round(v.z, 3) for v in verts],
            "i": [t[0] for t in tris],
            "j": [t[1] for t in tris],
            "k": [t[2] for t in tris],
        }, face_areas
    except Exception:
        return None, []
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _machinable_surface_pct(candidates, dfm, face_areas) -> float | None:
    """Machinable surface area % — total face area minus faces belonging to
    features whose planning is blocked (their 'blocked' issues in dfm)."""
    total = sum(face_areas)
    if total <= 0:
        return None
    blocked_names = {
        i.get("feature") for i in dfm.get("issues", [])
        if i.get("severity") == "blocked"
    }
    blocked_area = 0.0
    counted: set = set()
    for c in candidates:
        if (c.get("feature_name") or "") not in blocked_names:
            continue
        for fi in c.get("face_indices") or []:
            if isinstance(fi, int) and 0 <= fi < len(face_areas) and fi not in counted:
                counted.add(fi)
                blocked_area += face_areas[fi]
    return round(max(0.0, min(100.0, 100.0 * (1 - blocked_area / total))), 1)


def _body_bbox(file_bytes: bytes, body_index: int) -> dict | None:
    """Bounding box of one solid — cheap pass, no tessellation."""
    tmp_path = None
    try:
        import cadquery as cq
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        solids = cq.importers.importStep(tmp_path).val().Solids()
        if body_index < 0 or body_index >= len(solids):
            return None
        bb = solids[body_index].BoundingBox()
        return {"xmin": bb.xmin, "xmax": bb.xmax, "ymin": bb.ymin,
                "ymax": bb.ymax, "zmin": bb.zmin, "zmax": bb.zmax}
    except Exception:
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


_BACKEND_DIR = os.path.dirname(os.path.abspath(__file__))


def _load_backend_json(name: str) -> list:
    try:
        with open(os.path.join(_BACKEND_DIR, name), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _machines_library() -> list:
    """Curated market machines (India / Middle East / global) + app defaults."""
    lib = [normalize_machine_capabilities(m) for m in _load_backend_json("machines_library.json")]
    defaults = get_default_machines()
    names = {m.get("name") for m in lib}
    return lib + [m for m in defaults if m.get("name") not in names]


def _extended_tools() -> list:
    """API planning tool set: engine defaults + the extended metric library.

    Engine defaults stay untouched for Streamlit/tests; the API plans with
    the richer set so tool matches (drills, taps, reamers) are realistic.
    """
    from modules.tool_feasibility import normalize_tool_profile
    base = get_default_tools()
    seen = {(t.get("tool_type"), t.get("diameter_mm")) for t in base}
    extra = [
        normalize_tool_profile(t)
        for t in _load_backend_json("tools_extended.json")
        if (t.get("tool_type"), t.get("diameter_mm")) not in seen
    ]
    return base + extra


def _default_context(
    material_name: str | None = None,
    machine_name: str | None = None,
    machine_json: str | None = None,
):
    materials = get_default_materials()
    material = materials[0]
    if material_name:
        for m in materials:
            if m.get("name", "").lower() == material_name.lower():
                material = m
                break
    machine = get_default_machines()[0]
    if machine_json:
        try:
            machine = normalize_machine_capabilities(json.loads(machine_json))
        except Exception:
            pass
    elif machine_name:
        for m in _machines_library():
            if m.get("name", "").lower() == machine_name.lower():
                machine = m
                break
    return (_extended_tools(), material, machine)


def _hole_groups(candidates):
    """Group detected hole candidates by diameter — Toolpath-style
    '7x Ø5mm · Setup 3,5,6' rows for the Overview inspector."""
    groups: dict = {}
    for c in candidates:
        ft = (c.get("feature_type") or "").lower()
        dia = c.get("diameter") or 0
        if "hole" not in ft or not dia:
            continue
        key = round(float(dia), 2)
        g = groups.setdefault(key, {"diameter_mm": key, "count": 0, "setups": set()})
        g["count"] += 1
        setup = c.get("setup") or c.get("setup_label")
        if setup:
            g["setups"].add(str(setup))
    out = []
    for g in sorted(groups.values(), key=lambda x: x["diameter_mm"]):
        g["setups"] = sorted(g["setups"])
        out.append(g)
    return out


_SAMPLES_DIR = os.path.join(_REPO_ROOT, "test_samples")


@app.get("/api/sample/{name}")
def sample(name: str):
    """Serve a bundled sample STEP so the UI has a one-click 'try it' path."""
    safe = os.path.basename(name)
    path = os.path.join(_SAMPLES_DIR, safe)
    if not safe.lower().endswith((".step", ".stp")) or not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Sample not found.")
    return FileResponse(path, filename=safe, media_type="application/octet-stream")


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


@app.get("/api/machines")
def machines():
    """Machine library for the machine selector (India/ME market + defaults)."""
    return {"machines": _machines_library()}


@app.get("/api/materials")
def materials():
    """Material list for the cut-config selector."""
    return {
        "materials": [
            {
                "name": m.get("name"),
                "density": m.get("density"),
                "machinability_factor": m.get("machinability_factor"),
                "safety_factor": m.get("safety_factor"),
            }
            for m in get_default_materials()
        ]
    }


def _tool_display(t: dict) -> dict:
    """Catalog-style presentation fields derived from the tool record.

    Presentation only — the engine keeps using the raw library fields.
    Flute counts / tip angle are standard defaults per tool type, shown
    so the table reads like a real tool catalog.
    """
    ttype = str(t.get("tool_type") or "")
    dia = float(t.get("diameter_mm") or 0)
    tl = ttype.lower()
    if "drill" in tl and "spot" not in tl:
        flutes, tip = 2, "135°"
        name = f"{dia:g}mm Drill {tip}"
    elif "spot" in tl:
        flutes, tip = 2, "90°"
        name = f"{dia:g}mm Spot Drill {tip}"
    elif "face" in tl:
        flutes, tip = 6, None
        name = f'{dia:g}mm {flutes}F Face Mill'
    elif "tap" in tl:
        flutes, tip = 2, None
        name = f"{dia:g}mm Tap RH"
    elif "chamfer" in tl:
        flutes, tip = 4, "90°"
        name = f"{dia:g}mm Chamfer Mill {tip}"
    elif "bor" in tl:
        flutes, tip = 1, None
        name = f"{dia:g}mm Boring Bar"
    else:  # end mills, slot drills
        flutes, tip = 3, None
        name = f"{dia:g}mm {flutes}F Flat Endmill"
    return {"display_name": name, "flutes": flutes, "tip_angle": tip}


@app.get("/api/tools")
def tools_list():
    """Tool library for the Tool Table panel."""
    return {
        "tools": [
            {
                "tool_number": t.get("tool_number"),
                "tool_name": t.get("tool_name"),
                "tool_type": t.get("tool_type"),
                "diameter_mm": t.get("diameter_mm"),
                "flute_length_mm": t.get("flute_length_mm"),
                "max_depth_mm": t.get("max_depth_mm"),
                **_tool_display(t),
                "source_library": (
                    "Default Shop Library (Metric)"
                    if (t.get("tool_number") or 0) < 100
                    else "Extended Metric Library"
                ),
            }
            for t in _extended_tools()
        ]
    }


@app.post("/api/analyze")
async def analyze(
    file: UploadFile = File(...),
    material: str | None = None,
    machine: str | None = None,
    machine_json: str | None = Form(default=None),
):
    """Single entry point: parse a STEP file and return the full overview
    (dimensions, topology, detected features, machinability, mesh, and a
    weldment flag). Everything the Overview screen needs, in one call."""
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty file.")

    parse = parse_step_auto(data)
    if not parse.get("success"):
        raise HTTPException(status_code=400, detail=parse.get("message", "Parse failed."))

    tools, mat, mach = _default_context(material, machine, machine_json)
    candidates = parse.get("candidate_features", [])
    dfm = compute_dfm_score(candidates, tools, mat, mach)
    mesh, face_areas = _tessellate(data)
    msa_pct = _machinable_surface_pct(candidates, dfm, face_areas)
    solids = parse.get("solids_count") or 1

    # Stock sizing: automatic preset = part envelope + per-side allowance
    _L = parse.get("length_mm") or 0
    _W = parse.get("width_mm") or 0
    _H = parse.get("height_mm") or 0
    _allow = 5.0
    stock_block = {
        "mode": "Automatic",
        "preset": "Default Stock (+5 mm/side)",
        "allowance_mm": _allow,
        "size_mm": {
            "length": round(_L + 2 * _allow, 2),
            "width": round(_W + 2 * _allow, 2),
            "height": round(_H + 2 * _allow, 2),
        },
    }

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
        "machinable_surface_pct": msa_pct,
        "stock": stock_block,
        "hole_groups": _hole_groups(candidates),
        "setups": [
            {
                "label": lbl,
                **recommend_workholding(
                    {
                        "length": parse.get("length_mm"),
                        "width": parse.get("width_mm"),
                        "height": parse.get("height_mm"),
                    },
                    lbl,
                ),
            }
            for lbl in sorted({
                (c.get("setup") or c.get("setup_label") or "Top")
                for c in candidates
            })
        ],
        "is_multibody": solids > 1,
        "mesh": mesh,
        "material": mat.get("name"),
        "machine": mach.get("name"),
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
async def strategy(
    file: UploadFile = File(...),
    material: str | None = None,
    body_index: int | None = None,
    machine: str | None = None,
    machine_json: str | None = Form(default=None),
):
    """Operation plan grouped by setup with per-op tool + cycle time —
    the Strategy screen's data. With body_index, the plan is scoped to
    that solid's candidates (same body-scope filter the review UI uses)."""
    data = await file.read()
    parse = parse_step_auto(data)
    if not parse.get("success"):
        raise HTTPException(status_code=400, detail=parse.get("message", "Parse failed."))

    tools, mat, mach = _default_context(material, machine, machine_json)
    candidates = parse.get("candidate_features", [])

    scoped_to = None
    if body_index is not None:
        bbox = _body_bbox(data, body_index)
        if bbox is None:
            raise HTTPException(status_code=400, detail=f"Body {body_index + 1} not found.")
        candidates = filter_candidates_to_body(candidates, {"bbox": bbox})
        scoped_to = body_index
    features = []
    geo_by_name: dict = {}
    for i, c in enumerate(candidates):
        name = c.get("feature_name") or f"Feature {i + 1}"
        features.append({
            "feature_type": c.get("feature_type", ""),
            "feature_name": name,
            "diameter": c.get("diameter") or 0,
            "length": c.get("length") or 0,
            "width": c.get("width") or 0,
            "depth": c.get("depth") or 0,
            "x_pos": c.get("x_pos", 0) or 0,
            "y_pos": c.get("y_pos", 0) or 0,
            "setup_label": c.get("setup") or c.get("setup_label") or "Top",
        })
        # Raw-CAD-frame geometry for 3D highlighting (same frame as the mesh).
        cad = c.get("cad_position") or {}
        geo_by_name[name] = {
            "x": cad.get("x", c.get("x_pos")),
            "y": cad.get("y", c.get("y_pos")),
            "z": cad.get("z"),
            "diameter": c.get("diameter") or 0,
            "length": c.get("length") or 0,
            "width": c.get("width") or 0,
            "depth": c.get("depth") or 0,
            "feature_type": c.get("feature_type", ""),
        }
    ops = plan_operations(features, tools, mat, mach)
    per_op = estimate_time_per_operation(ops, mach, mat)
    totals = estimate_time(ops, mach, mat, features)

    def _base_feature(name: str) -> str:
        return name.replace(" (Rough)", "").replace(" (Finish)", "")

    # Catalog-style tool display per tool number (presentation only)
    tool_disp = {
        t.get("tool_number"): _tool_display(t).get("display_name")
        for t in tools
    }
    op_tool_num = {op.get("op_num"): op.get("tool_number") for op in ops}

    # Group per-op rows by setup, preserving first-appearance order
    setups: list = []
    index: dict = {}
    for row in per_op:
        row["geo"] = geo_by_name.get(_base_feature(row.get("feature", "")))
        row["tool_display"] = tool_disp.get(op_tool_num.get(row.get("op_num"))) or row.get("tool")
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
        "material": mat.get("name"),
        "machine": mach.get("name"),
        "scoped_body_index": scoped_to,
        "scoped_candidate_count": len(candidates) if scoped_to is not None else None,
    }
