import { useCallback, useEffect, useMemo, useState } from "react";
import { getApiBase } from "@/src/api/client";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { getAuthToken, useAuthStore } from "@/src/stores/auth";
import { PreviewCard, type NativeAppRendererProps } from "./shared";
import { deriveContextTrackerLayoutProfile } from "./contextTrackerLayout";

interface ContextBudgetResponse {
  utilization: number | null;
  consumed_tokens: number | null;
  total_tokens: number | null;
  gross_prompt_tokens?: number | null;
  current_prompt_tokens?: number | null;
  cached_prompt_tokens?: number | null;
  completion_tokens?: number | null;
  context_profile?: string | null;
  context_origin?: string | null;
  live_history_turns?: number | null;
  source?: string | null;
}

interface ContextCategory {
  key: string;
  label: string;
  chars: number;
  tokens_approx: number;
  percentage: number;
  category: string;
  description?: string;
}

interface ContextBreakdownResponse {
  session_id?: string | null;
  bot_id?: string | null;
  categories?: ContextCategory[];
  total_chars?: number;
  total_tokens_approx?: number;
  compaction?: {
    enabled?: boolean;
    has_summary?: boolean;
    turns_until_next?: number | null;
    messages_since_watermark?: number;
  };
}

interface SessionDiagnosticsResponse {
  compaction?: {
    user_turns_since_watermark?: number;
    turns_until_next?: number | null;
  };
}

interface ActivityEntry {
  id: string;
  label: string;
  meta: string;
  tone: "live" | "done" | "error";
  ts: number;
}

interface StatItem {
  label: string;
  value: string;
}

function fmtNum(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  if (Math.abs(value) >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}M`;
  if (Math.abs(value) >= 1_000) return `${Math.round(value / 1_000)}K`;
  return String(value);
}

function fmtPct(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "-";
  return `${Math.round(value * 100)}%`;
}

function timeLabel(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
}

function formatSourceLabel(source: string | null | undefined): string | null {
  if (source === "api") return "Actual";
  if (source === "estimate") return "Estimate";
  return null;
}

function formatProfileLabel(profile: string | null | undefined): string | null {
  if (!profile || profile === "chat") return null;
  return `${profile.slice(0, 1).toUpperCase()}${profile.slice(1)} profile`;
}

function formatStatusLabel(status: "idle" | "live" | "tool" | "error", label: string): string {
  if (status === "idle") return "Waiting";
  if (status === "error") return "Turn failed";
  if (status === "tool") return label === "tool" ? "Running tool" : label;
  return label;
}

function sectionTitleStyle(t: ThemeTokens) {
  return {
    fontSize: 10,
    color: t.textDim,
    textTransform: "uppercase" as const,
    letterSpacing: "0.08em",
  };
}

function sectionCardStyle(t: ThemeTokens, compact = false) {
  return {
    border: `1px solid ${t.surfaceBorder}`,
    borderRadius: compact ? 10 : 12,
    padding: compact ? "8px 9px" : "10px 11px",
    background: t.surface,
  };
}

function renderStatGrid(
  items: StatItem[],
  columns: number,
  t: ThemeTokens,
  compact = false,
) {
  return (
    <section
      style={{
        display: "grid",
        gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))`,
        gap: compact ? 6 : 8,
      }}
    >
      {items.map((item) => (
        <div key={item.label} style={sectionCardStyle(t, compact)}>
          <div
            style={{
              fontSize: compact ? 13 : 15,
              fontWeight: 650,
              color: t.text,
              fontVariantNumeric: "tabular-nums",
            }}
          >
            {item.value}
          </div>
          <div style={sectionTitleStyle(t)}>{item.label}</div>
        </div>
      ))}
    </section>
  );
}

function renderBreakdownSection(
  categories: ContextCategory[],
  t: ThemeTokens,
  minimal = false,
) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: minimal ? 6 : 8 }}>
      <div style={sectionTitleStyle(t)}>Breakdown</div>
      {categories.length ? categories.map((cat) => {
        const share = Number.isFinite(cat.percentage) ? cat.percentage : 0;
        return (
          <div key={cat.key} style={minimal ? undefined : sectionCardStyle(t)}>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                gap: 8,
                alignItems: "baseline",
                fontSize: minimal ? 12 : 12.5,
              }}
            >
              <span
                style={{
                  color: t.textMuted,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                  minWidth: 0,
                }}
              >
                {cat.label || cat.key}
              </span>
              <span style={{ color: t.textDim, fontVariantNumeric: "tabular-nums", flex: "0 0 auto" }}>
                {fmtNum(cat.tokens_approx)}
              </span>
            </div>
            <div
              style={{
                display: "grid",
                gridTemplateColumns: minimal ? "minmax(0, 1fr) auto" : "minmax(0, 1fr) 44px",
                gap: 8,
                alignItems: "center",
                marginTop: 4,
              }}
            >
              <div style={{ height: minimal ? 3 : 4, background: t.surfaceBorder }}>
                <div
                  style={{
                    width: `${Math.max(1, Math.min(100, Math.round(share * 100)))}%`,
                    height: "100%",
                    background: t.textDim,
                  }}
                />
              </div>
              <div
                style={{
                  textAlign: "right",
                  fontSize: 11,
                  color: t.textDim,
                  fontVariantNumeric: "tabular-nums",
                }}
              >
                {fmtPct(share)}
              </div>
            </div>
          </div>
        );
      }) : (
        <div style={{ color: t.textMuted, fontSize: 12 }}>No context categories yet.</div>
      )}
    </section>
  );
}

