import { useBots } from "@/src/api/hooks/useBots";
import { useThemeTokens } from "@/src/theme/tokens";
import { Bot, ChevronDown } from "lucide-react";
import { useRef, useState, useEffect } from "react";

interface EphemeralBotPickerProps {
  value: string;
  onChange: (botId: string) => void;
  disabled?: boolean;
}

/** Compact bot selector for the ephemeral session header.
    Disabled once the session has messages to prevent mid-session switching. */
export function EphemeralBotPicker({ value, onChange, disabled = false }: EphemeralBotPickerProps) {
  const t = useThemeTokens();
  const { data: bots } = useBots();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  const selectedBot = bots?.find((b) => b.id === value);
  const label = selectedBot?.name ?? value ?? "Pick a bot";

  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => !disabled && setOpen((v) => !v)}
        disabled={disabled}
        className="flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium transition-colors"
        style={{
          color: t.textMuted,
          background: "transparent",
          border: "none",
          cursor: disabled ? "default" : "pointer",
          opacity: disabled ? 0.6 : 1,
        }}
        title={disabled ? "Bot locked once session starts" : "Switch bot"}
      >
        <Bot size={12} />
        <span>{label}</span>
        {!disabled && <ChevronDown size={10} />}
      </button>

      {open && !disabled && (
        <div
          className="absolute left-0 top-full mt-1 z-50 rounded-lg shadow-lg overflow-hidden"
          style={{
            minWidth: 160,
            backgroundColor: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          {bots?.map((bot) => (
            <button
              key={bot.id}
              onClick={() => {
                onChange(bot.id);
                setOpen(false);
              }}
              className="w-full text-left px-3 py-2 text-xs transition-colors hover:bg-white/5"
              style={{
                color: bot.id === value ? t.accent : t.textMuted,
                background: "transparent",
                border: "none",
                cursor: "pointer",
                fontWeight: bot.id === value ? 600 : 400,
              }}
            >
              {bot.name ?? bot.id}
            </button>
          ))}
          {!bots?.length && (
            <div className="px-3 py-2 text-xs" style={{ color: t.textDim }}>
              No bots available
            </div>
          )}
        </div>
      )}
    </div>
  );
}
