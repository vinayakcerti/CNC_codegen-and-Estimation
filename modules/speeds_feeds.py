"""
Speeds & Feeds reference data and calculation helpers.
Tuned for Indian SME workshops — includes IS/EN grade steels, cast irons,
common non-ferrous alloys, and Indian market tool coatings.
All cutting speeds in m/min, chip loads in mm/tooth.
"""
import math


# Recommended cutting speeds Vc (m/min) by material and tool coating
# Format: { material: { coating: (vc_min, vc_max) } }
CUTTING_SPEEDS = {
    # ── Aluminium ─────────────────────────────────────────────────────
    "Aluminium (Al 6061 / IS 65032)": {
        "Carbide uncoated (K10/K20)":      (200, 400),
        "Carbide AlTiN coated":            (300, 600),
        "Carbide TiN coated":              (250, 450),
        "Carbide ZrN / DLC (Al-specific)": (400, 800),
        "HSS-Co (M35/M42)":                (60,  120),
        "HSS (M2)":                        (40,  80),
    },
    "Aluminium (Al 7075 / IS 74530)": {
        "Carbide uncoated (K10/K20)":      (180, 350),
        "Carbide AlTiN coated":            (250, 500),
        "Carbide ZrN / DLC (Al-specific)": (350, 700),
        "HSS-Co (M35/M42)":                (50,  100),
        "HSS (M2)":                        (30,  70),
    },
    # ── Mild / Carbon Steel ───────────────────────────────────────────
    "Mild Steel IS 2062 E250": {
        "Carbide uncoated (P10/P20)":      (100, 180),
        "Carbide TiN coated":              (120, 200),
        "Carbide TiAlN / AlTiN":           (150, 250),
        "Carbide TiCN coated":             (130, 220),
        "HSS-Co (M35/M42)":                (25,  50),
        "HSS (M2)":                        (18,  35),
    },
    "EN8 / IS 40C8 (Med. Carbon Steel)": {
        "Carbide uncoated (P10/P20)":      (80,  150),
        "Carbide TiN coated":              (100, 180),
        "Carbide TiAlN / AlTiN":           (120, 200),
        "Carbide TiCN coated":             (110, 190),
        "HSS-Co (M35/M42)":                (20,  40),
        "HSS (M2)":                        (15,  28),
    },
    "EN19 / IS 40Cr4Mo2 (Cr-Mo Steel)": {
        "Carbide uncoated (P10/P20)":      (60,  120),
        "Carbide TiAlN / AlTiN":           (90,  160),
        "Carbide TiCN coated":             (80,  150),
        "HSS-Co (M35/M42)":                (12,  25),
        "HSS (M2)":                        (8,   18),
    },
    "EN24 / IS 40Ni2Cr1Mo28 (Alloy Steel)": {
        "Carbide uncoated (P10/P20)":      (50,  100),
        "Carbide TiAlN / AlTiN":           (80,  140),
        "Carbide TiCN coated":             (70,  130),
        "Carbide AlCrN coated":            (90,  160),
        "HSS-Co (M35/M42)":                (10,  20),
        "HSS (M2)":                        (6,   14),
    },
    "EN31 / IS 103Cr1 (Bearing Steel)": {
        "Carbide uncoated (P10/P20)":      (40,  90),
        "Carbide TiAlN / AlTiN":           (60,  120),
        "Carbide AlCrN coated":            (70,  130),
        "HSS-Co (M35/M42)":                (8,   16),
        "HSS (M2)":                        (5,   10),
    },
    # ── Stainless Steels ──────────────────────────────────────────────
    "Stainless Steel 304 / IS 04Cr18Ni10": {
        "Carbide uncoated (M10/M20)":      (40,  80),
        "Carbide TiAlN / AlTiN":           (60,  110),
        "Carbide AlCrN coated":            (70,  120),
        "HSS-Co (M35/M42)":                (10,  20),
        "HSS (M2)":                        (6,   12),
    },
    "Stainless Steel 316L": {
        "Carbide uncoated (M10/M20)":      (35,  70),
        "Carbide TiAlN / AlTiN":           (55,  100),
        "Carbide AlCrN coated":            (65,  110),
        "HSS-Co (M35/M42)":                (8,   16),
        "HSS (M2)":                        (5,   10),
    },
    "Stainless Steel 410 / 17-4PH": {
        "Carbide uncoated (M10/M20)":      (40,  80),
        "Carbide TiAlN / AlTiN":           (60,  110),
        "Carbide AlCrN coated":            (65,  115),
        "HSS-Co (M35/M42)":                (10,  18),
        "HSS (M2)":                        (6,   12),
    },
    # ── Cast Irons ────────────────────────────────────────────────────
    "Cast Iron Grey IS 210 FG200": {
        "Carbide uncoated (K10/K20)":      (100, 200),
        "Carbide TiN coated":              (120, 220),
        "Carbide TiAlN / AlTiN":           (140, 260),
        "CBN (for finish)":                (300, 700),
        "HSS-Co (M35/M42)":                (20,  40),
        "HSS (M2)":                        (14,  28),
    },
    "Cast Iron Grey IS 210 FG260": {
        "Carbide uncoated (K10/K20)":      (80,  160),
        "Carbide TiAlN / AlTiN":           (110, 200),
        "CBN (for finish)":                (250, 600),
        "HSS-Co (M35/M42)":                (16,  32),
        "HSS (M2)":                        (10,  22),
    },
    "Cast Iron Ductile / SG IS 1865 SG400": {
        "Carbide uncoated (K10/K20)":      (90,  170),
        "Carbide TiAlN / AlTiN":           (120, 220),
        "CBN (for finish)":                (200, 500),
        "HSS-Co (M35/M42)":                (18,  35),
        "HSS (M2)":                        (12,  24),
    },
    # ── Tool Steel / Hardened ─────────────────────────────────────────
    "Tool Steel / Die Steel (H13, D2)": {
        "Carbide uncoated (P10)":          (30,  70),
        "Carbide TiAlN / AlTiN":           (50,  100),
        "Carbide AlCrN coated":            (60,  110),
        "HSS-Co (M35/M42)":                (5,   12),
    },
    "Hardened Steel (HRC 45–55)": {
        "Carbide TiAlN / AlTiN (fine)":    (30,  60),
        "Carbide AlCrN coated (fine)":     (35,  70),
        "CBN insert":                      (100, 250),
    },
    # ── Non-ferrous ───────────────────────────────────────────────────
    "Brass IS 319 / CZ121": {
        "Carbide uncoated (K10/K20)":      (100, 250),
        "Carbide TiN coated":              (130, 280),
        "HSS-Co (M35/M42)":                (30,  70),
        "HSS (M2)":                        (20,  50),
    },
    "Phosphor Bronze IS 7814": {
        "Carbide uncoated (K10/K20)":      (80,  180),
        "Carbide TiN coated":              (100, 200),
        "HSS-Co (M35/M42)":                (20,  50),
        "HSS (M2)":                        (15,  35),
    },
    "Gun Metal (LG2 Bronze)": {
        "Carbide uncoated (K10/K20)":      (80,  160),
        "Carbide TiN coated":              (100, 190),
        "HSS-Co (M35/M42)":                (20,  45),
        "HSS (M2)":                        (14,  30),
    },
    "Copper / ETP Copper": {
        "Carbide uncoated (K10/K20)":      (80,  180),
        "Carbide TiN coated":              (100, 200),
        "HSS-Co (M35/M42)":                (25,  55),
        "HSS (M2)":                        (18,  40),
    },
    "Zinc / Zamak Die Cast": {
        "Carbide uncoated (K10/K20)":      (150, 400),
        "Carbide TiN coated":              (200, 500),
        "HSS (M2)":                        (50,  120),
    },
    # ── Titanium ──────────────────────────────────────────────────────
    "Titanium Grade 2 (Cp-Ti)": {
        "Carbide uncoated (fine grain)":   (25,  55),
        "Carbide TiAlN / AlTiN":           (35,  70),
        "HSS-Co (M35/M42)":                (5,   12),
    },
    "Titanium Grade 5 (Ti-6Al-4V)": {
        "Carbide uncoated (fine grain)":   (20,  50),
        "Carbide TiAlN / AlTiN":           (30,  60),
        "HSS-Co (M35/M42)":                (4,   10),
    },
    # ── Superalloys ───────────────────────────────────────────────────
    "Inconel 718 / Nickel Alloy": {
        "Carbide TiAlN / AlTiN":           (20,  50),
        "Carbide AlCrN coated":            (25,  55),
        "Ceramic insert (rough)":          (150, 350),
        "HSS-Co (M35/M42)":                (3,   8),
    },
    # ── Plastics / Non-metals ─────────────────────────────────────────
    "Nylon PA6 / PA66": {
        "Carbide uncoated (K10/K20)":      (80,  200),
        "Carbide TiN coated":              (100, 250),
        "HSS (M2)":                        (30,  80),
    },
    "HDPE / Acrylic (Plastic)": {
        "Carbide uncoated (K10/K20)":      (100, 300),
        "HSS (M2)":                        (40,  120),
    },
    "Wood / MDF / Plywood": {
        "Carbide uncoated (K10/K20)":      (200, 600),
        "HSS (M2)":                        (80,  200),
    },
}


