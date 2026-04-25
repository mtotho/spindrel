/**
 * BotPicker — searchable bot selector with avatars and model badges.
 */
import { useMemo } from "react";
import { Bot } from "lucide-react";
import type { BotConfig } from "@/src/types/api";
import { SelectDropdown, type SelectDropdownOption } from "./SelectDropdown";

/** Shorten model IDs for badge display: "gemini/gemini-2.5-flash" -> "gemini-2.5-flash" */
function shortModel(model: string): string {
  const parts = model.split("/");
  return parts[parts.length - 1];
}

function BotAvatar({ bot, size }: { bot: BotConfig; size: number }) {
  return (
    <span
      className="flex shrink-0 items-center justify-center rounded-full bg-accent/[0.12] text-accent"
      style={{ width: size, height: size }}
      aria-hidden
    >
      <span style={{ fontSize: Math.max(10, Math.round(size * 0.55)) }}>
        {bot.avatar_emoji || "🤖"}
      </span>
    </span>
  );
}

interface BotOption extends SelectDropdownOption {
  bot?: BotConfig;
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
  const options = useMemo<BotOption[]>(() => {
    const mapped = bots.map((bot) => {
      const toolCount = (bot.local_tools?.length ?? 0) + (bot.mcp_servers?.length ?? 0);
      const skillCount = bot.skills?.length ?? 0;
      return {
        value: bot.id,
        label: bot.name,
        description: shortModel(bot.model),
        meta: toolCount > 0 || skillCount > 0
          ? `${toolCount > 0 ? `${toolCount} tools` : ""}${toolCount > 0 && skillCount > 0 ? " · " : ""}${skillCount > 0 ? `${skillCount} skills` : ""}`
          : undefined,
        searchText: `${bot.name} ${bot.display_name ?? ""} ${bot.id} ${bot.model}`,
        bot,
      };
    });
    if (!allowNone) return mapped;
    return [{ value: "", label: "None", searchText: "none no bot" }, ...mapped];
  }, [allowNone, bots]);

  return (
    <SelectDropdown
      value={value}
      onChange={(next) => onChange(next)}
      options={options}
      placeholder={placeholder ?? "Select bot..."}
      disabled={disabled}
      searchable
      searchPlaceholder="Search bots..."
      emptyLabel="No bots found"
      popoverWidth="content"
      size={compact ? "compact" : "md"}
      leadingIcon={<Bot size={compact ? 12 : 14} className="shrink-0 text-text-dim" />}
      triggerClassName={compact ? "border-transparent bg-transparent hover:bg-surface-overlay/45" : ""}
      renderValue={(option) => {
        const bot = (option as BotOption).bot;
        if (!bot) return <span className="italic text-text-dim">None</span>;
        return (
          <span className="flex min-w-0 items-center gap-2">
            <BotAvatar bot={bot} size={compact ? 14 : 20} />
            <span className={`min-w-0 flex-1 truncate text-text ${compact ? "font-medium" : ""}`}>{bot.name}</span>
            {!compact && (
              <span className="shrink-0 truncate rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-dim">
                {shortModel(bot.model)}
              </span>
            )}
          </span>
        );
      }}
      renderOption={(option, state) => {
        const bot = (option as BotOption).bot;
        if (!bot) return <span className="text-[12px] italic text-text-dim">None</span>;
        return (
          <>
            <BotAvatar bot={bot} size={24} />
            <span className="min-w-0 flex-1">
              <span className={`block truncate text-[12px] font-medium ${state.selected ? "text-accent" : "text-text"}`}>
                {bot.name}
              </span>
              <span className="mt-0.5 flex min-w-0 items-center gap-2 text-[10px] text-text-dim">
                <span className="truncate">{shortModel(bot.model)}</span>
                {option.meta && <span className="shrink-0">{option.meta}</span>}
              </span>
            </span>
          </>
        );
      }}
    />
  );
}
