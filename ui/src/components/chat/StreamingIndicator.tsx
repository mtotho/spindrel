import { useEffect, useRef, useState } from "react";
import { Loader2, Wrench, Check, XCircle, ShieldAlert, Sparkles, Pin, ChevronRight, ChevronDown, Brain, BookOpen, RefreshCw, ArrowRightLeft, ImageOff } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { MarkdownContent } from "./MarkdownContent";
import { formatToolArgs } from "./toolCallUtils";
import { useDecideApproval, type DecideRequest } from "../../api/hooks/useApprovals";
import { Avatar } from "./MessageActions";
import { TerminalStreamingToolTranscript } from "./TerminalToolTranscript";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

// Deterministic color from string hash (same as MessageBubble)
function avatarColor(name: string): string {
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

/** Auto-scrolling thinking block — keeps latest content visible as it streams */
function ThinkingBlock({ text, borderColor, textColor, labelColor }: { text: string; borderColor: string; textColor: string; labelColor: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [text]);

  return (
    <div
      style={{
        marginBottom: 8,
        marginTop: 2,
        borderRadius: 6,
        overflow: "hidden",
      }}
    >
      {/* Label */}
      <div style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 6,
        paddingBottom: 4,
      }}>
        <Brain size={12} color={labelColor} style={{ opacity: 0.7 }} />
        <span style={{ fontSize: 11, color: labelColor, fontWeight: 500, letterSpacing: 0.3, textTransform: "uppercase" }}>
          Thinking
        </span>
        <span className="thinking-pulse" style={{
          width: 4,
          height: 4,
          borderRadius: "50%",
          backgroundColor: labelColor,
          display: "inline-block",
        }} />
      </div>
      {/* Content */}
      <div
        ref={scrollRef}
        style={{
          paddingLeft: 12,
          paddingTop: 6,
          paddingBottom: 6,
          borderLeft: `2px solid ${borderColor}`,
          maxHeight: 160,
          overflowY: "auto",
        }}
      >
        <div
          style={{
            fontSize: 13,
            lineHeight: "1.55",
            color: textColor,
            fontStyle: "italic",
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
          }}
        >
          {text}
        </div>
      </div>
    </div>
  );
}

/** Shown when the agent is processing in the background (queued message). */
export function ProcessingIndicator({ botName, chatMode = "default" }: { botName?: string; chatMode?: "default" | "terminal" }) {
  const name = botName || "Bot";
  const bg = avatarColor(name);
  const t = useThemeTokens();
  const isTerminalMode = chatMode === "terminal";

  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 12, padding: isTerminalMode ? "10px 12px 6px" : "10px 20px 4px", alignSelf: "stretch" }}>
      {!isTerminalMode && (
        <div style={{ paddingTop: 2 }}>
          <Avatar name={name} isUser={false} />
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: bg, fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined }}>{name}</span>
        </div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 0" }}>
          <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
          <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
          <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
          <span style={{ fontSize: 13, color: t.textMuted, marginLeft: 2, fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined }}>Processing...</span>
        </div>
      </div>
    </div>
  );
}

type ToolCallItem = Props["toolCalls"][number];

/** Group consecutive tool calls with the same name */
function groupToolCalls(toolCalls: ToolCallItem[]): { name: string; calls: ToolCallItem[]; isCap: boolean }[] {
  const groups: { name: string; calls: ToolCallItem[]; isCap: boolean }[] = [];
  for (const tc of toolCalls) {
    const isCap = !!tc.capability;
    const displayName = isCap ? tc.capability!.name : tc.name;
    const last = groups[groups.length - 1];
    if (last && last.name === displayName) {
      last.calls.push(tc);
    } else {
      groups.push({ name: displayName, calls: [tc], isCap });
    }
  }
  return groups;
}

/** Mini status dots for a group of tool calls */
function StatusDots({ calls, t }: { calls: ToolCallItem[]; t: ReturnType<typeof useThemeTokens> }) {
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
      {calls.map((tc, i) => {
        const color = tc.status === "denied" ? t.danger
          : tc.status === "awaiting_approval" ? t.warning
          : tc.status === "running" ? t.purple
          : t.success;
        const isRunning = tc.status === "running";
        return (
          <div
            key={i}
            className={isRunning ? "thinking-pulse" : undefined}
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              backgroundColor: color,
              transition: "background-color 0.3s ease",
            }}
          />
        );
      })}
    </div>
  );
}

