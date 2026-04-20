/**
 * ToolSelector — searchable, source-grouped tool picker used by the task
 * step editor, the widget template editor, and any other surface that needs
 * to bind a string to a tool name.
 *
 * Matches selected tools via `resolveValue(tool)` so callers can opt into
 * either full (`tool_name` as-is, e.g. "github-list_prs") or
 * bare (integration prefix stripped, e.g. "list_prs") matching.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import ReactDOM from "react-dom";
import { ChevronDown as ChevronDownIcon, Wrench } from "lucide-react";

import type { ToolItem } from "@/src/api/hooks/useTools";

/** "google_workspace" → "Google Workspace", "homeassistant" → "Home Assistant" */
export function humanizeSource(s: string): string {
  const SPECIAL: Record<string, string> = {
    homeassistant: "Home Assistant",
    bluebubbles: "Blue Bubbles",
    claude_code: "Claude Code",
    web_search: "Web Search",
  };
  if (SPECIAL[s]) return SPECIAL[s];
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Split on -, _, and camelCase boundaries → lowercase tokens */
export function tokenize(s: string): string[] {
  return s
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/[-_]/g, " ")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
}

/** Compute the source key for grouping: integration name, "mcp:{server}", or "core" */
export function toolSourceKey(t: ToolItem): string {
  if (t.source_integration) return t.source_integration;
  if (t.server_name) return `mcp:${t.server_name}`;
  return "core";
}

/** Human-readable label for a source key */
export function sourceLabel(key: string): string {
  if (key === "core") return "Core";
  if (key.startsWith("mcp:")) return `MCP: ${key.slice(4)}`;
  return humanizeSource(key);
}

/** Strip redundant integration prefix from tool name for display / bare matching */
export function shortToolName(tool: ToolItem): string {
  if (!tool.source_integration) return tool.tool_name;
  const prefix = tool.source_integration + "-";
  if (tool.tool_name.startsWith(prefix)) return tool.tool_name.slice(prefix.length);
  const prefixUnderscore = tool.source_integration + "_";
  if (tool.tool_name.startsWith(prefixUnderscore)) return tool.tool_name.slice(prefixUnderscore.length);
  return tool.tool_name;
}

interface ToolSelectorProps {
  value: string | null;
  tools: ToolItem[];
  onChange: (value: string, tool: ToolItem) => void;
  /** Function that maps a tool → the value emitted / used for matching.
   *  Defaults to `tool.tool_name`. Pass `shortToolName` for bare-name mode. */
  resolveValue?: (tool: ToolItem) => string;
  placeholder?: string;
  /** Size preset — "sm" mirrors the step editor look; "md" works nicer in
   *  form rows with taller siblings. */
  size?: "sm" | "md";
  disabled?: boolean;
}

