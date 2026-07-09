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
from modules.turning_planner import plan_turning_operations, turning_summary

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


_MIN_DRILL_DIA = 3.0    # smallest drill in the extended library
_MIN_SLOT_WIDTH = 4.0   # smallest endmill that can enter a slot


def _validated_msa(file_bytes: bytes) -> dict | None:
    """Assembly-level machinable-surface % from VALIDATED per-body geometry.

    The billet-path formula punishes weldments for phantom blocked features
    (SLIDE BASE read 42.8%). This walks every solid once and classifies each
    face: planar/cone/torus and classifier-typed hole/slot faces are
    3-axis-machinable; hole faces under the minimum drill, slot faces under
    the minimum endmill, and freeform (BSPLINE etc.) faces are excluded and
    listed. Returns {"pct", "method", "exclusions", "per_body"} or None.
    """
    tmp_path = None
    try:
        import cadquery as cq
        from modules.weldment.slot_hole_classifier import classify_cylindrical_faces
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        solids = cq.importers.importStep(tmp_path).val().Solids()
        total_area = 0.0
        blocked_area = 0.0
        exclusions: list = []
        per_body: list = []
        # Validated assembly-wide plannability (replaces the billet DFM
        # grade that read 19%/D on weldments): every classified hole within
        # the drill range and every slot the smallest endmill can enter is
        # plannable; facing on each body is always plannable.
        _feat_total = 0
        _feat_plannable = 0
        for bi, solid in enumerate(solids):
            faces = solid.Faces()
            bb = solid.BoundingBox()
            cls = classify_cylindrical_faces(faces, bbox={
                "xmin": bb.xmin, "xmax": bb.xmax, "ymin": bb.ymin,
                "ymax": bb.ymax, "zmin": bb.zmin, "zmax": bb.zmax,
            })
            cats = cls.get("face_categories", {}) if cls.get("available") else {}
            if cls.get("available"):
                for h in cls.get("holes", []):
                    _feat_total += 1
                    if _MIN_DRILL_DIA <= (h.get("diameter_mm") or 0) <= 60.0:
                        _feat_plannable += 1
                for s in cls.get("slots", []):
                    _feat_total += 1
                    if (s.get("width_mm") or 0) >= _MIN_SLOT_WIDTH:
                        _feat_plannable += 1
            _feat_total += 1        # facing — every body gets faced
            _feat_plannable += 1
            b_total = b_blocked = 0.0
            b_notes: list = []
            for fi, face in enumerate(faces):
                try:
                    area = face.Area()
                except Exception:
                    continue
                b_total += area
                try:
                    gt = face.geomType()
                except Exception:
                    gt = "OTHER"
                if gt in ("PLANE", "CONE", "TORUS"):
                    continue  # machinable by facing/drill-tip/fillet tooling
                if gt == "CYLINDER":
                    cat = cats.get(fi)
                    try:
                        from modules.weldment.slot_hole_classifier import _cyl_data
                        rad = (_cyl_data(face) or {}).get("radius") or 0.0
                    except Exception:
                        rad = 0.0
                    dia = 2.0 * rad
                    if cat == "hole" and 0 < dia < _MIN_DRILL_DIA:
                        b_blocked += area
                        b_notes.append(f"Ø{dia:.1f} hole below Ø{_MIN_DRILL_DIA:g} min drill")
                    elif cat == "slot" and 0 < dia < _MIN_SLOT_WIDTH:
                        b_blocked += area
                        b_notes.append(f"{dia:.1f} mm slot below {_MIN_SLOT_WIDTH:g} mm min endmill")
                    continue  # typed or large cylinders are machinable
                # Freeform and everything else: excluded from 3-axis MSA
                b_blocked += area
                b_notes.append(f"{gt.lower()} face")
            total_area += b_total
            blocked_area += b_blocked
            if b_total > 0:
                per_body.append({
                    "body_index": bi,
                    "pct": round(100.0 * (1 - b_blocked / b_total), 1),
                })
            if b_notes:
                from collections import Counter
                counted = Counter(b_notes)
                exclusions.append(
                    f"Body {bi + 1}: "
                    + ", ".join(f"{n}× {k}" if n > 1 else k
                                for k, n in counted.most_common(4))
                )
        if total_area <= 0:
            return None
        return {
            "pct": round(100.0 * (1 - blocked_area / total_area), 1),
            "method": "validated_classifier",
            "exclusions": exclusions[:12],
            "per_body": per_body,
            "plannable_pct": (
                round(100.0 * _feat_plannable / _feat_total, 1)
                if _feat_total > 0 else None
            ),
            "feature_totals": {"total": _feat_total, "plannable": _feat_plannable},
        }
    except Exception:
        return None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _body_bbox(file_bytes: bytes, body_index: int, classify: bool = False):
    """Bounding box of one solid (cheap, no tessellation). With classify=True
    also returns the exact cylinder classification (holes/slots) AND the
    solid itself (for per-feature face tessellation)."""
    tmp_path = None
    try:
        import cadquery as cq
        from modules.weldment.slot_hole_classifier import classify_cylindrical_faces
        with tempfile.NamedTemporaryFile(suffix=".step", delete=False) as tmp:
            tmp.write(file_bytes)
            tmp_path = tmp.name
        solids = cq.importers.importStep(tmp_path).val().Solids()
        if body_index < 0 or body_index >= len(solids):
            return (None, None, None) if classify else None
        bb = solids[body_index].BoundingBox()
        bbox = {"xmin": bb.xmin, "xmax": bb.xmax, "ymin": bb.ymin,
                "ymax": bb.ymax, "zmin": bb.zmin, "zmax": bb.zmax}
        if not classify:
            return bbox
        cls = classify_cylindrical_faces(solids[body_index].Faces(), bbox=bbox)
        return bbox, cls, solids[body_index]
    except Exception:
        return (None, None, None) if classify else None
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


