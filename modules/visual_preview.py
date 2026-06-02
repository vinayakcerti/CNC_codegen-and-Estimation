import plotly.graph_objects as go
import math
import re


# ---------------------------------------------------------------------------
# Feature color palette (public — used by chart legend and UI)
# ---------------------------------------------------------------------------

FEATURE_COLORS = {
    "Face Milling":        "#87CEEB",   # light blue
    "Face milling":        "#87CEEB",
    "Hole":                "#1E90FF",   # dodger blue
    "Large Hole / Boring": "#8B008B",   # dark magenta / purple
    "Large hole / boring": "#8B008B",
    "Slot":                "#FF8C00",   # dark orange
    "Pocket":              "#228B22",   # forest green
    "Step":                "#8B4513",   # saddle brown
    "Chamfer":             "#DA70D6",   # orchid / pink-purple
    "Outer Profile":       "#2F4F4F",   # dark slate gray
}


def _feature_color(ftype):
    """Return the hex color for a feature type (case-insensitive)."""
    direct = FEATURE_COLORS.get(ftype)
    if direct:
        return direct
    ft = ftype.lower()
    if "face mill" in ft:               return "#87CEEB"
    if "large hole" in ft or "boring" in ft: return "#8B008B"
    if "hole" in ft:                    return "#1E90FF"
    if "slot" in ft:                    return "#FF8C00"
    if "pocket" in ft:                  return "#228B22"
    if "step" in ft or "shoulder" in ft: return "#8B4513"
    if "chamfer" in ft:                 return "#DA70D6"
    if "profile" in ft:                 return "#2F4F4F"
    return "#888888"


# ---------------------------------------------------------------------------
# Hover / label helpers
# ---------------------------------------------------------------------------

def _make_hover_text(ft_low, label, diameter, length, width, depth):
    """Return a clean, type-specific hover string for a feature candidate.

    All zero / missing values are omitted gracefully.
    """
    _pfx = "Approx marker: "
    if "large hole" in ft_low or "boring" in ft_low:
        parts = []
        if diameter > 0: parts.append(f"Ø{diameter:.1f} mm")
        if depth    > 0: parts.append(f"depth {depth:.1f} mm")
        return _pfx + ("Bore  " + "  ".join(parts) if parts else label)
    if "hole" in ft_low:
        parts = []
        if diameter > 0: parts.append(f"Ø{diameter:.1f} mm")
        if depth    > 0: parts.append(f"depth {depth:.1f} mm")
        return _pfx + ("Hole  " + "  ".join(parts) if parts else label)
    if "face mill" in ft_low:
        if length > 0 and width > 0:
            return f"{_pfx}Face milling  {length:.1f} × {width:.1f} mm"
        return f"{_pfx}Face milling"
    if "slot" in ft_low:
        dims = [f"{v:.1f}" for v in (length, width, depth) if v > 0]
        return _pfx + (("Slot  " + " × ".join(dims) + " mm") if dims else "Slot")
    if "pocket" in ft_low:
        dims = [f"{v:.1f}" for v in (length, width, depth) if v > 0]
        return _pfx + (("Pocket  " + " × ".join(dims) + " mm") if dims else "Pocket")
    if "step" in ft_low or "shoulder" in ft_low:
        dims = [f"{v:.1f}" for v in (length, width, depth) if v > 0]
        return _pfx + (("Step  " + " × ".join(dims) + " mm") if dims else "Step")
    if "chamfer" in ft_low:
        size = width or depth
        return f"{_pfx}Chamfer  ~{size:.1f} mm" if size > 0 else f"{_pfx}Chamfer"
    return _pfx + label


def _make_short_label(ft_low, diameter, length, width, depth):
    """Return a short string for 3D text label annotations.

    Returns an empty string when no meaningful label can be formed.
    """
    if "large hole" in ft_low or "boring" in ft_low:
        return f"Ø{diameter:.0f}" if diameter > 0 else "Bore"
    if "hole" in ft_low:
        return f"Ø{diameter:.0f}" if diameter > 0 else "Hole"
    if "face mill" in ft_low:
        if length > 0 and width > 0:
            return f"{length:.0f}×{width:.0f}"
        return "Face"
    if "slot" in ft_low:
        dims = [f"{v:.0f}" for v in (length, width, depth) if v > 0]
        return "×".join(dims) if dims else "Slot"
    if "pocket" in ft_low:
        dims = [f"{v:.0f}" for v in (length, width, depth) if v > 0]
        return "×".join(dims) if dims else "Pkt"
    if "step" in ft_low or "shoulder" in ft_low:
        return f"D{depth:.0f}" if depth > 0 else "Step"
    if "chamfer" in ft_low:
        size = width or depth
        return f"~{size:.0f}" if size > 0 else "Chfr"
    return ""


# ---------------------------------------------------------------------------
# Slot / Pocket orientation helpers
# ---------------------------------------------------------------------------

def _parse_xygaps(note):
    """
    Extract (x_gap, y_gap) from a Section-D detection_note.

    The note always contains:
        "X-pair: ... gap=N.NN mm; Y-pair: ... gap=M.MM mm"

    Returns (x_gap, y_gap) as floats, or None if the pattern is absent.
    """
    xm = re.search(r"X-pair:.*?gap=([\d.]+)\s*mm", note)
    ym = re.search(r"Y-pair:.*?gap=([\d.]+)\s*mm", note)
    if xm and ym:
        return float(xm.group(1)), float(ym.group(1))
    return None


