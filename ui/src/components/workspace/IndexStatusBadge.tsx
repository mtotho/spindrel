import { useState, useRef, useEffect } from "react";
import { Database } from "lucide-react";
import type { FileIndexEntry } from "../../api/hooks/useWorkspaces";

interface IndexStatusBadgeProps {
  entry: FileIndexEntry;
}

export function IndexStatusBadge({ entry }: IndexStatusBadgeProps) {
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
            background: "#1a1a1a",
            border: "1px solid #333",
            borderRadius: 6,
            padding: 12,
            minWidth: 220,
            zIndex: 100,
            fontSize: 12,
            color: "#ccc",
          }}
        >
          <div style={{ marginBottom: 8, fontWeight: 600, color: "#14b8a6", fontSize: 11, textTransform: "uppercase", letterSpacing: 0.5 }}>
            Index Details
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
            <Row label="Chunks" value={String(entry.chunk_count)} />
            <Row label="Last indexed" value={lastIndexed} />
            {entry.language && <Row label="Language" value={entry.language} />}
            {entry.embedding_model && <Row label="Model" value={entry.embedding_model} />}
            <div>
              <span style={{ color: "#666", fontSize: 11 }}>Bots:</span>
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

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ display: "flex", justifyContent: "space-between", gap: 12 }}>
      <span style={{ color: "#666", fontSize: 11 }}>{label}</span>
      <span style={{ fontSize: 11, color: "#ddd" }}>{value}</span>
    </div>
  );
}
