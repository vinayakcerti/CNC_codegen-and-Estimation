"""
Tolerance & Surface Finish reference data.
Based on ISO 286-1 (IT grades) and standard machining process capability.
Tuned for Indian SME workshops.
"""

# ── IT Tolerance tables (ISO 286-1) ─────────────────────────────────────────
# Fundamental tolerances in micrometres (µm) by IT grade and nominal diameter range.
# Columns: (range_label, d_min, d_max)
IT_DIAMETER_BANDS = [
    ("≤ 3 mm",       0,    3),
    ("3–6 mm",       3,    6),
    ("6–10 mm",      6,   10),
    ("10–18 mm",    10,   18),
    ("18–30 mm",    18,   30),
    ("30–50 mm",    30,   50),
    ("50–80 mm",    50,   80),
    ("80–120 mm",   80,  120),
    ("120–180 mm", 120,  180),
    ("180–250 mm", 180,  250),
    ("250–315 mm", 250,  315),
    ("315–400 mm", 315,  400),
    ("400–500 mm", 400,  500),
]

# IT_VALUES[grade] = [tolerance_µm for each band above]
IT_VALUES = {
    "IT5":  [4,   5,   6,   8,   9,  11,  13,  15,  18,  20,  23,  25,  27],
    "IT6":  [6,   8,   9,  11,  13,  16,  19,  22,  25,  29,  32,  36,  40],
    "IT7":  [10,  12,  15,  18,  21,  25,  30,  35,  40,  46,  52,  57,  63],
    "IT8":  [14,  18,  22,  27,  33,  39,  46,  54,  63,  72,  81,  89,  97],
    "IT9":  [25,  30,  36,  43,  52,  62,  74,  87, 100, 115, 130, 140, 155],
    "IT10": [40,  48,  58,  70,  84, 100, 120, 140, 160, 185, 210, 230, 250],
    "IT11": [60,  75,  90, 110, 130, 160, 190, 220, 250, 290, 320, 360, 400],
    "IT12": [100, 120, 150, 180, 210, 250, 300, 350, 400, 460, 520, 570, 630],
    "IT13": [140, 180, 220, 270, 330, 390, 460, 540, 630, 720, 810, 890, 970],
}

IT_GRADE_LIST = list(IT_VALUES.keys())


def get_it_tolerance_um(grade: str, diameter_mm: float) -> int:
    """Return IT tolerance in µm for a given grade and nominal diameter."""
    values = IT_VALUES.get(grade, IT_VALUES["IT7"])
    for idx, (_, d_min, d_max) in enumerate(IT_DIAMETER_BANDS):
        if d_min < diameter_mm <= d_max or (d_min == 0 and diameter_mm <= d_max):
            return values[idx]
    return values[-1]


