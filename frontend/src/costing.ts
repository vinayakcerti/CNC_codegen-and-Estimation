// Rate-card costing engine (ARD R2 + R3) — pure client-side.
//
// Two costing models exist side by side:
//   "time"     — the original hours × ₹/hr model (DEFAULT, untouched)
//   "ratecard" — milling priced ₹/cm² of machined surface + holes priced from
//                the hole cost library keyed (Ø, tolerance, thickness)
//
// Profiles are per machine, seeded from a default rate card, stored in
// localStorage v1 (server sync = production backlog PB-1) with CSV in/out and
// an edit audit log. Confirmed values render green; estimated values ORANGE
// until the shop confirms them (per-row Confirm action).
import { lsGet, lsSet } from "./storage";
import type { StrategySetup, StrategyOp } from "./api";

export type ToleranceClass = "H6" | "H7" | "H8" | "H9" | "H11" | "free" | "thread";

export interface HoleCostRow {
  id: string;
  diameter_mm: number;
  tolerance: ToleranceClass;
  thickness_mm: number;
  operation: string; // Drill | Drill+Ream | Bore | Bore+Ream | Tap | Counter-bore
  cost_inr: number;
  effective_from: string; // ISO date — versioning so old quotes stay reproducible
  source: string;
  confirmed: boolean; // false = ORANGE "estimated — not confirmed by shop"
}

export interface AuditEntry {
  at: string;
  user: string;
  action: string;
  before: string;
  after: string;
}

export interface CostingProfile {
  id: string;
  name: string; // usually the machine name
  model: "time" | "ratecard";
  milling_rate_per_cm2: number; // ARD: 0.60
  milling_rate_grinding_per_cm2: number; // ARD: 0.80 when surface grinding
  addon_rates: {
    grinding_per_cm2: number;
    plating_per_cm2: number;
    hardening_per_kg: number;
    powder_per_cm2: number;
  };
  holeLibrary: HoleCostRow[];
  auditLog: AuditEntry[];
}

// ARD §6.3 preferred H7 series for nearest-diameter snapping.
export const STANDARD_DIAMETERS = [
  3, 4, 5, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24, 25, 30, 35, 40, 45, 50,
];

// Generic fallback: derived from the ONE confirmed shop value
// (24 mm H7 through 50 mm = ₹800  →  ₹16 per mm of thickness at Ø24 H7),
// scaled by diameter ratio and a tolerance factor. Estimates only.
const BASE_PER_MM_THICKNESS = 16.0; // ₹/mm at Ø24 H7
const TOL_FACTOR: Record<ToleranceClass, number> = {
  H6: 1.25, H7: 1.0, H8: 0.85, H9: 0.75, H11: 0.65, free: 0.6, thread: 1.1,
};

export function genericHoleCost(
  dia: number,
  tol: ToleranceClass,
  thickness: number,
): number {
  const d = Math.max(dia, 1);
  const t = Math.max(thickness, 1);
  return Math.round(BASE_PER_MM_THICKNESS * (d / 24) * (TOL_FACTOR[tol] ?? 1) * t);
}

function seedRow(
  dia: number, tol: ToleranceClass, thick: number, op: string,
  cost: number, confirmed: boolean, source: string,
): HoleCostRow {
  return {
    id: `seed-${dia}-${tol}-${thick}`,
    diameter_mm: dia, tolerance: tol, thickness_mm: thick, operation: op,
    cost_inr: cost, effective_from: "2026-07-12",
    source, confirmed,
  };
}

// ARD §6.4 seed: ONE confirmed reviewer value + interpolable neighbours as
// clearly-marked estimates (thickness-linear / factor-scaled placeholders).
export function defaultHoleLibrary(): HoleCostRow[] {
  return [
    seedRow(24, "H7", 50, "Drill+Ream", 800, true, "Reviewer feedback 2026-07"),
    seedRow(24, "H7", 25, "Drill+Ream", genericHoleCost(24, "H7", 25), false, "estimated (thickness-scaled)"),
    seedRow(24, "H7", 75, "Drill+Ream", genericHoleCost(24, "H7", 75), false, "estimated (thickness-scaled)"),
    seedRow(20, "H7", 50, "Drill+Ream", genericHoleCost(20, "H7", 50), false, "estimated (diameter-scaled)"),
    seedRow(25, "H7", 50, "Drill+Ream", genericHoleCost(25, "H7", 50), false, "estimated (diameter-scaled)"),
    seedRow(24, "H8", 50, "Drill", genericHoleCost(24, "H8", 50), false, "estimated (tolerance factor)"),
    seedRow(24, "free", 50, "Drill", genericHoleCost(24, "free", 50), false, "estimated (tolerance factor)"),
  ];
}

