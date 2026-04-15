/**
 * ChipPicker — searchable chip list for multi-select (skills, tools, etc.)
 */
import { useState, useMemo, useRef, useEffect } from "react";

export function ChipPicker({ label, items, selected, onAdd, onRemove }: {
  label: string;
  items: { key: string; label: string; tag?: string }[];
  selected: string[];
  onAdd: (key: string) => void;
  onRemove: (key: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setOpen(false);
        setSearch("");
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const filtered = useMemo(() => {
    const term = search.toLowerCase();
    return items
      .filter((i) => !selected.includes(i.key))
      .filter((i) => !term || i.label.toLowerCase().includes(term) || (i.tag ?? "").toLowerCase().includes(term))
      .slice(0, 20);
  }, [items, selected, search]);

  const selectedItems = items.filter((i) => selected.includes(i.key));

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11px] text-text-dim font-semibold uppercase tracking-wider">
        {label}
        {selectedItems.length > 0 && (
          <span className="ml-1.5 text-accent font-bold">{selectedItems.length}</span>
        )}
      </div>
      <div className="flex flex-row gap-1.5 flex-wrap items-center min-h-[32px]">
        {selectedItems.map((item) => (
          <span
            key={item.key}
            className="inline-flex flex-row items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-accent/[0.08] text-accent border border-accent/20"
          >
            {item.label}
            <button
              onClick={() => onRemove(item.key)}
              className="bg-transparent border-none cursor-pointer text-sm text-accent p-0 leading-none opacity-60 hover:opacity-100"
            >
              &times;
            </button>
          </span>
        ))}
        <div ref={dropdownRef} className="relative">
          <button
            onClick={() => setOpen(!open)}
            className={`px-3 py-1 text-[11px] font-semibold rounded-full bg-transparent cursor-pointer transition-colors duration-150 ${
              open
                ? "border border-dashed border-accent text-accent"
                : "border border-dashed border-surface-border text-text-muted hover:border-accent/50 hover:text-text-muted"
            }`}
          >
            + Add
          </button>
          {open && (
            <div className="absolute top-full left-0 mt-1.5 w-[260px] max-h-[220px] overflow-y-auto bg-surface border border-surface-border rounded-[10px] shadow-xl z-10">
              <div className="p-2 border-b border-surface-border">
                <input
                  type="text"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={`Search ${label.toLowerCase()}...`}
                  autoFocus
                  className="w-full px-2.5 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
                />
              </div>
              {filtered.length === 0 ? (
                <div className="px-3.5 py-3 text-[11px] text-text-dim">
                  {items.length === 0 ? `No ${label.toLowerCase()} available` : "No matches"}
                </div>
              ) : (
                filtered.map((item) => (
                  <button
                    key={item.key}
                    onClick={() => { onAdd(item.key); setOpen(false); setSearch(""); }}
                    className="flex flex-row items-center gap-2 w-full px-3.5 py-2 text-xs bg-transparent border-none cursor-pointer text-text text-left transition-colors duration-100 hover:bg-surface-raised"
                  >
                    <span className="flex-1">{item.label}</span>
                    {item.tag && (
                      <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-raised">
                        {item.tag}
                      </span>
                    )}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