def _infer_half_xy(cand, xmin, xmax, ymin, ymax):
    """
    Return (half_x, half_y) — half-spans along X and Y — for drawing a
    Slot or Pocket outline rectangle in the correct orientation.

    Strategy (in order of reliability):
    1. Section D sources ("flat_ended_slot_walls", "paired_internal_walls"):
       parse the detection_note for explicit X-gap and Y-gap.
    2. Section C ("cadquery_face_records", cylinder-ended slots):
       check whether x_pos ± length/2 fits within [xmin, xmax] vs
       y_pos ± length/2 fits within [ymin, ymax].  The orientation
       whose extent exceeds the part bbox is excluded; the one that
       stays within it is used.  Tolerance = 2 mm for tessellation noise.
    3. Fallback: length → X, width → Y (pre-fix behaviour).
    """
    length = float(cand.get("length") or 0)
    width  = float(cand.get("width")  or 0)
    if length <= 0:
        return (25.0, 10.0)

    dsrc = cand.get("detection_source") or ""
    note = cand.get("detection_note")   or ""

    # ── Strategy 1: explicit wall-pair gaps in detection_note ──────────────
    if dsrc in ("flat_ended_slot_walls", "paired_internal_walls"):
        gaps = _parse_xygaps(note)
        if gaps:
            return (gaps[0] / 2, gaps[1] / 2)

    # ── Strategy 2: bounds-fitting for cylinder-ended slots ────────────────
    if dsrc == "cadquery_face_records" and length > width > 0:
        x_pos  = float(cand.get("x_pos") or 0)
        y_pos  = float(cand.get("y_pos") or 0)
        half_l = length / 2
        half_w = width  / 2
        _TOL   = 2.0   # mm — absorb tessellation / floating-point rounding

        x_fits = (xmin is not None and xmax is not None and
                  x_pos - half_l >= xmin - _TOL and
                  x_pos + half_l <= xmax + _TOL)
        y_fits = (ymin is not None and ymax is not None and
                  y_pos - half_l >= ymin - _TOL and
                  y_pos + half_l <= ymax + _TOL)

        if x_fits and not y_fits:
            return (half_l, half_w)   # long axis is X
        if y_fits and not x_fits:
            return (half_w, half_l)   # long axis is Y
        # Both or neither fit — fall through to default

    # ── Strategy 3: fallback (length → X, width → Y) ──────────────────────
    half_l = length / 2 if length > 0 else 25.0
    half_w = width  / 2 if width  > 0 else 10.0
    return (half_l, half_w)


# ---------------------------------------------------------------------------
# Candidate feature marker traces
# ---------------------------------------------------------------------------

