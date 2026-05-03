import plotly.graph_objects as go
import math


def build_top_view(stock, features):
    fig = go.Figure()

    sx = stock.get("length", 100)
    sy = stock.get("width", 100)

    fig.add_shape(
        type="rect",
        x0=0, y0=0, x1=sx, y1=sy,
        line=dict(color="steelblue", width=2),
        fillcolor="rgba(135,206,250,0.15)",
    )

    for feat in features:
        ftype = feat.get("feature_type", "")
        x = feat.get("x_pos", sx / 2) or sx / 2
        y = feat.get("y_pos", sy / 2) or sy / 2
        qty = feat.get("quantity", 1) or 1
        dia = feat.get("diameter", 10) or 10
        length = feat.get("length", 20) or 20
        width = feat.get("width", 20) or 20

        if ftype in ("Hole", "Large Hole / Boring"):
            for i in range(qty):
                xi = x + i * (dia + 5)
                theta = [math.radians(a) for a in range(0, 361, 10)]
                cx = [xi + (dia / 2) * math.cos(t) for t in theta]
                cy = [y + (dia / 2) * math.sin(t) for t in theta]
                fig.add_trace(go.Scatter(
                    x=cx, y=cy, mode="lines",
                    line=dict(color="red", width=1.5),
                    name=f"{feat['feature_name']} ({i+1})",
                    showlegend=(i == 0),
                ))
                fig.add_trace(go.Scatter(
                    x=[xi], y=[y], mode="markers",
                    marker=dict(color="red", size=4),
                    showlegend=False,
                ))

        elif ftype == "Pocket":
            fig.add_shape(
                type="rect",
                x0=x, y0=y, x1=x + length, y1=y + width,
                line=dict(color="orange", width=2),
                fillcolor="rgba(255,165,0,0.25)",
            )
            fig.add_trace(go.Scatter(
                x=[x + length / 2], y=[y + width / 2],
                mode="text",
                text=[feat["feature_name"]],
                textfont=dict(size=9, color="darkorange"),
                showlegend=False,
            ))

        elif ftype == "Slot":
            fig.add_shape(
                type="rect",
                x0=x, y0=y - width / 2,
                x1=x + length, y1=y + width / 2,
                line=dict(color="purple", width=2),
                fillcolor="rgba(128,0,128,0.2)",
            )

        elif ftype == "Face Milling":
            fig.add_shape(
                type="rect",
                x0=0, y0=0, x1=sx, y1=sy,
                line=dict(color="green", width=1, dash="dash"),
                fillcolor="rgba(0,128,0,0.08)",
            )

        elif ftype == "Outer Profile":
            fig.add_shape(
                type="rect",
                x0=x, y0=y, x1=x + length, y1=y + width,
                line=dict(color="navy", width=2, dash="dot"),
                fillcolor="rgba(0,0,128,0.05)",
            )

        elif ftype == "Chamfer":
            cx_pts = [x, x + dia, x + dia / 2, x]
            cy_pts = [y, y, y + dia, y]
            fig.add_trace(go.Scatter(
                x=cx_pts, y=cy_pts, mode="lines",
                line=dict(color="brown", width=1.5),
                name=feat["feature_name"],
            ))

    fig.update_layout(
        title="Top View — Approximate Feature Layout",
        xaxis_title="X (mm)",
        yaxis_title="Y (mm)",
        xaxis=dict(scaleanchor="y", scaleratio=1, range=[-10, sx + 20]),
        yaxis=dict(range=[-10, sy + 20]),
        height=500,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        margin=dict(l=40, r=40, t=60, b=40),
    )
    return fig


def build_3d_view(stock, features):
    fig = go.Figure()

    sx = stock.get("length", 100)
    sy = stock.get("width", 100)
    sz = stock.get("height", 50)

    vertices_x = [0, sx, sx, 0, 0, sx, sx, 0]
    vertices_y = [0, 0, sy, sy, 0, 0, sy, sy]
    vertices_z = [0, 0, 0, 0, sz, sz, sz, sz]
    i_idx = [0, 0, 0, 4, 4, 4, 0, 1, 2, 3]
    j_idx = [1, 2, 4, 5, 6, 7, 4, 5, 6, 7]
    k_idx = [2, 3, 5, 6, 7, 3, 1, 2, 5, 6]

    fig.add_trace(go.Mesh3d(
        x=vertices_x, y=vertices_y, z=vertices_z,
        i=i_idx, j=j_idx, k=k_idx,
        opacity=0.15,
        color="steelblue",
        name="Stock",
    ))

    for feat in features:
        ftype = feat.get("feature_type", "")
        x = feat.get("x_pos", sx / 2) or sx / 2
        y = feat.get("y_pos", sy / 2) or sy / 2
        depth = feat.get("depth", 10) or 10
        dia = feat.get("diameter", 10) or 10
        qty = feat.get("quantity", 1) or 1
        length = feat.get("length", 20) or 20
        width = feat.get("width", 20) or 20

        if ftype in ("Hole", "Large Hole / Boring"):
            for i in range(qty):
                xi = x + i * (dia + 5)
                theta = [math.radians(a) for a in range(0, 361, 20)]
                cx = [xi + (dia / 2) * math.cos(t) for t in theta]
                cy = [y + (dia / 2) * math.sin(t) for t in theta]
                cz_top = [sz] * len(theta)
                cz_bot = [sz - depth] * len(theta)
                fig.add_trace(go.Scatter3d(
                    x=cx, y=cy, z=cz_top,
                    mode="lines",
                    line=dict(color="red", width=3),
                    name=feat["feature_name"] if i == 0 else "",
                    showlegend=(i == 0),
                ))
                fig.add_trace(go.Scatter3d(
                    x=cx, y=cy, z=cz_bot,
                    mode="lines",
                    line=dict(color="darkred", width=1),
                    showlegend=False,
                ))
                for t_i in range(0, len(theta), 4):
                    fig.add_trace(go.Scatter3d(
                        x=[cx[t_i], cx[t_i]], y=[cy[t_i], cy[t_i]], z=[sz, sz - depth],
                        mode="lines",
                        line=dict(color="red", width=1),
                        showlegend=False,
                    ))

        elif ftype == "Pocket":
            xs = [x, x + length, x + length, x, x]
            ys = [y, y, y + width, y + width, y]
            zs_top = [sz] * 5
            zs_bot = [sz - depth] * 5
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=zs_top,
                mode="lines",
                line=dict(color="orange", width=3),
                name=feat["feature_name"],
            ))
            fig.add_trace(go.Scatter3d(
                x=xs, y=ys, z=zs_bot,
                mode="lines",
                line=dict(color="darkorange", width=2),
                showlegend=False,
            ))

        elif ftype == "Face Milling":
            fig.add_trace(go.Scatter3d(
                x=[0, sx, sx, 0, 0],
                y=[0, 0, sy, sy, 0],
                z=[sz, sz, sz, sz, sz],
                mode="lines",
                line=dict(color="green", width=3, dash="dash"),
                name="Face Mill Area",
            ))

    fig.update_layout(
        title="3D View — Approximate Feature Preview",
        scene=dict(
            xaxis_title="X (mm)",
            yaxis_title="Y (mm)",
            zaxis_title="Z (mm)",
            aspectmode="data",
        ),
        height=550,
        margin=dict(l=0, r=0, t=60, b=0),
    )
    return fig
