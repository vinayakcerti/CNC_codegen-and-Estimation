// API client for the CNC Plan & Process Pro backend (FastAPI, port 8000).
// Mirrors the endpoints in backend/main.py. No AI dependency — this is the
// deterministic "no-AI tier" data layer.

const BASE = import.meta.env.VITE_API_BASE ?? "http://127.0.0.1:8000";

export interface Mesh {
  x: number[]; y: number[]; z: number[];
  i: number[]; j: number[]; k: number[];
}

export interface Candidate {
  candidate_id?: string;
  feature_type?: string;
  feature_name?: string;
  diameter?: number;
  length?: number;
  width?: number;
  depth?: number;
  x_pos?: number;
  y_pos?: number;
  confidence?: string;
  setup?: string;
  // Likely metric tap inferred from a hole's pilot Ø ("M6"), "No Thread", or
  // undefined for non-hole features (gap-v5 C2 Feature-Table Thread column).
  thread?: string;
  // Exact tessellated face geometry (raw-CAD frame, same as the part mesh).
  // Shape varies by backend version — a list of {vertices,triangles} dicts,
  // a single {x,y,z,i,j,k} mesh, or a list of those — so it stays `unknown`
  // and the UI normalizes at runtime (see normalizeFaceMeshes in App).
  face_mesh_data?: unknown;
  [k: string]: unknown;
}

export interface Material {
  name: string;
  density: number;
  machinability_factor: number;
  safety_factor: number;
}

// Machine record from /api/machines. Curated library machines carry
// name/maker/axes; the engine's built-in defaults use machine_name /
// axis_count instead — consumers should go through a display helper.
export interface MachineInfo {
  name?: string;
  machine_name?: string;
  maker?: string;
  type?: string;
  machine_type?: string;
  axes?: number;
  axis_count?: number;
  travel_x_mm?: number | null;
  travel_y_mm?: number | null;
  travel_z_mm?: number | null;
  max_spindle_rpm?: number;
  spindle_power_kw?: number;
  tool_capacity?: number;
  controller?: string;
  rapid_feed_rate?: number;
  tool_change_time_s?: number;
  setup_time_min?: number;
  region?: string;
  [k: string]: unknown;
}

// How a machine selection rides along on analyze/strategy: a library
// machine by name (?machine=) or a custom machine serialized into the
// machine_json multipart form field.
export interface MachineOpts {
  machineName?: string;
  machineJson?: string;
}

// Same split for materials: a library material by name (?material=) or a
// user-defined material serialized into the material_json form field.
export interface MaterialOpts {
  materialName?: string;
  materialJson?: string;
}

// Planning basis: "grouped" plans one op per physical feature (duplicate
// detections deduped), "raw" plans every detection — most conservative.
export type PlanBasis = "grouped" | "raw";

// Manual (raw billet) stock: facing depths and side edge-milling on the
// backend plan follow these dims instead of the automatic +5 mm/side preset.
export interface ManualStockOpt {
  mode: "manual";
  length: number;
  width: number;
  height: number;
}

export interface AnalyzeOpts {
  material?: MaterialOpts;
  machine?: MachineOpts;
  stock?: ManualStockOpt;
}

export interface StrategyOpts extends AnalyzeOpts {
  bodyIndex?: number;
  basis?: PlanBasis;
}

export interface StockBlock {
  mode: string;
  preset: string;
  allowance_mm: number | null;
  size_mm: { length: number; width: number; height: number };
  // Manual (raw billet) stock: per-side allowances actually applied, plus
  // validation state (e.g. stock smaller than the part).
  allowances_mm?: Record<string, number>;
  valid?: boolean;
  errors?: string[];
  edge_milling?: boolean;
}

export interface ToolInfo {
  tool_number: number;
  tool_name: string;
  tool_type: string;
  diameter_mm: number;
  flute_length_mm: number;
  max_depth_mm: number;
  // Catalog-style presentation fields (backend derives from the tool record)
  display_name: string;
  flutes: number | null;
  tip_angle: number | null;
  source_library: string;
}

export interface HoleGroup {
  diameter_mm: number;
  count: number;
  setups: string[];
}

export interface SetupInfo {
  label: string;
  method: string;
  jaw_mode: string;
  reason: string;
}