# Recommended chip load fz (mm/tooth) by material and tool diameter
# Format: list of (dia_max_mm, fz_min, fz_max)
CHIP_LOADS = {
    "Aluminium (Al 6061 / IS 65032)":         [(4, 0.010, 0.020), (8, 0.020, 0.040), (12, 0.030, 0.060), (20, 0.040, 0.080), (999, 0.060, 0.150)],
    "Aluminium (Al 7075 / IS 74530)":         [(4, 0.008, 0.018), (8, 0.018, 0.035), (12, 0.025, 0.050), (20, 0.035, 0.070), (999, 0.055, 0.130)],
    "Mild Steel IS 2062 E250":                [(4, 0.005, 0.012), (8, 0.010, 0.020), (12, 0.015, 0.028), (20, 0.018, 0.035), (999, 0.025, 0.050)],
    "EN8 / IS 40C8 (Med. Carbon Steel)":      [(4, 0.004, 0.010), (8, 0.008, 0.018), (12, 0.012, 0.024), (20, 0.015, 0.030), (999, 0.020, 0.040)],
    "EN19 / IS 40Cr4Mo2 (Cr-Mo Steel)":       [(4, 0.003, 0.008), (8, 0.006, 0.014), (12, 0.009, 0.018), (20, 0.012, 0.025), (999, 0.016, 0.032)],
    "EN24 / IS 40Ni2Cr1Mo28 (Alloy Steel)":   [(4, 0.003, 0.007), (8, 0.005, 0.012), (12, 0.008, 0.016), (20, 0.010, 0.022), (999, 0.014, 0.028)],
    "EN31 / IS 103Cr1 (Bearing Steel)":       [(4, 0.002, 0.006), (8, 0.004, 0.010), (12, 0.006, 0.013), (20, 0.008, 0.018), (999, 0.012, 0.024)],
    "Stainless Steel 304 / IS 04Cr18Ni10":    [(4, 0.003, 0.008), (8, 0.006, 0.014), (12, 0.008, 0.018), (20, 0.010, 0.022), (999, 0.014, 0.030)],
    "Stainless Steel 316L":                   [(4, 0.003, 0.007), (8, 0.005, 0.013), (12, 0.007, 0.016), (20, 0.010, 0.020), (999, 0.013, 0.028)],
    "Stainless Steel 410 / 17-4PH":           [(4, 0.003, 0.008), (8, 0.006, 0.014), (12, 0.008, 0.018), (20, 0.010, 0.022), (999, 0.014, 0.030)],
    "Cast Iron Grey IS 210 FG200":            [(4, 0.005, 0.012), (8, 0.010, 0.020), (12, 0.014, 0.026), (20, 0.018, 0.034), (999, 0.024, 0.045)],
    "Cast Iron Grey IS 210 FG260":            [(4, 0.004, 0.010), (8, 0.008, 0.018), (12, 0.012, 0.022), (20, 0.016, 0.030), (999, 0.022, 0.040)],
    "Cast Iron Ductile / SG IS 1865 SG400":   [(4, 0.005, 0.012), (8, 0.010, 0.020), (12, 0.014, 0.026), (20, 0.018, 0.034), (999, 0.024, 0.045)],
    "Tool Steel / Die Steel (H13, D2)":       [(4, 0.002, 0.006), (8, 0.004, 0.010), (12, 0.006, 0.013), (20, 0.008, 0.016), (999, 0.010, 0.020)],
    "Hardened Steel (HRC 45–55)":             [(4, 0.001, 0.004), (8, 0.002, 0.006), (12, 0.003, 0.008), (20, 0.004, 0.010), (999, 0.006, 0.013)],
    "Brass IS 319 / CZ121":                   [(4, 0.010, 0.025), (8, 0.018, 0.040), (12, 0.025, 0.055), (20, 0.030, 0.070), (999, 0.045, 0.110)],
    "Phosphor Bronze IS 7814":                [(4, 0.008, 0.018), (8, 0.014, 0.030), (12, 0.020, 0.040), (20, 0.025, 0.055), (999, 0.035, 0.080)],
    "Gun Metal (LG2 Bronze)":                 [(4, 0.008, 0.018), (8, 0.014, 0.030), (12, 0.020, 0.040), (20, 0.025, 0.055), (999, 0.035, 0.080)],
    "Copper / ETP Copper":                    [(4, 0.008, 0.018), (8, 0.015, 0.030), (12, 0.020, 0.040), (20, 0.025, 0.050), (999, 0.035, 0.075)],
    "Zinc / Zamak Die Cast":                  [(4, 0.015, 0.035), (8, 0.025, 0.055), (12, 0.035, 0.075), (20, 0.050, 0.110), (999, 0.080, 0.180)],
    "Titanium Grade 2 (Cp-Ti)":              [(4, 0.002, 0.006), (8, 0.004, 0.010), (12, 0.006, 0.013), (20, 0.008, 0.016), (999, 0.010, 0.020)],
    "Titanium Grade 5 (Ti-6Al-4V)":          [(4, 0.002, 0.005), (8, 0.003, 0.008), (12, 0.005, 0.011), (20, 0.007, 0.014), (999, 0.009, 0.018)],
    "Inconel 718 / Nickel Alloy":            [(4, 0.001, 0.003), (8, 0.002, 0.006), (12, 0.003, 0.008), (20, 0.004, 0.010), (999, 0.006, 0.013)],
    "Nylon PA6 / PA66":                       [(4, 0.020, 0.050), (8, 0.040, 0.080), (12, 0.050, 0.110), (20, 0.070, 0.150), (999, 0.100, 0.250)],
    "HDPE / Acrylic (Plastic)":               [(4, 0.025, 0.060), (8, 0.050, 0.100), (12, 0.070, 0.140), (20, 0.090, 0.200), (999, 0.130, 0.300)],
    "Wood / MDF / Plywood":                   [(4, 0.040, 0.100), (8, 0.070, 0.160), (12, 0.100, 0.220), (20, 0.130, 0.300), (999, 0.180, 0.400)],
}