export function defaultProfile(name: string): CostingProfile {
  return {
    id: `profile-${name}`,
    name,
    model: "time",
    milling_rate_per_cm2: 0.6,
    milling_rate_grinding_per_cm2: 0.8,
    addon_rates: {
      grinding_per_cm2: 0.2, // placeholder — TBD with shop (ARD 7.2)
      plating_per_cm2: 0.5,
      hardening_per_kg: 60,
      powder_per_cm2: 0.35,
    },
    holeLibrary: defaultHoleLibrary(),
    auditLog: [],
  };
}

// ---- storage ---------------------------------------------------------------
const LS_KEY = "cnc.costing.profiles";

export function loadProfiles(): CostingProfile[] {
  try {
    const raw = lsGet(LS_KEY);
    const arr = raw ? (JSON.parse(raw) as CostingProfile[]) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

export function saveProfiles(profiles: CostingProfile[]): void {
  lsSet(LS_KEY, JSON.stringify(profiles));
}

// Profile for a machine — created from the default rate card on first use.
export function profileForMachine(machineName: string): CostingProfile {
  const profiles = loadProfiles();
  const found = profiles.find((p) => p.name === machineName);
  if (found) return found;
  const fresh = defaultProfile(machineName || "Default");
  saveProfiles([...profiles, fresh]);
  return fresh;
}

export function updateProfile(next: CostingProfile): void {
  const profiles = loadProfiles();
  const i = profiles.findIndex((p) => p.id === next.id);
  if (i >= 0) profiles[i] = next;
  else profiles.push(next);
  saveProfiles(profiles);
}

export function audit(
  p: CostingProfile, action: string, before: string, after: string,
): CostingProfile {
  return {
    ...p,
    auditLog: [
      ...p.auditLog,
      { at: new Date().toISOString(), user: "local", action, before, after },
    ].slice(-500),
  };
}

// ---- hole lookup (ARD §6.3, in order) --------------------------------------
export interface HoleCostResult {
  cost_inr: number;
  // exact / interpolated / nearest-diameter / generic-fallback
  method: "exact" | "interpolated" | "nearest_diameter" | "fallback";
  // ORANGE when true: any non-exact method OR an unconfirmed matched row.
  estimated: boolean;
  matched_row_id: string | null;
  note: string;
}

export function lookupHoleCost(
  lib: HoleCostRow[],
  dia: number,
  tol: ToleranceClass,
  thickness: number,
): HoleCostResult {
  const sameTol = lib.filter((r) => r.tolerance === tol);
  const sameDia = sameTol.filter((r) => Math.abs(r.diameter_mm - dia) < 0.26);

  // 1. exact (dia + tol + thickness)
  const exact = sameDia.find((r) => Math.abs(r.thickness_mm - thickness) < 0.51);
  if (exact) {
    return {
      cost_inr: exact.cost_inr,
      method: "exact",
      estimated: !exact.confirmed,
      matched_row_id: exact.id,
      note: exact.confirmed ? "library (confirmed)" : "library (estimated row)",
    };
  }

  // 2. thickness interpolation on same dia + tol
  if (sameDia.length >= 1) {
    const sorted = [...sameDia].sort((a, b) => a.thickness_mm - b.thickness_mm);
    const below = [...sorted].reverse().find((r) => r.thickness_mm <= thickness);
    const above = sorted.find((r) => r.thickness_mm >= thickness);
    if (below && above && below.id !== above.id) {
      const f =
        (thickness - below.thickness_mm) /
        Math.max(above.thickness_mm - below.thickness_mm, 1e-6);
      const cost = Math.round(below.cost_inr + f * (above.cost_inr - below.cost_inr));
      return {
        cost_inr: cost, method: "interpolated", estimated: true,
        matched_row_id: below.id,
        note: `interpolated ${below.thickness_mm}–${above.thickness_mm} mm`,
      };
    }
    const nearest = below ?? above!;
    const cost = Math.round(
      nearest.cost_inr * (thickness / Math.max(nearest.thickness_mm, 1)),
    );
    return {
      cost_inr: cost, method: "interpolated", estimated: true,
      matched_row_id: nearest.id,
      note: `scaled from ${nearest.thickness_mm} mm row`,
    };
  }

  // 3. nearest standard diameter, same tolerance
  if (sameTol.length) {
    const snap = STANDARD_DIAMETERS.reduce((a, b) =>
      Math.abs(b - dia) < Math.abs(a - dia) ? b : a,
    );
    const nearDia = [...sameTol].sort(
      (a, b) => Math.abs(a.diameter_mm - snap) - Math.abs(b.diameter_mm - snap),
    )[0];
    if (nearDia) {
      const thickScaled = Math.round(
        nearDia.cost_inr * (thickness / Math.max(nearDia.thickness_mm, 1)),
      );
      const diaScaled = Math.round(
        thickScaled * (dia / Math.max(nearDia.diameter_mm, 1)),
      );
      return {
        cost_inr: diaScaled, method: "nearest_diameter", estimated: true,
        matched_row_id: nearDia.id,
        note: `nearest Ø${nearDia.diameter_mm} ${nearDia.tolerance} row, scaled`,
      };
    }
  }

  // 4. generic fallback + warning
  return {
    cost_inr: genericHoleCost(dia, tol, thickness),
    method: "fallback", estimated: true, matched_row_id: null,
    note: "cost estimated — no library match",
  };
}

// Tolerance class we can INFER from detection (no tolerance data in STEP):
// threaded → "thread"; counterbored clearance → "free"; else assume H7 (the
// shop's own pricing convention from the feedback). Overridable via library.
export function inferTolerance(g: {
  thread_likely?: string | null;
  cbore_diameter_mm?: number | null;
}): ToleranceClass {
  if (g.thread_likely) return "thread";
  if (g.cbore_diameter_mm) return "free";
  return "H7";
}

// ---- rate-card pricing over a plan ------------------------------------------
export interface RateCardBreakdown {
  millingAreaCm2: number;
  millingRate: number;
  millingCost: number;
  holes: {
    feature: string;
    dia: number;
    tolerance: ToleranceClass;
    thickness: number;
    cost: number;
    estimated: boolean;
    method: HoleCostResult["method"];
    note: string;
  }[];
  holeCost: number;
  estimatedCount: number; // orange items in this quote
  fallbackCount: number;
  total: number; // milling + holes (per piece; material/setup/addons layered on top)
}

const HOLE_OPS = new Set(["Spot Drill", "Drill", "Pilot Drill", "Boring", "Tap"]);

function baseName(name: string): string {
  return (name || "")
    .replace(/\s*\((?:Rough|Finish)\)\s*$/i, "")
    .replace(/\s*-\s*(?:wall|floor)\s*finish\s*$/i, "")
    .replace(/\s*-\s*(?:rough|finish)\s*bore\s*$/i, "")
    .replace(/\s*-\s*facing\s*(?:rough|finish)\s*$/i, "")
    .trim();
}

export function rateCardBreakdown(
  setups: StrategySetup[],
  profile: CostingProfile,
  opts: { grinding: boolean; isOpExcluded?: (op: StrategyOp) => boolean },
): RateCardBreakdown {
  const excluded = opts.isOpExcluded ?? (() => false);
  const rate = opts.grinding
    ? profile.milling_rate_grinding_per_cm2
    : profile.milling_rate_per_cm2;

  // Milling: each PHYSICAL SURFACE priced once — dedupe ops by feature,
  // take the largest op area within the feature (rough covers the surface;
  // finish passes are included in the shop's ₹/cm² rate).
  const areaByFeature = new Map<string, number>();
  const holeFeatures = new Map<
    string,
    { dia: number; thickness: number; tol: ToleranceClass }
  >();

  for (const su of setups) {
    for (const op of su.ops) {
      if (excluded(op)) continue;
      if (op.lathe) continue;
      const f = baseName(op.feature || op.operation || "");
      const g = op.geo?.geometry;
      const isHole =
        (g && g.kind === "hole") || HOLE_OPS.has(op.operation || "");
      if (isHole) {
        if (g && g.kind === "hole" && !holeFeatures.has(f)) {
          holeFeatures.set(f, {
            dia: g.diameter_mm,
            thickness: g.depth_mm || 10,
            tol: inferTolerance(g),
          });
        }
        continue;
      }
      const a = op.machined_area_cm2 || 0;
      if (a > (areaByFeature.get(f) ?? 0)) areaByFeature.set(f, a);
    }
  }

  const millingAreaCm2 =
    Math.round([...areaByFeature.values()].reduce((s, a) => s + a, 0) * 100) / 100;
  const millingCost = millingAreaCm2 * rate;

  const holes: RateCardBreakdown["holes"] = [];
  let holeCost = 0;
  let estimatedCount = 0;
  let fallbackCount = 0;
  for (const [feature, h] of holeFeatures) {
    const r = lookupHoleCost(profile.holeLibrary, h.dia, h.tol, h.thickness);
    holes.push({
      feature, dia: h.dia, tolerance: h.tol, thickness: h.thickness,
      cost: r.cost_inr, estimated: r.estimated, method: r.method, note: r.note,
    });
    holeCost += r.cost_inr;
    if (r.estimated) estimatedCount++;
    if (r.method === "fallback") fallbackCount++;
  }

  const anyMillingEstimated = millingAreaCm2 > 0; // rates themselves are shop-set
  void anyMillingEstimated;

  return {
    millingAreaCm2,
    millingRate: rate,
    millingCost,
    holes,
    holeCost,
    estimatedCount,
    fallbackCount,
    total: millingCost + holeCost,
  };
}

// ---- CSV import / export ----------------------------------------------------
const CSV_HEADER =
  "diameter_mm,tolerance,thickness_mm,operation,cost_inr,effective_from,source,confirmed";

export function libraryToCsv(lib: HoleCostRow[]): string {
  const esc = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  return [
    CSV_HEADER,
    ...lib.map((r) =>
      [
        r.diameter_mm, r.tolerance, r.thickness_mm, esc(r.operation),
        r.cost_inr, r.effective_from, esc(r.source), r.confirmed ? "yes" : "no",
      ].join(","),
    ),
  ].join("\n");
}

export function csvToLibrary(text: string): HoleCostRow[] {
  const rows: HoleCostRow[] = [];
  const lines = text.split(/\r?\n/).filter((l) => l.trim());
  for (const line of lines.slice(1)) {
    // simple CSV split honouring quotes
    const cells: string[] = [];
    let cur = "";
    let q = false;
    for (let i = 0; i < line.length; i++) {
      const ch = line[i];
      if (q) {
        if (ch === '"' && line[i + 1] === '"') { cur += '"'; i++; }
        else if (ch === '"') q = false;
        else cur += ch;
      } else if (ch === '"') q = true;
      else if (ch === ",") { cells.push(cur); cur = ""; }
      else cur += ch;
    }
    cells.push(cur);
    if (cells.length < 8) continue;
    const dia = parseFloat(cells[0]);
    const thick = parseFloat(cells[2]);
    const cost = parseFloat(cells[4]);
    if (!Number.isFinite(dia) || !Number.isFinite(thick) || !Number.isFinite(cost))
      continue;
    rows.push({
      id: `csv-${dia}-${cells[1]}-${thick}-${rows.length}`,
      diameter_mm: dia,
      tolerance: (cells[1].trim() as ToleranceClass) || "H7",
      thickness_mm: thick,
      operation: cells[3].trim() || "Drill",
      cost_inr: cost,
      effective_from: cells[5].trim() || new Date().toISOString().slice(0, 10),
      source: cells[6].trim() || "CSV import",
      confirmed: /^(yes|true|1)$/i.test(cells[7].trim()),
    });
  }
  return rows;
}
