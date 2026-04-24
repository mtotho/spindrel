/**
 * PinScopePicker — shared "Runs as: You / A bot" radio group.
 *
 * Used at pin-time by `AddFromChannelSheet` and at edit-time by
 * `EditPinDrawer` so the language + data-model stay consistent. The picker
 * writes through to the pin's ``source_bot_id``: ``null`` for user scope,
 * ``<bot_id>`` for bot scope. The widget renderer reads the same field to
 * drive the scope chip (``@bot`` vs ``as you``).
 */
import type React from "react";
import { SelectDropdown } from "@/src/components/shared/SelectDropdown";

export type PinScope = { kind: "user" } | { kind: "bot"; botId: string };

export function pinScopeFromBotId(botId: string | null | undefined): PinScope {
  return botId ? { kind: "bot", botId } : { kind: "user" };
}

export function pinScopeToBotId(scope: PinScope): string | null {
  return scope.kind === "bot" ? scope.botId : null;
}

interface Props {
  scope: PinScope;
  onChange: (next: PinScope) => void;
  bots: { id: string; name?: string; display_name?: string | null }[] | null;
  /** When set, renders without the outer bordered card — for callers that
   *  already provide their own section chrome (e.g. EditPinDrawer). */
  bare?: boolean;
  disabled?: boolean;
}

export function PinScopePicker({ scope, onChange, bots, bare = false, disabled = false }: Props) {
  const firstBotId = bots?.[0]?.id ?? "";
  const inner = (
    <div className="flex flex-col gap-1.5">
      <label className="flex items-start gap-2 cursor-pointer text-[12px]">
        <input
          type="radio"
          name="pin-scope"
          checked={scope.kind === "user"}
          onChange={() => onChange({ kind: "user" })}
          disabled={disabled}
          className="mt-0.5"
        />
        <span className="flex-1">
          <span className="font-medium text-text">You</span>
          <span className="block text-[11px] text-text-muted">
            Each viewer sees data through their own account.
          </span>
        </span>
      </label>
      <label className="flex items-start gap-2 cursor-pointer text-[12px]">
        <input
          type="radio"
          name="pin-scope"
          checked={scope.kind === "bot"}
          onChange={() =>
            onChange({
              kind: "bot",
              botId: scope.kind === "bot" ? scope.botId : firstBotId,
            })
          }
          disabled={disabled || !bots || bots.length === 0}
          className="mt-0.5"
        />
        <span className="flex-1">
          <span className="font-medium text-text">A bot</span>
          <span className="block text-[11px] text-text-muted">
            Every viewer sees the same data through the bot's credentials.
          </span>
          {scope.kind === "bot" && bots && bots.length > 0 && (
            <div className="mt-1">
              <SelectDropdown
                value={scope.botId || firstBotId}
                options={bots.map((bot) => ({
                  value: bot.id,
                  label: bot.display_name || bot.name || bot.id,
                  searchText: `${bot.display_name ?? ""} ${bot.name ?? ""} ${bot.id}`,
                }))}
                onChange={(botId) => onChange({ kind: "bot", botId })}
                disabled={disabled}
                searchable
                searchPlaceholder="Search bots..."
                size="compact"
                popoverWidth="content"
              />
            </div>
          )}
        </span>
      </label>
    </div>
  );

  if (bare) return inner;
  return (
    <div className="rounded-md border border-surface-border bg-surface px-3 py-2">
      <div className="mb-1.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
        Runs as
      </div>
      {inner}
    </div>
  );
}

/** Legacy default export alias — older imports still reference `ScopePicker`. */
export const ScopePicker: React.FC<Props> = PinScopePicker;