def _candidate_marker_traces(candidates, zmax, zmin, show_labels=False,
                              highlight_color=None, suppress_hl_legend=False,
                              xmin=None, xmax=None, ymin=None, ymax=None):
    """
    Build Scatter3d marker traces (and optional text label traces) for
    detected feature candidates.

    Each feature type appears once in the chart legend via legendgroup.
    Clicking the legend entry toggles all markers of that type.

    Markers are placed at z=zmax (top of part) except face-milling bottom
    candidates which go at z=zmin.

    Args:
        candidates        : list of candidate dicts from step_candidates session key
        zmax              : top Z coordinate of the mesh (from mesh vertex extents)
        zmin              : bottom Z coordinate of the mesh
        show_labels       : if True, add a Scatter3d text annotation above each marker
        highlight_color   : when set, ALL candidates are rendered in this color with
                            thicker lines and grouped under the 'highlight' legend entry.
                            Used for the SMW preview-highlight overlay pass.
        suppress_hl_legend: when True with highlight_color, suppress the legend entry
                            (used when a face-highlight trace already claimed it).
        xmin, xmax        : mesh X extents — used by _infer_half_xy for Section C orientation
        ymin, ymax        : mesh Y extents — used by _infer_half_xy for Section C orientation

    Returns:
        list of plotly.graph_objects.Scatter3d traces
    """
    traces = []
    legend_shown = set()
    z_text = zmax + max((zmax - zmin) * 0.08, 3.0)

    _HL             = bool(highlight_color)
    _hl_legend_done = suppress_hl_legend   # True = legend entry already shown elsewhere

    # Line widths — significantly thicker in highlight mode for clear visibility
    _lw_hole   = 10  if _HL else 3
    _lw_face   = 8   if _HL else 2
    _lw_slot   = 8   if _HL else 1.5
    _lw_pocket = 10  if _HL else 3
    _lw_step   = 10  if _HL else 3
    _marker_sz = 20  if _HL else 10

    # Near-black shadow drawn behind the gold line for contrast
    _SHADOW_C = "#111111"
    _SHADOW_W = 5   # extra width beyond the gold line

    for cand in candidates:
        ftype  = cand.get("feature_type", "Unknown")
        ft_low = ftype.lower()
        color  = highlight_color if _HL else _feature_color(ftype)

        x        = float(cand.get("x_pos")    or 0)
        y        = float(cand.get("y_pos")    or 0)
        label    = cand.get("feature_name",   ftype)
        length   = float(cand.get("length")   or 0)
        width    = float(cand.get("width")    or 0)
        depth    = float(cand.get("depth")    or 0)
        diameter = float(cand.get("diameter") or 0)

        if _HL:
            _show_leg  = not _hl_legend_done
            _leg_name  = "Highlighted"
            _leg_group = "highlight"
            _hl_legend_done = True
        else:
            first_of_type = ftype not in legend_shown
            if first_of_type:
                legend_shown.add(ftype)
            _show_leg  = first_of_type
            _leg_name  = ftype
            _leg_group = ftype

        hover = _make_hover_text(ft_low, label, diameter, length, width, depth)

        # ── Hole / Large Hole: circle at zmax ──────────────────────────────
        if "hole" in ft_low or "boring" in ft_low:
            r = (diameter / 2) if diameter > 0 else 5.0
            theta = [math.radians(a) for a in range(0, 370, 10)]
            cx = [x + r * math.cos(t) for t in theta]
            cy = [y + r * math.sin(t) for t in theta]
            if _HL:
                traces.append(go.Scatter3d(
                    x=cx, y=cy, z=[zmax] * len(theta), mode="lines",
                    line=dict(color=_SHADOW_C, width=_lw_hole + _SHADOW_W),
                    name="", legendgroup=_leg_group, showlegend=False, hoverinfo="none",
                ))
            traces.append(go.Scatter3d(
                x=cx, y=cy, z=[zmax] * len(theta),
                mode="lines",
                line=dict(color=color, width=_lw_hole),
                name=_leg_name, legendgroup=_leg_group, showlegend=_show_leg,
                hovertext=hover, hoverinfo="text",
            ))

        # ── Face Milling: filled surface (HL) or dashed rectangle (normal) ──
        elif "face mill" in ft_low:
            z_face = zmin if "bottom" in label.lower() else zmax
            half_l = (length / 2) if length > 0 else 30.0
            half_w = (width  / 2) if width  > 0 else 30.0
            rx = [x - half_l, x + half_l, x + half_l, x - half_l, x - half_l]
            ry = [y - half_w, y - half_w, y + half_w, y + half_w, y - half_w]
            if _HL:
                # Filled gold rectangle so the full face area is visibly highlighted
                fx = [x - half_l, x + half_l, x + half_l, x - half_l]
                fy = [y - half_w, y - half_w, y + half_w, y + half_w]
                traces.append(go.Mesh3d(
                    x=fx, y=fy, z=[z_face] * 4,
                    i=[0, 0], j=[1, 2], k=[2, 3],
                    color=color, opacity=0.65, flatshading=True,
                    name=_leg_name, legendgroup=_leg_group, showlegend=_show_leg,
                    hovertext=hover, hoverinfo="text",
                ))
                # Shadow border
                traces.append(go.Scatter3d(
                    x=rx, y=ry, z=[z_face] * 5, mode="lines",
                    line=dict(color=_SHADOW_C, width=_lw_face + _SHADOW_W),
                    name="", legendgroup=_leg_group, showlegend=False, hoverinfo="none",
                ))
                # Gold border (solid, not dashed)
                traces.append(go.Scatter3d(
                    x=rx, y=ry, z=[z_face] * 5, mode="lines",
                    line=dict(color=color, width=_lw_face),
                    name=_leg_name, legendgroup=_leg_group, showlegend=False,
                    hovertext=hover, hoverinfo="text",
                ))
            else:
                traces.append(go.Scatter3d(
                    x=rx, y=ry, z=[z_face] * 5,
                    mode="lines",
                    line=dict(color=color, width=_lw_face, dash="dash"),
                    name=_leg_name, legendgroup=_leg_group, showlegend=_show_leg,
                    hovertext=hover, hoverinfo="text",
                ))

        # ── Slot: dashed outline at zmax — clearly secondary / fallback marker ──
        elif "slot" in ft_low:
            half_x, half_y = _infer_half_xy(cand, xmin, xmax, ymin, ymax)
            rx = [x - half_x, x + half_x, x + half_x, x - half_x, x - half_x]
            ry = [y - half_y, y - half_y, y + half_y, y + half_y, y - half_y]
            if _HL:
                traces.append(go.Scatter3d(
                    x=rx, y=ry, z=[zmax] * 5, mode="lines",
                    line=dict(color=_SHADOW_C, width=_lw_slot + _SHADOW_W),
                    name="", legendgroup=_leg_group, showlegend=False, hoverinfo="none",
                ))
            traces.append(go.Scatter3d(
                x=rx, y=ry, z=[zmax] * 5,
                mode="lines",
                line=dict(color=color, width=_lw_slot, dash="dash"),
                name=_leg_name, legendgroup=_leg_group, showlegend=_show_leg,
                hovertext=hover, hoverinfo="text",
            ))

        # ── Pocket: solid rectangle outline at zmax ─────────────────────────
        elif "pocket" in ft_low:
            half_x, half_y = _infer_half_xy(cand, xmin, xmax, ymin, ymax)
            rx = [x - half_x, x + half_x, x + half_x, x - half_x, x - half_x]
            ry = [y - half_y, y - half_y, y + half_y, y + half_y, y - half_y]
            if _HL:
                traces.append(go.Scatter3d(
                    x=rx, y=ry, z=[zmax] * 5, mode="lines",
                    line=dict(color=_SHADOW_C, width=_lw_pocket + _SHADOW_W),
                    name="", legendgroup=_leg_group, showlegend=False, hoverinfo="none",
                ))
            traces.append(go.Scatter3d(
                x=rx, y=ry, z=[zmax] * 5,
                mode="lines",
                line=dict(color=color, width=_lw_pocket),
                name=_leg_name, legendgroup=_leg_group, showlegend=_show_leg,
                hovertext=hover, hoverinfo="text",
            ))

        # ── Step / Shoulder: cross marker at (x, y, zmax) ──────────────────
        elif "step" in ft_low or "shoulder" in ft_low:
            arm = 8.0
            sx_pts = [x - arm, x + arm, None, x,       x      ]
            sy_pts = [y,       y,       None, y - arm, y + arm]
            if _HL:
                traces.append(go.Scatter3d(
                    x=sx_pts, y=sy_pts, z=[zmax] * 5, mode="lines",
                    line=dict(color=_SHADOW_C, width=_lw_step + _SHADOW_W),
                    name="", legendgroup=_leg_group, showlegend=False, hoverinfo="none",
                ))
            traces.append(go.Scatter3d(
                x=sx_pts, y=sy_pts, z=[zmax] * 5,
                mode="lines",
                line=dict(color=color, width=_lw_step),
                name=_leg_name, legendgroup=_leg_group, showlegend=_show_leg,
                hovertext=hover, hoverinfo="text",
            ))

        # ── Chamfer: diamond marker at (x, y, zmax) ────────────────────────
        elif "chamfer" in ft_low:
            traces.append(go.Scatter3d(
                x=[x], y=[y], z=[zmax],
                mode="markers",
                marker=dict(
                    size=_marker_sz, color=color, symbol="diamond",
                    line=dict(color=_SHADOW_C, width=3) if _HL else dict(),
                ),
                name=_leg_name, legendgroup=_leg_group, showlegend=_show_leg,
                hovertext=hover, hoverinfo="text",
            ))

        # ── Optional text label floating above the marker ──────────────────
        if show_labels:
            short = _make_short_label(ft_low, diameter, length, width, depth)
            if short:
                z_lbl = (zmin - max((zmax - zmin) * 0.08, 3.0)
                         if "face mill" in ft_low and "bottom" in label.lower()
                         else z_text)
                _lbl_size = 22 if _HL else 16
                traces.append(go.Scatter3d(
                    x=[x], y=[y], z=[z_lbl],
                    mode="text",
                    text=[short],
                    textfont=dict(size=_lbl_size, color=color, family="monospace"),
                    textposition="middle center",
                    name="",
                    legendgroup=_leg_group,
                    showlegend=False,
                    hoverinfo="none",
                ))

    return traces


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stock_box_traces(sx, sy, sz):
    """Return Mesh3d + wireframe Scatter3d traces for the stock bounding box.

    Draws the box from (0,0,0) to (sx, sy, sz).
    Used by build_3d_view() where features are also positioned from 0.
    """
    vx = [0,sx,sx, 0, 0,sx,sx, 0]
    vy = [0, 0,sy,sy, 0, 0,sy,sy]
    vz = [0, 0, 0, 0,sz,sz,sz,sz]
    mesh = go.Mesh3d(
        x=vx, y=vy, z=vz,
        i=[0,0,0,4,4,4,0,1,2,3],
        j=[1,2,4,5,6,7,4,5,6,7],
        k=[2,3,5,6,7,3,1,2,5,6],
        opacity=0.07, color="steelblue", name="Stock", showlegend=False,
    )
    ex, ey, ez = [], [], []
    idx = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    for a, b in idx:
        ex += [vx[a],vx[b],None]; ey += [vy[a],vy[b],None]; ez += [vz[a],vz[b],None]
    wire = go.Scatter3d(
        x=ex, y=ey, z=ez, mode="lines",
        line=dict(color="steelblue", width=1),
        name="Stock outline", showlegend=False,
    )
    return [mesh, wire]