/** Single tool call card (used for ungrouped or expanded view) */
function SingleToolCallCard({
  tc, t, isExpanded, onToggle, handleDecide, isDeciding,
}: {
  tc: ToolCallItem;
  t: ReturnType<typeof useThemeTokens>;
  isExpanded: boolean;
  onToggle: () => void;
  handleDecide: (approvalId: string, approved: boolean, pinCapabilityId?: string) => void;
  isDeciding: boolean;
}) {
  const formatted = formatToolArgs(tc.args);
  const isAwaiting = tc.status === "awaiting_approval";
  const isDenied = tc.status === "denied";
  const isCap = !!tc.capability;
  const iconColor = isDenied ? t.danger : isAwaiting ? t.warning : tc.status === "running" ? t.purple : t.success;
  const borderColor = isAwaiting ? t.warningBorder : isDenied ? t.dangerBorder : t.overlayBorder;
  const hasExpandableContent = !!formatted && !isCap;

  return (
    <div
      style={{
        borderRadius: 6,
        backgroundColor: t.overlayLight,
        border: `1px solid ${borderColor}`,
        overflow: "hidden",
        alignSelf: "flex-start",
        maxWidth: "100%",
        transition: "border-color 0.2s ease",
      }}
    >
      {/* Header row */}
      <div
        onClick={hasExpandableContent ? onToggle : undefined}
        style={{
          display: "flex", flexDirection: "row",
          alignItems: "center",
          gap: 8,
          padding: "6px 10px",
          cursor: hasExpandableContent ? "pointer" : "default",
          userSelect: "none",
        }}
      >
        {isCap && isAwaiting ? (
          <Sparkles size={12} color={iconColor} />
        ) : isAwaiting ? (
          <ShieldAlert size={12} color={iconColor} />
        ) : (
          <Wrench size={12} color={iconColor} />
        )}
        <span style={{ fontSize: 12, color: isCap ? t.text : t.textMuted, fontWeight: isCap ? 600 : 400, fontFamily: isCap ? "inherit" : "'Menlo', monospace" }}>
          {isCap ? tc.capability!.name : tc.name}
        </span>
        {tc.status === "running" && <Loader2 size={10} color={t.purple} className="animate-spin" />}
        {tc.status === "done" && <Check size={10} color={t.success} />}
        {isDenied && <XCircle size={10} color={t.danger} />}
        {isAwaiting && !isCap && (
          <span style={{ fontSize: 11, color: t.warning, fontWeight: 500 }}>
            Waiting for approval…
          </span>
        )}
        {isDenied && (
          <span style={{ fontSize: 11, color: t.danger, fontWeight: 500 }}>Denied</span>
        )}
        {hasExpandableContent && (
          isExpanded
            ? <ChevronDown size={10} color={t.textDim} />
            : <ChevronRight size={10} color={t.textDim} />
        )}
      </div>
      {/* Capability details */}
      {isCap && (
        <div style={{ padding: "0 10px 6px", display: "flex", flexDirection: "column", gap: 3 }}>
          {tc.capability!.description && (
            <span style={{ fontSize: 11, color: t.textMuted, lineHeight: "1.3" }}>
              {tc.capability!.description}
            </span>
          )}
          <span style={{ fontSize: 10, color: t.textDim }}>
            Provides: {tc.capability!.tools_count} tool{tc.capability!.tools_count !== 1 ? "s" : ""}, {tc.capability!.skills_count} skill{tc.capability!.skills_count !== 1 ? "s" : ""}
          </span>
        </div>
      )}
      {/* Approval buttons */}
      {isAwaiting && tc.approvalId && (
        <div
          style={{
            borderTop: `1px solid ${borderColor}`,
            padding: "8px 10px",
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 8,
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: 11, color: t.textMuted, flex: 1, minWidth: 100 }}>
            {tc.approvalReason || "Tool policy requires approval before execution"}
          </span>
          <button
            disabled={isDeciding}
            onClick={() => handleDecide(tc.approvalId!, true)}
            style={{
              fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 4,
              border: "none", cursor: isDeciding ? "default" : "pointer",
              backgroundColor: t.success, color: "#fff", opacity: isDeciding ? 0.6 : 1,
            }}
          >
            {isCap ? "Allow" : "Approve"}
          </button>
          {isCap && tc.capability && (
            <button
              disabled={isDeciding}
              onClick={() => handleDecide(tc.approvalId!, true, tc.capability!.id)}
              title="Allow and permanently add to this bot's capabilities"
              style={{
                fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 4,
                border: "none", cursor: isDeciding ? "default" : "pointer",
                backgroundColor: t.purple, color: "#fff", opacity: isDeciding ? 0.6 : 1,
                display: "flex", flexDirection: "row", alignItems: "center", gap: 4,
              }}
            >
              <Pin size={11} />
              Allow & Pin
            </button>
          )}
          <button
            disabled={isDeciding}
            onClick={() => handleDecide(tc.approvalId!, false)}
            style={{
              fontSize: 12, fontWeight: 600, padding: "4px 12px", borderRadius: 4,
              border: "none", cursor: isDeciding ? "default" : "pointer",
              backgroundColor: t.danger, color: "#fff", opacity: isDeciding ? 0.6 : 1,
            }}
          >
            Deny
          </button>
        </div>
      )}
      {/* Collapsible args body */}
      {isExpanded && formatted && !isCap && (
        <div
          style={{
            borderTop: `1px solid ${t.overlayBorder}`,
            padding: "6px 10px",
            maxHeight: 200,
            overflowY: "auto",
          }}
        >
          <pre
            style={{
              margin: 0, fontSize: 11,
              fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
              color: t.textMuted, whiteSpace: "pre-wrap",
              wordBreak: "break-word", lineHeight: "1.4",
            }}
          >
            {formatted}
          </pre>
        </div>
      )}
    </div>
  );
}

