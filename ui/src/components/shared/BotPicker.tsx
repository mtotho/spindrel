/**
 * BotPicker — searchable bot selector with avatars and model badges.
 *
 * Drop-in replacement for <SelectInput> in bot selection contexts.
 * Uses portal dropdown, same pattern as ToolSelector.
 */
import { useState, useMemo, useRef, useEffect } from "react";
import ReactDOM from "react-dom";
import { Bot, ChevronDown } from "lucide-react";
import type { BotConfig } from "@/src/types/api";

/** Shorten model IDs for badge display: "gemini/gemini-2.5-flash" → "gemini-2.5-flash" */
function shortModel(model: string): string {
  const parts = model.split("/");
  return parts[parts.length - 1];
}

export function BotPicker({ value, onChange, bots, allowNone, placeholder, disabled, compact }: {
  value: string;
  onChange: (botId: string) => void;
  bots: BotConfig[];
  allowNone?: boolean;
  placeholder?: string;
  disabled?: boolean;
  /** Smaller trigger for tight header contexts (ephemeral dock, etc.). */
  compact?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [open, setOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const dropdownRef = useRef<HTMLDivElement>(null);
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
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  const openDropdown = () => {
    if (disabled) return;
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      setPos({ top: rect.bottom + 4, left: rect.left, width: Math.max(rect.width, 280) });
    }
    setOpen(!open);
  };

  const filtered = useMemo(() => {
    if (!search.trim()) return bots;
    const term = search.toLowerCase();
    return bots.filter((b) =>
      b.name.toLowerCase().includes(term) ||
      (b.display_name ?? "").toLowerCase().includes(term) ||
      b.id.toLowerCase().includes(term)
    );
  }, [bots, search]);

  const selected = bots.find((b) => b.id === value);

  const selectBot = (botId: string) => {
    onChange(botId);
    setOpen(false);
    setSearch("");
  };

  const renderAvatar = (bot: BotConfig, size: number) => {
    if (bot.avatar_url) {
      return (
        <img
          src={bot.avatar_url}
          alt=""
          className="rounded-full object-cover shrink-0"
          style={{ width: size, height: size }}
        />
      );
    }
    return (
      <div
        className="rounded-full bg-accent/15 text-accent flex items-center justify-center shrink-0 text-[10px] font-bold uppercase"
        style={{ width: size, height: size }}
      >
        {bot.name.charAt(0)}
      </div>
    );
  };

  return (
    <div className="relative">
      <button
        ref={triggerRef}
        onClick={openDropdown}
        className={`flex flex-row items-center gap-2 w-full rounded-lg cursor-pointer text-left transition-colors ${
          compact
            ? "gap-1.5 px-2 py-1 text-[11px] border-0 hover:bg-white/5"
            : `gap-2 px-2.5 py-1.5 text-[13px] border ${
                open ? "border-accent bg-surface" : "border-surface-border bg-input hover:border-accent/50"
              }`
        } ${disabled ? "opacity-50 pointer-events-none" : ""}`}
      >
        {selected ? (
          <>
            {renderAvatar(selected, compact ? 14 : 20)}
            <span className={`flex-1 truncate text-text ${compact ? "font-medium" : ""}`}>
              {selected.name}
            </span>
            {!compact && (
              <span className="text-[10px] text-text-dim px-1.5 py-0.5 rounded bg-surface-overlay shrink-0 truncate max-w-[120px]">
                {shortModel(selected.model)}
              </span>
            )}
          </>
        ) : (
          <>
            <Bot size={compact ? 12 : 14} className="text-text-dim shrink-0" />
            <span className="flex-1 truncate text-text-dim">
              {placeholder ?? "Select bot..."}
            </span>
          </>
        )}
        <ChevronDown size={compact ? 10 : 12} className="text-text-dim shrink-0" />
      </button>

      {open && ReactDOM.createPortal(
        <div
          ref={dropdownRef}
          className="fixed bg-surface border border-surface-border rounded-lg shadow-xl z-[10050] max-h-[320px] overflow-hidden flex flex-col"
          style={{ top: pos.top, left: pos.left, width: pos.width, maxWidth: "calc(100vw - 24px)" }}
        >
          {/* Search */}
          <div className="p-2 border-b border-surface-border shrink-0">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search bots..."
              autoFocus
              className="w-full px-2.5 py-1.5 text-xs bg-input border border-surface-border rounded-md text-text outline-none focus:border-accent"
            />
          </div>

          {/* List */}
          <div className="overflow-y-auto">
            {allowNone && (
              <button
                onClick={() => selectBot("")}
                className={`flex flex-row items-center gap-2 w-full px-3 py-2 border-none cursor-pointer text-left transition-colors ${
                  !value ? "bg-accent/10 text-accent" : "bg-transparent text-text-dim hover:bg-surface-raised"
                }`}
              >
                <span className="text-xs italic">— None —</span>
              </button>
            )}
            {filtered.length === 0 ? (
              <div className="px-3 py-4 text-[11px] text-text-dim text-center">No bots found</div>
            ) : (
              filtered.map((bot) => {
                const isSelected = bot.id === value;
                const toolCount = (bot.local_tools?.length ?? 0) + (bot.mcp_servers?.length ?? 0);
                const skillCount = bot.skills?.length ?? 0;
                return (
                  <button
                    key={bot.id}
                    onClick={() => selectBot(bot.id)}
                    className={`flex flex-row items-center gap-2.5 w-full px-3 py-2 border-none cursor-pointer text-left transition-colors ${
                      isSelected ? "bg-accent/10" : "bg-transparent hover:bg-surface-raised"
                    }`}
                  >
                    {renderAvatar(bot, 24)}
                    <div className="flex flex-col flex-1 min-w-0">
                      <span className={`text-xs font-medium truncate ${isSelected ? "text-accent" : "text-text"}`}>
                        {bot.name}
                      </span>
                      <div className="flex flex-row items-center gap-2 text-[10px] text-text-dim">
                        <span className="truncate max-w-[100px]">{shortModel(bot.model)}</span>
                        {(toolCount > 0 || skillCount > 0) && (
                          <span className="shrink-0">
                            {toolCount > 0 && `${toolCount} tools`}
                            {toolCount > 0 && skillCount > 0 && " · "}
                            {skillCount > 0 && `${skillCount} skills`}
                          </span>
                        )}
                      </div>
                    </div>
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
