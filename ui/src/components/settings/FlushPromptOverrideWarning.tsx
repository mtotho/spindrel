import { AlertTriangle } from "lucide-react";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useThemeTokens } from "@/src/theme/tokens";

export function FlushPromptOverrideWarning() {
  const t = useThemeTokens();
  const { data: bots } = useAdminBots();
  const wsFileBots =
    bots?.filter((b) => b.memory_scheme === "workspace-files") ?? [];
  if (!wsFileBots.length) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        gap: 10,
        backgroundColor: "rgba(245,158,11,0.08)",
        border: "1px solid rgba(245,158,11,0.25)",
        borderRadius: 8,
        padding: 12,
        marginBottom: 4,
      }}
    >
      <AlertTriangle
        size={15}
        color="#f59e0b"
        style={{ marginTop: 1, flexShrink: 0 }}
      />
      <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 4 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: "#f59e0b" }}>
          Ignored by workspace-files bots
        </span>
        <span style={{ fontSize: 11, color: t.textMuted, lineHeight: "17px" }}>
          {wsFileBots.length === bots?.length
            ? "All bots use workspace-files memory — this prompt is never used. "
            : `This prompt is ignored for ${wsFileBots.length} bot${wsFileBots.length > 1 ? "s" : ""} using workspace-files memory. `}
          Those bots use a built-in flush prompt that writes to disk instead.
        </span>
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            flexWrap: "wrap",
            gap: 4,
            marginTop: 2,
          }}
        >
          {wsFileBots.map((b) => (
            <div
              key={b.id}
              style={{
                backgroundColor: "rgba(245,158,11,0.1)",
                paddingLeft: 7,
                paddingRight: 7,
                paddingTop: 2,
                paddingBottom: 2,
                borderRadius: 4,
              }}
            >
              <span
                style={{ fontSize: 10, fontWeight: 600, color: "#f59e0b" }}
              >
                {b.name}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
