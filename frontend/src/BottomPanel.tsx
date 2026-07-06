import { useEffect, useRef, useState } from "react";
import type { PointerEvent as ReactPointerEvent } from "react";
import { api } from "./api";
import type { Candidate, ToolInfo } from "./api";
import { lsGet, lsSet } from "./storage";

// Bottom panel under the 3D canvas: a small centered view switcher
// ("Tool Table" | "Feature Table" — extensible via VIEWS) over a dense
// data table. Resizable by dragging its top edge (double-click collapses);
// open state + selected view + height persist in localStorage.

type PanelView = "tools" | "features";

const VIEWS: { id: PanelView; label: string }[] = [
  { id: "tools", label: "Tool Table" },
  { id: "features", label: "Feature Table" },
];

const PANEL_MIN = 120;
const PANEL_DEFAULT = 220;
// Max is viewport-relative — read live so it tracks window resizes.
const panelMax = () => Math.round(window.innerHeight * 0.6);

function loadPanelHeight(): number {
  const v = Number(lsGet("cnc.bottomPanel.height"));
  return Number.isFinite(v) && v >= PANEL_MIN ? Math.min(v, panelMax()) : PANEL_DEFAULT;
}

const fmt = (v: unknown, digits = 1): string =>
  typeof v === "number" && Number.isFinite(v) ? v.toFixed(digits) : "—";

export function BottomPanel({ candidates }: { candidates: Candidate[] }) {
  const [open, setOpen] = useState(() => lsGet("cnc.bottomPanel.open") !== "0");
  const [view, setView] = useState<PanelView>(() =>
    lsGet("cnc.bottomPanel.view") === "features" ? "features" : "tools",
  );
  const [tools, setTools] = useState<ToolInfo[] | null>(null);
  const [toolsErr, setToolsErr] = useState(false);

  // Drag-to-resize via the top-edge handle — same pointer-capture pattern
  // as the inspector's vertical handle, on the Y axis.
  const [height, setHeight] = useState<number>(loadPanelHeight);
  const [dragging, setDragging] = useState(false);
  const dragRef = useRef<{ startY: number; startH: number } | null>(null);

  function onHandleDown(e: ReactPointerEvent<HTMLDivElement>) {
    dragRef.current = { startY: e.clientY, startH: height };
    setDragging(true);
    e.currentTarget.setPointerCapture(e.pointerId);
    document.body.style.userSelect = "none";
    document.body.style.cursor = "row-resize";
  }

  function onHandleMove(e: ReactPointerEvent<HTMLDivElement>) {
    const d = dragRef.current;
    if (!d) return;
    // Dragging UP (smaller clientY) grows the panel.
    const h = Math.min(panelMax(), Math.max(PANEL_MIN, d.startH + (d.startY - e.clientY)));
    setHeight(h);
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
    lsSet("cnc.bottomPanel.height", String(height));
  }

  function collapse() {
    setOpen(false);
    lsSet("cnc.bottomPanel.open", "0");
  }

  useEffect(() => {
    let alive = true;
    api
      .tools()
      .then((r) => {
        if (alive) setTools(r.tools);
      })
      .catch(() => {
        if (alive) setToolsErr(true);
      });
    return () => {
      alive = false;
    };
  }, []);

  function toggleOpen() {
    setOpen((o) => {
      lsSet("cnc.bottomPanel.open", o ? "0" : "1");
      return !o;
    });
  }

  function pickView(v: PanelView) {
    setView(v);
    lsSet("cnc.bottomPanel.view", v);
    if (!open) {
      setOpen(true);
      lsSet("cnc.bottomPanel.open", "1");
    }
  }

  return (
    <div className={`bottom-panel ${open ? "open" : ""}`} style={open ? { height } : undefined}>
      {open && (
        <div
          className={`bp-handle ${dragging ? "dragging" : ""}`}
          title="Drag to resize · double-click to collapse"
          onPointerDown={onHandleDown}
          onPointerMove={onHandleMove}
          onPointerUp={onHandleUp}
          onPointerCancel={onHandleUp}
          onDoubleClick={collapse}
        />
      )}
      <div className="bp-header">
        <div className="bp-switch">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              type="button"
              className={view === v.id && open ? "active" : ""}
              onClick={() => pickView(v.id)}
            >
              {v.label}
            </button>
          ))}
        </div>
        <button
          type="button"
          className="bp-chevron"
          title={open ? "Collapse panel" : "Expand panel"}
          onClick={toggleOpen}
        >
          {open ? "▾" : "▴"}
        </button>
      </div>

      {open && (
        <div className="bp-body">
          {view === "tools" &&
            (tools ? (
              <>
                <table className="dense-table">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Name</th>
                      <th>Type</th>
                      <th>Ø (mm)</th>
                      <th>Flutes</th>
                      <th>Tip</th>
                      <th>Flute len (mm)</th>
                      <th>Max depth (mm)</th>
                    </tr>
                  </thead>
                  <tbody>
                    {tools.map((t) => (
                      <tr key={t.tool_number}>
                        <td>T{t.tool_number}</td>
                        <td title={t.tool_name}>{t.display_name || t.tool_name}</td>
                        <td>{t.tool_type}</td>
                        <td>{fmt(t.diameter_mm)}</td>
                        <td>{t.flutes ?? "—"}</td>
                        <td>{t.tip_angle != null ? `${t.tip_angle}°` : "—"}</td>
                        <td>{fmt(t.flute_length_mm)}</td>
                        <td>{fmt(t.max_depth_mm)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {tools[0]?.source_library && (
                  <div className="bp-msg" style={{ padding: "6px 10px" }}>
                    {tools[0].source_library}
                  </div>
                )}
              </>
            ) : (
              <div className="bp-msg">{toolsErr ? "Tool library unavailable" : "Loading tools…"}</div>
            ))}

          {view === "features" &&
            (candidates.length ? (
              <table className="dense-table">
                <thead>
                  <tr>
                    <th>Type</th>
                    <th>Name</th>
                    <th>Ø (mm)</th>
                    <th>L (mm)</th>
                    <th>W (mm)</th>
                    <th>Depth (mm)</th>
                    <th>Confidence</th>
                    <th>Setup</th>
                  </tr>
                </thead>
                <tbody>
                  {candidates.map((c, i) => (
                    <tr key={c.candidate_id ?? i}>
                      <td>{c.feature_type || "—"}</td>
                      <td>{c.feature_name || "—"}</td>
                      <td>{fmt(c.diameter, 2)}</td>
                      <td>{fmt(c.length)}</td>
                      <td>{fmt(c.width)}</td>
                      <td>{fmt(c.depth)}</td>
                      <td>{c.confidence || "—"}</td>
                      <td>{c.setup || "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <div className="bp-msg">No detected features</div>
            ))}
        </div>
      )}
    </div>
  );
}
