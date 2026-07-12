// Shop Library screen: the shop's machine list on the left (curate "my
// machines" with checkboxes; empty set = using all machines), and for the
// selected machine on the right: read-only parameters plus its rate card
// edited INLINE via RateCardEditor (one costing profile = one machine's
// rate card, see costing.ts). "Copy prices from…" clones another machine's
// rates + hole library into this card.
import { useMemo, useState } from "react";
import type { MachineInfo } from "./api";
import { machineName, type CustomMachine } from "./MachineSelect";
import {
  audit, loadProfiles, profileForMachine, updateProfile,
  type CostingProfile,
} from "./costing";
import { RateCardEditor } from "./RateCardEditor";

const numOr = (s: string, fallback: number) => {
  const v = parseFloat(s);
  return Number.isFinite(v) && v >= 0 ? v : fallback;
};

// Read-only parameter rows — render whatever fields the library machine
// actually carries (engine defaults use machine_name/axis_count variants).
function libParamRows(m: MachineInfo): [string, string][] {
  const rows: [string, string][] = [];
  const add = (k: string, v: string | number | null | undefined, unit = "") => {
    if (v === undefined || v === null || v === "") return;
    rows.push([k, `${v}${unit}`]);
  };
  add("Maker", m.maker);
  add("Type", m.type ?? m.machine_type);
  add("Axes", m.axes ?? m.axis_count);
  if (m.travel_x_mm != null || m.travel_y_mm != null || m.travel_z_mm != null) {
    rows.push([
      "Travel X / Y / Z",
      `${m.travel_x_mm ?? "—"} / ${m.travel_y_mm ?? "—"} / ${m.travel_z_mm ?? "—"} mm`,
    ]);
  }
  add("Max spindle", m.max_spindle_rpm, " rpm");
  add("Spindle power", m.spindle_power_kw, " kW");
  add("Tool capacity", m.tool_capacity, " tools");
  add("Controller", m.controller);
  add("Rapid feed", m.rapid_feed_rate, " mm/min");
  add("Tool change", m.tool_change_time_s, " s");
  add("Setup time", m.setup_time_min, " min");
  add("Region", m.region);
  return rows;
}

function customParamRows(m: CustomMachine): [string, string][] {
  const rows: [string, string][] = [
    ["Axes", String(m.axes)],
    ["Max spindle", `${m.max_spindle_rpm} rpm`],
    ["Rapid feed", `${m.rapid_feed_rate} mm/min`],
    ["Tool change", `${m.tool_change_time_s} s`],
    ["Setup time", `${m.setup_time_min} min`],
  ];
  if (m.controller) rows.push(["Controller", m.controller]);
  return rows;
}