export function ToolSelector({
  value,
  tools,
  onChange,
  resolveValue = (t) => t.tool_name,
  placeholder = "Select tool…",
  size = "sm",
  disabled = false,
}: ToolSelectorProps) {
  const [search, setSearch] = useState("");
  const [sourceFilter, setSourceFilter] = useState<string | null>(null);
  const [sourceMenuOpen, setSourceMenuOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const sourceRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 });

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        triggerRef.current && !triggerRef.current.contains(e.target as Node) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setSearch("");
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
    if (disabled) return;
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left, width: Math.max(rect.width, 320) });
    }
    setOpen(!open);
  };

  const sourceGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of tools) {
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
  }, [tools]);

  const filtered = useMemo(() => {
    let pool = tools;

    if (sourceFilter) {
      pool = pool.filter((t) => toolSourceKey(t) === sourceFilter);
    }

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
  }, [tools, search, sourceFilter]);

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

  const selectedTool = tools.find((t) => resolveValue(t) === value);
  const isSearching = search.trim().length > 0;

  const triggerSizeCls = size === "md" ? "px-2.5 py-1.5 text-[13px]" : "px-2.5 py-1.5 text-xs";

  const renderToolButton = (tool: ToolItem, showSource: boolean, useShortName: boolean) => (
    <button
      key={tool.tool_key}
      onClick={() => {
        onChange(resolveValue(tool), tool);
        setOpen(false);
        setSearch("");
        setSourceFilter(null);
      }}
      className="flex flex-col gap-0.5 w-full px-3 py-2 bg-transparent border-none cursor-pointer text-left transition-colors hover:bg-surface-raised"
    >
      <div className="flex flex-row items-center gap-2">
        <span className="text-xs font-medium text-text truncate">
          {useShortName ? shortToolName(tool) : tool.tool_name}
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
    <div className="relative">
      <button
        ref={triggerRef}
        onClick={openDropdown}
        disabled={disabled}
        type="button"
        className={`flex flex-row items-center gap-2 w-full rounded-md border cursor-pointer text-left transition-colors ${triggerSizeCls} ${
          open
            ? "border-accent bg-surface"
            : "border-surface-border bg-input hover:border-accent/50 disabled:opacity-60 disabled:cursor-not-allowed"
        }`}
      >
        <Wrench size={size === "md" ? 13 : 12} className="text-blue-400 shrink-0" />
        <span className={`flex-1 truncate font-mono ${value ? "text-text" : "text-text-dim font-sans"}`}>
          {selectedTool ? (size === "md" ? resolveValue(selectedTool) : selectedTool.tool_name) : (value || placeholder)}
        </span>
        {selectedTool?.source_integration && (
          <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay shrink-0">
            {humanizeSource(selectedTool.source_integration)}
          </span>
        )}
        <ChevronDownIcon size={size === "md" ? 13 : 12} className="text-text-dim shrink-0" />
      </button>
      {open && ReactDOM.createPortal(
        <div
          ref={dropdownRef}
          className="fixed bg-surface border border-surface-border rounded-lg shadow-xl z-[10001] max-h-[360px] max-sm:max-h-[70vh] overflow-hidden flex flex-col"
          style={{ top: pos.top, left: pos.left, width: pos.width, maxWidth: "calc(100vw - 24px)" }}
        >
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
                type="button"
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
                  >×</span>
                ) : (
                  <ChevronDownIcon size={10} className="opacity-60" />
                )}
              </button>
              {sourceMenuOpen && (
                <div className="absolute top-full right-0 mt-1 bg-surface border border-surface-border rounded-lg shadow-xl z-[10002] min-w-[180px] max-h-[280px] overflow-y-auto py-1">
                  <button
                    onClick={() => { setSourceFilter(null); setSourceMenuOpen(false); }}
                    type="button"
                    className={`flex flex-row items-center justify-between w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                      !sourceFilter ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
                    }`}
                  >
                    <span>All sources</span>
                    <span className="text-[10px] text-text-dim">{tools.length}</span>
                  </button>
                  <div className="h-px bg-surface-border my-1" />
                  {sourceGroups.map((g) => (
                    <button
                      key={g.key}
                      onClick={() => { setSourceFilter(g.key); setSourceMenuOpen(false); }}
                      type="button"
                      className={`flex flex-row items-center justify-between w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                        sourceFilter === g.key ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
                      }`}
                    >
                      <span className="truncate">{g.label}</span>
                      <span className="text-[10px] text-text-dim ml-2 shrink-0">{g.count}</span>
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="px-3 py-1 text-[10px] text-text-dim border-b border-surface-border/50 shrink-0">
            {filtered.length} tool{filtered.length !== 1 ? "s" : ""}
            {sourceFilter && <span> in {sourceLabel(sourceFilter)}</span>}
            {isSearching && filtered.length === 50 && <span> (showing first 50)</span>}
          </div>

          <div className="overflow-y-auto">
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-[11px] text-text-dim text-center">
                No tools found
                {sourceFilter && (
                  <button
                    onClick={() => setSourceFilter(null)}
                    type="button"
                    className="block mx-auto mt-1 text-accent bg-transparent border-none cursor-pointer text-[11px] hover:underline"
                  >
                    Clear source filter
                  </button>
                )}
              </div>
            ) : grouped ? (
              grouped.map(([sourceKey, groupTools]) => (
                <div key={sourceKey}>
                  <div className="sticky top-0 px-3 py-1.5 text-[10px] font-semibold text-text-dim uppercase tracking-wider bg-surface-raised/80 backdrop-blur-sm border-b border-surface-border/30">
                    {sourceLabel(sourceKey)}
                    <span className="ml-1.5 font-normal opacity-60">{groupTools.length}</span>
                  </div>
                  {groupTools.map((tool) => renderToolButton(tool, false, true))}
                </div>
              ))
            ) : (
              filtered.map((tool) => renderToolButton(tool, isSearching, !!sourceFilter))
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