# ── Process capability: which operations achieve which IT grades ──────────────
# Format: { feature_type: [ { "operation", "it_grades", "ra_range_um", "notes" } ] }
PROCESS_CAPABILITY = {
    "Hole": [
        {
            "operation": "Drilling only",
            "it_grades": ["IT11", "IT12", "IT13"],
            "ra_range_um": (3.2, 12.5),
            "notes": "Drill as-is. Suitable for clearance holes and non-precision through holes.",
            "typical_fit": "Free fit (H12/h12)",
        },
        {
            "operation": "Drilling + Reaming",
            "it_grades": ["IT8", "IT9", "IT10"],
            "ra_range_um": (0.8, 3.2),
            "notes": "Drill undersized, ream to final diameter. Common for H8/H9 location fits in Indian workshops.",
            "typical_fit": "Sliding fit (H8/f8) or Locational clearance (H9/d9)",
        },
        {
            "operation": "Drilling + Fine Boring",
            "it_grades": ["IT6", "IT7"],
            "ra_range_um": (0.4, 1.6),
            "notes": "Bore on CNC with tight runout. Achievable on VMCs with quality boring bars.",
            "typical_fit": "Running fit (H7/f7) or Push fit (H7/p6) — most common precision fit in Indian industry",
        },
        {
            "operation": "Drilling + Boring + Honing",
            "it_grades": ["IT5", "IT6"],
            "ra_range_um": (0.1, 0.4),
            "notes": "Requires dedicated honing machine. Used for engine cylinders, hydraulic bores.",
            "typical_fit": "Precision clearance (H6/g5) or Tight running (H6/f6)",
        },
    ],
    "Large Hole / Boring": [
        {
            "operation": "Rough Boring",
            "it_grades": ["IT10", "IT11", "IT12"],
            "ra_range_um": (3.2, 12.5),
            "notes": "Multi-pass rough boring. First cut after pilot drilling.",
            "typical_fit": "Clearance / housing bores",
        },
        {
            "operation": "Semi-Finish Boring",
            "it_grades": ["IT8", "IT9"],
            "ra_range_um": (1.6, 6.3),
            "notes": "Leave 0.1–0.3 mm for finish pass.",
            "typical_fit": "H9/d9 clearance fits",
        },
        {
            "operation": "Fine Boring (G76 cycle)",
            "it_grades": ["IT6", "IT7"],
            "ra_range_um": (0.4, 1.6),
            "notes": "Single-point boring bar. Control feed and runout. Very achievable on BFW/Ace VMCs.",
            "typical_fit": "H7/f7 or H7/k6 transition fits — standard bearing housings",
        },
    ],
    "Pocket": [
        {
            "operation": "Rough End Milling",
            "it_grades": ["IT11", "IT12"],
            "ra_range_um": (6.3, 25.0),
            "notes": "Leave 0.3–0.5 mm stock all around for finish pass.",
            "typical_fit": "N/A (form features)",
        },
        {
            "operation": "Finish End Milling",
            "it_grades": ["IT8", "IT9", "IT10"],
            "ra_range_um": (1.6, 6.3),
            "notes": "Light cuts at high RPM. Use sharp 2/3-flute cutter for aluminium; 4-flute for steel.",
            "typical_fit": "Pocket depth ±0.05–0.1 mm typical",
        },
        {
            "operation": "Finish End Milling (HSM)",
            "it_grades": ["IT6", "IT7"],
            "ra_range_um": (0.4, 1.6),
            "notes": "High-speed milling with small step-down. Requires rigid spindle, quality carbide.",
            "typical_fit": "Mould/die cavities, precision jig pockets",
        },
    ],
    "Slot": [
        {
            "operation": "Slotting — Rough",
            "it_grades": ["IT10", "IT11", "IT12"],
            "ra_range_um": (3.2, 12.5),
            "notes": "Full-width slot cut. Width tolerance depends on tool diameter accuracy.",
            "typical_fit": "Keyway slots (JS9), woodruff key seats",
        },
        {
            "operation": "Slotting — Finish (side milling)",
            "it_grades": ["IT8", "IT9"],
            "ra_range_um": (1.6, 3.2),
            "notes": "Side milling passes on slot walls. Common for feather keyways to IS/DIN spec.",
            "typical_fit": "Key fits: N9/h9 or JS9/h9 (Indian standard keyways)",
        },
    ],
    "Face Milling": [
        {
            "operation": "Rough Face Milling",
            "it_grades": ["IT11", "IT12"],
            "ra_range_um": (6.3, 25.0),
            "notes": "Remove bulk stock. Use indexable face mill inserts.",
            "typical_fit": "Stock removal — not a fit surface",
        },
        {
            "operation": "Finish Face Milling (carbide inserts)",
            "it_grades": ["IT8", "IT9", "IT10"],
            "ra_range_um": (1.6, 3.2),
            "notes": "Sharp wiper inserts. Flatness ±0.02–0.05 mm achievable on rigid VMC.",
            "typical_fit": "Mating faces, gasket surfaces (Ra 1.6–3.2 typical spec)",
        },
        {
            "operation": "Fine Face Milling / Skimming",
            "it_grades": ["IT6", "IT7"],
            "ra_range_um": (0.4, 0.8),
            "notes": "Light finishing skim. Requires fresh wiper insert and stable fixturing.",
            "typical_fit": "Precision mating faces, hydraulic manifold faces",
        },
    ],
    "Outer Profile": [
        {
            "operation": "Rough Profile Milling",
            "it_grades": ["IT11", "IT12"],
            "ra_range_um": (6.3, 25.0),
            "notes": "Roughing passes. Leave 0.3–0.5 mm finish stock.",
            "typical_fit": "N/A",
        },
        {
            "operation": "Finish Profile Milling",
            "it_grades": ["IT8", "IT9", "IT10"],
            "ra_range_um": (1.6, 3.2),
            "notes": "Final profile pass. Dimensional accuracy depends on tool runout and thermal stability.",
            "typical_fit": "Profile tolerances ±0.05–0.1 mm",
        },
    ],
    "Chamfer": [
        {
            "operation": "Chamfer Milling",
            "it_grades": ["IT10", "IT11", "IT12"],
            "ra_range_um": (3.2, 6.3),
            "notes": "Chamfer angle ±1–2° typical. Use dedicated chamfer/deburring tool.",
            "typical_fit": "Deburring, assembly lead-in",
        },
    ],
}

