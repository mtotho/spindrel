import type { BindingSuggestion } from "@/src/api/hooks/useChannels";
import { Spinner } from "@/src/components/shared/Spinner";
import { SettingsControlRow, SettingsGroupLabel } from "@/src/components/shared/SettingsControls";

export function SuggestionsPicker({
  suggestions,
  isLoading,
  onSelect,
  selectedClientId,
}: {
  suggestions: BindingSuggestion[];
  isLoading: boolean;
  onSelect: (s: BindingSuggestion) => void;
  selectedClientId: string;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center gap-2 py-2">
        <Spinner />
        <span className="text-[11px] text-text-dim">Loading recent chats...</span>
      </div>
    );
  }

  if (suggestions.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      <SettingsGroupLabel label="Recent chats" />
      <div className="flex max-h-[200px] flex-col gap-1 overflow-y-auto">
        {suggestions.map((s) => {
          const isSelected = selectedClientId === s.client_id;
          return (
            <SettingsControlRow
              key={s.client_id}
              onClick={() => onSelect(s)}
              active={isSelected}
              compact
            >
              <span className="text-[12px] font-semibold text-text">
                {s.display_name}
              </span>
              <span className="font-mono text-[10px] text-text-dim">
                {s.client_id}
              </span>
              {s.description && (
                <span className="max-w-full truncate text-[10px] text-text-muted">
                  {s.description}
                </span>
              )}
            </SettingsControlRow>
          );
        })}
      </div>
    </div>
  );
}
