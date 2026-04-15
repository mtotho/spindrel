import { useState, memo } from "react";
import { ChevronRight, ExternalLink } from "lucide-react";
import { useNavigate } from "react-router-dom";
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
  scheduled_task: { label: "Scheduled Task", icon: "\u{1F501}", color: "#8b5cf6", rgb: "139,92,246" },
  callback: { label: "Task Callback", icon: "\u21A9", color: "#8b5cf6", rgb: "139,92,246" },
  delegation_callback: { label: "Delegation Result", icon: "\u21A9", color: "#8b5cf6", rgb: "139,92,246" },
};

export const SUPPORTED_TRIGGERS = new Set(Object.keys(TRIGGER_CONFIG));

function getSubtitle(meta: Record<string, any>): string | null {
  const trigger = meta.trigger as string;
  if (trigger === "scheduled_task") {
    const parts: string[] = [];
    if (meta.task_title) parts.push(`"${meta.task_title}"`);
    if (meta.recurrence) parts.push(`recurring ${meta.recurrence}`);
    return parts.length ? parts.join("  \u00B7  ") : null;
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
  const navigate = useNavigate();

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
      <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 7 }}>
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
          display: "flex", flexDirection: "row",
          alignItems: "center",
          justifyContent: "space-between",
          marginTop: 8,
          marginLeft: 24,
        }}
      >
        {hasPrompt ? (
          <button
            onClick={() => setExpanded(!expanded)}
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 4,
              cursor: "pointer",
              fontSize: 11,
              color: t.textMuted,
              userSelect: "none",
              padding: "2px 6px 2px 2px",
              borderRadius: 4,
              border: "none",
              backgroundColor: "transparent",
              transition: "background-color 0.15s",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = `rgba(${rgb},0.1)`; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = "transparent"; }}
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
          </button>
        ) : (
          <div />
        )}
        {taskId && (
          <button
            onClick={() => navigate(`/admin/tasks/${taskId}`)}
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 4,
              cursor: "pointer",
              fontSize: 11,
              color,
              padding: "2px 6px",
              borderRadius: 4,
              border: "none",
              backgroundColor: "transparent",
              transition: "background-color 0.15s, opacity 0.15s",
              opacity: 0.85,
            }}
            onMouseEnter={(e) => {
              const el = e.currentTarget as HTMLButtonElement;
              el.style.backgroundColor = `rgba(${rgb},0.1)`;
              el.style.opacity = "1";
            }}
            onMouseLeave={(e) => {
              const el = e.currentTarget as HTMLButtonElement;
              el.style.backgroundColor = "transparent";
              el.style.opacity = "0.85";
            }}
          >
            <span>View task</span>
            <ExternalLink size={10} color={color} />
          </button>
        )}
      </div>

      {/* Expandable prompt area -- animated via max-height + opacity */}
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
});
