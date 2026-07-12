import { useState } from "react";
import { SearchSelect, type SearchItem } from "./SearchSelect";
import type { MachineInfo } from "./api";

// Machine selector next to Cut config. Library machines come from
// /api/machines; user-defined machines live in localStorage
// (cnc.customMachines) and travel to the backend as machine_json.

export interface CustomMachine {
  name: string;
  max_spindle_rpm: number;
  axes: number;
  rapid_feed_rate: number;
  tool_change_time_s: number;
  setup_time_min: number;
  // Optional display field (Shop Library add form) — the backend's
  // machine_json normalizer tolerates and ignores unknown keys.
  controller?: string;
}

// Library machines use name/axes; engine defaults use machine_name/axis_count.
export function machineName(m: MachineInfo): string {
  return m.name ?? m.machine_name ?? "";
}

function machineCaption(m: MachineInfo): string {
  const axes = m.axes ?? m.axis_count;
  return [
    m.maker,
    axes != null ? `${axes}-axis` : null,
    m.max_spindle_rpm != null ? `${m.max_spindle_rpm} rpm` : null,
    m.controller,
  ]
    .filter(Boolean)
    .join(" · ");
}

// Coarse machine class for grouping the picker: milling (VMC), lathe/turning,
// or turn-mill. The library's `type` field is authoritative; fall back to the
// machine name for entries that don't carry a type (e.g. user-added).
type MachineKind = "mill" | "lathe" | "turnmill";
export function machineKind(m: MachineInfo): MachineKind {
  const t = `${m.type ?? ""} ${m.machine_type ?? ""}`.toLowerCase();
  if (t.includes("turn-mill") || t.includes("mill-turn") || t.includes("turnmill")) return "turnmill";
  if (t.includes("lathe") || t.includes("turning")) return "lathe";
  const n = machineName(m).toLowerCase();
  if (/integrex|\bntx\b|multi.?task/.test(n)) return "turnmill";
  if (/lathe|\bturn\b|quick turn|\blynx\b|\bst-\d|\bclx\b|\bnlx\b/.test(n)) return "lathe";
  return "mill";
}
const MACHINE_GROUP_LABEL: Record<MachineKind, string> = {
  mill: "Milling (VMC)",
  lathe: "Lathe / Turning",
  turnmill: "Turn-Mill",
};
const MACHINE_GROUP_ORDER: Record<MachineKind, number> = { mill: 1, lathe: 2, turnmill: 3 };

const numOr0 = (s: string) => {
  const v = parseFloat(s);
  return Number.isFinite(v) && v >= 0 ? v : 0;
};

function AddMachineForm({
  onSave,
  onCancel,
}: {
  onSave: (m: CustomMachine) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [rpm, setRpm] = useState(8000);
  const [axes, setAxes] = useState(3);
  const [rapid, setRapid] = useState(24000);
  const [toolChange, setToolChange] = useState(5);
  const [setupMin, setSetupMin] = useState(20);

  const fields: [string, number, (v: number) => void][] = [
    ["Max spindle rpm", rpm, setRpm],
    ["Axes", axes, setAxes],
    ["Rapid feed (mm/min)", rapid, setRapid],
    ["Tool change (s)", toolChange, setToolChange],
    ["Setup time (min)", setupMin, setSetupMin],
  ];

  return (
    <div className="mat-form">
      <div className="mat-form-row">
        <span>Name</span>
        <input
          className="num-input"
          style={{ width: 150, textAlign: "left" }}
          placeholder="My VMC"
          value={name}
          onChange={(e) => setName(e.target.value)}
        />
      </div>
      {fields.map(([label, val, set]) => (
        <div className="mat-form-row" key={label}>
          <span>{label}</span>
          <input
            className="num-input"
            type="number"
            min={0}
            value={val}
            onChange={(e) => set(numOr0(e.target.value))}
          />
        </div>
      ))}
      <div className="mat-form-actions">
        <button
          type="button"
          className="btn"
          style={{ padding: "3px 10px", fontSize: 11 }}
          onClick={onCancel}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn primary"
          style={{ padding: "3px 10px", fontSize: 11 }}
          disabled={!name.trim()}
          onClick={() =>
            onSave({
              name: name.trim(),
              max_spindle_rpm: rpm,
              axes,
              rapid_feed_rate: rapid,
              tool_change_time_s: toolChange,
              setup_time_min: setupMin,
            })
          }
        >
          Save machine
        </button>
      </div>
    </div>
  );
}

// Footer of the dropdown: "+ Add machine" row that flips into the inline
// form. Lives in its own component so the form state unmounts (resets)
// whenever the dropdown closes.
function AddMachineFooter({
  close,
  onAddCustom,
}: {
  close: () => void;
  onAddCustom: (m: CustomMachine) => void;
}) {
  const [adding, setAdding] = useState(false);
  if (!adding) {
    return (
      <button type="button" className="mat-add" onClick={() => setAdding(true)}>
        + Add machine
      </button>
    );
  }
  return (
    <AddMachineForm
      onCancel={() => setAdding(false)}
      onSave={(m) => {
        onAddCustom(m);
        close();
      }}
    />
  );
}

export function MachineSelect({
  machines,
  customMachines,
  value,
  onChange,
  onAddCustom,
  disabled,
}: {
  machines: MachineInfo[];
  customMachines: CustomMachine[];
  value: string;
  onChange: (name: string) => void;
  onAddCustom: (m: CustomMachine) => void;
  disabled?: boolean;
}) {
  const customNames = new Set(customMachines.map((m) => m.name));
  // Library machines sorted into Milling → Lathe → Turn-Mill, alphabetical
  // within each class, so the picker shows clear sections.
  const libSorted = machines
    .filter((m) => machineName(m) && !customNames.has(machineName(m)))
    .map((m) => ({ m, kind: machineKind(m) }))
    .sort(
      (a, b) =>
        MACHINE_GROUP_ORDER[a.kind] - MACHINE_GROUP_ORDER[b.kind] ||
        machineName(a.m).localeCompare(machineName(b.m)),
    );
  const items: SearchItem[] = [
    // The user's own machines first, then the library grouped by class.
    ...customMachines.map((m) => ({ id: m.name, title: m.name, caption: "Custom", group: "My Shop" })),
    ...libSorted.map(({ m, kind }) => ({
      id: machineName(m),
      title: machineName(m),
      caption: machineCaption(m),
      group: MACHINE_GROUP_LABEL[kind],
    })),
  ];
  const selectedLib = machines.find((m) => machineName(m) === value);
  const triggerCaption = !value
    ? null
    : customNames.has(value)
      ? "Custom"
      : selectedLib
        ? machineCaption(selectedLib)
        : null;

  return (
    <SearchSelect
      label="Machine"
      labelStyle={{ marginTop: 0 }}
      items={items}
      value={value}
      triggerCaption={triggerCaption}
      placeholder="Select machine…"
      searchPlaceholder="Search machines…"
      emptyText="No matching machine"
      onChange={onChange}
      disabled={disabled}
      footer={(close) => <AddMachineFooter close={close} onAddCustom={onAddCustom} />}
    />
  );
}
