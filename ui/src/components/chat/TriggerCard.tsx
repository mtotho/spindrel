import { useState, memo } from "react";
import { ChevronRight, ExternalLink, Timer, CornerDownLeft, Repeat } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { formatTimeShort } from "../../utils/time";
import type { Message } from "../../types/api";
import type { LucideIcon } from "lucide-react";

interface TriggerStyle {
  label: string;
  Icon: LucideIcon;
}

const TRIGGER_CONFIG: Record<string, TriggerStyle> = {
  scheduled_task: { label: "Scheduled Task", Icon: Timer },
  callback: { label: "Task Callback", Icon: Repeat },
  delegation_callback: { label: "Delegation Result", Icon: CornerDownLeft },
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
  const navigate = useNavigate();

  const meta = (message.metadata ?? {}) as Record<string, any>;
  const trigger = meta.trigger as string;
  const config = TRIGGER_CONFIG[trigger];
  if (!config) return null;

  const { label, Icon } = config;
  const subtitle = getSubtitle(meta);
  const taskId = meta.task_id as string | undefined;
  const timestamp = formatTimeShort(message.created_at);
  const promptText = message.content?.trim();
  const hasPrompt = !!promptText;

  return (
    <div className="mx-5 my-1.5 border-l-2 border-surface-border rounded-lg bg-surface-raised/40 px-3.5 py-2.5 transition-colors">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon size={14} className="text-text-dim flex-shrink-0" />
          <span className="text-xs font-semibold text-text-muted tracking-wide">{label}</span>
        </div>
        <span className="text-[11px] text-text-dim">{timestamp}</span>
      </div>

      {/* Subtitle */}
      {subtitle && (
        <p className="text-xs text-text-dim mt-1 ml-[22px] truncate">{subtitle}</p>
      )}

      {/* Actions row */}
      <div className="flex items-center justify-between mt-2 ml-[22px]">
        {hasPrompt ? (
          <button
            onClick={() => setExpanded(!expanded)}
            className="inline-flex items-center gap-1 text-[11px] text-text-dim hover:text-text-muted px-1.5 py-0.5 rounded transition-colors hover:bg-surface-overlay cursor-pointer border-none bg-transparent"
          >
            <ChevronRight
              size={12}
              className={`transition-transform duration-200 ${expanded ? "rotate-90" : ""}`}
            />
            <span>{expanded ? "Hide prompt" : "Show prompt"}</span>
          </button>
        ) : (
          <div />
        )}
        {taskId && (
          <button
            onClick={() => navigate(`/admin/tasks/${taskId}`)}
            className="inline-flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover px-1.5 py-0.5 rounded transition-colors hover:bg-accent/5 cursor-pointer border-none bg-transparent opacity-85 hover:opacity-100"
          >
            <span>View task</span>
            <ExternalLink size={10} />
          </button>
        )}
      </div>

      {/* Expandable prompt area */}
      {hasPrompt && (
        <div
          className="overflow-hidden transition-all duration-250 ease-in-out"
          style={{
            maxHeight: expanded ? 320 : 0,
            opacity: expanded ? 1 : 0,
            marginTop: expanded ? 8 : 0,
          }}
        >
          <div className="rounded-md bg-surface-overlay/50 border border-surface-border px-3 py-2 max-h-[300px] overflow-y-auto">
            <pre className="m-0 text-[11.5px] font-mono text-text-dim whitespace-pre-wrap break-words leading-relaxed">
              {promptText}
            </pre>
          </div>
        </div>
      )}
    </div>
  );
});
