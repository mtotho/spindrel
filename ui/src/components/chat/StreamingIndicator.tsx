import { useEffect, useRef, useState } from "react";
import { ChevronRight, ChevronDown, Brain, BookOpen, RefreshCw, ArrowRightLeft, ImageOff } from "lucide-react";
import { useIsMobile } from "../../hooks/useIsMobile";
import { useThemeTokens } from "../../theme/tokens";
import { MarkdownContent } from "./MarkdownContent";
import { Avatar } from "./MessageActions";
import type { AssistantTurnBody } from "../../types/api";
import type { ToolCall as LiveToolCall } from "../../stores/chat";
import { OrderedTranscript } from "./OrderedTranscript";
import { buildAssistantTurnBodyItems } from "./toolTranscriptModel";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";
const STREAMING_RENDER_THROTTLE_CHARS = 8_000;
const STREAMING_RENDER_THROTTLE_MS = 100;

export function shouldThrottleStreamingRenderSize(charCount: number): boolean {
  return charCount > STREAMING_RENDER_THROTTLE_CHARS;
}

function assistantTurnBodyTextLength(body: AssistantTurnBody): number {
  return body.items.reduce((total, item) => {
    if (item.kind !== "text") return total;
    return total + item.text.length;
  }, 0);
}

function useThrottledStreamingValue<T>(value: T, enabled: boolean): T {
  const [rendered, setRendered] = useState(value);
  const latestRef = useRef(value);
  const lastFlushRef = useRef(0);
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    latestRef.current = value;

    if (!enabled) {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current);
        timerRef.current = null;
      }
      lastFlushRef.current = Date.now();
      setRendered(value);
      return;
    }

    const now = Date.now();
    const elapsed = now - lastFlushRef.current;
    if (elapsed >= STREAMING_RENDER_THROTTLE_MS) {
      lastFlushRef.current = now;
      setRendered(value);
      return;
    }

    if (timerRef.current != null) return;
    timerRef.current = window.setTimeout(() => {
      timerRef.current = null;
      lastFlushRef.current = Date.now();
      setRendered(latestRef.current);
    }, STREAMING_RENDER_THROTTLE_MS - elapsed);
  }, [enabled, value]);

  useEffect(() => {
    return () => {
      if (timerRef.current != null) {
        window.clearTimeout(timerRef.current);
      }
    };
  }, []);

  return rendered;
}

function TerminalThinkingStatus({
  color,
  dimColor,
  compact = false,
}: {
  color: string;
  dimColor: string;
  compact?: boolean;
}) {
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        padding: compact ? "2px 0 0" : "4px 0",
        color,
        fontFamily: TERMINAL_FONT_STACK,
        fontSize: 12,
        lineHeight: 1.35,
        letterSpacing: 0.1,
      }}
    >
      <span style={{ color: dimColor }}>(</span>
      <span>thinking</span>
      <span className="terminal-thinking-dot" style={{ animationDelay: "0s" }}>.</span>
      <span className="terminal-thinking-dot" style={{ animationDelay: "0.2s" }}>.</span>
      <span className="terminal-thinking-dot" style={{ animationDelay: "0.4s" }}>.</span>
      <span style={{ color: dimColor }}>)</span>
    </div>
  );
}

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
function ThinkingBlock({ text, borderColor, textColor, labelColor, chatMode = "default" }: { text: string; borderColor: string; textColor: string; labelColor: string; chatMode?: "default" | "terminal" }) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const [expanded, setExpanded] = useState(false);
  const isTerminalMode = chatMode === "terminal";

  useEffect(() => {
    const el = scrollRef.current;
    if (el && expanded) el.scrollTop = el.scrollHeight;
  }, [expanded, text]);

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
      <button
        type="button"
        onClick={() => setExpanded((prev) => !prev)}
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 6,
          padding: 0,
          paddingBottom: 4,
          border: "none",
          background: "transparent",
          cursor: "pointer",
        }}
      >
        {expanded ? <ChevronDown size={12} color={labelColor} /> : <ChevronRight size={12} color={labelColor} />}
        <div style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 6,
        fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
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
      </button>
      {/* Content */}
      {expanded && (
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
              fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
              fontSize: isTerminalMode ? 12 : 13,
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
      )}
    </div>
  );
}

