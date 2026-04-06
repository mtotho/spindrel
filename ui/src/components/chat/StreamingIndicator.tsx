import { useEffect, useRef, useState } from "react";
import { View, Text, Platform } from "react-native";
import { Loader2, Wrench, Check, XCircle, ShieldAlert, Sparkles, Pin } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { MarkdownContent } from "./MarkdownContent";
import { formatToolArgs } from "./toolCallUtils";
import { useDecideApproval, type DecideRequest } from "../../api/hooks/useApprovals";
import { Avatar } from "./MessageActions";

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
function ThinkingBlock({ text, borderColor, textColor }: { text: string; borderColor: string; textColor: string }) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [text]);

  return (
    <div
      ref={scrollRef}
      style={{
        marginBottom: 8,
        marginTop: 2,
        paddingLeft: 12,
        paddingTop: 6,
        paddingBottom: 6,
        borderLeft: `3px solid ${borderColor}`,
        maxHeight: 200,
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
  );
}

/** Shown when the agent is processing in the background (queued message). */
export function ProcessingIndicator({ botName }: { botName?: string }) {
  const name = botName || "Bot";
  const bg = avatarColor(name);
  const t = useThemeTokens();

  if (Platform.OS === "web") {
    return (
      <div style={{ display: "flex", flexDirection: "row", gap: 12, padding: "10px 20px 4px", alignSelf: "stretch" }}>
        <div style={{ paddingTop: 2 }}>
          <Avatar name={name} isUser={false} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2, userSelect: "none" }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: bg }}>{name}</span>
          </div>
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "4px 0" }}>
            <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
            <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
            <span className="typing-dot" style={{ width: 6, height: 6, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
            <span style={{ fontSize: 13, color: t.textMuted, marginLeft: 2 }}>Processing...</span>
          </div>
        </div>
      </div>
    );
  }

  return (
    <View style={{ flexDirection: "row", gap: 12, paddingHorizontal: 20, paddingTop: 10, paddingBottom: 4, alignSelf: "stretch" }}>
      <View style={{ paddingTop: 2 }}>
        <Avatar name={name} isUser={false} />
      </View>
      <View style={{ flex: 1, minWidth: 0 }}>
        <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <Text style={{ fontSize: 15, fontWeight: "700", color: bg }}>{name}</Text>
        </View>
        <View style={{ flexDirection: "row", alignItems: "center", gap: 6, paddingVertical: 4 }}>
          <View className="w-2 h-2 rounded-full bg-text-dim animate-pulse" />
          <Text style={{ fontSize: 13, color: t.textMuted }}>Processing...</Text>
        </View>
      </View>
    </View>
  );
}

