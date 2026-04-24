import { useState } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useChannelContextBreakdown, type ContextBreakdownMode } from "@/src/api/hooks/useChannels";
import { Section, EmptyState, Toggle } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  SettingsControlRow,
  SettingsSegmentedControl,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { apiFetch } from "@/src/api/client";
import { useQuery } from "@tanstack/react-query";

const CATEGORY_CLASS: Record<string, { bar: string; dot: string; badge: "info" | "success" | "warning" | "purple" | "neutral" }> = {
  static: { bar: "bg-accent", dot: "bg-accent", badge: "info" },
  rag: { bar: "bg-success", dot: "bg-success", badge: "success" },
  conversation: { bar: "bg-warning", dot: "bg-warning", badge: "warning" },
  compaction: { bar: "bg-purple", dot: "bg-purple", badge: "purple" },
};

const ROLE_BADGE: Record<string, "info" | "success" | "purple" | "warning" | "neutral"> = {
  system: "info",
  user: "success",
  assistant: "purple",
  tool: "warning",
};

function ContextBlock({
  block,
  isPlaceholder,
}: {
  block: { label: string; role: string; content: string };
  isPlaceholder: boolean;
}) {
  const [open, setOpen] = useState(false);
  const truncated = block.content.length > 200 && !open;
  const displayContent = truncated ? `${block.content.slice(0, 200)}...` : block.content;

  return (
    <SettingsControlRow onClick={() => setOpen(!open)} className="flex flex-col gap-2">
      <div className="flex w-full items-center justify-between gap-3 text-left">
        <span className="inline-flex items-center gap-2">
          <StatusBadge label={block.role} variant={ROLE_BADGE[block.role] ?? "neutral"} />
          <span className="text-[11px] font-semibold text-text">{block.label}</span>
        </span>
        <span className="text-[10px] text-text-dim">
          {block.content.length.toLocaleString()} chars {open ? "▲" : "▼"}
        </span>
      </div>
      <div
        className={`max-h-[120px] overflow-hidden whitespace-pre-wrap font-mono text-[11px] leading-relaxed ${isPlaceholder ? "italic text-text-dim" : "text-text-muted"} ${open ? "max-h-none" : ""}`}
      >
        {displayContent}
      </div>
    </SettingsControlRow>
  );
}