/** Shown when the agent is processing in the background (queued message). */
export function ProcessingIndicator({ botName, chatMode = "default" }: { botName?: string; chatMode?: "default" | "terminal" }) {
  const name = botName || "Bot";
  const bg = avatarColor(name);
  const t = useThemeTokens();
  const isTerminalMode = chatMode === "terminal";
  const isMobile = useIsMobile();
  const nameColor = isTerminalMode ? t.accent : bg;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: isMobile ? "column" : "row",
        gap: isMobile ? 0 : 12,
        padding: isTerminalMode ? "10px 12px 6px" : isMobile ? "10px 8px 4px" : "10px 20px 4px",
        alignSelf: "stretch",
      }}
    >
      {!isTerminalMode && !isMobile && (
        <div style={{ paddingTop: 2 }}>
          <Avatar name={name} isUser={false} />
        </div>
      )}
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <span style={{ fontSize: isTerminalMode ? 13 : 15, fontWeight: 700, color: nameColor, fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined }}>{isTerminalMode ? `assistant:${name}` : name}</span>
        </div>
        {isTerminalMode ? (
          <TerminalThinkingStatus color={t.textMuted} dimColor={t.textDim} />
        ) : (
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 0" }}>
            <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
            <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
            <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
            <span style={{ fontSize: 13, color: t.textMuted, marginLeft: 2 }}>Processing...</span>
          </div>
        )}
      </div>
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
function SkillPills({ skills, t, chatMode = "default" }: { skills: AutoInjectedSkillDisplay[]; t: ReturnType<typeof useThemeTokens>; chatMode?: "default" | "terminal" }) {
  if (skills.length === 0) return null;
  const isTerminalMode = chatMode === "terminal";
  return (
    <div style={{ marginBottom: 6 }}>
      {/* Section label — mirrors ThinkingBlock pattern */}
      <div style={{
        display: "flex", flexDirection: "row",
        alignItems: "center",
        gap: 5,
        paddingBottom: 4,
      }}>
        <BookOpen size={10} color={isTerminalMode ? t.textDim : t.purpleMuted} style={{ opacity: 0.7 }} />
        <span style={{
          fontSize: 10,
          color: isTerminalMode ? t.textDim : t.purpleMuted,
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
              backgroundColor: isTerminalMode ? "transparent" : t.purpleSubtle,
              border: isTerminalMode ? `1px solid ${t.overlayBorder}` : `1px solid ${t.purpleBorder}`,
              animationDelay: `${i * 60}ms`,
            }}
          >
            {/* Similarity dot — opacity maps to relevance score */}
            <div style={{
              width: 5,
              height: 5,
              borderRadius: "50%",
              backgroundColor: isTerminalMode ? t.textDim : t.purple,
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
  toolCalls: LiveToolCall[];
  assistantTurnBody: AssistantTurnBody;
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
  waitingForUserInput?: boolean;
  channelId?: string | null;
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

export function StreamingIndicator({
  content,
  toolCalls,
  assistantTurnBody,
  autoInjectedSkills,
  botName,
  botId,
  thinkingContent,
  llmStatus,
  chatMode = "default",
  waitingForUserInput = false,
  channelId,
}: Props) {
  const name = botName || "Bot";
  const bg = avatarColor(name);
  const t = useThemeTokens();
  const isTerminalMode = chatMode === "terminal";
  const isMobile = useIsMobile();
  const nameColor = isTerminalMode ? t.accent : bg;
  const renderedContent = useThrottledStreamingValue(
    content,
    shouldThrottleStreamingRenderSize(content.length),
  );
  const renderedAssistantTurnBody = useThrottledStreamingValue(
    assistantTurnBody,
    shouldThrottleStreamingRenderSize(assistantTurnBodyTextLength(assistantTurnBody)),
  );

  // Trim trailing whitespace/newlines to prevent empty spacer divs from markdown parser
  const displayContent = renderedContent.trim();
  const displayThinking = thinkingContent?.trim() ?? "";
  const hasAssistantTurnBody = renderedAssistantTurnBody.items.length > 0;
  const orderedTurnBodyItems = hasAssistantTurnBody
    ? buildAssistantTurnBodyItems({ assistantTurnBody: renderedAssistantTurnBody, toolCalls, renderMode: chatMode })
    : [];
  const hasVisibleActivity =
    !!displayThinking ||
    hasAssistantTurnBody ||
    (autoInjectedSkills?.length ?? 0) > 0 ||
    toolCalls.length > 0 ||
    !!llmStatus;
  const showFooterCursor = !waitingForUserInput && !displayContent && hasVisibleActivity;

  if (waitingForUserInput && !displayContent && !hasVisibleActivity) {
    return null;
  }

  return (
    <div style={{ display: "flex", flexDirection: isMobile ? "column" : "row", gap: isMobile ? 0 : 12, padding: isTerminalMode ? "10px 12px 6px" : isMobile ? "10px 8px 4px" : "10px 20px 4px", alignSelf: "stretch" }}>
      {!isTerminalMode && !isMobile && (
        <div style={{ paddingTop: 2 }}>
          <Avatar name={name} isUser={false} />
        </div>
      )}

      <div style={{ flex: 1, minWidth: 0 }}>
        {/* Name header */}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <span style={{
            fontSize: isTerminalMode ? 13 : 15,
            fontWeight: isTerminalMode ? 600 : 700,
            color: nameColor,
            fontFamily: isTerminalMode ? TERMINAL_FONT_STACK : undefined,
            textTransform: isTerminalMode ? "lowercase" : undefined,
          }}>
            {isTerminalMode ? `assistant:${name}` : name}
          </span>
        </div>

        {/* Thinking content */}
        {displayThinking ? (
          <ThinkingBlock text={displayThinking} borderColor={t.textDim} textColor={t.textMuted} labelColor={isTerminalMode ? t.textMuted : t.purpleMuted} chatMode={chatMode} />
        ) : null}

        {/* Auto-injected skills */}
        {autoInjectedSkills && autoInjectedSkills.length > 0 && (
          <SkillPills skills={autoInjectedSkills} t={t} chatMode={chatMode} />
        )}

        {/* Ordered transcript body */}
        {hasAssistantTurnBody ? (
          <OrderedTranscript
            items={orderedTurnBodyItems}
            t={t}
            chatMode={chatMode}
            botId={botId}
          />
        ) : displayContent ? (
          <div style={{ contain: "content" }}>
            <MarkdownContent text={displayContent} t={t} chatMode={chatMode} channelId={channelId} />
          </div>
        ) : !waitingForUserInput && !hasVisibleActivity ? (
          /* Typing indicator dots — with optional LLM status badge */
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 0" }}>
            {llmStatus ? (
              <LlmStatusBadge status={llmStatus} t={t} />
            ) : isTerminalMode ? (
              <TerminalThinkingStatus color={t.textMuted} dimColor={t.textDim} compact />
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
        {llmStatus && (hasAssistantTurnBody || toolCalls.length > 0 || displayContent) && (
          <div style={{ padding: "2px 0" }}>
            <LlmStatusBadge status={llmStatus} t={t} />
          </div>
        )}

        {/* Keep a live cursor visible while the turn is still open, even if
            the only visible activity is tool use / thinking and no text delta
            is currently streaming. */}
        {showFooterCursor && (
          isTerminalMode ? (
            <TerminalThinkingStatus color={t.textMuted} dimColor={t.textDim} compact />
          ) : (
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", padding: "6px 0 0" }}>
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
          )
        )}
      </div>
    </div>
  );
}
