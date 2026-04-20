/**
 * ChipPicker — searchable chip list for multi-select (skills, tools, etc.)
 * ToolMultiPicker — richer variant with source grouping + descriptions for tools.
 */
import { useState, useMemo, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import type { ToolItem } from "@/src/api/hooks/useTools";

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
                  className="w-full px-2.5 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent/40"
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

// ---------------------------------------------------------------------------
// ToolMultiPicker — source-grouped tool picker with descriptions
// ---------------------------------------------------------------------------

function tokenize(s: string): string[] {
  return s
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[-_]/g, " ")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
}

function toolSourceKey(t: ToolItem): string {
  if (t.source_integration) return t.source_integration;
  if (t.server_name) return `mcp:${t.server_name}`;
  return "core";
}

function sourceLabel(key: string): string {
  if (key === "core") return "Core";
  if (key.startsWith("mcp:")) return `MCP: ${key.slice(4)}`;
  const SPECIAL: Record<string, string> = {
    google_workspace: "Google Workspace",
    google_calendar: "Google Calendar",
    web_search: "Web Search",
  };
  return SPECIAL[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function shortToolName(tool: ToolItem): string {
  if (!tool.source_integration) return tool.tool_name;
  const prefix = tool.source_integration + "-";
  if (tool.tool_name.startsWith(prefix)) return tool.tool_name.slice(prefix.length);
  const prefixUnderscore = tool.source_integration + "_";
  if (tool.tool_name.startsWith(prefixUnderscore)) return tool.tool_name.slice(prefixUnderscore.length);
  return tool.tool_name;
}

export function ToolMultiPicker({ tools, selected, onAdd, onRemove }: {
  tools: ToolItem[];
  selected: string[];
  onAdd: (key: string) => void;
  onRemove: (key: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0 });

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        triggerRef.current && !triggerRef.current.contains(e.target as Node) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setSearch("");
        setSourceFilter(null);
        setSourceMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  useEffect(() => {
    if (!sourceMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (sourceRef.current && !sourceRef.current.contains(e.target as Node)) {
        setSourceMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [sourceMenuOpen]);

  const openDropdown = () => {
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left });
    }
    setOpen(!open);
  };

  const available = useMemo(() => tools.filter((t) => !selected.includes(t.tool_key)), [tools, selected]);

  const sourceGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of available) {
      const key = toolSourceKey(t);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => {
        if (a[0] === "core") return -1;
        if (b[0] === "core") return 1;
        return b[1] - a[1];
      })
      .map(([key, count]) => ({ key, label: sourceLabel(key), count }));
  }, [available]);

  const filtered = useMemo(() => {
    let pool = available;
    if (sourceFilter) pool = pool.filter((t) => toolSourceKey(t) === sourceFilter);
    if (search.trim()) {
      const queryTokens = tokenize(search);
      pool = pool.filter((t) => {
        const haystack = [
          ...tokenize(t.tool_name),
          ...tokenize(t.description ?? ""),
          ...tokenize(t.source_integration ?? ""),
          ...tokenize(t.server_name ?? ""),
        ].join(" ");
        return queryTokens.every((qt) => haystack.includes(qt));
      });
    }
    return pool.slice(0, 50);
  }, [available, search, sourceFilter]);

  const grouped = useMemo(() => {
    if (search.trim() || sourceFilter) return null;
    const groups = new Map<string, ToolItem[]>();
    for (const t of filtered) {
      const key = toolSourceKey(t);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key)!.push(t);
    }
    const order = sourceGroups.map((g) => g.key);
    return [...groups.entries()].sort((a, b) => order.indexOf(a[0]) - order.indexOf(b[0]));
  }, [filtered, search, sourceFilter, sourceGroups]);

  const selectedTools = tools.filter((t) => selected.includes(t.tool_key));

  const renderToolButton = (tool: ToolItem, showSource: boolean, useShort: boolean) => (
    <button
      key={tool.tool_key}
      onClick={() => { onAdd(tool.tool_key); }}
      className="flex flex-col gap-0.5 w-full px-3 py-2 bg-transparent border-none cursor-pointer text-left transition-colors hover:bg-surface-raised"
    >
      <div className="flex flex-row items-center gap-2">
        <span className="text-xs font-medium text-text truncate">
          {useShort ? shortToolName(tool) : tool.tool_name}
        </span>
        {showSource && (tool.source_integration || tool.server_name) && (
          <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay shrink-0">
            {sourceLabel(toolSourceKey(tool))}
          </span>
        )}
      </div>
      {tool.description && (
        <span className="text-[10px] text-text-dim line-clamp-1">{tool.description}</span>
      )}
    </button>
  );

  return (
    <div className="flex flex-col gap-2">
      <div className="text-[11px] text-text-dim font-semibold uppercase tracking-wider">
        Tools
        {selectedTools.length > 0 && (
          <span className="ml-1.5 text-accent font-bold">{selectedTools.length}</span>
        )}
      </div>
      <div className="flex flex-row gap-1.5 flex-wrap items-center min-h-[32px]">
        {selectedTools.map((tool) => (
          <span
            key={tool.tool_key}
            className="inline-flex flex-row items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-accent/[0.08] text-accent border border-accent/20"
            title={tool.description ?? undefined}
          >
            {tool.tool_name}
            {tool.source_integration && (
              <span className="text-[9px] text-accent/60">{sourceLabel(toolSourceKey(tool))}</span>
            )}
            <button
              onClick={() => onRemove(tool.tool_key)}
              className="bg-transparent border-none cursor-pointer text-sm text-accent p-0 leading-none opacity-60 hover:opacity-100"
            >
              &times;
            </button>
          </span>
        ))}
        <button
          ref={triggerRef}
          onClick={openDropdown}
          className={`px-3 py-1 text-[11px] font-semibold rounded-full bg-transparent cursor-pointer transition-colors duration-150 ${
            open
              ? "border border-dashed border-accent text-accent"
              : "border border-dashed border-surface-border text-text-muted hover:border-accent/50 hover:text-text-muted"
          }`}
        >
          + Add
        </button>
        {open && ReactDOM.createPortal(
          <div
            ref={dropdownRef}
            className="fixed bg-surface border border-surface-border rounded-lg shadow-xl z-[10001] max-h-[360px] overflow-hidden flex flex-col"
            style={{ top: pos.top, left: pos.left, width: 340, maxWidth: "calc(100vw - 24px)" }}
          >
            {/* Search + source filter */}
            <div className="flex flex-row items-center gap-1.5 p-2 border-b border-surface-border shrink-0">
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search tools..."
                autoFocus
                className="flex-1 min-w-0 px-2.5 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent/40"
              />
              <div ref={sourceRef} className="relative shrink-0">
                <button
                  onClick={() => setSourceMenuOpen(!sourceMenuOpen)}
                  className={`flex flex-row items-center gap-1 px-2 py-1.5 text-[11px] rounded-md border cursor-pointer transition-colors whitespace-nowrap ${
                    sourceFilter
                      ? "border-accent/40 bg-accent/10 text-accent"
                      : "border-surface-border bg-input text-text-dim hover:border-accent/30"
                  }`}
                >
                  <span className="truncate max-w-[100px]">
                    {sourceFilter ? sourceLabel(sourceFilter) : "All sources"}
                  </span>
                  {sourceFilter ? (
                    <span
                      onClick={(e) => { e.stopPropagation(); setSourceFilter(null); setSourceMenuOpen(false); }}
                      className="ml-0.5 hover:text-text cursor-pointer"
                    >&times;</span>
                  ) : (
                    <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" className="opacity-60">
                      <polyline points="6 9 12 15 18 9" />
                    </svg>
                  )}
                </button>
                {sourceMenuOpen && (
                  <div className="absolute top-full right-0 mt-1 bg-surface border border-surface-border rounded-lg shadow-xl z-[10002] min-w-[180px] max-h-[280px] overflow-y-auto py-1">
                    <button
                      onClick={() => { setSourceFilter(null); setSourceMenuOpen(false); }}
                      className={`flex flex-row items-center justify-between w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                        !sourceFilter ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
                      }`}
                    >
                      All sources
                      <span className="text-[10px] text-text-dim">{available.length}</span>
                    </button>
                    {sourceGroups.map((sg) => (
                      <button
                        key={sg.key}
                        onClick={() => { setSourceFilter(sg.key); setSourceMenuOpen(false); }}
                        className={`flex flex-row items-center justify-between w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                          sourceFilter === sg.key ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
                        }`}
                      >
                        {sg.label}
                        <span className="text-[10px] text-text-dim">{sg.count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            </div>

            {/* Tool list */}
            <div className="overflow-y-auto flex-1">
              {filtered.length === 0 ? (
                <div className="px-3.5 py-3 text-[11px] text-text-dim">
                  {available.length === 0 ? "All tools selected" : "No matches"}
                </div>
              ) : grouped ? (
                grouped.map(([sourceKey, groupTools]) => (
                  <div key={sourceKey}>
                    <div className="px-3 pt-2.5 pb-1 text-[10px] font-semibold text-text-dim uppercase tracking-wider sticky top-0 bg-surface">
                      {sourceLabel(sourceKey)}
                    </div>
                    {groupTools.map((tool) => renderToolButton(tool, false, true))}
                  </div>
                ))
              ) : (
                filtered.map((tool) => renderToolButton(tool, true, false))
              )}
            </div>
          </div>,
          document.body,
        )}
      </div>
    </div>
  );
}
