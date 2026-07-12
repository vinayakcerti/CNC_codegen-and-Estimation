// Rate-card editor (ARD R3 §6.5): per-machine costing profile content —
// milling rates, this-part hole confirm list, the filterable hole cost
// library with CSV in/out, and the audit footer.
// Orange = estimated (not confirmed by the shop) · Green = confirmed.
// Every change is audit-logged via updateProfile + audit. Rendered inside
// the CostLibraryPanel modal AND inline on the Shop Library screen.
import { useMemo, useRef, useState } from "react";
import {
  audit, csvToLibrary, libraryToCsv, updateProfile,
  type CostingProfile, type HoleCostRow, type RateCardBreakdown,
  type ToleranceClass,
} from "./costing";

const TOLS: ToleranceClass[] = ["H6", "H7", "H8", "H9", "H11", "free", "thread"];

// Hole-making operations: everything the planner emits today plus the ops
// shops commonly quote (the tester's Drill / Drill+Ream seeds included).
// NOTE: the pricing lookup keys on (Ø, tolerance, thickness) — this column
// documents HOW the shop achieves the hole; "Custom…" keeps it open-ended.
const HOLE_OPERATIONS = [
  "Drill", "Spot Drill", "Pilot Drill", "Drill+Ream", "Ream",
  "Bore", "Bore+Ream", "Tap", "Drill+Tap", "Thread Mill",
  "Counter-bore", "Countersink", "Drill+Counter-bore", "Drill+Countersink",
  "Jig Bore", "Gun Drill", "Honing",
];