# ISO metric coarse tap-drill sizes. A hole whose pilot diameter sits on
# one of these (±0.12 mm) is LIKELY a tapped hole — an inference, not
# thread detection (STEP carries no thread data). Display-only for now.
_TAP_DRILL = [
    (2.5, "M3"), (3.3, "M4"), (4.2, "M5"), (5.0, "M6"), (6.8, "M8"),
    (8.5, "M10"), (10.2, "M12"), (12.0, "M14"), (14.0, "M16"),
    (15.5, "M18"), (17.5, "M20"),
]


def _thread_likely(diameter_mm, cbore_diameter_mm=None) -> str | None:
    """Likely metric tap for a pilot diameter, or None. Counterbored holes
    are fastener clearance holes, never tapped."""
    if not diameter_mm or cbore_diameter_mm:
        return None
    for drill, tap in _TAP_DRILL:
        if abs(diameter_mm - drill) <= 0.12:
            return tap
    return None


def _setup_from_dir(direction, signed: bool = False) -> str:
    """Map a hole/slot axis direction to a face-setup label.

    signed=True names the actual entry face (six-way: Top/Bottom,
    Front/Back, Right/Left) — the direction is the OUTWARD normal of the
    face the tool enters from. signed=False keeps the legacy abs-dominant
    three-way labels."""
    ax = [abs(direction[0]), abs(direction[1]), abs(direction[2])]
    k = ax.index(max(ax))
    if not signed:
        return ["Right", "Front", "Top"][k]
    pos = direction[k] >= 0
    return [("Right", "Left"), ("Front", "Back"), ("Top", "Bottom")][k][0 if pos else 1]