# ── Surface finish guide ─────────────────────────────────────────────────────
# Ra in µm, also mapped to N-grade and Rz
SURFACE_FINISH_TABLE = [
    {"N_grade": "N12", "Ra_um": 50.0,  "Rz_um": 200,  "description": "Very rough",     "typical_process": "Sawing, rough casting"},
    {"N_grade": "N11", "Ra_um": 25.0,  "Rz_um": 100,  "description": "Rough",           "typical_process": "Rough turning, rough milling"},
    {"N_grade": "N10", "Ra_um": 12.5,  "Rz_um": 50,   "description": "Semi-rough",      "typical_process": "Drilling, rough boring"},
    {"N_grade": "N9",  "Ra_um": 6.3,   "Rz_um": 25,   "description": "Medium",          "typical_process": "Normal turning/milling, drilling"},
    {"N_grade": "N8",  "Ra_um": 3.2,   "Rz_um": 12.5, "description": "Semi-finish",     "typical_process": "Finish turning, semi-finish milling, reaming"},
    {"N_grade": "N7",  "Ra_um": 1.6,   "Rz_um": 6.3,  "description": "Finish",          "typical_process": "Fine turning, finish milling, reaming — most common spec in Indian drawings"},
    {"N_grade": "N6",  "Ra_um": 0.8,   "Rz_um": 3.2,  "description": "Fine",            "typical_process": "Fine boring, finish grinding, precision reaming"},
    {"N_grade": "N5",  "Ra_um": 0.4,   "Rz_um": 1.6,  "description": "Very fine",       "typical_process": "Cylindrical grinding, precision boring, hard turning"},
    {"N_grade": "N4",  "Ra_um": 0.2,   "Rz_um": 0.8,  "description": "Ultra-fine",      "typical_process": "Fine grinding, honing, superfinishing"},
    {"N_grade": "N3",  "Ra_um": 0.1,   "Rz_um": 0.4,  "description": "Mirror (near)",  "typical_process": "Honing, lapping, precision grinding"},
    {"N_grade": "N2",  "Ra_um": 0.05,  "Rz_um": 0.2,  "description": "Mirror",          "typical_process": "Lapping, superfinishing, polishing"},
]

# ── Common Indian engineering fits ───────────────────────────────────────────
COMMON_FITS = [
    {"fit": "H7/f7",  "type": "Clearance", "description": "Running/Sliding fit", "use_case": "Bearings, rotating shafts — most common in India"},
    {"fit": "H7/g6",  "type": "Clearance", "description": "Close running fit",   "use_case": "Precision spindles, sliding fits with minimal clearance"},
    {"fit": "H7/h6",  "type": "Clearance", "description": "Locating fit",        "use_case": "Location dowels, close assembly"},
    {"fit": "H7/k6",  "type": "Transition","description": "Push fit",            "use_case": "Gears, pulleys on shafts (removable)"},
    {"fit": "H7/p6",  "type": "Transition","description": "Drive fit",           "use_case": "Hubs, bushes (press or light shrink)"},
    {"fit": "H7/s6",  "type": "Interference","description": "Heavy press fit",   "use_case": "Permanent assemblies, coupling hubs"},
    {"fit": "H8/f8",  "type": "Clearance", "description": "Easy sliding fit",    "use_case": "Pistons, guide shafts, linkages"},
    {"fit": "H9/d9",  "type": "Clearance", "description": "Loose clearance",     "use_case": "Agricultural/general machinery, moderate precision"},
    {"fit": "H11/c11","type": "Clearance", "description": "Free fit",            "use_case": "Rough work, heavy flanges, large clearances"},
    {"fit": "JS9/h9", "type": "Clearance", "description": "Symmetric keyway",    "use_case": "Feather keys, IS 2048 woodruff keys"},
]


def get_process_for_feature(feature_type: str):
    return PROCESS_CAPABILITY.get(feature_type, PROCESS_CAPABILITY.get("Hole", []))


def get_it_band_label(diameter_mm: float) -> str:
    for label, d_min, d_max in IT_DIAMETER_BANDS:
        if d_min < diameter_mm <= d_max or (d_min == 0 and diameter_mm <= d_max):
            return label
    return IT_DIAMETER_BANDS[-1][0]
