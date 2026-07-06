import { useState } from "react";
import { SearchSelect } from "./SearchSelect";
import type { Material } from "./api";

// Searchable material dropdown — the "Cut config" selector at the top of
// the Overview inspector. Library materials come from /api/materials;
// user-defined materials live in localStorage (cnc.customMaterials) and
// travel to the backend as the material_json form field.

function matCaption(m: Material): string {
  return `mach ${m.machinability_factor.toFixed(2)} · ${m.density} g/cm³`;
}

const numOr0 = (s: string) => {
  const v = parseFloat(s);
  return Number.isFinite(v) && v >= 0 ? v : 0;
};

function AddMaterialForm({
  onSave,
  onCancel,
}: {
  onSave: (m: Material) => void;
  onCancel: () => void;
}) {
  const [name, setName] = useState("");
  const [density, setDensity] = useState(2.7);
  const [mach, setMach] = useState(1.0);
  const [safety, setSafety] = useState(1.2);

  const fields: [string, number, (v: number) => void][] = [
    ["Density (g/cm³)", density, setDensity],
    ["Machinability factor", mach, setMach],
    ["Safety factor", safety, setSafety],
  ];

  return (
    <div className="mat-form">
      <div className="mat-form-row">
        <span>Name</span>
        <input
          className="num-input"
          style={{ width: 150, textAlign: "left" }}
          placeholder="EN24 Steel"
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
            step={0.01}
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
              density,
              machinability_factor: mach,
              safety_factor: safety,
            })
          }
        >
          Save material
        </button>
      </div>
    </div>
  );
}

// Footer of the dropdown: "+ Add material" row that flips into the inline
// form. Lives in its own component so the form state unmounts (resets)
// whenever the dropdown closes.
function AddMaterialFooter({
  close,
  onAddCustom,
}: {
  close: () => void;
  onAddCustom: (m: Material) => void;
}) {
  const [adding, setAdding] = useState(false);
  if (!adding) {
    return (
      <button type="button" className="mat-add" onClick={() => setAdding(true)}>
        + Add material
      </button>
    );
  }
  return (
    <AddMaterialForm
      onCancel={() => setAdding(false)}
      onSave={(m) => {
        onAddCustom(m);
        close();
      }}
    />
  );
}

export function MaterialSelect({
  materials,
  customMaterials,
  value,
  onChange,
  onAddCustom,
  disabled,
}: {
  materials: Material[];
  customMaterials: Material[];
  value: string;
  onChange: (name: string) => void;
  onAddCustom: (m: Material) => void;
  disabled?: boolean;
}) {
  const customNames = new Set(customMaterials.map((m) => m.name));
  const items = [
    ...customMaterials.map((m) => ({ id: m.name, title: m.name, caption: "Custom" })),
    ...materials
      .filter((m) => !customNames.has(m.name))
      .map((m) => ({ id: m.name, title: m.name, caption: matCaption(m) })),
  ];
  // Custom wins on a name collision (the user explicitly created it) —
  // same rule the request layer applies via material_json.
  const selected =
    customMaterials.find((m) => m.name === value) ??
    materials.find((m) => m.name === value) ??
    null;
  const triggerCaption = selected
    ? `${customNames.has(selected.name) ? "Custom · " : ""}machinability ${selected.machinability_factor.toFixed(2)} · density ${selected.density} g/cm³`
    : null;

  return (
    <SearchSelect
      label="Cut config"
      labelStyle={{ marginTop: 0 }}
      items={items}
      value={value}
      triggerCaption={triggerCaption}
      placeholder="Select material…"
      searchPlaceholder="Search materials…"
      emptyText="No matching material"
      onChange={onChange}
      disabled={disabled}
      footer={(close) => <AddMaterialFooter close={close} onAddCustom={onAddCustom} />}
    />
  );
}