/** Tool call cards with grouping, collapsing, and approval support (web only) */
function ToolCallCards({ toolCalls, t, botId }: { toolCalls: Props["toolCalls"]; t: ReturnType<typeof useThemeTokens>; botId?: string }) {
  const decideApproval = useDecideApproval();
  const [decidingIds, setDecidingIds] = useState<Set<string>>(new Set());
  const [expandedArgs, setExpandedArgs] = useState<Set<number>>(new Set());
  const [expandedGroups, setExpandedGroups] = useState<Set<number>>(new Set());

  const handleDecide = (approvalId: string, approved: boolean, pinCapabilityId?: string) => {
    setDecidingIds((prev) => new Set(prev).add(approvalId));
    const data: DecideRequest = { approved, decided_by: "web:admin" };
    if (pinCapabilityId) data.pin_capability = pinCapabilityId;
    decideApproval.mutate(
      { approvalId, data },
      {
        onError: () => setDecidingIds((prev) => { const next = new Set(prev); next.delete(approvalId); return next; }),
      },
    );
  };

  const toggleArgs = (idx: number) => {
    setExpandedArgs((prev) => { const next = new Set(prev); next.has(idx) ? next.delete(idx) : next.add(idx); return next; });
  };
  const toggleGroup = (idx: number) => {
    setExpandedGroups((prev) => { const next = new Set(prev); next.has(idx) ? next.delete(idx) : next.add(idx); return next; });
  };

  const groups = groupToolCalls(toolCalls);
  let globalIdx = 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4, marginBottom: 8 }}>
      {groups.map((group, gi) => {
        const startIdx = globalIdx;
        globalIdx += group.calls.length;

        // Grouped tool calls (2+) — compact summary row
        if (group.calls.length > 1) {
          const doneCount = group.calls.filter(c => c.status === "done").length;
          const runningCount = group.calls.filter(c => c.status === "running").length;
          const total = group.calls.length;
          const allDone = doneCount === total;
          const hasAwaiting = group.calls.some(c => c.status === "awaiting_approval");
          const isGroupExpanded = expandedGroups.has(gi);

          return (
            <div key={gi}>
              {/* Group summary row */}
              <div
                onClick={() => toggleGroup(gi)}
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  padding: "7px 12px",
                  borderRadius: 6,
                  backgroundColor: t.overlayLight,
                  border: `1px solid ${hasAwaiting ? t.warningBorder : t.overlayBorder}`,
                  cursor: "pointer",
                  userSelect: "none",
                  transition: "background-color 0.15s ease",
                  alignSelf: "flex-start",
                  maxWidth: "100%",
                }}
              >
                <Wrench size={12} color={allDone ? t.success : runningCount > 0 ? t.purple : t.textDim} />
                <span style={{
                  fontSize: 12,
                  color: t.textMuted,
                  fontFamily: "'Menlo', monospace",
                }}>
                  {group.name}
                </span>
                {/* Progress: status dots */}
                <StatusDots calls={group.calls} t={t} />
                {/* Count label */}
                <span style={{
                  fontSize: 11,
                  color: allDone ? t.success : runningCount > 0 ? t.purple : t.textDim,
                  fontWeight: 500,
                  fontVariantNumeric: "tabular-nums",
                }}>
                  {doneCount}/{total}
                </span>
                {isGroupExpanded
                  ? <ChevronDown size={10} color={t.textDim} />
                  : <ChevronRight size={10} color={t.textDim} />}
              </div>
              {/* Expanded: show individual cards */}
              {isGroupExpanded && (
                <div style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: 4,
                  paddingLeft: 16,
                  marginTop: 4,
                  borderLeft: `2px solid ${t.overlayBorder}`,
                }}>
                  {group.calls.map((tc, ci) => {
                    const idx = startIdx + ci;
                    return (
                      <SingleToolCallCard
                        key={idx}
                        tc={tc}
                        t={t}
                        isExpanded={expandedArgs.has(idx)}
                        onToggle={() => toggleArgs(idx)}
                        handleDecide={handleDecide}
                        isDeciding={tc.approvalId ? decidingIds.has(tc.approvalId) : false}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          );
        }

        // Single tool call — render directly
        const tc = group.calls[0];
        const idx = startIdx;
        return (
          <SingleToolCallCard
            key={gi}
            tc={tc}
            t={t}
            isExpanded={expandedArgs.has(idx)}
            onToggle={() => toggleArgs(idx)}
            handleDecide={handleDecide}
            isDeciding={tc.approvalId ? decidingIds.has(tc.approvalId) : false}
          />
        );
      })}
    </div>
  );
}

