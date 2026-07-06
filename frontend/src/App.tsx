import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, PointerEvent as ReactPointerEvent } from "react";
import { api, SAMPLE_NAME } from "./api";
import type {
  AnalyzeResult, StrategyResult, StrategyOp, Material, OpGeo, Mesh,
  WeldmentResult, WeldmentGroup, MachineInfo, MachineOpts, MaterialOpts, PlanBasis,
} from "./api";
import { PartViewer } from "./PartViewer";
import type { Vec3, Approach } from "./PartViewer";
import { MaterialSelect } from "./MaterialSelect";
import { MachineSelect } from "./MachineSelect";
import type { CustomMachine } from "./MachineSelect";
import { BottomPanel } from "./BottomPanel";
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
  front: [0, -1, 0],
  back: [0, 1, 0],
  left: [-1, 0, 0],
  right: [1, 0, 0],
};
// Unknown setup labels fall back to a front-right-top isometric view.
const ISO_DIR: Vec3 = [0.577, -0.577, 0.577];

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
const inr = (v: number) => "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
const fmtMin = (min: number) => {
  const m = Math.round(min);
  return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m} min`;
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

function loadInspectorWidth(): number {
  const v = Number(lsGet("cnc.inspectorWidth"));
  return Number.isFinite(v) && v >= INSPECTOR_MIN && v <= INSPECTOR_MAX ? v : INSPECTOR_DEFAULT;
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
        <span>Rate (₹/hr)</span>
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
  const [view, setView] = useState<"projects" | "part">("projects");
  const [selOp, setSelOp] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<OpGeo | null>(null);
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const [rateHr, setRateHr] = useState(800);
  const [setupCharge, setSetupCharge] = useState(500);
  const [matPriceKg, setMatPriceKg] = useState(650);
  const [marginPct, setMarginPct] = useState(20);
  const fileRef = useRef<HTMLInputElement>(null);

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

  // Stock config (Overview → Material section). Manual sizes replace the
  // stock volume behind the Estimate material line. Per-part session state.
  const [stockMode, setStockMode] = useState<"auto" | "manual">("auto");
  const [manualStock, setManualStock] =
    useState<{ length: number; width: number; height: number } | null>(null);

  // Part opacity in the 3D viewer (0.2–1, persisted)
  const [viewerOpacity, setViewerOpacity] = useState<number>(loadViewerOpacity);

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
    if (tab !== "strategy" || scopedBodyIndex == null || !partFile) return;
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

  // Exact face meshes for the selected op via geo.candidate_id → analyze
  // candidates. Candidates are whole-assembly in the raw-CAD frame — the
  // same frame as body meshes — so this works under a body scope too.
  const selFaceMeshes = useMemo((): Mesh[] | null => {
    const cid = selOpData?.geo?.candidate_id;
    if (!cid || !analysis) return null;
    const cand = analysis.candidates.find((c) => c.candidate_id === cid);
    const meshes = cand ? normalizeFaceMeshes(cand.face_mesh_data) : [];
    return meshes.length ? meshes : null;
  }, [selOpData, analysis]);

  // ---- Shared estimate core (Estimate tab ledger + Route tab blocks) ----
  // One source of truth for the machining multiplier, material mass/cost and
  // setup charges, so the routed grand total is an exact superset of the
  // milling-only estimate.
  const estCore = useMemo(() => {
    if (!analysis || !strategy) return null;
    const machineMin = strategy.totals.total_machine_time_min ?? 0;
    // Operator-controlled machining multiplier: quote preset × complexity ×
    // tolerance. Applies ONLY to machining-time cost lines — never to
    // material or setup charges.
    const presetMult = PRESET_MULT[estPreset];
    const tolMult = TOLERANCE_MULT[estTolerance];
    const complexity = Number.isFinite(estComplexity)
      ? Math.min(COMPLEXITY_MAX, Math.max(COMPLEXITY_MIN, estComplexity))
      : 1.0;
    const machMult = presetMult * complexity * tolMult;
    const machining = (machineMin / 60) * rateHr * machMult;
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
    const setupsCost = strategy.setups.length * setupCharge;
    return {
      machineMin, presetMult, tolMult, complexity, machMult, machining,
      stockSize, massKg, materialCost, setupsCost,
    };
  }, [
    analysis, strategy, estPreset, estTolerance, estComplexity,
    customMaterials, materials, stockMode, manualStock, matPriceKg, setupCharge, rateHr,
  ]);

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
    const hasTurning = turnedCount > 0;
    const turnCost = (turnMin / 60) * turnRate;
    const customMin = customRouteSteps.reduce((s, c) => s + c.timeMin, 0);
    const customCost = customRouteSteps.reduce((s, c) => s + (c.timeMin / 60) * c.rateHr, 0);
    const blockCount = 1 + (hasWeld ? 1 : 0) + (hasTurning ? 1 : 0) + customRouteSteps.length;
    const totalMin =
      estCore.machineMin + (hasWeld ? weldMin : 0) + (hasTurning ? turnMin : 0) + customMin;
    const blocksCost =
      millingCost + (hasWeld ? weldCost : 0) + (hasTurning ? turnCost : 0) + customCost;
    // Same footer math as the Estimate ledger — material + setups + margin —
    // with all process blocks in place of the single machining line.
    const subtotal = blocksCost + estCore.materialCost + estCore.setupsCost;
    const margin = subtotal * (marginPct / 100);
    const total = subtotal + margin;
    return {
      millingCost, hasWeld, weldMin, weldCost, turnedCount, hasTurning, turnCost,
      customMin, customCost, blockCount, totalMin, blocksCost, subtotal, margin, total,
    };
  }, [estCore, wmResult, weldRate, turnMin, turnRate, customRouteSteps, marginPct]);

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
    const d = SETUP_DIRS[activeSetup.trim().toLowerCase()];
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

  // ---- Thread status per hole diameter (session-only UI state) ----
  const [threadByDia, setThreadByDia] = useState<Record<string, string>>({});

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

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) void runAnalysis(file);
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
  const rollupsBySetup = useMemo(
    () =>
      (stratForView?.setups ?? []).map((su) => ({
        label: su.setup_label,
        opCount: su.ops.length,
        subtotal: su.subtotal_min,
        rollups: buildRollups(su.setup_label, su.ops),
      })),
    [stratForView],
  );

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
              </div>
              <span className="t">{fmtNum(wmResult.total_machining_time_min)} min</span>
            </div>
            {wmResult.groups.map((g) => (
              <div
                key={g.group_id}
                className={`body-row ${selectedGroupId === g.group_id ? "sel" : ""}`}
                onClick={() => selectScope(g.group_id)}
                title={`${scopeLabel(g)} — click to isolate in 3D`}
              >
                <div className="main">
                  <div className="name">
                    {titleCase(g.classification)} ×{g.quantity}
                  </div>
                  <div className="dims">{groupDims(g)} mm</div>
                </div>
                <span className="t">{fmtNum(g.machining_min_per_pc)} min/pc</span>
              </div>
            ))}
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
    return (
      <>
        <div className="section-title">Holes</div>
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
    return (
      <div
        key={id}
        className={`op-row ${child ? "child" : ""} ${selOp === id ? "sel" : ""}`}
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
          <div>{child ? op.feature || op.operation : op.operation}</div>
          {!child && <div className="tool">{op.tool_display || op.tool}</div>}
        </div>
        <span className="t">{op.cut_min.toFixed(1)}m</span>
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
        <button title="Libraries">▤</button>
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
            {analysis && <button className="btn primary">Prepare Quote</button>}
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".step,.stp"
            style={{ display: "none" }}
            onChange={onFile}
          />
        </div>

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
                  <div className="card-sub">Upload STEP</div>
                </div>
              </div>
            </div>
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
                <div style={{ height: "100%", display: "flex", alignItems: "center", justifyContent: "center", color: "var(--text-1)" }}>
                  Analysing part…
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
                  approach={selectedGroup ? null : setupView.approach}
                  opacity={viewerOpacity}
                  // Workholding visuals follow the active setup — whole-assembly
                  // view only, same guard as the orientation/cone above.
                  workholding={
                    !selectedGroup && activeSetup
                      ? { flip: SECONDARY_FACE_RE.test(activeSetup) }
                      : null
                  }
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
            {analysis && <BottomPanel candidates={analysis.candidates} />}
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
                        <MaterialSelect
                          materials={materials}
                          customMaterials={customMaterials}
                          value={material}
                          onChange={changeMaterial}
                          onAddCustom={addCustomMaterial}
                          disabled={loading || (materials.length === 0 && customMaterials.length === 0)}
                        />
                        <MachineSelect
                          machines={machines}
                          customMachines={customMachines}
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
                              <div className="value">
                                <span className={`badge ${gradeClass(analysis.dfm.grade)}`}>
                                  {analysis.dfm.score_pct}% {analysis.dfm.grade}
                                </span>
                              </div>
                            </div>
                            <div className="metric">
                              <div className="label">Bodies</div>
                              <div className="value">{analysis.topology.solids}</div>
                            </div>
                            <div className="metric">
                              <div className="label">Machinable surface</div>
                              <div className="value">
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
                            <div className="row"><span className="k">Volume</span><span className="v">{fmtNum(selectedGroup.volume_cm3)} cm³</span></div>
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
                            <div className="row"><span className="k">Part vol</span><span className="v">{analysis.volumes_cm3.part} cm³</span></div>

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
                            {stratForView.basis && (
                              <div style={{ margin: "2px 0 6px" }}>
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
                              </div>
                            )}
                            <div className="row" style={{ borderBottom: "none" }}>
                              <span className="k">Total machine time</span>
                              <span className="v">{stratForView.totals.total_machine_time_min?.toFixed(0)} min</span>
                            </div>
                            {rollupsBySetup.length === 0 && (
                              <div style={{ fontSize: 12, color: "var(--text-2)", padding: "6px 0" }}>
                                No machinable candidates in this scope
                              </div>
                            )}
                            {rollupsBySetup.map((su) => (
                              <div key={su.label}>
                                <div className="section-title">
                                  Setup · {su.label} — {su.opCount} ops · {su.subtotal.toFixed(1)} min
                                </div>
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
                              </div>
                            ))}
                          </>
                        )}
                      </>
                    )}

                    {tab === "estimate" && strategy && estCore && (() => {
                      // All shared cost math lives in estCore (also feeds the
                      // Route tab, keeping the routed total a strict superset).
                      const {
                        machineMin, presetMult, tolMult, complexity, machMult,
                        machining, stockSize, massKg, materialCost: material_, setupsCost,
                      } = estCore;
                      const partTotal = material_ + machining; // block 1: material + machining
                      const subtotal = partTotal + setupsCost;
                      const margin = subtotal * (marginPct / 100);
                      const total = subtotal + margin;
                      // Quote range: the same ledger recomputed at the
                      // competitive (×0.70) and conservative (×1.00) preset
                      // ends — complexity/tolerance stay as selected.
                      const totalAtPreset = (pm: number) => {
                        const mach = (machineMin / 60) * rateHr * pm * complexity * tolMult;
                        return (material_ + mach + setupsCost) * (1 + marginPct / 100);
                      };
                      const rangeLow = totalAtPreset(PRESET_MULT.competitive);
                      const rangeHigh = totalAtPreset(PRESET_MULT.conservative);
                      const d = analysis.dimensions_mm;
                      const stockDims = stockSize
                        ? `${fmtNum(stockSize.length)} × ${fmtNum(stockSize.width)} × ${fmtNum(stockSize.height)} mm`
                        : `${d.length} × ${d.width} × ${d.height} mm`;
                      const stockTag = stockSize && stockMode === "manual" ? " (manual)" : "";
                      const materialLine =
                        `${analysis.material} stock ${stockDims}${stockTag} — ${massKg.toFixed(1)} kg @ ₹${matPriceKg}/kg`;
                      return (
                        <>
                          {selectedGroup && (
                            <div className="scope-note">
                              Estimate is whole-assembly; body-scoped planning coming.
                            </div>
                          )}
                          <div className="section-title">Estimate settings</div>
                          <div className="row">
                            <span className="k">Machining rate (₹/hr)</span>
                            <input
                              className="num-input" type="number" value={rateHr}
                              onChange={(e) => setRateHr(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Setup charge (₹)</span>
                            <input
                              className="num-input" type="number" value={setupCharge}
                              onChange={(e) => setSetupCharge(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Material (₹/kg)</span>
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
                                style={{ maxWidth: 148 }}
                                value={estPreset}
                                title="Scales the machining-time cost lines only"
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
                              value={Number.isFinite(estComplexity) ? estComplexity : ""}
                              onChange={(e) => changeComplexity(+e.target.value)}
                            />
                          </div>
                          <div className="row">
                            <span className="k">Tolerance class</span>
                            <select
                              className="mini-select"
                              style={{ maxWidth: 170 }}
                              value={estTolerance}
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
                          <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 6 }}>
                            machining ×{machMult.toFixed(2)} = preset {presetMult.toFixed(2)} ×
                            complexity {complexity.toFixed(2)} × tolerance {tolMult.toFixed(2)}
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
                            {strategy.setups.map((su) => {
                              const multTag = machMult !== 1 ? ` × ${machMult.toFixed(2)}` : "";
                              const line = `Setup · ${su.setup_label} — ${fmtMin(su.subtotal_min)} — ₹${rateHr}/hr${multTag}`;
                              return (
                                <div className="ledger-row child" key={su.setup_label}>
                                  <span className="desc" title={line}>{line}</span>
                                  <span className="amt">{inr((su.subtotal_min / 60) * rateHr * machMult)}</span>
                                </div>
                              );
                            })}

                            {/* Block 2 — per-setup fixed charges */}
                            <div className="ledger-row root">
                              <span className="desc">Setup Charges</span>
                              <span className="qty">× {strategy.setups.length}</span>
                              <span className="amt">{inr(setupsCost)}</span>
                            </div>
                            {strategy.setups.map((su) => (
                              <div className="ledger-row child" key={su.setup_label}>
                                <span className="desc">Setup · {su.setup_label}</span>
                                <span className="amt">{inr(setupCharge)}</span>
                              </div>
                            ))}

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
                          </div>
                          <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 8 }}>
                            {machineMin.toFixed(0)} min machine time · {strategy.setups.length} setups · per part
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
                                  ₹{rateHr}/hr
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
                                    <span className="k">Rate (₹/hr)</span>
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
                                      <div className="rb-station">Lathe — manual quote</div>
                                    </div>
                                    <span className="rb-cost">{inr(routeCalc.turnCost)}</span>
                                  </div>
                                  <div className="rb-note">
                                    Detected {routeCalc.turnedCount} turned part
                                    {routeCalc.turnedCount === 1 ? "" : "s"} — turning planning coming
                                    with the lathe module
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">Time (min, manual)</span>
                                    <input
                                      className="num-input"
                                      type="number"
                                      min={0}
                                      value={turnMin}
                                      onChange={(e) => setTurnMin(numOr0(e.target.value))}
                                    />
                                  </div>
                                  <div className="rb-line">
                                    <span className="k">Rate (₹/hr)</span>
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
                                    <span className="v">₹{c.rateHr}/hr</span>
                                  </div>
                                  <div className="rb-sub">custom process</div>
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
                                title={`${analysis.material} stock — ${estCore.massKg.toFixed(1)} kg @ ₹${matPriceKg}/kg (same line as the Estimate tab)`}
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
        </div>
        )}
      </div>
    </div>
  );
}