def _stock_box_coords_traces(x0, x1, y0, y1, z0, z1):
    """Return Mesh3d + wireframe Scatter3d for a box defined by explicit min/max coords.

    Used by build_step_mesh3d() where coordinates must match the OCC/CadQuery
    tessellation coordinate system rather than a 0-based span.
    """
    vx = [x0,x1,x1,x0, x0,x1,x1,x0]
    vy = [y0,y0,y1,y1, y0,y0,y1,y1]
    vz = [z0,z0,z0,z0, z1,z1,z1,z1]
    mesh = go.Mesh3d(
        x=vx, y=vy, z=vz,
        i=[0,0,0,4,4,4,0,1,2,3],
        j=[1,2,4,5,6,7,4,5,6,7],
        k=[2,3,5,6,7,3,1,2,5,6],
        opacity=0.10, color="steelblue",
        name="Stock / bounding box", showlegend=True,
    )
    ex, ey, ez = [], [], []
    idx = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    for a, b in idx:
        ex += [vx[a],vx[b],None]; ey += [vy[a],vy[b],None]; ez += [vz[a],vz[b],None]
    wire = go.Scatter3d(
        x=ex, y=ey, z=ez, mode="lines",
        line=dict(color="steelblue", width=1.5, dash="dash"),
        name="", showlegend=False,
    )
    return [mesh, wire]


# ---------------------------------------------------------------------------
# Feature overlay helpers — normal offset + boundary edges
# ---------------------------------------------------------------------------

def _face_avg_normal(verts, tris):
    """Return the average unit normal of a face mesh as (nx, ny, nz).

    Averages per-triangle normals (each weighted equally) then renormalises.
    Falls back to (0, 0, 1) for degenerate meshes.
    """
    nx = ny = nz = 0.0
    for t in tris:
        v0, v1, v2 = verts[t[0]], verts[t[1]], verts[t[2]]
        e1x = v1[0] - v0[0]; e1y = v1[1] - v0[1]; e1z = v1[2] - v0[2]
        e2x = v2[0] - v0[0]; e2y = v2[1] - v0[1]; e2z = v2[2] - v0[2]
        cx = e1y * e2z - e1z * e2y
        cy = e1z * e2x - e1x * e2z
        cz = e1x * e2y - e1y * e2x
        mag = math.sqrt(cx * cx + cy * cy + cz * cz)
        if mag > 0:
            nx += cx / mag; ny += cy / mag; nz += cz / mag
    mag2 = math.sqrt(nx * nx + ny * ny + nz * nz)
    return (nx / mag2, ny / mag2, nz / mag2) if mag2 > 0 else (0.0, 0.0, 1.0)


