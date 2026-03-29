import { useState, useRef, useEffect } from "react";
import { Database } from "lucide-react";
import type { FileIndexEntry } from "../../api/hooks/useWorkspaces";
import { useThemeTokens } from "../../theme/tokens";

interface IndexStatusBadgeProps {
  entry: FileIndexEntry;
}

export function IndexStatusBadge({ entry }: IndexStatusBadgeProps) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
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

  const lastIndexed = entry.last_indexed
    ? new Date(entry.last_indexed).toLocaleString()
    : "Unknown";

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 4,
          background: "rgba(20,184,166,0.12)",
          color: "#14b8a6",
          border: "1px solid rgba(20,184,166,0.3)",
          borderRadius: 4,
          padding: "2px 8px",
          fontSize: 11,
          cursor: "pointer",
          fontWeight: 600,
        }}
      >
        <Database size={10} /> Indexed
      </button>

      {open && (
        <div
          style={{
            position: "absolute",
            top: "100%",
            right: 0,
            marginTop: 4,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: 12,
            minWidth: 220,
            zIndex: 100,
            fontSize: 12,
            color: t.text,
          }}
        >
          <div style={{ marginBottom: 8, fontWeight: 600, color: "#14b8a6", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Index Details
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <DetailRow label="Chunks" value={String(entry.chunk_count)} t={t} />
            <DetailRow label="Last indexed" value={lastIndexed} t={t} />
            {entry.language && <DetailRow label="Language" value={entry.language} t={t} />}
            {entry.embedding_model && <DetailRow label="Model" value={entry.embedding_model} t={t} />}
            <div>
              <span style={{ color: t.textDim, fontSize: 11 }}>Bots:</span>
              <div style={{ marginTop: 2 }}>
                {entry.bots.map((b) => (
                  <span
                    key={b.bot_id}
                    style={{
                      display: "inline-block",
                      background: "rgba(59,130,246,0.1)",
                      color: "#6b9eff",
                      borderRadius: 3,
                      padding: "1px 6px",
                      fontSize: 11,
                      marginRight: 4,
                      marginBottom: 2,
                    }}
                  >
                    {b.bot_name}
                  </span>
                ))}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function DetailRow({ label, value, t }: { label: string; value: string; t: ReturnType<typeof useThemeTokens> }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
      <span style={{ color: t.textDim, fontSize: 11 }}>{label}</span>
      <span style={{ fontSize: 11, color: t.text }}>{value}</span>
    </div>
  );
}