export interface DfmScore {
  score_pct: number;
  grade: string;
  total_features: number;
  machinable: number;
  at_risk: number;
  blocked: number;
  setup_count: number;
  setup_labels: string[];
  issues: { severity: string; feature: string; message: string }[];
}

export interface AnalyzeResult {
  success: boolean;
  filename: string;
  dimensions_mm: { length: number; width: number; height: number };
  volumes_cm3: { stock: number; part: number };
  // Per-part reporting rollup (Overview): finished volume, machined
  // (machinable) surface area in cm², and finished-part mass. mass uses the
  // resolved material's density — the same basis as the Estimate ledger.
  reporting?: {
    volume_cm3: number | null;
    machined_area_cm2_total: number | null;
    mass_g: number | null;
    mass_kg: number | null;
    density_g_cm3: number | null;
  };
  topology: { solids: number; faces: number; edges: number; vertices: number };
  parser: string;
  candidates: Candidate[];
  candidate_count: number;
  dfm: DfmScore;
  // % of surface area not tied to blocked features (null = no face areas)
  machinable_surface_pct?: number | null;
  // Present on multibody parts when the validated per-body surface walk
  // succeeded (replaces the billet-path blocked-feature formula).
  machinable_surface_detail?: {
    pct: number;
    method: string;
    exclusions: string[];
    per_body: { body_index: number; pct: number }[];
    // Validated assembly-wide plannability (replaces the billet DFM
    // grade on weldments)
    plannable_pct?: number | null;
    feature_totals?: { total: number; plannable: number } | null;
  } | null;
  // Planned lathe summary (Epic 20 v1) when turned regions were detected.
  turning?: TurningSummary | null;
  // Automatic stock sizing block (part envelope + per-side allowance)
  stock?: StockBlock;
  hole_groups?: HoleGroup[];
  setups?: SetupInfo[];
  is_multibody: boolean;
  mesh: Mesh | null;
  material: string;
  // Resolved machine name — null when the engine default has no name
  machine?: string | null;
}

export interface WeldmentGroup {
  group_id: string;
  classification: string;
  quantity: number;
  body_indices: number[];
  dims_mm: { length: number; width: number; height: number };
  volume_cm3: number;
  // Per-body reporting (ONE representative body of the group): mass and
  // machinable surface area. mass_g/kg use the steel weldment density basis.
  mass_g?: number | null;
  mass_kg?: number | null;
  machined_area_cm2?: number | null;
  faces: number;
  machining_min_per_pc: number;
  features: { feature_type: string; count: number; note: string }[];
  operations: { operation: string; tool_type: string; note: string }[];
  mesh: Mesh | null;
  // Validated classifier counts for the group's representative body —
  // null when the classifier could not run on it.
  feature_counts?: FeatureCounts | null;
  // Dimensioned hole/slot lines incl. depth, e.g. "8× Ø11/cb Ø18 × 15 deep"
  features_brief?: string[] | null;
}

export interface WeldmentResult {
  success: boolean;
  filename: string;
  total_bodies: number;
  total_machining_time_min: number;
  total_assembly_time_min: number;
  total_time_min: number;
  groups: WeldmentGroup[];
  // Assembly-level reporting rollup: exact totals summed over EVERY body
  // (authoritative — the per-group rows use a representative body, so they
  // need not sum to this exactly). Mass uses the steel weldment density.
  reporting?: {
    density_g_cm3: number;
    material_basis: string;
    total_volume_cm3: number;
    total_mass_g: number;
    total_mass_kg: number;
    machined_area_cm2_total: number | null;
  };
  assembly_operations: { phase: string; operation: string; tool_equipment: string; note: string }[];
  warnings: string[];
}

// ---- Validated feature geometry (GAP-3) ----
// Attached to an op's geo only when the plan was built from the exact
// classifier (feature_source === "exact_classifier"); billet-path plans
// omit it. Direction fields are raw-CAD unit vectors.
export interface HoleGeometry {
  kind: "hole";
  diameter_mm: number;
  cbore_diameter_mm: number | null;
  depth_mm: number;
  ld_ratio: number | null;
  through: boolean | null; // null = unknown
  depth_below_top_mm: number | null;
  tip_angle_deg: number | null; // drill-tip cone at a blind bottom
  countersink: boolean | null;
  axis_dir: number[] | null;
  entry_dir: number[] | null;
  // Likely metric tap inferred from the pilot diameter (e.g. "M5");
  // an inference, not detected thread data.
  thread_likely?: string | null;
  // Gap-v5 B4: shallow blind hole whose drill tip is auto-upgraded from the
  // standard 118° to a near-flat 140° so the point doesn't exceed the depth.
  cone_deviation?: { original_deg: number; modified_deg: number } | null;
}

