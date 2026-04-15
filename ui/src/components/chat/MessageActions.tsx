/**
 * Message action buttons (copy, view trace) and avatar component.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useState } from "react";
import { Copy, Check, Activity } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { writeToClipboard } from "../../utils/clipboard";
import type { ThemeTokens } from "../../theme/tokens";

// ---------------------------------------------------------------------------
// Copy + trace buttons -- appears on hover (web only)
// ---------------------------------------------------------------------------

export function MessageActions({
  text,
  fullTurnText,
  correlationId,
  t,
}: {
  text: string;
  /** Concatenated text of all segments in a multi-segment bot turn */
  fullTurnText?: string;
  correlationId?: string;
  t: ThemeTokens;
}) {
  const [copied, setCopied] = useState<"single" | "full" | false>(false);
  const navigate = useNavigate();

  const btnStyle = (active?: boolean): React.CSSProperties => ({
    display: "flex", flexDirection: "row",
    alignItems: "center",
    justifyContent: "center",
    width: 28,
    height: 28,
    borderRadius: 6,
    border: `1px solid ${t.surfaceBorder}`,
    backgroundColor: t.surfaceRaised,
    color: active ? "#10b981" : t.textMuted,
    cursor: "pointer",
    padding: 0,
    boxShadow: "0 1px 4px rgba(0,0,0,0.15)",
  });

  const doCopy = (value: string, which: "single" | "full") => {
    writeToClipboard(value).then(() => {
      setCopied(which);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="msg-actions" style={{ userSelect: "none" }}>
      {correlationId && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            navigate(`/admin/logs/${correlationId}`);
          }}
          title="View trace"
          style={btnStyle()}
        >
          <Activity size={14} />
        </button>
      )}
      <button
        onClick={(e) => {
          e.stopPropagation();
          doCopy(fullTurnText || text, fullTurnText ? "full" : "single");
        }}
        title={fullTurnText ? "Copy full response" : "Copy message"}
        style={btnStyle(!!copied)}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Avatar
// ---------------------------------------------------------------------------

export function Avatar({ name, isUser, onClick }: { name: string; isUser: boolean; onClick?: () => void }) {
  const bg = isUser ? "#4b5563" : avatarColorLocal(name);
  const letter = isUser ? "U" : (name[0] || "B").toUpperCase();
  const clickable = !isUser && !!onClick;

  return (
    <div
      onClick={clickable ? onClick : undefined}
      style={{
        width: 36,
        height: 36,
        borderRadius: 6,
        backgroundColor: bg,
        display: "flex", flexDirection: "row",
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
        userSelect: "none",
        cursor: clickable ? "pointer" : undefined,
      }}
    >
      <span style={{ color: "#fff", fontSize: 14, fontWeight: 700 }}>
        {letter}
      </span>
    </div>
  );
}

// Local copy to keep this file self-contained
function avatarColorLocal(name: string): string {
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    hash = name.charCodeAt(i) + ((hash << 5) - hash);
  }
  const colors = [
    "#6366f1", "#8b5cf6", "#ec4899", "#f59e0b",
    "#10b981", "#06b6d4", "#ef4444", "#e879f9",
  ];
  return colors[Math.abs(hash) % colors.length];
}