def _exact_body_features(cls: dict, scoped_candidates: list) -> list:
    """Feature list for planning built from VALIDATED cylinder geometry.

    The billet-path detector on fabricated assemblies emits many phantom
    slots and misses seam-split holes (audited on SLIDE BASE body 28:
    42 slot candidates of which 40 false, 2 of 22 holes found). Holes and
    slots therefore come from the exact classifier; billet candidates are
    kept only for feature types the classifier does not cover (facing,
    pockets, steps, chamfers, edge milling).
    """
    features = []
    for i, h in enumerate(cls.get("holes", []), start=1):
        name = f"Hole Ø{h['diameter_mm']:.2f} mm #{i}"
        if h.get("cbore_diameter_mm"):
            name = (
                f"Hole Ø{h['diameter_mm']:.2f} mm "
                f"(cbore Ø{h['cbore_diameter_mm']:.2f}) #{i}"
            )
        # Route by the SIGNED entry direction (which face the tool enters
        # from), not the unsigned axis — a +Y hole and a -Y hole need
        # opposite setups.
        entry = h.get("entry_dir") or h.get("dir", (0, 0, 1))
        features.append({
            "feature_type": "Hole",
            "feature_name": name,
            "diameter": h["diameter_mm"],
            "length": 0, "width": 0,
            "depth": h["depth_mm"],
            "x_pos": h["x"], "y_pos": h["y"],
            "setup_label": _setup_from_dir(entry, signed=True),
            "_exact": {"x": h["x"], "y": h["y"], "z": h["z"]},
            "_face_indices": h.get("face_indices") or [],
            "_geometry": {
                "kind": "hole",
                "diameter_mm": h["diameter_mm"],
                "cbore_diameter_mm": h.get("cbore_diameter_mm"),
                "depth_mm": h["depth_mm"],
                "ld_ratio": h.get("ld_ratio"),
                "through": h.get("through"),
                "depth_below_top_mm": h.get("depth_below_top_mm"),
                "tip_angle_deg": h.get("tip_angle_deg"),
                "countersink": h.get("countersink"),
                "axis_dir": list(h.get("dir") or ()) or None,
                "entry_dir": list(h.get("entry_dir") or ()) or None,
                # Gap-v5 B4 "Hole Cone Deviation": a shallow blind hole (L/D<0.3)
                # can't take a full 118° drill point — the cone would be deeper
                # than the feature. Flag the auto-upgrade to a 140° (near-flat)
                # tip so the drill card shows "118° -> 140°".
                "cone_deviation": (
                    {"original_deg": 118, "modified_deg": 140}
                    if (
                        h.get("through") is False
                        and (h.get("ld_ratio") or 1.0) > 0
                        and (h.get("ld_ratio") or 1.0) < 0.3
                    )
                    else None
                ),
                "thread_likely": _thread_likely(
                    h["diameter_mm"], h.get("cbore_diameter_mm")
                ),
            },
        })
    for i, s in enumerate(cls.get("slots", []), start=1):
        # Gap-v5 A1: a slot's setup is the face its cutter ENTERS through.
        # For an OPEN slot the tool comes in through the opening, so route by
        # open_dir — this matches the card's "Opens toward" and splits slots
        # that open different ways (Left/Top/Bottom/Right) into their own
        # setups instead of collapsing them onto the shared cap-axis (which
        # made four differently-opening slots all land in one BACK setup).
        # A closed slot is cut from its cap-axis entry side.
        if s.get("open") and s.get("open_dir"):
            entry = s["open_dir"]
        else:
            entry = s.get("entry_dir") or s.get("axis_dir") or (0, 0, 1)
        features.append({
            "feature_type": "Slot",
            "feature_name": (
                f"Slot {s['length_mm']:.2f}×{s['width_mm']:.2f} mm"
                f"{' (open)' if s.get('open') else ''} #{i}"
            ),
            "diameter": 0,
            "length": s["length_mm"], "width": s["width_mm"],
            "depth": s.get("depth_mm") or 0,
            "x_pos": s.get("x", 0), "y_pos": s.get("y", 0),
            "setup_label": _setup_from_dir(entry, signed=True),
            "_exact": {"x": s.get("x"), "y": s.get("y"), "z": s.get("z")},
            "_face_indices": s.get("face_indices") or [],
            "_geometry": {
                "kind": "slot",
                "open": bool(s.get("open")),
                "length_mm": s["length_mm"],
                "width_mm": s["width_mm"],
                # Largest endmill that can enter the slot (C4 tool-bounds)
                "max_tool_dia_mm": s["width_mm"],
                "depth_mm": s.get("depth_mm"),
                "axis_dir": list(s.get("axis_dir") or ()) or None,
                "open_dir": list(s.get("open_dir") or ()) or None,
                "entry_dir": list(s.get("entry_dir") or ()) or None,
                "opens_toward": (
                    _setup_from_dir(s["open_dir"], signed=True)
                    if s.get("open_dir") else None
                ),
            },
        })
    _cyl_types = {"slot", "hole", "large hole / boring"}
    for c in scoped_candidates:
        if (c.get("feature_type") or "").lower() in _cyl_types:
            continue
        features.append({
            "feature_type": c.get("feature_type", ""),
            "feature_name": c.get("feature_name") or "Feature",
            "diameter": c.get("diameter") or 0,
            "length": c.get("length") or 0,
            "width": c.get("width") or 0,
            "depth": c.get("depth") or 0,
            "x_pos": c.get("x_pos", 0) or 0,
            "y_pos": c.get("y_pos", 0) or 0,
            "setup_label": c.get("setup") or c.get("setup_label") or "Top",
            "_candidate": c,
        })
    return features


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


