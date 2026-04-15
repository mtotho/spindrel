import { useThemeTokens } from "@/src/theme/tokens";
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
  const t = useThemeTokens();

  if (isLoading) {
    return (
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, padding: "8px 0" }}>
        <span
          style={{
            width: 12,
            height: 12,
            border: `2px solid ${t.textDim}`,
            borderTopColor: "transparent",
            borderRadius: "50%",
            display: "inline-block",
            animation: "spin 0.6s linear infinite",
          }}
        />
        <span style={{ fontSize: 11, color: t.textDim }}>Loading recent chats...</span>
      </div>
    );
  }

  if (suggestions.length === 0) return null;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <span style={{ fontSize: 11, fontWeight: 600, color: t.textDim }}>Recent chats</span>
      <div
        style={{
          display: "flex",
          flexDirection: "column",
          gap: 2,
          maxHeight: 200,
          overflowY: "auto",
          borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`,
          background: t.surfaceRaised,
        }}
      >
        {suggestions.map((s) => {
          const isSelected = selectedClientId === s.client_id;
          return (
            <button
              key={s.client_id}
              onClick={() => onSelect(s)}
              style={{
                display: "flex",
                flexDirection: "column",
                gap: 1,
                padding: "8px 12px",
                background: isSelected ? t.accentSubtle : "transparent",
                border: "none",
                borderBottom: `1px solid ${t.surfaceBorder}`,
                cursor: "pointer",
                textAlign: "left",
                transition: "background 0.1s",
              }}
              onMouseEnter={(e) => { if (!isSelected) e.currentTarget.style.background = t.surfaceOverlay; }}
              onMouseLeave={(e) => { if (!isSelected) e.currentTarget.style.background = "transparent"; }}
            >
              <span style={{ fontSize: 12, fontWeight: 600, color: t.text }}>
                {s.display_name}
              </span>
              <span style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
                {s.client_id}
              </span>
              {s.description && (
                <span style={{
                  fontSize: 10,
                  color: t.textMuted,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  maxWidth: "100%",
                }}>
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
