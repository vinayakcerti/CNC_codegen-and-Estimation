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
  [k: string]: unknown;
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
  topology: { solids: number; faces: number; edges: number; vertices: number };
  parser: string;
  candidates: Candidate[];
  candidate_count: number;
  dfm: DfmScore;
  is_multibody: boolean;
  mesh: Mesh | null;
  material: string;
  machine: string;
}

export interface WeldmentGroup {
  group_id: string;
  classification: string;
  quantity: number;
  body_indices: number[];
  dims_mm: { length: number; width: number; height: number };
  volume_cm3: number;
  faces: number;
  machining_min_per_pc: number;
  features: { feature_type: string; count: number; note: string }[];
  operations: { operation: string; tool_type: string; note: string }[];
  mesh: Mesh | null;
}

export interface WeldmentResult {
  success: boolean;
  filename: string;
  total_bodies: number;
  total_machining_time_min: number;
  total_assembly_time_min: number;
  total_time_min: number;
  groups: WeldmentGroup[];
  assembly_operations: { phase: string; operation: string; tool_equipment: string; note: string }[];
  warnings: string[];
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
  blocked: boolean;
}

export interface StrategyResult {
  success: boolean;
  filename: string;
  setups: { setup_label: string; ops: StrategyOp[]; subtotal_min: number }[];
  totals: { total_machine_time_min: number; cutting_time_min: number; num_operations: number };
}

async function postFile<T>(path: string, file: File): Promise<T> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE}${path}`, { method: "POST", body: form });
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

export const api = {
  health: () => fetch(`${BASE}/api/health`).then((r) => r.json()),
  analyze: (file: File) => postFile<AnalyzeResult>("/api/analyze", file),
  weldment: (file: File) => postFile<WeldmentResult>("/api/weldment", file),
  strategy: (file: File) => postFile<StrategyResult>("/api/strategy", file),
  sampleFile,
};