def _cand_float(c: dict, *keys) -> float:
    for k in keys:
        v = c.get(k)
        if isinstance(v, (int, float)):
            return float(v)
    return 0.0


def _same_location(a: dict, b: dict) -> bool:
    """Two noisy detections of the same physical place — ported from the
    review UI's _same_review_location (proximity scaled by feature size)."""
    ax, ay = _cand_float(a, "x_pos", "center_x"), _cand_float(a, "y_pos", "center_y")
    bx, by = _cand_float(b, "x_pos", "center_x"), _cand_float(b, "y_pos", "center_y")
    az, bz = _cand_float(a, "z_pos", "center_z"), _cand_float(b, "z_pos", "center_z")
    length = max(_cand_float(a, "length"), _cand_float(b, "length"))
    width = max(_cand_float(a, "width"), _cand_float(b, "width"))
    depth = max(_cand_float(a, "depth"), _cand_float(b, "depth"))
    long_tol = max(3.0, length * 0.12)
    short_tol = max(3.0, width * 1.5)
    z_tol = max(3.0, depth * 0.35)
    dx, dy, dz = abs(ax - bx), abs(ay - by), abs(az - bz)
    same_xy = (dx <= long_tol and dy <= short_tol) or (dx <= short_tol and dy <= long_tol)
    return same_xy and dz <= z_tol


def _group_candidates_for_planning(candidates: list) -> list:
    """One representative per physical feature — mirrors the review UI's
    grouping: bucket by (type, dims rounded to 0.1), then keep one member
    per approximate location within each bucket. Kills the duplicate
    detections that inflate raw-basis estimates."""
    buckets: dict = {}
    order: list = []
    for c in candidates:
        key = (
            c.get("feature_type") or "?",
            round(float(c.get("diameter") or 0), 1),
            round(float(c.get("length") or 0), 1),
            round(float(c.get("width") or 0), 1),
            round(float(c.get("depth") or 0), 1),
        )
        if key not in buckets:
            buckets[key] = []
            order.append(key)
        buckets[key].append(c)

    kept = []
    for key in order:
        reps: list = []
        for m in buckets[key]:
            if any(_same_location(m, r) for r in reps):
                continue
            reps.append(m)
        kept.extend(reps or buckets[key])
    return kept