# Fallback material key — used when exact match not found
_FALLBACK = "Mild Steel IS 2062 E250"


def material_list():
    return list(CUTTING_SPEEDS.keys())


def coating_list(material):
    return list(CUTTING_SPEEDS.get(material, CUTTING_SPEEDS[_FALLBACK]).keys())


def get_vc_range(material, coating):
    return CUTTING_SPEEDS.get(material, CUTTING_SPEEDS[_FALLBACK]).get(coating, (80, 150))


def get_chip_load_range(material, diameter_mm):
    table = CHIP_LOADS.get(material, CHIP_LOADS[_FALLBACK])
    for dia_max, fz_min, fz_max in table:
        if diameter_mm <= dia_max:
            return fz_min, fz_max
    return table[-1][1], table[-1][2]


def calc_rpm(vc_m_min, diameter_mm):
    """RPM from cutting speed (m/min) and tool diameter (mm)."""
    if diameter_mm <= 0:
        return 0
    return (vc_m_min * 1000) / (math.pi * diameter_mm)


def calc_feed(rpm, fz_mm_tooth, num_flutes):
    """Feed rate (mm/min) from RPM, chip load per tooth, and flute count."""
    return rpm * fz_mm_tooth * num_flutes


def calc_vc_from_rpm(rpm, diameter_mm):
    """Back-calculate Vc (m/min) from RPM and diameter."""
    return (rpm * math.pi * diameter_mm) / 1000


def calc_mrr(feed_mm_min, axial_doc_mm, radial_doc_mm):
    """Material Removal Rate in cm³/min."""
    return (feed_mm_min * axial_doc_mm * radial_doc_mm) / 1000
