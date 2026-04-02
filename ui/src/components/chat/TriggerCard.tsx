import { useState, memo } from "react";
import { View, Text, Platform, Pressable } from "react-native";
import { ChevronRight, ExternalLink } from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "../../theme/tokens";
import { formatTimeShort } from "../../utils/time";
import type { Message } from "../../types/api";

interface TriggerStyle {
  label: string;
  icon: string;
  /** Accent color for border, text, links */
  color: string;
  /** rgba tuples for backgrounds/borders at various opacities */
  rgb: string;
}

const TRIGGER_CONFIG: Record<string, TriggerStyle> = {
  scheduled_task: { label: "Scheduled Task", icon: "🔁", color: "#8b5cf6", rgb: "139,92,246" },
  callback: { label: "Task Callback", icon: "↩", color: "#8b5cf6", rgb: "139,92,246" },
  delegation_callback: { label: "Delegation Result", icon: "↩", color: "#8b5cf6", rgb: "139,92,246" },
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
  if (trigger === "delegation_callback")
    return meta.delegation_child_display ? `from ${meta.delegation_child_display}` : null;
  if (trigger === "callback") return meta.task_title || null;
  return null;
}

interface Props {
  message: Message;
  botName?: string;
}

export const TriggerCard = memo(function TriggerCard({ message }: Props) {
  const [expanded, setExpanded] = useState(false);
  const t = useThemeTokens();
  const router = useRouter();
  const isWeb = Platform.OS === "web";

  const meta = (message.metadata ?? {}) as Record<string, any>;
  const trigger = meta.trigger as string;
  const config = TRIGGER_CONFIG[trigger];
  if (!config) return null;

  const { label, icon, color, rgb } = config;
  const subtitle = getSubtitle(meta);
  const taskId = meta.task_id as string | undefined;
  const timestamp = formatTimeShort(message.created_at);
  const promptText = message.content?.trim();
  const hasPrompt = !!promptText;

  if (isWeb) {
    return (
      <div
        style={{
          margin: "6px 20px",
          borderLeft: `3px solid ${color}`,
          borderRadius: 8,
          backgroundColor: `rgba(${rgb},0.06)`,
          padding: "10px 14px",
          transition: "background-color 0.15s",
        }}
      >
        {/* Header row */}
        <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
            <span style={{ fontSize: 15, lineHeight: 1 }}>{icon}</span>
            <span style={{ fontSize: 13, fontWeight: 600, color, letterSpacing: 0.1 }}>{label}</span>
          </div>
          <span style={{ fontSize: 11, color: t.textDim }}>{timestamp}</span>
        </div>

        {/* Subtitle */}
        {subtitle && (
          <div
            style={{
              fontSize: 12,
              color: t.textMuted,
              marginTop: 3,
              marginLeft: 24,
              overflow: "hidden",
              textOverflow: "ellipsis",
              whiteSpace: "nowrap",
            }}
          >
            {subtitle}
          </div>
        )}

        {/* Actions row */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            marginTop: 8,
            marginLeft: 24,
          }}
        >
          {hasPrompt ? (
            <div
              role="button"
              tabIndex={0}
              onClick={() => setExpanded(!expanded)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") setExpanded(!expanded); }}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                cursor: "pointer",
                fontSize: 11,
                color: t.textMuted,
                userSelect: "none",
                padding: "2px 6px 2px 2px",
                borderRadius: 4,
                transition: "background-color 0.15s",
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLDivElement).style.backgroundColor = `rgba(${rgb},0.1)`; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLDivElement).style.backgroundColor = "transparent"; }}
            >
              <ChevronRight
                size={12}
                color={t.textMuted}
                style={{
                  transition: "transform 0.2s ease",
                  transform: expanded ? "rotate(90deg)" : "rotate(0deg)",
                } as any}
              />
              <span>{expanded ? "Hide prompt" : "Show prompt"}</span>
            </div>
          ) : (
            <div />
          )}
          {taskId && (
            <div
              role="button"
              tabIndex={0}
              onClick={() => router.push(`/admin/tasks/${taskId}`)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") router.push(`/admin/tasks/${taskId}`); }}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: 4,
                cursor: "pointer",
                fontSize: 11,
                color,
                padding: "2px 6px",
                borderRadius: 4,
                transition: "background-color 0.15s, opacity 0.15s",
                opacity: 0.85,
              }}
              onMouseEnter={(e) => {
                const el = e.currentTarget as HTMLDivElement;
                el.style.backgroundColor = `rgba(${rgb},0.1)`;
                el.style.opacity = "1";
              }}
              onMouseLeave={(e) => {
                const el = e.currentTarget as HTMLDivElement;
                el.style.backgroundColor = "transparent";
                el.style.opacity = "0.85";
              }}
            >
              <span>View task</span>
              <ExternalLink size={10} color={color} />
            </div>
          )}
        </div>

        {/* Expandable prompt area — animated via max-height + opacity */}
        {hasPrompt && (
          <div
            style={{
              overflow: "hidden",
              maxHeight: expanded ? 320 : 0,
              opacity: expanded ? 1 : 0,
              transition: "max-height 0.25s ease, opacity 0.2s ease, margin 0.25s ease",
              marginTop: expanded ? 8 : 0,
            }}
          >
            <div
              style={{
                borderRadius: 6,
                backgroundColor: `rgba(${rgb},0.04)`,
                border: `1px solid rgba(${rgb},0.12)`,
                padding: "8px 12px",
                maxHeight: 300,
                overflowY: "auto",
              }}
            >
              <pre
                style={{
                  margin: 0,
                  fontSize: 11.5,
                  fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                  color: t.textMuted,
                  whiteSpace: "pre-wrap",
                  wordBreak: "break-word",
                  lineHeight: "1.5",
                }}
              >
                {promptText}
              </pre>
            </div>
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
        borderRadius: 8,
        backgroundColor: `rgba(${rgb},0.06)`,
        padding: 12,
      }}
    >
      <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 7 }}>
          <Text style={{ fontSize: 15 }}>{icon}</Text>
          <Text style={{ fontSize: 13, fontWeight: "600", color }}>{label}</Text>
        </View>
        <Text style={{ fontSize: 11, color: t.textDim }}>{timestamp}</Text>
      </View>
      {subtitle && (
        <Text
          style={{ fontSize: 12, color: t.textMuted, marginTop: 3, marginLeft: 24 }}
          numberOfLines={1}
          ellipsizeMode="tail"
        >
          {subtitle}
        </Text>
      )}
      {taskId && (
        <Pressable
          onPress={() => router.push(`/admin/tasks/${taskId}`)}
          style={{ marginTop: 8, marginLeft: 24 }}
        >
          <Text style={{ fontSize: 11, color }}>View task →</Text>
        </Pressable>
      )}
    </View>
  );
});