def _offset_verts(verts, tris, offset_mm):
    """Return vertices shifted by offset_mm along the face average normal."""
    nx, ny, nz = _face_avg_normal(verts, tris)
    return [[v[0] + offset_mm * nx, v[1] + offset_mm * ny, v[2] + offset_mm * nz]
            for v in verts]


def _boundary_edge_coords(verts, tris):
    """Return (xs, ys, zs) of boundary edges (edges belonging to exactly one triangle).

    xs/ys/zs contain None separators between disconnected segments, ready for
    a Scatter3d trace.  Boundary edges form the visible outline of the face.
    """
    from collections import Counter
    edge_cnt = Counter()
    for t in tris:
        for a, b in ((t[0], t[1]), (t[1], t[2]), (t[2], t[0])):
            edge_cnt[tuple(sorted((a, b)))] += 1
    xs, ys, zs = [], [], []
    for (a, b), cnt in edge_cnt.items():
        if cnt == 1:
            xs += [verts[a][0], verts[b][0], None]
            ys += [verts[a][1], verts[b][1], None]
            zs += [verts[a][2], verts[b][2], None]
    return xs, ys, zs


# ---------------------------------------------------------------------------
# Mesh3d solid viewer — CadQuery tessellation data
# ---------------------------------------------------------------------------

