import { useState, useRef } from "react";
import type { ChangeEvent } from "react";
import { api, SAMPLE_NAME } from "./api";
import type { AnalyzeResult, StrategyResult, OpGeo } from "./api";
import { PartViewer } from "./PartViewer";

type Tab = "overview" | "strategy" | "estimate";

function gradeClass(grade: string) {
  if (grade === "A") return "green";
  if (grade === "B" || grade === "C") return "amber";
  return "red";
}

export default function App() {
  const [analysis, setAnalysis] = useState<AnalyzeResult | null>(null);
  const [strategy, setStrategy] = useState<StrategyResult | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selOp, setSelOp] = useState<string | null>(null);
  const [highlight, setHighlight] = useState<OpGeo | null>(null);
  const [rateHr, setRateHr] = useState(800);
  const [setupCharge, setSetupCharge] = useState(500);
  const [matPriceKg, setMatPriceKg] = useState(650);
  const [marginPct, setMarginPct] = useState(20);
  const fileRef = useRef<HTMLInputElement>(null);

  async function runAnalysis(file: File) {
    setLoading(true);
    setError(null);
    try {
      const a = await api.analyze(file);
      setAnalysis(a);
      const s = await api.strategy(file);
      setStrategy(s);
      setTab("overview");
      setSelOp(null);
      setHighlight(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setLoading(false);
    }
  }

  function onFile(e: ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) runAnalysis(file);
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

  return (
    <div style={{ display: "flex", height: "100%" }}>
      <div className="rail">
        <button className="active" title="Part">◧</button>
        <button title="Projects">▦</button>
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
          </div>
          <div style={{ display: "flex", gap: 8 }}>
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

        <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
          <div style={{ flex: 1, position: "relative", background: "#191c20" }}>
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
            {error && (
              <div style={{ position: "absolute", top: 12, left: 12, color: "var(--red)", fontSize: 13 }}>
                {error}
              </div>
            )}
            {analysis && !loading && <PartViewer mesh={analysis.mesh} highlight={highlight} />}
            {analysis && (
              <div style={{ position: "absolute", bottom: 10, left: 12, fontSize: 11, color: "var(--text-2)" }}>
                {analysis.dimensions_mm.length} × {analysis.dimensions_mm.width} × {analysis.dimensions_mm.height} mm · drag to orbit
              </div>
            )}
          </div>

          {analysis && (
            <div className="inspector">
              {tab === "overview" && (
                <>
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

                  <div className="section-title">General</div>
                  <div className="row"><span className="k">Machine type</span><span className="v">3 Axis</span></div>
                  <div className="row"><span className="k">Material</span><span className="v">{analysis.material}</span></div>
                  <div className="row"><span className="k">Parser</span><span className="v">{analysis.parser}</span></div>

                  <div className="section-title">Stock</div>
                  <div className="row"><span className="k">Size (mm)</span><span className="v">{analysis.dimensions_mm.length} × {analysis.dimensions_mm.width} × {analysis.dimensions_mm.height}</span></div>
                  <div className="row"><span className="k">Stock vol</span><span className="v">{analysis.volumes_cm3.stock} cm³</span></div>
                  <div className="row"><span className="k">Part vol</span><span className="v">{analysis.volumes_cm3.part} cm³</span></div>

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

              {tab === "strategy" && strategy && (
                <>
                  <div className="row" style={{ borderBottom: "none" }}>
                    <span className="k">Total machine time</span>
                    <span className="v">{strategy.totals.total_machine_time_min?.toFixed(0)} min</span>
                  </div>
                  {strategy.setups.map((su) => (
                    <div key={su.setup_label}>
                      <div className="section-title">
                        Setup · {su.setup_label} — {su.ops.length} ops · {su.subtotal_min.toFixed(1)} min
                      </div>
                      {su.ops.slice(0, 40).map((op) => {
                        const id = `${su.setup_label}-${op.op_num}`;
                        return (
                          <div
                            key={id}
                            className={`op-row ${selOp === id ? "sel" : ""}`}
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
                              <div>{op.operation}</div>
                              <div className="tool">{op.tool}</div>
                            </div>
                            <span className="t">{op.cut_min.toFixed(1)}m</span>
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
                const massKg = ((analysis.volumes_cm3.part ?? 0) * 2.7) / 1000;
                const material = massKg * matPriceKg;
                const setupsCost = strategy.setups.length * setupCharge;
                const subtotal = machining + material + setupsCost;
                const margin = subtotal * (marginPct / 100);
                const total = subtotal + margin;
                const inr = (v: number) =>
                  "₹" + v.toLocaleString("en-IN", { maximumFractionDigits: 0 });
                return (
                  <>
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
                      <span className="k">Material ({massKg.toFixed(1)} kg Al)</span>
                      <span className="v">{inr(material)}</span>
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
          )}
        </div>
      </div>
    </div>
  );
}