type AutoInjectedSkillDisplay = {
  skillId: string;
  skillName: string;
  similarity: number;
  source: string;
};

/** Compact pills showing which skills were auto-loaded for this turn */
function SkillPills({ skills, t }: { skills: AutoInjectedSkillDisplay[]; t: ReturnType<typeof useThemeTokens> }) {
  if (skills.length === 0) return null;
  return (
    <div style={{ marginBottom: 6 }}>
      {/* Section label — mirrors ThinkingBlock pattern */}
      <div style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 5,
        paddingBottom: 4,
      }}>
        <BookOpen size={10} color={t.purpleMuted} style={{ opacity: 0.7 }} />
        <span style={{
          fontSize: 10,
          color: t.purpleMuted,
          fontWeight: 500,
          letterSpacing: 0.3,
          textTransform: "uppercase",
        }}>
          Skills loaded
        </span>
      </div>
      {/* Pills */}
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
        {skills.map((s, i) => (
          <div
            key={s.skillId}
            className="skill-pill"
            style={{
              display: "inline-flex", flexDirection: "row",
              alignItems: "center",
              gap: 5,
              padding: "2px 8px 2px 6px",
              borderRadius: 10,
              backgroundColor: t.purpleSubtle,
              border: `1px solid ${t.purpleBorder}`,
              animationDelay: `${i * 60}ms`,
            }}
          >
            {/* Similarity dot — opacity maps to relevance score */}
            <div style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              backgroundColor: t.purple,
              opacity: 0.3 + s.similarity * 0.7,
              flexShrink: 0,
            }} />
            <span style={{ fontSize: 11, color: t.textMuted, fontWeight: 500 }}>
              {s.skillName}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

interface Props {
  content: string;
  toolCalls: {
    name: string;
    args?: string;
    status: "running" | "done" | "awaiting_approval" | "denied";
    approvalId?: string;
    approvalReason?: string;
    capability?: { id: string; name: string; description: string; tools_count: number; skills_count: number };
  }[];
  autoInjectedSkills?: AutoInjectedSkillDisplay[];
  botName?: string;
  botId?: string;
  thinkingContent?: string;
  llmStatus?: {
    status: string;
    model?: string;
    reason?: string;
    attempt?: number;
    maxRetries?: number;
    waitSeconds?: number;
    fallbackModel?: string;
    error?: string;
  } | null;
  chatMode?: "default" | "terminal";
}

/** Badge showing LLM retry/fallback status during streaming */
function LlmStatusBadge({ status, t }: { status: NonNullable<Props["llmStatus"]>; t: ReturnType<typeof useThemeTokens> }) {
  let icon: React.ReactNode;
  let label: string;

  if (status.status === "error") {
    icon = <ImageOff size={11} color={t.danger} />;
    const detail = status.error || status.reason || "LLM call failed";
    label = `LLM error: ${detail.slice(0, 120)}`;
  } else if (status.status === "fallback") {
    icon = <ArrowRightLeft size={11} color={t.warning} />;
    label = status.fallbackModel
      ? `Switching to ${status.fallbackModel}...`
      : "Switching model...";
  } else if (status.status === "cooldown_skip") {
    icon = <ArrowRightLeft size={11} color={t.textMuted} />;
    label = status.fallbackModel
      ? `Using ${status.fallbackModel} (primary cooling down)`
      : "Using fallback (primary cooling down)";
  } else if (status.reason === "vision_not_supported") {
    icon = <ImageOff size={11} color={t.warning} />;
    label = "Describing image\u2026";
  } else {
    // retry
    icon = <RefreshCw size={11} color={t.warning} className="animate-spin" />;
    const parts = ["Retrying"];
    if (status.attempt && status.maxRetries) {
      parts[0] = `Retrying (${status.attempt}/${status.maxRetries})`;
    }
    if (status.reason === "rate_limited") {
      parts.push("rate limited");
    }
    label = parts.join(" — ");
  }

  return (
    <div className="flex flex-row items-center gap-1.5 rounded px-2 py-0.5"
      style={{ backgroundColor: t.overlayLight, border: `1px solid ${t.overlayBorder}` }}>
      {icon}
      <span className="text-[11px] font-medium" style={{ color: t.textMuted }}>{label}</span>
    </div>
  );
}

export function StreamingIndicator({ content, toolCalls, autoInjectedSkills, botName, botId, thinkingContent, llmStatus, chatMode = "default" }: Props) {
  const name = botName || "Bot";
  const bg = avatarColor(name);
  const t = useThemeTokens();
  const isTerminalMode = chatMode === "terminal";

  // Trim trailing whitespace/newlines to prevent empty spacer divs from markdown parser
  const displayContent = content.trim();
  const displayThinking = thinkingContent?.trim() ?? "";
  const hasVisibleActivity =
    !!displayThinking ||
    (autoInjectedSkills?.length ?? 0) > 0 ||
    toolCalls.length > 0 ||
    !!llmStatus;
  const showFooterCursor = !displayContent && hasVisibleActivity;

  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 12, padding: isTerminalMode ? "10px 12px 6px" : "10px 20px 4px", alignSelf: "stretch" }}>
      {!isTerminalMode && (
        <div style={{ paddingTop: 2 }}>
          <Avatar name={name} isUser={false} />
        </div>
      )}

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Name header */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <span style={{ fontSize: 15, fontWeight: 700, color: bg, fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined }}>{name}</span>
        </div>

        {/* Thinking content */}
        {displayThinking ? (
          <ThinkingBlock text={displayThinking} borderColor={t.textDim} textColor={t.textMuted} labelColor={t.purpleMuted} />
        ) : null}

        {/* Auto-injected skills */}
        {autoInjectedSkills && autoInjectedSkills.length > 0 && (
          <SkillPills skills={autoInjectedSkills} t={t} />
        )}

        {/* Tool calls in progress */}
        {toolCalls.length > 0 && (
          isTerminalMode
            ? <TerminalStreamingToolTranscript toolCalls={toolCalls} t={t} />
            : <ToolCallCards toolCalls={toolCalls} t={t} botId={botId} />
        )}

        {/* Streaming text */}
        {displayContent ? (
          <div style={{ contain: "content" }}>
            <MarkdownContent text={displayContent} t={t} />
            <span
              style={{
                display: "inline-block",
                width: 2,
                height: 17,
                backgroundColor: t.purple,
                marginLeft: 2,
                verticalAlign: "text-bottom",
                opacity: 0.8,
                animation: "blink 1s step-end infinite",
              }}
            />
          </div>
        ) : !hasVisibleActivity ? (
          /* Typing indicator dots — with optional LLM status badge */
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 0" }}>
            {llmStatus ? (
              <LlmStatusBadge status={llmStatus} t={t} />
            ) : (
              <>
                <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
                <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
                <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
              </>
            )}
          </div>
        ) : null}

        {/* LLM status badge shown alongside tool calls or streaming content */}
        {llmStatus && (toolCalls.length > 0 || displayContent) && (
          <div style={{ padding: "2px 0" }}>
            <LlmStatusBadge status={llmStatus} t={t} />
          </div>
        )}

        {/* Keep a live cursor visible while the turn is still open, even if
            the only visible activity is tool use / thinking and no text delta
            is currently streaming. */}
        {showFooterCursor && (
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", padding: isTerminalMode ? "4px 0 0" : "6px 0 0" }}>
            <span
              aria-label="Still streaming"
              style={{
                display: "inline-block",
                width: 2,
                height: 17,
                backgroundColor: t.purple,
                opacity: 0.8,
                animation: "blink 1s step-end infinite",
              }}
            />
          </div>
        )}
      </div>
    </div>
  );
}