/** Tool call cards with approval support (web only) */
function ToolCallCards({ toolCalls, t, botId }: { toolCalls: Props["toolCalls"]; t: ReturnType<typeof useThemeTokens>; botId?: string }) {
  const decideApproval = useDecideApproval();
  const [decidingIds, setDecidingIds] = useState<Set<string>>(new Set());

  const handleDecide = (approvalId: string, approved: boolean, pinCapabilityId?: string) => {
    setDecidingIds((prev) => new Set(prev).add(approvalId));
    const data: DecideRequest = { approved, decided_by: "web:admin" };
    if (pinCapabilityId) data.pin_capability = pinCapabilityId;
    decideApproval.mutate(
      { approvalId, data },
      {
        // On error, re-enable the button so user can retry
        onError: () => setDecidingIds((prev) => { const next = new Set(prev); next.delete(approvalId); return next; }),
        // On success (including 409-as-success), keep button disabled until
        // the SSE approval_resolved event updates the tool call status.
      },
    );
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginBottom: 8 }}>
      {toolCalls.map((tc, i) => {
        const formatted = formatToolArgs(tc.args);
        const isAwaiting = tc.status === "awaiting_approval";
        const isDenied = tc.status === "denied";
        const isDeciding = tc.approvalId ? decidingIds.has(tc.approvalId) : false;
        const isCap = !!tc.capability;

        const iconColor = isDenied ? t.danger : isAwaiting ? t.warning : tc.status === "running" ? t.purple : t.success;
        const borderColor = isAwaiting ? t.warningBorder : isDenied ? t.dangerBorder : t.overlayBorder;

        return (
          <div
            key={i}
            style={{
              borderRadius: 6,
              backgroundColor: t.overlayLight,
              border: `1px solid ${borderColor}`,
              overflow: "hidden",
              alignSelf: "flex-start",
              maxWidth: "100%",
            }}
          >
            {/* Header row */}
            <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 10px" }}>
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
              {tc.status === "running" && <Loader2 size={10} color={t.purple} />}
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
            </div>
            {/* Capability details (description + provides) */}
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
            {/* Approval reason + buttons */}
            {isAwaiting && tc.approvalId && (
              <div
                style={{
                  borderTop: `1px solid ${borderColor}`,
                  padding: "8px 10px",
                  display: "flex",
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
                    fontSize: 12,
                    fontWeight: 600,
                    padding: "4px 12px",
                    borderRadius: 4,
                    border: "none",
                    cursor: isDeciding ? "default" : "pointer",
                    backgroundColor: t.success,
                    color: "#fff",
                    opacity: isDeciding ? 0.6 : 1,
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
                      fontSize: 12,
                      fontWeight: 600,
                      padding: "4px 12px",
                      borderRadius: 4,
                      border: "none",
                      cursor: isDeciding ? "default" : "pointer",
                      backgroundColor: t.purple,
                      color: "#fff",
                      opacity: isDeciding ? 0.6 : 1,
                      display: "flex",
                      alignItems: "center",
                      gap: 4,
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
                    fontSize: 12,
                    fontWeight: 600,
                    padding: "4px 12px",
                    borderRadius: 4,
                    border: "none",
                    cursor: isDeciding ? "default" : "pointer",
                    backgroundColor: t.danger,
                    color: "#fff",
                    opacity: isDeciding ? 0.6 : 1,
                  }}
                >
                  Deny
                </button>
              </div>
            )}
            {/* Args body (hidden for capability approvals) */}
            {formatted && !isCap && (
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
                    margin: 0,
                    fontSize: 11,
                    fontFamily: "'Menlo', 'Monaco', 'Consolas', monospace",
                    color: t.textMuted,
                    whiteSpace: "pre-wrap",
                    wordBreak: "break-word",
                    lineHeight: "1.4",
                  }}
                >
                  {formatted}
                </pre>
              </div>
            )}
          </div>
        );
      })}
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
  botName?: string;
  botId?: string;
  thinkingContent?: string;
}

