import type {
  ContextSummaryPayload,
  Message,
  SlashCommandFindResultsPayload,
} from "../../types/api";
import { useThemeTokens } from "../../theme/tokens";
import { useSetSessionHarnessSettings } from "../../api/hooks/useApprovals";
import { FindResultsRenderer } from "./renderers/FindResultsRenderer";
import { SlashResultPanel } from "./renderers/SlashResultPanel";

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
    return (
      <FindResultsRenderer
        payload={rawPayload as SlashCommandFindResultsPayload}
        chatMode={chatMode}
      />
    );
  }

  if (slashCommand === "help") {
    return <HelpCard payload={rawPayload as ContextSummaryPayload} chatMode={chatMode} />;
  }

  if (resultType === "harness_context_summary") {
    return <HarnessContextSummaryCard payload={rawPayload as Record<string, any>} chatMode={chatMode} />;
  }

  if (resultType === "harness_compact_summary") {
    return <HarnessCompactSummaryCard payload={rawPayload as Record<string, any>} chatMode={chatMode} />;
  }

  if (resultType === "harness_model_effort_picker") {
    return <HarnessModelEffortPickerCard payload={rawPayload as Record<string, any>} chatMode={chatMode} />;
  }

  // Default: context_summary (used by /context)
  return <ContextSummaryCard message={message} chatMode={chatMode} />;
}

function HarnessCompactSummaryCard({
  payload,
  chatMode,
}: {
  payload: Record<string, any>;
  chatMode: "default" | "terminal";
}) {
  return (
    <SlashResultPanel
      chatMode={chatMode}
      commandLabel="/compact"
      meta="harness"
    >
      <div className="grid gap-2 p-3 text-[12px] text-text-muted">
        <div className="font-medium text-text">{String(payload.title || "Harness session compacted")}</div>
        <div>{String(payload.detail || "")}</div>
        <div className="rounded bg-surface-overlay/50 p-2 font-mono text-[11px] leading-5 text-text-muted whitespace-pre-wrap">
          {String(payload.summary_preview || "")}
        </div>
        <div className="text-[10px] text-text-dim">
          Queued hint: {String(payload.queued_hint_kind || "compact_summary")} · {Number(payload.summary_chars || 0).toLocaleString()} chars
        </div>
      </div>
    </SlashResultPanel>
  );
}

function HarnessModelEffortPickerCard({
  payload,
  chatMode,
}: {
  payload: Record<string, any>;
  chatMode: "default" | "terminal";
}) {
  const setSettings = useSetSessionHarnessSettings();
  const sessionId = String(payload.session_id || "");
  const selectedModel = payload.selected_model as string | null | undefined;
  const selectedEffort = payload.selected_effort as string | null | undefined;
  const modelOptions = Array.isArray(payload.model_options) ? payload.model_options : [];
  const selectedOption =
    modelOptions.find((opt: any) => opt.id === selectedModel) ?? modelOptions[0] ?? null;
  const effortValues = Array.isArray(selectedOption?.effort_values)
    ? selectedOption.effort_values
    : [];
  const choose = (patch: { model?: string | null; effort?: string | null }) => {
    if (!sessionId) return;
    setSettings.mutate({ sessionId, patch });
  };
  return (
    <SlashResultPanel
      chatMode={chatMode}
      commandLabel="/model"
      meta={String(payload.display_name || payload.runtime || "harness")}
    >
      <div className="grid gap-3 p-3">
        <div className="text-[13px] font-semibold text-text">Harness model and effort</div>
        <div className="flex flex-wrap gap-1.5">
          <button
            type="button"
            onClick={() => choose({ model: null })}
            className={`rounded px-2 py-1 text-[11px] ${!selectedModel ? "bg-accent/15 text-accent" : "bg-surface-overlay text-text-muted"}`}
          >
            runtime default
          </button>
          {modelOptions.map((opt: any) => (
            <button
              type="button"
              key={opt.id}
              onClick={() => choose({ model: opt.id, effort: opt.default_effort ?? selectedEffort ?? null })}
              className={`rounded px-2 py-1 text-[11px] ${selectedModel === opt.id ? "bg-accent/15 text-accent" : "bg-surface-overlay text-text-muted"}`}
            >
              {opt.label || opt.id}
            </button>
          ))}
        </div>
        {effortValues.length > 0 && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[10px] uppercase tracking-wide text-text-dim">Effort</span>
            <button
              type="button"
              onClick={() => choose({ effort: null })}
              className={`rounded px-2 py-1 text-[11px] ${!selectedEffort ? "bg-accent/15 text-accent" : "bg-surface-overlay text-text-muted"}`}
            >
              default
            </button>
            {effortValues.map((level: string) => (
              <button
                type="button"
                key={level}
                onClick={() => choose({ effort: level })}
                className={`rounded px-2 py-1 text-[11px] ${selectedEffort === level ? "bg-accent/15 text-accent" : "bg-surface-overlay text-text-muted"}`}
              >
                {level}
              </button>
            ))}
          </div>
        )}
      </div>
    </SlashResultPanel>
  );
}

