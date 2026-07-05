import { useEffect, useRef, useState } from "react";
import type { Material } from "./api";

// Searchable material dropdown — the "Cut config" selector at the top of
// the Overview inspector. Filter input + list, closes on outside click
// or Escape, and reports the picked material name upward.
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
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const rootRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQuery("");
    inputRef.current?.focus();
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const selected = materials.find((m) => m.name === value) ?? null;
  const q = query.trim().toLowerCase();
  const filtered = q ? materials.filter((m) => m.name.toLowerCase().includes(q)) : materials;

  return (
    <div className="mat-select" ref={rootRef}>
      <div className="section-title" style={{ marginTop: 0 }}>Cut config</div>
      <button
        type="button"
        className="mat-trigger"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        title={value || "Select material"}
      >
        <span className="mat-name">{value || "Select material…"}</span>
        <span className="mat-caret">{open ? "▴" : "▾"}</span>
      </button>
      {selected && (
        <div className="mat-caption">
          machinability {selected.machinability_factor.toFixed(2)} · density {selected.density} g/cm³
        </div>
      )}
      {open && (
        <div className="mat-pop">
          <input
            ref={inputRef}
            className="mat-search"
            placeholder="Search materials…"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="mat-list">
            {filtered.map((m) => (
              <div
                key={m.name}
                className={`mat-item ${m.name === value ? "sel" : ""}`}
                onClick={() => {
                  setOpen(false);
                  if (m.name !== value) onChange(m.name);
                }}
              >
                <div className="mat-item-name">{m.name}</div>
                <div className="mat-item-sub">
                  mach {m.machinability_factor.toFixed(2)} · {m.density} g/cm³
                </div>
              </div>
            ))}
            {filtered.length === 0 && <div className="mat-empty">No matching material</div>}
          </div>
        </div>
      )}
    </div>
  );
}
