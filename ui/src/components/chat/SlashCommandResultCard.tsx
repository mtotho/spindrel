import type { ContextSummaryPayload, Message } from "../../types/api";
import { useThemeTokens } from "../../theme/tokens";

interface Props {
  message: Message;
}

function fmtTokens(n?: number | null) {
  if (n == null) return "—";
  return n.toLocaleString();
}

function fmtPct(n?: number | null) {
  if (n == null) return "—";
  return `${Math.round(n * 100)}%`;
}

export function SlashCommandResultCard({ message }: Props) {
  const t = useThemeTokens();
  const payload = (message.metadata?.payload ?? {}) as ContextSummaryPayload;
  const budget = payload.budget ?? null;
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
