import type { BindingSuggestion } from "@/src/api/hooks/useChannels";

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
        <span className="inline-block h-3 w-3 animate-spin rounded-full border-2 border-text-dim border-t-transparent" />
        <span className="text-[11px] text-text-dim">Loading recent chats...</span>
      </div>
    );
  }

  if (suggestions.length === 0) return null;

  return (
    <div className="flex flex-col gap-1">
      <span className="text-[11px] font-semibold text-text-dim">Recent chats</span>
      <div className="flex max-h-[200px] flex-col gap-0.5 overflow-y-auto rounded-md border border-surface-border bg-surface-raised">
        {suggestions.map((s) => {
          const isSelected = selectedClientId === s.client_id;
          return (
            <button
              key={s.client_id}
              type="button"
              onClick={() => onSelect(s)}
              className={
                `flex flex-col gap-px px-3 py-2 text-left transition-colors ` +
                (isSelected ? "bg-accent/[0.08]" : "bg-transparent hover:bg-surface-overlay/60")
              }
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
            </button>
          );
        })}
      </div>
    </div>
  );
}
