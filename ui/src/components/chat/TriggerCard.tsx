import { useState } from "react";
import { View, Text, Platform, Pressable } from "react-native";
import { ChevronRight, ChevronDown, ExternalLink } from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "../../theme/tokens";
import { formatTimeShort } from "../../utils/time";
import type { Message } from "../../types/api";

const TRIGGER_CONFIG: Record<string, { label: string; icon: string; color: string }> = {
  scheduled_task: { label: "Scheduled Task", icon: "🔁", color: "#8b5cf6" },
  callback: { label: "Task Callback", icon: "↩", color: "#8b5cf6" },
  harness_callback: { label: "Harness Callback", icon: "⚡", color: "#06b6d4" },
  delegation_callback: { label: "Delegation Result", icon: "↩", color: "#8b5cf6" },
};

export const SUPPORTED_TRIGGERS = new Set(Object.keys(TRIGGER_CONFIG));

function getSubtitle(meta: Record<string, any>): string | null {
  const trigger = meta.trigger as string;
  if (trigger === "scheduled_task") {
    const parts: string[] = [];
    if (meta.task_title) parts.push(`"${meta.task_title}"`);
    if (meta.recurrence) parts.push(`recurring ${meta.recurrence}`);
    return parts.length ? parts.join("  ·  ") : null;
  }
  if (trigger === "harness_callback") return meta.harness_name || null;
  if (trigger === "delegation_callback") return meta.delegation_child_display ? `from ${meta.delegation_child_display}` : null;
  if (trigger === "callback") return meta.task_title || null;
  return null;
}

interface Props {
  message: Message;
  botName?: string;
}

export function TriggerCard({ message }: Props) {
  const [expanded, setExpanded] = useState(false);
  const t = useThemeTokens();
  const router = useRouter();
  const isWeb = Platform.OS === "web";

  const meta = (message.metadata ?? {}) as Record<string, any>;
  const trigger = meta.trigger as string;
  const config = TRIGGER_CONFIG[trigger];
  if (!config) return null;

  const { label, icon, color } = config;
  const subtitle = getSubtitle(meta);
  const taskId = meta.task_id as string | undefined;
  const timestamp = formatTimeShort(message.created_at);
  const promptText = message.content?.trim();
  const hasPrompt = !!promptText;

  if (isWeb) {
    return (
      <div
        style={{
          margin: "4px 16px 4px 52px",
          borderLeft: `3px solid ${color}`,
          borderRadius: 6,
          backgroundColor: `${color}08`,
          padding: "8px 12px",
        }}
      >
        {/* Header row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
            <span style={{ fontSize: 14 }}>{icon}</span>
            <span style={{ fontSize: 13, fontWeight: 600, color }}>{label}</span>
          </div>
          <span style={{ fontSize: 11, color: t.textDim }}>{timestamp}</span>
        </div>

        {/* Subtitle */}
        {subtitle && (
          <div style={{ fontSize: 12, color: t.textMuted, marginTop: 2, marginLeft: 22 }}>
            {subtitle}
          </div>
        )}

        {/* Actions row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginTop: 6, marginLeft: 22 }}>
          {hasPrompt ? (
            <div
              onClick={() => setExpanded(!expanded)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                cursor: "pointer",
                fontSize: 11,
                color: t.textMuted,
                userSelect: "none",
              }}
            >
              {expanded
                ? <ChevronDown size={12} color={t.textMuted} />
                : <ChevronRight size={12} color={t.textMuted} />
              }
              <span>{expanded ? "Hide prompt" : "Show prompt"}</span>
            </div>
          ) : (
            <div />
          )}
          {taskId && (
            <div
              onClick={() => router.push(`/admin/tasks/${taskId}`)}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 3,
                cursor: "pointer",
                fontSize: 11,
                color,
              }}
            >
              <span>View task</span>
              <ExternalLink size={10} color={color} />
            </div>
          )}
        </div>

        {/* Expanded prompt */}
        {expanded && hasPrompt && (
          <div
            style={{
              marginTop: 6,
              borderRadius: 4,
              backgroundColor: `${color}06`,
              border: `1px solid ${color}15`,
              padding: "6px 10px",
              maxHeight: 300,
              overflowY: "auto",
            }}
          >
            <pre
              style={{
                margin: 0,
                fontSize: 11,
                fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                color: t.textMuted,
                whiteSpace: "pre-wrap",
                wordBreak: "break-word",
                lineHeight: "1.4",
              }}
            >
              {promptText}
            </pre>
          </div>
        )}
      </div>
    );
  }

  // Native: simple non-expandable card
  return (
    <View
      style={{
        marginHorizontal: 16,
        marginVertical: 4,
        borderLeftWidth: 3,
        borderLeftColor: color,
        borderRadius: 6,
        backgroundColor: `${color}08`,
        padding: 10,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6 }}>
          <Text style={{ fontSize: 14 }}>{icon}</Text>
          <Text style={{ fontSize: 13, fontWeight: "600", color }}>{label}</Text>
        </View>
        <Text style={{ fontSize: 11, color: t.textDim }}>{timestamp}</Text>
      </View>
      {subtitle && (
        <Text style={{ fontSize: 12, color: t.textMuted, marginTop: 2, marginLeft: 22 }}>
          {subtitle}
        </Text>
      )}
      {taskId && (
        <Pressable
          onPress={() => router.push(`/admin/tasks/${taskId}`)}
          style={{ marginTop: 6, marginLeft: 22 }}
        >
          <Text style={{ fontSize: 11, color }}>View task →</Text>
        </Pressable>
      )}
    </View>
  );
}
