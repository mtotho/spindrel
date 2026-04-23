import { useCallback, useEffect, useState } from "react";
import type { ToolResultEnvelope } from "@/src/types/api";
import type { ThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { getAuthToken, useAuthStore } from "@/src/stores/auth";
import { PreviewCard } from "./shared";

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

export function ContextTrackerWidget({
  envelope,
  sessionId,
  channelId,
  t,
}: {
  envelope: ToolResultEnvelope;
  sessionId?: string;
  dashboardPinId?: string;
  channelId?: string;
  t: ThemeTokens;
}) {
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
      fetch(`${serverUrl}/api/v1/widget-actions/stream?${qs}`, {
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
                // Keepalive or malformed frame; ignore and keep the stream alive.
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
  const topCategories = (breakdown?.categories ?? []).slice(0, 5);
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

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12, minHeight: "100%", color: t.text }}>
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 7, minWidth: 0 }}>
          <span style={{ width: 7, height: 7, background: dotColor, display: "inline-block", flex: "0 0 auto" }} />
          <span style={{ color: t.textMuted, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {statusLabel}
          </span>
        </div>
        <span style={{ color: t.textDim, fontSize: 11, fontVariantNumeric: "tabular-nums" }}>
          {budget?.source ?? "none"}
        </span>
      </div>

      <section>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", gap: 8 }}>
          <div style={{ fontSize: 34, lineHeight: 1, fontWeight: 700, letterSpacing: "-0.05em", color: gaugeColor }}>
            {fmtPct(utilization)}
          </div>
          <div style={{ textAlign: "right", fontSize: 11, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
            <div>{fmtNum(budget?.gross_prompt_tokens ?? budget?.consumed_tokens)} / {fmtNum(budget?.total_tokens)}</div>
            <div>{budget?.context_profile ?? "profile unknown"}</div>
          </div>
        </div>
        <div style={{ height: 3, background: t.surfaceBorder, marginTop: 10 }}>
          <div style={{ height: "100%", width: `${Math.round(pct * 100)}%`, background: gaugeColor }} />
        </div>
      </section>

      <section style={{ display: "grid", gridTemplateColumns: "repeat(3, minmax(0, 1fr))", borderTop: `1px solid ${t.surfaceBorder}`, borderBottom: `1px solid ${t.surfaceBorder}` }}>
        {[
          ["Current", fmtNum(budget?.current_prompt_tokens)],
          ["Cached", fmtNum(budget?.cached_prompt_tokens)],
          ["Until", turnsUntilCompact == null ? "-" : String(turnsUntilCompact)],
        ].map(([label, value], index) => (
          <div key={label} style={{ padding: "8px 6px", borderLeft: index === 0 ? "none" : `1px solid ${t.surfaceBorder}` }}>
            <div style={{ fontSize: 14, fontWeight: 650, color: t.text, fontVariantNumeric: "tabular-nums" }}>{value}</div>
            <div style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>{label}</div>
          </div>
        ))}
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        <div style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Breakdown
        </div>
        {topCategories.length ? topCategories.map((cat) => {
          const share = Number.isFinite(cat.percentage) ? cat.percentage : 0;
          return (
            <div key={cat.key} style={{ display: "grid", gridTemplateColumns: "minmax(0, 1fr) 42px", gap: 8, alignItems: "center" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, fontSize: 12 }}>
                  <span style={{ color: t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{cat.label || cat.key}</span>
                  <span style={{ color: t.textDim, fontVariantNumeric: "tabular-nums" }}>{fmtNum(cat.tokens_approx)}</span>
                </div>
                <div style={{ height: 2, background: t.surfaceBorder, marginTop: 3 }}>
                  <div style={{ width: `${Math.max(1, Math.min(100, Math.round(share * 100)))}%`, height: "100%", background: t.textDim }} />
                </div>
              </div>
              <div style={{ textAlign: "right", fontSize: 11, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
                {fmtPct(share)}
              </div>
            </div>
          );
        }) : (
          <div style={{ color: t.textMuted, fontSize: 12 }}>No context categories yet.</div>
        )}
      </section>

      <section style={{ display: "flex", flexDirection: "column", gap: 5, minHeight: 0 }}>
        <div style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", letterSpacing: "0.08em" }}>
          Recent turns
        </div>
        {activity.length ? activity.map((entry) => (
          <div key={`${entry.id}:${entry.ts}`} style={{ display: "grid", gridTemplateColumns: "44px minmax(0, 1fr)", gap: 8, fontSize: 12 }}>
            <span style={{ color: t.textDim, fontVariantNumeric: "tabular-nums" }}>{timeLabel(entry.ts)}</span>
            <span style={{ color: entry.tone === "error" ? t.danger : t.textMuted, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{entry.label}</span>
          </div>
        )) : (
          <div style={{ color: t.textMuted, fontSize: 12 }}>Waiting for channel activity.</div>
        )}
      </section>

      <div style={{ marginTop: "auto", borderTop: `1px solid ${t.surfaceBorder}`, paddingTop: 6, display: "flex", justifyContent: "space-between", gap: 8, fontSize: 11, color: error ? t.danger : t.textDim }}>
        <span>{error ? "Snapshot failed" : turnsInContext == null ? "Last turn view" : `${turnsInContext} turns in context`}</span>
        <span>{lastUpdated ? `Updated ${timeLabel(lastUpdated)}` : "No snapshot"}</span>
      </div>
    </div>
  );
}
