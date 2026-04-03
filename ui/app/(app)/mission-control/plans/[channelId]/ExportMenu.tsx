import { useState } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { downloadBlob } from "@/src/utils/download";
import { Download } from "lucide-react";

// ---------------------------------------------------------------------------
// Export menu — dropdown for markdown / JSON plan export
// ---------------------------------------------------------------------------
export function ExportMenu({
  channelId,
  planId,
  planTitle,
}: {
  channelId: string;
  planId: string;
  planTitle: string;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const doExport = async (format: "markdown" | "json") => {
    setExporting(true);
    try {
      const { apiFetchText } = await import("@/src/api/client");
      const content = await apiFetchText(
        `/integrations/mission_control/channels/${channelId}/plans/${planId}/export?format=${format}`,
      );
      const ext = format === "markdown" ? "md" : "json";
      const slug = planTitle.toLowerCase().replace(/[^a-z0-9]+/g, "-").slice(0, 40);
      downloadBlob(content, `plan-${slug}.${ext}`, format === "markdown" ? "text/markdown" : "application/json");
    } catch {
      // silently fail
    } finally {
      setExporting(false);
      setOpen(false);
    }
  };

  return (
    <div style={{ position: "relative" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        disabled={exporting}
        style={{
          display: "flex", alignItems: "center", gap: 4,
          padding: "4px 10px", fontSize: 11, fontWeight: 600,
          border: `1px solid ${t.surfaceBorder}`, borderRadius: 5,
          background: "transparent", color: t.textDim, cursor: "pointer",
          opacity: exporting ? 0.5 : 1,
        }}
      >
        <Download size={12} />
        Export
      </button>
      {open && (
        <div
          style={{
            position: "absolute",
            top: 28,
            right: 0,
            zIndex: 100,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            boxShadow: "0 4px 12px rgba(0,0,0,0.15)",
            minWidth: 120,
            overflow: "hidden",
          }}
        >
          <button
            onClick={() => doExport("markdown")}
            style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "8px 12px", fontSize: 12, color: t.text,
              background: "transparent", border: "none", cursor: "pointer",
            }}
          >
            Markdown
          </button>
          <button
            onClick={() => doExport("json")}
            style={{
              display: "block", width: "100%", textAlign: "left",
              padding: "8px 12px", fontSize: 12, color: t.text,
              background: "transparent", border: "none", cursor: "pointer",
            }}
          >
            JSON
          </button>
        </div>
      )}
    </div>
  );
}