export function StreamingIndicator({ content, toolCalls, botName, botId, thinkingContent }: Props) {
  const name = botName || "Bot";
  const bg = avatarColor(name);
  const t = useThemeTokens();
  const isWeb = Platform.OS === "web";

  // Trim trailing whitespace/newlines to prevent empty spacer divs from markdown parser
  const displayContent = content.trim();
  const displayThinking = thinkingContent?.trim() ?? "";

  // ── Web path ──
  if (isWeb) {
    return (
      <div style={{ display: "flex", flexDirection: "row", gap: 12, padding: "10px 20px 4px", alignSelf: "stretch" }}>
        <div style={{ paddingTop: 2 }}>
          <Avatar name={name} isUser={false} />
        </div>

        <div style={{ flex: 1, minWidth: 0 }}>
          {/* Name header */}
          <div style={{ display: "flex", flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2, userSelect: "none" }}>
            <span style={{ fontSize: 15, fontWeight: 700, color: bg }}>{name}</span>
          </div>

          {/* Thinking content */}
          {displayThinking ? (
            <ThinkingBlock text={displayThinking} borderColor={t.textDim} textColor={t.textMuted} />
          ) : null}

          {/* Tool calls in progress */}
          {toolCalls.length > 0 && <ToolCallCards toolCalls={toolCalls} t={t} botId={botId} />}

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
          ) : toolCalls.length === 0 ? (
            /* Typing indicator dots */
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4, padding: "4px 0" }}>
              <span className="typing-dot" style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
              <span className="typing-dot" style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
              <span className="typing-dot" style={{ width: 8, height: 8, borderRadius: "50%", backgroundColor: t.textDim, display: "inline-block" }} />
            </div>
          ) : null}
        </div>
      </div>
    );
  }

  // ── Native path ──
  return (
    <View style={{ flexDirection: "row", gap: 12, paddingHorizontal: 20, paddingTop: 10, paddingBottom: 4, alignSelf: "stretch" }}>
      <View style={{ paddingTop: 2 }}>
        <Avatar name={name} isUser={false} />
      </View>

      <View style={{ flex: 1, minWidth: 0 }}>
        {/* Name header */}
        <View style={{ flexDirection: "row", alignItems: "baseline", gap: 8, marginBottom: 2 }}>
          <Text style={{ fontSize: 15, fontWeight: "700", color: bg }}>
            {name}
          </Text>
        </View>

        {/* Thinking content */}
        {displayThinking ? (
          <View
            style={{
              marginBottom: 8,
              marginTop: 2,
              paddingLeft: 12,
              paddingVertical: 6,
              borderLeftWidth: 3,
              borderLeftColor: t.textDim,
            }}
          >
            <Text
              style={{
                fontSize: 13,
                lineHeight: 20,
                color: t.textMuted,
                fontStyle: "italic",
              }}
              numberOfLines={12}
            >
              {displayThinking}
            </Text>
          </View>
        ) : null}

        {/* Tool calls — native fallback (no args) */}
        {toolCalls.length > 0 && (
          <View className="mb-2 gap-1.5">
            {toolCalls.map((tc, i) => (
              <View
                key={i}
                style={{
                  flexDirection: "row",
                  alignItems: "center",
                  gap: 8,
                  paddingHorizontal: 10,
                  paddingVertical: 6,
                  borderRadius: 6,
                  backgroundColor: t.overlayLight,
                  borderWidth: 1,
                  borderColor: tc.status === "awaiting_approval" ? t.warningBorder : tc.status === "denied" ? t.dangerBorder : t.overlayBorder,
                  alignSelf: "flex-start",
                }}
              >
                <Wrench size={12} color={tc.status === "denied" ? t.danger : tc.status === "awaiting_approval" ? t.warning : tc.status === "running" ? t.purple : t.success} />
                <Text style={{ fontSize: 12, color: t.textMuted }}>
                  {tc.name}
                </Text>
                {tc.status === "running" && (
                  <Loader2 size={10} color={t.purple} />
                )}
                {tc.status === "done" && (
                  <Text style={{ fontSize: 11, color: t.success }}>done</Text>
                )}
                {tc.status === "awaiting_approval" && (
                  <Text style={{ fontSize: 11, color: t.warning }}>awaiting approval</Text>
                )}
                {tc.status === "denied" && (
                  <Text style={{ fontSize: 11, color: t.danger }}>denied</Text>
                )}
              </View>
            ))}
          </View>
        )}

        {/* Streaming text */}
        {displayContent ? (
          <Text style={{ fontSize: 15, lineHeight: 22, color: t.contentText }}>{displayContent}</Text>
        ) : toolCalls.length === 0 ? (
          <View style={{ flexDirection: "row", alignItems: "center", gap: 4, paddingVertical: 4 }}>
            <View className="w-2 h-2 rounded-full bg-text-dim animate-pulse" />
            <View className="w-2 h-2 rounded-full bg-text-dim animate-pulse delay-150" />
            <View className="w-2 h-2 rounded-full bg-text-dim animate-pulse delay-300" />
          </View>
        ) : null}
      </View>
    </View>
  );
}
