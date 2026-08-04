"""Generate test fixtures for the drawing-extraction feature.

Produces (in test_samples/):
  - D01_plate_drawing.pdf       2-page dimensioned drawing of the known
                                02_plate part (100x60x30, 4x Ø10 through)
  - D01_plate_drawing.extract.json   ground-truth extraction (fixture mode)
  - D02_plate_drawing_mismatch.extract.json  deliberately mismatched
                                extraction (Ø12 holes, qty 6) to exercise the
                                comparison flow's mismatch path

Run:  conda run -n cnc-cadquery python experiments/make_test_drawing.py
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Circle, Rectangle

OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "test_samples")

L, W, H = 100.0, 60.0, 30.0
HOLE_D = 10.0
# Same 4-hole pattern as 02_plate_4_through_holes_d10.step (70 x 30 grid)
HOLES = [(-35.0, -15.0), (35.0, -15.0), (-35.0, 15.0), (35.0, 15.0)]


def dim_h(ax, x0, x1, y, text):
    ax.annotate("", xy=(x0, y), xytext=(x1, y), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text((x0 + x1) / 2, y + 1.5, text, ha="center", fontsize=8)


def dim_v(ax, x, y0, y1, text):
    ax.annotate("", xy=(x, y0), xytext=(x, y1), arrowprops=dict(arrowstyle="<->", lw=0.8))
    ax.text(x + 1.5, (y0 + y1) / 2, text, va="center", rotation=90, fontsize=8)


pdf_path = os.path.abspath(os.path.join(OUT_DIR, "D01_plate_drawing.pdf"))
with PdfPages(pdf_path) as pdf:
    # ---- Page 1: top view with dimensions ----
    fig, ax = plt.subplots(figsize=(11.7, 8.3))  # A4 landscape
    ax.set_aspect("equal")
    ax.add_patch(Rectangle((-L / 2, -W / 2), L, W, fill=False, lw=1.4))
    for (hx, hy) in HOLES:
        ax.add_patch(Circle((hx, hy), HOLE_D / 2, fill=False, lw=1.0))
        ax.plot([hx - 7, hx + 7], [hy, hy], lw=0.4, color="k")
        ax.plot([hx, hx], [hy - 7, hy + 7], lw=0.4, color="k")
    ax.annotate("4 x Ø10.0 THRU", xy=(HOLES[1][0] + 3.5, HOLES[1][1] + 3.5),
                xytext=(62, 32), fontsize=9,
                arrowprops=dict(arrowstyle="->", lw=0.8))
    dim_h(ax, -L / 2, L / 2, -W / 2 - 10, "100.0")
    dim_v(ax, -L / 2 - 10, -W / 2, W / 2, "60.0")
    dim_h(ax, HOLES[0][0], HOLES[1][0], W / 2 + 8, "70.0")
    dim_v(ax, L / 2 + 8, HOLES[0][1], HOLES[2][1], "30.0")
    ax.text(-L / 2, -W / 2 - 20, "MATERIAL: AL 6061   |   QTY: 1   |   ALL DIMS MM   |   TOL: ISO 2768-mK",
            fontsize=9)
    ax.text(-L / 2, W / 2 + 16, "DWG NO: D01-PLATE   REV A   —   TOP VIEW   (THICKNESS 30.0)",
            fontsize=10, fontweight="bold")
    ax.set_xlim(-75, 85)
    ax.set_ylim(-55, 55)
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)

    # ---- Page 2: front view + notes ----
    fig, ax = plt.subplots(figsize=(11.7, 8.3))
    ax.set_aspect("equal")
    ax.add_patch(Rectangle((-L / 2, -H / 2), L, H, fill=False, lw=1.4))
    for (hx, _hy) in HOLES[:2]:
        ax.plot([hx - HOLE_D / 2, hx - HOLE_D / 2], [-H / 2, H / 2], lw=0.7, ls="--", color="k")
        ax.plot([hx + HOLE_D / 2, hx + HOLE_D / 2], [-H / 2, H / 2], lw=0.7, ls="--", color="k")
    dim_v(ax, L / 2 + 8, -H / 2, H / 2, "30.0")
    ax.text(-L / 2, -H / 2 - 14, "NOTES: 1. BREAK ALL SHARP EDGES 0.5 MAX   2. SURFACE FINISH Ra 3.2",
            fontsize=9)
    ax.text(-L / 2, H / 2 + 10, "DWG NO: D01-PLATE   REV A   —   FRONT VIEW", fontsize=10, fontweight="bold")
    ax.set_xlim(-75, 85)
    ax.set_ylim(-45, 40)
    ax.axis("off")
    pdf.savefig(fig)
    plt.close(fig)

print("wrote", pdf_path)

# ---- Ground truth extraction (what a perfect vision model would return) ----
truth = {
    "part": {
        "name": "PLATE", "material": "AL 6061",
        "envelope_mm": {"length": 100.0, "width": 60.0, "height": 30.0},
        "quantity": 1, "drawing_number": "D01-PLATE", "revision": "A",
    },
    "features": [
        {
            "kind": "hole", "diameter_mm": 10.0, "depth_mm": None, "count": 4,
            "thread_spec": None,
            "positions_mm": [[-35.0, -15.0], [35.0, -15.0], [-35.0, 15.0], [35.0, 15.0]],
            "tolerance_note": None, "source_page": 1, "confidence": "high",
        },
    ],
    "general": {
        "tolerance_standard": "ISO 2768-mK",
        "surface_finish": "Ra 3.2",
        "notes": ["BREAK ALL SHARP EDGES 0.5 MAX"],
    },
    "pages": [
        {"page": 1, "type": "drawing_view", "summary": "Top view with envelope and hole pattern dims"},
        {"page": 2, "type": "drawing_view", "summary": "Front view, thickness, general notes"},
    ],
    "overall_confidence": "high",
    "caveats": [],
}
p1 = os.path.abspath(os.path.join(OUT_DIR, "D01_plate_drawing.extract.json"))
json.dump(truth, open(p1, "w", encoding="utf-8"), indent=1)
print("wrote", p1)

# ---- Deliberate mismatch fixture: Ø12 x 6 holes, thicker plate ----
mismatch = json.loads(json.dumps(truth))
mismatch["part"]["envelope_mm"]["height"] = 35.0
mismatch["features"][0].update({
    "diameter_mm": 12.0, "count": 6,
    "positions_mm": [[-35.0, -15.0], [0.0, -15.0], [35.0, -15.0],
                      [-35.0, 15.0], [0.0, 15.0], [35.0, 15.0]],
})
mismatch["caveats"] = ["fixture: deliberately mismatched against 02_plate STEP"]
p2 = os.path.abspath(os.path.join(OUT_DIR, "D02_plate_drawing_mismatch.extract.json"))
json.dump(mismatch, open(p2, "w", encoding="utf-8"), indent=1)
print("wrote", p2)
