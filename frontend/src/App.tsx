import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, PointerEvent as ReactPointerEvent } from "react";
import { api, SAMPLE_NAME } from "./api";
import type {
  AnalyzeResult, StrategyResult, StrategyOp, StrategySetup, Material, OpGeo, Mesh,
  WeldmentResult, WeldmentGroup, MachineInfo, MachineOpts, MaterialOpts, PlanBasis,
  FeatureGeometry, FeatureCounts, Candidate, AssistantContext,
} from "./api";
import { PartViewer } from "./PartViewer";
import {
  profileForMachine, rateCardBreakdown, updateProfile, audit, baseName,
  inferTolerance, loadProfiles, saveProfiles, addonLibraryFor,
  type RateCardBreakdown, type AddonBasis,
} from "./costing";
import { CostLibraryPanel } from "./CostLibraryPanel";
import { ShopLibrary } from "./ShopLibrary";
import { exportShopFile, importShopFile } from "./shopFile";
import { buildWorkbook, type WorkbookPayload } from "./excelExport";
import type { Vec3, Approach, Highlight } from "./PartViewer";
import { MaterialSelect } from "./MaterialSelect";
import { MachineSelect } from "./MachineSelect";
import type { CustomMachine } from "./MachineSelect";
import { BottomPanel } from "./BottomPanel";
import { QuoteModal } from "./QuoteModal";
import { AssistantPanel } from "./AssistantPanel";
import { lsGet, lsSet } from "./storage";

type Tab = "overview" | "strategy" | "estimate" | "route";
type Theme = "dark" | "light";

const INSPECTOR_MIN = 200;
const INSPECTOR_MAX = 560;
const INSPECTOR_DEFAULT = 320;

// Setup label → direction from part center to the camera (raw-CAD frame,
// Z-up parts). Also the outward normal of the setup's stock face.
const SETUP_DIRS: Record<string, Vec3> = {
  top: [0, 0, 1],
  bottom: [0, 0, -1],
  front: [0, 1, 0],
  back: [0, -1, 0],
  left: [-1, 0, 0],
  right: [1, 0, 0],
};
// Unknown setup labels fall back to a front-right-top isometric view.
const ISO_DIR: Vec3 = [0.577, -0.577, 0.577];

// Distinct per-setup colors (Toolpath-style color-coded setups). Assigned by
// setup order; shared by the Strategy list band and the 3D highlight so a
// setup reads the same everywhere.
const SETUP_COLORS = [
  "#4a9eff", "#e0a63b", "#5ac36a", "#c86ee0", "#e06a6a",
  "#3ec9c9", "#e0c93b", "#7a8cff", "#e07ab0", "#8a9aa8",
];
function setupColorAt(i: number): string {
  return SETUP_COLORS[((i % SETUP_COLORS.length) + SETUP_COLORS.length) % SETUP_COLORS.length];
}

// Bore setups ("Front (Bore)") orient like their parent face — strip the
// suffix before the SETUP_DIRS lookup.
function normalizeSetupLabel(label: string): string {
  return label.replace(/\s*\(bore\)\s*$/i, "").trim().toLowerCase();
}

function gradeClass(grade: string) {
  if (grade === "A") return "green";
  if (grade === "B" || grade === "C") return "amber";
  return "red";
}

// Machinable-surface badge: >=95 green, >=80 amber, below red
function msaClass(pct: number) {
  if (pct >= 95) return "green";
  if (pct >= 80) return "amber";
  return "red";
}

// Setups on these faces mean the part comes off the primary fixture —
// the viewer shows an amber flip indicator for them.
const SECONDARY_FACE_RE = /bottom|back|left/i;

function loadViewerOpacity(): number {
  const v = Number(lsGet("cnc.viewerOpacity"));
  return Number.isFinite(v) && v >= 0.2 && v <= 1 ? v : 1;
}

export interface ViewerLayers {
  grid: boolean;
  dims: boolean;
  stock: boolean;
  fixture: boolean;
  // WS-B: show pickable feature dots for the 3D right-click deselect. Off by
  // default so the part isn't covered in markers.
  select: boolean;
}
const DEFAULT_LAYERS: ViewerLayers = { grid: true, dims: true, stock: false, fixture: false, select: false };
function loadLayers(): ViewerLayers {
  try {
    const raw = lsGet("cnc.viewerLayers");
    if (!raw) return DEFAULT_LAYERS;
    const o = JSON.parse(raw) as Partial<ViewerLayers>;
    return {
      grid: o.grid ?? true,
      dims: o.dims ?? true,
      stock: o.stock ?? false,
      fixture: o.fixture ?? false,
      select: o.select ?? false,
    };
  } catch {
    return DEFAULT_LAYERS;
  }
}

function loadCustomMachines(): CustomMachine[] {
  try {
    const raw = lsGet("cnc.customMachines");
    const arr: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr.filter(
      (m): m is CustomMachine =>
        !!m && typeof (m as CustomMachine).name === "string" && (m as CustomMachine).name.length > 0,
    );
  } catch {
    return [];
  }
}

// User-defined materials (cnc.customMaterials). All three factors must be
// finite numbers — the selector and the estimate mass math rely on them.
function loadCustomMaterials(): Material[] {
  try {
    const raw = lsGet("cnc.customMaterials");
    const arr: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr.filter((m): m is Material => {
      const c = m as Material;
      return (
        !!c &&
        typeof c.name === "string" &&
        c.name.length > 0 &&
        Number.isFinite(c.density) &&
        Number.isFinite(c.machinability_factor) &&
        Number.isFinite(c.safety_factor)
      );
    });
  } catch {
    return [];
  }
}

// ---- Operator-controlled estimation (Estimate tab settings) ----
// Quote preset scales ONLY the machining-time cost lines: textbook
// two-pass planning (×1.00) down to a competitive shop quote (×0.70).
type QuotePreset = "conservative" | "standard" | "competitive";
const PRESET_MULT: Record<QuotePreset, number> = {
  conservative: 1.0,
  standard: 0.85,
  competitive: 0.7,
};

// Tolerance class scales machining cost — tighter tolerances mean slower
// feeds, more passes, and in-process inspection.
type ToleranceClass = "general" | "medium" | "fine" | "precision";
const TOLERANCE_MULT: Record<ToleranceClass, number> = {
  general: 1.0,
  medium: 1.15,
  fine: 1.35,
  precision: 1.6,
};

const COMPLEXITY_MIN = 0.8;
const COMPLEXITY_MAX = 1.5;

function loadBasis(): PlanBasis {
  return lsGet("cnc.estBasis") === "raw" ? "raw" : "grouped";
}

function loadPreset(): QuotePreset {
  const v = lsGet("cnc.estPreset");
  return v === "standard" || v === "competitive" ? v : "conservative";
}

function loadComplexity(): number {
  const v = Number(lsGet("cnc.estComplexity"));
  return Number.isFinite(v) && v >= COMPLEXITY_MIN && v <= COMPLEXITY_MAX ? v : 1.0;
}

function loadTolerance(): ToleranceClass {
  const v = lsGet("cnc.estTolerance");
  return v === "medium" || v === "fine" || v === "precision" ? v : "general";
}

// Lenient numeric input parse — empty/garbage becomes 0, never NaN
const numOr0 = (s: string) => {
  const v = parseFloat(s);
  return Number.isFinite(v) && v >= 0 ? v : 0;
};

// Shared money/time formatters (Estimate + Route tabs)
// Display currency for ALL money in the app (estimate, route, effort sheet).
// Symbol-only by design: the shop enters its rates (₹/hr, ₹/kg, setup charge)
// in whatever currency it works in, so no FX conversion happens — the selector
// just relabels. Mirrors the Quote modal's currency list (Gulf-ready).
const CURRENCIES: { code: string; symbol: string }[] = [
  { code: "INR", symbol: "₹" }, { code: "USD", symbol: "$" },
  { code: "AED", symbol: "AED " }, { code: "SAR", symbol: "SAR " },
  { code: "QAR", symbol: "QAR " }, { code: "OMR", symbol: "OMR " },
  { code: "KWD", symbol: "KD " }, { code: "BHD", symbol: "BD " },
  { code: "EUR", symbol: "€" }, { code: "GBP", symbol: "£" },
];
let CUR_SYM = "₹"; // kept in sync with the selected currency on every render
const inr = (v: number) => CUR_SYM + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const fmtMin = (min: number) => {
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m} min`;
};
// Finer duration for the machining breakdown rows: minutes+seconds under an
// hour, bare seconds under a minute — so sub-minute cutting never reads "0 min".
const fmtDur = (min: number) => {
  if (min >= 60) { const m = Math.round(min); return `${Math.floor(m / 60)}h ${m % 60}m`; }
  const s = Math.round(min * 60);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
};

// ---- Exact-face highlight (Feature A) ----
// A candidate's face_mesh_data has shipped in three shapes across backend
// versions: a single plotly-style {x,y,z,i,j,k} mesh, an array of those, or
// an array of tessellation dicts {vertices:[[x,y,z]...], triangles:[[i,j,k]...]}
// (the current /api/analyze shape). Normalize all of them to Mesh[] and drop
// anything malformed — a missing overlay falls back to the marker.
function normalizeFaceMeshes(raw: unknown): Mesh[] {
  const asNums = (a: unknown): number[] | null =>
    Array.isArray(a) && a.every((v) => typeof v === "number") ? (a as number[]) : null;

  const one = (m: unknown): Mesh | null => {
    if (!m || typeof m !== "object") return null;
    const o = m as Record<string, unknown>;
    // Shape 1: plotly-style mesh dict
    const x = asNums(o.x), y = asNums(o.y), z = asNums(o.z);
    const i = asNums(o.i), j = asNums(o.j), k = asNums(o.k);
    if (x && y && z && i && j && k && x.length && i.length) return { x, y, z, i, j, k };
    // Shape 2: tessellation dict {vertices, triangles}
    if (Array.isArray(o.vertices) && Array.isArray(o.triangles)) {
      const mx: number[] = [], my: number[] = [], mz: number[] = [];
      for (const v of o.vertices) {
        if (!Array.isArray(v) || v.length < 3) return null;
        mx.push(Number(v[0])); my.push(Number(v[1])); mz.push(Number(v[2]));
      }
      const mi: number[] = [], mj: number[] = [], mk: number[] = [];
      for (const t of o.triangles) {
        if (!Array.isArray(t) || t.length < 3) return null;
        mi.push(Number(t[0])); mj.push(Number(t[1])); mk.push(Number(t[2]));
      }
      if (mx.length && mi.length) return { x: mx, y: my, z: mz, i: mi, j: mj, k: mk };
    }
    return null;
  };

  const list = Array.isArray(raw) ? raw : raw ? [raw] : [];
  const out: Mesh[] = [];
  for (const m of list) {
    const n = one(m);
    if (n) out.push(n);
  }
  return out;
}

// ---- Process Route (Feature B) ----
// Weldment classifications that belong on a lathe, not the VMC.
const TURNED_RE = /^(shaft|tube)$/i;

// Operator-added route steps (deburr, anodize, inspection...). Persisted —
// a shop's post-processes are stable across parts.
interface CustomRouteStep {
  id: string;
  name: string;
  timeMin: number;
  rateHr: number;
  station: string;
}

function loadCustomRouteSteps(): CustomRouteStep[] {
  try {
    const raw = lsGet("cnc.customRouteSteps");
    const arr: unknown = raw ? JSON.parse(raw) : [];
    if (!Array.isArray(arr)) return [];
    return arr.filter((s): s is CustomRouteStep => {
      const c = s as CustomRouteStep;
      return (
        !!c &&
        typeof c.id === "string" &&
        typeof c.name === "string" &&
        c.name.length > 0 &&
        Number.isFinite(c.timeMin) &&
        c.timeMin >= 0 &&
        Number.isFinite(c.rateHr) &&
        c.rateHr >= 0 &&
        typeof c.station === "string"
      );
    });
  } catch {
    return [];
  }
}

function loadWeldRate(): number {
  const v = Number(lsGet("cnc.routeWeldRate"));
  return Number.isFinite(v) && v > 0 ? v : 400;
}

// "Setup 3","Setup 5" → "Setup 3,5" · "Top" → "Setup Top"
function formatSetups(setups: string[]): string {
  if (!setups.length) return "—";
  return "Setup " + setups.map((s) => s.replace(/^setup\s*/i, "")).join(",");
}

// ---- Per-body scope helpers (multibody weldments) ----
// Backend classifications are lowercase ("plate") — display as "Plate".
function titleCase(s: string) {
  return s ? s[0].toUpperCase() + s.slice(1) : s;
}

// 13.0 → "13", 37.2 → "37.2"
function fmtNum(v: number) {
  return Number(v.toFixed(1)).toString();
}

// Mass display: "NNN g" under 1 kg, else "N.NN kg" (customer spec).
function fmtMass(grams: number | null | undefined): string {
  if (grams == null || !Number.isFinite(grams)) return "—";
  if (grams < 1000) return `${Math.round(grams)} g`;
  return `${(grams / 1000).toFixed(2)} kg`;
}

// Volume with thousands separators, e.g. "2,121 cm³" (matches Toolpath).
function fmtVolCm3(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${Math.round(v).toLocaleString("en-US")} cm³`;
}

