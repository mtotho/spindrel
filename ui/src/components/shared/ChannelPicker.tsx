/**
 * ChannelPicker — searchable channel selector with integration badges and type filter.
 *
 * Drop-in replacement for <SelectInput> in channel selection contexts.
 * Uses portal dropdown, same pattern as ToolSelector / BotPicker.
 */
import { useState, useMemo, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import { Hash, ChevronDown, Users } from "lucide-react";
import type { Channel, BotConfig } from "@/src/types/api";

function humanizeIntegration(s: string): string {
  const SPECIAL: Record<string, string> = {
    bluebubbles: "Blue Bubbles",
    homeassistant: "Home Assistant",
    web_search: "Web Search",
  };
  if (SPECIAL[s]) return SPECIAL[s];
  return s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

function channelTypeKey(ch: Channel): string {
  return ch.integration || "direct";
}

function channelTypeLabel(key: string): string {
  if (key === "direct") return "Direct";
  return humanizeIntegration(key);
}

export function ChannelPicker({ value, onChange, channels, bots, allowNone, placeholder, disabled }: {
  value: string;
  onChange: (channelId: string) => void;
  channels: Channel[];
  bots?: BotConfig[];
  allowNone?: boolean;
  placeholder?: string;
  disabled?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [typeMenuOpen, setTypeMenuOpen] = useState(false);
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
  const typeRef = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ top: 0, left: 0, width: 0 });

  const botMap = useMemo(() => {
    const m = new Map<string, BotConfig>();
    for (const b of bots ?? []) m.set(b.id, b);
    return m;
  }, [bots]);

  // Close main dropdown
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (
        triggerRef.current && !triggerRef.current.contains(e.target as Node) &&
        dropdownRef.current && !dropdownRef.current.contains(e.target as Node)
      ) {
        setOpen(false);
        setSearch("");
        setTypeMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Close type submenu
  useEffect(() => {
    if (!typeMenuOpen) return;
    const handler = (e: MouseEvent) => {
      if (typeRef.current && !typeRef.current.contains(e.target as Node)) {
        setTypeMenuOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [typeMenuOpen]);

  const openDropdown = () => {
    if (disabled) return;
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left, width: Math.max(rect.width, 300) });
    }
    setOpen(!open);
  };

  // Type groups with counts
  const typeGroups = useMemo(() => {
    const counts = new Map<string, number>();
    for (const ch of channels) {
      const key = channelTypeKey(ch);
      counts.set(key, (counts.get(key) ?? 0) + 1);
    }
    return [...counts.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([key, count]) => ({ key, label: channelTypeLabel(key), count }));
  }, [channels]);

  // Filter + search
  const filtered = useMemo(() => {
    let pool = channels;
    if (typeFilter) {
      pool = pool.filter((ch) => channelTypeKey(ch) === typeFilter);
    }
    if (search.trim()) {
      const term = search.toLowerCase();
      pool = pool.filter((ch) =>
        (ch.display_name ?? "").toLowerCase().includes(term) ||
        ch.name.toLowerCase().includes(term)
      );
    }
    return pool;
  }, [channels, search, typeFilter]);

  const selected = channels.find((ch) => String(ch.id) === value);

  const selectChannel = (chId: string) => {
    onChange(chId);
    setOpen(false);
    setSearch("");
    setTypeFilter(null);
  };

  const channelDisplayName = (ch: Channel) => ch.display_name || ch.name;

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        onClick={openDropdown}
        className={`flex flex-row items-center gap-2 w-full px-2.5 py-1.5 text-[13px] rounded-lg border cursor-pointer text-left transition-colors ${
          disabled ? "opacity-50 pointer-events-none" : ""
        } ${
          open ? "border-accent bg-surface" : "border-surface-border bg-input hover:border-accent/50"
        }`}
      >
        {selected ? (
          <>
            <Hash size={14} className="text-text-dim shrink-0" />
            <span className="flex-1 truncate text-text">{channelDisplayName(selected)}</span>
            {selected.integration && (
              <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay shrink-0">
                {humanizeIntegration(selected.integration)}
              </span>
            )}
          </>
        ) : (
          <>
            <Hash size={14} className="text-text-dim shrink-0" />
            <span className="flex-1 truncate text-text-dim">
              {value === "" && allowNone ? "— None —" : (placeholder ?? "Select channel...")}
            </span>
          </>
        )}
        <ChevronDown size={12} className="text-text-dim shrink-0" />
      </button>

      {open && ReactDOM.createPortal(
        <div
          ref={dropdownRef}
          className="fixed bg-surface border border-surface-border rounded-lg shadow-xl z-[10001] max-h-[360px] sm:max-h-[360px] max-sm:max-h-[70vh] overflow-hidden flex flex-col"
          style={{ top: pos.top, left: pos.left, width: pos.width, maxWidth: "calc(100vw - 24px)" }}
        >
          {/* Search + type filter */}
          <div className="flex flex-row items-center gap-1.5 p-2 border-b border-surface-border shrink-0">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search channels..."
              autoFocus
              className="flex-1 min-w-0 px-2.5 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent/40"
            />
            {typeGroups.length > 1 && (
              <div ref={typeRef} className="relative shrink-0">
                <button
                  onClick={() => setTypeMenuOpen(!typeMenuOpen)}
                  className={`flex flex-row items-center gap-1 px-2 py-1.5 text-[11px] rounded-md border cursor-pointer transition-colors whitespace-nowrap ${
                    typeFilter
                      ? "border-accent/40 bg-accent/10 text-accent"
                      : "border-surface-border bg-input text-text-dim hover:border-accent/30"
                  }`}
                >
                  <span className="truncate max-w-[100px]">
                    {typeFilter ? channelTypeLabel(typeFilter) : "All types"}
                  </span>
                  {typeFilter ? (
                    <span
                      onClick={(e) => { e.stopPropagation(); setTypeFilter(null); setTypeMenuOpen(false); }}
                      className="ml-0.5 hover:text-text cursor-pointer"
                    >×</span>
                  ) : (
                    <ChevronDown size={10} className="opacity-60" />
                  )}
                </button>
                {typeMenuOpen && (
                  <div className="absolute top-full right-0 mt-1 bg-surface border border-surface-border rounded-lg shadow-xl z-[10002] min-w-[160px] max-h-[240px] overflow-y-auto py-1">
                    <button
                      onClick={() => { setTypeFilter(null); setTypeMenuOpen(false); }}
                      className={`flex flex-row items-center justify-between w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                        !typeFilter ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
                      }`}
                    >
                      <span>All types</span>
                      <span className="text-[10px] text-text-dim">{channels.length}</span>
                    </button>
                    <div className="h-px bg-surface-border my-1" />
                    {typeGroups.map((g) => (
                      <button
                        key={g.key}
                        onClick={() => { setTypeFilter(g.key); setTypeMenuOpen(false); }}
                        className={`flex flex-row items-center justify-between w-full px-3 py-1.5 text-xs border-none cursor-pointer text-left transition-colors ${
                          typeFilter === g.key ? "bg-accent/10 text-accent font-medium" : "bg-transparent text-text hover:bg-surface-raised"
                        }`}
                      >
                        <span>{g.label}</span>
                        <span className="text-[10px] text-text-dim ml-2 shrink-0">{g.count}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Count */}
          <div className="px-3 py-1 text-[10px] text-text-dim border-b border-surface-border/50 shrink-0">
            {filtered.length} channel{filtered.length !== 1 ? "s" : ""}
            {typeFilter && <span> · {channelTypeLabel(typeFilter)}</span>}
          </div>

          {/* List */}
          <div className="overflow-y-auto">
            {allowNone && (
              <button
                onClick={() => selectChannel("")}
                className={`flex flex-row items-center gap-2 w-full px-3 py-2 border-none cursor-pointer text-left transition-colors ${
                  !value ? "bg-accent/10 text-accent" : "bg-transparent text-text-dim hover:bg-surface-raised"
                }`}
              >
                <span className="text-xs italic">— None —</span>
              </button>
            )}
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-[11px] text-text-dim text-center">
                No channels found
                {typeFilter && (
                  <button
                    onClick={() => setTypeFilter(null)}
                    className="block mx-auto mt-1 text-accent bg-transparent border-none cursor-pointer text-[11px] hover:underline"
                  >
                    Clear filter
                  </button>
                )}
              </div>
            ) : (
              filtered.map((ch) => {
                const isSelected = String(ch.id) === value;
                const primaryBot = botMap.get(ch.bot_id);
                const memberCount = ch.member_bots?.length ?? 0;
                return (
                  <button
                    key={ch.id}
                    onClick={() => selectChannel(String(ch.id))}
                    className={`flex flex-row items-center gap-2.5 w-full px-3 py-2 border-none cursor-pointer text-left transition-colors ${
                      isSelected ? "bg-accent/10" : "bg-transparent hover:bg-surface-raised"
                    }`}
                  >
                    <Hash size={14} className={`shrink-0 ${isSelected ? "text-accent" : "text-text-dim"}`} />
                    <div className="flex flex-col flex-1 min-w-0">
                      <span className={`text-xs font-medium truncate ${isSelected ? "text-accent" : "text-text"}`}>
                        {channelDisplayName(ch)}
                      </span>
                      <div className="flex flex-row items-center gap-2 text-[10px] text-text-dim">
                        {primaryBot && <span className="truncate max-w-[100px]">{primaryBot.name}</span>}
                        {memberCount > 1 && (
                          <span className="flex flex-row items-center gap-0.5 shrink-0">
                            <Users size={9} />
                            {memberCount}
                          </span>
                        )}
                        {ch.integration && (
                          <span className="shrink-0">{humanizeIntegration(ch.integration)}</span>
                        )}
                      </div>
                    </div>
                    {ch.category && (
                      <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay shrink-0">
                        {ch.category}
                      </span>
                    )}
                  </button>
                );
              })
            )}
          </div>
        </div>,
        document.body,
      )}
    </div>
  );
}