export function RateCardEditor({
  profile,
  currency,
  partHoles = null,
  onChanged,
}: {
  profile: CostingProfile;
  currency: string;
  // The loaded part's hole lookups (rate-card breakdown) — surfaces a
  // "confirm what you quote" list so the shop signs off the operations of
  // THIS part first; the full library below is for everything else.
  partHoles?: RateCardBreakdown["holes"] | null;
  // Bump a nonce in the parent so estimates re-read the stored profile.
  onChanged: () => void;
}) {
  const [tolFilter, setTolFilter] = useState<string>("all");
  const [diaFilter, setDiaFilter] = useState<string>("");
  const [partVals, setPartVals] = useState<Record<string, string>>({});
  const fileRef = useRef<HTMLInputElement>(null);

  // One row per distinct (Ø, tolerance, depth) spec on the part — confirming
  // a spec covers every hole of that size here and on future parts.
  const partSpecs = useMemo(() => {
    const m = new Map<
      string,
      {
        dia: number; tolerance: ToleranceClass; thickness: number;
        count: number; cost: number; estimated: boolean; note: string;
      }
    >();
    for (const h of partHoles ?? []) {
      const k = `${h.dia.toFixed(1)}|${h.tolerance}|${h.thickness.toFixed(1)}`;
      const e = m.get(k);
      if (e) {
        e.count++;
        e.estimated = e.estimated || h.estimated;
      } else {
        m.set(k, {
          dia: h.dia, tolerance: h.tolerance, thickness: h.thickness,
          count: 1, cost: h.cost, estimated: h.estimated, note: h.note,
        });
      }
    }
    return [...m.values()].sort((a, b) => a.dia - b.dia || a.thickness - b.thickness);
  }, [partHoles]);

  const rows = useMemo(() => {
    let r = profile.holeLibrary;
    if (tolFilter !== "all") r = r.filter((x) => x.tolerance === tolFilter);
    const d = parseFloat(diaFilter);
    if (Number.isFinite(d)) r = r.filter((x) => Math.abs(x.diameter_mm - d) < 0.26);
    return [...r].sort(
      (a, b) =>
        a.tolerance.localeCompare(b.tolerance) ||
        a.diameter_mm - b.diameter_mm ||
        a.thickness_mm - b.thickness_mm,
    );
  }, [profile.holeLibrary, tolFilter, diaFilter]);

  function commit(next: CostingProfile, action: string, before: string, after: string) {
    updateProfile(audit(next, action, before, after));
    onChanged();
  }

  function setRow(id: string, patch: Partial<HoleCostRow>, action: string) {
    const before = profile.holeLibrary.find((r) => r.id === id);
    const next = {
      ...profile,
      holeLibrary: profile.holeLibrary.map((r) =>
        r.id === id ? { ...r, ...patch } : r,
      ),
    };
    commit(next, action, JSON.stringify(before ?? {}), JSON.stringify(patch));
  }

  function addRow() {
    const row: HoleCostRow = {
      id: `row-${Date.now()}`,
      diameter_mm: 10, tolerance: "H7", thickness_mm: 20,
      operation: "Drill", cost_inr: 0,
      effective_from: new Date().toISOString().slice(0, 10),
      source: "manual", confirmed: false,
    };
    commit(
      { ...profile, holeLibrary: [...profile.holeLibrary, row] },
      "add_row", "", JSON.stringify(row),
    );
  }

  function deleteRow(id: string) {
    const before = profile.holeLibrary.find((r) => r.id === id);
    commit(
      { ...profile, holeLibrary: profile.holeLibrary.filter((r) => r.id !== id) },
      "delete_row", JSON.stringify(before ?? {}), "",
    );
  }

  // Confirm a part spec: update the matching library row, or seed a new
  // CONFIRMED exact row — future lookups of this Ø/tol/depth go green.
  function confirmPartSpec(
    s: { dia: number; tolerance: ToleranceClass; thickness: number },
    cost: number,
  ) {
    const today = new Date().toISOString().slice(0, 10);
    const match = profile.holeLibrary.find(
      (r) =>
        r.tolerance === s.tolerance &&
        Math.abs(r.diameter_mm - s.dia) < 0.26 &&
        Math.abs(r.thickness_mm - s.thickness) < 0.51,
    );
    if (match) {
      setRow(match.id, {
        cost_inr: cost, confirmed: true,
        source: "confirmed from part quote", effective_from: today,
      }, "confirm_part_spec");
      return;
    }
    const row: HoleCostRow = {
      id: `part-${Date.now()}-${Math.round(s.dia * 10)}`,
      diameter_mm: s.dia, tolerance: s.tolerance, thickness_mm: s.thickness,
      operation: s.tolerance === "thread" ? "Tap" : "Drill+Ream",
      cost_inr: cost, effective_from: today,
      source: "confirmed from part quote", confirmed: true,
    };
    commit(
      { ...profile, holeLibrary: [...profile.holeLibrary, row] },
      "confirm_part_spec", "", JSON.stringify(row),
    );
  }

  function exportCsv() {
    const blob = new Blob([libraryToCsv(profile.holeLibrary)], {
      type: "text/csv;charset=utf-8",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${profile.name.replace(/[^\w-]+/g, "_")}_hole_cost_library.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  function importCsv(file: File) {
    const reader = new FileReader();
    reader.onload = () => {
      const imported = csvToLibrary(String(reader.result || ""));
      if (!imported.length) return;
      commit(
        { ...profile, holeLibrary: imported },
        "csv_import", `${profile.holeLibrary.length} rows`, `${imported.length} rows`,
      );
    };
    reader.readAsText(file);
  }

  const numCell = (
    value: number, onChange: (v: number) => void, width = 64, step = 0.01,
  ) => (
    <input
      className="num-input" type="number" step={step} value={value}
      style={{ width }}
      onChange={(e) => {
        const v = parseFloat(e.target.value);
        if (Number.isFinite(v)) onChange(v);
      }}
    />
  );

  return (
    <>
      <div style={{ fontSize: 12, color: "var(--text-2)", marginBottom: 10 }}>
        <span style={{ color: "#2e9e5b" }}>■ confirmed by shop</span>
        {"  ·  "}
        <span style={{ color: "#c07a2a" }}>■ estimated — click Confirm once the shop signs off</span>
        {"  ·  saved on this computer (CSV below to back up / move)"}
      </div>

      {/* Milling + add-on rates */}
      <div className="qm-sect">Milling rates ({currency}/cm² of machined surface)</div>
      <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginBottom: 10 }}>
        <label style={{ fontSize: 12 }}>
          Without grinding{" "}
          {numCell(profile.milling_rate_per_cm2, (v) =>
            commit(
              { ...profile, milling_rate_per_cm2: v },
              "milling_rate", String(profile.milling_rate_per_cm2), String(v),
            ),
          )}
        </label>
        <label style={{ fontSize: 12 }}>
          With grinding{" "}
          {numCell(profile.milling_rate_grinding_per_cm2, (v) =>
            commit(
              { ...profile, milling_rate_grinding_per_cm2: v },
              "milling_rate_grinding",
              String(profile.milling_rate_grinding_per_cm2), String(v),
            ),
          )}
        </label>
      </div>

      {/* This part first: confirm the operations actually being quoted */}
      {partSpecs.length > 0 && (
        <>
          <div className="qm-sect">
            This part’s hole operations ({partSpecs.length} size
            {partSpecs.length > 1 ? "s" : ""}) — confirm what you quote
          </div>
          <table className="dense-table" style={{ width: "100%" }}>
            <thead>
              <tr>
                <th>Ø (mm)</th><th>Tol</th><th>Depth (mm)</th><th>Holes</th>
                <th>Price ({currency})</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {partSpecs.map((s) => {
                const k = `${s.dia.toFixed(1)}|${s.tolerance}|${s.thickness.toFixed(1)}`;
                return (
                  <tr
                    key={k}
                    style={{
                      background: s.estimated
                        ? "rgba(192,122,42,0.14)"
                        : "rgba(46,158,91,0.10)",
                    }}
                  >
                    <td>{s.dia.toFixed(1)}</td>
                    <td>{s.tolerance}</td>
                    <td>{s.thickness.toFixed(1)}</td>
                    <td>×{s.count}</td>
                    <td>
                      {s.estimated ? (
                        <input
                          className="num-input" type="number" style={{ width: 72 }}
                          title={`Our estimate: ${s.cost} (${s.note}) — correct it if you know the real price`}
                          value={partVals[k] ?? String(s.cost)}
                          onChange={(e) =>
                            setPartVals((v) => ({ ...v, [k]: e.target.value }))
                          }
                        />
                      ) : (
                        s.cost
                      )}
                    </td>
                    <td>
                      {s.estimated ? (
                        <button
                          className="btn"
                          style={{ color: "#c07a2a" }}
                          title="Save as a CONFIRMED library price for this Ø / tolerance / depth"
                          onClick={() => {
                            const v = parseFloat(partVals[k] ?? String(s.cost));
                            if (Number.isFinite(v)) confirmPartSpec(s, v);
                          }}
                        >
                          Confirm
                        </button>
                      ) : (
                        <span style={{ color: "#2e9e5b", fontSize: 11, fontWeight: 600 }}>
                          confirmed
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <div style={{ fontSize: 11, color: "var(--text-2)", margin: "4px 0 6px" }}>
            Confirming writes the price into the library below — every future
            part with the same Ø/tolerance/depth prices green automatically.
          </div>
        </>
      )}

      {/* Hole library */}
      <div className="qm-sect" style={{ display: "flex", alignItems: "center", gap: 8 }}>
        Hole cost library ({profile.holeLibrary.length} rows)
        <span style={{ flex: 1 }} />
        <select
          className="mini-select" value={tolFilter}
          onChange={(e) => setTolFilter(e.target.value)}
        >
          <option value="all">All tolerances</option>
          {TOLS.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
        <input
          className="num-input" placeholder="Ø filter" style={{ width: 70 }}
          value={diaFilter} onChange={(e) => setDiaFilter(e.target.value)}
        />
        <button className="btn" onClick={addRow}>+ Add row</button>
        <button className="btn" onClick={exportCsv}>Export CSV</button>
        <button className="btn" onClick={() => fileRef.current?.click()}>Import CSV</button>
        <input
          ref={fileRef} type="file" accept=".csv" style={{ display: "none" }}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) importCsv(f);
            e.target.value = "";
          }}
        />
      </div>
      <div style={{ maxHeight: "42vh", overflow: "auto" }}>
        <table className="dense-table" style={{ width: "100%" }}>
          <thead>
            <tr>
              <th>Ø (mm)</th><th>Tol</th><th>Thickness (mm)</th><th>Operation</th>
              <th>Cost ({currency})</th><th>Effective</th><th>Source</th>
              <th>Status</th><th></th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr
                key={r.id}
                style={{
                  background: r.confirmed
                    ? "rgba(46,158,91,0.10)"
                    : "rgba(192,122,42,0.14)",
                }}
              >
                <td>{numCell(r.diameter_mm, (v) => setRow(r.id, { diameter_mm: v }, "edit_dia"), 58, 0.1)}</td>
                <td>
                  <select
                    className="mini-select" value={r.tolerance}
                    onChange={(e) =>
                      setRow(r.id, { tolerance: e.target.value as ToleranceClass }, "edit_tol")
                    }
                  >
                    {TOLS.map((t) => <option key={t} value={t}>{t}</option>)}
                  </select>
                </td>
                <td>{numCell(r.thickness_mm, (v) => setRow(r.id, { thickness_mm: v }, "edit_thickness"), 58, 0.5)}</td>
                <td>
                  <select
                    className="mini-select"
                    style={{ width: 118 }}
                    value={r.operation}
                    onChange={(e) => {
                      const v = e.target.value;
                      if (v === "__custom__") {
                        const c = window.prompt("Operation name:", r.operation);
                        if (c && c.trim())
                          setRow(r.id, { operation: c.trim() }, "edit_operation");
                        return;
                      }
                      setRow(r.id, { operation: v }, "edit_operation");
                    }}
                  >
                    {!HOLE_OPERATIONS.includes(r.operation) && (
                      <option value={r.operation}>{r.operation}</option>
                    )}
                    {HOLE_OPERATIONS.map((o) => (
                      <option key={o} value={o}>{o}</option>
                    ))}
                    <option value="__custom__">Custom…</option>
                  </select>
                </td>
                <td>
                  {numCell(r.cost_inr, (v) =>
                    // A manual price entered by the user counts as confirmed.
                    setRow(r.id, {
                      cost_inr: v, confirmed: true,
                      source: "manual entry",
                      effective_from: new Date().toISOString().slice(0, 10),
                    }, "edit_cost"),
                  68, 1)}
                </td>
                <td style={{ fontSize: 11 }}>{r.effective_from}</td>
                <td style={{ fontSize: 11 }} title={r.source}>
                  {r.source.length > 18 ? r.source.slice(0, 17) + "…" : r.source}
                </td>
                <td>
                  {r.confirmed ? (
                    <span style={{ color: "#2e9e5b", fontSize: 11, fontWeight: 600 }}>
                      confirmed
                    </span>
                  ) : (
                    <button
                      className="btn"
                      style={{ color: "#c07a2a" }}
                      title="Shop has signed off this price — mark it confirmed"
                      onClick={() =>
                        setRow(r.id, {
                          confirmed: true,
                          source: r.source + " · confirmed",
                          effective_from: new Date().toISOString().slice(0, 10),
                        }, "confirm_row")
                      }
                    >
                      Confirm
                    </button>
                  )}
                </td>
                <td>
                  <button
                    className="btn" title="Delete row"
                    onClick={() => deleteRow(r.id)}
                  >
                    ✕
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: "var(--text-2)", marginTop: 8 }}>
        Lookup order: exact (Ø, tol, thickness) → thickness interpolation →
        nearest standard Ø → generic estimate (always orange). {profile.auditLog.length}
        {" "}edits logged.
      </div>
    </>
  );
}
