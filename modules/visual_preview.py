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
    if "large hole" in ft_low or "boring" in ft_low:
        parts = []
        if diameter > 0: parts.append(f"Ø{diameter:.1f} mm")
        if depth    > 0: parts.append(f"depth {depth:.1f} mm")
        return "Bore  " + "  ".join(parts) if parts else label
    if "hole" in ft_low:
        parts = []
        if diameter > 0: parts.append(f"Ø{diameter:.1f} mm")
        if depth    > 0: parts.append(f"depth {depth:.1f} mm")
        return "Hole  " + "  ".join(parts) if parts else label
    if "face mill" in ft_low:
        if length > 0 and width > 0:
            return f"Face milling  {length:.1f} × {width:.1f} mm"
        return "Face milling"
    if "slot" in ft_low:
        dims = [f"{v:.1f}" for v in (length, width, depth) if v > 0]
        return ("Slot  " + " × ".join(dims) + " mm") if dims else "Slot"
    if "pocket" in ft_low:
        dims = [f"{v:.1f}" for v in (length, width, depth) if v > 0]
        return ("Pocket  " + " × ".join(dims) + " mm") if dims else "Pocket"
    if "step" in ft_low or "shoulder" in ft_low:
        dims = [f"{v:.1f}" for v in (length, width, depth) if v > 0]
        return ("Step  " + " × ".join(dims) + " mm") if dims else "Step"
    if "chamfer" in ft_low:
        size = width or depth
        return f"Chamfer  ~{size:.1f} mm" if size > 0 else "Chamfer"
    return label


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
                              xmin=None, xmax=None, ymin=None, ymax=None):
    """
    Build Scatter3d marker traces (and optional text label traces) for
    detected feature candidates.

    Each feature type appears once in the chart legend via legendgroup.
    Clicking the legend entry toggles all markers of that type.

    Markers are placed at z=zmax (top of part) except face-milling bottom
    candidates which go at z=zmin.

    Args:
        candidates  : list of candidate dicts from step_candidates session key
        zmax        : top Z coordinate of the mesh (from mesh vertex extents)
        zmin        : bottom Z coordinate of the mesh
        show_labels : if True, add a Scatter3d text annotation above each marker
        xmin, xmax  : mesh X extents — used by _infer_half_xy for Section C orientation
        ymin, ymax  : mesh Y extents — used by _infer_half_xy for Section C orientation

    Returns:
        list of plotly.graph_objects.Scatter3d traces
    """
    traces = []
    legend_shown = set()

    # Text labels float a small distance above the part top surface.
    z_text = zmax + max((zmax - zmin) * 0.08, 3.0)

    for cand in candidates:
        ftype  = cand.get("feature_type", "Unknown")
        ft_low = ftype.lower()
        color  = _feature_color(ftype)

        x        = float(cand.get("x_pos")    or 0)
        y        = float(cand.get("y_pos")    or 0)
        label    = cand.get("feature_name",   ftype)
        length   = float(cand.get("length")   or 0)
        width    = float(cand.get("width")    or 0)
        depth    = float(cand.get("depth")    or 0)
        diameter = float(cand.get("diameter") or 0)

        first_of_type = ftype not in legend_shown
        if first_of_type:
            legend_shown.add(ftype)

        hover = _make_hover_text(ft_low, label, diameter, length, width, depth)

        # ── Hole / Large Hole: circle at zmax ──────────────────────────────
        if "hole" in ft_low or "boring" in ft_low:
            r = (diameter / 2) if diameter > 0 else 5.0
            theta = [math.radians(a) for a in range(0, 370, 10)]
            traces.append(go.Scatter3d(
                x=[x + r * math.cos(t) for t in theta],
                y=[y + r * math.sin(t) for t in theta],
                z=[zmax] * len(theta),
                mode="lines",
                line=dict(color=color, width=3),
                name=ftype,
                legendgroup=ftype,
                showlegend=first_of_type,
                hovertext=hover,
                hoverinfo="text",
            ))

        # ── Face Milling: dashed rectangle at zmax or zmin ─────────────────
        elif "face mill" in ft_low:
            z_face = zmin if "bottom" in label.lower() else zmax
            half_l = (length / 2) if length > 0 else 30.0
            half_w = (width  / 2) if width  > 0 else 30.0
            rx = [x - half_l, x + half_l, x + half_l, x - half_l, x - half_l]
            ry = [y - half_w, y - half_w, y + half_w, y + half_w, y - half_w]
            traces.append(go.Scatter3d(
                x=rx, y=ry, z=[z_face] * 5,
                mode="lines",
                line=dict(color=color, width=2, dash="dash"),
                name=ftype,
                legendgroup=ftype,
                showlegend=first_of_type,
                hovertext=hover,
                hoverinfo="text",
            ))

        # ── Slot: solid rectangle outline at zmax ──────────────────────────
        elif "slot" in ft_low:
            half_x, half_y = _infer_half_xy(cand, xmin, xmax, ymin, ymax)
            rx = [x - half_x, x + half_x, x + half_x, x - half_x, x - half_x]
            ry = [y - half_y, y - half_y, y + half_y, y + half_y, y - half_y]
            traces.append(go.Scatter3d(
                x=rx, y=ry, z=[zmax] * 5,
                mode="lines",
                line=dict(color=color, width=3),
                name=ftype,
                legendgroup=ftype,
                showlegend=first_of_type,
                hovertext=hover,
                hoverinfo="text",
            ))

        # ── Pocket: solid rectangle outline at zmax ─────────────────────────
        elif "pocket" in ft_low:
            half_x, half_y = _infer_half_xy(cand, xmin, xmax, ymin, ymax)
            rx = [x - half_x, x + half_x, x + half_x, x - half_x, x - half_x]
            ry = [y - half_y, y - half_y, y + half_y, y + half_y, y - half_y]
            traces.append(go.Scatter3d(
                x=rx, y=ry, z=[zmax] * 5,
                mode="lines",
                line=dict(color=color, width=3),
                name=ftype,
                legendgroup=ftype,
                showlegend=first_of_type,
                hovertext=hover,
                hoverinfo="text",
            ))

        # ── Step / Shoulder: cross marker at (x, y, zmax) ──────────────────
        elif "step" in ft_low or "shoulder" in ft_low:
            arm = 8.0
            traces.append(go.Scatter3d(
                x=[x - arm, x + arm, None, x,       x      ],
                y=[y,       y,       None, y - arm, y + arm],
                z=[zmax] * 5,
                mode="lines",
                line=dict(color=color, width=3),
                name=ftype,
                legendgroup=ftype,
                showlegend=first_of_type,
                hovertext=hover,
                hoverinfo="text",
            ))

        # ── Chamfer: diamond marker at (x, y, zmax) ────────────────────────
        elif "chamfer" in ft_low:
            traces.append(go.Scatter3d(
                x=[x], y=[y], z=[zmax],
                mode="markers",
                marker=dict(size=10, color=color, symbol="diamond"),
                name=ftype,
                legendgroup=ftype,
                showlegend=first_of_type,
                hovertext=hover,
                hoverinfo="text",
            ))

        # ── Optional text label floating above the marker ──────────────────
        if show_labels:
            short = _make_short_label(ft_low, diameter, length, width, depth)
            if short:
                # Face-milling bottom label at z_text below the part (zmin offset)
                z_lbl = (zmin - max((zmax - zmin) * 0.08, 3.0)
                         if "face mill" in ft_low and "bottom" in label.lower()
                         else z_text)
                traces.append(go.Scatter3d(
                    x=[x], y=[y], z=[z_lbl],
                    mode="text",
                    text=[short],
                    textfont=dict(size=11, color=color, family="monospace"),
                    textposition="middle center",
                    name="",
                    legendgroup=ftype,
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
        opacity=0.05, color="steelblue",
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
# Mesh3d solid viewer — CadQuery tessellation data
# ---------------------------------------------------------------------------

def build_step_mesh3d(mesh_data, stock, candidates=None, show_labels=False):
    """
    Build a rotatable Plotly Mesh3d figure from pre-computed tessellation data.

    The bounding box overlay is derived from the actual vertex extents of the
    tessellated mesh so it always encloses the part regardless of the OCC
    coordinate origin.

    Args:
        mesh_data   : dict with keys x/y/z (vertex coord lists) and i/j/k (triangle index lists)
        stock       : dict with length/width/height keys (mm) — retained for signature compatibility
        candidates  : list of candidate dicts from step_candidates session key, or None/[]
                      to suppress markers
        show_labels : if True, add Scatter3d text annotations above each candidate marker

    Returns:
        plotly.graph_objects.Figure
    """
    xs, ys, zs = mesh_data["x"], mesh_data["y"], mesh_data["z"]

    # Derive bounding box from actual mesh vertex coordinates (OCC coordinate system).
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    zmin, zmax = min(zs), max(zs)

    fig = go.Figure()

    fig.add_trace(go.Mesh3d(
        x=xs,
        y=ys,
        z=zs,
        i=mesh_data["i"],
        j=mesh_data["j"],
        k=mesh_data["k"],
        color="lightsteelblue",
        opacity=0.88,
        flatshading=False,
        lighting=dict(
            ambient=0.5, diffuse=0.8, specular=0.2,
            roughness=0.5, fresnel=0.2,
        ),
        lightposition=dict(x=1, y=1, z=2),
        name="Part (solid body)",
        showlegend=True,
    ))

    for tr in _stock_box_coords_traces(xmin, xmax, ymin, ymax, zmin, zmax):
        fig.add_trace(tr)

    if candidates:
        for tr in _candidate_marker_traces(
            candidates, zmax, zmin,
            show_labels=show_labels,
            xmin=xmin, xmax=xmax, ymin=ymin, ymax=ymax,
        ):
            fig.add_trace(tr)

    fig.update_layout(
        title="3D Preview — Part Shape (planning reference only)",
        scene=dict(
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Z (mm)",
            aspectmode="data",
            xaxis=dict(backgroundcolor="rgba(240,248,255,0.5)"),
            yaxis=dict(backgroundcolor="rgba(240,248,255,0.5)"),
            zaxis=dict(backgroundcolor="rgba(220,230,240,0.5)"),
        ),
        height=480,
        margin=dict(l=0, r=0, t=50, b=0),
        legend=dict(orientation="h", yanchor="bottom", y=0),
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
