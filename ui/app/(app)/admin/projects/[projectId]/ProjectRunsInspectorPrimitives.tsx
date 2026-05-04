import { useEffect } from "react";
import type { ReactNode } from "react";
import { X } from "lucide-react";
import type { ProjectCodingRun, ProjectCodingRunSchedule } from "@/src/types/api";

export const WORK_SURFACE_OPTIONS = [
  { label: "Isolated worktree", value: "isolated_worktree" },
  { label: "Fresh Project instance", value: "fresh_project_instance" },
  { label: "Shared repo", value: "shared_repo" },
];

export function sessionPathForRun(run: ProjectCodingRun) {
  return run.task.channel_id && run.task.session_id ? `/channels/${run.task.channel_id}/session/${run.task.session_id}` : null;
}

export function sessionPathForScheduleRun(run?: ProjectCodingRunSchedule["last_run"] | null) {
  return run?.channel_id && run.session_id ? `/channels/${run.channel_id}/session/${run.session_id}` : null;
}

export function columnLabel(key: string) {
  if (key === "backlog") return "Backlog / ready";
  if (key === "running") return "Running";
  if (key === "review") return "Human review";
  return "Closed";
}

export function DetailRow({ label, value }: { label: string; value?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-t border-surface-border/45 pt-2 text-[12px]">
      <span className="text-text-dim">{label}</span>
      <span className="min-w-0 text-right font-semibold text-text-muted">{value || "none"}</span>
    </div>
  );
}

export function compactPath(value?: string | null) {
  if (!value) return "none";
  const parts = value.split("/").filter(Boolean);
  return parts.length > 4 ? `.../${parts.slice(-4).join("/")}` : value;
}

export function modelSelectionLine(selection?: Record<string, any> | null) {
  if (!selection) return "default";
  const model = selection.model_override || selection.effective_model;
  const effort = selection.harness_effort || selection.effective_harness_effort;
  const parts = [
    model ? String(model).split("/").pop() : null,
    effort ? `effort ${effort}` : null,
  ].filter(Boolean);
  return parts.length ? parts.join(" · ") : "default";
}

export function InspectorPanel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-md bg-surface-raised/55 p-3">
      <div className="mb-2 text-[11px] font-bold uppercase tracking-[0.08em] text-text-dim">{title}</div>
      {children}
    </div>
  );
}

export function DetailDrawer({ title, children, onClose }: { title: string; children: ReactNode; onClose: () => void }) {
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/45" onClick={onClose}>
      <div className="h-full w-full max-w-[460px] overflow-y-auto border-l border-surface-border bg-surface p-4 shadow-2xl" onClick={(event) => event.stopPropagation()}>
        <div className="mb-4 flex items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="truncate text-sm font-semibold text-text">{title}</div>
            <div className="text-[11px] text-text-dim">Project run inspector</div>
          </div>
          <button type="button" onClick={onClose} className="rounded-md p-2 text-text-muted hover:bg-surface-raised hover:text-text">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