// Machined (machinable) surface area, e.g. "501 cm²".
function fmtAreaCm2(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${Math.round(v).toLocaleString("en-US")} cm²`;
}

function groupDims(g: WeldmentGroup) {
  return `${fmtNum(g.dims_mm.length)} × ${fmtNum(g.dims_mm.width)} × ${fmtNum(g.dims_mm.height)}`;
}

// body_indices are 0-based from the splitter; shop-floor labels are 1-based.
function bodyLabel(g: WeldmentGroup) {
  const nums = g.body_indices.map((i) => i + 1);
  const shown = nums.slice(0, 4).join(",");
  return `${nums.length === 1 ? "Body" : "Bodies"} ${shown}${nums.length > 4 ? "…" : ""}`;
}

function scopeLabel(g: WeldmentGroup) {
  return `${titleCase(g.classification)} ×${g.quantity} (${bodyLabel(g)})`;
}

// "22 holes · 4 slots · 3 fillet faces" — fillet/chamfer terms only when
// present. Shared by the Bodies list rows and the scoped-strategy chip.
function typedCounts(fc: FeatureCounts): string {
  let s = `${fc.holes} holes · ${fc.slots} slots`;
  if ((fc.likely_threaded ?? 0) > 0) s += ` · ${fc.likely_threaded} likely tapped`;
  if (fc.fillet_faces > 0) s += ` · ${fc.fillet_faces} fillet faces`;
  if (fc.chamfer_faces > 0) s += ` · ${fc.chamfer_faces} chamfer faces`;
  return s;
}

// Consecutive ops in a setup that share operation type + tool collapse
// into one rollup row (Toolpath-style "Drilling ×22 — Drill 8mm").
interface OpRollup {
  key: string;
  operation: string;
  tool: string; // raw engine tool name — grouping key
  toolDisplay: string; // catalog-style name for display ("6mm Drill 135°")
  ops: StrategyOp[];
  totalMin: number;
}

// A user-selected add-on process for the current part. Seeded from the rate
// card's add-on library but editable inline (basis + rate), or a one-off
// "Custom" row. `param` is an optional note (Ni, 45 HRC, RAL 7035, …).
type AddonSelection = {
  uid: string;
  procId: string | null; // library process id, or null for a custom row
  name: string;
  basis: AddonBasis;
  rate: number;
  area: "surface" | "machined";
  param?: string;
};

// Price the selected add-ons. per_cm2 uses machined area (grinding) or the
// external stock-envelope area (plating/coating); per_kg uses part weight;
// flat is a lump sum (e.g. an outsourced quote). Returns {name, cost}[] so
// every downstream consumer (ledger, route, Excel, effort doc) is unchanged.
function computeAddonSelections(
  sels: AddonSelection[],
  ctx: { envAreaCm2: number; machinedAreaCm2: number; massKg: number },
): { name: string; cost: number }[] {
  return sels
    .filter((a) => a.name.trim())
    .map((a) => {
      const r = a.rate || 0;
      let cost = 0;
      if (a.basis === "flat") cost = r;
      else if (a.basis === "per_kg") cost = r * ctx.massKg;
      else cost = r * (a.area === "machined" ? ctx.machinedAreaCm2 : ctx.envAreaCm2);
      const label =
        a.param && a.param.trim() ? `${a.name.trim()} (${a.param.trim()})` : a.name.trim();
      return { name: label, cost };
    });
}

function buildRollups(setupLabel: string, ops: StrategyOp[]): OpRollup[] {
  const out: OpRollup[] = [];
  for (const op of ops) {
    const last = out[out.length - 1];
    if (last && last.operation === op.operation && last.tool === op.tool) {
      last.ops.push(op);
      last.totalMin += op.cut_min;
    } else {
      out.push({
        key: `${setupLabel}:${out.length}`,
        operation: op.operation,
        tool: op.tool,
        toolDisplay: op.tool_display || op.tool,
        ops: [op],
        totalMin: op.cut_min,
      });
    }
  }
  return out;
}

// ---- Machining cost breakdown by feature category (Estimate tab) ----
// Toolpath shows where the machining minutes go per feature category plus a
// tool-change line; we adopt the same view. The category cutting rows +
// positioning + tool-changes + machine-setup are the four components of
// total_machine_time_min, so they reconcile exactly to the machining cost.
const CATEGORY_ORDER = [
  "facing", "holes", "slots", "pockets", "profile", "edges", "turning", "other",
] as const;
type CategoryKey = (typeof CATEGORY_ORDER)[number];

function opCategory(op: StrategyOp): { key: CategoryKey; label: string } {
  if (op.lathe) return { key: "turning", label: "Turning" };
  const s = `${op.feature || ""} ${op.operation || ""}`.toLowerCase();
  if (/\b(?:od|id)\s*turn|turning|groove|face\s*turn/.test(s)) return { key: "turning", label: "Turning" };
  // Edges before facing: a chamfer/edge-break op on a faced surface carries
  // "face" in its text but belongs in Chamfer & edges, not Facing.
  if (/chamfer|deburr|fillet|edge/.test(s)) return { key: "edges", label: "Chamfer & edges" };
  if (/face|facing/.test(s)) return { key: "facing", label: "Facing" };
  if (/hole|drill|ream|bore|spot|tap|c'?bore|counterbore|countersink|c'?sink/.test(s))
    return { key: "holes", label: "Holes & drilling" };
  if (/slot/.test(s)) return { key: "slots", label: "Slots" };
  if (/pocket/.test(s)) return { key: "pockets", label: "Pockets" };
  if (/contour|profile|perimeter|outline|\bstep\b/.test(s)) return { key: "profile", label: "Profile & contour" };
  return { key: "other", label: "Other milling" };
}

// Strip rough/finish variant suffixes so a feature machined over several
// passes counts once (mirrors the backend's _base_feature).
function baseFeatureName(name: string): string {
  return (name || "")
    .replace(/\s*\((?:Rough|Finish)\)\s*$/i, "")
    .replace(/\s*-\s*(?:wall|floor)\s*finish\s*$/i, "")
    .replace(/\s*-\s*(?:rough|finish)\s*bore\s*$/i, "")
    .replace(/\s*-\s*facing\s*(?:rough|finish)\s*$/i, "")
    .trim();
}

// Feature Table rows from the SCOPED plan (gap-v5 A2 + C1). The whole-part
// billet detector over-segments slots (one long slot shows up 15x); the
// scoped plan's features come from the exact classifier, which already lists
// each physical feature once. Group the plan's ops back to their physical
// feature (rough/finish variants collapse) and tag each with its setup — so
// the table de-dupes AND the previously-empty Setup column fills in.
function buildScopedFeatureRows(sp: StrategyResult): Candidate[] {
  const byName = new Map<string, Candidate>();
  for (const su of sp.setups) {
    for (const op of su.ops) {
      const base = baseFeatureName(op.feature || "");
      if (!base) continue;
      const existing = byName.get(base);
      if (existing) {
        if (!existing.setup) existing.setup = su.setup_label;
        continue;
      }
      const g = op.geo;
      const ft = (g?.feature_type || "").toLowerCase();
      const threadLikely =
        g?.geometry && g.geometry.kind === "hole" ? g.geometry.thread_likely : null;
      byName.set(base, {
        candidate_id: g?.candidate_id ?? base,
        feature_type: g?.feature_type || op.operation || "—",
        feature_name: base,
        diameter: g?.diameter || undefined,
        length: g?.length || undefined,
        width: g?.width || undefined,
        depth: g?.depth || undefined,
        confidence: "exact",
        setup: su.setup_label,
        thread: threadLikely || (ft.includes("hole") ? "No Thread" : undefined),
      });
    }
  }
  return [...byName.values()];
}

interface MachiningBreakdown {
  categories: { key: CategoryKey; label: string; count: number; min: number; cost: number }[];
  rapid: { min: number; cost: number };
  toolChanges: { count: number; min: number; cost: number };
  machineSetup: { min: number; cost: number };
}

function buildMachiningBreakdown(
  setups: StrategySetup[],
  totals: StrategyResult["totals"],
  rateHr: number,
  machMult: number,
): MachiningBreakdown {
  const machineMin = totals.total_machine_time_min ?? 0;
  const rapidMin = totals.rapid_time_min ?? 0;
  const tcMin = totals.tool_change_time_min ?? 0;
  const setupMin = totals.setup_time_min ?? 0;
  const tcCount = totals.num_tool_changes ?? 0;

  const cat = new Map<CategoryKey, { label: string; minRaw: number; feats: Set<string> }>();
  for (const su of setups) {
    for (const op of su.ops) {
      const c = opCategory(op);
      let e = cat.get(c.key);
      if (!e) { e = { label: c.label, minRaw: 0, feats: new Set() }; cat.set(c.key, e); }
      e.minRaw += op.cut_min || 0;
      e.feats.add(baseFeatureName(op.feature));
    }
  }

  // The authoritative cutting total is (machine − rapid − tc − setup). Per-op
  // cut_min sums to ≈ that (differs only by per-op rounding); scale the
  // category cutting so the category minutes sum to it exactly.
  const sumCatRaw = [...cat.values()].reduce((a, e) => a + e.minRaw, 0);
  const cutMinAuth = Math.max(machineMin - rapidMin - tcMin - setupMin, 0);
  const scale = sumCatRaw > 0 ? cutMinAuth / sumCatRaw : 0;
  const costF = (min: number) => (min / 60) * rateHr * machMult;

  const catList = [...cat.entries()]
    .map(([key, e]) => ({ key, label: e.label, count: e.feats.size, min: e.minRaw * scale }))
    .filter((c) => c.min > 0.001 || c.count > 0)
    .sort((a, b) => CATEGORY_ORDER.indexOf(a.key) - CATEGORY_ORDER.indexOf(b.key));

  // Round every rupee cost with the largest-remainder method so the displayed
  // rows sum EXACTLY to the rounded machining total — no ±₹1 drift. Σ of the
  // row minutes is machineMin, so Σ floatCosts == machining and the header
  // (inr(machining)) equals `target`.
  const rowMins = [...catList.map((c) => c.min), rapidMin, tcMin, setupMin];
  const target = Math.round(costF(machineMin));
  const floatCosts = rowMins.map(costF);
  const intCosts = floatCosts.map(Math.floor);
  let residual = target - intCosts.reduce((a, b) => a + b, 0);
  const byFrac = floatCosts
    .map((c, idx) => ({ idx, frac: c - Math.floor(c) }))
    .sort((a, b) => b.frac - a.frac);
  for (let k = 0; k < byFrac.length && residual > 0; k++, residual--) intCosts[byFrac[k].idx]++;

  const nCat = catList.length;
  return {
    categories: catList.map((c, i) => ({ ...c, cost: intCosts[i] })),
    rapid: { min: rapidMin, cost: intCosts[nCat] },
    toolChanges: { count: tcCount, min: tcMin, cost: intCosts[nCat + 1] },
    machineSetup: { min: setupMin, cost: intCosts[nCat + 2] },
  };
}

// ---- Effort Estimate (MVP-1): a print-ready internal document for whoever
// prices the job. Distinct from the customer Quote — it shows the effort
// DRIVERS (time by feature category, tool changes, setups, cost breakdown),
// not a customer-facing price sheet. Built entirely client-side from data the
// app already has and printed via the browser (Save as PDF).
interface EffortEstimateParams {
  filename: string;
  scopeLabel: string;
  // The USER's letterhead (shop that owns the tool) — same company block +
  // logo they save in the Quote modal. Our product stays a small credit line;
  // the document is THEIR branded paper.
  company?: { name?: string; address?: string; logo?: string } | null;
  machine: string;
  materialLine: string;
  machineMin: number;
  setupCount: number;
  toolChanges: number;
  complexityMult: number;
  rateHr: number;
  breakdown: MachiningBreakdown;
  // Batch pricing (qty > 1): setup paid once, unit price amortized.
  batch?: { qty: number; unit: number; total: number; setupOnce: number } | null;
  // Weldment job rollup (multi-body): parts × qty + welding + post-weld.
  job?: {
    mode: "parts" | "assembled";
    assemblies: number;
    rows: { label: string; pieces: number; min: number; cost: number; ready: boolean }[];
    weldMin: number; weldCost: number;
    pwMin: number; pwCost: number;
    subtotal: number; margin: number; total: number;
  } | null;
  setups: { label: string; ops: number; min: number }[];
  cost: {
    material: number; machining: number; setups: number;
    subtotal: number; margin: number; marginPct: number; total: number;
  };
  // ARD R4 add-on processes (grinding/plating/hardening/powder) — per piece.
  addons?: { name: string; cost: number }[];
  // Route as a flow line, e.g. "CNC Milling → Welding → Electroplating (Ni)".
  flow?: string;
}

function effortLabel(min: number): string {
  if (min < 30) return "Low";
  if (min < 90) return "Medium";
  return "High";
}

function effortEstimateHtml(p: EffortEstimateParams): string {
  const esc = (s: string) =>
    s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const date = new Date().toLocaleDateString("en-IN", {
    year: "numeric", month: "short", day: "numeric",
  });
  const catRows = p.breakdown.categories
    .map((c) => `<tr><td>${esc(c.label)}</td><td class="n">${c.count}</td><td class="n">${fmtDur(c.min)}</td><td class="n">${inr(c.cost)}</td></tr>`)
    .join("");
  const overhead = [
    p.breakdown.rapid.min > 0.001 ? { l: "Positioning &amp; rapids", ...p.breakdown.rapid } : null,
    p.breakdown.toolChanges.cost > 0 || p.breakdown.toolChanges.min > 0.001
      ? { l: `Tool changes ×${p.breakdown.toolChanges.count}`, min: p.breakdown.toolChanges.min, cost: p.breakdown.toolChanges.cost } : null,
    p.breakdown.machineSetup.min > 0.001 ? { l: "Machine setup &amp; load", ...p.breakdown.machineSetup } : null,
  ].filter(Boolean) as { l: string; min: number; cost: number }[];
  const ovRows = overhead
    .map((o) => `<tr><td>${o.l}</td><td class="n">—</td><td class="n">${fmtDur(o.min)}</td><td class="n">${inr(o.cost)}</td></tr>`)
    .join("");
  const setupRows = p.setups
    .map((s) => `<tr><td>${esc(s.label)}</td><td class="n">${s.ops}</td><td class="n">${fmtMin(s.min)}</td></tr>`)
    .join("");
  return `<!doctype html><html><head><meta charset="utf-8"><title>Effort Estimate — ${esc(p.filename)}</title>
<style>
  :root{--ink:#1c2530;--mut:#5a6470;--line:#d5dae1;--band:#f3f5f8;}
  *{box-sizing:border-box}
  body{font:13px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;color:var(--ink);margin:0;padding:28px 32px;}
  h1{font-size:20px;margin:0 0 2px}
  .sub{color:var(--mut);font-size:12px;margin:0 0 16px}
  .badge{display:inline-block;background:var(--band);border:1px solid var(--line);border-radius:5px;padding:2px 8px;font-size:11px;color:var(--mut);margin-left:6px}
  h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;color:var(--mut);margin:20px 0 6px;border-bottom:1px solid var(--line);padding-bottom:3px}
  table{width:100%;border-collapse:collapse;margin:0}
  td,th{padding:5px 8px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
  th{font-size:11px;color:var(--mut);font-weight:600;text-transform:uppercase;letter-spacing:.03em}
  td.n,th.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
  .summary td:first-child{color:var(--mut);width:42%}
  .tot td{font-weight:700;border-top:2px solid var(--ink)}
  .note{margin-top:22px;color:var(--mut);font-size:11px;border-top:1px solid var(--line);padding-top:8px}
  @media print{body{padding:0}}
</style></head><body>
${(() => {
  const co = p.company;
  if (!co || (!co.logo && !co.name)) return "";
  // Only embed the logo if it's a real image data URL — defense-in-depth so
  // the one attribute interpolation can't carry markup even if the stored
  // value were ever tampered with.
  const safeLogo = co.logo && /^data:image\//.test(co.logo) ? co.logo : "";
  const mark = safeLogo
    ? `<img src="${esc(safeLogo)}" alt="logo" style="max-height:52px;max-width:180px;object-fit:contain">`
    : `<div style="font-size:17px;font-weight:700">${esc(co.name || "")}</div>`;
  const addr = co.address
    ? `<div style="font-size:11px;color:var(--mut);white-space:pre-line;margin-top:3px">${esc(co.address)}</div>`
    : "";
  return `<div style="margin-bottom:14px">${mark}${addr}</div>`;
})()}
<h1>Effort Estimate</h1>
<p class="sub">Internal machining-effort sheet for quoting — not a customer quote. &nbsp;${esc(p.filename)} <span class="badge">${esc(p.scopeLabel)}</span> <span class="badge">${date}</span></p>

<h2>Job summary</h2>
<table class="summary">
  <tr><td>Material &amp; stock</td><td>${esc(p.materialLine)}</td></tr>
${p.flow ? `  <tr><td>Process flow</td><td>${esc(p.flow)}</td></tr>` : ""}
  <tr><td>Machine</td><td>${esc(p.machine || "—")}</td></tr>
  <tr><td>Total machine time</td><td>${fmtMin(p.machineMin)}</td></tr>
  <tr><td>Setups</td><td>${p.setupCount}</td></tr>
  <tr><td>Tool changes</td><td>${p.toolChanges}</td></tr>
  <tr><td>Complexity factor</td><td>×${p.complexityMult.toFixed(2)}</td></tr>
  <tr><td>Effort level</td><td>${effortLabel(p.machineMin)}</td></tr>
${p.batch && p.batch.qty > 1 ? `
  <tr><td>Quantity</td><td>${p.batch.qty} pcs — setup time + setup charges (${inr(p.batch.setupOnce)}) paid once per batch</td></tr>
  <tr><td>Unit price (${p.batch.qty} pcs)</td><td>${inr(p.batch.unit)} &nbsp;(${inr(p.cost.total)} at 1 pc)</td></tr>
  <tr><td>Batch total</td><td>${inr(p.batch.total)}</td></tr>` : ""}
</table>

<h2>Where the machining time goes</h2>
<table>
  <thead><tr><th>Category</th><th class="n">Features</th><th class="n">Time</th><th class="n">Cost @ ${CUR_SYM}${p.rateHr}/hr</th></tr></thead>
  <tbody>${catRows}${ovRows}
    <tr class="tot"><td>Machining</td><td class="n"></td><td class="n">${fmtMin(p.machineMin)}</td><td class="n">${inr(p.cost.machining)}</td></tr>
  </tbody>
</table>

<h2>By setup</h2>
<table>
  <thead><tr><th>Setup</th><th class="n">Ops</th><th class="n">Cut time</th></tr></thead>
  <tbody>${setupRows}</tbody>
</table>

<h2>Cost drivers</h2>
<table class="summary">
  <tr><td>Material</td><td>${inr(p.cost.material)}</td></tr>
  <tr><td>Machining</td><td>${inr(p.cost.machining)}</td></tr>
  <tr><td>Setup charges</td><td>${inr(p.cost.setups)}</td></tr>
${(p.addons ?? [])
  .map((a) => `  <tr><td>${esc(a.name)} — add-on</td><td>${inr(a.cost)}</td></tr>`)
  .join("\n")}
  <tr><td>Subtotal</td><td>${inr(p.cost.subtotal)}</td></tr>
  <tr><td>Margin (${p.cost.marginPct}%)</td><td>${inr(p.cost.margin)}</td></tr>
  <tr class="tot"><td>Indicative total</td><td>${inr(p.cost.total)}</td></tr>
</table>

${p.job ? `
<h2>${p.job.mode === "assembled"
    ? "Weldment job — post-weld machining only (arrives welded)"
    : "Weldment job — parts × quantity + welding + post-weld"}</h2>
<table>
  <thead><tr><th>Item</th><th class="n">Time</th><th class="n">Cost</th></tr></thead>
  <tbody>
  ${p.job.mode === "assembled" ? "" : p.job.rows.map((r) =>
    `<tr><td>${esc(r.label)} — ${r.pieces} pcs${r.ready ? "" : " (NOT PLANNED)"}</td><td class="n">${r.ready ? fmtMin(r.min) : "—"}</td><td class="n">${r.ready ? inr(r.cost) : "—"}</td></tr>`,
  ).join("")}
  ${p.job.mode === "assembled" ? "" :
    `<tr><td>Welding / assembly${p.job.assemblies > 1 ? ` × ${p.job.assemblies}` : ""}</td><td class="n">${fmtMin(p.job.weldMin)}</td><td class="n">${inr(p.job.weldCost)}</td></tr>`}
  <tr><td>Post-weld machining${p.job.assemblies > 1 ? ` × ${p.job.assemblies}` : ""}</td><td class="n">${fmtMin(p.job.pwMin)}</td><td class="n">${inr(p.job.pwCost)}</td></tr>
  <tr><td>Margin</td><td class="n"></td><td class="n">${inr(p.job.margin)}</td></tr>
  <tr class="tot"><td>Job total${p.job.assemblies > 1 ? ` (${p.job.assemblies} assemblies)` : ""}</td><td class="n"></td><td class="n">${inr(p.job.total)}</td></tr>
  </tbody>
</table>` : ""}
<p class="note">Times are analytical estimates (feed × path-length with a material safety factor); verify against shop actuals. Prepared by CNC Plan &amp; Process Pro.</p>
</body></html>`;
}

// Open an HTML document in a new window and trigger the print dialog
// (browser "Save as PDF" gives the downloadable file). Popup-blocked → no-op.
function openPrintDoc(html: string): void {
  const w = window.open("", "_blank", "width=900,height=1000");
  if (!w) {
    alert("Please allow pop-ups to download the Effort Estimate.");
    return;
  }
  w.document.open();
  w.document.write(html);
  w.document.close();
  w.focus();
  setTimeout(() => w.print(), 350);
}

// Download a text file (G-code, CSV, …) from the browser.
function downloadText(filename: string, text: string): void {
  const blob = new Blob([text], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

// ---- DRAFT G-code (good-to-have) ---------------------------------------------
// A STARTING-POINT program, not machine-ready: real drilling canned cycles and
// positions from the plan, with milling toolpaths deliberately left to CAM. The
// header makes the "verify before running" contract explicit — feeding
// unverified milling code to a machine is a crash/liability risk.
function draftGcode(setups: StrategySetup[], machineName: string, partName: string): string {
  const L: string[] = [];
  const n = (v: number | null | undefined) =>
    Number.isFinite(v as number) ? (v as number).toFixed(3) : "0.000";
  L.push("; ============================================================");
  L.push("; DRAFT PROGRAM - DO NOT RUN DIRECTLY ON A MACHINE.");
  L.push("; Planning / starting-point code only. Work offset (G54), tool");
  L.push("; numbers/offsets, Z zero, speeds and feeds MUST be set and");
  L.push("; verified in a CAM simulator by a qualified programmer first.");
  L.push("; Milling toolpaths are NOT generated - only hole positions and");
  L.push("; drilling cycles. Generate milling paths in your CAM system.");
  L.push("; ============================================================");
  L.push(`; Part    : ${partName}`);
  L.push(`; Machine : ${machineName || "CNC Machine"}`);
  L.push("; Program : CNC Plan & Process Pro (draft)");
  L.push("O0001");
  L.push("G21 G17 G90 G94 G54 G49 G80 G40 (metric, absolute, cancel cycles/comp)");
  L.push("G0 Z50.0");
  let curTool = "";
  let toolNo = 0;
  for (const su of setups) {
    L.push(`(======== SETUP: ${su.setup_label} ========)`);
    for (const op of su.ops) {
      const tool = op.tool_display || op.tool || "Tool";
      if (tool !== curTool) {
        curTool = tool;
        toolNo += 1;
        L.push("M5");
        L.push(`T${toolNo} M6 (${tool})`);
        L.push(`S${Math.round(op.spindle_rpm || 0)} M3`);
      }
      const g = op.geo;
      const opl = (op.operation || "").toLowerCase();
      const feed = Math.round(op.feed_mm_min || 200);
      if (g && g.x != null && g.y != null && /drill|spot|ream|bore|tap/.test(opl)) {
        const depth = Math.max(g.depth || 5, 1);
        const spot = /spot/.test(opl);
        const cyc = spot ? "G81" : "G83";
        const peck = spot ? "" : ` Q${n(Math.max(depth / 4, 1))}`;
        L.push(`G0 X${n(g.x)} Y${n(g.y)}`);
        L.push(`${cyc} Z${n(-depth)} R2.0${peck} F${feed} (${op.feature || op.operation})`);
        L.push("G80");
      } else {
        if (g && g.x != null && g.y != null) L.push(`G0 X${n(g.x)} Y${n(g.y)}`);
        L.push(`(MILL: ${op.operation} - ${op.feature || ""} | make toolpath in CAM, feed ~${feed})`);
      }
    }
  }
  L.push("G0 Z50.0");
  L.push("M5");
  L.push("M30");
  L.push("%");
  return L.join("\n");
}

function loadInspectorWidth(): number {
  const v = Number(lsGet("cnc.inspectorWidth"));
  return Number.isFinite(v) && v >= INSPECTOR_MIN && v <= INSPECTOR_MAX ? v : INSPECTOR_DEFAULT;
}

// Validated-geometry rows for the op panel (GAP-3 A2/C4): hole Ø / cbore /
// depth / L·D / through-blind / tip cone, slot size / open-closed / opening
// face. Rendered only when the backend planned from exact classifier
// geometry (op.geo.geometry present).
function GeometrySection({ g }: { g: FeatureGeometry }) {
  // ARD R5: a "compound" hole is a counter (counterbore or countersink) sitting
  // over a threaded base hole — e.g. a counterbore clearing a screw head above
  // a tapped M6. For those cards, surface the thread spec as a top-level,
  // visually prominent row above the counter geometry so it isn't buried below
  // the base-hole rows it actually belongs to.
  const hasCounter =
    g.kind === "hole" && ((g.cbore_diameter_mm != null && g.cbore_diameter_mm > 0) || g.countersink === true);
  const isCompound = g.kind === "hole" && hasCounter && !!g.thread_likely;
  return (
    <>
      <div className="op-panel-sect">Geometry</div>
      {g.kind === "hole" ? (
        <>
          {isCompound && (
            <div
              className="op-panel-row"
              title={`Base hole Ø${fmtNum(g.diameter_mm)} mm — likely ${g.thread_likely} tap`}
            >
              <span className="k">Thread</span>
              <span className="v" style={{ fontWeight: 600 }}>{g.thread_likely}</span>
            </div>
          )}
          {g.cbore_diameter_mm != null && g.cbore_diameter_mm > 0 && (
            <div className="op-panel-row">
              <span className="k">Counterbore</span>
              <span className="v">Ø{fmtNum(g.cbore_diameter_mm)} mm</span>
            </div>
          )}
          {g.countersink && (
            <div className="op-panel-row">
              <span className="k">Countersink</span>
              <span className="v">{g.tip_angle_deg != null ? `${fmtNum(g.tip_angle_deg)}°` : "—"}</span>
            </div>
          )}
          <div className="op-panel-row">
            <span className="k">Diameter</span>
            <span className="v">Ø{fmtNum(g.diameter_mm)} mm</span>
          </div>
          <div className="op-panel-row">
            <span className="k">Depth</span>
            <span className="v">{fmtNum(g.depth_mm)} mm</span>
          </div>
          {g.ld_ratio != null && (
            <div className="op-panel-row">
              <span className="k">L/D ratio</span>
              <span className="v">{fmtNum(g.ld_ratio)}</span>
            </div>
          )}
          <div className="op-panel-row">
            <span className="k">Through/Blind</span>
            <span className="v">
              {g.through === true ? "Through" : g.through === false ? "Blind" : "—"}
            </span>
          </div>
          {g.depth_below_top_mm != null && g.depth_below_top_mm > 0 && (
            <div className="op-panel-row">
              <span className="k">Depth below top</span>
              <span className="v">{fmtNum(g.depth_below_top_mm)} mm</span>
            </div>
          )}
          {!g.countersink && g.tip_angle_deg != null && (
            <div className="op-panel-row">
              <span className="k">Tip angle</span>
              <span className="v">{fmtNum(g.tip_angle_deg)}°</span>
            </div>
          )}
          {g.cone_deviation && (
            <div
              className="op-panel-row"
              title="Shallow blind hole — a full 118° drill point would go deeper than the feature; tip auto-upgraded to a near-flat 140°."
            >
              <span className="k">Hole Cone Deviation</span>
              <span className="v">
                {g.cone_deviation.original_deg}° → {g.cone_deviation.modified_deg}°
              </span>
            </div>
          )}
          {!isCompound && g.thread_likely && (
            <div className="op-panel-row" title="Inferred from the pilot diameter (tap-drill table) — not thread data from the CAD file">
              <span className="k">Thread</span>
              <span className="v">likely {g.thread_likely}</span>
            </div>
          )}
          {!isCompound && g.countersink && (
            <div className="op-panel-chips">
              <span className="chip">Countersink</span>
            </div>
          )}
        </>
      ) : (
        <>
          <div className="op-panel-row">
            <span className="k">Size</span>
            <span className="v">
              {fmtNum(g.length_mm)} × {fmtNum(g.width_mm)} ×{" "}
              {g.depth_mm != null ? fmtNum(g.depth_mm) : "—"} mm
            </span>
          </div>
          <div className="op-panel-row">
            <span className="k">Open/Closed</span>
            <span className="v">{g.open ? "Open" : "Closed"}</span>
          </div>
          {g.open && g.opens_toward && (
            <div className="op-panel-row">
              <span className="k">Opens toward</span>
              <span className="v">{g.opens_toward}</span>
            </div>
          )}
          {g.max_tool_dia_mm != null && g.max_tool_dia_mm > 0 && (
            <div
              className="op-panel-row"
              title="Largest endmill that can enter the slot (= slot width)"
            >
              <span className="k">Max tool Ø</span>
              <span className="v">≤ {fmtNum(g.max_tool_dia_mm)} mm</span>
            </div>
          )}
        </>
      )}
    </>
  );
}

// Geometry section for mill/facing ops that carry no hole/slot geometry
// object (gap-v5 A3). A Face Mill / Rough-End-Mill on a planar face still has
// L×W×depth on op.geo, so surface Feature depth + L/D the same way holes do —
// the Face Mill card used to show only cutting parameters.
function MillGeometrySection({ g }: { g: OpGeo }) {
  const L = g.length ?? 0;
  const W = g.width ?? 0;
  const D = g.depth ?? 0;
  const span = Math.max(L, W);
  const ld = D > 0 && span > 0 ? D / span : null; // shallow face -> low L/D
  if (L <= 0 && W <= 0 && D <= 0) return null;
  return (
    <>
      <div className="op-panel-sect">Geometry</div>
      <div className="op-panel-row">
        <span className="k">Size</span>
        <span className="v">
          {fmtNum(L)} × {fmtNum(W)} × {fmtNum(D)} mm
        </span>
      </div>
      {D > 0 && (
        <div className="op-panel-row">
          <span className="k">Feature depth</span>
          <span className="v">{fmtNum(D)} mm</span>
        </div>
      )}
      {ld != null && (
        <div
          className="op-panel-row"
          title="Feature depth ÷ largest planar span — low for shallow faces"
        >
          <span className="k">L/D ratio</span>
          <span className="v">{(ld < 0.1 ? ld.toFixed(3) : ld.toFixed(2))}:1</span>
        </div>
      )}
    </>
  );
}

// Floating op-detail panel over the canvas (Strategy op click). Read-mostly:
// spindle/feed edits recompute the cut time LOCALLY — the planned time's
// built-in safety factor (origTime·origFeed/path) is preserved, so
// newTime = origTime × origFeed / newFeed. Never mutates the plan.
// Remount per op (key=selOp) so the inputs reset to the op's planned values.
function OpPanel({ op, onClose }: { op: StrategyOp; onClose: () => void }) {
  const [spindleStr, setSpindleStr] = useState(String(Math.round(op.spindle_rpm ?? 0)));
  const [feedStr, setFeedStr] = useState(String(Math.round(op.feed_mm_min ?? 0)));
  const origFeed = op.feed_mm_min ?? 0;
  const newFeed = numOr0(feedStr);
  const edited = newFeed > 0 && origFeed > 0 && Math.abs(newFeed - origFeed) > 1e-9;
  const cutMin = edited ? op.cut_min * (origFeed / newFeed) : op.cut_min;
  const geom = op.geo?.geometry ?? null;
  return (
    <div className="op-panel">
      <div className="op-panel-head">
        <div style={{ minWidth: 0 }}>
          <div className="op-panel-title" title={op.operation}>{op.operation}</div>
          <div className="op-panel-sub" title={op.feature}>{op.feature || "—"}</div>
        </div>
        <button className="op-panel-x" title="Close (clears the highlight)" onClick={onClose}>
          ✕
        </button>
      </div>
      <div className="op-panel-row">
        <span className="k">Tool</span>
        <span className="v" title={op.tool}>{op.tool_display || op.tool}</span>
      </div>
      {geom ? (
        <GeometrySection g={geom} />
      ) : (
        op.geo && <MillGeometrySection g={op.geo} />
      )}
      <div className="op-panel-sect">Cutting parameters</div>
      <div className="op-panel-row">
        <span className="k">Spindle (rpm)</span>
        <input
          className="num-input"
          type="number"
          min={0}
          value={spindleStr}
          onChange={(e) => setSpindleStr(e.target.value)}
        />
      </div>
      <div className="op-panel-row">
        <span className="k">Feed (mm/min)</span>
        <input
          className="num-input"
          type="number"
          min={0}
          value={feedStr}
          onChange={(e) => setFeedStr(e.target.value)}
        />
      </div>
      <div className="op-panel-row">
        <span className="k">Path (mm)</span>
        <span className="v">{(op.path_mm ?? 0).toFixed(0)}</span>
      </div>
      <div className="op-panel-row">
        <span className="k">Cut time (min)</span>
        <span className="v" style={edited ? { color: "var(--accent)" } : undefined}>
          {cutMin.toFixed(2)}
        </span>
      </div>
      <div className="op-panel-note">Estimates only — does not modify the plan</div>
    </div>
  );
}

// Inline "+ Add process" form on the Route tab. Name and a positive time
// are required; rate defaults to a generic bench rate.
// First-run "wow": a staged loader so the wait reads as the tool WORKING
// (reading geometry → detecting features → planning → pricing) instead of a
// bare spinner. Stages advance on a timer — cosmetic, not tied to real
// progress — and the last stage holds until analysis actually returns.
function AnalyzingStages() {
  const STAGES = [
    "Reading the 3D geometry",
    "Detecting holes, slots & pockets",
    "Planning setups & tools",
    "Pricing the job",
  ];
  const [i, setI] = useState(0);
  useEffect(() => {
    // Hold on the final stage; earlier ones tick by so it feels alive.
    const t = setInterval(() => setI((n) => Math.min(n + 1, STAGES.length - 1)), 1400);
    return () => clearInterval(t);
  }, [STAGES.length]);
  return (
    <div className="analyzing">
      <div className="ring" />
      <div className="az-stages">
        {STAGES.map((s, n) => (
          <div
            key={s}
            className={`az-stage ${n < i ? "done" : n === i ? "active" : ""}`}
          >
            <span className="dot">{n < i ? "✓" : ""}</span>
            {s}
          </div>
        ))}
      </div>
    </div>
  );
}

function AddProcessForm({
  onAdd,
  onCancel,
}: {
  onAdd: (s: Omit<CustomRouteStep, "id">) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [timeStr, setTimeStr] = useState("30");
  const [rateStr, setRateStr] = useState("500");
  const [station, setStation] = useState("");
  const valid = name.trim().length > 0 && numOr0(timeStr) > 0;
  return (
    <div className="route-form">
      <div className="mat-form-row">
        <span>Process name</span>
        <input
          className="text-input"
          placeholder="e.g. Deburr & clean"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="mat-form-row">
        <span>Time (min)</span>
        <input
          className="num-input"
          type="number"
          min={0}
          value={timeStr}
          onChange={(e) => setTimeStr(e.target.value)}
        />
      </div>
      <div className="mat-form-row">
        <span>Rate ({CUR_SYM}/hr)</span>
        <input
          className="num-input"
          type="number"
          min={0}
          value={rateStr}
          onChange={(e) => setRateStr(e.target.value)}
        />
      </div>
      <div className="mat-form-row">
        <span>Machine/station</span>
        <input
          className="text-input"
          placeholder="optional"
          value={station}
          onChange={(e) => setStation(e.target.value)}
        />
      </div>
      <div className="mat-form-actions">
        <button className="btn" style={{ padding: "4px 12px", fontSize: 12 }} onClick={onCancel}>
          Cancel
        </button>
        <button
          className="btn primary"
          style={{ padding: "4px 12px", fontSize: 12 }}
          disabled={!valid}
          onClick={() =>
            onAdd({
              name: name.trim(),
              timeMin: numOr0(timeStr),
              rateHr: numOr0(rateStr),
              station: station.trim(),
            })
          }
        >
          Add
        </button>
      </div>
    </div>
  );
}

export default function App() {
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null);
  const [strategy, setStrategy] = useState<StrategyResult | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<"projects" | "part" | "shop">("projects");
  // SHOP-3: machines the shop actually uses (names). Empty = show all.
  const [myMachines, setMyMachines] = useState<Set<string>>(() => {
    try {
      const raw = lsGet("cnc.myMachines");
      return new Set(raw ? (JSON.parse(raw) as string[]) : []);
    } catch {
      return new Set();
    }
  });
  const toggleMyMachine = (name: string) =>
    setMyMachines((prev) => {
      const n = new Set(prev);
      if (n.has(name)) n.delete(name);
      else n.add(name);
      lsSet("cnc.myMachines", JSON.stringify([...n]));
      return n;
    });
  // Machine dropdowns show only the curated machines (Shop Library) — the
  // currently selected machine always stays visible so nothing breaks.
  const filterMy = <T extends { name?: string }>(list: T[], current: string): T[] =>
    myMachines.size === 0
      ? list
      : list.filter(
          (m) => m.name === current || (m.name != null && myMachines.has(m.name)),
        );
  const [selOp, setSelOp] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<OpGeo | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  // Strategy accordion: which setup cards are dropped down. Defaults to the
  // first setup open (si===0); clicking a setup header toggles it so the panel
  // isn't crowded with every setup's ops at once.
  const [openSetups, setOpenSetups] = useState<Record<string, boolean>>({});
  // WS-B: features the user deselected (won't be machined). Keyed by
  // candidate_id (part-agnostic); loaded/persisted per part below.
  const [excluded, setExcluded] = useState<Set<string>>(new Set());
  const [rateHr, setRateHr] = useState(800);
  const [setupCharge, setSetupCharge] = useState(500);
  const [matPriceKg, setMatPriceKg] = useState(650);
  const [marginPct, setMarginPct] = useState(20);
  // Batch quantity: setup time + setup charges are paid ONCE per batch, so the
  // unit price falls as qty rises (₹500 setup over 10 pcs = ₹50/pc).
  const [qty, setQty] = useState(1);
  // Display currency (persisted). Symbol-only — see CURRENCIES.
  const [currencyCode, setCurrencyCode] = useState<string>(
    () => lsGet("cnc.currencyCode") || "INR",
  );
  const sym = CURRENCIES.find((c) => c.code === currencyCode)?.symbol ?? "₹";
  CUR_SYM = sym; // module-level formatter follows the selection each render
  // ARD R2/R3: per-machine costing profile (Time-based default | Rate-card).
  // Profile follows the selected machine; created from the default rate card
  // on first use. `costingNonce` re-reads after library edits.
  const [costingNonce, setCostingNonce] = useState(0);
  const [machineSelForCosting, setMachineSelForCosting] = useState("");
  // A shop can keep several rate cards (one per machine) — this pins the
  // ACTIVE card for quoting; empty = follow the selected machine's own card.
  const [rateCardId, setRateCardId] = useState<string>(
    () => lsGet("cnc.costing.activeCard") || "",
  );
  const costingProfile = useMemo(() => {
    if (rateCardId) {
      const picked = loadProfiles().find((p) => p.id === rateCardId);
      if (picked) return picked;
    }
    return profileForMachine(machineSelForCosting || "Default");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [machineSelForCosting, costingNonce, rateCardId]);
  // All saved rate cards, for the picker (refreshes on any profile edit).
  const allRateCards = useMemo(
    () => loadProfiles(),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [costingNonce, machineSelForCosting],
  );
  const rateCardActive = costingProfile.model === "ratecard";
  const [costPanelOpen, setCostPanelOpen] = useState(false);
  // "+ New" rate card inline form (null = closed). Creating a card copies
  // the CURRENT card's rates + hole library so tuned prices carry over;
  // fresh defaults come from simply using a machine with no card yet.
  const [newCardName, setNewCardName] = useState<string | null>(null);
  const createRateCard = () => {
    const name = (newCardName ?? "").trim();
    if (!name) return;
    if (allRateCards.some((p) => p.name.toLowerCase() === name.toLowerCase())) {
      window.alert("A rate card with this name already exists.");
      return;
    }
    const fresh = {
      ...costingProfile,
      id: `profile-${name}-${Date.now()}`,
      name,
      model: "ratecard" as const,
      holeLibrary: costingProfile.holeLibrary.map((r) => ({ ...r })),
      auditLog: [],
    };
    updateProfile(audit(fresh, "create_card", "", `copied from ${costingProfile.name}`));
    setRateCardId(fresh.id);
    lsSet("cnc.costing.activeCard", fresh.id);
    setNewCardName(null);
    setCostingNonce((n) => n + 1);
  };
  // ARD R4: add-on processes selected for this part (grinding/plating/…),
  // each seeded from the rate-card library but editable inline. Empty = none.
  const [addonSels, setAddonSels] = useState<AddonSelection[]>([]);
  const addonLib = useMemo(
    () => addonLibraryFor(costingProfile),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [costingProfile, costingNonce],
  );
  // Add a library process to this part's selection (seed from its saved rate).
  const addAddonFromLib = (procId: string) => {
    const p = addonLib.find((x) => x.id === procId);
    if (!p) return;
    setAddonSels((s) => [
      ...s,
      {
        uid: `sel-${Date.now()}`, procId: p.id, name: p.name,
        basis: p.basis, rate: p.rate, area: p.area ?? "surface",
      },
    ]);
  };
  const addCustomAddon = () =>
    setAddonSels((s) => [
      ...s,
      {
        uid: `sel-${Date.now()}`, procId: null, name: "Custom process",
        basis: "flat", rate: 0, area: "surface",
      },
    ]);
  const patchAddon = (uid: string, patch: Partial<AddonSelection>) =>
    setAddonSels((s) => s.map((a) => (a.uid === uid ? { ...a, ...patch } : a)));
  const removeAddon = (uid: string) =>
    setAddonSels((s) => s.filter((a) => a.uid !== uid));
  // Persist an edited add-on row back into the rate-card library (two-way):
  // updates the matching process, or adds a new confirmed one for a custom row.
  const saveAddonToLib = (a: AddonSelection) => {
    const lib = addonLibraryFor(costingProfile);
    const today = new Date().toISOString().slice(0, 10);
    let next;
    const existing = a.procId ? lib.find((x) => x.id === a.procId) : null;
    if (existing) {
      next = lib.map((x) =>
        x.id === a.procId
          ? { ...x, basis: a.basis, rate: a.rate, area: a.area, confirmed: true, source: "shop-confirmed", effective_from: today }
          : x,
      );
    } else {
      const id = `addon-${Date.now()}`;
      next = [
        ...lib,
        { id, name: a.name.trim() || "Process", basis: a.basis, rate: a.rate, area: a.area, confirmed: true, source: "shop-confirmed", effective_from: today },
      ];
      patchAddon(a.uid, { procId: id });
    }
    updateProfile(audit({ ...costingProfile, addonLibrary: next }, "addon_save", a.name, String(a.rate)));
    setCostingNonce((n) => n + 1);
  };
  // Bodies excluded from machining (purchased parts / bolts), per part file.
  const [excludedBodies, setExcludedBodies] = useState<Set<string>>(new Set());
  const toggleBodyExcluded = (groupId: string) =>
    setExcludedBodies((prev) => {
      const n = new Set(prev);
      if (n.has(groupId)) n.delete(groupId);
      else n.add(groupId);
      const fn = analysis?.filename;
      if (fn) lsSet(`cnc.excludedBodies.${fn}`, JSON.stringify([...n]));
      return n;
    });
  const fileRef = useRef<HTMLInputElement>(null);
  // Parts the user uploaded this session — a project can hold as many as they
  // like. Each shows as a card on Projects; clicking one analyses it. (Kept as
  // in-memory File handles so re-analysis on click needs no re-upload.)
  const [uploadedParts, setUploadedParts] = useState<File[]>([]);

  // Uploaded part is retained so material changes can re-run analysis
  const [partFile, setPartFile] = useState<File | null>(null);
  const [materials, setMaterials] = useState<Material[]>([]);
  const [material, setMaterial] = useState<string>(() => lsGet("cnc.material") ?? "");
  // User-defined materials — travel to the backend as material_json and
  // their density drives the estimate's stock-mass line.
  const [customMaterials, setCustomMaterials] = useState<Material[]>(loadCustomMaterials);

  // ---- Operator-controlled estimation settings (all persisted) ----
  const [estBasis, setEstBasis] = useState<PlanBasis>(loadBasis);
  // Ref mirrors estBasis synchronously so in-flight runAnalysis strategy
  // fetches use the latest pick, not a stale closure value.
  const estBasisRef = useRef<PlanBasis>(estBasis);
  const [basisLoading, setBasisLoading] = useState(false);
  // Bumps whenever a newer whole-assembly strategy fetch starts —
  // invalidates slower in-flight ones (basis switch vs full re-analysis).
  const stratReqRef = useRef(0);
  const [estPreset, setEstPreset] = useState<QuotePreset>(loadPreset);
  const [estComplexity, setEstComplexity] = useState<number>(loadComplexity);
  const [estTolerance, setEstTolerance] = useState<ToleranceClass>(loadTolerance);

  // ---- Process Route state (Route tab) ----
  // Welding/assembly labour rate — persisted (a shop's rate is stable).
  const [weldRate, setWeldRate] = useState<number>(loadWeldRate);
  // Turning placeholder: manual time/rate so turned parts are quotable
  // before the lathe module lands. Session-only by design.
  const [turnMin, setTurnMin] = useState(0);
  const [turnRate, setTurnRate] = useState(600);
  // Operator-added process blocks (persisted under cnc.customRouteSteps).
  const [customRouteSteps, setCustomRouteSteps] = useState<CustomRouteStep[]>(loadCustomRouteSteps);
  const [addingProcess, setAddingProcess] = useState(false);

  function changeWeldRate(v: number) {
    setWeldRate(v);
    lsSet("cnc.routeWeldRate", String(v));
  }

  function addRouteStep(s: Omit<CustomRouteStep, "id">) {
    const step: CustomRouteStep = {
      ...s,
      id: `crs-${Date.now()}-${Math.random().toString(36).slice(2, 7)}`,
    };
    setCustomRouteSteps((cur) => {
      const next = [...cur, step];
      lsSet("cnc.customRouteSteps", JSON.stringify(next));
      return next;
    });
    setAddingProcess(false);
  }

  function removeRouteStep(id: string) {
    setCustomRouteSteps((cur) => {
      const next = cur.filter((c) => c.id !== id);
      lsSet("cnc.customRouteSteps", JSON.stringify(next));
      return next;
    });
  }

  // Machine selection: library machines from /api/machines, user-defined
  // machines from localStorage. Custom machines are sent as machine_json.
  const [machines, setMachines] = useState<MachineInfo[]>([]);
  const [customMachines, setCustomMachines] = useState<CustomMachine[]>(loadCustomMachines);
  const [machineSel, setMachineSel] = useState<string>(() => lsGet("cnc.machine") ?? "");
  // Costing profile follows the selected machine (declared above machineSel to
  // keep the estimate cores below it — sync here, not in the memo, to avoid a
  // temporal-dead-zone crash).
  useEffect(() => {
    setMachineSelForCosting(machineSel);
  }, [machineSel]);

  // Multi-machine routing (our moat): the operator can assign a distinct
  // machine to each process stage in the Route tab. Milling stays tied to
  // machineSel (it drove the plan); turning + custom stages get their own.
  const [routeMachines, setRouteMachines] = useState<Record<string, string>>(() => {
    try {
      return JSON.parse(lsGet("cnc.routeMachines") || "{}") as Record<string, string>;
    } catch {
      return {};
    }
  });
  function setRouteMachine(stage: string, name: string) {
    setRouteMachines((cur) => {
      const next = { ...cur, [stage]: name };
      lsSet("cnc.routeMachines", JSON.stringify(next));
      return next;
    });
  }

  // Stock config (Overview → Material section). Manual sizes replace the
  // stock volume behind the Estimate material line. Per-part session state.
  const [stockMode, setStockMode] = useState<"auto" | "manual">("auto");
  const [manualStock, setManualStock] =
    useState<{ length: number; width: number; height: number } | null>(null);

  // Part opacity in the 3D viewer (0.2–1, persisted)
  const [viewerOpacity, setViewerOpacity] = useState<number>(loadViewerOpacity);
  const [layers, setLayers] = useState<ViewerLayers>(loadLayers);
  function toggleLayer(k: keyof ViewerLayers) {
    setLayers((cur) => {
      const next = { ...cur, [k]: !cur[k] };
      lsSet("cnc.viewerLayers", JSON.stringify(next));
      return next;
    });
  }

  // Per-body scope for multibody weldments. selectedGroupId null = full assembly.
  // Session-only by design — scope resets on every new analysis.
  const [wmResult, setWmResult] = useState<WeldmentResult | null>(null);
  const [wmLoading, setWmLoading] = useState(false);
  const [wmError, setWmError] = useState<string | null>(null);
  const [selectedGroupId, setSelectedGroupId] = useState<string | null>(null);
  // File the weldment cache/fetch belongs to — guards stale async results
  // and skips refetching when the same file is re-analysed (material change).
  const wmFileRef = useRef<File | null>(null);

  const selectedGroup = useMemo(
    () =>
      wmResult && selectedGroupId
        ? wmResult.groups.find((g) => g.group_id === selectedGroupId) ?? null
        : null,
    [wmResult, selectedGroupId],
  );

  // ---- Body-scoped strategy (lazy, cached per body_index+material) ----
  const [scopedStrategy, setScopedStrategy] = useState<StrategyResult | null>(null);
  const [scopedLoading, setScopedLoading] = useState(false);
  const [scopedError, setScopedError] = useState<string | null>(null);
  const [scopedRetryNonce, setScopedRetryNonce] = useState(0);
  const scopedCacheRef = useRef<Map<string, StrategyResult>>(new Map());
  const scopedReqRef = useRef(0); // bumps on every effect run — invalidates stale fetches

  // Representative body of the group — the splitter's first body, whose
  // mesh is also what the isolated 3D view shows.
  const scopedBodyIndex = selectedGroup ? selectedGroup.body_indices[0] : null;

  // Resolve a machine pick into request opts: custom machines travel as
  // machine_json, library machines as ?machine=<name>. Custom wins on a
  // name collision (the user explicitly created it).
  function machineOptsFor(name: string): MachineOpts | undefined {
    if (!name) return undefined;
    const custom = customMachines.find((c) => c.name === name);
    return custom ? { machineJson: JSON.stringify(custom) } : { machineName: name };
  }

  // Same resolution for materials: custom picks travel as material_json,
  // library picks as ?material=<name>. Custom wins on a name collision.
  function materialOptsFor(name: string): MaterialOpts | undefined {
    if (!name) return undefined;
    const custom = customMaterials.find((c) => c.name === name);
    return custom ? { materialJson: JSON.stringify(custom) } : { materialName: name };
  }

  useEffect(() => {
    const token = ++scopedReqRef.current;
    // The Estimate tab consumes the scoped plan too (per-body ledger),
    // so a scope set from Overview must fetch on either tab.
    if ((tab !== "strategy" && tab !== "estimate") || scopedBodyIndex == null || !partFile) return;
    const machineKey = machineSel
      ? customMachines.some((c) => c.name === machineSel)
        ? `custom:${machineSel}`
        : machineSel
      : "";
    const materialKey = material
      ? customMaterials.some((c) => c.name === material)
        ? `custom:${material}`
        : material
      : "";
    const key = `${scopedBodyIndex}:${materialKey}:${machineKey}:${estBasis}`;
    const cached = scopedCacheRef.current.get(key);
    if (cached) {
      setScopedStrategy(cached);
      setScopedLoading(false);
      setScopedError(null);
      return;
    }
    setScopedLoading(true);
    setScopedError(null);
    api
      .strategy(partFile, {
        material: materialOptsFor(material),
        bodyIndex: scopedBodyIndex,
        machine: machineOptsFor(machineSel),
        basis: estBasis,
      })
      .then((r) => {
        if (scopedReqRef.current !== token) return;
        scopedCacheRef.current.set(key, r);
        setScopedStrategy(r);
        setScopedLoading(false);
        // Reviewing a body part-by-part also fills the assembly rollup — the
        // job ledger's "pending" count drops as each part gets planned.
        const grp = wmResult?.groups.find((g) => g.body_indices.includes(scopedBodyIndex!));
        if (grp) setRollupPlans((p) => (p[grp.group_id] ? p : { ...p, [grp.group_id]: r }));
      })
      .catch((err) => {
        if (scopedReqRef.current !== token) return;
        setScopedError(err instanceof Error ? err.message : "Scoped strategy failed");
        setScopedLoading(false);
      });
    // machineOptsFor/materialOptsFor are stable per (machineSel,
    // customMachines, material, customMaterials), all in deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab, scopedBodyIndex, material, partFile, scopedRetryNonce, machineSel, customMachines, customMaterials, estBasis]);

  // Strategy shown on the Strategy tab: scoped plan when a body scope is
  // active (guarded against stale responses), whole-assembly otherwise.
  const stratForView = selectedGroup
    ? scopedStrategy && scopedStrategy.scoped_body_index === scopedBodyIndex
      ? scopedStrategy
      : null
    : strategy;

  // Selected op resolved from the on-screen plan (selOp id = "<setup>-<num>").
  // Derived, not stored — it can never outlive a plan/scope/basis change.
  const selOpData = useMemo((): StrategyOp | null => {
    if (!selOp || !stratForView) return null;
    for (const su of stratForView.setups) {
      for (const op of su.ops) {
        if (`${su.setup_label}-${op.op_num}` === selOp) return op;
      }
    }
    return null;
  }, [selOp, stratForView]);

  // Exact face meshes for the selected op. Classifier features (scoped
  // holes/slots/turning) carry their own tessellated faces in
  // geo.face_mesh_data; billet candidates are looked up via candidate_id
  // in the analyze response. Both are raw-CAD frame, same as body meshes.
  const selFaceMeshes = useMemo((): Mesh[] | null => {
    const direct = selOpData?.geo?.face_mesh_data;
    if (direct) {
      const meshes = normalizeFaceMeshes(direct);
      if (meshes.length) return meshes;
    }
    const cid = selOpData?.geo?.candidate_id;
    if (!cid || !analysis) return null;
    const cand = analysis.candidates.find((c) => c.candidate_id === cid);
    const meshes = cand ? normalizeFaceMeshes(cand.face_mesh_data) : [];
    return meshes.length ? meshes : null;
  }, [selOpData, analysis]);

  // Exclusion helpers — declared ABOVE everything that calls them during
  // render (the assembly rollup memo below runs at its position in the body;
  // a later `const` would be a temporal-dead-zone crash, invisible to tsc).
  const opFeatureKey = (op: StrategyOp): string =>
    op.geo?.candidate_id || baseFeatureName(op.feature || "") || op.feature || "";
  const isOpExcluded = (op: StrategyOp): boolean => excluded.has(opFeatureKey(op));
  // Exclusion-aware totals. Cutting time drops EXACTLY (sum of surviving
  // cut_min); overheads SCALE instead of sticking: a setup left with zero ops
  // stops charging setup time, tool changes are recounted from the surviving
  // tool sequence, rapid scales with the surviving cutting fraction. With
  // nothing excluded the original totals pass through untouched, so the
  // no-exclusion baseline (and every gate) is byte-identical.
  const exclusionAdjusted = (
    sus: StrategySetup[],
    totals: StrategyResult["totals"],
  ) => {
    const machineMin = totals.total_machine_time_min ?? 0;
    const rapidMin = totals.rapid_time_min ?? 0;
    const tcMin = totals.tool_change_time_min ?? 0;
    const setupMin = totals.setup_time_min ?? 0;
    const tcCount = totals.num_tool_changes ?? 0;
    let cutAll = 0, cutInc = 0, tcNew = 0, setupsInc = 0;
    let anyExcluded = false;
    for (const su of sus) {
      let prevTool: string | null = null;
      let any = false;
      for (const op of su.ops) {
        const c = op.cut_min || 0;
        cutAll += c;
        if (isOpExcluded(op)) { anyExcluded = true; continue; }
        cutInc += c;
        any = true;
        const t = op.tool_display || op.tool || "";
        if (prevTool !== null && t !== prevTool) tcNew++;
        prevTool = t;
      }
      if (any) setupsInc++;
    }
    if (!anyExcluded) {
      return { machineMin, rapidMin, tcMin, setupMin, tcCount, includedSetups: sus.length };
    }
    const frac = cutAll > 0 ? cutInc / cutAll : 0;
    const cutAuth = Math.max(machineMin - rapidMin - tcMin - setupMin, 0);
    const perTc = tcCount > 0 ? tcMin / tcCount : 0;
    const tcCount2 = Math.min(tcCount, tcNew);
    const tcMin2 = Math.min(tcMin, tcNew * perTc);
    const rapid2 = rapidMin * frac;
    const setup2 = sus.length > 0 ? setupMin * (setupsInc / sus.length) : setupMin;
    return {
      machineMin: cutAuth * frac + rapid2 + tcMin2 + setup2,
      rapidMin: rapid2,
      tcMin: tcMin2,
      setupMin: setup2,
      tcCount: tcCount2,
      includedSetups: setupsInc,
    };
  };

  // ---- ASSY-ROLLUP: the weldment job ledger --------------------------------
  // A welded assembly is NOT machined as one billet: each body is machined
  // individually (exact per-body plans), then welded, then optionally machined
  // again as an assembly (post-weld facing etc.). The rollup sums exact
  // per-group plans × quantity + welding + post-weld ops — this is the number
  // to quote for a weldment; the billet-style assembly plan is reference only.
  const [rollupPlans, setRollupPlans] = useState<Record<string, StrategyResult>>({});
  const [rollupBusy, setRollupBusy] = useState<string | null>(null);
  const [rollupErr, setRollupErr] = useState<string | null>(null);
  // Weldment intent (asked on Overview): machine the ALREADY-ASSEMBLED weldment
  // (surface ops only) vs build it part-by-part (machine → weld → post-weld).
  // Persisted per part.
  const [assemblyMode, setAssemblyModeState] = useState<"parts" | "assembled" | null>(null);
  const setAssemblyMode = (m: "parts" | "assembled") => {
    setAssemblyModeState(m);
    const fn = analysis?.filename;
    if (fn) lsSet(`cnc.assyMode.${fn}`, m);
  };
  // Welding is often a NUMBER the fabricator knows — override the analyzer's
  // minutes per assembly when set.
  const [weldMinOverride, setWeldMinOverride] = useState<number | null>(null);
  // Some shops SUPPLY the cut parts and the customer welds them — so welding
  // shows by default but can be removed from the job. Persisted per part.
  const [weldingOff, setWeldingOff] = useState(false);
  // Post-weld ops (machined on the WELDED assembly). Suggested rows are the
  // assembly plan's own top/bottom facing passes — deletable, one click.
  const [postWeld, setPostWeld] = useState<
    { id: string; name: string; min: number; suggested?: boolean }[]
  >([]);
  const [postWeldInit, setPostWeldInit] = useState(false);
  const [pwFormName, setPwFormName] = useState("");
  const [pwFormMin, setPwFormMin] = useState("");

  // Returns the completed plans record so callers (Excel export) can use it
  // immediately instead of waiting a render for the rollup memo to catch up.
  async function buildRollup(): Promise<Record<string, StrategyResult> | null> {
    if (!partFile || !wmResult) return null;
    setRollupErr(null);
    const plans: Record<string, StrategyResult> = { ...rollupPlans };
    try {
      for (let i = 0; i < wmResult.groups.length; i++) {
        const g = wmResult.groups[i];
        if (plans[g.group_id]) continue;
        // EST-7: purchased parts need no machining plan.
        if (excludedBodies.has(g.group_id)) continue;
        setRollupBusy(
          `Planning ${titleCase(g.classification)} (${i + 1}/${wmResult.groups.length})…`,
        );
        const r = await api.strategy(partFile, {
          material: materialOptsFor(material),
          bodyIndex: g.body_indices[0],
          machine: machineOptsFor(machineSel),
          basis: estBasis,
        });
        plans[g.group_id] = r;
        setRollupPlans({ ...plans });
      }
      return plans;
    } catch (e) {
      setRollupErr(e instanceof Error ? e.message : "Assembly rollup failed");
      return null;
    } finally {
      setRollupBusy(null);
    }
  }

  // Seed the suggested post-weld facing from the billet assembly plan's own
  // top/bottom facing passes (real tool + feed derived times) — near-universal
  // practice after welding (distortion cleanup).
  useEffect(() => {
    if (postWeldInit || !strategy || !wmResult || wmResult.groups.length <= 1) return;
    const rows: { id: string; name: string; min: number; suggested: boolean }[] = [];
    for (const su of strategy.setups)
      for (const op of su.ops) {
        const f = (op.feature || "").toLowerCase();
        if (
          (op.operation || "").startsWith("Face Mill") &&
          (f.includes("top") || f.includes("bottom"))
        ) {
          rows.push({
            id: `pw-${su.setup_label}-${op.op_num}`,
            name: `Post-weld ${op.feature || op.operation}`,
            min: op.cut_min || 0,
            suggested: true,
          });
        }
      }
    if (rows.length) setPostWeld(rows);
    setPostWeldInit(true);
  }, [strategy, wmResult, postWeldInit]);

  // Selected-material density (g/cm³) — the SAME lookup the estimate ledger
  // uses (custom material wins, then library, then 2.7 default). Drives the
  // Overview "Part mass" line so it never disagrees with the Estimate tab.
  const partDensity = useMemo(() => {
    if (!analysis) return 2.7;
    return (
      customMaterials.find((m) => m.name === analysis.material)?.density ??
      materials.find((m) => m.name === analysis.material)?.density ??
      2.7
    );
  }, [analysis, customMaterials, materials]);

  const rollup = useMemo(() => {
    if (!analysis || !wmResult || wmResult.groups.length <= 1) return null;
    const complexity = Number.isFinite(estComplexity)
      ? Math.min(COMPLEXITY_MAX, Math.max(COMPLEXITY_MIN, estComplexity))
      : 1.0;
    const machMult = PRESET_MULT[estPreset] * complexity * TOLERANCE_MULT[estTolerance];
    const density =
      customMaterials.find((m) => m.name === analysis.material)?.density ??
      materials.find((m) => m.name === analysis.material)?.density ??
      2.7;
    const allow = 5.0;
    // Workpieces (assemblies) to build — workshop arithmetic: 10 assemblies
    // with 2 flanges each = 20 flanges through the shop.
    const NA = Math.max(1, Math.floor(qty) || 1);
    let ready = true;
    const rows = wmResult.groups.map((g) => {
      const pieces = g.quantity * NA;
      // EST-7: purchased parts (bolts, standard hardware) stay in the ledger
      // for the piece count but carry no machining plan and no cost.
      if (excludedBodies.has(g.group_id)) {
        return {
          g, ready: true as const, purchased: true, pieces,
          minBatch: 0, costBatch: 0,
        };
      }
      const plan = rollupPlans[g.group_id];
      if (!plan) {
        ready = false;
        return { g, ready: false as const, pieces, minBatch: 0, costBatch: 0 };
      }
      const adj = exclusionAdjusted(plan.setups, plan.totals);
      // Identical pieces of a group run in the SAME setups: setup time and
      // per-setup charges are paid once per group, run time repeats per piece.
      const cutPcMin = Math.max(adj.machineMin - adj.setupMin, 0);
      const minBatch = cutPcMin * pieces + adj.setupMin;
      const setupTimeCost = (adj.setupMin / 60) * rateHr * machMult;
      const runCostPc = (cutPcMin / 60) * rateHr * machMult;
      const stockVolCm3 =
        ((g.dims_mm.length + 2 * allow) *
          (g.dims_mm.width + 2 * allow) *
          (g.dims_mm.height + 2 * allow)) /
        1000;
      const matPc = ((stockVolCm3 * density) / 1000) * matPriceKg;
      const setupsCharge = adj.includedSetups * setupCharge;
      // Rate-card mode: per-piece machining = surface money + hole library;
      // setup TIME is not billed separately (the shop's ₹/cm² covers it) —
      // only the per-setup charge stays.
      const rcG = rateCardActive
        ? rateCardBreakdown(plan.setups, costingProfile, {
            grinding: false,
            isOpExcluded,
          })
        : null;
      const costBatch = rcG
        ? (matPc + rcG.total) * pieces + setupsCharge
        : (matPc + runCostPc) * pieces + setupTimeCost + setupsCharge;
      return { g, ready: true as const, pieces, minBatch, costBatch };
    });
    const plannedCount = rows.filter((r) => r.ready).length;
    const machSubtotal = rows.reduce((a, r) => a + (r.ready ? r.costBatch : 0), 0);
    const machMin = rows.reduce((a, r) => a + (r.ready ? r.minBatch : 0), 0);
    // Welding: the analyzer's minutes per assembly, or the fabricator's own
    // number when entered — × assemblies.
    // Welding is removable — shops that supply unwelded parts cross it out.
    const weldPerAssy = weldingOff ? 0 : (weldMinOverride ?? (wmResult.total_assembly_time_min ?? 0));
    const weldMin = weldPerAssy * NA;
    const weldCost = (weldMin / 60) * weldRate;
    const pwPerAssy = postWeld.reduce((a, r) => a + (r.min || 0), 0);
    const pwTotalMin = pwPerAssy * NA;
    const pwCost = (pwTotalMin / 60) * rateHr * machMult;
    // Assembled-only mode: the weldment arrives welded — no part machining,
    // no welding; just post-weld surface work × assemblies.
    const assembledSubtotal = pwCost;
    const assembledTotal = assembledSubtotal * (1 + marginPct / 100);
    const subtotal = machSubtotal + weldCost + pwCost;
    const total = subtotal * (1 + marginPct / 100);
    return {
      rows, ready, plannedCount, groupCount: rows.length, NA,
      machMin, machSubtotal, weldPerAssy, weldMin, weldCost,
      pwPerAssy, pwTotalMin, pwCost, subtotal, total,
      assembledSubtotal, assembledTotal,
    };
    // exclusionAdjusted closes over `excluded` — keep it in deps
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    analysis, wmResult, rollupPlans, excluded, estPreset, estTolerance,
    estComplexity, rateHr, matPriceKg, setupCharge, marginPct, weldRate,
    postWeld, materials, customMaterials, qty, weldMinOverride, weldingOff,
    rateCardActive, costingProfile, excludedBodies,
  ]);

  // ---- Shared estimate core (Estimate tab ledger + Route tab blocks) ----
  // One source of truth for the machining multiplier, material mass/cost and
  // setup charges, so the routed grand total is an exact superset of the
  // milling-only estimate.
  // WS-B: load/persist the deselected feature set per part (localStorage,
  // keyed by filename). Excluded features drop out of the estimate, quote and
  // G-code, and grey out in the plan. Nothing here is part-specific.
  useEffect(() => {
    const fn = analysis?.filename;
    if (!fn) return;
    try {
      const raw = localStorage.getItem(`cnc.excluded.${fn}`);
      setExcluded(new Set(raw ? (JSON.parse(raw) as string[]) : []));
    } catch {
      setExcluded(new Set());
    }
    setQty(1); // batch qty is a per-part decision — reset with the part
    setRollupPlans({});
    setPostWeld([]);
    setPostWeldInit(false);
    setRollupErr(null);
    setWeldMinOverride(null);
    setAddonSels([]); // add-ons are per-part decisions (ARD R4)
    setWeldingOff(false);
    try {
      const rawB = localStorage.getItem(`cnc.excludedBodies.${fn}`);
      setExcludedBodies(new Set(rawB ? (JSON.parse(rawB) as string[]) : []));
    } catch {
      setExcludedBodies(new Set());
    }
    const m = lsGet(`cnc.assyMode.${fn}`);
    setAssemblyModeState(m === "parts" || m === "assembled" ? m : null);
  }, [analysis?.filename]);
  useEffect(() => {
    const fn = analysis?.filename;
    if (!fn) return;
    try {
      localStorage.setItem(`cnc.excluded.${fn}`, JSON.stringify([...excluded]));
    } catch {
      /* storage disabled — keep session state only */
    }
  }, [excluded, analysis?.filename]);
  const toggleFeatureExcluded = (key: string) =>
    setExcluded((prev) => {
      const n = new Set(prev);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  const bulkExcluded = (keys: string[], exclude: boolean) =>
    setExcluded((prev) => {
      const n = new Set(prev);
      for (const k of keys) {
        if (exclude) n.add(k);
        else n.delete(k);
      }
      return n;
    });
  const estCore = useMemo(() => {
    if (!analysis || !strategy) return null;
    const adj = exclusionAdjusted(strategy.setups, strategy.totals);
    const machineMin = adj.machineMin;
    // Operator-controlled machining multiplier: quote preset × complexity ×
    // tolerance. Applies ONLY to machining-time cost lines — never to
    // material or setup charges.
    const presetMult = PRESET_MULT[estPreset];
    const tolMult = TOLERANCE_MULT[estTolerance];
    const complexity = Number.isFinite(estComplexity)
      ? Math.min(COMPLEXITY_MAX, Math.max(COMPLEXITY_MIN, estComplexity))
      : 1.0;
    const machMult = presetMult * complexity * tolMult;
    // ARD R2/R3 — Rate-card model: milling priced per cm² of machined surface
    // (each physical surface once) + holes from the cost library. Shop rates
    // are absolute: the time-model preset/complexity/tolerance multipliers do
    // NOT apply. Time-based stays the untouched default.
    const rc: RateCardBreakdown | null = rateCardActive
      ? rateCardBreakdown(strategy.setups, costingProfile, {
          isOpExcluded,
        })
      : null;
    const machining = rc ? rc.total : (machineMin / 60) * rateHr * machMult;
    // Custom materials win the density lookup — their density drives the
    // stock-mass line.
    const density =
      customMaterials.find((m) => m.name === analysis.material)?.density ??
      materials.find((m) => m.name === analysis.material)?.density ??
      2.7;
    // Material is bought as STOCK, not as the finished part — mass comes
    // from the stock block, so Manual stock sizes flow straight in.
    const stockSize =
      stockMode === "manual" && manualStock ? manualStock : analysis.stock?.size_mm;
    const stockVolCm3 = stockSize
      ? (stockSize.length * stockSize.width * stockSize.height) / 1000
      : (analysis.volumes_cm3.stock ?? 0); // legacy fallback: no stock block
    const massKg = (stockVolCm3 * density) / 1000;
    const materialCost = massKg * matPriceKg;
    // Setup charges follow the SURVIVING setups — excluding every feature of a
    // setup removes that setup's charge too.
    const setupsCost = adj.includedSetups * setupCharge;
    // ARD R4 add-ons — outsourced/secondary processes, priced in BOTH costing
    // models from the user's selection (each seeded from the rate-card library,
    // editable inline). per_cm2 uses machined or external surface; per_kg the
    // weight; flat a lump sum.
    const rcInfo =
      rc ??
      rateCardBreakdown(strategy.setups, costingProfile, { isOpExcluded });
    const envAreaCm2 = stockSize
      ? (2 *
          (stockSize.length * stockSize.width +
            stockSize.length * stockSize.height +
            stockSize.width * stockSize.height)) /
        100
      : 0;
    const addons = computeAddonSelections(addonSels, {
      envAreaCm2, machinedAreaCm2: rcInfo.millingAreaCm2, massKg,
    });
    const addonCost = addons.reduce((a, x) => a + x.cost, 0);
    return {
      machineMin, presetMult, tolMult, complexity, machMult, machining,
      stockSize, massKg, materialCost, setupsCost, rc, rcInfo, addons, addonCost,
    };
  }, [
    analysis, strategy, estPreset, estTolerance, estComplexity, excluded,
    customMaterials, materials, stockMode, manualStock, matPriceKg, setupCharge, rateHr,
    rateCardActive, costingProfile, addonSels,
  ]);

  // Per-body estimate (scoped): same ledger math as estCore but from the
  // SCOPED strategy plan and the body's own stock envelope (+5 mm/side).
  // One piece — the Bodies row shows ×N; the Route/assembly view remains
  // the whole-job quote. estCore itself stays whole-assembly because the
  // routed grand total must remain a superset of the milling estimate.
  const scopedEstCore = useMemo(() => {
    if (!analysis || !selectedGroup) return null;
    const sp = scopedStrategy;
    if (!sp || sp.scoped_body_index !== scopedBodyIndex) return null;
    const adj = exclusionAdjusted(sp.setups, sp.totals);
    const machineMin = adj.machineMin;
    const presetMult = PRESET_MULT[estPreset];
    const tolMult = TOLERANCE_MULT[estTolerance];
    const complexity = Number.isFinite(estComplexity)
      ? Math.min(COMPLEXITY_MAX, Math.max(COMPLEXITY_MIN, estComplexity))
      : 1.0;
    const machMult = presetMult * complexity * tolMult;
    const rc: RateCardBreakdown | null = rateCardActive
      ? rateCardBreakdown(sp.setups, costingProfile, {
          isOpExcluded,
        })
      : null;
    const machining = rc ? rc.total : (machineMin / 60) * rateHr * machMult;
    const density =
      customMaterials.find((m) => m.name === analysis.material)?.density ??
      materials.find((m) => m.name === analysis.material)?.density ??
      2.7;
    const dims = selectedGroup.dims_mm;
    const allow = 5.0;
    const stockSize = {
      length: dims.length + 2 * allow,
      width: dims.width + 2 * allow,
      height: dims.height + 2 * allow,
    };
    const stockVolCm3 =
      (stockSize.length * stockSize.width * stockSize.height) / 1000;
    const massKg = (stockVolCm3 * density) / 1000;
    const materialCost = massKg * matPriceKg;
    const setupsCost = adj.includedSetups * setupCharge;
    // ARD R4 add-ons — same model as estCore, scoped to this body.
    const rcInfo =
      rc ?? rateCardBreakdown(sp.setups, costingProfile, { isOpExcluded });
    const envAreaCm2 =
      (2 *
        (stockSize.length * stockSize.width +
          stockSize.length * stockSize.height +
          stockSize.width * stockSize.height)) /
      100;
    const addons = computeAddonSelections(addonSels, {
      envAreaCm2, machinedAreaCm2: rcInfo.millingAreaCm2, massKg,
    });
    const addonCost = addons.reduce((a, x) => a + x.cost, 0);
    return {
      machineMin, presetMult, tolMult, complexity, machMult, machining,
      stockSize, massKg, materialCost, setupsCost, rc, rcInfo, addons, addonCost,
    };
  }, [
    analysis, selectedGroup, scopedStrategy, scopedBodyIndex, estPreset,
    estTolerance, estComplexity, excluded, customMaterials, materials, matPriceKg,
    setupCharge, rateHr, rateCardActive, costingProfile, addonSels,
  ]);

  // ---- EST-4 (ARD R1): per-part Excel export with cost split ------------
  // Client-side workbook (excelExport.ts; exceljs lazy-loads on click).
  // Weldment jobs export one part per body group — missing per-part plans
  // are computed on first click (same fetch as "Compute exact per-part
  // plans"). Synthetic Welding / Post-weld / Margin rows keep the Summary
  // TOTAL reconciled to the on-screen grand total.
  const [excelBusy, setExcelBusy] = useState(false);
  async function exportExcel() {
    if (!analysis || !strategy || excelBusy) return;
    setExcelBusy(true);
    try {
      const profile = costingProfile;
      const N = Math.max(1, Math.floor(qty) || 1);
      const density =
        customMaterials.find((m) => m.name === analysis.material)?.density ??
        materials.find((m) => m.name === analysis.material)?.density ??
        2.7;
      const machMult = estCore ? estCore.machMult : 1;

      type XPart = WorkbookPayload["parts"][number];
      const syntheticPart = (name: string, cost: number, min: number): XPart => ({
        name, bodyIndex: -1, material: "—", quantity: 1, weightKg: null,
        machinedAreaCm2: 0, holeCount: 0, addons: [], costInr: cost,
        cycleMin: min, ops: [], holes: [], features: [],
      });

      const partFromPlan = (
        name: string,
        bodyIndex: number,
        plan: StrategyResult | null,
        base: {
          quantity: number; weightKg: number | null; costInr: number;
          cycleMin: number; purchased?: boolean; addons?: string[];
          features?: Candidate[];
        },
      ): XPart => {
        // Rate-card split for the per-op cost column; also computed in time
        // mode purely for the informational machined-area number.
        const rcInfoP = plan
          ? rateCardBreakdown(plan.setups, profile, {
              grinding: false, isOpExcluded,
            })
          : null;
        const rcp = rateCardActive ? rcInfoP : null;
        const ops: XPart["ops"] = [];
        const featureCostUsed = new Set<string>();
        if (plan && !base.purchased) {
          for (const su of plan.setups)
            for (const op of su.ops) {
              if (isOpExcluded(op)) continue;
              const key = baseName(op.feature || op.operation || "");
              let costInr: number | null = null;
              let costNote: string | undefined;
              if (rcp) {
                // The feature's FIRST op carries the rate-card price —
                // rough + finish passes are included in the shop's rate.
                const hole = rcp.holes.find((h) => h.feature === key);
                const mill = hole
                  ? null
                  : rcp.millingByFeature.find((m) => m.feature === key);
                if (hole) {
                  if (!featureCostUsed.has(key)) {
                    featureCostUsed.add(key);
                    costInr = hole.cost;
                    costNote = hole.note;
                  } else {
                    costInr = 0;
                    costNote = "per-hole price carried by the first op";
                  }
                } else if (mill) {
                  if (!featureCostUsed.has(key)) {
                    featureCostUsed.add(key);
                    costInr = mill.cost;
                    costNote = `${mill.areaCm2.toFixed(1)} cm² @ ${rcp.millingRate.toFixed(2)}/cm²`;
                  } else {
                    costInr = 0;
                    costNote = "surface priced once — rough+finish in the rate";
                  }
                } else {
                  costInr = 0;
                  costNote = "not separately priced";
                }
              } else {
                costInr = (op.cut_min / 60) * rateHr * machMult;
              }
              ops.push({
                opNum: op.op_num,
                setup: su.setup_label,
                opType: op.operation,
                tool: op.tool_display || op.tool,
                feature: op.feature || "—",
                depthMm: op.geo?.depth ?? null,
                cutLenMm: op.path_mm ?? null,
                cycleMin: op.cut_min || 0,
                areaCm2: op.machined_area_cm2 ?? 0,
                costInr,
                costNote,
              });
            }
        }
        // One row per physical hole feature, from validated geometry.
        const holes: XPart["holes"] = [];
        const holeSeen = new Set<string>();
        if (plan && !base.purchased) {
          for (const su of plan.setups)
            for (const op of su.ops) {
              const g = op.geo?.geometry;
              if (!g || g.kind !== "hole") continue;
              const key = baseName(op.feature || "");
              if (holeSeen.has(key)) continue;
              holeSeen.add(key);
              const rch = rcp?.holes.find((h) => h.feature === key) ?? null;
              holes.push({
                id: key || `hole-${holes.length + 1}`,
                diaMm: g.diameter_mm,
                tolerance: rch?.tolerance ?? inferTolerance(g),
                thicknessMm: g.depth_mm ?? null,
                thread: g.thread_likely || "—",
                through:
                  g.through == null ? "unknown" : g.through ? "through" : "blind",
                costInr: rch ? rch.cost : null,
                fallback: rch ? rch.method === "fallback" : false,
                counterDiaMm: g.cbore_diameter_mm ?? null,
                counterDepthMm: null,
              });
            }
        }
        const features: XPart["features"] = (base.features ?? []).map((c) => ({
          type: String(c.feature_type ?? "—"),
          name: String(c.feature_name ?? "—"),
          dia: c.diameter ?? null,
          l: c.length ?? null,
          w: c.width ?? null,
          depth: c.depth ?? null,
          confidence: String(c.confidence ?? "—"),
          setup: String(c.setup ?? "—"),
        }));
        return {
          name,
          bodyIndex,
          material: analysis.material,
          quantity: base.quantity,
          weightKg: base.weightKg,
          machinedAreaCm2: rcInfoP?.millingAreaCm2 ?? 0,
          holeCount: holes.length,
          addons: base.addons ?? [],
          costInr: base.costInr,
          cycleMin: base.cycleMin,
          purchased: base.purchased,
          ops,
          holes,
          features,
        };
      };

      const parts: XPart[] = [];
      let estimatorTotal = 0;
      const multiBody = !!(
        wmResult && wmResult.groups.length > 1 && !selectedGroup && rollup
      );

      if (multiBody && wmResult && rollup) {
        // Assembly job — make sure every non-purchased group has a plan
        // (decision: first click waits for the rollup computation).
        let plans = rollupPlans;
        if (!rollup.ready) {
          const done = await buildRollup();
          if (!done) return; // planning failed — rollupErr shows on screen
          plans = done;
        }
        const allow = 5.0;
        for (const g of wmResult.groups) {
          const purchased = excludedBodies.has(g.group_id);
          const plan = plans[g.group_id] ?? null;
          const pieces = g.quantity * N;
          const stockVolCm3 =
            ((g.dims_mm.length + 2 * allow) *
              (g.dims_mm.width + 2 * allow) *
              (g.dims_mm.height + 2 * allow)) /
            1000;
          const weightKg = (stockVolCm3 * density) / 1000;
          // Same batch math as the rollup memo — keep in lockstep.
          let costBatch = 0;
          let minBatch = 0;
          if (!purchased && plan && assemblyMode !== "assembled") {
            const adj = exclusionAdjusted(plan.setups, plan.totals);
            const cutPcMin = Math.max(adj.machineMin - adj.setupMin, 0);
            minBatch = cutPcMin * pieces + adj.setupMin;
            const setupTimeCost = (adj.setupMin / 60) * rateHr * machMult;
            const runCostPc = (cutPcMin / 60) * rateHr * machMult;
            const matPc = weightKg * matPriceKg;
            const setupsCharge = adj.includedSetups * setupCharge;
            const rcG = rateCardActive
              ? rateCardBreakdown(plan.setups, profile, {
                  grinding: false, isOpExcluded,
                })
              : null;
            costBatch = rcG
              ? (matPc + rcG.total) * pieces + setupsCharge
              : (matPc + runCostPc) * pieces + setupTimeCost + setupsCharge;
          }
          parts.push(
            partFromPlan(
              `${titleCase(g.classification)} ×${g.quantity}`,
              g.body_indices[0],
              plan,
              {
                quantity: pieces,
                weightKg,
                costInr: costBatch,
                cycleMin: minBatch,
                purchased,
                features: plan ? buildScopedFeatureRows(plan) : [],
              },
            ),
          );
        }
        // Welding / post-weld / margin — the rollup memo's own numbers
        // (plan-independent, so valid even while plans were pending).
        if (assemblyMode === "assembled") {
          const sub = rollup.pwCost;
          const marginAmt = sub * (marginPct / 100);
          parts.push(
            syntheticPart("Post-weld machining", rollup.pwCost, rollup.pwTotalMin),
          );
          parts.push(syntheticPart(`Margin (${marginPct}%)`, marginAmt, 0));
          estimatorTotal = sub + marginAmt;
        } else {
          const machSubtotal = parts.reduce((a, p) => a + p.costInr, 0);
          const sub = machSubtotal + rollup.weldCost + rollup.pwCost;
          const marginAmt = sub * (marginPct / 100);
          parts.push(syntheticPart("Welding", rollup.weldCost, rollup.weldMin));
          if (rollup.pwCost > 0)
            parts.push(
              syntheticPart("Post-weld machining", rollup.pwCost, rollup.pwTotalMin),
            );
          parts.push(syntheticPart(`Margin (${marginPct}%)`, marginAmt, 0));
          estimatorTotal = sub + marginAmt;
        }
      } else {
        // Single part (or scoped body) — mirror the on-screen batch ledger.
        const core = selectedGroup && scopedEstCore ? scopedEstCore : estCore;
        const sp =
          selectedGroup && scopedStrategy && scopedEstCore
            ? scopedStrategy
            : strategy;
        if (!core || !sp) return;
        const adjX = exclusionAdjusted(sp.setups, sp.totals);
        const setupTimeCost = core.rc
          ? 0
          : (adjX.setupMin / 60) * rateHr * core.machMult;
        const runCostPc =
          Math.max(core.machining - setupTimeCost, 0) +
          core.materialCost +
          core.addonCost;
        const setupOnce = setupTimeCost + core.setupsCost;
        const batchSubtotal = runCostPc * N + setupOnce;
        const batchTotal = batchSubtotal * (1 + marginPct / 100);
        const cutPcMin = Math.max(adjX.machineMin - adjX.setupMin, 0);
        parts.push(
          partFromPlan(
            selectedGroup
              ? `${titleCase(selectedGroup.classification)} (scoped)`
              : analysis.filename,
            selectedGroup ? selectedGroup.body_indices[0] : 0,
            sp,
            {
              quantity: N,
              weightKg: core.massKg,
              costInr: batchSubtotal,
              cycleMin: cutPcMin * N + adjX.setupMin,
              addons: core.addons.map((a) => a.name),
              features: featureTableRows,
            },
          ),
        );
        const marginAmt = batchTotal - batchSubtotal;
        parts.push(syntheticPart(`Margin (${marginPct}%)`, marginAmt, 0));
        estimatorTotal = batchTotal;
      }

      const today = new Date().toISOString().slice(0, 10);
      const library: WorkbookPayload["library"] = [
        {
          category: "Milling", sub: "Machined surface", unit: `${sym}/cm²`,
          rate: profile.milling_rate_per_cm2, effectiveFrom: today,
          source: "rate card", confirmed: true,
        },
        ...addonLibraryFor(profile).map((p) => ({
          category: "Add-on",
          sub: p.name,
          unit:
            p.basis === "flat" ? `${sym} flat`
              : p.basis === "per_kg" ? `${sym}/kg`
                : `${sym}/cm²${p.area === "machined" ? " machined" : ""}`,
          rate: p.rate,
          effectiveFrom: p.effective_from,
          source: p.source,
          confirmed: p.confirmed,
        })),
        ...profile.holeLibrary.map((r) => ({
          category: "Hole",
          sub: `Ø${r.diameter_mm} ${r.tolerance} × ${r.thickness_mm} mm — ${r.operation}`,
          unit: `${sym}/hole`,
          rate: r.cost_inr,
          effectiveFrom: r.effective_from,
          source: r.source,
          confirmed: r.confirmed,
        })),
      ];

      const blob = await buildWorkbook({
        filename: analysis.filename,
        currencySymbol: sym,
        costingModel: rateCardActive ? "ratecard" : "time",
        library,
        parts,
        totals: { estimatorTotal },
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${analysis.filename.replace(/\.[^.]+$/, "")}_cost_split.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } finally {
      setExcelBusy(false);
    }
  }

  // Feature Table source: under a body scope, use the classifier's
  // de-duplicated features (with setup labels) instead of the raw whole-part
  // billet candidates that over-segment slots (gap-v5 A2 + C1).
  const featureTableRows = useMemo<Candidate[]>(() => {
    if (
      selectedGroup && scopedStrategy &&
      scopedStrategy.scoped_body_index === scopedBodyIndex
    ) {
      return buildScopedFeatureRows(scopedStrategy);
    }
    return analysis?.candidates ?? [];
  }, [analysis, selectedGroup, scopedStrategy, scopedBodyIndex]);

  // WS-B: pickable feature handles for the 3D right-click deselect. One per
  // physical feature (deduped by exclusion key) at its geo position, from the
  // plan currently on screen (scoped body or whole assembly).
  const pickFeatures = useMemo(() => {
    const sp = selectedGroup && scopedStrategy ? scopedStrategy : strategy;
    type PF = { id: string; opId: string; hl: Highlight; faces: Mesh[] };
    if (!sp) return [] as PF[];
    const byId = new Map<string, PF>();
    const order: string[] = [];
    for (const su of sp.setups)
      for (const op of su.ops) {
        const g = op.geo;
        if (!g || g.x == null || g.y == null || g.z == null) continue;
        const id = opFeatureKey(op);
        let entry = byId.get(id);
        if (!entry) {
          entry = {
            id,
            opId: `${su.setup_label}-${op.op_num}`,
            hl: {
              x: g.x, y: g.y, z: g.z,
              diameter: g.diameter ?? 0,
              length: g.length ?? 0,
              width: g.width ?? 0,
              depth: g.depth ?? 0,
              feature_type: g.feature_type || op.operation || "",
            },
            faces: [],
          };
          byId.set(id, entry);
          order.push(id);
        }
        // A feature spans several ops (rough/finish); grab the exact faces from
        // whichever op carries them so the excluded fill sits on the REAL shape,
        // not an axis-aligned box.
        if (!entry.faces.length) {
          let faces = normalizeFaceMeshes(g.face_mesh_data);
          if (!faces.length && g.candidate_id && analysis) {
            const cand = analysis.candidates.find((c) => c.candidate_id === g.candidate_id);
            if (cand) faces = normalizeFaceMeshes(cand.face_mesh_data);
          }
          if (faces.length) entry.faces = faces;
        }
      }
    return order.map((id) => byId.get(id)!);
  }, [selectedGroup, scopedStrategy, strategy, analysis]);

  // ---- Route rollup: block times/costs + routed grand total ----
  // Computed at top level (not in the Route tab) because the Estimate tab
  // links to the routed total whenever the route has more than one block.
  const routeCalc = useMemo(() => {
    if (!estCore) return null;
    const millingCost = estCore.machining; // identical to the estimate's machining lines
    const hasWeld = !!wmResult;
    const weldMin = wmResult?.total_assembly_time_min ?? 0;
    const weldCost = (weldMin / 60) * weldRate;
    const turnedCount = (wmResult?.groups ?? [])
      .filter((g) => TURNED_RE.test(g.classification))
      .reduce((n, g) => n + g.quantity, 0);
    // Turned regions detected on the part itself (Epic 20 v1) also make
    // the Turning block appear — single-body shafts have no weldment groups.
    const autoTurnMin = analysis?.turning?.est_minutes ?? 0;
    const hasTurning = turnedCount > 0 || autoTurnMin > 0;
    // Manual entry wins; otherwise the planned lathe minutes drive the block.
    const effTurnMin = turnMin > 0 ? turnMin : autoTurnMin;
    const turnCost = (effTurnMin / 60) * turnRate;
    const customMin = customRouteSteps.reduce((s, c) => s + c.timeMin, 0);
    const customCost = customRouteSteps.reduce((s, c) => s + (c.timeMin / 60) * c.rateHr, 0);
    // ARD R4: selected add-on processes (grinding/plating/hardening/powder/
    // custom) are route blocks too — outsourced, so they add cost, not
    // machine minutes.
    const addons = estCore.addons;
    const addonCost = estCore.addonCost;
    const blockCount =
      1 + (hasWeld ? 1 : 0) + (hasTurning ? 1 : 0) + customRouteSteps.length + addons.length;
    const totalMin =
      estCore.machineMin + (hasWeld ? weldMin : 0) + (hasTurning ? effTurnMin : 0) + customMin;
    const blocksCost =
      millingCost + (hasWeld ? weldCost : 0) + (hasTurning ? turnCost : 0) + customCost +
      addonCost;
    // Same footer math as the Estimate ledger — material + setups + margin —
    // with all process blocks in place of the single machining line.
    const subtotal = blocksCost + estCore.materialCost + estCore.setupsCost;
    const margin = subtotal * (marginPct / 100);
    const total = subtotal + margin;
    return {
      millingCost, hasWeld, weldMin, weldCost, turnedCount, hasTurning, turnCost,
      autoTurnMin, effTurnMin, addons, addonCost,
      customMin, customCost, blockCount, totalMin, blocksCost, subtotal, margin, total,
    };
  }, [estCore, analysis, wmResult, weldRate, turnMin, turnRate, customRouteSteps, marginPct]);

  // ---- Setup orientation (Overview → Setups click) ----
  const [activeSetup, setActiveSetup] = useState<string | null>(null);

  // Full-assembly mesh bounding box (raw-CAD frame) for face centers.
  const meshBounds = useMemo(() => {
    const m = analysis?.mesh;
    if (!m || !m.x.length) return null;
    const mins = [Infinity, Infinity, Infinity];
    const maxs = [-Infinity, -Infinity, -Infinity];
    const axes = [m.x, m.y, m.z];
    for (let a = 0; a < 3; a++) {
      const arr = axes[a];
      for (let i = 0; i < arr.length; i++) {
        const v = arr[i];
        if (!Number.isFinite(v)) continue;
        if (v < mins[a]) mins[a] = v;
        if (v > maxs[a]) maxs[a] = v;
      }
    }
    if (![...mins, ...maxs].every(Number.isFinite)) return null;
    return { mins, maxs };
  }, [analysis]);

  // Camera direction + approach cone for the active setup. Unknown labels
  // get an isometric view and no cone (no face to point at).
  const setupView = useMemo((): { dir: Vec3 | null; approach: Approach | null } => {
    if (!activeSetup) return { dir: null, approach: null };
    const d = SETUP_DIRS[normalizeSetupLabel(activeSetup)];
    if (!d) return { dir: ISO_DIR, approach: null };
    if (!meshBounds) return { dir: d, approach: null };
    const { mins, maxs } = meshBounds;
    const mid = (a: number) => (mins[a] + maxs[a]) / 2;
    // Center of the bbox face the tool enters through.
    const origin: Vec3 = [
      d[0] !== 0 ? (d[0] > 0 ? maxs[0] : mins[0]) : mid(0),
      d[1] !== 0 ? (d[1] > 0 ? maxs[1] : mins[1]) : mid(1),
      d[2] !== 0 ? (d[2] > 0 ? maxs[2] : mins[2]) : mid(2),
    ];
    // Tool direction = into the part = opposite the face normal.
    return { dir: d, approach: { origin, dir: [-d[0], -d[1], -d[2]] as Vec3 } };
  }, [activeSetup, meshBounds]);

  // Per-op tool-approach cone from the SELECTED op's own geometry — the tool
  // enters at the feature along its real entry direction, not the setup's
  // nominal face (a "BACK" setup can hold a Top-opening slot). entry_dir is
  // the OUTWARD vector (where the tool comes from), so the tool travels into
  // the part along -entry_dir. Works for the scoped body too (same raw-CAD
  // frame as its mesh), so a slot reads as cut INTO the part from outside.
  const opApproach = useMemo((): Approach | null => {
    const geo = selOpData?.geo;
    if (!geo || geo.x == null || geo.y == null || geo.z == null) return null;
    // The cutter plunges along the feature's tool axis (entry_dir = outward
    // normal of the machined face), NOT a slot's horizontal open_dir — the
    // real cut comes from the floor-normal face, matching the setup routing.
    // Ops without an entry vector (facing, steps) fall back to their SETUP's
    // outward face so the cone always shows where the tool comes from.
    const ed =
      geo.geometry?.entry_dir ??
      SETUP_DIRS[normalizeSetupLabel(selOpData?.setup ?? "")] ??
      null;
    if (!ed || ed.length < 3) return null;
    const n = Math.hypot(ed[0], ed[1], ed[2]);
    if (n < 1e-6) return null;
    return {
      origin: [geo.x, geo.y, geo.z] as Vec3,
      dir: [-ed[0] / n, -ed[1] / n, -ed[2] / n] as Vec3,
    };
  }, [selOpData]);

  // Auto-focus target for the selected op: the camera flies to the feature
  // along its outward tool direction (fallback: the setup face, else iso).
  const opFocus = useMemo((): { point: Vec3; dir: Vec3 } | null => {
    const g = selOpData?.geo;
    if (!g || g.x == null || g.y == null || g.z == null) return null;
    if (opApproach) {
      return {
        point: opApproach.origin,
        dir: [-opApproach.dir[0], -opApproach.dir[1], -opApproach.dir[2]] as Vec3,
      };
    }
    const d = SETUP_DIRS[normalizeSetupLabel(selOpData?.setup ?? "")] ?? ISO_DIR;
    return { point: [g.x, g.y, g.z] as Vec3, dir: d };
  }, [selOpData, opApproach]);

  // Fixture context: the active machined-face normal (tool axis) + the
  // recommended workholding method, so the 3D fixture clamps CLEAR of the
  // face being cut and matches vise-vs-fixture-plate. Sourced from the
  // selected op's setup when scoped, else the active whole-assembly setup.
  const fixtureCtx = useMemo((): {
    toolAxis: Vec3 | null;
    method: string | null;
    flip: boolean;
    facing: boolean;
  } => {
    // Does the active setup face-mill its whole surface? Then clamps must
    // grip the part ENDS below the machined face — a toe on the face being
    // faced would sit in the cutter's path.
    const setupHasFacing = (label: string | null): boolean => {
      if (!label) return false;
      const su = stratForView?.setups.find(
        (s) => normalizeSetupLabel(s.setup_label) === normalizeSetupLabel(label),
      );
      return !!su?.ops.some((op) => (op.operation || "").startsWith("Face Mill"));
    };
    if (selectedGroup) {
      const setupLabel = selOpData?.setup ?? stratForView?.setups[0]?.setup_label ?? null;
      if (!setupLabel) return { toolAxis: null, method: null, flip: false, facing: false };
      const su = stratForView?.setups.find((s) => s.setup_label === setupLabel);
      return {
        toolAxis: SETUP_DIRS[normalizeSetupLabel(setupLabel)] ?? null,
        method: su?.workholding?.method ?? stratForView?.setups[0]?.workholding?.method ?? null,
        flip: false,
        facing: setupHasFacing(setupLabel),
      };
    }
    // A selected op re-orients the WHOLE-PART view too: the part sits
    // working-face-up exactly as it would in the machine for that op's
    // setup. A VMC tool never enters from below — without this, bottom-face
    // ops read as "drilling upward" in the raw part orientation.
    if (selOpData?.setup) {
      const su = stratForView?.setups.find(
        (s) => normalizeSetupLabel(s.setup_label) === normalizeSetupLabel(selOpData.setup),
      );
      return {
        toolAxis: SETUP_DIRS[normalizeSetupLabel(selOpData.setup)] ?? null,
        method: su?.workholding?.method ?? null,
        flip: SECONDARY_FACE_RE.test(selOpData.setup),
        facing: setupHasFacing(selOpData.setup),
      };
    }
    if (activeSetup) {
      const su = analysis?.setups?.find(
        (s) => normalizeSetupLabel(s.label) === normalizeSetupLabel(activeSetup),
      );
      return {
        toolAxis: SETUP_DIRS[normalizeSetupLabel(activeSetup)] ?? null,
        method: su?.method ?? null,
        flip: SECONDARY_FACE_RE.test(activeSetup),
        facing: setupHasFacing(activeSetup),
      };
    }
    return { toolAxis: null, method: null, flip: false, facing: false };
  }, [selectedGroup, selOpData, stratForView, activeSetup, analysis]);

  // ---- Thread status per hole diameter (session-only UI state) ----
  const [threadByDia, setThreadByDia] = useState<Record<string, string>>({});
  const [quoteOpen, setQuoteOpen] = useState(false);

  // ---- AI Assistant panel (paid tier) ----
  const [assistantOpen, setAssistantOpen] = useState(false);
  // Compact plan summary sent with every question — a summary dict, not raw
  // meshes/candidates. Mirrors the whole-assembly Estimate tab ledger
  // (estCore), so the numbers the assistant cites match what's on screen.
  const assistantContext = useMemo((): AssistantContext | null => {
    if (!analysis || !strategy || !estCore) return null;
    return {
      filename: analysis.filename,
      material: analysis.material,
      machine: machineSel || strategy.machine || analysis.machine || null,
      setups: strategy.setups.map((su) => ({
        label: su.setup_label,
        op_count: su.ops.length,
        subtotal_min: su.subtotal_min,
        workholding: su.workholding?.method ?? null,
      })),
      totals: {
        machine_time_min: Math.round(estCore.machineMin * 10) / 10,
        tool_changes: strategy.totals.num_tool_changes ?? 0,
        setup_count: strategy.setups.length,
      },
      estimate: {
        material: Math.round(estCore.materialCost),
        machining: Math.round(estCore.machining),
        setups: Math.round(estCore.setupsCost),
        total: Math.round(estCore.materialCost + estCore.machining + estCore.setupsCost),
      },
      excluded_count: excluded.size,
    };
  }, [analysis, strategy, estCore, machineSel, excluded]);

  async function fetchWeldment(file: File) {
    setWmLoading(true);
    setWmError(null);
    try {
      const r = await api.weldment(file);
      if (wmFileRef.current !== file) return; // superseded by a newer file
      setWmResult(r);
      setWmLoading(false);
    } catch (err) {
      if (wmFileRef.current !== file) return;
      wmFileRef.current = null; // allow retry
      setWmError(err instanceof Error ? err.message : "Body analysis failed");
      setWmLoading(false);
    }
  }

  function retryWeldment() {
    if (!partFile) return;
    wmFileRef.current = partFile;
    void fetchWeldment(partFile);
  }

  function selectScope(groupId: string | null) {
    setSelectedGroupId(groupId);
    // Op highlights belong to the previous scope's plan — they don't
    // survive a scope change. Neither do rollup expansions, the setup
    // orientation, or the currently shown scoped plan.
    setSelOp(null);
    setHighlight(null);
    setExpanded({});
    setActiveSetup(null);
    setScopedStrategy(null);
    setScopedError(null);
  }

  const [theme, setTheme] = useState<Theme>(() => (lsGet("cnc.theme") === "light" ? "light" : "dark"));
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    lsSet("cnc.theme", theme);
  }, [theme]);

  useEffect(() => {
    let alive = true;
    api
      .materials()
      .then((r) => {
        if (!alive) return;
        setMaterials(r.materials);
        setMaterial((cur) => cur || (r.materials[0]?.name ?? ""));
      })
      .catch(() => {
        /* selector stays empty; analyze falls back to backend default */
      });
    api
      .machines()
      .then((r) => {
        if (alive) setMachines(r.machines);
      })
      .catch(() => {
        /* machine dropdown shows custom machines only */
      });
    return () => {
      alive = false;
    };
  }, []);

  // Inspector resize / collapse
  const [inspWidth, setInspWidth] = useState<number>(loadInspectorWidth);
  const [inspCollapsed, setInspCollapsed] = useState(() => lsGet("cnc.inspectorCollapsed") === "1");
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startX: number; startW: number } | null>(null);

  function setInspectorCollapsed(c: boolean) {
    setInspCollapsed(c);
    lsSet("cnc.inspectorCollapsed", c ? "1" : "0");
  }

  function onHandleDown(e: ReactPointerEvent<HTMLDivElement>) {
    dragRef.current = { startX: e.clientX, startW: inspWidth };
    setDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "col-resize";
  }

  function onHandleMove(e: ReactPointerEvent<HTMLDivElement>) {
    const d = dragRef.current;
    if (!d) return;
    const w = Math.min(INSPECTOR_MAX, Math.max(INSPECTOR_MIN, d.startW + (d.startX - e.clientX)));
    setInspWidth(w);
  }

  function onHandleUp(e: ReactPointerEvent<HTMLDivElement>) {
    if (!dragRef.current) return;
    dragRef.current = null;
    setDragging(false);
    try {
      e.currentTarget.releasePointerCapture(e.pointerId);
    } catch {
      /* capture may already be released */
    }
    document.body.style.userSelect = "";
    document.body.style.cursor = "";
    lsSet("cnc.inspectorWidth", String(inspWidth));
  }

  async function runAnalysis(
    file: File,
    opts?: { material?: MaterialOpts; preserveTab?: boolean; machine?: MachineOpts },
  ) {
    const mat = opts?.material ?? materialOptsFor(material);
    const mach = opts?.machine ?? machineOptsFor(machineSel);
    const isNewFile = partFile !== file; // material/machine re-runs pass the same File
    setLoading(true);
    setError(null);
    setView("part");
    setPartFile(file);
    setSelectedGroupId(null); // scope resets on any new analysis
    setScopedStrategy(null);
    setScopedError(null);
    setActiveSetup(null);
    if (wmFileRef.current !== file) {
      // Different part — drop the cached weldment breakdown and any
      // body-scoped strategy plans (body indices are per-file).
      wmFileRef.current = null;
      setWmResult(null);
      setWmError(null);
      setWmLoading(false);
      scopedCacheRef.current.clear();
    }
    try {
      const a = await api.analyze(file, { material: mat, machine: mach });
      setAnalysis(a);
      // Stock config: reset on a new part; survive material/machine re-runs.
      if (isNewFile) setStockMode("auto");
      const sz = a.stock?.size_mm;
      if (sz) {
        setManualStock((cur) => (isNewFile || !cur ? { ...sz } : cur));
      } else if (isNewFile) {
        setManualStock(null);
      }
      // Body breakdown loads in parallel — never blocks the main analyze flow.
      // Weldment output is material-independent, so a cached result is kept.
      if (a.is_multibody && wmFileRef.current !== file) {
        wmFileRef.current = file;
        void fetchWeldment(file);
      }
      if (a.material) setMaterial(a.material); // sync to what the backend resolved
      if (a.machine) setMachineSel(a.machine); // engine default may be unnamed (null)
      // Ref (not closure state) for basis: the user may flip it while
      // analyze is in flight. Token guards against a newer basis refetch
      // landing before this older whole-assembly plan does.
      const stratToken = ++stratReqRef.current;
      setBasisLoading(false); // a full re-analysis supersedes any basis refetch
      const s = await api.strategy(file, { material: mat, machine: mach, basis: estBasisRef.current });
      if (stratReqRef.current === stratToken) setStrategy(s);
      if (!opts?.preserveTab) setTab("overview");
      setSelOp(null);
      setHighlight(null);
      setExpanded({});
      setThreadByDia({}); // thread statuses are per-analysis session state
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  function changeMaterial(name: string) {
    setMaterial(name);
    lsSet("cnc.material", name);
    if (partFile) void runAnalysis(partFile, { material: materialOptsFor(name), preserveTab: true });
  }

  // Save a custom material (localStorage), select it, and re-run with its
  // JSON. Scoped plans keyed by this name may now be stale (re-saving a
  // name with new factors changes the plan) — drop them.
  function addCustomMaterial(m: Material) {
    const next = [...customMaterials.filter((c) => c.name !== m.name), m];
    setCustomMaterials(next);
    lsSet("cnc.customMaterials", JSON.stringify(next));
    setMaterial(m.name);
    lsSet("cnc.material", m.name);
    scopedCacheRef.current.clear();
    if (partFile) {
      void runAnalysis(partFile, {
        preserveTab: true,
        material: { materialJson: JSON.stringify(m) },
      });
    }
  }

  // Re-fetch the whole-assembly strategy only — basis is a planning knob,
  // the analyze result (features/DFM/mesh) does not depend on it.
  async function refetchStrategy(file: File, basis: PlanBasis) {
    const token = ++stratReqRef.current;
    setBasisLoading(true);
    try {
      const s = await api.strategy(file, {
        material: materialOptsFor(material),
        machine: machineOptsFor(machineSel),
        basis,
      });
      if (stratReqRef.current !== token) return;
      setStrategy(s);
    } catch (err) {
      if (stratReqRef.current !== token) return;
      setError(err instanceof Error ? err.message : "Strategy refresh failed");
    } finally {
      if (stratReqRef.current === token) setBasisLoading(false);
    }
  }

  function changeBasis(b: PlanBasis) {
    if (b === estBasis) return;
    estBasisRef.current = b;
    setEstBasis(b);
    lsSet("cnc.estBasis", b);
    // Op ids / rollup keys belong to the old-basis plan.
    setSelOp(null);
    setHighlight(null);
    setExpanded({});
    // The scoped effect re-resolves via its cache (basis is in the key);
    // null out the old-basis scoped plan so it can't linger meanwhile.
    setScopedStrategy(null);
    if (partFile) void refetchStrategy(partFile, b);
  }

  function changePreset(p: QuotePreset) {
    setEstPreset(p);
    lsSet("cnc.estPreset", p);
  }

  function changeComplexity(v: number) {
    setEstComplexity(v);
    lsSet("cnc.estComplexity", String(v));
  }

  function changeTolerance(t: ToleranceClass) {
    setEstTolerance(t);
    lsSet("cnc.estTolerance", t);
  }

  function changeMachine(name: string) {
    setMachineSel(name);
    lsSet("cnc.machine", name);
    if (partFile) void runAnalysis(partFile, { preserveTab: true, machine: machineOptsFor(name) });
  }

  // Save a custom machine (localStorage), select it, and re-plan with its
  // JSON. The next list is computed here because machineOptsFor would still
  // see the pre-setState customMachines.
  function addCustomMachine(m: CustomMachine) {
    const next = [...customMachines.filter((c) => c.name !== m.name), m];
    setCustomMachines(next);
    lsSet("cnc.customMachines", JSON.stringify(next));
    setMachineSel(m.name);
    lsSet("cnc.machine", m.name);
    if (partFile) {
      void runAnalysis(partFile, { preserveTab: true, machine: { machineJson: JSON.stringify(m) } });
    }
  }

  // Edit a custom machine in place (Shop Library "✎ Edit"): replace by its
  // old name; keep selection and the my-machines tick following a rename.
  function updateCustomMachine(originalName: string, m: CustomMachine) {
    const next = customMachines.map((c) => (c.name === originalName ? m : c));
    setCustomMachines(next);
    lsSet("cnc.customMachines", JSON.stringify(next));
    if (m.name !== originalName && myMachines.has(originalName)) {
      setMyMachines((prev) => {
        const n = new Set(prev);
        n.delete(originalName);
        n.add(m.name);
        lsSet("cnc.myMachines", JSON.stringify([...n]));
        return n;
      });
    }
    if (machineSel === originalName) {
      setMachineSel(m.name);
      lsSet("cnc.machine", m.name);
      if (partFile) {
        void runAnalysis(partFile, { preserveTab: true, machine: { machineJson: JSON.stringify(m) } });
      }
    }
  }

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(e.target.files ?? []);
    if (!files.length) return;
    // Add every selected file to the project (dedupe by name+size), so the
    // user can drop in 5–6 STEPs at once and browse them as cards.
    setUploadedParts((prev) => {
      const key = (f: File) => `${f.name}:${f.size}`;
      const seen = new Set(prev.map(key));
      return [...prev, ...files.filter((f) => !seen.has(key(f)))];
    });
    // Open the first one immediately so there's instant feedback; the rest
    // wait as cards on Projects.
    void runAnalysis(files[0]);
    e.target.value = ""; // let the same files be re-picked later
  }

  async function loadSample() {
    setLoading(true);
    setError(null);
    try {
      const file = await api.sampleFile(SAMPLE_NAME);
      await runAnalysis(file);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sample failed");
      setLoading(false);
    }
  }

  // Rollups for whichever plan the Strategy tab is showing (scoped or whole).
  const rollupsBySetup = useMemo(() => {
    let setups = stratForView?.setups ?? [];
    // "Already welded" intent: parts buried in the weldment can't be machined
    // individually at all — a scoped body shows no ops (banner explains).
    if (
      selectedGroup &&
      assemblyMode === "assembled" &&
      wmResult &&
      wmResult.groups.length > 1
    ) {
      return [];
    }
    // …and the assembly-level plan keeps only SURFACE operations (facing,
    // chamfer/edge cleanup) — you can't pocket or drill inside a weldment.
    // Select/deselect as usual.
    if (
      !selectedGroup &&
      assemblyMode === "assembled" &&
      wmResult &&
      wmResult.groups.length > 1
    ) {
      const surface = (op: StrategyOp) => {
        const o = (op.operation || "").toLowerCase();
        const f = (op.feature || "").toLowerCase();
        return (
          o.startsWith("face mill") || o.includes("chamfer") ||
          f.includes("edge") || f.includes("chamfer")
        );
      };
      setups = setups
        .map((su) => {
          const ops = su.ops.filter(surface);
          return {
            ...su,
            ops,
            subtotal_min: ops.reduce((a, op) => a + (op.cut_min || 0), 0),
          };
        })
        .filter((su) => su.ops.length > 0);
    }
    return setups.map((su) => ({
      label: su.setup_label,
      opCount: su.ops.length,
      subtotal: su.subtotal_min,
      workholding: su.workholding ?? null,
      rollups: buildRollups(su.setup_label, su.ops),
    }));
  }, [stratForView, selectedGroup, assemblyMode, wmResult]);

  function toggleRollup(key: string) {
    setExpanded((e) => ({ ...e, [key]: !e[key] }));
  }

  // Bodies list (multibody only): "Full assembly" row + one row per group.
  // Rendered in both scoped and unscoped Overview layouts.
  function renderBodiesSection() {
    if (!analysis?.is_multibody) return null;
    return (
      <>
        <div className="section-title">
          Bodies{wmResult ? ` — ${wmResult.total_bodies} in ${wmResult.groups.length} groups` : ""}
        </div>
        {wmLoading && (
          <div style={{ fontSize: 12, color: "var(--text-2)", padding: "6px 0" }}>Analysing bodies…</div>
        )}
        {wmError && (
          <div className="row" style={{ borderBottom: "none" }}>
            <span className="k" style={{ color: "var(--red)" }}>{wmError}</span>
            <button className="btn" style={{ padding: "3px 10px", fontSize: 11 }} onClick={retryWeldment}>
              Retry
            </button>
          </div>
        )}
        {wmResult && (
          <>
            <div
              className={`body-row ${!selectedGroupId ? "sel" : ""}`}
              onClick={() => selectScope(null)}
              title="Show the whole weldment"
            >
              <div className="main">
                <div className="name">Full assembly</div>
                <div className="dims">
                  {wmResult.total_bodies} bodies · {wmResult.groups.length} groups
                </div>
                {wmResult.reporting && (
                  <div
                    className="dims"
                    title={`Assembly total mass = Σ(every body volume × ${partDensity} g/cm³). Machined area = total machinable surface. Volume = ${fmtVolCm3(wmResult.reporting.total_volume_cm3)}.`}
                  >
                    {fmtMass(wmResult.reporting.total_volume_cm3 * partDensity)}
                    {" · "}
                    {fmtAreaCm2(wmResult.reporting.machined_area_cm2_total)}
                  </div>
                )}
              </div>
              <span className="t">{fmtNum(wmResult.total_machining_time_min)} min</span>
            </div>
            {wmResult.groups.map((g) => {
              // EST-7: purchased parts (bolts, standard hardware) are viewed
              // but never machined or costed.
              const purchased = excludedBodies.has(g.group_id);
              return (
              <div
                key={g.group_id}
                className={`body-row ${selectedGroupId === g.group_id ? "sel" : ""}`}
                style={purchased ? { opacity: 0.55 } : undefined}
                onClick={() => selectScope(g.group_id)}
                title={`${scopeLabel(g)} — click to isolate in 3D`}
              >
                <div className="main">
                  <div className="name">
                    {titleCase(g.classification)} ×{g.quantity}
                    {purchased && (
                      <span
                        style={{
                          marginLeft: 6, fontSize: 10, fontWeight: 600,
                          color: "#c07a2a", border: "1px solid #c07a2a",
                          borderRadius: 4, padding: "0 4px",
                        }}
                      >
                        purchased
                      </span>
                    )}
                  </div>
                  <div className="dims">{groupDims(g)} mm</div>
                  <div
                    className="dims"
                    title={`Per body: volume ${fmtVolCm3(g.volume_cm3)}, mass = volume × ${partDensity} g/cm³${g.quantity > 1 ? ` (×${g.quantity} in the assembly)` : ""}.`}
                  >
                    {fmtMass(g.volume_cm3 * partDensity)}
                    {g.machined_area_cm2 != null && ` · ${fmtAreaCm2(g.machined_area_cm2)}`}
                    {g.quantity > 1 && ` /pc`}
                  </div>
                  {g.feature_counts && (
                    <div
                      className="dims"
                      title={
                        g.features_brief?.length
                          ? "Per-feature dims × depth:\n" + g.features_brief.join("\n")
                          : "Validated classifier counts (representative body)"
                      }
                    >
                      {typedCounts(g.feature_counts)}
                    </div>
                  )}
                </div>
                <button
                  className="btn"
                  style={{
                    padding: "0 6px", fontSize: 12, lineHeight: "18px",
                    color: purchased ? "#c07a2a" : undefined,
                  }}
                  title={
                    purchased
                      ? "Marked as purchased — no machining, no cost. Click to machine it again."
                      : "Don't machine (purchased part) — drop it from the job cost"
                  }
                  onClick={(e) => {
                    e.stopPropagation();
                    toggleBodyExcluded(g.group_id);
                  }}
                >
                  ⊘
                </button>
                <span className="t">
                  {assemblyMode === "assembled"
                    ? "view only"
                    : purchased
                      ? "purchased"
                      : `${fmtNum(g.machining_min_per_pc)} min/pc`}
                </span>
              </div>
              );
            })}
          </>
        )}
      </>
    );
  }

  // Setups render in BOTH scoped and unscoped Overview modes — operators
  // must always see them. The camera-orientation click only applies to the
  // whole-assembly view, so rows are static while a body scope is active.
  function renderSetupsSection() {
    const setups = analysis?.setups ?? [];
    if (!setups.length) return null;
    const interactive = !selectedGroup;
    return (
      <>
        <div className="section-title">Setups</div>
        {setups.map((s) => (
          <div
            className={`setup-row ${interactive ? "clickable" : ""} ${
              interactive && activeSetup === s.label ? "sel" : ""
            }`}
            key={s.label}
            title={interactive ? `${s.reason} — click to view from ${s.label}` : s.reason}
            onClick={
              interactive
                ? () => setActiveSetup((cur) => (cur === s.label ? null : s.label))
                : undefined
            }
          >
            <div className="setup-line">
              <span className="k">{s.label}</span>
              <span className="v">{s.method}</span>
            </div>
            <div className="setup-sub">{s.jaw_mode}</div>
          </div>
        ))}
      </>
    );
  }

  function renderHolesSection() {
    const groups = analysis?.hole_groups ?? [];
    if (!groups.length) return null;
    // Whole-part threaded census (Toolpath parity: "0 of 33"). Validated
    // per-body counts when the weldment split is available, else the
    // billet hole groups.
    const validatedTotal = (wmResult?.groups ?? []).reduce(
      (n, g) => n + (g.feature_counts?.holes ?? 0) * g.quantity,
      0,
    );
    const totalHoles =
      validatedTotal > 0
        ? validatedTotal
        : groups.reduce((n, g) => n + g.count, 0);
    return (
      <>
        <div className="section-title">Holes</div>
        <div className="hole-row" style={{ opacity: 0.9 }}>
          <span
            className="chip"
            title={
              validatedTotal > 0
                ? "Validated per-body hole count. Thread detection is inference-based — scope a body for likely-tap chips."
                : "From detected hole groups."
            }
          >
            0 of {totalHoles} holes threaded
          </span>
        </div>
        {groups.map((g) => {
          const diaKey = g.diameter_mm.toFixed(2);
          return (
            <div className="hole-row" key={g.diameter_mm}>
              <span className="hole-main">
                {g.count}× Ø{g.diameter_mm.toFixed(2)}mm
              </span>
              <select
                className="thread-select"
                title="Thread status (session only)"
                value={threadByDia[diaKey] ?? "none"}
                onChange={(e) =>
                  setThreadByDia((t) => ({ ...t, [diaKey]: e.target.value }))
                }
              >
                <option value="none">No Thread</option>
                <option value="tapped">Tapped</option>
                <option value="spec">Threaded (spec)</option>
              </select>
              <span className="hole-setups" title={formatSetups(g.setups)}>
                {formatSetups(g.setups)}
              </span>
            </div>
          );
        })}
      </>
    );
  }

  function renderOpRow(setupLabel: string, op: StrategyOp, child: boolean) {
    const id = `${setupLabel}-${op.op_num}`;
    const fkey = opFeatureKey(op);
    const ex = excluded.has(fkey);
    const strike = ex ? { textDecoration: "line-through" as const } : undefined;
    return (
      <div
        key={id}
        className={`op-row ${child ? "child" : ""} ${selOp === id ? "sel" : ""} ${ex ? "excluded" : ""}`}
        style={ex ? { opacity: 0.45 } : undefined}
        onClick={() => {
          if (selOp === id) {
            setSelOp(null);
            setHighlight(null);
          } else {
            setSelOp(id);
            setHighlight(op.geo);
          }
        }}
      >
        <span
          className={`op-dot ${op.blocked ? "red" : "green"}`}
          title={op.blocked ? "Blocked — no capable tool/setup" : "Plannable"}
        />
        <span className="seq">{op.op_num}</span>
        <div className="main">
          <div style={strike}>{child ? op.feature || op.operation : op.operation}</div>
          {!child && <div className="tool">{op.tool_display || op.tool}</div>}
        </div>
        <span className="t" style={strike}>{op.cut_min.toFixed(1)}m</span>
        <button
          className="op-skip"
          title={ex ? "Re-include this feature (machine it)" : "Exclude this feature — don't machine (e.g. already done)"}
          onClick={(e) => {
            e.stopPropagation();
            toggleFeatureExcluded(fkey);
          }}
          style={{
            marginLeft: 6,
            border: "none",
            background: "transparent",
            cursor: "pointer",
            color: ex ? "#4a9eff" : "var(--text-2)",
            fontSize: 13,
            lineHeight: 1,
            padding: "0 2px",
          }}
        >
          {ex ? "↺" : "⊘"}
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", height: "100%" }}>
      {error && (
        <div className="toast-error" onClick={() => setError(null)}>
          {error} <span style={{ opacity: 0.7, marginLeft: 8 }}>✕</span>
        </div>
      )}
      <div className="rail">
        <button
          className={view === "projects" ? "active" : ""}
          title="Projects"
          onClick={() => setView("projects")}
        >▦</button>
        <button
          className={view === "part" ? "active" : ""}
          title="Part workspace"
          onClick={() => setView("part")}
        >◧</button>
        <button
          className={view === "shop" ? "active" : ""}
          title="Shop Library — your machines & rate cards"
          onClick={() => setView("shop")}
        >▤</button>
        <button title="Team">◈</button>
      </div>

      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        <div className="topbar">
          <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
            <span style={{ fontWeight: 500, fontSize: 14 }}>
              {analysis ? analysis.filename : "CNC Plan & Process Pro"}
            </span>
            {analysis && (
              <div className="tabs">
                {(["overview", "strategy", "estimate", "route"] as Tab[]).map((t) => (
                  <button
                    key={t}
                    className={`tab ${tab === t ? "active" : ""}`}
                    onClick={() => {
                      setTab(t);
                      if (t !== "strategy") {
                        setSelOp(null);
                        setHighlight(null);
                      }
                    }}
                  >
                    {t[0].toUpperCase() + t.slice(1)}
                  </button>
                ))}
              </div>
            )}
            {analysis?.is_multibody && (
              <span
                className={`scope-chip ${selectedGroup ? "scoped" : ""}`}
                title={selectedGroup ? `Scoped to ${scopeLabel(selectedGroup)} — click ✕ to reset` : "Analysis covers the whole assembly"}
              >
                <span className="scope-label">
                  Scope: {selectedGroup ? scopeLabel(selectedGroup) : "Full assembly"}
                </span>
                {selectedGroup && (
                  <button className="scope-x" title="Reset to full assembly" onClick={() => selectScope(null)}>
                    ✕
                  </button>
                )}
              </span>
            )}
            {analysis && (
              <button
                className={`btn ${assistantOpen ? "primary" : ""}`}
                title="Ask about the current plan"
                onClick={() => setAssistantOpen((o) => !o)}
              >
                Assistant
              </button>
            )}
          </div>
          <div style={{ display: "flex", gap: 8 }}>
            <button
              className="btn icon"
              title={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"}
              onClick={() => setTheme((t) => (t === "dark" ? "light" : "dark"))}
            >
              {theme === "dark" ? "☀" : "☾"}
            </button>
            <button className="btn" onClick={() => fileRef.current?.click()}>
              Upload STEP
            </button>
            {analysis && strategy && (
              <button
                className="btn"
                disabled={excelBusy}
                title="Per-part cost-split workbook — Summary, Ops, Holes, Features and Cost Library sheets (.xlsx). On a weldment the first click computes any missing per-part plans."
                onClick={() => void exportExcel()}
              >
                {excelBusy ? "Building…" : "⭳ Export Excel"}
              </button>
            )}
            {analysis && (
              <button className="btn primary" onClick={() => setQuoteOpen(true)}>Prepare Quote</button>
            )}
            {costPanelOpen && (
              <CostLibraryPanel
                profile={costingProfile}
                currency={sym}
                partHoles={
                  (selectedGroup && scopedEstCore ? scopedEstCore : estCore)
                    ?.rcInfo?.holes ?? null
                }
                onClose={() => setCostPanelOpen(false)}
                onChanged={() => setCostingNonce((n) => n + 1)}
              />
            )}
            {analysis && (
              <QuoteModal
                open={quoteOpen}
                onClose={() => setQuoteOpen(false)}
                quote={(() => {
                  // Weldment job: quote the Assembly job ledger — only when it
                  // is COMPLETE (all part groups planned) or post-weld-only,
                  // never a misleadingly low partial sum.
                  if (rollup && assemblyMode === "assembled") {
                    return {
                      partName: analysis.filename,
                      qty: rollup.NA,
                      unitAmount: rollup.assembledTotal / rollup.NA,
                    };
                  }
                  if (rollup && assemblyMode === "parts" && rollup.ready) {
                    return {
                      partName: analysis.filename,
                      qty: rollup.NA,
                      unitAmount: rollup.total / rollup.NA,
                    };
                  }
                  // Batch-aware quote: setup components (setup time cost +
                  // per-setup charges) are amortized over the batch quantity;
                  // at qty 1 this is exactly the legacy routed total.
                  const N = Math.max(1, Math.floor(qty) || 1);
                  if (!routeCalc || !strategy || !estCore || N === 1) {
                    return { partName: analysis.filename, qty: N, unitAmount: routeCalc?.total ?? 0 };
                  }
                  const adj = exclusionAdjusted(strategy.setups, strategy.totals);
                  const setupOnce =
                    (adj.setupMin / 60) * rateHr * estCore.machMult + estCore.setupsCost;
                  const unit =
                    (Math.max(routeCalc.subtotal - setupOnce, 0) + setupOnce / N) *
                    (1 + marginPct / 100);
                  return { partName: analysis.filename, qty: N, unitAmount: unit };
                })()}
              />
            )}
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".step,.stp"
            multiple
            style={{ display: "none" }}
            onChange={onFile}
          />
        </div>

        {view === "shop" && (
          <div style={{ flex: 1, overflowY: "auto", padding: "28px 36px" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 18 }}>
              <h1 style={{ fontSize: 20, fontWeight: 600, margin: 0, flex: 1 }}>
                My Shop — Machines &amp; Rate Cards
              </h1>
              {/* SHOP-4: one shop file — full backup/restore of machines,
                  rate cards and the my-machines selection. */}
              <button
                className="btn"
                title="Download your whole shop setup (machines, rate cards, selection) as one JSON file"
                onClick={() => {
                  const text = exportShopFile(
                    loadProfiles(), customMachines, [...myMachines],
                  );
                  const blob = new Blob([text], { type: "application/json" });
                  const url = URL.createObjectURL(blob);
                  const a = document.createElement("a");
                  a.href = url;
                  a.download = "my_shop_library.json";
                  a.click();
                  URL.revokeObjectURL(url);
                }}
              >
                ⭳ Export shop file
              </button>
              <button
                className="btn"
                title="Restore a shop file (replaces rate cards, custom machines and the my-machines selection)"
                onClick={() => document.getElementById("shop-import-input")?.click()}
              >
                Import…
              </button>
              <input
                id="shop-import-input"
                type="file"
                accept=".json,application/json"
                style={{ display: "none" }}
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  e.target.value = "";
                  if (!f) return;
                  const reader = new FileReader();
                  reader.onload = () => {
                    const res = importShopFile(String(reader.result || ""));
                    if (!res.ok) {
                      setError(`Shop file import failed: ${res.error}`);
                      return;
                    }
                    saveProfiles(res.data.profiles);
                    setCustomMachines(res.data.customMachines);
                    lsSet("cnc.customMachines", JSON.stringify(res.data.customMachines));
                    setMyMachines(new Set(res.data.myMachines));
                    lsSet("cnc.myMachines", JSON.stringify(res.data.myMachines));
                    setCostingNonce((n) => n + 1);
                    if (res.warnings.length)
                      window.alert(
                        "Imported with warnings:\n" + res.warnings.join("\n"),
                      );
                  };
                  reader.readAsText(f);
                }}
              />
            </div>
            <ShopLibrary
              machines={machines}
              customMachines={customMachines}
              myMachines={myMachines}
              onToggleMyMachine={toggleMyMachine}
              onAddCustomMachine={addCustomMachine}
              onUpdateCustomMachine={updateCustomMachine}
              currency={sym}
              profilesNonce={costingNonce}
              onProfilesChanged={() => setCostingNonce((n) => n + 1)}
            />
          </div>
        )}
        {view === "projects" && (
          <div style={{ flex: 1, overflowY: "auto", padding: "28px 36px" }}>
            <h1 style={{ fontSize: 20, fontWeight: 600, margin: "0 0 18px" }}>Projects</h1>
            <div className="project-group">
              <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>Samples</div>
              <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 14 }}>
                Bundled demo parts — click to analyse
              </div>
              <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                <div className="part-card" id="card-sample" onClick={loadSample}>
                  <div className="thumb">
                    <span className="body-badge">28 Bodies</span>
                    <svg viewBox="0 0 120 70" width="100" aria-hidden="true">
                      <polygon points="12,42 78,24 108,38 42,58" fill="#3a4048" stroke="#565e68" />
                      <polygon points="12,42 42,58 42,66 12,50" fill="#2e343b" stroke="#565e68" />
                      <polygon points="42,58 108,38 108,46 42,66" fill="#333940" stroke="#565e68" />
                    </svg>
                  </div>
                  <div className="card-name">3100171001_01 SLIDE BASE-1812</div>
                  <div className="card-sub">Weldment · uploaded sample</div>
                </div>
                <div className="part-card upload" onClick={() => fileRef.current?.click()}>
                  <div style={{ fontSize: 26, color: "var(--text-2)" }}>+</div>
                  <div className="card-sub">Upload STEP (one or many)</div>
                </div>
              </div>
            </div>

            {uploadedParts.length > 0 && (
              <div className="project-group" style={{ marginTop: 18 }}>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>
                  Your uploads ({uploadedParts.length})
                </div>
                <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 14 }}>
                  Uploaded this session — click a part to analyse it
                </div>
                <div style={{ display: "flex", gap: 14, flexWrap: "wrap" }}>
                  {uploadedParts.map((f, i) => (
                    <div
                      className="part-card"
                      key={`${f.name}:${f.size}:${i}`}
                      onClick={() => void runAnalysis(f)}
                      title={f.name}
                    >
                      <div className="thumb">
                        <svg viewBox="0 0 120 70" width="100" aria-hidden="true">
                          <polygon points="16,44 80,26 104,40 40,58" fill="#3a4048" stroke="#565e68" />
                          <polygon points="16,44 40,58 40,66 16,52" fill="#2e343b" stroke="#565e68" />
                          <polygon points="40,58 104,40 104,48 40,66" fill="#333940" stroke="#565e68" />
                        </svg>
                      </div>
                      <div className="card-name">{f.name.replace(/\.(step|stp)$/i, "")}</div>
                      <div className="card-sub">
                        {(f.size / 1024).toFixed(0)} KB · click to analyse
                      </div>
                    </div>
                  ))}
                  <div
                    className="part-card upload"
                    onClick={() => fileRef.current?.click()}
                  >
                    <div style={{ fontSize: 26, color: "var(--text-2)" }}>+</div>
                    <div className="card-sub">Add more</div>
                  </div>
                </div>
              </div>
            )}
          </div>
        )}

        {view === "part" && (
        <div style={{ flex: 1, display: "flex", minHeight: 0, minWidth: 0 }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0, minHeight: 0 }}>
            <div style={{ flex: 1, position: "relative", background: "var(--canvas-bg)", minWidth: 0, minHeight: 0, overflow: "hidden" }}>
              {!analysis && !loading && (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <div className="upload-zone">
                    <div style={{ fontSize: 15, color: "var(--text-0)", marginBottom: 8 }}>
                      Upload a STEP file to begin
                    </div>
                    <div style={{ fontSize: 13, marginBottom: 20 }}>
                      Feature detection, machinability, and machining strategy — no CAD needed.
                    </div>
                    <button className="btn primary" onClick={() => fileRef.current?.click()}>
                      Choose file
                    </button>
                    <div style={{ marginTop: 14, fontSize: 12 }}>
                      or{" "}
                      <a id="load-sample" onClick={loadSample} style={{ color: "var(--accent)", cursor: "pointer" }}>
                        load the SLIDE BASE sample
                      </a>
                    </div>
                  </div>
                </div>
              )}
              {loading && (
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center" }}>
                  <AnalyzingStages />
                </div>
              )}
              {analysis && !loading && (
                <PartViewer
                  // Remount on scope change so Bounds re-fits the camera to the
                  // isolated body (PartViewer itself needs no changes).
                  key={selectedGroupId ?? "assembly"}
                  mesh={selectedGroup ? selectedGroup.mesh : analysis.mesh}
                  // Highlights always come from the plan currently on screen —
                  // scoped plans emit raw-CAD geo, the same frame as body meshes,
                  // so markers land correctly on the isolated body too.
                  highlight={highlight}
                  // Exact faces of the selected op's feature (raw-CAD frame).
                  // When present, PartViewer drapes them on the surface and
                  // skips the approximate marker.
                  faceMeshes={selFaceMeshes}
                  theme={theme}
                  // Setup orientation applies to the whole-assembly view only
                  // (the Setups list is a whole-assembly analysis).
                  cameraDir={selectedGroup ? null : setupView.dir}
                  // Re-orient the part so the active setup's machined face
                  // points up (cutter from the top) — like Toolpath. Applies
                  // to the scoped body view too (where the user works).
                  orientTo={selOpData || activeSetup ? fixtureCtx.toolAxis : null}
                  focus={opFocus}
                  // Per-op cone (from the op's real entry direction) wins; the
                  // setup-level cone is the fallback for the whole-assembly
                  // Setups view when no single op is selected.
                  approach={opApproach ?? (selectedGroup ? null : setupView.approach)}
                  opacity={viewerOpacity}
                  // Workholding visuals follow the active setup — whole-assembly
                  // view only, same guard as the orientation/cone above.
                  workholding={
                    // Show the fixture when the Fixture layer is on OR a
                    // whole-assembly setup is active; it clamps clear of the
                    // active machined face (fixtureCtx.toolAxis).
                    layers.fixture || (!selectedGroup && !!activeSetup)
                      ? {
                          flip: fixtureCtx.flip,
                          toolAxis: fixtureCtx.toolAxis,
                          method: fixtureCtx.method,
                          clearFace: fixtureCtx.facing,
                        }
                      : null
                  }
                  pickFeatures={pickFeatures}
                  excludedSet={excluded}
                  onToggleExcluded={toggleFeatureExcluded}
                  onSelectFeature={(id) => {
                    const pf = pickFeatures.find((p) => p.id === id);
                    if (!pf) return;
                    setSelOp(pf.opId);
                    setHighlight(pf.hl);
                  }}
                  selectedId={selOpData ? opFeatureKey(selOpData) : null}
                  layers={layers}
                  stockAllowance={analysis.stock?.allowance_mm ?? 5}
                />
              )}
              {analysis && !loading && selectedGroup && !selectedGroup.mesh && (
                <div style={{ position: "absolute", inset: 0, display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-2)", fontSize: 13, pointerEvents: "none" }}>
                  No preview mesh available for this body group
                </div>
              )}
              {analysis && (
                <div style={{ position: "absolute", bottom: 10, left: 12, fontSize: 11, color: "var(--text-2)" }}>
                  {selectedGroup
                    ? `${scopeLabel(selectedGroup)} · ${groupDims(selectedGroup)} mm · drag to orbit`
                    : `${analysis.dimensions_mm.length} × ${analysis.dimensions_mm.width} × ${analysis.dimensions_mm.height} mm · drag to orbit`}
                </div>
              )}
              {analysis && !loading && (
                <div className="viewer-layers" title="Scene layers">
                  {([
                    ["grid", "Grid"],
                    ["dims", "Dims"],
                    ["stock", "Stock"],
                    ["fixture", "Fixture"],
                  ] as [keyof ViewerLayers, string][]).map(([k, label]) => (
                    <button
                      key={k}
                      type="button"
                      className={`layer-chip${layers[k] ? " on" : ""}`}
                      onClick={() => toggleLayer(k)}
                      title={`Toggle ${label.toLowerCase()}`}
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
              {analysis && !loading && (
                <div className="viewer-opacity" title="Part opacity">
                  <span>Opacity</span>
                  <input
                    type="range"
                    min={0.2}
                    max={1}
                    step={0.05}
                    value={viewerOpacity}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setViewerOpacity(v);
                      lsSet("cnc.viewerOpacity", String(v));
                    }}
                  />
                </div>
              )}
              {/* Op detail panel — floats over the canvas' left side while a
                  strategy op is selected. key remounts it per op so the
                  editable spindle/feed reset to the op's planned values. */}
              {analysis && !loading && tab === "strategy" && selOpData && (
                <OpPanel
                  key={selOp}
                  op={selOpData}
                  onClose={() => {
                    setSelOp(null);
                    setHighlight(null);
                  }}
                />
              )}
            </div>
            {analysis && (
              <BottomPanel
                candidates={featureTableRows}
                excluded={excluded}
                onToggleExcluded={toggleFeatureExcluded}
                onBulkExcluded={bulkExcluded}
              />
            )}
          </div>

          {analysis && (
            <div className="inspector-wrap" style={{ width: inspCollapsed ? 24 : inspWidth }}>
              {inspCollapsed ? (
                <button className="insp-strip" title="Expand inspector" onClick={() => setInspectorCollapsed(false)}>
                  ◂
                </button>
              ) : (
                <>
                  <div
                    className={`insp-handle ${dragging ? "dragging" : ""}`}
                    title="Drag to resize · double-click to collapse"
                    onPointerDown={onHandleDown}
                    onPointerMove={onHandleMove}
                    onPointerUp={onHandleUp}
                    onPointerCancel={onHandleUp}
                    onDoubleClick={() => setInspectorCollapsed(true)}
                  />
                  <button className="insp-collapse" title="Collapse inspector" onClick={() => setInspectorCollapsed(true)}>
                    ▸
                  </button>
                  <div className="inspector">
                    {tab === "overview" && (
                      <>
                        {wmResult && wmResult.groups.length > 1 && (
                          <>
                            <div className="section-title">Weldment — how will you machine it?</div>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "2px 0 6px" }}>
                              <button
                                className="btn"
                                style={assemblyMode === "parts" ? { outline: "2px solid #4a9eff" } : undefined}
                                onClick={() => setAssemblyMode("parts")}
                                title="Machine each part, weld, then finish — full job ledger with per-part plans"
                              >
                                Build part-by-part
                              </button>
                              <button
                                className="btn"
                                style={assemblyMode === "assembled" ? { outline: "2px solid #4a9eff" } : undefined}
                                onClick={() => setAssemblyMode("assembled")}
                                title="The weldment arrives already welded — only surface operations (facing, cleanup) apply"
                              >
                                Already welded — surface ops only
                              </button>
                            </div>
                            {assemblyMode === null && (
                              <div className="scope-note" style={{ marginBottom: 8 }}>
                                Pick one — it decides what the Strategy and Estimate show
                                for this assembly.
                              </div>
                            )}
                          </>
                        )}
                        <div className="row">
                          <span className="k">Workpieces to build</span>
                          <input
                            className="num-input" type="number" min={1} value={qty}
                            onChange={(e) => setQty(Math.max(1, Math.floor(+e.target.value) || 1))}
                            title="Multiplies the whole job — 10 assemblies × 2 flanges = 20 flanges through the shop"
                          />
                        </div>
                        <MaterialSelect
                          materials={materials}
                          customMaterials={customMaterials}
                          value={material}
                          onChange={changeMaterial}
                          onAddCustom={addCustomMaterial}
                          disabled={loading || (materials.length === 0 && customMaterials.length === 0)}
                        />
                        <MachineSelect
                          machines={filterMy(machines, machineSel)}
                          customMachines={filterMy(customMachines, machineSel)}
                          value={machineSel}
                          onChange={changeMachine}
                          onAddCustom={addCustomMachine}
                          disabled={loading || (machines.length === 0 && customMachines.length === 0)}
                        />

                        {/* Stock config — manual sizes replace the stock volume
                            behind the Estimate material line */}
                        <div className="row">
                          <span className="k">Stock mode</span>
                          <select
                            className="mini-select"
                            value={stockMode}
                            disabled={!analysis.stock}
                            onChange={(e) =>
                              setStockMode(e.target.value === "manual" ? "manual" : "auto")
                            }
                          >
                            <option value="auto">Automatic</option>
                            <option value="manual">Manual</option>
                          </select>
                        </div>
                        <div className="row">
                          <span className="k">Stock preset</span>
                          <select
                            className="mini-select"
                            disabled
                            style={{ maxWidth: 170 }}
                            title={analysis.stock?.preset}
                          >
                            <option>{analysis.stock?.preset ?? "—"}</option>
                          </select>
                        </div>
                        {stockMode === "manual" && manualStock ? (
                          <div className="stock-dims" title="Manual stock size (mm)">
                            {(["length", "width", "height"] as const).map((k, i) => (
                              <label className="stock-dim" key={k}>
                                {"LWH"[i]}
                                <input
                                  className="num-input"
                                  type="number"
                                  min={0}
                                  value={manualStock[k]}
                                  onChange={(e) =>
                                    setManualStock({ ...manualStock, [k]: numOr0(e.target.value) })
                                  }
                                />
                              </label>
                            ))}
                          </div>
                        ) : (
                          <div className="row">
                            <span className="k">Stock size</span>
                            <span className="v">
                              {analysis.stock
                                ? `${fmtNum(analysis.stock.size_mm.length)} × ${fmtNum(analysis.stock.size_mm.width)} × ${fmtNum(analysis.stock.size_mm.height)} mm`
                                : "—"}
                            </span>
                          </div>
                        )}

                        {/* Assembly-level metrics hide under a body scope — honest
                            labeling: the DFM score is whole-assembly only. */}
                        {!selectedGroup && (
                          <div className="metric-grid">
                            <div className="metric">
                              <div className="label">Features plannable</div>
                              <div
                                className="value"
                                title={
                                  analysis.machinable_surface_detail?.plannable_pct != null
                                    ? `Validated per-body walk: ${analysis.machinable_surface_detail.feature_totals?.plannable ?? "—"} of ${analysis.machinable_surface_detail.feature_totals?.total ?? "—"} classified features plan with the current tool library`
                                    : analysis.is_multibody
                                      ? "Whole-assembly grade from the raw detector — noisy on weldments. Scope to a body (Bodies list) for the validated per-body figure."
                                      : "Share of detected features whose operations plan cleanly with the current tools + machine"
                                }
                              >
                                {analysis.machinable_surface_detail?.plannable_pct != null ? (
                                  <span className={`badge ${msaClass(analysis.machinable_surface_detail.plannable_pct)}`}>
                                    {analysis.machinable_surface_detail.plannable_pct}%
                                  </span>
                                ) : (
                                  <span className={`badge ${gradeClass(analysis.dfm.grade)}`}>
                                    {analysis.dfm.score_pct}% {analysis.dfm.grade}
                                    {analysis.is_multibody ? " (assembly)" : ""}
                                  </span>
                                )}
                              </div>
                            </div>
                            <div className="metric">
                              <div className="label">Bodies</div>
                              <div className="value">{analysis.topology.solids}</div>
                            </div>
                            <div className="metric">
                              <div className="label">Machinable surface</div>
                              <div
                                className="value"
                                title={
                                  analysis.machinable_surface_detail
                                    ? "Validated per-body surface walk" +
                                      (analysis.machinable_surface_detail.exclusions.length
                                        ? "\nExcluded:\n" +
                                          analysis.machinable_surface_detail.exclusions.join("\n")
                                        : " — no exclusions")
                                    : "Face-area share of features whose planning is blocked"
                                }
                              >
                                {analysis.machinable_surface_pct != null ? (
                                  <span className={`badge ${msaClass(analysis.machinable_surface_pct)}`}>
                                    {analysis.machinable_surface_pct}%
                                  </span>
                                ) : (
                                  "—"
                                )}
                              </div>
                            </div>
                          </div>
                        )}

                        {renderBodiesSection()}

                        {selectedGroup && (
                          <>
                            <div className="section-title">
                              Scoped body — {titleCase(selectedGroup.classification)} ×{selectedGroup.quantity}
                            </div>
                            <div className="row"><span className="k">Bodies</span><span className="v">{bodyLabel(selectedGroup)}</span></div>
                            <div className="row"><span className="k">Dimensions</span><span className="v">{groupDims(selectedGroup)} mm</span></div>
                            <div className="row"><span className="k">Volume</span><span className="v">{fmtVolCm3(selectedGroup.volume_cm3)}{selectedGroup.quantity > 1 ? " /pc" : ""}</span></div>
                            <div className="row" title={`Per body = volume × ${partDensity} g/cm³ (same density as the Estimate tab).`}><span className="k">Mass</span><span className="v">{fmtMass(selectedGroup.volume_cm3 * partDensity)}{selectedGroup.quantity > 1 ? " /pc" : ""}</span></div>
                            {selectedGroup.machined_area_cm2 != null && (
                              <div className="row" title="Machinable surface area of this body."><span className="k">Machined area</span><span className="v">{fmtAreaCm2(selectedGroup.machined_area_cm2)}</span></div>
                            )}
                            <div className="row"><span className="k">Faces</span><span className="v">{selectedGroup.faces}</span></div>
                            <div className="row"><span className="k">Machining</span><span className="v">{fmtNum(selectedGroup.machining_min_per_pc)} min/pc</span></div>

                            <div className="section-title">Features</div>
                            {selectedGroup.features.length === 0 && (
                              <div style={{ fontSize: 12, color: "var(--text-2)", padding: "6px 0" }}>
                                No machined features detected on this body
                              </div>
                            )}
                            {selectedGroup.features.map((f, n) => (
                              <div className="setup-row" key={n} title={f.note}>
                                <div className="setup-line">
                                  <span className="k">{f.feature_type} ×{f.count}</span>
                                </div>
                                {f.note && <div className="setup-sub" style={{ textAlign: "left" }}>{f.note}</div>}
                              </div>
                            ))}

                            {selectedGroup.operations.length > 0 && (
                              <>
                                <div className="section-title">Operations</div>
                                {selectedGroup.operations.map((o, n) => (
                                  <div className="setup-row" key={n} title={o.note}>
                                    <div className="setup-line">
                                      <span className="k">{o.operation}</span>
                                      <span className="v">{o.tool_type}</span>
                                    </div>
                                    {o.note && <div className="setup-sub" style={{ textAlign: "left" }}>{o.note}</div>}
                                  </div>
                                ))}
                              </>
                            )}

                            {/* Whole-assembly setups stay visible under a body
                                scope — operators must always see setups. */}
                            {renderSetupsSection()}
                            {renderHolesSection()}
                          </>
                        )}

                        {!selectedGroup && (
                          <>
                            <div className="section-title">General</div>
                            <div className="row"><span className="k">Machine type</span><span className="v">3 Axis</span></div>
                            <div className="row"><span className="k">Material</span><span className="v" style={{ textAlign: "right" }}>{analysis.material}</span></div>
                            <div className="row"><span className="k">Parser</span><span className="v">{analysis.parser}</span></div>

                            {/* Part envelope (was "Stock" pre-stock-block; real
                                stock config now lives under Cut config above) */}
                            <div className="section-title">Part envelope</div>
                            <div className="stock-dims">
                              <label className="stock-dim">
                                L<input className="num-input" readOnly value={analysis.dimensions_mm.length ?? ""} />
                              </label>
                              <label className="stock-dim">
                                W<input className="num-input" readOnly value={analysis.dimensions_mm.width ?? ""} />
                              </label>
                              <label className="stock-dim">
                                H<input className="num-input" readOnly value={analysis.dimensions_mm.height ?? ""} />
                              </label>
                            </div>
                            <div className="row"><span className="k">Part volume</span><span className="v">{fmtVolCm3(analysis.reporting?.volume_cm3 ?? analysis.volumes_cm3.part)}</span></div>
                            <div className="row" title="Machinable surface area that will be machined (cm² counterpart of the Machinable surface %)."><span className="k">Machined area</span><span className="v">{fmtAreaCm2(analysis.reporting?.machined_area_cm2_total)}</span></div>
                            <div className="row" title={`Finished-part mass = part volume × ${partDensity} g/cm³ (same density as the Estimate tab).`}><span className="k">Part mass</span><span className="v">{fmtMass((analysis.reporting?.volume_cm3 ?? analysis.volumes_cm3.part ?? 0) * partDensity)}</span></div>

                            {renderSetupsSection()}
                            {renderHolesSection()}

                            <div className="section-title">Topology</div>
                            <div className="row"><span className="k">Faces</span><span className="v">{analysis.topology.faces}</span></div>
                            <div className="row"><span className="k">Detected features</span><span className="v">{analysis.candidate_count}</span></div>

                            {analysis.dfm.issues.length > 0 && (
                              <>
                                <div className="section-title">Machinability issues</div>
                                {analysis.dfm.issues.slice(0, 8).map((iss, n) => (
                                  <div className="row" key={n}>
                                    <span className="k">{iss.feature}</span>
                                    <span className="v" style={{ color: iss.severity === "blocked" ? "var(--red)" : "var(--amber)" }}>
                                      {iss.severity}
                                    </span>
                                  </div>
                                ))}
                              </>
                            )}
                          </>
                        )}
                      </>
                    )}

                    {tab === "strategy" && (
                      <>
                        {selectedGroup && (
                          <div className="scope-head">
                            Scoped to {scopeLabel(selectedGroup)}
                            {stratForView
                              ? `: ${stratForView.scoped_candidate_count ?? 0} candidates`
                              : ""}
                          </div>
                        )}
                        {selectedGroup && !stratForView && scopedLoading && (
                          <div style={{ fontSize: 12, color: "var(--text-2)", padding: "6px 0" }}>
                            Planning scoped strategy…
                          </div>
                        )}
                        {selectedGroup && !stratForView && !scopedLoading && scopedError && (
                          <div className="row" style={{ borderBottom: "none" }}>
                            <span className="k" style={{ color: "var(--red)" }}>{scopedError}</span>
                            <button
                              className="btn"
                              style={{ padding: "3px 10px", fontSize: 11 }}
                              onClick={() => setScopedRetryNonce((n) => n + 1)}
                            >
                              Retry
                            </button>
                          </div>
                        )}
                        {stratForView && (
                          <>
                            {(stratForView.basis ||
                              stratForView.hole_stats ||
                              stratForView.features_plannable_pct != null ||
                              stratForView.body_feature_counts) ? (
                              <div className="chip-row">
                                {stratForView.basis && (
                                  <span
                                    className="chip"
                                    title={
                                      stratForView.basis === "grouped"
                                        ? "Grouped basis — duplicate detections deduped; one op per physical feature"
                                        : "Raw basis — every detection planned; most conservative"
                                    }
                                  >
                                    {stratForView.basis === "grouped"
                                      ? `Physical features: ${stratForView.planned_candidate_count ?? "—"}`
                                      : `Raw detections: ${stratForView.planned_candidate_count ?? "—"}`}
                                  </span>
                                )}
                                {stratForView.hole_stats && (
                                  <>
                                    <span
                                      className="chip"
                                      title="Hole census from validated geometry — threaded stays 0 until thread detection ships"
                                    >
                                      {stratForView.hole_stats.threaded} of {stratForView.hole_stats.total} holes threaded
                                      {(stratForView.hole_stats.likely_threaded ?? 0) > 0 &&
                                        ` (${stratForView.hole_stats.likely_threaded} likely ${(stratForView.hole_stats.likely_taps ?? []).join("/")})`}
                                    </span>
                                    <span className="chip-sub">
                                      {stratForView.hole_stats.through} thru · {stratForView.hole_stats.blind} blind
                                    </span>
                                  </>
                                )}
                                {stratForView.features_plannable_pct != null && (
                                  <span
                                    className="chip"
                                    title="Share of validated features the planner produced ops for (scoped basis)"
                                  >
                                    Features plannable {fmtNum(stratForView.features_plannable_pct)}%
                                  </span>
                                )}
                                {stratForView.body_feature_counts && (
                                  <span
                                    className="chip"
                                    title="Validated typed feature counts for the scoped body"
                                  >
                                    {typedCounts(stratForView.body_feature_counts)}
                                  </span>
                                )}
                              </div>
                            ) : null}
                            <div className="row" style={{ borderBottom: "none" }}>
                              <span className="k">Total machine time</span>
                              <span className="v">
                                {exclusionAdjusted(stratForView.setups, stratForView.totals)
                                  .machineMin.toFixed(0)}{" "}
                                min
                              </span>
                            </div>
                            {!selectedGroup && wmResult && wmResult.groups.length > 1 && (
                              <div className="scope-note" style={{ margin: "6px 0 8px" }}>
                                {assemblyMode === "assembled"
                                  ? "Already-welded intent: showing SURFACE operations only (facing, chamfer/edge cleanup) — select/deselect as needed; pockets and holes inside the weldment are hidden. Change the intent on the Overview tab."
                                  : "Weldment: the plan below treats the welded assembly as ONE block — machine each part individually (click a body under Bodies) and price with the Assembly job ledger on the Estimate tab. Only post-weld ops (e.g. facing) happen at assembly level."}
                              </div>
                            )}
                            {selectedGroup && assemblyMode === "assembled" &&
                              wmResult && wmResult.groups.length > 1 && (
                              <div className="scope-note" style={{ margin: "6px 0 8px" }}>
                                Already-welded intent: this part sits inside the weldment —
                                it can't be machined individually anymore, so no operations
                                are planned for it (3D view is for inspection). Switch the
                                intent to “Build part-by-part” on the Overview tab to plan
                                this part.
                              </div>
                            )}
                            {rollupsBySetup.length === 0 && (
                              <div style={{ fontSize: 12, color: "var(--text-2)", padding: "6px 0" }}>
                                No machinable candidates in this scope
                              </div>
                            )}
                            {rollupsBySetup.map((su, si) => {
                              const isSetupOpen = openSetups[su.label] ?? (si === 0);
                              return (
                              <div
                                key={su.label}
                                className="setup-group"
                                style={{ borderLeft: `3px solid ${setupColorAt(si)}` }}
                              >
                                <div
                                  className="section-title setup-head"
                                  style={{ cursor: "pointer" }}
                                  onClick={() =>
                                    setOpenSetups((p) => ({
                                      ...p,
                                      [su.label]: !(p[su.label] ?? (si === 0)),
                                    }))
                                  }
                                >
                                  <span className="seq">{isSetupOpen ? "▾" : "▸"}</span>
                                  <span
                                    className="setup-swatch"
                                    style={{ background: setupColorAt(si) }}
                                  />
                                  Setup {si + 1} · {su.label} — {su.opCount} ops · {su.subtotal.toFixed(1)} min
                                </div>
                                {isSetupOpen && (
                                  <>
                                    {su.workholding && (
                                      <div className="setup-wh" title={su.workholding.reason}>
                                        {su.workholding.method} · {su.workholding.jaw_mode}
                                      </div>
                                    )}
                                    {su.rollups.map((r) => {
                                      if (r.ops.length === 1) return renderOpRow(su.label, r.ops[0], false);
                                      const isOpen = !!expanded[r.key];
                                      return (
                                        <div key={r.key}>
                                          <div className="op-row rollup" onClick={() => toggleRollup(r.key)}>
                                            <span
                                              className={`op-dot ${r.ops.some((o) => o.blocked) ? "red" : "green"}`}
                                              title={r.ops.some((o) => o.blocked) ? "Contains blocked ops" : "Plannable"}
                                            />
                                            <span className="seq">{isOpen ? "▾" : "▸"}</span>
                                            <div className="main">
                                              <div>{r.operation} ×{r.ops.length}</div>
                                              <div className="tool">{r.toolDisplay}</div>
                                            </div>
                                            <span className="t">{r.totalMin.toFixed(1)}m</span>
                                          </div>
                                          {isOpen && r.ops.map((op) => renderOpRow(su.label, op, true))}
                                        </div>
                                      );
                                    })}
                                  </>
                                )}
                              </div>
                              );
                            })}
                          </>
                        )}
                      </>
                    )}

                    {tab === "estimate" && strategy && estCore && (() => {
                      // All shared cost math lives in estCore (also feeds the
                      // Route tab, keeping the routed total a strict superset).
                      // Under a body scope the ledger switches to the scoped
                      // plan + body stock (scopedEstCore); Route stays whole-job.
                      const scoped = !!(selectedGroup && scopedEstCore);
                      const {
                        machineMin, presetMult, tolMult, complexity, machMult,
                        machining, stockSize, massKg, materialCost: material_, setupsCost,
                        rc: estRc, addons: estAddons, addonCost: estAddonCost,
                      } = scoped ? scopedEstCore! : estCore;
                      // Itemised rows must come from the SAME plan as the
                      // totals — scoped plan under a body scope.
                      const ledgerSetupsRaw =
                        scoped && scopedStrategy ? scopedStrategy.setups : strategy.setups;
                      const totalsRaw =
                        scoped && scopedStrategy ? scopedStrategy.totals : strategy.totals;
                      // WS-B: drop deselected features from the itemised rows and
                      // reduce the machine total by their cutting time so the
                      // breakdown reconciles to the (already reduced) machining
                      // cost. Downstream rows/downloads reuse this filtered list.
                      const adjT = exclusionAdjusted(ledgerSetupsRaw, totalsRaw);
                      const ledgerSetups = ledgerSetupsRaw
                        .map((su) => {
                          const ops = su.ops.filter((op) => !isOpExcluded(op));
                          return {
                            ...su,
                            ops,
                            subtotal_min: ops.reduce((a, op) => a + (op.cut_min || 0), 0),
                          };
                        })
                        // A fully-excluded setup vanishes from the ledger, the
                        // effort estimate and the G-code — and stops charging.
                        .filter((su) => su.ops.length > 0);
                      const totalsForView = {
                        ...totalsRaw,
                        total_machine_time_min: adjT.machineMin,
                        rapid_time_min: adjT.rapidMin,
                        tool_change_time_min: adjT.tcMin,
                        setup_time_min: adjT.setupMin,
                        num_tool_changes: adjT.tcCount,
                      };
                      // Toolpath-style: where the machining minutes go, by feature
                      // category + a tool-change line. Reconciles to `machining`.
                      // Rate-card mode prices machining at the shop's ₹/cm², so
                      // the time multipliers (preset/complexity/tolerance) don't
                      // apply — keep the reference breakdown at ×1 so it doesn't
                      // drift away from the (multiplier-free) rate-card total.
                      const machBreakdown = buildMachiningBreakdown(
                        ledgerSetups, totalsForView, rateHr, rateCardActive ? 1 : machMult,
                      );
                      const partTotal = material_ + machining; // block 1: material + machining
                      const subtotal = partTotal + setupsCost + estAddonCost;
                      const margin = subtotal * (marginPct / 100);
                      const total = subtotal + margin;
                      // ---- Batch pricing: setup TIME (in machining) and setup
                      // CHARGES are paid once per batch; material + run time
                      // (cut/rapid/tool changes) repeat per piece. Unit price
                      // therefore falls with quantity.
                      const N = Math.max(1, Math.floor(qty) || 1);
                      // Rate-card machining carries no setup-time component —
                      // only the per-setup charge is batch-fixed.
                      const setupTimeCost = estRc
                        ? 0
                        : (adjT.setupMin / 60) * rateHr * machMult;
                      // Add-ons repeat per piece (each part is plated/hardened).
                      const runCostPc =
                        Math.max(machining - setupTimeCost, 0) + material_ + estAddonCost;
                      const setupOnce = setupTimeCost + setupsCost;
                      const batchSubtotal = runCostPc * N + setupOnce;
                      const batchTotal = batchSubtotal * (1 + marginPct / 100);
                      const unitCost = batchTotal / N;
                      // Quote range: the same ledger recomputed at the
                      // competitive (×0.70) and conservative (×1.00) preset
                      // ends — complexity/tolerance stay as selected.
                      const totalAtPreset = (pm: number) => {
                        // Rate-card mode ignores the preset multiplier — machining is
                        // the fixed ₹/cm² total, so the "range" collapses to one price.
                        const mach = rateCardActive
                          ? machining
                          : (machineMin / 60) * rateHr * pm * complexity * tolMult;
                        // Add-ons are outsourced flat costs — preset-independent.
                        return (material_ + mach + setupsCost + estAddonCost) * (1 + marginPct / 100);
                      };
                      const rangeLow = totalAtPreset(PRESET_MULT.competitive);
                      const rangeHigh = totalAtPreset(PRESET_MULT.conservative);
                      const d = analysis.dimensions_mm;
                      const stockDims = stockSize
                        ? `${fmtNum(stockSize.length)} × ${fmtNum(stockSize.width)} × ${fmtNum(stockSize.height)} mm`
                        : `${d.length} × ${d.width} × ${d.height} mm`;
                      const stockTag =
                        stockSize && stockMode === "manual" && !scoped ? " (manual)" : "";
                      const materialLine =
                        `${analysis.material} stock ${stockDims}${stockTag} — ${massKg.toFixed(1)} kg @ ${sym}${matPriceKg}/kg`;
                      return (
                        <>
                          {/* Hero price — the ANSWER, first thing the user sees.
                              Weldment job total when it's ready, else this
                              part's (batch-aware) grand total. */}
                          {(() => {
                            const jobReady =
                              !scoped && rollup &&
                              (assemblyMode === "assembled" || rollup.ready);
                            // A weldment whose per-part plans aren't computed yet:
                            // the billet total treats the whole envelope as one
                            // solid block, which over-quotes the welded job — so
                            // label it "rough" and point at the compute button.
                            const roughWeldment = !scoped && !!rollup && !jobReady;
                            const heroAmt = jobReady
                              ? assemblyMode === "assembled"
                                ? rollup.assembledTotal
                                : rollup.total
                              : N > 1
                                ? unitCost
                                : total;
                            const heroLabel = jobReady
                              ? "Estimated job price"
                              : roughWeldment
                                ? "Rough estimate (whole block)"
                                : N > 1
                                  ? `Estimated price / pc (${N} pcs)`
                                  : "Estimated price";
                            const heroSub = jobReady
                              ? `${rollup.groupCount} parts · welded assembly${rollup.NA > 1 ? ` · ×${rollup.NA}` : ""}`
                              : roughWeldment
                                ? "Press “Compute exact per-part plans” for the real welded-job price"
                                : scoped && selectedGroup
                                  ? `${scopeLabel(selectedGroup)} · 1 pc`
                                  : `${analysis.material} · ${strategy.setups.length} setup${strategy.setups.length === 1 ? "" : "s"}`;
                            return (
                              <div
                                className="hero-price"
                                style={roughWeldment ? { borderColor: "#c07a2a" } : undefined}
                              >
                                <div className="hp-main">
                                  <div className="hp-label">{heroLabel}</div>
                                  <div
                                    className="hp-amount"
                                    style={roughWeldment ? { color: "#c07a2a" } : undefined}
                                  >
                                    {inr(heroAmt)}
                                  </div>
                                  <div className="hp-sub">{heroSub}</div>
                                </div>
                                {!jobReady && !roughWeldment && (
                                  <div className="hp-range">
                                    typical range<br />
                                    <b>{inr(rangeLow)}</b> – <b>{inr(rangeHigh)}</b>
                                  </div>
                                )}
                              </div>
                            );
                          })()}
                          {selectedGroup && (
                            <div className="scope-note">
                              {scoped
                                ? `Per-body estimate — ${scopeLabel(selectedGroup)}, 1 pc` +
                                  (selectedGroup.quantity > 1
                                    ? ` (assembly has ×${selectedGroup.quantity} — multiply for the set)`
                                    : "") +
                                  ". Clear the scope for the whole-assembly quote."
                                : "Scoped plan loading — showing whole-assembly estimate."}
                            </div>
                          )}
                          {/* ASSY-ROLLUP: THE number for a weldment — exact
                              per-part plans × qty + welding + post-weld ops.
                              The billet ledger below stays as reference. */}
                          {!scoped && rollup && (
                            <>
                              <div className="section-title">
                                {assemblyMode === "assembled"
                                  ? "Assembled weldment — post-weld machining only"
                                  : "Assembly job ledger — machine parts, weld, then post-weld"}
                              </div>
                              {assemblyMode === null && (
                                <div className="scope-note" style={{ marginBottom: 6 }}>
                                  How will you machine this weldment?{" "}
                                  <span
                                    style={{ cursor: "pointer", textDecoration: "underline" }}
                                    onClick={() => setAssemblyMode("parts")}
                                  >
                                    Build part-by-part
                                  </span>
                                  {" · "}
                                  <span
                                    style={{ cursor: "pointer", textDecoration: "underline" }}
                                    onClick={() => setAssemblyMode("assembled")}
                                  >
                                    Already welded — surface ops only
                                  </span>
                                </div>
                              )}
                              {assemblyMode !== "assembled" &&
                                rollup.plannedCount < rollup.groupCount && (
                                  <div className="scope-note" style={{ marginBottom: 6 }}>
                                    ⚠ Quoted {rollup.plannedCount} of {rollup.groupCount} part
                                    groups — {rollup.groupCount - rollup.plannedCount} pending.
                                    Click each body under Bodies, or press “Compute exact
                                    per-part plans” below to finish them all.
                                  </div>
                                )}
                              <div className="ledger">
                                {assemblyMode !== "assembled" && (
                                  <>
                                    {rollup.rows.map((r) => {
                                      const purch = "purchased" in r && r.purchased;
                                      return (
                                      <div
                                        className="ledger-row"
                                        key={r.g.group_id}
                                        style={purch ? { opacity: 0.6 } : undefined}
                                        title={
                                          purch
                                            ? "Marked as purchased under Bodies — supplied, not machined; no cost in this quote"
                                            : r.ready
                                              ? `Exact per-body plan × ${r.pieces} pcs — setup time + setup charges once per group`
                                              : "Not planned yet — click this body under Bodies or press “Compute exact per-part plans”"
                                        }
                                      >
                                        <span className="desc">
                                          {titleCase(r.g.classification)} ×{r.g.quantity}
                                          {rollup.NA > 1
                                            ? ` × ${rollup.NA} = ${r.pieces} pcs`
                                            : ""}
                                          {purch
                                            ? " — purchased part"
                                            : r.ready
                                              ? ` — ${fmtMin(r.minBatch)}`
                                              : " — pending"}
                                        </span>
                                        <span className="amt">
                                          {purch ? "—" : r.ready ? inr(r.costBatch) : "—"}
                                        </span>
                                      </div>
                                      );
                                    })}
                                    {weldingOff ? (
                                      <div className="ledger-row" style={{ opacity: 0.6 }}>
                                        <span className="desc">
                                          Welding — removed (parts supplied unwelded){" "}
                                          <span
                                            style={{ cursor: "pointer", textDecoration: "underline", fontSize: 11 }}
                                            title="Put welding back into the job"
                                            onClick={() => setWeldingOff(false)}
                                          >
                                            add back
                                          </span>
                                        </span>
                                        <span className="amt">—</span>
                                      </div>
                                    ) : (
                                    <div
                                      className="ledger-row"
                                      title="The analyzer's welding minutes per assembly — type your own number if you know it better, or remove welding entirely if you supply the parts unwelded"
                                    >
                                      <span className="desc" style={{ display: "flex", alignItems: "center", gap: 6 }}>
                                        Welding
                                        <input
                                          className="num-input" type="number" min={0}
                                          style={{ width: 64 }}
                                          value={Math.round(rollup.weldPerAssy * 10) / 10}
                                          onChange={(e) => {
                                            const v = parseFloat(e.target.value);
                                            setWeldMinOverride(Number.isFinite(v) && v >= 0 ? v : 0);
                                          }}
                                        />
                                        min/assembly
                                        {rollup.NA > 1 ? ` × ${rollup.NA}` : ""} @{" "}
                                        <span className="rate-val">{sym}{weldRate}/hr</span>
                                        {weldMinOverride != null && (
                                          <span
                                            style={{ cursor: "pointer", textDecoration: "underline", fontSize: 11 }}
                                            title="Back to the analyzer's welding time"
                                            onClick={() => setWeldMinOverride(null)}
                                          >
                                            reset
                                          </span>
                                        )}
                                        <button
                                          className="btn"
                                          style={{ padding: "0 6px", fontSize: 12 }}
                                          title="Remove welding — we supply the cut parts, the customer welds them"
                                          onClick={() => setWeldingOff(true)}
                                        >
                                          ✕
                                        </button>
                                      </span>
                                      <span className="amt">{inr(rollup.weldCost)}</span>
                                    </div>
                                    )}
                                  </>
                                )}
                                <div className="ledger-row">
                                  <span className="desc">
                                    Post-weld machining — {fmtMin(rollup.pwPerAssy)}/assembly
                                    {rollup.NA > 1 ? ` × ${rollup.NA} = ${fmtMin(rollup.pwTotalMin)}` : ""}
                                  </span>
                                  <span className="amt">{inr(rollup.pwCost)}</span>
                                </div>
                                {postWeld.map((r) => (
                                  <div className="ledger-row child" key={r.id}>
                                    <span className="desc">
                                      {r.name}
                                      {r.suggested ? " · suggested" : ""}
                                    </span>
                                    <span className="amt">
                                      {fmtMin(r.min)}
                                      <button
                                        title="Remove this post-weld op"
                                        onClick={() =>
                                          setPostWeld((p) => p.filter((x) => x.id !== r.id))
                                        }
                                        style={{
                                          marginLeft: 8, border: "none", background: "transparent",
                                          color: "var(--text-2)", cursor: "pointer",
                                        }}
                                      >
                                        ✕
                                      </button>
                                    </span>
                                  </div>
                                ))}
                                <div
                                  className="ledger-row child"
                                  style={{ gap: 6, alignItems: "center" }}
                                >
                                  <input
                                    className="num-input" placeholder="Add post-weld op (e.g. Line bore)"
                                    style={{ flex: 1, minWidth: 0 }}
                                    value={pwFormName}
                                    onChange={(e) => setPwFormName(e.target.value)}
                                  />
                                  <input
                                    className="num-input" placeholder="min" type="number" min={0}
                                    style={{ width: 64 }}
                                    value={pwFormMin}
                                    onChange={(e) => setPwFormMin(e.target.value)}
                                  />
                                  <button
                                    className="btn"
                                    onClick={() => {
                                      const m = parseFloat(pwFormMin);
                                      if (!pwFormName.trim() || !Number.isFinite(m) || m <= 0) return;
                                      setPostWeld((p) => [
                                        ...p,
                                        { id: `pw-c-${Date.now()}`, name: pwFormName.trim(), min: m },
                                      ]);
                                      setPwFormName("");
                                      setPwFormMin("");
                                    }}
                                  >
                                    + Add
                                  </button>
                                </div>
                                {(() => {
                                  const isAsm = assemblyMode === "assembled";
                                  const sub = isAsm ? rollup.assembledSubtotal : rollup.subtotal;
                                  const tot = isAsm ? rollup.assembledTotal : rollup.total;
                                  return (
                                    <>
                                      <div className="ledger-row subtotal">
                                        <span className="desc">Subtotal</span>
                                        <span className="amt">{inr(sub)}</span>
                                      </div>
                                      <div className="ledger-row">
                                        <span className="desc">Margin ({marginPct}%)</span>
                                        <span className="amt">{inr(tot - sub)}</span>
                                      </div>
                                      <div className="ledger-row grand">
                                        <span className="desc">
                                          {isAsm
                                            ? `Job total — post-weld only${rollup.NA > 1 ? ` (${rollup.NA} assemblies)` : ""}`
                                            : `Job total — welded assembly${rollup.NA > 1 ? ` ×${rollup.NA}` : ""}`}
                                        </span>
                                        <span className="amt">
                                          {isAsm || rollup.ready
                                            ? inr(tot)
                                            : `${inr(tot)} + pending parts`}
                                        </span>
                                      </div>
                                    </>
                                  );
                                })()}
                              </div>
                              {assemblyMode !== "assembled" && !rollup.ready && (
                                <button
                                  className="btn"
                                  style={{ marginTop: 6 }}
                                  disabled={!!rollupBusy}
                                  onClick={buildRollup}
                                  title="Runs the exact per-body plan for every part group (one pass, cached)"
                                >
                                  {rollupBusy ?? "Compute exact per-part plans"}
                                </button>
                              )}
                              {rollupErr && (
                                <div className="scope-note" style={{ marginTop: 6 }}>
                                  {rollupErr} —{" "}
                                  <span
                                    style={{ cursor: "pointer", textDecoration: "underline" }}
                                    onClick={buildRollup}
                                  >
                                    retry
                                  </span>
                                </div>
                              )}
                              <div style={{ fontSize: 11, color: "var(--text-2)", margin: "6px 0 12px" }}>
                                Per-part rows use the exact per-body classifier; setup time and
                                setup charges are paid once per group of identical parts. The
                                single-block ledger below treats the welded assembly as one
                                billet — reference only, do not quote a weldment from it.
                              </div>
                            </>
                          )}
                          <div style={{ margin: "2px 0 12px" }}>
                            <button
                              className="btn"
                              title="Print-ready internal effort sheet for whoever prices the job — opens a print dialog, Save as PDF"
                              onClick={() =>
                                openPrintDoc(
                                  effortEstimateHtml({
                                    filename: analysis.filename,
                                    // Shop letterhead — the same company block +
                                    // logo saved from the Quote modal, so the
                                    // user uploads once and both documents
                                    // carry THEIR branding.
                                    company: (() => {
                                      try {
                                        return JSON.parse(
                                          lsGet("cnc.quote.company") || "null",
                                        ) as EffortEstimateParams["company"];
                                      } catch {
                                        return null;
                                      }
                                    })(),
                                    scopeLabel:
                                      scoped && selectedGroup
                                        ? scopeLabel(selectedGroup)
                                        : "Whole assembly",
                                    machine: machineSel || strategy.machine || "",
                                    materialLine,
                                    machineMin,
                                    setupCount: ledgerSetups.length,
                                    toolChanges: totalsForView.num_tool_changes ?? 0,
                                    complexityMult: machMult,
                                    rateHr,
                                    breakdown: machBreakdown,
                                    batch: N > 1
                                      ? { qty: N, unit: unitCost, total: batchTotal, setupOnce }
                                      : null,
                                    // Weldment job section — mirrors the
                                    // Assembly job ledger (parts × qty +
                                    // welding + post-weld, or post-weld only).
                                    job:
                                      !scoped && rollup && assemblyMode
                                        ? {
                                            mode: assemblyMode,
                                            assemblies: rollup.NA,
                                            rows: rollup.rows.map((r) => ({
                                              label:
                                                titleCase(r.g.classification) +
                                                ` ×${r.g.quantity}` +
                                                ("purchased" in r && r.purchased
                                                  ? " — purchased part"
                                                  : ""),
                                              pieces: r.pieces,
                                              min: r.minBatch,
                                              cost: r.costBatch,
                                              ready: r.ready,
                                            })),
                                            weldMin: rollup.weldMin,
                                            weldCost: rollup.weldCost,
                                            pwMin: rollup.pwTotalMin,
                                            pwCost: rollup.pwCost,
                                            subtotal:
                                              assemblyMode === "assembled"
                                                ? rollup.assembledSubtotal
                                                : rollup.subtotal,
                                            margin:
                                              assemblyMode === "assembled"
                                                ? rollup.assembledTotal - rollup.assembledSubtotal
                                                : rollup.total - rollup.subtotal,
                                            total:
                                              assemblyMode === "assembled"
                                                ? rollup.assembledTotal
                                                : rollup.total,
                                          }
                                        : null,
                                    setups: ledgerSetups.map((su) => ({
                                      label: su.setup_label,
                                      ops: su.ops.length,
                                      min: su.subtotal_min,
                                    })),
                                    cost: {
                                      material: material_,
                                      machining,
                                      setups: setupsCost,
                                      subtotal,
                                      margin,
                                      marginPct,
                                      total,
                                    },
                                    addons: estAddons,
                                    flow: [
                                      "CNC Milling",
                                      !scoped && wmResult && assemblyMode !== "assembled"
                                        ? "Welding & Assembly"
                                        : null,
                                      ...estAddons.map((a) => a.name),
                                    ]
                                      .filter(Boolean)
                                      .join(" → "),
                                  }),
                                )
                              }
                            >
                              ⭳ Download Effort Estimate
                            </button>
                            <button
                              className="btn"
                              style={{ marginLeft: 8 }}
                              title="Draft starting-point program — real drilling cycles + hole positions; milling left to CAM. Verify in a simulator before running."
                              onClick={() =>
                                downloadText(
                                  `${analysis.filename.replace(/\.[^.]+$/, "")}_draft.nc`,
                                  draftGcode(
                                    ledgerSetups,
                                    machineSel || strategy.machine || "",
                                    analysis.filename,
                                  ),
                                )
                              }
                            >
                              ⭳ Draft G-code
                            </button>
                          </div>
                          <div className="section-title">Estimate settings</div>
                          {/* Currency comes FIRST — everything below prices in it. */}
                          <div className="row">
                            <span className="k">Currency</span>
                            <select
                              className="mini-select"
                              value={currencyCode}
                              onChange={(e) => {
                                setCurrencyCode(e.target.value);
                                lsSet("cnc.currencyCode", e.target.value);
                              }}
                              title="Display symbol only — enter your rates in this currency; no conversion is applied"
                            >
                              {CURRENCIES.map((c) => (
                                <option key={c.code} value={c.code}>{c.code}</option>
                              ))}
                            </select>
                          </div>
                          {/* Costing model as two cards — Time-based is the default. */}
                          {(() => {
                            const setModel = (v: "time" | "ratecard") => {
                              if (costingProfile.model === v) return;
                              updateProfile(
                                audit(
                                  { ...costingProfile, model: v },
                                  "model", costingProfile.model, v,
                                ),
                              );
                              setCostingNonce((n) => n + 1);
                            };
                            return (
                              <div style={{ display: "flex", gap: 8, margin: "6px 0" }}>
                                <div
                                  className={`model-card ${!rateCardActive ? "sel" : ""}`}
                                  title="Machine hours × your hourly rate — the classic model"
                                  onClick={() => setModel("time")}
                                >
                                  <div className="mc-name">
                                    {!rateCardActive ? "✓ " : ""}Time-based
                                  </div>
                                  <div className="mc-sub">{sym}{rateHr}/hr × machine hours</div>
                                </div>
                                <div
                                  className={`model-card ${rateCardActive ? "sel" : ""}`}
                                  title="Machined surface × ₹/cm² + per-hole prices from your rate card"
                                  onClick={() => setModel("ratecard")}
                                >
                                  <div className="mc-name">
                                    {rateCardActive ? "✓ " : ""}Rate card
                                  </div>
                                  <div className="mc-sub">
                                    {sym}/cm² + hole library
                                  </div>
                                </div>
                              </div>
                            );
                          })()}
                          {rateCardActive && (
                            <>
                              <div className="row">
                                <span className="k">Rate card</span>
                                <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                  {allRateCards.length > 1 ? (
                                    <select
                                      className="mini-select"
                                      style={{ maxWidth: 150 }}
                                      value={costingProfile.id}
                                      title="Pick which rate card prices this quote"
                                      onChange={(e) => {
                                        const id = e.target.value;
                                        setRateCardId(id);
                                        lsSet("cnc.costing.activeCard", id);
                                        const p = allRateCards.find((x) => x.id === id);
                                        // Choosing a card AS the pricing source
                                        // implies rate-card mode for it.
                                        if (p && p.model !== "ratecard")
                                          updateProfile(
                                            audit({ ...p, model: "ratecard" }, "model", p.model, "ratecard"),
                                          );
                                        setCostingNonce((n) => n + 1);
                                      }}
                                    >
                                      {allRateCards.map((p) => (
                                        <option key={p.id} value={p.id}>{p.name}</option>
                                      ))}
                                    </select>
                                  ) : (
                                    <span className="v">{costingProfile.name}</span>
                                  )}
                                  <button
                                    className="btn"
                                    title="Create a new rate card — starts as a copy of the current card's rates and hole prices"
                                    onClick={() => setNewCardName("")}
                                  >
                                    + New
                                  </button>
                                </span>
                              </div>
                              {newCardName != null && (
                                <div className="row">
                                  <span className="k">· Name the new card</span>
                                  <span style={{ display: "flex", gap: 6, alignItems: "center" }}>
                                    <input
                                      className="num-input"
                                      style={{ width: 130 }}
                                      autoFocus
                                      placeholder="e.g. HAAS VF2 / Shop B"
                                      value={newCardName}
                                      onChange={(e) => setNewCardName(e.target.value)}
                                      onKeyDown={(e) => {
                                        if (e.key === "Enter") createRateCard();
                                        if (e.key === "Escape") setNewCardName(null);
                                      }}
                                    />
                                    <button className="btn" onClick={createRateCard}>Create</button>
                                    <button className="btn" title="Cancel" onClick={() => setNewCardName(null)}>✕</button>
                                  </span>
                                </div>
                              )}
                              <div className="row">
                                <span className="k">Prices in this card</span>
                                <button className="btn" onClick={() => setCostPanelOpen(true)}>
                                  Edit rate card…
                                </button>
                              </div>
                              {estRc && estRc.estimatedCount > 0 && (
                                <div className="scope-note" style={{ color: "#c07a2a" }}>
                                  ⚠ {estRc.estimatedCount} hole price
                                  {estRc.estimatedCount > 1 ? "s are" : " is"} estimated —
                                  not confirmed by the shop. Open “Edit rate card…” to
                                  confirm or correct them.
                                </div>
                              )}
                            </>
                          )}
                          {/* ARD R4 add-on processes — flow style: pick one from
                              the dropdown, it becomes a row here, a line in the
                              Quote ledger AND a block in the Process Route. */}
                          <div className="row">
                            <span
                              className="k"
                              title="Outsourced / secondary processes from your rate-card library. Each one you add appears below (rate editable), in the Quote ledger, and as a block in the Process Route. Edit here and press Save to card to store it back in the library."
                            >
                              Add-on processes
                            </span>
                            <select
                              className="mini-select"
                              value=""
                              onChange={(e) => {
                                const v = e.target.value;
                                if (v === "__custom__") addCustomAddon();
                                else if (v) addAddonFromLib(v);
                              }}
                            >
                              <option value="">+ Add process…</option>
                              {addonLib.map((p) => (
                                <option key={p.id} value={p.id}>{p.name}</option>
                              ))}
                              <option value="__custom__">Custom (own name + rate)…</option>
                            </select>
                          </div>
                          {addonSels.map((a) => {
                            const unit =
                              a.basis === "flat" ? `${sym} flat`
                                : a.basis === "per_kg" ? `${sym}/kg`
                                  : `${sym}/cm²`;
                            return (
                              <div
                                key={a.uid}
                                style={{
                                  border: "1px solid var(--border)", borderRadius: 8,
                                  padding: "6px 8px", margin: "4px 0",
                                }}
                              >
                                <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                                  {a.procId ? (
                                    <span style={{ fontWeight: 600, fontSize: 12, flex: 1 }}>{a.name}</span>
                                  ) : (
                                    <input
                                      className="num-input"
                                      style={{ flex: 1, minWidth: 0 }}
                                      value={a.name}
                                      title="Process name — shows in the ledger, route and documents"
                                      onChange={(e) => patchAddon(a.uid, { name: e.target.value })}
                                    />
                                  )}
                                  <input
                                    className="num-input"
                                    style={{ width: 66 }}
                                    placeholder="note"
                                    value={a.param ?? ""}
                                    title="Optional note (e.g. Ni, 45 HRC, RAL 7035)"
                                    onChange={(e) => patchAddon(a.uid, { param: e.target.value })}
                                  />
                                  <button className="btn" title="Remove from this quote" onClick={() => removeAddon(a.uid)}>✕</button>
                                </div>
                                <div style={{ display: "flex", alignItems: "center", gap: 6, flexWrap: "wrap", fontSize: 11 }}>
                                  <select
                                    className="mini-select"
                                    value={a.basis}
                                    title="How this process is priced — per cm² of surface, per kg of weight, or a flat quoted amount"
                                    onChange={(e) => patchAddon(a.uid, { basis: e.target.value as AddonBasis })}
                                  >
                                    <option value="per_cm2">per cm²</option>
                                    <option value="per_kg">per kg</option>
                                    <option value="flat">flat rate</option>
                                  </select>
                                  {a.basis === "per_cm2" && (
                                    <select
                                      className="mini-select"
                                      value={a.area}
                                      title="Which surface the rate applies to"
                                      onChange={(e) => patchAddon(a.uid, { area: e.target.value as "surface" | "machined" })}
                                    >
                                      <option value="surface">external surface</option>
                                      <option value="machined">machined surface</option>
                                    </select>
                                  )}
                                  <input
                                    className="num-input"
                                    type="number"
                                    step="0.01"
                                    style={{ width: 66 }}
                                    value={a.rate}
                                    title={`Rate in ${unit}`}
                                    onChange={(e) => patchAddon(a.uid, { rate: +e.target.value || 0 })}
                                  />
                                  <span style={{ color: "var(--text-2)" }}>{unit}</span>
                                  <button
                                    className="btn"
                                    style={{ fontSize: 11, padding: "2px 8px" }}
                                    title="Save this rate into the rate-card library so it's reused on the next quote (marks it confirmed/green)"
                                    onClick={() => saveAddonToLib(a)}
                                  >
                                    Save to card
                                  </button>
                                </div>
                              </div>
                            );
                          })}
                          <div className="row">
                            <span className="k">Quantity (pcs)</span>
                            <input
                              className="num-input" type="number" min={1} value={qty}
                              onChange={(e) => setQty(Math.max(1, Math.floor(+e.target.value) || 1))}
                              title="Setup time + setup charges are paid once per batch — unit price falls as quantity rises"
                            />
                          </div>
                          <div className="row">
                            <span className="k">Machining rate ({sym}/hr)</span>
                            <input
                              className="num-input" type="number" value={rateHr}
                              onChange={(e) => setRateHr(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Setup charge ({sym})</span>
                            <input
                              className="num-input" type="number" value={setupCharge}
                              onChange={(e) => setSetupCharge(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Material ({sym}/kg)</span>
                            <input
                              className="num-input" type="number" value={matPriceKg}
                              onChange={(e) => setMatPriceKg(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Margin (%)</span>
                            <input
                              className="num-input" type="number" value={marginPct}
                              onChange={(e) => setMarginPct(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Feature basis</span>
                            <select
                              className="mini-select"
                              style={{ maxWidth: 170 }}
                              value={estBasis}
                              disabled={basisLoading}
                              title="What the plan counts: grouped physical features (duplicate detections deduped) or every raw detection"
                              onChange={(e) => changeBasis(e.target.value === "raw" ? "raw" : "grouped")}
                            >
                              <option value="grouped">Grouped — physical features (recommended)</option>
                              <option value="raw">Raw — every detection (most conservative)</option>
                            </select>
                          </div>
                          {basisLoading && (
                            <div style={{ fontSize: 11, color: "var(--text-2)", padding: "4px 0" }}>
                              Re-planning on {estBasis} basis…
                            </div>
                          )}
                          <div className="row">
                            <span className="k">Quote preset</span>
                            <span style={{ display: "flex", alignItems: "center", gap: 6 }}>
                              <select
                                className="mini-select"
                                style={{ maxWidth: 148, opacity: rateCardActive ? 0.5 : 1 }}
                                value={estPreset}
                                disabled={rateCardActive}
                                title={rateCardActive ? "Rate card active — machining is priced at ₹/cm², so this multiplier is not applied" : "Scales the machining-time cost lines only"}
                                onChange={(e) => {
                                  const v = e.target.value;
                                  changePreset(
                                    v === "standard" || v === "competitive" ? v : "conservative",
                                  );
                                }}
                              >
                                <option value="conservative">Conservative — textbook two-pass</option>
                                <option value="standard">Standard shop</option>
                                <option value="competitive">Competitive</option>
                              </select>
                              <span
                                style={{ fontSize: 11, color: "var(--text-2)", fontVariantNumeric: "tabular-nums" }}
                                title="Machining multiplier from this preset"
                              >
                                ×{presetMult.toFixed(2)}
                              </span>
                            </span>
                          </div>
                          <div className="row">
                            <span className="k">Complexity (0.8–1.5)</span>
                            <input
                              className="num-input"
                              type="number"
                              min={COMPLEXITY_MIN}
                              max={COMPLEXITY_MAX}
                              step={0.05}
                              disabled={rateCardActive}
                              style={rateCardActive ? { opacity: 0.5 } : undefined}
                              title={rateCardActive ? "Rate card active — machining is priced at ₹/cm², so complexity is not applied" : undefined}
                              value={Number.isFinite(estComplexity) ? estComplexity : ""}
                              onChange={(e) => changeComplexity(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Tolerance class</span>
                            <select
                              className="mini-select"
                              style={{ maxWidth: 170, opacity: rateCardActive ? 0.5 : 1 }}
                              value={estTolerance}
                              disabled={rateCardActive}
                              title={rateCardActive ? "Rate card active — machining is priced at ₹/cm², so tolerance is not applied" : undefined}
                              onChange={(e) => {
                                const v = e.target.value;
                                changeTolerance(
                                  v === "medium" || v === "fine" || v === "precision" ? v : "general",
                                );
                              }}
                            >
                              <option value="general">General ±0.2 mm (×1.00)</option>
                              <option value="medium">Medium ±0.1 (×1.15)</option>
                              <option value="fine">Fine ±0.05 (×1.35)</option>
                              <option value="precision">Precision (×1.60)</option>
                            </select>
                          </div>
                          <div style={{ fontSize: 11, color: rateCardActive ? "#c07a2a" : "var(--text-2)", marginTop: 6 }}>
                            {rateCardActive
                              ? "Rate card active — machining is priced at the shop's ₹/cm², so preset / complexity / tolerance do not change the total. Switch to Time-based (above) to use them."
                              : `machining ×${machMult.toFixed(2)} = preset ${presetMult.toFixed(2)} × complexity ${complexity.toFixed(2)} × tolerance ${tolMult.toFixed(2)}`}
                          </div>

                          <div className="section-title">Quote ledger</div>
                          <div className="ledger">
                            {/* Block 1 — the part: material + machining per setup */}
                            <div className="ledger-row root">
                              <span className="desc" title={analysis.filename}>{analysis.filename}</span>
                              <span className="qty">qty 1</span>
                              <span className="amt">{inr(partTotal)}</span>
                            </div>
                            <div className="ledger-row child">
                              <span className="desc" title={materialLine}>{materialLine}</span>
                              <span className="amt">{inr(material_)}</span>
                            </div>
                            {(() => {
                              // Machining sub-header + Toolpath-style breakdown by
                              // feature category, then Positioning / Tool changes /
                              // Machine setup — the four components of machineMin, so
                              // these rows sum exactly to the machining cost above.
                              const multTag = (!rateCardActive && machMult !== 1) ? ` × ${machMult.toFixed(2)}` : "";
                              const bd = machBreakdown;
                              return (
                                <>
                                  {estRc ? (
                                    <>
                                      <div className="ledger-row child">
                                        <span
                                          className="desc"
                                          title="Rate-card model: each machined surface priced once at the shop's ₹/cm² (rough + finish included in the rate)."
                                        >
                                          Milling — {estRc.millingAreaCm2.toFixed(1)} cm² @{" "}
                                          <span className="rate-val">
                                            {sym}{estRc.millingRate.toFixed(2)}/cm²
                                          </span>
                                        </span>
                                        <span className="amt">{inr(estRc.millingCost)}</span>
                                      </div>
                                      <div className="ledger-row child">
                                        <span
                                          className="desc"
                                          title={estRc.holes
                                            .map(
                                              (h) =>
                                                `${h.feature}: ${inr(h.cost)} (${h.note})`,
                                            )
                                            .join("\n")}
                                          style={
                                            estRc.estimatedCount > 0
                                              ? { color: "#c07a2a" }
                                              : undefined
                                          }
                                        >
                                          Holes — {estRc.holes.length} from library
                                          {estRc.estimatedCount > 0
                                            ? ` · ⚠ ${estRc.estimatedCount} estimated`
                                            : ""}
                                        </span>
                                        <span className="amt">{inr(estRc.holeCost)}</span>
                                      </div>
                                    </>
                                  ) : (
                                  <div className="ledger-row child">
                                    <span
                                      className="desc"
                                      title={`Machining — ${fmtMin(machineMin)} @ ${sym}${rateHr}/hr${multTag}. Broken down by feature category below; positioning, tool changes and machine setup are the remaining time components.`}
                                    >
                                      Machining — {fmtMin(machineMin)} @{" "}
                                      <span className="rate-val">{sym}{rateHr}/hr{multTag}</span>
                                    </span>
                                    <span className="amt">{inr(machining)}</span>
                                  </div>
                                  )}
                                  {bd.categories.map((c) => (
                                    <div className="ledger-row grandchild" key={c.key}>
                                      <span className="desc">
                                        {c.label} <span className="mut">×{c.count}</span> — {fmtDur(c.min)}
                                      </span>
                                      <span className="amt">{inr(c.cost)}</span>
                                    </div>
                                  ))}
                                  {/* Overhead rows are gated on cost/min, never on
                                      count — so a row that carries an allocated
                                      rupee is never hidden and the visible rows
                                      always sum to the Machining header. */}
                                  {(bd.rapid.cost > 0 || bd.rapid.min > 0.001) && (
                                    <div className="ledger-row grandchild">
                                      <span className="desc">Positioning &amp; rapids — {fmtDur(bd.rapid.min)}</span>
                                      <span className="amt">{inr(bd.rapid.cost)}</span>
                                    </div>
                                  )}
                                  {(bd.toolChanges.cost > 0 || bd.toolChanges.min > 0.001) && (
                                    <div className="ledger-row grandchild">
                                      <span className="desc">
                                        Tool changes{bd.toolChanges.count > 0 && (
                                          <span className="mut"> ×{bd.toolChanges.count}</span>
                                        )} — {fmtDur(bd.toolChanges.min)}
                                      </span>
                                      <span className="amt">{inr(bd.toolChanges.cost)}</span>
                                    </div>
                                  )}
                                  {(bd.machineSetup.cost > 0 || bd.machineSetup.min > 0.001) && (
                                    <div className="ledger-row grandchild">
                                      <span className="desc">Machine setup &amp; load — {fmtDur(bd.machineSetup.min)}</span>
                                      <span className="amt">{inr(bd.machineSetup.cost)}</span>
                                    </div>
                                  )}
                                </>
                              );
                            })()}

                            {/* Block 2 — per-setup fixed charges */}
                            <div className="ledger-row root">
                              <span className="desc">Setup Charges</span>
                              <span className="qty">× {ledgerSetups.length}</span>
                              <span className="amt">{inr(setupsCost)}</span>
                            </div>
                            {ledgerSetups.map((su) => (
                              <div className="ledger-row child" key={su.setup_label}>
                                <span className="desc">Setup · {su.setup_label}</span>
                                <span className="amt">{inr(setupCharge)}</span>
                              </div>
                            ))}

                            {/* Block 3 — ARD R4 add-on processes (per piece) */}
                            {estAddons.length > 0 && (
                              <>
                                <div className="ledger-row root">
                                  <span
                                    className="desc"
                                    title="Outsourced / secondary processes from the rate card's add-on rates — repeat per piece"
                                  >
                                    Add-on Processes
                                  </span>
                                  <span className="qty">× {estAddons.length}</span>
                                  <span className="amt">{inr(estAddonCost)}</span>
                                </div>
                                {estAddons.map((a) => (
                                  <div className="ledger-row child" key={a.name}>
                                    <span className="desc">{a.name}</span>
                                    <span className="amt">{inr(a.cost)}</span>
                                  </div>
                                ))}
                              </>
                            )}

                            {/* Footer */}
                            <div className="ledger-row subtotal">
                              <span className="desc">Subtotal</span>
                              <span className="amt">{inr(subtotal)}</span>
                            </div>
                            <div className="ledger-row">
                              <span className="desc">Margin ({marginPct}%)</span>
                              <span className="amt">{inr(margin)}</span>
                            </div>
                            <div className="ledger-row grand">
                              <span className="desc">Grand Total</span>
                              <span className="amt">{inr(total)}</span>
                            </div>
                            {/* Never quote blind: the competitive→conservative
                                spread for this part, at the selected
                                complexity/tolerance */}
                            <div
                              className="ledger-row range"
                              title="Grand total recomputed at the Competitive (×0.70) and Conservative (×1.00) presets — complexity and tolerance as selected"
                            >
                              <span className="desc">Range</span>
                              <span className="amt">{inr(rangeLow)} — {inr(rangeHigh)}</span>
                            </div>
                            {/* Batch pricing: setup time + setup charges are paid
                                once per batch, so the unit price falls with qty. */}
                            {N > 1 && (
                              <>
                                <div className="ledger-row subtotal">
                                  <span className="desc">Batch — {N} pcs</span>
                                  <span className="amt"></span>
                                </div>
                                <div className="ledger-row child"
                                  title="Setup time cost + per-setup charges — paid once for the whole batch">
                                  <span className="desc">Setup (time + charges) — once</span>
                                  <span className="amt">{inr(setupOnce)}</span>
                                </div>
                                <div className="ledger-row child"
                                  title="Material + cutting/rapid/tool-change time — repeats every piece">
                                  <span className="desc">Per-piece run (material + machining)</span>
                                  <span className="amt">{inr(runCostPc)}</span>
                                </div>
                                <div className="ledger-row grand"
                                  title={`Setup amortized over ${N} pcs — was ${inr(total)} at 1 pc`}>
                                  <span className="desc">Unit price ({N} pcs)</span>
                                  <span className="amt">{inr(unitCost)}</span>
                                </div>
                                <div className="ledger-row grand">
                                  <span className="desc">Batch total</span>
                                  <span className="amt">{inr(batchTotal)}</span>
                                </div>
                              </>
                            )}
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 8 }}>
                            {machineMin.toFixed(0)} min machine time · {strategy.setups.length} setups ·{" "}
                            {N > 1
                              ? `${N} pcs — unit ${inr(unitCost)} (${inr(total)} at 1 pc)`
                              : "per part"}
                          </div>
                          {/* This ledger prices the milling only — point at the
                              full job when the route has more processes. */}
                          {routeCalc && routeCalc.blockCount > 1 && (
                            <div
                              className="route-link"
                              title="This estimate covers CNC milling only — the Route tab adds welding/assembly, turning, and custom processes"
                              onClick={() => setTab("route")}
                            >
                              Full multi-process quote on the Route tab:{" "}
                              <b>{inr(routeCalc.total)}</b> →
                            </div>
                          )}
                        </>
                      );
                    })()}

                    {/* ---- Process Route: the multi-process/multi-machine job
                         chain. Milling comes from the strategy, welding &
                         assembly from the weldment analysis, turning is a
                         manual-quote placeholder until the lathe module, and
                         operators append their own steps. ---- */}
                    {tab === "route" && (!strategy || !estCore || !routeCalc) && (
                      <div style={{ fontSize: 12, color: "var(--text-2)", padding: "6px 0" }}>
                        Waiting for the machining strategy…
                      </div>
                    )}
                    {tab === "route" && strategy && estCore && routeCalc && (() => {
                      let blockNum = 0;
                      const num = () => ++blockNum;
                      return (
                        <>
                          {selectedGroup && (
                            <div className="scope-note">
                              The route always covers the whole job — body scope does not apply here.
                            </div>
                          )}
                          <div className="section-title">Process route</div>
                          <div className="route-chain">
                            {/* Block 1 — CNC Milling (auto from the strategy) */}
                            <div className="route-block">
                              <div className="rb-head">
                                <span className="rb-num">{num()}</span>
                                <div className="rb-title">
                                  <div className="rb-name">CNC Milling</div>
                                  <div className="rb-station" title={machineSel || undefined}>
                                    {machineSel || strategy.machine || "Default machine"}
                                  </div>
                                </div>
                                <span className="rb-cost">{inr(routeCalc.millingCost)}</span>
                              </div>
                              <div className="rb-machine">
                                <MachineSelect
                                  machines={filterMy(machines, machineSel)}
                                  customMachines={filterMy(customMachines, machineSel)}
                                  value={machineSel}
                                  onChange={changeMachine}
                                  onAddCustom={addCustomMachine}
                                  disabled={machines.length === 0 && customMachines.length === 0}
                                />
                              </div>
                              <div className="rb-line">
                                <span className="k">Time</span>
                                <span className="v">{fmtMin(estCore.machineMin)}</span>
                              </div>
                              <div className="rb-line">
                                <span className="k">Rate</span>
                                <span
                                  className="v"
                                  title={
                                    estCore.machMult !== 1
                                      ? "Machining rate × the Estimate tab's preset/complexity/tolerance multiplier"
                                      : "Machining rate from the Estimate tab"
                                  }
                                >
                                  {sym}{rateHr}/hr
                                  {estCore.machMult !== 1 ? ` × ${estCore.machMult.toFixed(2)}` : ""}
                                </span>
                              </div>
                              <div className="rb-sub">
                                {strategy.setups.length} setup{strategy.setups.length === 1 ? "" : "s"} · auto from strategy
                                {strategy.basis && (
                                  <span
                                    className="chip"
                                    title={
                                      strategy.basis === "grouped"
                                        ? "Grouped basis — duplicate detections deduped; one op per physical feature"
                                        : "Raw basis — every detection planned; most conservative"
                                    }
                                  >
                                    {strategy.basis === "grouped"
                                      ? `Physical features: ${strategy.planned_candidate_count ?? "—"}`
                                      : `Raw detections: ${strategy.planned_candidate_count ?? "—"}`}
                                  </span>
                                )}
                              </div>
                            </div>

                            {/* Block 2 — Welding & Assembly (auto, weldments only) */}
                            {wmResult && (
                              <>
                                <div className="route-connector" />
                                <div className="route-block">
                                  <div className="rb-head">
                                    <span className="rb-num">{num()}</span>
                                    <div className="rb-title">
                                      <div className="rb-name">Welding &amp; Assembly</div>
                                      <div className="rb-station">Weld shop</div>
                                    </div>
                                    <span className="rb-cost">{inr(routeCalc.weldCost)}</span>
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">Time</span>
                                    <span className="v">{fmtMin(routeCalc.weldMin)}</span>
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">Rate ({sym}/hr)</span>
                                    <input
                                      className="num-input"
                                      type="number"
                                      min={0}
                                      value={weldRate}
                                      onChange={(e) => changeWeldRate(numOr0(e.target.value))}
                                    />
                                  </div>
                                  {wmResult.assembly_operations.length > 0 && (
                                    <div style={{ marginTop: 6 }}>
                                      {wmResult.assembly_operations.map((o, i) => (
                                        <div className="rb-oprow" key={i} title={o.note || o.tool_equipment}>
                                          <span className="ph">{o.phase}</span>
                                          <span className="op">— {o.operation}</span>
                                        </div>
                                      ))}
                                    </div>
                                  )}
                                  <div className="rb-sub">auto from weldment analysis</div>
                                </div>
                              </>
                            )}
                            {analysis.is_multibody && !wmResult && wmLoading && (
                              <>
                                <div className="route-connector" />
                                <div className="route-block" style={{ fontSize: 12, color: "var(--text-2)" }}>
                                  Analysing bodies — the Welding &amp; Assembly block will appear here…
                                </div>
                              </>
                            )}

                            {/* Block 3 — CNC Turning placeholder (shaft/tube bodies
                                detected; plannable once the lathe module lands) */}
                            {routeCalc.hasTurning && (
                              <>
                                <div className="route-connector" />
                                <div className="route-block">
                                  <div className="rb-head">
                                    <span className="rb-num">{num()}</span>
                                    <div className="rb-title">
                                      <div className="rb-name">CNC Turning</div>
                                      <div className="rb-station">
                                        {routeCalc.autoTurnMin > 0
                                          ? `Lathe — planned ${fmtNum(routeCalc.effTurnMin)} min`
                                          : "Lathe — manual quote"}
                                      </div>
                                    </div>
                                    <span className="rb-cost">{inr(routeCalc.turnCost)}</span>
                                  </div>
                                  <div className="rb-machine">
                                    <MachineSelect
                                      machines={filterMy(machines, routeMachines.turning ?? "")}
                                      customMachines={filterMy(customMachines, routeMachines.turning ?? "")}
                                      value={routeMachines.turning ?? ""}
                                      onChange={(n) => setRouteMachine("turning", n)}
                                      onAddCustom={addCustomMachine}
                                      disabled={machines.length === 0 && customMachines.length === 0}
                                    />
                                  </div>
                                  <div className="rb-note">
                                    {routeCalc.autoTurnMin > 0
                                      ? `Planned from detected turning regions (${analysis?.turning?.op_count ?? 0} lathe ops, ${analysis?.turning?.setup ?? "Lathe Chuck"}). Enter a manual time to override.`
                                      : `Detected ${routeCalc.turnedCount} turned part${routeCalc.turnedCount === 1 ? "" : "s"} — enter time and rate to quote.`}
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">
                                      {routeCalc.autoTurnMin > 0
                                        ? "Time (min, override)"
                                        : "Time (min, manual)"}
                                    </span>
                                    <input
                                      className="num-input"
                                      type="number"
                                      min={0}
                                      value={turnMin}
                                      placeholder={routeCalc.autoTurnMin > 0 ? String(routeCalc.autoTurnMin) : undefined}
                                      onChange={(e) => setTurnMin(numOr0(e.target.value))}
                                    />
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">Rate ({sym}/hr)</span>
                                    <input
                                      className="num-input"
                                      type="number"
                                      min={0}
                                      value={turnRate}
                                      onChange={(e) => setTurnRate(numOr0(e.target.value))}
                                    />
                                  </div>
                                </div>
                              </>
                            )}

                            {/* Custom process blocks (operator-added, persisted) */}
                            {customRouteSteps.map((c) => (
                              <Fragment key={c.id}>
                                <div className="route-connector" />
                                <div className="route-block">
                                  <div className="rb-head">
                                    <span className="rb-num">{num()}</span>
                                    <div className="rb-title">
                                      <div className="rb-name" title={c.name}>{c.name}</div>
                                      <div className="rb-station" title={c.station || undefined}>
                                        {c.station || "—"}
                                      </div>
                                    </div>
                                    <span className="rb-cost">{inr((c.timeMin / 60) * c.rateHr)}</span>
                                    <button
                                      className="rb-x"
                                      title="Remove this process"
                                      onClick={() => removeRouteStep(c.id)}
                                    >
                                      ✕
                                    </button>
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">Time</span>
                                    <span className="v">{fmtMin(c.timeMin)}</span>
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">Rate</span>
                                    <span className="v">{sym}{c.rateHr}/hr</span>
                                  </div>
                                  <div className="rb-sub">custom process</div>
                                </div>
                              </Fragment>
                            ))}

                            {/* Add-on process blocks (from Estimate settings —
                                grinding/plating/hardening/powder/custom price) */}
                            {routeCalc.addons.map((a) => (
                              <Fragment key={`addon-${a.name}`}>
                                <div className="route-connector" />
                                <div className="route-block">
                                  <div className="rb-head">
                                    <span className="rb-num">{num()}</span>
                                    <div className="rb-title">
                                      <div className="rb-name" title={a.name}>{a.name}</div>
                                      <div className="rb-station">Outsourced / secondary</div>
                                    </div>
                                    <span className="rb-cost">{inr(a.cost)}</span>
                                    <button
                                      className="rb-x"
                                      title="Remove this process (also clears it in Estimate settings)"
                                      onClick={() =>
                                        setAddonSels((arr) =>
                                          arr.filter((s) => {
                                            const label =
                                              s.param && s.param.trim()
                                                ? `${s.name.trim()} (${s.param.trim()})`
                                                : s.name.trim();
                                            return label !== a.name;
                                          }),
                                        )
                                      }
                                    >
                                      ✕
                                    </button>
                                  </div>
                                  <div className="rb-sub">
                                    add-on from Estimate settings · rate card pricing
                                  </div>
                                </div>
                              </Fragment>
                            ))}
                          </div>

                          {addingProcess ? (
                            <AddProcessForm onAdd={addRouteStep} onCancel={() => setAddingProcess(false)} />
                          ) : (
                            <button className="btn route-add" onClick={() => setAddingProcess(true)}>
                              + Add process
                            </button>
                          )}

                          <div className="section-title">Route summary</div>
                          {(() => {
                            const used = [
                              machineSel || strategy.machine,
                              routeCalc.hasTurning ? routeMachines.turning : null,
                              ...customRouteSteps.map((c) => c.station),
                            ].filter((m): m is string => !!m && m.trim().length > 0);
                            const distinct = [...new Set(used)];
                            if (distinct.length < 1) return null;
                            return (
                              <div className="row" title="Machines assigned across the routed stages">
                                <span className="k">
                                  Machines{distinct.length > 1 ? ` (${distinct.length})` : ""}
                                </span>
                                <span className="v" style={{ textAlign: "right", maxWidth: 210 }}>
                                  {distinct.join(" → ")}
                                </span>
                              </div>
                            );
                          })()}
                          <div className="row">
                            <span className="k">Total route time</span>
                            <span className="v">{fmtMin(routeCalc.totalMin)}</span>
                          </div>
                          <div className="ledger">
                            <div className="ledger-row root">
                              <span className="desc">Process blocks</span>
                              <span className="qty">× {routeCalc.blockCount}</span>
                              <span className="amt">{inr(routeCalc.blocksCost)}</span>
                            </div>
                            <div className="ledger-row">
                              <span
                                className="desc"
                                title={`${analysis.material} stock — ${estCore.massKg.toFixed(1)} kg @ ${sym}${matPriceKg}/kg (same line as the Estimate tab)`}
                              >
                                Material — {analysis.material}, {estCore.massKg.toFixed(1)} kg
                              </span>
                              <span className="amt">{inr(estCore.materialCost)}</span>
                            </div>
                            <div className="ledger-row">
                              <span className="desc">Setup charges</span>
                              <span className="qty">× {strategy.setups.length}</span>
                              <span className="amt">{inr(estCore.setupsCost)}</span>
                            </div>
                            <div className="ledger-row subtotal">
                              <span className="desc">Subtotal</span>
                              <span className="amt">{inr(routeCalc.subtotal)}</span>
                            </div>
                            <div className="ledger-row">
                              <span className="desc">Margin ({marginPct}%)</span>
                              <span className="amt">{inr(routeCalc.margin)}</span>
                            </div>
                            <div className="ledger-row grand">
                              <span className="desc">Routed grand total</span>
                              <span className="amt">{inr(routeCalc.total)}</span>
                            </div>
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 8 }}>
                            Superset of the milling-only estimate — material, setup charges and
                            margin reuse the Estimate settings.
                          </div>
                        </>
                      );
                    })()}
                  </div>
                </>
              )}
            </div>
          )}
          <AssistantPanel
            open={assistantOpen}
            onToggle={() => setAssistantOpen((o) => !o)}
            context={assistantContext}
            contextKey={analysis?.filename ?? null}
          />
        </div>
        )}
      </div>
    </div>
  );
}