export interface SlotGeometry {
  kind: "slot";
  open: boolean;
  length_mm: number;
  width_mm: number;
  // Largest endmill that fits the slot (= width)
  max_tool_dia_mm?: number | null;
  depth_mm: number | null;
  axis_dir: number[] | null;
  open_dir: number[] | null;
  entry_dir: number[] | null;
  // Signed face label the opening points at (e.g. "Top") — open slots only
  opens_toward: string | null;
}

export type FeatureGeometry = HoleGeometry | SlotGeometry;

// Planned lathe work rollup (turning_planner): cycle minutes + a flat
// handling allowance, for the Route tab's Turning block.
export interface TurningSummary {
  op_count: number;
  cut_min: number;
  est_minutes: number;
  setup: string | null;
}

// Per-setup workholding recommendation (method/jaws + the sizing reason)
export interface Workholding {
  method: string;
  jaw_mode: string;
  reason: string;
}

// Hole census for the strategy header chip. threaded stays 0 until
// thread detection ships; likely_* are tap-drill-table inferences.
export interface HoleStats {
  total: number;
  threaded: number;
  through: number;
  blind: number;
  likely_threaded?: number;
  likely_taps?: string[];
}

// Validated typed feature counts for one body (scoped strategy plans and
// weldment group rows share this shape).
export interface FeatureCounts {
  holes: number;
  slots: number;
  fillet_faces: number;
  chamfer_faces: number;
  // Tap-drill-table inference (pilot Ø → likely metric tap)
  likely_threaded?: number;
}

export interface OpGeo {
  x: number | null;
  y: number | null;
  z: number | null;
  diameter: number;
  length: number;
  width: number;
  depth: number;
  feature_type: string;
  // Links the op back to its analyze-response candidate, whose
  // face_mesh_data provides the exact-face 3D highlight.
  candidate_id?: string | null;
  // Validated geometry for the op panel's Geometry section (exact-classifier
  // plans only; null/absent for billet-path features).
  geometry?: FeatureGeometry | null;
  // Tessellated faces of a classifier feature (raw-CAD frame) — lets the
  // viewer drape the real slot/hole surfaces instead of the locator ring.
  face_mesh_data?: unknown;
}

export interface StrategyOp {
  op_num: number;
  operation: string;
  feature: string;
  setup: string;
  tool: string;
  spindle_rpm: number;
  feed_mm_min: number;
  path_mm: number;
  cut_min: number;
  // ARD R2: machined surface (cm²) this op touches — rate-card costing input.
  machined_area_cm2?: number;
  blocked: boolean;
  geo: OpGeo | null;
  // Catalog-style tool name ("6mm Drill 135°") — presentation only
  tool_display?: string;
  // Set on lathe rows so the Estimate breakdown buckets them as Turning.
  lathe?: boolean;
}

export interface StrategySetup {
  setup_label: string;
  ops: StrategyOp[];
  subtotal_min: number;
  // Workholding recommendation sized from the scoped body (or whole part)
  // envelope — null when the backend has no stock envelope for the scope.
  workholding?: Workholding | null;
}

export interface StrategyResult {
  success: boolean;
  filename: string;
  setups: StrategySetup[];
  totals: {
    total_machine_time_min: number;
    cutting_time_min: number;
    num_operations: number;
    // Time-model components (present in the backend payload). The Estimate
    // tab's machining breakdown uses them to reconcile category cutting +
    // positioning + tool-changes + machine-setup back to the machining total.
    rapid_time_min?: number;
    tool_change_time_min?: number;
    setup_time_min?: number;
    num_tool_changes?: number;
  };
  material?: string;
  machine?: string | null;
  // Planning basis the backend used ("grouped" | "raw") and how many
  // candidates it actually planned on that basis.
  basis?: string;
  planned_candidate_count?: number;
  // "exact_classifier" when the plan used validated geometry
  feature_source?: string;
  // Set when the plan was scoped to one solid via ?body_index=
  scoped_body_index?: number | null;
  scoped_candidate_count?: number | null;
  // Hole census from validated geometry (exact-classifier plans only)
  hole_stats?: HoleStats | null;
  // % of validated features the planner produced ops for (scoped basis)
  features_plannable_pct?: number | null;
  // Typed feature counts for the scoped body (scoped plans only)
  body_feature_counts?: FeatureCounts | null;
}