def build_step_mesh3d(mesh_data, stock, candidates=None, show_labels=False,
                      show_stock_box=False, show_face_colors=True,
                      show_face_milling=False, show_markers=True,
                      highlighted_candidate_ids=None,
                      part_opacity=1.0,
                      camera_view="Isometric"):
    """
    Build a rotatable Plotly Mesh3d figure from pre-computed tessellation data.

    The base part is rendered as a fully opaque light metallic grey body.
    When candidates carry face_mesh_data, those faces are rendered as colored
    Mesh3d overlays using the feature-type palette.  Face-milling surfaces are
    hidden by default — they cover the entire top/bottom face and obscure the
    base body; show_face_milling=True makes them visible.  Candidates without
    face data fall back to Scatter3d marker shapes (show_markers controls this).

    Args:
        mesh_data        : dict with keys x/y/z (vertex lists) and i/j/k (triangle index lists)
        stock            : dict with length/width/height — retained for signature compatibility
        candidates       : list of candidate dicts; each may carry face_indices / face_mesh_data
        show_labels      : if True, add Scatter3d text annotations above marker candidates
        show_stock_box   : if True, overlay the semi-transparent stock bounding box
        show_face_colors : if True, render candidates that have face_mesh_data as colored faces
        show_face_milling: if True, include face-milling surface overlays (default OFF — they
                           cover the whole top/bottom face and obscure the base body)
        show_markers     : if True, render candidates without face_mesh_data as marker overlays
        part_opacity     : opacity for the base part body, useful when inspecting overlays
        camera_view      : initial camera preset: Isometric, Top, Front, Right

    Returns:
        plotly.graph_objects.Figure
    """
    xs, ys, zs = mesh_data["x"], mesh_data["y"], mesh_data["z"]
    part_opacity = max(0.15, min(float(part_opacity or 1.0), 1.0))

    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)

    # ── Split candidates: highlighted | feature faces | face-milling | markers ──
    _hl_set          = set(highlighted_candidate_ids or [])
    _hl_face_cands   = []   # highlighted with face data — rendered gold on top
    _hl_marker_cands = []   # highlighted without face data — gold marker overlay
    _face_cands      = []   # non-highlighted holes/pockets/chamfers — colored by default
    _face_mill_cands = []   # non-highlighted face-milling — only shown when requested
    _marker_cands    = []   # non-highlighted without face data → approximate marker fallback
    for _cand in (candidates or []):
        _ft  = _cand.get("feature_type", "")
        _cid = _cand.get("candidate_id", "")
        _is_hl = bool(_hl_set) and _cid in _hl_set
        if _is_hl:
            if _cand.get("face_mesh_data"):
                _hl_face_cands.append(_cand)
            else:
                _hl_marker_cands.append(_cand)
        elif show_face_colors and _cand.get("face_mesh_data"):
            if _ft == "Face milling":
                _face_mill_cands.append(_cand)
            else:
                _face_cands.append(_cand)
        else:
            _marker_cands.append(_cand)

    fig = go.Figure()
    _HL_COLOR = "#FFD700"   # gold

    # Normal-offset amount: at least 0.2 mm, or 0.1 % of bounding-box diagonal.
    # This physically moves each overlay face in front of the base mesh surface
    # so the overlay passes the depth test regardless of the comparison mode.
    _bbox_diag = math.sqrt((xmax - xmin) ** 2 + (ymax - ymin) ** 2 + (zmax - zmin) ** 2)
    _offset    = max(0.2, _bbox_diag * 0.001)

    # ── Base solid — rendered first, fully opaque metallic grey ──────────────
    fig.add_trace(go.Mesh3d(
        x=xs, y=ys, z=zs,
        i=mesh_data["i"], j=mesh_data["j"], k=mesh_data["k"],
        color="#DCDCDC",
        opacity=part_opacity,
        flatshading=False,
        lighting=dict(ambient=0.55, diffuse=0.85, specular=0.25,
                      roughness=0.45, fresnel=0.15),
        lightposition=dict(x=1, y=1, z=2),
        name="Part body",
        showlegend=True,
    ))

    if show_stock_box:
        for tr in _stock_box_coords_traces(xmin, xmax, ymin, ymax, zmin, zmax):
            fig.add_trace(tr)

    # ── Colored CAD face overlays — rendered after base, offset outward ───────
    # Each face mesh is shifted _offset mm along its average face normal so the
    # overlay vertices sit physically in front of the base surface.  The depth
    # test then passes for the overlay, making it visible.  Boundary edges are
    # added as thick Scatter3d lines to guarantee the feature outline is always
    # visible even if residual z-fighting affects the filled face.
    if show_face_colors:
        _legend_shown_fc = set()
        _active_fc = _face_cands + (_face_mill_cands if show_face_milling else [])
        for _fc in _active_fc:
            _ftype = _fc.get("feature_type", "Unknown")
            _color = _feature_color(_ftype)
            _fname = _fc.get("feature_name", _ftype)
            for _fm in _fc.get("face_mesh_data", []):
                _verts = _fm.get("vertices", [])
                _tris  = _fm.get("triangles", [])
                if not _verts or not _tris:
                    continue
                _first_fc = _ftype not in _legend_shown_fc
                if _first_fc:
                    _legend_shown_fc.add(_ftype)
                _ov = _offset_verts(_verts, _tris, _offset)
                fig.add_trace(go.Mesh3d(
                    x=[v[0] for v in _ov],
                    y=[v[1] for v in _ov],
                    z=[v[2] for v in _ov],
                    i=[t[0] for t in _tris],
                    j=[t[1] for t in _tris],
                    k=[t[2] for t in _tris],
                    color=_color,
                    opacity=1.0,
                    flatshading=True,
                    lighting=dict(ambient=0.85, diffuse=0.4, specular=0.1,
                                  roughness=0.5, fresnel=0.05),
                    lightposition=dict(x=1, y=1, z=2),
                    name=_ftype,
                    legendgroup=f"face_{_ftype}",
                    showlegend=_first_fc,
                    hovertext=f"CAD face: {_fname}",
                    hoverinfo="text",
                ))
                _bx, _by, _bz = _boundary_edge_coords(_ov, _tris)
                if _bx:
                    fig.add_trace(go.Scatter3d(
                        x=_bx, y=_by, z=_bz,
                        mode="lines",
                        line=dict(color=_color, width=4),
                        name=_ftype,
                        legendgroup=f"face_{_ftype}",
                        showlegend=False,
                        hoverinfo="none",
                    ))

    # ── Highlighted CAD face overlays — 2× offset, always on top ─────────────
    _hl_legend_shown = False
    for _fc in _hl_face_cands:
        _fname = _fc.get("feature_name", _fc.get("feature_type", ""))
        for _fm in _fc.get("face_mesh_data", []):
            _verts = _fm.get("vertices", [])
            _tris  = _fm.get("triangles", [])
            if not _verts or not _tris:
                continue
            _ov_hl = _offset_verts(_verts, _tris, _offset * 2)
            fig.add_trace(go.Mesh3d(
                x=[v[0] for v in _ov_hl],
                y=[v[1] for v in _ov_hl],
                z=[v[2] for v in _ov_hl],
                i=[t[0] for t in _tris],
                j=[t[1] for t in _tris],
                k=[t[2] for t in _tris],
                color=_HL_COLOR,
                opacity=1.0,
                flatshading=True,
                lighting=dict(ambient=0.95, diffuse=0.6, specular=0.7,
                              roughness=0.15, fresnel=0.5),
                lightposition=dict(x=1, y=1, z=2),
                name="Highlighted",
                legendgroup="highlight",
                showlegend=not _hl_legend_shown,
                hovertext=f"Highlighted: {_fname}",
                hoverinfo="text",
            ))
            _hl_legend_shown = True
            _bx, _by, _bz = _boundary_edge_coords(_ov_hl, _tris)
            if _bx:
                fig.add_trace(go.Scatter3d(
                    x=_bx, y=_by, z=_bz,
                    mode="lines",
                    line=dict(color=_HL_COLOR, width=5),
                    name="Highlighted",
                    legendgroup="highlight",
                    showlegend=False,
                    hoverinfo="none",
                ))

    # ── Approximate markers (fallback for candidates without face data) ────────
    if show_markers and _marker_cands:
        for tr in _candidate_marker_traces(
            _marker_cands, zmax, zmin,
            show_labels=show_labels,
            xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
        ):
            fig.add_trace(tr)

    # ── Highlighted marker overlays (shown even when show_markers=False) ──────
    if _hl_marker_cands:
        for tr in _candidate_marker_traces(
            _hl_marker_cands, zmax, zmin,
            show_labels=False,
            highlight_color=_HL_COLOR,
            suppress_hl_legend=_hl_legend_shown,
            xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
        ):
            fig.add_trace(tr)
            if not _hl_legend_shown:
                _hl_legend_shown = True

    # ── Scene layout — CAD-style coloured axes, readable labels ───────────────
    _view = str(camera_view or "Isometric")
    _camera_presets = {
        "Isometric": dict(eye=dict(x=1.45, y=1.45, z=1.15), up=dict(x=0, y=0, z=1)),
        "Top":       dict(eye=dict(x=0.0,  y=0.0,  z=2.25), up=dict(x=0, y=1, z=0)),
        "Front":     dict(eye=dict(x=0.0,  y=-2.2, z=0.35), up=dict(x=0, y=0, z=1)),
        "Right":     dict(eye=dict(x=2.2,  y=0.0,  z=0.35), up=dict(x=0, y=0, z=1)),
    }

    fig.update_layout(
        title=dict(
            text="3D Preview — Part Shape (planning reference only)",
            font=dict(size=15),
        ),
        scene=dict(
            xaxis=dict(
                title=dict(text="X (mm)", font=dict(size=14, color="#CC4444")),
                tickfont=dict(size=11),
                backgroundcolor="rgba(248,240,240,0.4)",
                gridcolor="rgba(200,140,140,0.35)",
                showline=True,
                linecolor="#CC4444",
                linewidth=2,
            ),
            yaxis=dict(
                title=dict(text="Y (mm)", font=dict(size=14, color="#2E8B2E")),
                tickfont=dict(size=11),
                backgroundcolor="rgba(240,248,240,0.4)",
                gridcolor="rgba(140,200,140,0.35)",
                showline=True,
                linecolor="#2E8B2E",
                linewidth=2,
            ),
            zaxis=dict(
                title=dict(text="Z (mm)", font=dict(size=14, color="#1a5fa8")),
                tickfont=dict(size=11),
                backgroundcolor="rgba(240,244,252,0.4)",
                gridcolor="rgba(140,160,210,0.35)",
                showline=True,
                linecolor="#1a5fa8",
                linewidth=2,
            ),
            aspectmode="data",
            camera=_camera_presets.get(_view, _camera_presets["Isometric"]),
        ),
        height=520,
        margin=dict(l=0, r=0, t=55, b=0),
        legend=dict(
            orientation="h",
            x=0.02,
            y=0.02,
            xanchor="left",
            yanchor="bottom",
            font=dict(size=14),
            bgcolor="rgba(255,255,255,0.75)",
            bordercolor="rgba(0,0,0,0.15)",
            borderwidth=1,
        ),
    )
    return fig


