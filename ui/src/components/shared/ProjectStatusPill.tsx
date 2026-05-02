/**
 * Single status pill condensing a Project's current state into one chip.
 *
 * Picks ONE highest-priority signal (per the UI operator skill: one focal
 * point, low chrome). Priority order matches `skills/project/index.md`
 * stage routing so the pill agrees with whatever the agent will say:
 *
 *   1. concurrency saturated   -> "Cap full"     (warning tone)
 *   2. needs_review            -> "N to review"  (warning tone)
 *   3. runs_in_flight          -> "N running"    (accent tone)
 *   4. shaping_packs           -> "N proposed"   (accent tone)
 *   5. unconfigured            -> "Setup needed" (warning tone)
 *   6. ready_no_work           -> "Ready"        (muted tone)
 *   7. else                    -> stage label    (muted tone)
 *
 * Read-only chip; click navigates to the admin Project page.
 */
import * as React from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  CheckCircle2,
  CircleDot,
  Cog,
  PauseCircle,
} from "lucide-react";
import {
  useProjectFactoryState,
  useProjectOrchestrationPolicy,
} from "@/src/api/hooks/useProjects";

type Tone = "warning" | "accent" | "muted";

interface PillSignal {
  label: string;
  tone: Tone;
  icon: React.ReactNode;
  title: string;
}

const STAGE_LABEL: Record<string, string> = {
  unconfigured: "Setup needed",
  ready_no_work: "Ready",
  planning: "Planning",
  shaping_packs: "Shaping",
  runs_in_flight: "Running",
  needs_review: "Needs review",
  reviewed_idle: "Reviewed",
};

function pickSignal(
  state: ReturnType<typeof useProjectFactoryState>["data"],
  policy: ReturnType<typeof useProjectOrchestrationPolicy>["data"],
): PillSignal | null {
  if (!state) return null;
  const stage = state.current_stage;
  const ready = state.runs.ready_for_review;
  const inFlight = state.runs.active_implementation;
  const proposed = state.run_packs.proposed + state.run_packs.needs_info;
  const cap = policy?.concurrency.max_concurrent_runs ?? state.runs.concurrency.cap;
  const saturated = policy?.concurrency.saturated ?? false;

  if (saturated && cap != null) {
    return {
      label: `Cap ${state.runs.active_implementation}/${cap}`,
      tone: "warning",
      icon: <PauseCircle size={10} />,
      title: `Concurrency cap saturated (${state.runs.active_implementation} of ${cap}). Wait for a run to finish or raise the Blueprint cap.`,
    };
  }
  if (stage === "needs_review") {
    return {
      label: `${ready} to review`,
      tone: "warning",
      icon: <AlertTriangle size={10} />,
      title: `${ready} run${ready === 1 ? "" : "s"} ready for review with no active reviewer.`,
    };
  }
  if (stage === "runs_in_flight" && inFlight > 0) {
    return {
      label: `${inFlight} running`,
      tone: "accent",
      icon: <CircleDot size={10} />,
      title: `${inFlight} implementation run${inFlight === 1 ? "" : "s"} in flight.`,
    };
  }
  if (stage === "shaping_packs" && proposed > 0) {
    return {
      label: `${proposed} proposed`,
      tone: "accent",
      icon: <CircleDot size={10} />,
      title: `${proposed} Run Pack${proposed === 1 ? "" : "s"} proposed and waiting for a launch decision.`,
    };
  }
  if (stage === "unconfigured") {
    return {
      label: STAGE_LABEL.unconfigured,
      tone: "warning",
      icon: <Cog size={10} />,
      title: state.suggested_next_action.headline,
    };
  }
  if (stage === "ready_no_work") {
    return {
      label: STAGE_LABEL.ready_no_work,
      tone: "muted",
      icon: <CheckCircle2 size={10} />,
      title: state.suggested_next_action.headline,
    };
  }
  return {
    label: STAGE_LABEL[stage] ?? stage,
    tone: "muted",
    icon: <CircleDot size={10} />,
    title: state.suggested_next_action.headline,
  };
}

const TONE_CLASS: Record<Tone, string> = {
  warning: "bg-warning/10 text-warning hover:bg-warning/15",
  accent: "bg-accent/10 text-accent hover:bg-accent/15",
  muted: "bg-surface-overlay text-text-muted hover:bg-surface-overlay/70 hover:text-text",
};

export interface ProjectStatusPillProps {
  projectId: string;
  /** When set, click navigates here instead of /admin/projects/{id}. */
  href?: string;
  /** When true, the pill is rendered as a non-interactive span. */
  static?: boolean;
}

export function ProjectStatusPill({ projectId, href, static: isStatic }: ProjectStatusPillProps) {
  const navigate = useNavigate();
  const stateQuery = useProjectFactoryState(projectId, { refetchIntervalMs: 30_000 });
  const policyQuery = useProjectOrchestrationPolicy(projectId, { refetchIntervalMs: 30_000 });
  const signal = pickSignal(stateQuery.data, policyQuery.data);
  if (!signal) return null;

  const target = href ?? `/admin/projects/${projectId}`;
  const className = `inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium transition-colors ${TONE_CLASS[signal.tone]}`;

  if (isStatic) {
    return (
      <span className={className} title={signal.title}>
        {signal.icon}
        <span className="truncate max-w-[10rem]">{signal.label}</span>
      </span>
    );
  }
  return (
    <button
      type="button"
      className={className}
      title={signal.title}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        navigate(target);
      }}
    >
      {signal.icon}
      <span className="truncate max-w-[10rem]">{signal.label}</span>
    </button>
  );
}
