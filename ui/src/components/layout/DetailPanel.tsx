import { X } from "lucide-react";
import { useUIStore } from "../../stores/ui";
import { useThemeTokens } from "../../theme/tokens";

export function DetailPanel() {
  const { type, id } = useUIStore((s) => s.detailPanel);
  const closeDetail = useUIStore((s) => s.closeDetail);
  const t = useThemeTokens();

  if (!type) return null;

  return (
    <div
      style={{
        width: 350,
        backgroundColor: t.surface,
        borderLeft: `1px solid ${t.surfaceBorder}`,
        flexShrink: 0,
        display: "flex",
        flexDirection: "column",
      }}
    >
      {/* Header */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          paddingLeft: 16,
          paddingRight: 16,
          paddingTop: 12,
          paddingBottom: 12,
          borderBottom: `1px solid ${t.surfaceBorder}`,
        }}
      >
        <span
          style={{
            color: t.text,
            fontWeight: 500,
            fontSize: 14,
            textTransform: "capitalize",
          }}
        >
          {type} Detail
        </span>
        <button
          className="header-icon-btn"
          onClick={closeDetail}
          style={{ padding: 4, width: 28, height: 28 }}
        >
          <X size={16} color={t.textMuted} />
        </button>
      </div>

      {/* Content -- will be replaced with type-specific views */}
      <div style={{ flex: 1, padding: 16, overflowY: "auto" }}>
        <span style={{ color: t.textMuted, fontSize: 14 }}>
          {type}: {id}
        </span>
      </div>
    </div>
  );
}
