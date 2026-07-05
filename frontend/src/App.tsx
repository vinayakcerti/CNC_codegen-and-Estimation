import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, PointerEvent as ReactPointerEvent } from "react";
import { api, SAMPLE_NAME } from "./api";
import type { AnalyzeResult, StrategyResult, StrategyOp, Material, OpGeo, WeldmentResult, WeldmentGroup } from "./api";
import { PartViewer } from "./PartViewer";
import { MaterialSelect } from "./MaterialSelect";
import { BottomPanel } from "./BottomPanel";
import { lsGet, lsSet } from "./storage";

type Tab = "overview" | "strategy" | "estimate";
type Theme = "dark" | "light";

const INSPECTOR_MIN = 200;
const INSPECTOR_MAX = 560;
const INSPECTOR_DEFAULT = 320;

function gradeClass(grade: string) {
  if (grade === "A") return "green";
  if (grade === "B" || grade === "C") return "amber";
  return "red";
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
  tool: string;
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
    // Op highlights are assembly-space — they don't survive a scope change.
    setSelOp(null);
    setHighlight(null);
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

  async function runAnalysis(file: File, opts?: { material?: string; preserveTab?: boolean }) {
    const mat = opts?.material ?? (material || undefined);
    setLoading(true);
    setError(null);
    setView("part");
    setPartFile(file);
    setSelectedGroupId(null); // scope resets on any new analysis
    if (wmFileRef.current !== file) {
      // Different part — drop the cached weldment breakdown.
      wmFileRef.current = null;
      setWmResult(null);
      setWmError(null);
      setWmLoading(false);
    }
    try {
      const a = await api.analyze(file, mat);
      setAnalysis(a);
      // Body breakdown loads in parallel — never blocks the main analyze flow.
      // Weldment output is material-independent, so a cached result is kept.
      if (a.is_multibody && wmFileRef.current !== file) {
        wmFileRef.current = file;
        void fetchWeldment(file);
      }
      if (a.material) setMaterial(a.material); // sync to what the backend resolved
      const s = await api.strategy(file, mat);
      setStrategy(s);
      if (!opts?.preserveTab) setTab("overview");
      setSelOp(null);
      setHighlight(null);
      setExpanded({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  function changeMaterial(name: string) {
    setMaterial(name);
    lsSet("cnc.material", name);
    if (partFile) void runAnalysis(partFile, { material: name, preserveTab: true });
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

  const rollupsBySetup = useMemo(
    () =>
      (strategy?.setups ?? []).map((su) => ({
        label: su.setup_label,
        opCount: su.ops.length,
        subtotal: su.subtotal_min,
        rollups: buildRollups(su.setup_label, su.ops),
      })),
    [strategy],
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
        <span className="seq">{op.op_num}</span>
        <div className="main">
          <div>{child ? op.feature || op.operation : op.operation}</div>
          {!child && <div className="tool">{op.tool}</div>}
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
                {(["overview", "strategy", "estimate"] as Tab[]).map((t) => (
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
                  // Op markers are assembly-space — only valid in full-assembly scope.
                  highlight={selectedGroup ? null : highlight}
                  theme={theme}
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
                          value={material}
                          onChange={changeMaterial}
                          disabled={loading || materials.length === 0}
                        />

                        {/* Assembly-level metrics hide under a body scope — honest
                            labeling: the DFM score is whole-assembly only. */}
                        {!selectedGroup && (
                          <div className="metric-grid">
                            <div className="metric">
                              <div className="label">Machinability</div>
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
                          </>
                        )}

                        {!selectedGroup && (
                          <>
                            <div className="section-title">General</div>
                            <div className="row"><span className="k">Machine type</span><span className="v">3 Axis</span></div>
                            <div className="row"><span className="k">Material</span><span className="v" style={{ textAlign: "right" }}>{analysis.material}</span></div>
                            <div className="row"><span className="k">Parser</span><span className="v">{analysis.parser}</span></div>

                            <div className="section-title">Stock</div>
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
                            <div className="row"><span className="k">Stock vol</span><span className="v">{analysis.volumes_cm3.stock} cm³</span></div>
                            <div className="row"><span className="k">Part vol</span><span className="v">{analysis.volumes_cm3.part} cm³</span></div>

                            {(analysis.setups ?? []).length > 0 && (
                              <>
                                <div className="section-title">Setups</div>
                                {(analysis.setups ?? []).map((s) => (
                                  <div className="setup-row" key={s.label} title={s.reason}>
                                    <div className="setup-line">
                                      <span className="k">{s.label}</span>
                                      <span className="v">{s.method}</span>
                                    </div>
                                    <div className="setup-sub">{s.jaw_mode}</div>
                                  </div>
                                ))}
                              </>
                            )}

                            {(analysis.hole_groups ?? []).length > 0 && (
                              <>
                                <div className="section-title">Holes</div>
                                {(analysis.hole_groups ?? []).map((g) => (
                                  <div className="hole-row" key={g.diameter_mm}>
                                    <span className="hole-main">
                                      {g.count}× Ø{g.diameter_mm.toFixed(2)}mm
                                    </span>
                                    <span className="chip">No thread</span>
                                    <span className="hole-setups" title={formatSetups(g.setups)}>
                                      {formatSetups(g.setups)}
                                    </span>
                                  </div>
                                ))}
                              </>
                            )}

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

                    {tab === "strategy" && strategy && (
                      <>
                        {selectedGroup && (
                          <div className="scope-note">
                            Strategy is whole-assembly; body-scoped planning coming.
                          </div>
                        )}
                        <div className="row" style={{ borderBottom: "none" }}>
                          <span className="k">Total machine time</span>
                          <span className="v">{strategy.totals.total_machine_time_min?.toFixed(0)} min</span>
                        </div>
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
                                    <span className="seq">{isOpen ? "▾" : "▸"}</span>
                                    <div className="main">
                                      <div>{r.operation} ×{r.ops.length}</div>
                                      <div className="tool">{r.tool}</div>
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

                    {tab === "estimate" && strategy && (() => {
                      const machineMin = strategy.totals.total_machine_time_min ?? 0;
                      const machining = (machineMin / 60) * rateHr;
                      const density = materials.find((m) => m.name === analysis.material)?.density ?? 2.7;
                      // Material is bought as STOCK, not as the finished part —
                      // quote the stock block mass (competitor does the same).
                      const massKg = ((analysis.volumes_cm3.stock ?? 0) * density) / 1000;
                      const material_ = massKg * matPriceKg;
                      const setupsCost = strategy.setups.length * setupCharge;
                      const subtotal = machining + material_ + setupsCost;
                      const margin = subtotal * (marginPct / 100);
                      const total = subtotal + margin;
                      const inr = (v: number) =>
                        "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
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

                          <div className="section-title">Machining — {machineMin.toFixed(0)} min</div>
                          {strategy.setups.map((su) => (
                            <div className="row" key={su.setup_label}>
                              <span className="k">Setup · {su.setup_label} ({su.subtotal_min.toFixed(0)}m)</span>
                              <span className="v">{inr((su.subtotal_min / 60) * rateHr)}</span>
                            </div>
                          ))}
                          <div className="row">
                            <span className="k">Machine time total</span>
                            <span className="v">{inr(machining)}</span>
                          </div>

                          <div className="section-title">Costs</div>
                          <div className="row">
                            <span className="k">Material (stock {massKg.toFixed(1)} kg)</span>
                            <span className="v">{inr(material_)}</span>
                          </div>
                          <div className="row">
                            <span className="k">Setup charges × {strategy.setups.length}</span>
                            <span className="v">{inr(setupsCost)}</span>
                          </div>
                          <div className="row">
                            <span className="k">Margin ({marginPct}%)</span>
                            <span className="v">{inr(margin)}</span>
                          </div>

                          <div className="total-card">
                            <div className="label">Grand total (per part)</div>
                            <div className="big">{inr(total)}</div>
                            <div className="sub">
                              {machineMin.toFixed(0)} min machine time · {strategy.setups.length} setups
                            </div>
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