// Inline "+ Add machine" form: name required; axes / rpm / controller
// optional (engine defaults fill the rest, as in the machine dropdown).
function AddMachineInlineForm({
  onSave,
  onCancel,
}: {
  onSave: (m: CustomMachine) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [axes, setAxes] = useState(3);
  const [rpm, setRpm] = useState(8000);
  const [controller, setController] = useState("");

  return (
    <div className="route-form" style={{ marginTop: 10 }}>
      <div className="mat-form-row">
        <span>Name *</span>
        <input
          className="num-input"
          style={{ width: 140, textAlign: "left" }}
          placeholder="My VMC"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      <div className="mat-form-row">
        <span>Axes</span>
        <input
          className="num-input" type="number" min={0} style={{ width: 140 }}
          value={axes}
          onChange={(e) => setAxes(numOr(e.target.value, 3))}
        />
      </div>
      <div className="mat-form-row">
        <span>Max spindle rpm</span>
        <input
          className="num-input" type="number" min={0} style={{ width: 140 }}
          value={rpm}
          onChange={(e) => setRpm(numOr(e.target.value, 8000))}
        />
      </div>
      <div className="mat-form-row">
        <span>Controller</span>
        <input
          className="num-input"
          style={{ width: 140, textAlign: "left" }}
          placeholder="e.g. Fanuc (optional)"
          value={controller}
          onChange={(e) => setController(e.target.value)}
        />
      </div>
      <div className="mat-form-actions">
        <button
          type="button" className="btn"
          style={{ padding: "3px 10px", fontSize: 11 }}
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button" className="btn primary"
          style={{ padding: "3px 10px", fontSize: 11 }}
          disabled={!name.trim()}
          onClick={() => {
            const m: CustomMachine = {
              name: name.trim(),
              max_spindle_rpm: rpm,
              axes,
              // Same engine defaults as the machine dropdown's add form.
              rapid_feed_rate: 24000,
              tool_change_time_s: 5,
              setup_time_min: 20,
            };
            if (controller.trim()) m.controller = controller.trim();
            onSave(m);
          }}
        >
          Save machine
        </button>
      </div>
    </div>
  );
}

export function ShopLibrary({
  machines,
  customMachines,
  myMachines,
  onToggleMyMachine,
  onAddCustomMachine,
  currency,
  profilesNonce,
  onProfilesChanged,
}: {
  machines: MachineInfo[]; // backend defaults (/api/machines)
  customMachines: CustomMachine[]; // user-added
  // Machine names the shop actually uses; EMPTY set = "all machines".
  myMachines: Set<string>;
  onToggleMyMachine: (name: string) => void;
  onAddCustomMachine: (m: CustomMachine) => void;
  currency: string; // display symbol, e.g. "₹"
  // Re-read stored costing profiles whenever this bumps.
  profilesNonce: number;
  onProfilesChanged: () => void;
}) {
  const [picked, setPicked] = useState<string>("");
  const [adding, setAdding] = useState(false);
  const [copyFromId, setCopyFromId] = useState("");

  // Defaults first, then customs marked "custom". A custom machine wins a
  // name collision (same rule as the machine dropdown); default names are
  // deduped so row keys stay unique.
  const entries = useMemo(() => {
    const customNames = new Set(customMachines.map((c) => c.name));
    const seen = new Set<string>();
    const defaults: { name: string; custom: boolean }[] = [];
    for (const m of machines) {
      const n = machineName(m);
      if (!n || customNames.has(n) || seen.has(n)) continue;
      seen.add(n);
      defaults.push({ name: n, custom: false });
    }
    return [...defaults, ...customMachines.map((c) => ({ name: c.name, custom: true }))];
  }, [machines, customMachines]);

  // Selected machine: the clicked row, falling back to the first entry.
  const selName = entries.some((e) => e.name === picked)
    ? picked
    : (entries[0]?.name ?? "");

  // One costing profile per machine — created from the default rate card on
  // first visit. Recomputed when the parent bumps profilesNonce.
  const profile = useMemo(
    () => (selName ? profileForMachine(selName) : null),
    // profilesNonce forces a re-read of localStorage after edits
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [selName, profilesNonce],
  );
  const otherProfiles = useMemo(
    () => loadProfiles().filter((p) => p.id !== profile?.id),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [profile?.id, profilesNonce],
  );

  const curated = myMachines.size > 0;
  const selCustom = customMachines.find((c) => c.name === selName) ?? null;
  const selLib = selCustom
    ? null
    : (machines.find((m) => machineName(m) === selName) ?? null);
  const paramRows: [string, string][] = selCustom
    ? customParamRows(selCustom)
    : selLib
      ? libParamRows(selLib)
      : [];

  // Replace this machine's prices with another card's (deep copy rows,
  // keep this profile's id/name/model). Audit-logged as copy_from.
  function copyPrices() {
    if (!profile) return;
    const src = otherProfiles.find((p) => p.id === copyFromId);
    if (!src) return;
    if (!window.confirm(`Replace this machine's prices with ${src.name}?`)) return;
    const next: CostingProfile = {
      ...profile,
      milling_rate_per_cm2: src.milling_rate_per_cm2,
      milling_rate_grinding_per_cm2: src.milling_rate_grinding_per_cm2,
      addon_rates: { ...src.addon_rates },
      holeLibrary: src.holeLibrary.map((r) => ({ ...r })),
    };
    updateProfile(audit(next, "copy_from", src.name, profile.name));
    onProfilesChanged();
  }

  return (
    <div className="shop-lib">
      {/* LEFT: the shop's machines */}
      <div className="shop-machines">
        <div className="section-title" style={{ marginTop: 0 }}>
          My Shop — Machines
        </div>
        {!curated && (
          <div className="shop-hint">using all machines — tick to curate</div>
        )}
        <div className="shop-machine-list">
          {entries.map((e) => (
            <div
              key={(e.custom ? "c:" : "d:") + e.name}
              className={
                "shop-machine-row" +
                (e.name === selName ? " sel" : "") +
                (!curated ? " implicit" : "")
              }
              onClick={() => setPicked(e.name)}
            >
              <input
                type="checkbox"
                checked={curated ? myMachines.has(e.name) : true}
                title={
                  curated
                    ? myMachines.has(e.name)
                      ? "In my shop — untick to remove"
                      : "Tick to add to my shop"
                    : "using all machines — tick to curate"
                }
                onClick={(ev) => ev.stopPropagation()}
                onChange={() => onToggleMyMachine(e.name)}
              />
              <span className="name" title={e.name}>{e.name}</span>
              {e.custom && <span className="chip">custom</span>}
            </div>
          ))}
          {entries.length === 0 && (
            <div className="bp-msg">No machines yet — add one below.</div>
          )}
        </div>
        {adding ? (
          <AddMachineInlineForm
            onCancel={() => setAdding(false)}
            onSave={(m) => {
              onAddCustomMachine(m);
              setPicked(m.name);
              setAdding(false);
            }}
          />
        ) : (
          <button className="btn route-add" onClick={() => setAdding(true)}>
            + Add machine
          </button>
        )}
      </div>

      {/* RIGHT: parameters + rate card for the selected machine */}
      <div className="shop-detail">
        {!selName || !profile ? (
          <div className="bp-msg">
            Select a machine on the left to see its parameters and rate card.
          </div>
        ) : (
          <>
            <div className="section-title" style={{ marginTop: 0 }}>
              Machine parameters{selCustom ? " (custom)" : ""}
            </div>
            {paramRows.length > 0 ? (
              paramRows.map(([k, v]) => (
                <div className="row" key={k}>
                  <span className="k">{k}</span>
                  <span className="v">{v}</span>
                </div>
              ))
            ) : (
              <div className="bp-msg">No parameters on record for this machine.</div>
            )}
            <div className="shop-note">
              Parameters are read-only — custom machine editing lands with the
              shop database (v1).
            </div>

            <div className="section-title">Rate card — {profile.name}</div>
            <div className="shop-copy-row">
              <span style={{ fontSize: 12, color: "var(--text-1)" }}>
                Copy prices from…
              </span>
              <select
                className="mini-select"
                style={{ maxWidth: 220 }}
                value={copyFromId}
                onChange={(e) => setCopyFromId(e.target.value)}
              >
                <option value="">Select rate card…</option>
                {otherProfiles.map((p) => (
                  <option key={p.id} value={p.id}>{p.name}</option>
                ))}
              </select>
              <button className="btn" disabled={!copyFromId} onClick={copyPrices}>
                Copy
              </button>
            </div>
            <RateCardEditor
              key={profile.id}
              profile={profile}
              currency={currency}
              onChanged={onProfilesChanged}
            />
          </>
        )}
      </div>
    </div>
  );
}
