import { SearchSelect } from "./SearchSelect";
import type { Material } from "./api";

// Searchable material dropdown — the "Cut config" selector at the top of
// the Overview inspector. Thin adapter over the generic SearchSelect.
export function MaterialSelect({
  materials,
  value,
  onChange,
  disabled,
}: {
  materials: Material[];
  value: string;
  onChange: (name: string) => void;
  disabled?: boolean;
}) {
  const selected = materials.find((m) => m.name === value) ?? null;
  return (
    <SearchSelect
      label="Cut config"
      labelStyle={{ marginTop: 0 }}
      items={materials.map((m) => ({
        id: m.name,
        title: m.name,
        caption: `mach ${m.machinability_factor.toFixed(2)} · ${m.density} g/cm³`,
      }))}
      value={value}
      triggerCaption={
        selected
          ? `machinability ${selected.machinability_factor.toFixed(2)} · density ${selected.density} g/cm³`
          : null
      }
      placeholder="Select material…"
      searchPlaceholder="Search materials…"
      emptyText="No matching material"
      onChange={onChange}
      disabled={disabled}
    />
  );
}
