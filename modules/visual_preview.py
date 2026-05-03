import plotly.graph_objects as go
import math


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _stock_box_traces(sx, sy, sz):
    """Return Mesh3d + wireframe Scatter3d traces for the stock bounding box."""
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
    # wireframe edges of the box
    edges = [
        [0,1,None,1,2,None,2,3,None,3,0,None],   # bottom
        [4,5,None,5,6,None,6,7,None,7,4,None],   # top
        [0,4,None,1,5,None,2,6,None,3,7,None],   # verticals
    ]
    ex, ey, ez = [], [], []
    idx = [(0,1),(1,2),(2,3),(3,0),(4,5),(5,6),(6,7),(7,4),(0,4),(1,5),(2,6),(3,7)]
    for a,b in idx:
        ex += [vx[a],vx[b],None]; ey += [vy[a],vy[b],None]; ez += [vz[a],vz[b],None]
    wire = go.Scatter3d(
        x=ex, y=ey, z=ez, mode="lines",
        line=dict(color="steelblue", width=1),
        name="Stock outline", showlegend=False,
    )
    return [mesh, wire]


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
        title = "Top View — Actual STEP Geometry (XY projection)"

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
        title = "Top View — Feature Layout (no STEP file loaded)"

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

        title = "3D View — Actual STEP Geometry"

    else:
        # ── Fallback: bounding box + features ────────────────────────────
        for tr in _stock_box_traces(sx, sy, sz):
            fig.add_trace(tr)
        _add_feature_traces_3d(fig, features, sz)
        title = "3D View — Feature Preview (no STEP file loaded)"

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