def _add_feature_traces_3d(fig, features, sz):
    """Add manually-entered feature annotations on top of the 3D view."""
    for feat in features:
        ftype = feat.get("feature_type", "")
        x     = feat.get("x_pos", 0) or 0
        y     = feat.get("y_pos", 0) or 0
        depth = feat.get("depth", 10) or 10
        dia   = feat.get("diameter", 10) or 10
        qty   = feat.get("quantity", 1) or 1
        flen  = feat.get("length", 20) or 20
        fwid  = feat.get("width", 20) or 20
        name  = feat.get("feature_name", ftype)

        if ftype in ("Hole", "Large Hole / Boring"):
            for i in range(min(qty, 8)):
                xi = x + i * (dia + 5)
                theta = [math.radians(a) for a in range(0, 361, 15)]
                cx = [xi + (dia/2)*math.cos(t) for t in theta]
                cy = [y  + (dia/2)*math.sin(t) for t in theta]
                fig.add_trace(go.Scatter3d(
                    x=cx, y=cy, z=[sz]*len(theta), mode="lines",
                    line=dict(color="red", width=3),
                    name=name if i == 0 else "", showlegend=(i == 0),
                ))
                fig.add_trace(go.Scatter3d(
                    x=cx, y=cy, z=[sz-depth]*len(theta), mode="lines",
                    line=dict(color="darkred", width=1), showlegend=False,
                ))

        elif ftype == "Pocket":
            xs = [x, x+flen, x+flen, x, x]
            ys = [y, y, y+fwid, y+fwid, y]
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=[sz]*5, mode="lines",
                line=dict(color="orange", width=3), name=name,
            ))
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=[sz-depth]*5, mode="lines",
                line=dict(color="darkorange", width=2), showlegend=False,
            ))

        elif ftype == "Face Milling":
            sx2 = feat.get("length", 100) or 100
            sy2 = feat.get("width", 100) or 100
            fig.add_trace(go.Scatter3d(
                x=[0,sx2,sx2,0,0], y=[0,0,sy2,sy2,0], z=[sz]*5,
                mode="lines", line=dict(color="green", width=2, dash="dash"),
                name="Face Mill",
            ))


# ---------------------------------------------------------------------------
# Top view (2D)
# ---------------------------------------------------------------------------

