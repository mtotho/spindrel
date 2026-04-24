import type {
  ContextSummaryPayload,
  Message,
  SlashCommandFindResultsPayload,
} from "../../types/api";
import { useThemeTokens } from "../../theme/tokens";
import { FindResultsRenderer } from "./renderers/FindResultsRenderer";

interface Props {
  message: Message;
  chatMode?: "default" | "terminal";
}

function fmtTokens(n?: number | null) {
  if (n == null) return "—";
  return n.toLocaleString();
}

function fmtPct(n?: number | null) {
  if (n == null) return "—";
  return `${Math.round(n * 100)}%`;
}

function formatPinnedSkipReason(reason: string) {
  switch (reason) {
    case "channel_disabled":
      return "channel disabled";
    case "profile_disabled":
      return "profile disabled";
    case "export_disabled":
      return "export disabled";
    case "no_summary":
      return "no summary";
    case "trimmed":
      return "trimmed";
    default:
      return reason;
  }
}

export function SlashCommandResultCard({ message, chatMode = "default" }: Props) {
  const resultType = (message.metadata?.result_type ?? "context_summary") as string;
  const rawPayload = message.metadata?.payload ?? {};
  const slashCommand = String(message.metadata?.slash_command ?? "");

  if (resultType === "find_results") {
    return <FindResultsRenderer payload={rawPayload as SlashCommandFindResultsPayload} />;
  }

  if (slashCommand === "help") {
    return <HelpCard payload={rawPayload as ContextSummaryPayload} chatMode={chatMode} />;
  }

  // Default: context_summary (used by /context)
  return <ContextSummaryCard message={message} chatMode={chatMode} />;
}

