/**
 * Collapsed message variants for heartbeat and workflow lifecycle messages.
 *
 * These render as compact, expandable rows instead of full message bubbles.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useState } from "react";
import { View, Text, Platform } from "react-native";
import { ChevronRight, ChevronDown, ExternalLink } from "lucide-react";
import { MarkdownContent } from "./MarkdownContent";
import { ToolBadges } from "./ToolBadges";
import type { ThemeTokens } from "../../theme/tokens";
import type { Message, ToolCall } from "../../types/api";

// ---------------------------------------------------------------------------
// Collapsed heartbeat (non-dispatched)
// ---------------------------------------------------------------------------

export function CollapsedHeartbeat({
  displayContent,
  timestamp,
  toolsUsed,
  toolCalls,
  t,
}: {
  displayContent: string;
  timestamp: string;
  toolsUsed: string[];
  toolCalls?: ToolCall[];
  t: ThemeTokens;
}) {
  const [expanded, setExpanded] = useState(false);
  const isWeb = Platform.OS === "web";

  if (!isWeb) {
    return (
      <View style={{ paddingHorizontal: 20, paddingVertical: 2 }}>
        <Text style={{ fontSize: 12, color: t.textDim }}>
          Heartbeat ran -- {timestamp}
        </Text>
      </View>
    );
  }

  return (
    <div
      className="msg-hover"
      style={{
        paddingLeft: 20,
        paddingRight: 20,
        paddingTop: 2,
        paddingBottom: 2,
      }}
    >
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          cursor: "pointer",
          padding: "4px 8px",
          borderRadius: 4,
          fontSize: 12,
          color: t.textDim,
        }}
      >
        {expanded
          ? <ChevronDown size={11} color={t.textDim} />
          : <ChevronRight size={11} color={t.textDim} />
        }
        <span>Heartbeat ran</span>
        <span style={{ fontSize: 11, color: t.textDim, opacity: 0.7 }}>
          {timestamp}
        </span>
      </div>
      {expanded && (
        <div style={{ paddingLeft: 30, paddingTop: 4, paddingBottom: 4 }}>
          <div style={{ fontSize: 14, lineHeight: "1.5", color: t.textMuted, whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
            {displayContent}
          </div>
          {toolsUsed.length > 0 && <ToolBadges toolNames={toolsUsed} toolCalls={toolCalls} t={t} />}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collapsed workflow lifecycle message
// ---------------------------------------------------------------------------

export function CollapsedWorkflow({
  message,
  displayContent,
  timestamp,
  t,
}: {
  message: Message;
  displayContent: string;
  timestamp: string;
  t: ThemeTokens;
}) {
  const [expanded, setExpanded] = useState(false);
  const isWeb = Platform.OS === "web";
  const meta = message.metadata || {};

  const wfEvent = (meta.workflow_event as string) || "unknown";
  const wfName = (meta.workflow_name as string) || "Workflow";
  const wfId = meta.workflow_id as string | undefined;
  const wfRunId = meta.workflow_run_id as string | undefined;
  const totalSteps = meta.total_steps as number | undefined;
  const completedSteps = meta.completed_steps as number | undefined;
  const stepId = meta.step_id as string | undefined;

  const eventConfig: Record<string, { icon: string; label: string; color: string }> = {
    started: { icon: "\u25b6", label: "started", color: "#6366f1" },
    step_done: { icon: "\u2713", label: "step done", color: "#10b981" },
    step_failed: { icon: "\u2717", label: "step failed", color: "#ef4444" },
    completed: { icon: "\u2713", label: "completed", color: "#10b981" },
    failed: { icon: "\u2717", label: "failed", color: "#ef4444" },
  };
  const cfg = eventConfig[wfEvent] || { icon: "\u27f3", label: wfEvent, color: "#8b5cf6" };
  const progress = totalSteps != null && completedSteps != null
    ? `${completedSteps}/${totalSteps}`
    : null;
  const runDetailHref = wfId && wfRunId
    ? `/admin/workflows/${wfId}?tab=runs&run=${wfRunId}`
    : null;

  if (!isWeb) {
    return (
      <View style={{ paddingHorizontal: 20, paddingVertical: 2 }}>
        <Text style={{ fontSize: 12, color: t.textDim }}>
          {wfName} -- {wfEvent} -- {timestamp}
        </Text>
      </View>
    );
  }

  return (
    <div
      className="msg-hover"
      style={{
        paddingLeft: 20,
        paddingRight: 20,
        paddingTop: 2,
        paddingBottom: 2,
      }}
    >
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          cursor: "pointer",
          padding: "4px 8px",
          borderRadius: 4,
          fontSize: 12,
          color: t.textDim,
        }}
      >
        {expanded
          ? <ChevronDown size={11} color={t.textDim} />
          : <ChevronRight size={11} color={t.textDim} />
        }
        <span style={{ color: cfg.color, fontWeight: 600 }}>{cfg.icon}</span>
        <span>{wfName}</span>
        <span style={{
          fontSize: 10, fontWeight: 600, color: cfg.color,
          background: `${cfg.color}18`, border: `1px solid ${cfg.color}30`,
          borderRadius: 10, padding: "0px 6px",
        }}>
          {cfg.label}
        </span>
        {stepId && wfEvent.startsWith("step_") && (
          <span style={{ fontSize: 11, fontFamily: "monospace", color: t.textMuted }}>
            {stepId}
          </span>
        )}
        {progress && (
          <span style={{ fontSize: 11, color: t.textMuted }}>
            ({progress})
          </span>
        )}
        <span style={{ fontSize: 11, color: t.textDim, opacity: 0.7, flex: 1 }}>
          {timestamp}
        </span>
        {runDetailHref && (
          <span
            onClick={(e) => {
              e.stopPropagation();
              window.location.href = runDetailHref;
            }}
            title="View workflow run"
            style={{
              display: "inline-flex", alignItems: "center", cursor: "pointer",
              color: t.textDim, opacity: 0.5,
              transition: "opacity 0.15s",
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.opacity = "1"; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.opacity = "0.5"; }}
          >
            <ExternalLink size={11} />
          </span>
        )}
      </div>
      {expanded && displayContent.length > 0 && (
        <div style={{ paddingLeft: 30, paddingTop: 4, paddingBottom: 4 }}>
          <div style={{
            fontSize: 14, lineHeight: "1.5", color: t.textMuted,
            whiteSpace: "pre-wrap", wordBreak: "break-word",
          }}>
            <MarkdownContent text={displayContent} t={t} />
          </div>
        </div>
      )}
    </div>
  );
}