def build_top_view(stock, features, step_geometry=None):
    fig = go.Figure()
    sx = stock.get("length", 100)
    sy = stock.get("width", 100)

    if step_geometry and step_geometry.get("success") and (
            step_geometry.get("line_segments") or step_geometry.get("circle_traces")):

        # ── Render actual STEP wireframe (XY projection) ──────────────────
        # Straight edges
        ex, ey = [], []
        for seg in step_geometry["line_segments"]:
            x1,y1,_,x2,y2,_ = seg
            ex += [x1, x2, None]
            ey += [y1, y2, None]
        if ex:
            fig.add_trace(go.Scatter(
                x=ex, y=ey, mode="lines",
                line=dict(color="#1a5fa8", width=1.5),
                name="STEP edges", showlegend=True,
            ))

        # Circles/arcs
        for i, (px, py, pz) in enumerate(step_geometry["circle_traces"]):
            fig.add_trace(go.Scatter(
                x=list(px), y=list(py), mode="lines",
                line=dict(color="crimson", width=2),
                name="STEP circle" if i == 0 else "",
                showlegend=(i == 0),
            ))

        # Bounding box outline
        fig.add_shape(type="rect", x0=0, y0=0, x1=sx, y1=sy,
                      line=dict(color="steelblue", width=1.5, dash="dash"),
                      fillcolor="rgba(135,206,250,0.05)")
        title = "Top View — Approximate STEP Wireframe (XY projection) — Planning Preview Only"

    else:
        # ── Fallback: bounding box + feature boxes ─────────────────────────
        fig.add_shape(type="rect", x0=0, y0=0, x1=sx, y1=sy,
                      line=dict(color="steelblue", width=2),
                      fillcolor="rgba(135,206,250,0.15)")

        for feat in features:
            ftype = feat.get("feature_type", "")
            x = feat.get("x_pos", sx/2) or sx/2
            y = feat.get("y_pos", sy/2) or sy/2
            qty = feat.get("quantity", 1) or 1
            dia = feat.get("diameter", 10) or 10
            flen = feat.get("length", 20) or 20
            fwid = feat.get("width", 20) or 20

            if ftype in ("Hole", "Large Hole / Boring"):
                for i in range(min(qty, 8)):
                    xi = x + i*(dia+5)
                    theta = [math.radians(a) for a in range(0, 361, 10)]
                    cx = [xi + (dia/2)*math.cos(t) for t in theta]
                    cy = [y  + (dia/2)*math.sin(t) for t in theta]
                    fig.add_trace(go.Scatter(x=cx, y=cy, mode="lines",
                        line=dict(color="red", width=1.5),
                        name=feat["feature_name"] if i == 0 else "",
                        showlegend=(i == 0)))
            elif ftype == "Pocket":
                fig.add_shape(type="rect",
                    x0=x, y0=y, x1=x+flen, y1=y+fwid,
                    line=dict(color="orange", width=2),
                    fillcolor="rgba(255,165,0,0.25)")
            elif ftype == "Slot":
                fig.add_shape(type="rect",
                    x0=x, y0=y-fwid/2, x1=x+flen, y1=y+fwid/2,
                    line=dict(color="purple", width=2),
                    fillcolor="rgba(128,0,128,0.2)")
            elif ftype == "Face Milling":
                fig.add_shape(type="rect", x0=0, y0=0, x1=sx, y1=sy,
                    line=dict(color="green", width=1, dash="dash"),
                    fillcolor="rgba(0,128,0,0.08)")
            elif ftype == "Outer Profile":
                fig.add_shape(type="rect",
                    x0=x, y0=y, x1=x+flen, y1=y+fwid,
                    line=dict(color="navy", width=2, dash="dot"),
                    fillcolor="rgba(0,0,128,0.05)")
        title = "Top View — Approximate Feature Layout — Planning Preview Only"

    pad = max(sx, sy) * 0.12
    fig.update_layout(
        title=title,
        xaxis_title="X (mm)", yaxis_title="Y (mm)",
        xaxis=dict(scaleanchor="y", scaleratio=1, range=[-pad, sx+pad]),
        yaxis=dict(range=[-pad, sy+pad]),
        height=520,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


# ---------------------------------------------------------------------------
# 3D view
# ---------------------------------------------------------------------------

def build_3d_view(stock, features, step_geometry=None):
    fig = go.Figure()
    sx = stock.get("length", 100)
    sy = stock.get("width", 100)
    sz = stock.get("height", 50)

    if step_geometry and step_geometry.get("success") and (
            step_geometry.get("line_segments") or step_geometry.get("circle_traces")):

        # ── Actual STEP wireframe ─────────────────────────────────────────
        # Straight edges — batch into one trace for performance
        ex, ey, ez = [], [], []
        for seg in step_geometry["line_segments"]:
            x1,y1,z1,x2,y2,z2 = seg
            ex += [x1, x2, None]
            ey += [y1, y2, None]
            ez += [z1, z2, None]
        if ex:
            fig.add_trace(go.Scatter3d(
                x=ex, y=ey, z=ez, mode="lines",
                line=dict(color="#1a5fa8", width=2),
                name="STEP edges",
            ))

        # Circular arcs
        for i, (px, py, pz) in enumerate(step_geometry["circle_traces"]):
            fig.add_trace(go.Scatter3d(
                x=list(px), y=list(py), z=list(pz), mode="lines",
                line=dict(color="crimson", width=2.5),
                name="Holes / arcs" if i == 0 else "",
                showlegend=(i == 0),
            ))

        # Light bounding box overlay for spatial reference
        for tr in _stock_box_traces(sx, sy, sz):
            fig.add_trace(tr)

        # Feature overlays on top
        _add_feature_traces_3d(fig, features, sz)

        title = "3D View — Approximate STEP Wireframe — Planning Preview Only"

    else:
        # ── Fallback: bounding box + features ────────────────────────────
        for tr in _stock_box_traces(sx, sy, sz):
            fig.add_trace(tr)
        _add_feature_traces_3d(fig, features, sz)
        title = "3D View — Approximate Feature Layout — Planning Preview Only"

    fig.update_layout(
        title=title,
        scene=dict(
            xaxis_title="X (mm)", yaxis_title="Y (mm)", zaxis_title="Z (mm)",
            aspectmode="data",
            xaxis=dict(backgroundcolor="rgba(240,248,255,0.5)"),
            yaxis=dict(backgroundcolor="rgba(240,248,255,0.5)"),
            zaxis=dict(backgroundcolor="rgba(220,230,240,0.5)"),
        ),
        height=580,
        margin=dict(l=0, r=0, t=60, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=0),
    )
    return fig
