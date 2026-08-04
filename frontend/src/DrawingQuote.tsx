import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "./api";
import type { DrawingCompareReport, DrawingExtraction } from "./api";

// Drawing-to-quote flow: a customer PDF drawing becomes a quotable part.
//
//   1. preview + Extract       (vision LLM, or AI_EXTRACT_FIXTURE in dev)
//   2. review the extraction   (features, caveats, confidence — human gate)
//   3a. drawing only  -> synthesize a STEP -> normal pipeline (estimate/G-code)
//   3b. have a STEP   -> deterministic compare -> mismatch report (colored)
//        -> user picks: quote the DRAWING / quote the STEP / compare BOTH
//        -> "both" shows machine-time + quick-price delta at current rates.

type Stage =
  | "preview" | "extracting" | "review"
  | "comparing" | "compare_report" | "synthesizing" | "pricing_both";

const STATUS_COLOR: Record<string, string> = {
  MATCHED: "var(--green, #2e9e5b)",
  COUNT_MISMATCH: "var(--amber, #d99a26)",
  DIM_MISMATCH: "var(--red, #d64545)",
  MISSING_IN_STEP: "var(--red, #d64545)",
  EXTRA_IN_STEP: "var(--red, #d64545)",
  NOT_COMPARED: "var(--text-2)",
};