function renderActivitySection(activity: ActivityEntry[], t: ThemeTokens) {
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 7, minHeight: 0 }}>
      <div style={sectionTitleStyle(t)}>Recent turns</div>
      {activity.length ? activity.map((entry) => (
        <div key={`${entry.id}:${entry.ts}`} style={sectionCardStyle(t, true)}>
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: 8,
              alignItems: "baseline",
            }}
          >
            <span style={{ color: t.textDim, fontSize: 11, fontVariantNumeric: "tabular-nums", flex: "0 0 auto" }}>
              {timeLabel(entry.ts)}
            </span>
            <span
              style={{
                color: entry.tone === "error" ? t.danger : t.textMuted,
                fontSize: 12,
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                minWidth: 0,
              }}
            >
              {entry.label}
            </span>
          </div>
        </div>
      )) : (
        <div style={{ color: t.textMuted, fontSize: 12 }}>Waiting for channel activity.</div>
      )}
    </section>
  );
}

export function ContextTrackerWidget({
  envelope,
  sessionId,
  channelId,
  gridDimensions,
  layout,
  t,
}: NativeAppRendererProps) {
  const serverUrl = useAuthStore((s) => s.serverUrl);
  const [budget, setBudget] = useState<ContextBudgetResponse | null>(null);
  const [breakdown, setBreakdown] = useState<ContextBreakdownResponse | null>(null);
  const [diagnostics, setDiagnostics] = useState<SessionDiagnosticsResponse | null>(null);
  const [activity, setActivity] = useState<ActivityEntry[]>([]);
  const [status, setStatus] = useState<"idle" | "live" | "tool" | "error">("idle");
  const [statusLabel, setStatusLabel] = useState("idle");
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  const displayLabel = envelope.display_label || "Context tracker";

  const fetchSnapshot = useCallback(async () => {
    if (!channelId) return;
    const sessionQs = new URLSearchParams();
    if (sessionId) sessionQs.set("session_id", sessionId);
    const breakdownQs = new URLSearchParams();
    breakdownQs.set("mode", "last_turn");
    if (sessionId) breakdownQs.set("session_id", sessionId);
    try {
      const [budgetResp, breakdownResp, diagnosticsResp] = await Promise.all([
        apiFetch<ContextBudgetResponse>(
          `/api/v1/channels/${channelId}/context-budget${sessionQs.toString() ? `?${sessionQs}` : ""}`,
        ),
        apiFetch<ContextBreakdownResponse>(
          `/api/v1/channels/${channelId}/context-breakdown?${breakdownQs}`,
        ),
        sessionId
          ? apiFetch<SessionDiagnosticsResponse>(`/sessions/${sessionId}/context/diagnostics`).catch(() => null)
          : Promise.resolve(null),
      ]);
      setBudget(budgetResp);
      setBreakdown(breakdownResp);
      setDiagnostics(diagnosticsResp);
      setLastUpdated(Date.now());
      setError(null);
      setStatus((current) => (current === "error" ? "idle" : current));
      setStatusLabel((current) => (current === "error" ? "idle" : current));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Context snapshot failed");
      setStatus("error");
      setStatusLabel("error");
    }
  }, [channelId, sessionId]);

  useEffect(() => {
    void fetchSnapshot();
    const handle = window.setInterval(() => void fetchSnapshot(), 15_000);
    return () => window.clearInterval(handle);
  }, [fetchSnapshot]);

  useEffect(() => {
    if (!channelId || !serverUrl) return;
    const streamChannelId = channelId;
    let stopped = false;
    let retryTimer: number | null = null;
    let retryCount = 0;
    let lastSeq: number | null = null;
    let ctrl: AbortController | null = null;

    function pushActivity(entry: Omit<ActivityEntry, "ts">) {
      setActivity((prev) => [{ ...entry, ts: Date.now() }, ...prev].slice(0, 5));
    }

    function eventMatchesSession(payload: Record<string, unknown>) {
      if (!sessionId) return true;
      const eventSessionId = typeof payload.session_id === "string" ? payload.session_id : null;
      return eventSessionId == null || eventSessionId === sessionId;
    }

    function handleWire(wire: { kind?: string; seq?: number; payload?: Record<string, unknown> }) {
      if (typeof wire.seq === "number") lastSeq = wire.seq;
      const kind = wire.kind;
      const payload = wire.payload ?? {};
      if (!kind || !eventMatchesSession(payload)) return;
      if (kind === "context_budget") {
        void fetchSnapshot();
        return;
      }
      if (kind === "turn_started") {
        const bot = typeof payload.bot_id === "string" ? payload.bot_id : "bot";
        const turnId = typeof payload.turn_id === "string" ? payload.turn_id : `turn:${Date.now()}`;
        setStatus("live");
        setStatusLabel(`${bot} thinking`);
        pushActivity({ id: turnId, label: `${bot} started`, meta: "", tone: "live" });
        return;
      }
      if (kind === "turn_stream_tool_start") {
        const tool = typeof payload.tool_name === "string" ? payload.tool_name : "tool";
        setStatus("tool");
        setStatusLabel(tool);
        return;
      }
      if (kind === "turn_ended") {
        const bot = typeof payload.bot_id === "string" ? payload.bot_id : "bot";
        const turnId = typeof payload.turn_id === "string" ? payload.turn_id : `done:${Date.now()}`;
        const failed = Boolean(payload.error);
        setStatus(failed ? "error" : "idle");
        setStatusLabel(failed ? "failed" : "idle");
        pushActivity({ id: `${turnId}:end`, label: `${bot} ${failed ? "failed" : "finished"}`, meta: "", tone: failed ? "error" : "done" });
        void fetchSnapshot();
      }
    }

    function connect() {
      if (stopped) return;
      ctrl = new AbortController();
      const token = getAuthToken();
      const qs = new URLSearchParams();
      qs.set("channel_id", streamChannelId);
      qs.set("kinds", "context_budget,turn_started,turn_ended,turn_stream_tool_start");
      if (lastSeq != null) qs.set("since", String(lastSeq));
      fetch(`${getApiBase()}/api/v1/widget-actions/stream?${qs}`, {
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          Accept: "text/event-stream",
        },
        signal: ctrl.signal,
      })
        .then(async (res) => {
          if (!res.ok || !res.body) throw new Error(`SSE connect failed: ${res.status}`);
          retryCount = 0;
          const reader = res.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!stopped) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) continue;
              try {
                handleWire(JSON.parse(line.slice(6)));
              } catch {
                // Ignore malformed frames and keep the stream alive.
              }
            }
          }
          if (!stopped) retryTimer = window.setTimeout(connect, 1000);
        })
        .catch(() => {
          if (stopped || ctrl?.signal.aborted) return;
          const delay = Math.min(1000 * 2 ** retryCount, 30000);
          retryCount = Math.min(retryCount + 1, 10);
          retryTimer = window.setTimeout(connect, delay);
        });
    }

    connect();
    return () => {
      stopped = true;
      if (retryTimer) window.clearTimeout(retryTimer);
      ctrl?.abort();
    };
  }, [channelId, fetchSnapshot, serverUrl, sessionId]);

  if (!channelId) {
    return <PreviewCard title={displayLabel} description="Pin this to a channel dashboard to track context usage." t={t} />;
  }

  const utilization = budget?.utilization ?? null;
  const pct = utilization == null ? 0 : Math.max(0, Math.min(1, utilization));
  const gaugeColor = status === "error"
    ? t.danger
    : pct >= 0.9
      ? t.danger
      : pct >= 0.75
        ? t.warning
        : t.accent;
  const turnsInContext = diagnostics?.compaction?.user_turns_since_watermark;
  const turnsUntilCompact =
    diagnostics?.compaction?.turns_until_next
    ?? breakdown?.compaction?.turns_until_next
    ?? null;
  const dotColor = status === "live"
    ? t.success
    : status === "tool"
      ? t.warning
      : status === "error"
        ? t.danger
        : t.textDim;

  const profile = useMemo(
    () => deriveContextTrackerLayoutProfile(layout, gridDimensions),
    [layout, gridDimensions],
  );
  const sourceLabel = formatSourceLabel(budget?.source);
  const profileLabel = formatProfileLabel(budget?.context_profile);
  const friendlyStatusLabel = formatStatusLabel(status, statusLabel);
  const topCategories = (breakdown?.categories ?? []).slice(0, profile.categoryLimit);
  const visibleActivity = activity.slice(0, profile.activityLimit);
  const compactSecondStat: StatItem = turnsUntilCompact == null
    ? { label: "Cached", value: fmtNum(budget?.cached_prompt_tokens) }
    : { label: "Until", value: String(turnsUntilCompact) };
  const statItems: StatItem[] = profile.mode === "compact"
    ? [
        { label: "Current", value: fmtNum(budget?.current_prompt_tokens) },
        compactSecondStat,
      ]
    : [
        { label: "Current", value: fmtNum(budget?.current_prompt_tokens) },
        { label: "Cached", value: fmtNum(budget?.cached_prompt_tokens) },
        { label: "Until", value: turnsUntilCompact == null ? "-" : String(turnsUntilCompact) },
        ...(profile.showTurnsInContext
          ? [{ label: "Turns", value: turnsInContext == null ? "-" : String(turnsInContext) }]
          : []),
      ];
  const footerLeft = error
    ? "Snapshot failed"
    : profile.mode === "compact" && budget?.cached_prompt_tokens != null && turnsUntilCompact != null
      ? `Cached ${fmtNum(budget.cached_prompt_tokens)}`
      : turnsInContext == null
        ? "Last turn view"
        : `${turnsInContext} turns in context`;
  const percentFontSize = profile.mode === "wide"
    ? 44
    : profile.mode === "tall"
      ? 40
      : profile.mode === "compact"
        ? 28
        : 34;
  const compact = profile.mode === "compact";

  const hero = (
    <section style={{ display: "flex", flexDirection: "column", gap: compact ? 6 : 10 }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: compact ? "flex-end" : "baseline",
          gap: 10,
        }}
      >
        <div
          style={{
            fontSize: percentFontSize,
            lineHeight: 0.95,
            fontWeight: 700,
            letterSpacing: "-0.05em",
            color: gaugeColor,
            fontVariantNumeric: "tabular-nums",
          }}
        >
          {fmtPct(utilization)}
        </div>
        <div
          style={{
            textAlign: "right",
            fontSize: compact ? 10.5 : 11,
            color: t.textDim,
            fontVariantNumeric: "tabular-nums",
            flex: "0 0 auto",
          }}
        >
          <div>{fmtNum(budget?.gross_prompt_tokens ?? budget?.consumed_tokens)} / {fmtNum(budget?.total_tokens)}</div>
          {profileLabel ? <div>{profileLabel}</div> : null}
        </div>
      </div>
      <div style={{ height: compact ? 4 : 5, background: t.surfaceBorder }}>
        <div style={{ height: "100%", width: `${Math.round(pct * 100)}%`, background: gaugeColor }} />
      </div>
    </section>
  );

  const header = (
    <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
        <span style={{ width: 7, height: 7, background: dotColor, display: "inline-block", flex: "0 0 auto" }} />
        <span
          style={{
            color: t.textMuted,
            fontSize: compact ? 11 : 12,
            overflow: "hidden",
            textOverflow: "ellipsis",
            whiteSpace: "nowrap",
          }}
        >
          {friendlyStatusLabel}
        </span>
      </div>
      {!compact && sourceLabel ? (
        <span
          style={{
            color: t.textDim,
            fontSize: 11,
            fontVariantNumeric: "tabular-nums",
            flex: "0 0 auto",
          }}
        >
          {sourceLabel}
        </span>
      ) : null}
    </div>
  );

  const footer = (
    <div
      style={{
        marginTop: "auto",
        borderTop: `1px solid ${t.surfaceBorder}`,
        paddingTop: compact ? 5 : 6,
        display: "flex",
        justifyContent: "space-between",
        gap: 8,
        fontSize: compact ? 10 : 11,
        color: error ? t.danger : t.textDim,
      }}
    >
      <span>{compact ? (sourceLabel ?? footerLeft) : footerLeft}</span>
      <span>{lastUpdated ? `Updated ${timeLabel(lastUpdated)}` : "No snapshot"}</span>
    </div>
  );

  if (profile.mode === "compact") {
    return (
      <div style={{ display: "flex", flexDirection: "column", gap: 8, minHeight: "100%", color: t.text }}>
        {header}
        {hero}
        {renderStatGrid(statItems, profile.statColumns, t, true)}
        {footer}
      </div>
    );
  }

  const secondaryContent = (
    <>
      {profile.showBreakdown ? renderBreakdownSection(topCategories, t) : null}
      {profile.showActivity ? renderActivitySection(visibleActivity, t) : null}
    </>
  );

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: profile.mode === "wide" ? 14 : 12, minHeight: "100%", color: t.text }}>
      {header}

      {profile.mode === "wide" ? (
        <section
          style={{
            display: "grid",
            gridTemplateColumns: "minmax(0, 1.15fr) minmax(220px, 0.95fr)",
            gap: 14,
            alignItems: "start",
            flex: "1 1 auto",
          }}
        >
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {hero}
            {renderStatGrid(statItems, profile.statColumns, t)}
          </div>
          <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            {secondaryContent}
          </div>
        </section>
      ) : (
        <>
          {hero}
          {renderStatGrid(statItems, profile.statColumns, t)}
          {secondaryContent}
        </>
      )}

      {footer}
    </div>
  );
}
