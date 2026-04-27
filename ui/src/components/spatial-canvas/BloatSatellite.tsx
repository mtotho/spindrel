import { useState } from "react";
import { Wind, X } from "lucide-react";
import { useAgentSmell, type AgentSmellBot } from "../../api/hooks/useUsage";
import { ATTENTION_HUB_X, ATTENTION_HUB_Y } from "./spatialGeometry";

const SATELLITE_OFFSET_X = 110;
const SATELLITE_OFFSET_Y = -60;

function fmtTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${Math.round(value / 100) / 10}k`;
  return String(value);
}

function severityClass(severity: string): string {
  if (severity === "critical") return "border-danger/65 bg-danger/15 text-danger";
  if (severity === "smelly") return "border-warning/70 bg-warning/15 text-warning";
  if (severity === "watch") return "border-accent/55 bg-accent/15 text-accent";
  return "border-success/60 bg-success/15 text-success";
}

export function BloatSatellite() {
  const [open, setOpen] = useState(false);
  const { data } = useAgentSmell({ hours: 24, baseline_days: 7, limit: 25 });
  const summary = data?.summary;
  const bloatedBotCount = summary?.bloated_bot_count ?? 0;
  if (!data || bloatedBotCount === 0) return null;

  const offenders = data.bots.filter((b) =>
    b.reasons.some((r) => r.key === "context_bloat"),
  );

  return (
    <>
      <button
        type="button"
        className={`absolute flex flex-col items-center justify-center rounded-full border-2 shadow-md backdrop-blur transition-transform hover:scale-110 ${severityClass(summary?.max_severity ?? "watch")}`}
        style={{
          left: ATTENTION_HUB_X + SATELLITE_OFFSET_X - 32,
          top: ATTENTION_HUB_Y + SATELLITE_OFFSET_Y - 32,
          width: 64,
          height: 64,
          zIndex: 5,
        }}
        onPointerDown={(event) => event.stopPropagation()}
        onClick={(event) => {
          event.stopPropagation();
          setOpen(true);
        }}
        title={`Context bloat: ${bloatedBotCount} bot${bloatedBotCount === 1 ? "" : "s"} carrying unused tools/skills`}
      >
        <Wind size={22} />
        <span className="mt-0.5 text-[11px] font-semibold leading-none">{bloatedBotCount}</span>
      </button>
      {open ? <BloatDrawer offenders={offenders} summary={summary} onClose={() => setOpen(false)} /> : null}
    </>
  );
}

function BloatDrawer({
  offenders,
  summary,
  onClose,
}: {
  offenders: AgentSmellBot[];
  summary: { total_unused_tools: number; total_pinned_unused_tools: number; total_unused_skills: number; total_estimated_bloat_tokens: number } | undefined;
  onClose: () => void;
}) {
  return (
    <aside
      className="fixed bottom-4 right-4 top-16 z-[70] flex w-[480px] max-w-[calc(100vw-2rem)] flex-col rounded-md bg-surface-raised/95 text-sm text-text shadow-xl ring-1 ring-surface-border backdrop-blur"
      onPointerDown={(event) => event.stopPropagation()}
    >
      <div className="flex items-center justify-between border-b border-surface-border px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-xs uppercase tracking-[0.08em] text-text-dim">
            <Wind size={14} />
            Context Bloat
          </div>
          <div className="mt-1 text-xs text-text-muted">
            {summary
              ? `${summary.total_unused_tools} unused · ${summary.total_pinned_unused_tools} pinned-unused · ~${fmtTokens(summary.total_estimated_bloat_tokens)} tokens/turn`
              : null}
          </div>
        </div>
        <button
          type="button"
          className="rounded-md p-2 text-text-muted hover:bg-surface-overlay hover:text-text"
          onClick={onClose}
          title="Close"
        >
          <X size={16} />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3 space-y-3">
        {offenders.length === 0 ? (
          <div className="rounded-md border border-dashed border-surface-border px-3 py-4 text-xs text-text-dim">
            No bloated working sets right now.
          </div>
        ) : (
          offenders.map((bot) => <BloatRow key={bot.bot_id} bot={bot} />)
        )}
      </div>
    </aside>
  );
}

function BloatRow({ bot }: { bot: AgentSmellBot }) {
  const name = bot.display_name || bot.name || bot.bot_id;
  return (
    <div className="rounded-md border border-surface-border bg-surface p-3">
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-text">{name}</div>
          <div className="truncate text-[11px] text-text-dim">{bot.model || bot.bot_id}</div>
        </div>
        <span className={`rounded-full border px-2 py-0.5 text-[11px] font-semibold ${severityClass(bot.severity)}`}>
          {bot.score}
        </span>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-text-muted tabular-nums">
        <span>{bot.metrics.enrolled_tools_count} enrolled tools</span>
        <span>{bot.metrics.unused_tools_count} unused</span>
        <span>{bot.metrics.enrolled_skills_count} enrolled skills</span>
        <span>{bot.metrics.unused_skills_count} unused</span>
        {bot.metrics.tool_schema_tokens_estimate ? (
          <span className="col-span-2">
            ~{fmtTokens(bot.metrics.tool_schema_tokens_estimate)} schema tokens/turn · ~
            {fmtTokens(bot.metrics.estimated_bloat_tokens)} bloat
          </span>
        ) : (
          <span className="col-span-2">~{fmtTokens(bot.metrics.estimated_bloat_tokens)} bloat tokens/turn</span>
        )}
      </div>
      {bot.metrics.pinned_unused_tools.length > 0 ? (
        <div className="mt-2">
          <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Pinned but never used</div>
          <div className="flex flex-wrap gap-1">
            {bot.metrics.pinned_unused_tools.map((name) => (
              <span
                key={name}
                className="rounded-full border border-warning/60 bg-warning/10 px-2 py-0.5 text-[10px] text-warning"
                title="Pinned in bot config but no recorded use"
              >
                📌 {name}
              </span>
            ))}
          </div>
        </div>
      ) : null}
      {bot.metrics.pinned_unused_skills.length > 0 ? (
        <div className="mt-2">
          <div className="mb-1 text-[10px] uppercase tracking-[0.08em] text-text-dim">Pinned skills, never used</div>
          <div className="flex flex-wrap gap-1">
            {bot.metrics.pinned_unused_skills.map((name) => (
              <span
                key={name}
                className="rounded-full border border-warning/60 bg-warning/10 px-2 py-0.5 text-[10px] text-warning"
              >
                📌 {name}
              </span>
            ))}
          </div>
        </div>
      ) : null}
    </div>
  );
}