function HarnessContextSummaryCard({
  payload,
  chatMode,
}: {
  payload: Record<string, any>;
  chatMode: "default" | "terminal";
}) {
  const tools = Array.isArray(payload.bridge_tools) ? payload.bridge_tools : [];
  const hints = Array.isArray(payload.hints) ? payload.hints : [];
  const bridgeStatus = payload.bridge_status_detail && typeof payload.bridge_status_detail === "object"
    ? payload.bridge_status_detail as Record<string, any>
    : {};
  const ignoredClientTools = Array.isArray(bridgeStatus.ignored_client_tools) ? bridgeStatus.ignored_client_tools : [];
  const explicitTools = Array.isArray(bridgeStatus.explicit_tool_names) ? bridgeStatus.explicit_tool_names : [];
  const taggedSkills = Array.isArray(bridgeStatus.tagged_skill_ids) ? bridgeStatus.tagged_skill_ids : [];
  const usage = payload.usage && typeof payload.usage === "object"
    ? Object.entries(payload.usage).slice(0, 4).map(([k, v]) => `${k}: ${String(v)}`).join(" · ")
    : null;
  return (
    <SlashResultPanel
      chatMode={chatMode}
      commandLabel="/context"
      meta={String(payload.runtime || "harness")}
    >
      <div className="grid gap-2 p-3 text-[12px] text-text-muted">
        <div className="grid gap-1 sm:grid-cols-2">
          <div><span className="text-text-dim">Model</span> {payload.model || "runtime default"}</div>
          <div><span className="text-text-dim">Effort</span> {payload.effort || "default"}</div>
          <div><span className="text-text-dim">Approval</span> {payload.permission_mode || "default"}</div>
          <div><span className="text-text-dim">Resume</span> {payload.harness_session_id || "new"}</div>
          <div><span className="text-text-dim">Hints</span> {payload.pending_hint_count ?? 0}</div>
          <div><span className="text-text-dim">Bridge</span> {String(payload.bridge_status || "unknown")}</div>
          <div><span className="text-text-dim">Token budget</span> {payload.native_token_budget_available ? "available" : "native unavailable"}</div>
        </div>
        {bridgeStatus.error && <div className="text-warning-muted">{String(bridgeStatus.error)}</div>}
        <div>
          <span className="text-text-dim">Spindrel bridge tools</span>{" "}
          {tools.length ? tools.map((t: any) => t.name).join(", ") : "none selected"}
        </div>
        {ignoredClientTools.length > 0 && (
          <div><span className="text-text-dim">Client tools not bridgeable</span> {ignoredClientTools.join(", ")}</div>
        )}
        {explicitTools.length > 0 && (
          <div><span className="text-text-dim">One-turn tools</span> {explicitTools.join(", ")}</div>
        )}
        {taggedSkills.length > 0 && (
          <div><span className="text-text-dim">Tagged skills</span> {taggedSkills.join(", ")}</div>
        )}
        {hints.length > 0 && (
          <div className="grid gap-1">
            <div className="text-text-dim">Pending hints</div>
            {hints.map((hint: any, idx: number) => (
              <div key={idx} className="rounded bg-surface-overlay/50 px-2 py-1">
                <div className="font-mono text-[10px] text-text">{String(hint.kind || "hint")} {hint.source ? `from ${String(hint.source)}` : ""}</div>
                <div className="text-[11px] leading-snug">{String(hint.preview || "")}</div>
              </div>
            ))}
          </div>
        )}
        {payload.last_compacted_at && <div><span className="text-text-dim">Last compact reset</span> {payload.last_compacted_at}</div>}
        {usage && <div><span className="text-text-dim">Last usage</span> {usage}</div>}
      </div>
    </SlashResultPanel>
  );
}

function HelpCard({
  payload,
  chatMode,
}: {
  payload: ContextSummaryPayload;
  chatMode: "default" | "terminal";
}) {
  const categories = payload.top_categories ?? [];
  return (
    <SlashResultPanel
      chatMode={chatMode}
      commandLabel="/help"
      meta={`${categories.length} command${categories.length === 1 ? "" : "s"}`}
    >
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
    </SlashResultPanel>
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