function ContextPreview({ channelId }: { channelId: string }) {
  const [includeHistory, setIncludeHistory] = useState(false);
  const [expanded, setExpanded] = useState(true);

  const { data, isLoading } = useQuery({
    queryKey: ["context-preview", channelId, includeHistory],
    queryFn: () => apiFetch<{
      blocks: { label: string; role: string; content: string }[];
      conversation: { label: string; role: string; content: string }[];
      total_chars: number;
      total_tokens_approx: number;
      history_mode: string | null;
    }>(`/api/v1/admin/channels/${channelId}/context-preview?include_history=${includeHistory}`),
  });

  return (
    <Section title="Context Preview">
      <div className="flex flex-wrap items-center gap-3">
        <ActionButton
          label={expanded ? "Collapse" : "Expand"}
          onPress={() => setExpanded(!expanded)}
          variant="secondary"
          size="small"
          icon={expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        />
        <Toggle
          value={includeHistory}
          onChange={setIncludeHistory}
          label="Include conversation messages"
        />
        {data && (
          <span className="ml-auto text-[11px] text-text-dim">
            ~{data.total_chars.toLocaleString()} chars / ~{data.total_tokens_approx.toLocaleString()} tokens
          </span>
        )}
      </div>

      {isLoading && <Spinner />}

      {expanded && data && (
        <div className="flex flex-col gap-1.5">
          {data.blocks.map((block, i) => {
            const isPlaceholder = block.content.startsWith("[") && block.content.endsWith("]");
            return <ContextBlock key={`sys-${i}`} block={block} isPlaceholder={isPlaceholder} />;
          })}

          {data.conversation.length > 0 && (
            <>
              <div className="mt-2 text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
                Conversation Messages ({data.conversation.length})
              </div>
              {data.conversation.map((block, i) => (
                <ContextBlock key={`conv-${i}`} block={block} isPlaceholder={false} />
              ))}
            </>
          )}
        </div>
      )}

      <div className="text-[10px] italic text-text-dim">
        This preview shows deterministic injections. RAG-dependent blocks vary by query and are shown as placeholders.
      </div>
    </Section>
  );
}

export function ContextTab({ channelId }: { channelId: string }) {
  const [mode, setMode] = useState<ContextBreakdownMode>("last_turn");
  const { data, isLoading } = useChannelContextBreakdown(channelId, mode);
  const fmtNum = (value?: number | null) => (value == null ? "—" : value.toLocaleString());
  const fmtPct = (value?: number | null) => (value == null ? "—" : `${Math.round(value * 100)}%`);

  if (isLoading) return <Spinner />;
  if (!data) return <EmptyState message="No context data available." />;

  const legend = [
    { key: "static", label: "Static" },
    { key: "rag", label: "RAG" },
    { key: "conversation", label: "Conversation" },
    { key: "compaction", label: "Compaction" },
  ];

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <SettingsSegmentedControl
          value={mode}
          onChange={setMode}
          options={[
            { key: "last_turn", label: "Last turn" },
            { key: "next_turn", label: "Next-turn forecast" },
          ]}
        />
        <div className="max-w-[65ch] text-[11px] leading-relaxed text-text-dim">
          {mode === "last_turn"
            ? "Total tokens reflect what the most recent turn actually consumed and match the chat header."
            : "Total tokens forecast what the next turn would consume with the current configuration."}
        </div>
      </div>

      <Section title="Summary">
        <SettingsStatGrid
          items={[
            { label: "Total Tokens", value: `~${data.total_tokens_approx.toLocaleString()}`, tone: "accent" },
            { label: "Total Chars", value: data.total_chars.toLocaleString() },
            { label: "Bot", value: data.bot_id },
            { label: "Profile", value: data.context_profile ?? "unknown" },
            { label: "Origin", value: data.context_origin ?? "chat" },
            { label: "Live Turns", value: data.live_history_turns == null ? "full" : String(data.live_history_turns) },
            { label: "Conversation", value: data.session_id ? `${data.session_id.slice(0, 8)}...` : "none" },
          ]}
        />
      </Section>

      {data.context_budget && (
        <Section title="Prompt Budget">
          <SettingsStatGrid
            items={[
              { label: "Profile", value: data.context_budget.context_profile ?? data.context_profile ?? "—" },
              { label: "Origin", value: data.context_budget.context_origin ?? data.context_origin ?? "—" },
              { label: "History Turns", value: data.context_budget.live_history_turns == null ? "full" : String(data.context_budget.live_history_turns) },
              { label: "Estimate Gross", value: fmtNum(data.context_budget.estimate?.gross_prompt_tokens) },
              { label: "Estimate Util.", value: fmtPct(data.context_budget.estimate?.utilization) },
              { label: "Last Gross", value: fmtNum(data.context_budget.usage?.gross_prompt_tokens) },
              { label: "Last Current", value: fmtNum(data.context_budget.usage?.current_prompt_tokens) },
              { label: "Last Cached", value: fmtNum(data.context_budget.usage?.cached_prompt_tokens) },
              { label: "Last Completion", value: fmtNum(data.context_budget.usage?.completion_tokens) },
              { label: "Window", value: fmtNum(data.context_budget.estimate?.total_tokens ?? data.context_budget.usage?.total_tokens) },
            ]}
          />
          <div className="text-[11px] italic text-text-dim">
            Gross prompt tokens stay aligned with the header pill. Current and cached splits come from the latest API usage when available.
          </div>
        </Section>
      )}

      <Section title="Proportions">
        <div className="flex h-7 overflow-hidden rounded-md bg-surface-raised/40">
          {data.categories
            .filter((c) => c.percentage > 0)
            .map((c) => (
              <div
                key={c.key}
                title={`${c.label}: ${c.percentage}%`}
                className={CATEGORY_CLASS[c.category]?.bar ?? "bg-text-dim"}
                style={{ width: `${c.percentage}%`, minWidth: c.percentage > 0.5 ? 3 : 0 }}
              />
            ))}
        </div>
        <div className="flex flex-wrap gap-4">
          {legend.map((l) => (
            <div key={l.key} className="flex items-center gap-1.5 text-[11px] text-text-muted">
              <div className={`h-2 w-2 rounded-full ${CATEGORY_CLASS[l.key]?.dot ?? "bg-text-dim"}`} />
              {l.label}
            </div>
          ))}
        </div>
      </Section>

      <Section title="Components">
        <div className="flex flex-col gap-1.5">
          {data.categories.map((c) => (
            <SettingsControlRow key={c.key} className="flex items-center gap-3">
              <div className={`h-2 w-2 shrink-0 rounded-full ${CATEGORY_CLASS[c.category]?.dot ?? "bg-text-dim"}`} />
              <div className="min-w-0 flex-1">
                <div className="text-[13px] font-semibold text-text">{c.label}</div>
                <div className="mt-0.5 text-[11px] text-text-dim">{c.description}</div>
              </div>
              <div className="shrink-0 text-right">
                <div className="text-[13px] font-semibold text-text">~{c.tokens_approx.toLocaleString()} tok</div>
                <div className="text-[11px] text-text-dim">{c.percentage}%</div>
              </div>
            </SettingsControlRow>
          ))}
        </div>
      </Section>

      {data.compaction && (
        <Section title="Compaction">
          <SettingsStatGrid
            items={[
              { label: "Enabled", value: data.compaction.enabled ? "Yes" : "No", tone: data.compaction.enabled ? "success" : "default" },
              { label: "Has Summary", value: data.compaction.has_summary ? `Yes (${data.compaction.summary_chars.toLocaleString()} chars)` : "No" },
              { label: "Total Messages", value: data.compaction.total_messages },
              { label: "Since Watermark", value: data.compaction.messages_since_watermark },
              { label: "Interval", value: data.compaction.compaction_interval },
              { label: "Keep Turns", value: data.compaction.compaction_keep_turns },
              { label: "Turns Until Next", value: data.compaction.turns_until_next ?? "N/A" },
            ]}
          />
        </Section>
      )}

      {data.compression && (
        <Section title="Context Compression">
          <SettingsStatGrid
            items={[
              { label: "Enabled", value: data.compression.enabled ? "Yes" : "No", tone: data.compression.enabled ? "success" : "default" },
              { label: "Model", value: data.compression.model || "—" },
              { label: "Threshold", value: `${data.compression.threshold.toLocaleString()} chars` },
              { label: "Keep Turns", value: data.compression.keep_turns },
              { label: "Conv. Chars", value: data.compression.conversation_chars.toLocaleString() },
              { label: "Would Compress", value: data.compression.would_compress ? "Yes" : "No", tone: data.compression.would_compress ? "success" : "default" },
            ]}
          />
          <div className="text-[11px] italic text-text-dim">
            Compression is ephemeral: it summarizes older conversation each turn without modifying stored messages.
          </div>
        </Section>
      )}

      {data.reranking && (
        <Section title="RAG Re-ranking">
          <SettingsStatGrid
            items={[
              { label: "Enabled", value: data.reranking.enabled ? "Yes" : "No", tone: data.reranking.enabled ? "success" : "default" },
              { label: "Model", value: data.reranking.model || "—" },
              { label: "Threshold", value: `${data.reranking.threshold_chars.toLocaleString()} chars` },
              { label: "Max Chunks", value: data.reranking.max_chunks },
              { label: "RAG Chars", value: data.reranking.total_rag_chars.toLocaleString() },
              { label: "Would Rerank", value: data.reranking.would_rerank ? "Yes" : "No", tone: data.reranking.would_rerank ? "success" : "default" },
            ]}
          />
          <div className="text-[11px] italic text-text-dim">
            Re-ranking uses an LLM to filter RAG chunks across all sources.
          </div>
        </Section>
      )}

      {data.effective_settings && (
        <Section title="Effective Settings">
          <div className="flex flex-col gap-1.5">
            {Object.entries(data.effective_settings).map(([key, setting]) => (
              <SettingsControlRow key={key} className="flex items-center justify-between gap-3">
                <span className="font-mono text-[12px] text-text-muted">{key}</span>
                <div className="flex items-center gap-2">
                  <span className="text-[12px] text-text">{String(setting.value)}</span>
                  <StatusBadge
                    label={setting.source}
                    variant={setting.source === "channel" ? "info" : setting.source === "bot" ? "success" : "neutral"}
                  />
                </div>
              </SettingsControlRow>
            ))}
          </div>
        </Section>
      )}

      <div className="text-[11px] italic text-text-dim">{data.disclaimer}</div>

      <ContextPreview channelId={channelId} />
    </div>
  );
}