// ---- AI Assistant panel (paid tier) ----
export interface AssistantChatMessage {
  role: "user" | "assistant";
  content: string;
}

// Compact plan summary sent with every question — never raw meshes/candidates.
export interface AssistantContext {
  filename: string;
  material: string;
  machine: string | null;
  setups: {
    label: string;
    op_count: number;
    subtotal_min: number;
    workholding: string | null;
  }[];
  totals: {
    machine_time_min: number;
    tool_changes: number;
    setup_count: number;
  };
  estimate: {
    material: number;
    machining: number;
    setups: number;
    total: number;
  };
  excluded_count: number;
}

export interface AssistantResult {
  available: boolean;
  answer?: string;
  message?: string;
}

async function postFile<T>(
  path: string,
  file: File,
  query?: Record<string, string>,
  formFields?: Record<string, string>,
): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  for (const [k, v] of Object.entries(formFields ?? {})) form.append(k, v);
  const qs = query && Object.keys(query).length ? `?${new URLSearchParams(query).toString()}` : "";
  const res = await fetch(`${BASE}${path}${qs}`, { method: "POST", body: form });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE}${path}`);
  if (!res.ok) throw new Error(`Request failed: ${res.status}`);
  return res.json() as Promise<T>;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({ detail: res.statusText }));
    throw new Error(detail.detail ?? `Request failed: ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export const SAMPLE_NAME = "3100171001_01 SLIDE BASE-1812 ( FOR TOOL LOADER ).STEP";

async function sampleFile(name: string): Promise<File> {
  const blob = await fetch(`${BASE}/api/sample/${encodeURIComponent(name)}`).then((r) => {
    if (!r.ok) throw new Error("Sample not available");
    return r.blob();
  });
  return new File([blob], name, { type: "application/octet-stream" });
}

// Split material/machine picks into query params (library names) and
// multipart form fields (custom JSON payloads) — shared by analyze/strategy.
function buildOpts(opts?: AnalyzeOpts): {
  query: Record<string, string>;
  form: Record<string, string>;
} {
  const query: Record<string, string> = {};
  const form: Record<string, string> = {};
  if (opts?.material?.materialName) query.material = opts.material.materialName;
  if (opts?.material?.materialJson) form.material_json = opts.material.materialJson;
  if (opts?.machine?.machineName) query.machine = opts.machine.machineName;
  if (opts?.machine?.machineJson) form.machine_json = opts.machine.machineJson;
  if (opts?.stock) form.stock_json = JSON.stringify(opts.stock);
  return { query, form };
}

export const api = {
  health: () => fetch(`${BASE}/api/health`).then((r) => r.json()),
  materials: () => getJson<{ materials: Material[] }>("/api/materials"),
  machines: () => getJson<{ machines: MachineInfo[] }>("/api/machines"),
  tools: () => getJson<{ tools: ToolInfo[] }>("/api/tools"),
  analyze: (file: File, opts?: AnalyzeOpts) => {
    const { query, form } = buildOpts(opts);
    return postFile<AnalyzeResult>("/api/analyze", file, query, form);
  },
  weldment: (file: File) => postFile<WeldmentResult>("/api/weldment", file),
  strategy: (file: File, opts?: StrategyOpts) => {
    const { query, form } = buildOpts(opts);
    if (opts?.bodyIndex !== undefined) query.body_index = String(opts.bodyIndex);
    if (opts?.basis) query.basis = opts.basis;
    return postFile<StrategyResult>("/api/strategy", file, query, form);
  },
  assistant: (question: string, context: AssistantContext, history?: AssistantChatMessage[]) =>
    postJson<AssistantResult>("/api/assistant", { question, context, history }),
  sampleFile,
};
