import { ChevronRight, Wind } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { useAgentSmell, type AgentSmellBot } from "../../api/hooks/useUsage";
import {
  EmptyState,
  QuietPill,
  SettingsGroupLabel,
  StatusBadge,
} from "../shared/SettingsControls";

const SATELLITE_OFFSET_X = 110;
const SATELLITE_OFFSET_Y = -60;

function fmtTokens(value: number): string {
  if (value >= 1_000_000) return `${(value / 1_000_000).toFixed(1)}m`;
  if (value >= 1_000) return `${Math.round(value / 100) / 10}k`;
  return String(value);
}

function severityVariant(severity: string): "danger" | "warning" | "info" | "success" {
  if (severity === "critical") return "danger";
  if (severity === "smelly") return "warning";
  if (severity === "watch") return "info";
  return "success";
}

function severityChipClass(severity: string): string {
  // Used only for the floating satellite. The Starboard panel uses
  // `StatusBadge` which already maps these variants.
  if (severity === "critical") return "border-danger/65 bg-danger/15 text-danger";
  if (severity === "smelly") return "border-warning/70 bg-warning/15 text-warning";
  if (severity === "watch") return "border-accent/55 bg-accent/15 text-accent";
  return "border-success/60 bg-success/15 text-success";
}

interface BloatSatelliteProps {
  /** Live world position of the Attention Hub landmark; the satellite
   *  anchors its small orbit relative to the hub so dragging the hub
   *  carries the bloat callout with it. */
  hubX: number;
  hubY: number;
  /** Click handler — typically opens the "Smell" station in the
   *  Starboard. The satellite itself owns no drawer state. */
  onOpen: () => void;
}

export function BloatSatellite({ hubX, hubY, onOpen }: BloatSatelliteProps) {
  const { data } = useAgentSmell({ hours: 24, baseline_days: 7, limit: 25 });
  const summary = data?.summary;
  const bloatedBotCount = summary?.bloated_bot_count ?? 0;
  if (!data || bloatedBotCount === 0) return null;

  return (
    <button
      type="button"
      className={`absolute flex flex-col items-center justify-center rounded-full border-2 shadow-md backdrop-blur transition-transform hover:scale-110 ${severityChipClass(summary?.max_severity ?? "watch")}`}
      style={{
        left: hubX + SATELLITE_OFFSET_X - 32,
        top: hubY + SATELLITE_OFFSET_Y - 32,
        width: 64,
        height: 64,
        zIndex: 5,
      }}
      onPointerDown={(event) => event.stopPropagation()}
      onClick={(event) => {
        event.stopPropagation();
        onOpen();
      }}
      title={`Context bloat: ${bloatedBotCount} bot${bloatedBotCount === 1 ? "" : "s"} carrying unused tools/skills`}
    >
      <Wind size={22} />
      <span className="mt-0.5 text-[11px] font-semibold leading-none">{bloatedBotCount}</span>
    </button>
  );
}

/**
 * Bloat / context-smell content for the Starboard "Smell" station.
 * Owns its own data fetch — the chrome owns the panel shell + station
 * label, so we render only a quiet summary line and the per-bot rows.
 */
export function BloatStationContent() {
  const { data, isLoading } = useAgentSmell({ hours: 24, baseline_days: 7, limit: 25 });
  const summary = data?.summary;
  const offenders =
    data?.bots.filter((b) => b.reasons.some((r) => r.key === "context_bloat")) ?? [];

  return (
    <>
      <div className="mb-3 text-sm text-text-muted">
        {summary
          ? `${summary.total_unused_tools} unused · ${summary.total_pinned_unused_tools} pinned-unused · ~${fmtTokens(summary.total_estimated_bloat_tokens)} tokens/turn`
          : isLoading
            ? "Scanning bot working sets…"
            : "No bloat data yet."}
      </div>
      {offenders.length === 0 ? (
        <EmptyState message="No bloated working sets right now." />
      ) : (
        <div className="space-y-2">
          {offenders.map((bot) => (
            <BloatRow key={bot.bot_id} bot={bot} />
          ))}
        </div>
      )}
    </>
  );
}

function BloatRow({ bot }: { bot: AgentSmellBot }) {
  const navigate = useNavigate();
  const name = bot.display_name || bot.name || bot.bot_id;
  const m = bot.metrics;
  const enrolledTools = m.enrolled_tools_count ?? 0;
  const unusedTools = m.unused_tools_count ?? 0;
  const enrolledSkills = m.enrolled_skills_count ?? 0;
  const unusedSkills = m.unused_skills_count ?? 0;
  const schemaTokens = m.tool_schema_tokens_estimate ?? 0;
  const bloatTokens = m.estimated_bloat_tokens ?? 0;
  const pinnedUnusedTools = m.pinned_unused_tools ?? [];
  const pinnedUnusedSkills = m.pinned_unused_skills ?? [];
  const handleOpen = () => {
    navigate(`/admin/bots/${encodeURIComponent(bot.bot_id)}#tools`);
  };
  return (
    <button
      type="button"
      onClick={handleOpen}
      className="group block w-full rounded-md bg-surface-raised/40 px-3 py-2.5 text-left transition-colors hover:bg-surface-overlay/45 focus:outline-none focus:ring-2 focus:ring-accent/40"
      title="Open bot Tools & Skills"
    >
      <div className="flex items-center justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-medium text-text">{name}</span>
            <ChevronRight
              size={14}
              className="shrink-0 text-text-dim opacity-0 transition-opacity group-hover:opacity-100"
            />
          </div>
          <div className="truncate text-xs text-text-dim">{bot.model || bot.bot_id}</div>
        </div>
        <StatusBadge label={String(bot.score)} variant={severityVariant(bot.severity)} />
      </div>
      <div className="mt-2 grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-text-muted tabular-nums">
        <span>{enrolledTools} enrolled tools</span>
        <span>{unusedTools} unused</span>
        <span>{enrolledSkills} enrolled skills</span>
        <span>{unusedSkills} unused</span>
        {schemaTokens ? (
          <span className="col-span-2 text-text-dim">
            ~{fmtTokens(schemaTokens)} schema tokens/turn · <span className="text-warning-muted">~{fmtTokens(bloatTokens)} bloat</span>
          </span>
        ) : (
          <span className="col-span-2 text-warning-muted">~{fmtTokens(bloatTokens)} bloat tokens/turn</span>
        )}
      </div>
      {pinnedUnusedTools.length > 0 ? (
        <div className="mt-2.5">
          <SettingsGroupLabel label="Pinned but never used" />
          <div className="mt-1 flex flex-wrap gap-1">
            {pinnedUnusedTools.map((name) => (
              <QuietPill
                key={name}
                label={name}
                tone="warning"
                title="Pinned in bot config but no recorded use"
              />
            ))}
          </div>
        </div>
      ) : null}
      {pinnedUnusedSkills.length > 0 ? (
        <div className="mt-2.5">
          <SettingsGroupLabel label="Pinned skills, never used" />
          <div className="mt-1 flex flex-wrap gap-1">
            {pinnedUnusedSkills.map((name) => (
              <QuietPill key={name} label={name} tone="warning" />
            ))}
          </div>
        </div>
      ) : null}
    </button>
  );
}