def _default_context(
    material_name: str | None = None,
    machine_name: str | None = None,
    machine_json: str | None = None,
    material_json: str | None = None,
):
    materials = get_default_materials()
    material = materials[0]
    if material_json:
        try:
            mj = json.loads(material_json)
            if mj.get("name"):
                material = {
                    "name": mj["name"],
                    "density": float(mj.get("density") or 2.7),
                    "machinability_factor": float(mj.get("machinability_factor") or 1.0),
                    "safety_factor": float(mj.get("safety_factor") or 1.2),
                }
        except Exception:
            pass
    elif material_name:
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
    material_json: str | None = Form(default=None),
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

    tools, mat, mach = _default_context(material, machine, machine_json, material_json)
    candidates = parse.get("candidate_features", [])
    dfm = compute_dfm_score(candidates, tools, mat, mach)
    mesh, face_areas = _tessellate(data)
    msa_pct = _machinable_surface_pct(candidates, dfm, face_areas)
    solids = parse.get("solids_count") or 1

    # Multibody parts: the billet-path MSA counts phantom blocked features
    # on fabricated assemblies. Replace with the validated per-body surface
    # walk; keep the billet number as fallback when the walk fails.
    msa_detail = None
    if solids > 1:
        msa_detail = _validated_msa(data)
        if msa_detail:
            msa_pct = msa_detail["pct"]

    # Turned-part summary (Epic 20 v1): planned lathe minutes for the
    # Route tab's Turning block. Empty for pure milling parts.
    _turn_cands = [c for c in candidates if (c.get("feature_type") or "") in
                   ("OD Turning", "ID Turning / Bore", "ID Groove")]
    turning_block = None
    if _turn_cands:
        _dims = sorted([parse.get("length_mm") or 0.0,
                        parse.get("width_mm") or 0.0,
                        parse.get("height_mm") or 0.0])
        _t_ops = plan_turning_operations(
            _turn_cands, mat,
            part_length_mm=_dims[2], part_max_od_mm=_dims[1],
        )
        turning_block = turning_summary(_t_ops)

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
        "machinable_surface_detail": msa_detail,
        "turning": turning_block,
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
        raw = bodies_raw.get(rep.body_index) or {}
        # Depth-carrying feature brief for the Bodies row (tester: "depth
        # appears in the Bodies panel for every hole and slot") + likely-tap
        # census from the pilot-diameter inference.
        _brief: list = []
        _likely = 0
        from collections import Counter as _Counter
        _hole_keys = _Counter()
        for h in raw.get("holes") or []:
            dia = h.get("diameter_mm") or 0
            cb = h.get("cbore_diameter_mm")
            dep = h.get("depth_mm") or 0
            _hole_keys[(dia, cb, dep)] += 1
            if _thread_likely(dia, cb):
                _likely += 1
        for (dia, cb, dep), n in _hole_keys.most_common(6):
            _brief.append(
                f"{n}× Ø{dia:g}{f'/cb Ø{cb:g}' if cb else ''} × {dep:g} deep"
            )
        _slot_keys = _Counter()
        for s in raw.get("slots") or []:
            _slot_keys[(s.get("length_mm") or 0, s.get("width_mm") or 0,
                        s.get("depth_mm") or 0)] += 1
        for (L, W, D), n in _slot_keys.most_common(4):
            _brief.append(f"{n}× slot {L:g}×{W:g} × {D:g} deep")
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
            "mesh": raw.get("mesh_data"),
            # Feature-typed content per body (tester A1 v1): validated
            # classifier counts for the representative body.
            "feature_counts": {
                "holes": raw.get("hole_count", 0),
                "slots": raw.get("slot_count", 0),
                "fillet_faces": raw.get("fillet_faces", 0),
                "chamfer_faces": raw.get("chamfer_faces", 0),
                "likely_threaded": _likely,
            } if raw.get("cyl_classifier_available") else None,
            # Dimensioned hole/slot lines incl. DEPTH for the Bodies row
            "features_brief": _brief or None,
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
    basis: str = "raw",
    machine_json: str | None = Form(default=None),
    material_json: str | None = Form(default=None),
):
    """Operation plan grouped by setup with per-op tool + cycle time —
    the Strategy screen's data. With body_index, the plan is scoped to
    that solid's candidates (same body-scope filter the review UI uses)."""
    data = await file.read()
    parse = parse_step_auto(data)
    if not parse.get("success"):
        raise HTTPException(status_code=400, detail=parse.get("message", "Parse failed."))

    tools, mat, mach = _default_context(material, machine, machine_json, material_json)
    candidates = parse.get("candidate_features", [])
    if basis == "grouped":
        candidates = _group_candidates_for_planning(candidates)

    scoped_to = None
    feature_source = "billet_candidates"
    exact_features: list | None = None
    bbox = None
    body_cls = None
    body_solid = None
    if body_index is not None:
        bbox, body_cls, body_solid = _body_bbox(data, body_index, classify=True)
        if bbox is None:
            raise HTTPException(status_code=400, detail=f"Body {body_index + 1} not found.")
        candidates = filter_candidates_to_body(candidates, {"bbox": bbox})
        scoped_to = body_index
        # Holes/slots from VALIDATED cylinder geometry (audited: the billet
        # detector on weldments plans phantom slots and misses seam-split
        # holes). basis=raw keeps the old path for comparison.
        if basis == "grouped" and body_cls and body_cls.get("available"):
            exact_features = _exact_body_features(body_cls, candidates)
            feature_source = "exact_classifier"

    features = []
    geo_by_name: dict = {}
    if exact_features is not None:
        # Exact classifier features have no analyze-candidate to borrow face
        # meshes from — tessellate their own faces so the viewer can drape
        # the real geometry instead of falling back to the locator ring.
        _body_faces = body_solid.Faces() if body_solid is not None else []

        def _face_meshes_for(indices: list) -> list | None:
            import math as _math
            meshes = []
            for fi in indices:
                if not isinstance(fi, int) or fi < 0 or fi >= len(_body_faces):
                    continue
                try:
                    f_verts, f_tris = _body_faces[fi].tessellate(0.5)
                    if not f_verts or not f_tris:
                        continue
                    xs = [v.x for v in f_verts]
                    ys = [v.y for v in f_verts]
                    zs = [v.z for v in f_verts]
                    # OCC tessellation can emit NaN vertices; one NaN poisons
                    # the three.js bounding sphere and blanks the whole scene.
                    if not all(_math.isfinite(c) for c in xs + ys + zs):
                        continue
                    meshes.append({
                        "x": xs, "y": ys, "z": zs,
                        "i": [t[0] for t in f_tris],
                        "j": [t[1] for t in f_tris],
                        "k": [t[2] for t in f_tris],
                    })
                except Exception:
                    continue
            return meshes or None

        def _slot_extra_faces(f) -> list:
            """Planar wall/floor faces inside a slot's volume — the cylinder
            cap alone is a 5 mm sliver that vanishes at plate scale."""
            g = f.get("_geometry") or {}
            if g.get("kind") != "slot" or body_solid is None:
                return []
            ex = f.get("_exact") or {}
            cx, cy, cz = ex.get("x") or 0, ex.get("y") or 0, ex.get("z") or 0
            ax = g.get("axis_dir") or [0, 0, 1]
            half_lat = (max(g.get("length_mm") or 0, g.get("width_mm") or 0)) / 2 + 1.5
            half_ax = (g.get("depth_mm") or 0) / 2 + 1.5
            extra = []
            for fi, face in enumerate(_body_faces):
                try:
                    if face.geomType() != "PLANE":
                        continue
                    c = face.Center()
                    d = (c.x - cx, c.y - cy, c.z - cz)
                    along = abs(d[0] * ax[0] + d[1] * ax[1] + d[2] * ax[2])
                    lat = (sum(v * v for v in d) - along * along) ** 0.5
                    if along <= half_ax and lat <= half_lat:
                        extra.append(fi)
                    if len(extra) >= 8:
                        break
                except Exception:
                    continue
            return extra

        for f in exact_features:
            features.append({k: v for k, v in f.items() if not k.startswith("_")})
            ex = f.get("_exact") or {}
            cand = f.get("_candidate") or {}
            cad = cand.get("cad_position") or {}
            geo_by_name[f["feature_name"]] = {
                "x": ex.get("x", cad.get("x", f.get("x_pos"))),
                "y": ex.get("y", cad.get("y", f.get("y_pos"))),
                "z": ex.get("z", cad.get("z")),
                "diameter": f.get("diameter") or 0,
                "length": f.get("length") or 0,
                "width": f.get("width") or 0,
                "depth": f.get("depth") or 0,
                "feature_type": f.get("feature_type", ""),
                "candidate_id": cand.get("candidate_id"),
                # Validated geometry for the op panel's Geometry section:
                # L/D, through/blind, depth below top, drill-tip cone,
                # counterbore, slot opening direction.
                "geometry": f.get("_geometry"),
                # Exact face meshes (raw CAD frame, same as the body mesh)
                # for direct 3D highlighting of classifier features.
                "face_mesh_data": _face_meshes_for(
                    (f.get("_face_indices") or []) + _slot_extra_faces(f)
                ),
            }
    else:
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
                "lathe_facing": bool(c.get("lathe_facing")),
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
                # Lets the UI look up the candidate's exact face meshes
                # (analyze response carries face_mesh_data per candidate).
                "candidate_id": c.get("candidate_id"),
            }
    # Turned regions (19-2/19-3) plan on the lathe, not the mill. Split
    # them out so the milling planner sees only milled work, then append
    # the lathe ops as their own setup group.
    _TURN_TYPES = {"OD Turning", "ID Turning / Bore", "ID Groove"}
    turn_features = [f for f in features if f.get("feature_type") in _TURN_TYPES]
    mill_features = [
        f for f in features
        if f.get("feature_type") not in _TURN_TYPES
        # End faces of a turned part are faced on the lathe (the turning
        # plan includes a Face op) — keep them off the mill to avoid
        # double-counting. Milled flats on turn-mill parts stay.
        and not (turn_features and f.get("lathe_facing"))
    ]

    ops = plan_operations(mill_features, tools, mat, mach)
    per_op = estimate_time_per_operation(ops, mach, mat)
    totals = estimate_time(ops, mach, mat, mill_features)

    turning_ops = []
    turning_sum = None
    if turn_features:
        _pl = parse.get("length_mm") or 0.0
        _pw = parse.get("width_mm") or 0.0
        _ph = parse.get("height_mm") or 0.0
        _dims = sorted([_pl, _pw, _ph])
        turning_ops = plan_turning_operations(
            turn_features, mat,
            part_length_mm=_dims[2],          # longest = turning length
            part_max_od_mm=_dims[1],          # next = diameter envelope
        )
        turning_sum = turning_summary(turning_ops)

    def _base_feature(name: str) -> str:
        for suf in (" (Rough)", " (Finish)", " - wall finish",
                    " - floor finish", " - rough bore", " - finish bore"):
            name = name.replace(suf, "")
        return name

    # Catalog-style tool display per tool number (presentation only)
    tool_disp = {
        t.get("tool_number"): _tool_display(t).get("display_name")
        for t in tools
    }
    op_tool_num = {op.get("op_num"): op.get("tool_number") for op in ops}

    # Group per-op rows by setup, preserving first-appearance order.
    # Each setup carries its own workholding recommendation (C3) sized
    # from the scoped body (or whole part) envelope.
    wh_stock = None
    if body_index is not None and bbox:
        wh_stock = {"length": bbox["xmax"] - bbox["xmin"],
                    "width": bbox["ymax"] - bbox["ymin"],
                    "height": bbox["zmax"] - bbox["zmin"]}
    elif parse.get("length_mm"):
        wh_stock = {"length": parse.get("length_mm") or 0,
                    "width": parse.get("width_mm") or 0,
                    "height": parse.get("height_mm") or 0}
    setups: list = []
    index: dict = {}
    for row in per_op:
        row["geo"] = geo_by_name.get(_base_feature(row.get("feature", "")))
        row["tool_display"] = tool_disp.get(op_tool_num.get(row.get("op_num"))) or row.get("tool")
        label = row["setup"]
        if label not in index:
            index[label] = {"setup_label": label, "ops": [], "subtotal_min": 0.0,
                            "workholding": (
                                recommend_workholding(wh_stock, label)
                                if wh_stock else None
                            )}
            setups.append(index[label])
        index[label]["ops"].append(row)
        index[label]["subtotal_min"] = round(index[label]["subtotal_min"] + row["cut_min"], 2)

    # Lathe ops as their own setup group, shaped like milling rows so the
    # Strategy view renders them without special cases.
    if turning_ops:
        _lrows = []
        for i, top in enumerate(turning_ops, start=1):
            _lrows.append({
                "op_num": 900 + i,
                "operation": top["op"],
                "feature": top["feature"],
                "setup": top["setup"],
                "tool": top["tool"],
                "tool_display": top["tool"],
                "spindle_rpm": top["rpm"],
                "feed_mm_min": round(top["feed_mm_rev"] * top["rpm"], 1),
                "path_mm": top["path_mm"],
                "cut_min": top["cut_min"],
                "blocked": False,
                "geo": None,
                "lathe": True,
                "notes": top.get("notes"),
            })
        setups.append({
            "setup_label": turning_ops[0]["setup"],
            "ops": _lrows,
            "subtotal_min": round(sum(r["cut_min"] for r in _lrows), 2),
            "workholding": {
                "method": "3-Jaw Chuck",
                "jaw_mode": ("Chuck + tailstock centre"
                             if "Tailstock" in turning_ops[0]["setup"]
                             else "Hard jaws"),
                "reason": "Turned part — lathe workholding",
            },
        })

    # Hole stats for the threaded chip ("0 of N holes threaded" until
    # thread detection ships) + validated-geometry MSA when scoped: the
    # phantom-blocked-feature penalty does not apply to exact features.
    hole_stats = None
    msa_scoped = None
    if exact_features is not None:
        n_holes = sum(1 for f in exact_features if f.get("feature_type") == "Hole")
        n_thru = sum(1 for f in exact_features
                     if (f.get("_geometry") or {}).get("through"))
        _likely = [
            (f.get("_geometry") or {}).get("thread_likely")
            for f in exact_features if f.get("feature_type") == "Hole"
        ]
        _likely = [t for t in _likely if t]
        hole_stats = {"total": n_holes, "threaded": 0,
                      "through": n_thru, "blind": n_holes - n_thru,
                      "likely_threaded": len(_likely),
                      "likely_taps": sorted(set(_likely))}
        planned_names = {
            op.get("feature_name") for op in ops
            if not op.get("planning_blocked")
        }
        plannable = sum(
            1 for f in exact_features
            if any(f["feature_name"] in (pn or "") for pn in planned_names)
        )
        if exact_features:
            msa_scoped = round(100.0 * plannable / len(exact_features), 1)

    return {
        "success": True,
        "filename": file.filename,
        "setups": setups,
        "totals": totals,
        "material": mat.get("name"),
        "machine": mach.get("name"),
        "basis": basis,
        "feature_source": feature_source,
        "planned_candidate_count": len(features),
        "scoped_body_index": scoped_to,
        "scoped_candidate_count": len(features) if scoped_to is not None else None,
        "hole_stats": hole_stats,
        "features_plannable_pct": msa_scoped,
        "turning": turning_sum,
        "body_feature_counts": (
            {
                "holes": body_cls.get("hole_count", 0),
                "slots": body_cls.get("slot_count", 0),
                "fillet_faces": body_cls.get("fillet_faces", 0),
                "chamfer_faces": body_cls.get("chamfer_faces", 0),
            }
            if body_index is not None and body_cls and body_cls.get("available")
            else None
        ),
    }