export function DrawingQuote({
  pdf,
  rateHr,
  setupCharge,
  currency,
  onQuote,
  onClose,
}: {
  pdf: File;
  rateHr: number;
  setupCharge: number;
  currency: string;
  // Hand the chosen file to the normal analyze pipeline.
  onQuote: (file: File, note?: string) => void;
  onClose: () => void;
}) {
  const [stage, setStage] = useState<Stage>("preview");
  const [error, setError] = useState<string | null>(null);
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [extraction, setExtraction] = useState<DrawingExtraction | null>(null);
  const [fixture, setFixture] = useState(false);
  const [stepFile, setStepFile] = useState<File | null>(null);
  const [report, setReport] = useState<DrawingCompareReport | null>(null);
  const [both, setBoth] = useState<{
    drawing: { min: number; setups: number; price: number };
    step: { min: number; setups: number; price: number };
  } | null>(null);
  const [synWarnings, setSynWarnings] = useState<string[]>([]);
  const stepInputRef = useRef<HTMLInputElement>(null);

  const pdfUrl = useMemo(() => URL.createObjectURL(pdf), [pdf]);
  useEffect(() => () => URL.revokeObjectURL(pdfUrl), [pdfUrl]);

  async function extract() {
    setStage("extracting");
    setError(null);
    try {
      const r = await api.drawingExtract(pdf);
      if (!r.available || !r.extraction) {
        setUnavailable(r.message || "Drawing extraction is not available.");
        setStage("preview");
        return;
      }
      setExtraction(r.extraction);
      setFixture(!!r.fixture);
      setStage("review");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Extraction failed.");
      setStage("preview");
    }
  }

  async function quoteFromDrawing() {
    if (!extraction) return;
    setStage("synthesizing");
    setError(null);
    try {
      const { file, warnings } = await api.drawingSynthesize(extraction);
      setSynWarnings(warnings);
      onQuote(
        file,
        warnings.length
          ? `Built from drawing with ${warnings.length} warning(s) — check before quoting.`
          : "Built from the drawing — verify dimensions before quoting.",
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Synthesis failed.");
      setStage("review");
    }
  }

  async function compareWith(file: File) {
    if (!extraction) return;
    setStepFile(file);
    setStage("comparing");
    setError(null);
    try {
      const { report: rep } = await api.drawingCompare(extraction, file);
      setReport(rep);
      setStage("compare_report");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Comparison failed.");
      setStage("review");
    }
  }

  // "Consider both": machine-time + quick price for drawing-version and
  // STEP-version at the CURRENT shop rates. The full ledger comes from
  // opening either version — this is the decision aid.
  async function priceBoth() {
    if (!extraction || !stepFile) return;
    setStage("pricing_both");
    setError(null);
    try {
      const { file: synth } = await api.drawingSynthesize(extraction);
      const [ds, ss] = await Promise.all([api.strategy(synth), api.strategy(stepFile)]);
      const tally = (s: { setups: { subtotal_min: number }[] }) => {
        const min = s.setups.reduce((a, su) => a + (su.subtotal_min || 0), 0);
        const setups = s.setups.length;
        return { min, setups, price: Math.round((min / 60) * rateHr + setups * setupCharge) };
      };
      setBoth({ drawing: tally(ds), step: tally(ss) });
      setStage("compare_report");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Estimating both versions failed.");
      setStage("compare_report");
    }
  }

  const busy = ["extracting", "comparing", "synthesizing", "pricing_both"].includes(stage);

  return (
    <div style={{ flex: 1, display: "flex", minHeight: 0 }}>
      {/* Left: the drawing itself, always visible */}
      <div style={{ flex: 1, minWidth: 0, borderRight: "1px solid var(--border)" }}>
        <iframe src={pdfUrl} title="Drawing" style={{ width: "100%", height: "100%", border: "none" }} />
      </div>

      {/* Right: the flow */}
      <div style={{ width: 460, flexShrink: 0, overflowY: "auto", padding: 16 }} className="drawing-flow">
        <div style={{ display: "flex", alignItems: "center", marginBottom: 10 }}>
          <div style={{ fontSize: 14, fontWeight: 600 }}>Quote from drawing</div>
          <button className="btn" style={{ marginLeft: "auto" }} onClick={onClose}>✕ Close</button>
        </div>
        <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 12 }}>{pdf.name}</div>

        {error && <div className="assistant-error" style={{ margin: "0 0 10px" }}>{error}</div>}
        {unavailable && <div className="assistant-nokey" style={{ margin: "0 0 10px" }}>{unavailable}</div>}

        {stage === "preview" && !unavailable && (
          <>
            <p style={{ fontSize: 12.5, lineHeight: 1.5 }}>
              The AI reads every page of the drawing — dimensions, holes, threads,
              notes, title block — and builds a quotable part from it. Nothing is
              priced until you review what was read.
            </p>
            <button className="btn primary" onClick={() => void extract()}>
              ⛏ Extract drawing data
            </button>
          </>
        )}

        {busy && (
          <div className="assistant-bubble assistant loading" style={{ margin: "8px 0" }}>
            {stage === "extracting" && "Reading the drawing…"}
            {stage === "comparing" && "Comparing drawing against STEP…"}
            {stage === "synthesizing" && "Building the 3D part from the drawing…"}
            {stage === "pricing_both" && "Estimating both versions…"}
          </div>
        )}

        {(stage === "review" || stage === "compare_report" || busy) && extraction && (
          <div style={{ marginTop: 8 }}>
            {fixture && (
              <div className="scope-note" style={{ marginBottom: 8 }}>
                Fixture mode — canned extraction for testing (AI_EXTRACT_FIXTURE).
              </div>
            )}
            <div className="section-title">Extracted from the drawing</div>
            <table className="drawing-table">
              <tbody>
                <tr><td>Part</td><td>{extraction.part.name ?? "—"} {extraction.part.drawing_number ? `(${extraction.part.drawing_number} rev ${extraction.part.revision ?? "-"})` : ""}</td></tr>
                <tr><td>Material</td><td>{extraction.part.material ?? "— not stated"}</td></tr>
                <tr><td>Envelope</td><td>{extraction.part.envelope_mm ? `${extraction.part.envelope_mm.length} × ${extraction.part.envelope_mm.width} × ${extraction.part.envelope_mm.height} mm` : "— incomplete"}</td></tr>
                <tr><td>Quantity</td><td>{extraction.part.quantity ?? "— not stated"}</td></tr>
                <tr><td>Confidence</td><td className={`conf-${extraction.overall_confidence}`}>{extraction.overall_confidence.toUpperCase()}</td></tr>
              </tbody>
            </table>

            <div className="section-title" style={{ marginTop: 10 }}>Features</div>
            {extraction.features.map((f, i) => (
              <div key={i} className="drawing-feature">
                <span className={`conf-dot conf-${f.confidence}`} title={`confidence: ${f.confidence}`} />
                {f.count}× {f.kind}
                {f.diameter_mm != null && ` Ø${f.diameter_mm}`}
                {f.thread_spec && ` ${f.thread_spec}`}
                {f.through === true ? " (thru)" : f.depth_mm != null ? ` ↓${f.depth_mm}` : f.through === null && f.depth_mm == null ? " (depth unconfirmed)" : ""}
                {f.tolerance_note && <span style={{ color: "var(--text-2)" }}> · {f.tolerance_note}</span>}
              </div>
            ))}

            {extraction.caveats.length > 0 && (
              <>
                <div className="section-title" style={{ marginTop: 10 }}>⚠ Could not read</div>
                {extraction.caveats.map((c, i) => (
                  <div key={i} className="drawing-caveat">{c}</div>
                ))}
              </>
            )}

            {stage === "review" && (
              <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
                <button className="btn primary" onClick={() => void quoteFromDrawing()}>
                  ✔ Quote from the drawing (build 3D part)
                </button>
                <button className="btn" onClick={() => stepInputRef.current?.click()}>
                  📎 I also have the STEP file — compare them
                </button>
                <input
                  ref={stepInputRef}
                  type="file"
                  accept=".step,.stp"
                  style={{ display: "none" }}
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) void compareWith(f);
                    e.target.value = "";
                  }}
                />
              </div>
            )}
          </div>
        )}

        {stage === "compare_report" && report && (
          <div style={{ marginTop: 14 }}>
            <div className="section-title">Drawing vs STEP</div>
            <div className={`drawing-verdict verdict-${report.verdict}`}>
              {report.verdict === "CONSISTENT" && "✓ Consistent — drawing and STEP agree"}
              {report.verdict === "MINOR_MISMATCH" && "△ Minor mismatches — review below"}
              {report.verdict === "MAJOR_MISMATCH" && "✗ MAJOR mismatch — the drawing and STEP describe different parts"}
            </div>

            <div className="drawing-row" style={{ borderLeftColor: STATUS_COLOR[report.envelope.status === "MATCHED" ? "MATCHED" : "DIM_MISMATCH"] }}>
              <b>Envelope:</b> drawing {report.envelope.drawing_mm.join("×")} vs STEP {report.envelope.step_mm.join("×")} mm — {report.envelope.status}
            </div>
            {report.features.map((r, i) => (
              <div key={i} className="drawing-row" style={{ borderLeftColor: STATUS_COLOR[r.status] ?? "var(--text-2)" }}>
                <b>{r.status.replace(/_/g, " ")}:</b> {r.detail}
              </div>
            ))}
            {report.extra_in_step.map((r, i) => (
              <div key={`x${i}`} className="drawing-row" style={{ borderLeftColor: STATUS_COLOR.EXTRA_IN_STEP }}>
                <b>EXTRA IN STEP:</b> {r.detail}
              </div>
            ))}

            {both && (
              <>
                <div className="section-title" style={{ marginTop: 10 }}>Both versions — quick comparison</div>
                <table className="drawing-table">
                  <tbody>
                    <tr><td></td><td><b>Drawing</b></td><td><b>STEP</b></td></tr>
                    <tr><td>Machine time</td><td>{both.drawing.min.toFixed(1)} min</td><td>{both.step.min.toFixed(1)} min</td></tr>
                    <tr><td>Setups</td><td>{both.drawing.setups}</td><td>{both.step.setups}</td></tr>
                    <tr><td>Quick price*</td><td>{currency}{both.drawing.price.toLocaleString()}</td><td>{currency}{both.step.price.toLocaleString()}</td></tr>
                    <tr><td>Difference</td><td colSpan={2}><b>{currency}{Math.abs(both.drawing.price - both.step.price).toLocaleString()}</b> — {both.drawing.price > both.step.price ? "drawing version costs more" : both.drawing.price < both.step.price ? "STEP version costs more" : "equal"}</td></tr>
                  </tbody>
                </table>
                <div style={{ fontSize: 10.5, color: "var(--text-2)", marginTop: 4 }}>
                  *machining {currency}{rateHr}/hr + setups {currency}{setupCharge} — open a version for the full ledger.
                </div>
              </>
            )}

            <div style={{ display: "flex", flexDirection: "column", gap: 8, marginTop: 14 }}>
              <button className="btn primary" onClick={() => void quoteFromDrawing()}>
                Use the DRAWING version
              </button>
              <button
                className="btn primary"
                onClick={() => stepFile && onQuote(stepFile, "Quoting the STEP version — drawing mismatches noted.")}
              >
                Use the STEP version
              </button>
              {!both && (
                <button className="btn" onClick={() => void priceBoth()}>
                  ⚖ Consider both — show price difference
                </button>
              )}
            </div>
          </div>
        )}

        {synWarnings.length > 0 && stage === "synthesizing" && (
          <div style={{ marginTop: 10 }}>
            {synWarnings.map((w, i) => (
              <div key={i} className="drawing-caveat">{w}</div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
