/**
 * Message action buttons (copy, view trace) and avatar component.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useState } from "react";
import { View, Text } from "react-native";
import { Copy, Check, Activity } from "lucide-react";
import { useRouter } from "expo-router";
import { writeToClipboard } from "../../utils/clipboard";
import type { ThemeTokens } from "../../theme/tokens";

// ---------------------------------------------------------------------------
// Copy + trace buttons -- appears on hover (web only)
// ---------------------------------------------------------------------------

export function MessageActions({
  text,
  correlationId,
  t,
}: {
  text: string;
  correlationId?: string;
  t: ThemeTokens;
}) {
  const [copied, setCopied] = useState(false);
  const router = useRouter();

  const btnStyle = (active?: boolean): React.CSSProperties => ({
    display: "flex",
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

  return (
    <div className="msg-actions" style={{ userSelect: "none" }}>
      {correlationId && (
        <button
          onClick={(e) => {
            e.stopPropagation();
            router.push(`/admin/logs/${correlationId}` as any);
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
          writeToClipboard(text).then(() => {
            setCopied(true);
            setTimeout(() => setCopied(false), 2000);
          });
        }}
        title="Copy message"
        style={btnStyle(copied)}
      >
        {copied ? <Check size={14} /> : <Copy size={14} />}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Avatar
// ---------------------------------------------------------------------------

export function Avatar({ name, isUser }: { name: string; isUser: boolean }) {
  // Import avatarColor inline to avoid circular deps -- it's a pure function
  const bg = isUser ? "#4b5563" : avatarColorLocal(name);
  const letter = isUser ? "U" : (name[0] || "B").toUpperCase();
  return (
    <View
      style={{
        width: 36,
        height: 36,
        borderRadius: 6,
        backgroundColor: bg,
        alignItems: "center",
        justifyContent: "center",
        flexShrink: 0,
      }}
    >
      <Text style={{ color: "#fff", fontSize: 14, fontWeight: "700" }}>
        {letter}
      </Text>
    </View>
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