function HelpCard({
  payload,
  chatMode,
}: {
  payload: ContextSummaryPayload;
  chatMode: "default" | "terminal";
}) {
  const isTerminal = chatMode === "terminal";
  const categories = payload.top_categories ?? [];
  const containerClass = isTerminal
    ? "my-2 rounded-none border border-surface-border/60 bg-surface-raised font-mono"
    : "my-2 rounded-md border border-surface-border bg-surface-raised";
  return (
    <div className={containerClass}>
      <div className="flex items-center justify-between gap-3 px-3 py-2 border-b border-surface-border/60">
        <div className="text-[11px] uppercase tracking-wider text-text-dim">
          /help
        </div>
        <div className="text-[11px] text-text-dim">
          {categories.length} command{categories.length === 1 ? "" : "s"}
        </div>
      </div>
      <ul className="divide-y divide-surface-border/40">
        {categories.map((cmd) => (
          <li
            key={cmd.key}
            className="flex flex-col gap-0.5 px-3 py-2 sm:flex-row sm:items-baseline sm:gap-3"
          >
            <span className="text-[13px] font-medium text-text whitespace-nowrap">
              /{cmd.key}
            </span>
            <span className="text-[12px] text-text-muted leading-snug">
              {cmd.description}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ContextSummaryCard({ message, chatMode = "default" }: Props) {
  void chatMode;
  const t = useThemeTokens();
  const payload = (message.metadata?.payload ?? {}) as ContextSummaryPayload;
  const budget = payload.budget ?? null;
  const pinned = payload.pinned_widget_context ?? null;
  const pct = budget?.utilization ?? null;
  const barColor =
    pct != null && pct >= 0.8 ? "#ef4444" : pct != null && pct >= 0.5 ? "#f59e0b" : t.accent;

  return (
    <div
      style={{
        margin: "8px 0",
        padding: 14,
        borderRadius: 12,
        border: `1px solid ${t.surfaceBorder}`,
        background: t.surfaceRaised,
        boxShadow: "0 10px 24px -18px rgba(0,0,0,0.45)",
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ fontSize: 11, textTransform: "uppercase", letterSpacing: "0.08em", color: t.textDim }}>
            /{String(message.metadata?.slash_command ?? "command")}
          </div>
          <div style={{ fontSize: 15, fontWeight: 600, color: t.text }}>{payload.headline || "Context snapshot"}</div>
        </div>
        <div
          style={{
            flexShrink: 0,
            fontSize: 11,
            color: t.textDim,
            padding: "4px 8px",
            borderRadius: 999,
            background: t.surfaceOverlay,
          }}
        >
          {payload.scope_kind}
        </div>
      </div>

      {budget && (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12, color: t.textDim }}>
            <span>{fmtTokens(budget.gross_prompt_tokens ?? budget.consumed_tokens)}/{fmtTokens(budget.total_tokens)} tokens</span>
            <span>{fmtPct(budget.utilization)}</span>
          </div>
          {(budget.current_prompt_tokens != null || budget.cached_prompt_tokens != null || budget.context_profile) && (
            <div style={{ marginTop: 4, fontSize: 11, color: t.textDim }}>
              {[
                budget.current_prompt_tokens != null ? `current ${fmtTokens(budget.current_prompt_tokens)}` : null,
                budget.cached_prompt_tokens != null ? `cached ${fmtTokens(budget.cached_prompt_tokens)}` : null,
                budget.context_profile ? budget.context_profile : null,
              ].filter(Boolean).join(" · ")}
            </div>
          )}
          <div style={{ marginTop: 6, height: 7, borderRadius: 999, background: t.overlayLight, overflow: "hidden" }}>
            <div
              style={{
                width: `${Math.max(2, Math.min(100, Math.round((pct ?? 0) * 100)))}%`,
                height: "100%",
                background: barColor,
              }}
            />
          </div>
        </div>
      )}

      {payload.top_categories?.length > 0 && (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          {payload.top_categories.slice(0, 4).map((cat) => (
            <div key={cat.key} style={{ display: "grid", gap: 2 }}>
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12 }}>
                <span style={{ color: t.text }}>{cat.label}</span>
                <span style={{ color: t.textDim }}>
                  {fmtTokens(cat.tokens_approx)} tok · {fmtPct(cat.percentage)}
                </span>
              </div>
              <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.45 }}>{cat.description}</div>
            </div>
          ))}
        </div>
      )}

      {pinned && (
        <div style={{ marginTop: 12, display: "grid", gap: 8 }}>
          <div style={{ display: "flex", justifyContent: "space-between", gap: 12, fontSize: 12 }}>
            <span style={{ color: t.text }}>Pinned widget context</span>
            <span style={{ color: t.textDim }}>
              {pinned.enabled ? `${pinned.exported_count}/${pinned.total_pins} exported` : "disabled"}
              {pinned.enabled && pinned.total_chars > 0 ? ` · ${fmtTokens(pinned.total_chars)} chars` : ""}
            </span>
          </div>
          {!pinned.enabled && (
            <div style={{ fontSize: 12, color: t.textMuted }}>
              This channel has pinned-widget context disabled.
            </div>
          )}
          {pinned.enabled && pinned.rows.length === 0 && (
            <div style={{ fontSize: 12, color: t.textMuted }}>
              No pinned widgets are currently exporting context.
            </div>
          )}
          {pinned.enabled && pinned.rows.length > 0 && (
            <div style={{ display: "grid", gap: 6 }}>
              {pinned.rows.slice(0, 4).map((row) => (
                <div key={row.pin_id} style={{ display: "grid", gap: 2 }}>
                  <div style={{ fontSize: 12, color: t.text }}>{row.label}</div>
                  <div style={{ fontSize: 12, color: t.textMuted, lineHeight: 1.45 }}>{row.summary}</div>
                  {row.hint && (
                    <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.4 }}>
                      Hint: {row.hint}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
          {pinned.skipped.length > 0 && (
            <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.4 }}>
              Skipped: {pinned.skipped.slice(0, 4).map((item) => `${item.label} (${formatPinnedSkipReason(item.reason)})`).join(" · ")}
            </div>
          )}
        </div>
      )}

      {payload.notes?.length > 0 && (
        <div style={{ marginTop: 12, display: "grid", gap: 4 }}>
          {payload.notes.slice(0, 3).map((note, idx) => (
            <div key={idx} style={{ fontSize: 12, color: t.textMuted }}>
              {note}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
