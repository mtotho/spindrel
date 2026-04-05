import { useState } from "react";
import { AlertTriangle, X } from "lucide-react";

interface Props {
  behavior: "queue" | "drop";
}

export function SystemPauseBanner({ behavior }: Props) {
  const [dismissed, setDismissed] = useState(false);
  if (dismissed) return null;

  const description =
    behavior === "queue"
      ? "Messages will be queued and processed when unpaused."
      : "Messages are being dropped.";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        paddingLeft: 16,
        paddingRight: 16,
        paddingTop: 8,
        paddingBottom: 8,
        backgroundColor: "rgba(245, 158, 11, 0.15)",
        flexShrink: 0,
      }}
    >
      <AlertTriangle size={16} color="#f59e0b" />
      <span style={{ fontSize: 14, flex: 1, color: "#f59e0b" }}>
        System Paused — {description}
      </span>
      <button
        className="banner-btn"
        onClick={() => setDismissed(true)}
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          width: 28,
          height: 28,
          borderRadius: 6,
          border: "none",
          background: "transparent",
          cursor: "pointer",
          padding: 0,
        }}
      >
        <X size={14} color="#f59e0b" />
      </button>
    </div>
  );
}
