import { useEffect, useRef, useState } from "react";
import type { CSSProperties, ReactNode } from "react";

// Generic searchable dropdown behind the Cut config (material) and Machine
// selectors. Filter input + list, closes on outside click or Escape, and
// reports the picked item id upward. An optional footer (e.g. "+ Add
// machine") is pinned under the list and receives a close() callback.
export interface SearchItem {
  id: string;
  title: string;
  caption?: string;
  // Optional section label. When any item carries a group, the list renders
  // a header before each group (in first-seen order); otherwise it's flat.
  group?: string;
}

export function SearchSelect({
  label,
  labelStyle,
  items,
  value,
  triggerCaption,
  placeholder,
  searchPlaceholder,
  emptyText,
  onChange,
  disabled,
  footer,
}: {
  label: string;
  labelStyle?: CSSProperties;
  items: SearchItem[];
  value: string; // selected item id ("" = nothing selected yet)
  triggerCaption?: string | null;
  placeholder: string;
  searchPlaceholder: string;
  emptyText: string;
  onChange: (id: string) => void;
  disabled?: boolean;
  footer?: (close: () => void) => ReactNode;
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

  const selected = items.find((it) => it.id === value) ?? null;
  const shown = selected?.title ?? value;
  const q = query.trim().toLowerCase();
  const filtered = q
    ? items.filter(
        (it) => it.title.toLowerCase().includes(q) || (it.caption ?? "").toLowerCase().includes(q),
      )
    : items;

  return (
    <div className="mat-select" ref={rootRef}>
      <div className="section-title" style={labelStyle}>{label}</div>
      <button
        type="button"
        className="mat-trigger"
        disabled={disabled}
        onClick={() => setOpen((o) => !o)}
        title={shown || placeholder}
      >
        <span className="mat-name">{shown || placeholder}</span>
        <span className="mat-caret">{open ? "▴" : "▾"}</span>
      </button>
      {triggerCaption && <div className="mat-caption">{triggerCaption}</div>}
      {open && (
        <div className="mat-pop">
          <input
            ref={inputRef}
            className="mat-search"
            placeholder={searchPlaceholder}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <div className="mat-list">
            {(() => {
              // Bucket by group, preserving first-seen order. Headers show only
              // when at least one item is grouped (keeps ungrouped selects flat).
              const order: string[] = [];
              const byGroup = new Map<string, SearchItem[]>();
              for (const it of filtered) {
                const g = it.group ?? "";
                if (!byGroup.has(g)) {
                  byGroup.set(g, []);
                  order.push(g);
                }
                byGroup.get(g)!.push(it);
              }
              const showHeaders = order.some((g) => g !== "");
              return order.map((g) => (
                <div key={g || "_ungrouped"}>
                  {showHeaders && g && <div className="mat-group-header">{g}</div>}
                  {byGroup.get(g)!.map((it) => (
                    <div
                      key={it.id}
                      className={`mat-item ${it.id === value ? "sel" : ""}`}
                      onClick={() => {
                        setOpen(false);
                        if (it.id !== value) onChange(it.id);
                      }}
                    >
                      <div className="mat-item-name">{it.title}</div>
                      {it.caption && <div className="mat-item-sub">{it.caption}</div>}
                    </div>
                  ))}
                </div>
              ));
            })()}
            {filtered.length === 0 && <div className="mat-empty">{emptyText}</div>}
          </div>
          {footer?.(() => setOpen(false))}
        </div>
      )}
    </div>
  );
}
