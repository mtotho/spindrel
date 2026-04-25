import { AlertTriangle, RefreshCw, Server, Container } from "lucide-react";
import { useCronJobs } from "@/src/api/hooks/useTasks";
import { useQueryClient } from "@tanstack/react-query";
import type { CronEntry } from "@/src/types/api";

export function CronJobsView() {
  const qc = useQueryClient();
  const { data, isLoading, isFetching } = useCronJobs();

  if (isLoading) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center p-10">
        <div className="chat-spinner" />
      </div>
    );
  }

  const jobs = data?.cron_jobs ?? [];
  const errors = data?.errors ?? [];

  const containerJobs = jobs.filter((j) => j.source_type === "container");
  const hostJobs = jobs.filter((j) => j.source_type === "host");

  // Group container jobs by source_name
  const containerGroups: Record<string, CronEntry[]> = {};
  for (const j of containerJobs) {
    const key = j.source_name;
    if (!containerGroups[key]) containerGroups[key] = [];
    containerGroups[key].push(j);
  }

  return (
    <div className="flex flex-col gap-4 p-5">
      {/* Header */}
      <div className="flex flex-row items-center justify-between">
        <span className="text-[13px] text-text-muted">
          {jobs.length} cron job{jobs.length !== 1 ? "s" : ""} discovered
        </span>
        <button
          onClick={() => qc.invalidateQueries({ queryKey: ["admin-cron-jobs"] })}
          className={`flex flex-row items-center gap-1 rounded-md px-2.5 py-1 text-[11px] font-semibold text-text-muted hover:bg-surface-overlay/50 hover:text-text ${isFetching ? "opacity-50" : ""}`}
        >
          <RefreshCw size={11} style={isFetching ? { animation: "spin 1s linear infinite" } : undefined} />
          Refresh
        </button>
      </div>

      {/* Errors banner */}
      {errors.length > 0 && (
        <div className="flex flex-row items-start gap-2 rounded-md bg-warning/10 px-3 py-2">
          <AlertTriangle size={14} className="mt-px shrink-0 text-warning-muted" />
          <div className="text-[11px] text-warning-muted">
            {errors.map((e, i) => (
              <div key={i}>{e}</div>
            ))}
          </div>
        </div>
      )}

      {jobs.length === 0 && !isLoading && (
        <div className="p-10 text-center text-[13px] text-text-dim">
          No cron jobs found in any running containers or on the host.
        </div>
      )}

      {/* Container groups */}
      {Object.entries(containerGroups).map(([name, entries]) => (
        <SourceGroup
          key={name}
          icon={<Container size={13} className="text-accent" />}
          title={name}
          subtitle={entries[0].workspace_name ?? undefined}
          entries={entries}
        />
      ))}

      {/* Host group */}
      {hostJobs.length > 0 && (
        <SourceGroup
          icon={<Server size={13} className="text-text-muted" />}
          title={hostJobs[0].source_name}
          subtitle="Host OS"
          entries={hostJobs}
        />
      )}
    </div>
  );
}

function SourceGroup({
  icon,
  title,
  subtitle,
  entries,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle?: string;
  entries: CronEntry[];
}) {
  return (
    <div className="overflow-hidden rounded-md bg-surface-raised/40">
      {/* Group header */}
      <div className="flex flex-row items-center gap-2 px-3 py-2">
        {icon}
        <span className="text-[12px] font-semibold text-text">{title}</span>
        {subtitle && (
          <span className="text-[11px] text-text-dim">({subtitle})</span>
        )}
        <span className="ml-auto text-[10px] text-text-dim">
          {entries.length} job{entries.length !== 1 ? "s" : ""}
        </span>
      </div>

      {/* Table */}
      <table className="w-full border-collapse">
        <thead>
          <tr>
            {["Schedule", "Command", "User"].map((h) => (
              <th
                key={h}
                className="border-t border-surface-border/60 px-3 py-1.5 text-left text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70"
              >
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {entries.map((e, i) => (
            <tr key={i}>
              <td className={`whitespace-nowrap px-3 py-1.5 font-mono text-[12px] text-accent ${i < entries.length - 1 ? "border-b border-surface-border/40" : ""}`}>
                {e.expression}
              </td>
              <td className={`break-all px-3 py-1.5 font-mono text-[12px] text-text ${i < entries.length - 1 ? "border-b border-surface-border/40" : ""}`}>
                {e.command}
              </td>
              <td className={`px-3 py-1.5 text-[11px] text-text-muted ${i < entries.length - 1 ? "border-b border-surface-border/40" : ""}`}>
                {e.user}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
