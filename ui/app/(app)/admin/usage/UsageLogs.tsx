import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, ListTree, Rows3 } from "lucide-react";

import { useBots } from "@/src/api/hooks/useBots";
import { useUsageLogs, type UsageLogEntry, type UsageParams } from "@/src/api/hooks/useUsage";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSegmentedControl,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { fmtCost, fmtDate, fmtDuration, fmtTime, fmtTokens } from "./usageUtils";

interface TraceGroup {
  correlation_id: string;
  created_at: string;
  bot_name: string | null;
  channel_name: string | null;
  entries: UsageLogEntry[];
  total_prompt_tokens: number;
  total_completion_tokens: number;
  total_cost: number | null;
  total_duration_ms: number | null;
  has_cost_data: boolean;
}

function groupByCorrelation(entries: UsageLogEntry[], bots: any[] | undefined): TraceGroup[] {
  const map = new Map<string, TraceGroup>();
  for (const entry of entries) {
    const key = entry.correlation_id || entry.id;
    let group = map.get(key);
    if (!group) {
      const bot = bots?.find((b: any) => b.id === entry.bot_id);
      group = {
        correlation_id: key,
        created_at: entry.created_at,
        bot_name: bot?.name || entry.bot_id || null,
        channel_name: entry.channel_name,
        entries: [],
        total_prompt_tokens: 0,
        total_completion_tokens: 0,
        total_cost: null,
        total_duration_ms: null,
        has_cost_data: true,
      };
      map.set(key, group);
    }
    group.entries.push(entry);
    group.total_prompt_tokens += entry.prompt_tokens;
    group.total_completion_tokens += entry.completion_tokens;
    if (entry.cost != null) group.total_cost = (group.total_cost ?? 0) + entry.cost;
    else group.has_cost_data = false;
    if (entry.duration_ms != null) group.total_duration_ms = (group.total_duration_ms ?? 0) + entry.duration_ms;
  }
  return Array.from(map.values());
}

export function LogsTab({
  params,
  onSelectTrace,
}: {
  params: UsageParams;
  onSelectTrace: (correlationId: string) => void;
}) {
  const [page, setPage] = useState(1);
  const [viewMode, setViewMode] = useState<"traces" | "raw">("traces");
  const { data, isLoading } = useUsageLogs({ ...params, page, page_size: 100 });
  const { data: bots } = useBots();
  const traceGroups = useMemo(() => (data ? groupByCorrelation(data.entries, bots) : []), [data, bots]);
  const totalPages = data ? Math.ceil(data.total / data.page_size) : 0;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-10">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <SettingsSegmentedControl
          value={viewMode}
          onChange={setViewMode}
          options={[
            { value: "traces", label: "Traces", count: traceGroups.length, icon: <ListTree size={13} /> },
            { value: "raw", label: "Raw Calls", count: data?.entries.length ?? 0, icon: <Rows3 size={13} /> },
          ]}
        />
        <div className="ml-auto text-[11px] text-text-dim">{data?.total ?? 0} calls in this filtered window</div>
      </div>

      {viewMode === "traces" ? (
        <div className="space-y-1.5">
          <SettingsGroupLabel label="Trace Runs" count={traceGroups.length} />
          {traceGroups.map((group) => (
            <SettingsControlRow
              key={group.correlation_id}
              title={`${fmtDate(group.created_at)} ${fmtTime(group.created_at)}`}
              description={`${group.bot_name || "Unknown bot"} · ${group.channel_name || "No channel"} · ${group.correlation_id}`}
              meta={
                <div className="flex flex-wrap items-center justify-end gap-1.5">
                  <QuietPill label={`${group.entries.length} calls`} />
                  <QuietPill label={`${fmtTokens(group.total_prompt_tokens + group.total_completion_tokens)} tokens`} />
                  <QuietPill label={fmtDuration(group.total_duration_ms)} />
                  <span className="font-mono text-[11px] text-text">{group.has_cost_data ? fmtCost(group.total_cost) : "--"}</span>
                  {!group.has_cost_data && <StatusBadge label="pricing missing" variant="warning" />}
                </div>
              }
              onClick={() => onSelectTrace(group.correlation_id)}
            />
          ))}
        </div>
      ) : (
        <div className="space-y-1.5">
          <SettingsGroupLabel label="Raw Calls" count={data?.entries.length ?? 0} />
          {data?.entries.map((entry) => {
            const bot = bots?.find((b: any) => b.id === entry.bot_id);
            const traceId = entry.correlation_id || entry.id;
            return (
              <SettingsControlRow
                key={entry.id}
                title={entry.model || "Unknown model"}
                description={`${fmtDate(entry.created_at)} ${fmtTime(entry.created_at)} · ${bot?.name || entry.bot_id || "--"} · ${entry.channel_name || "No channel"}`}
                meta={
                  <div className="flex flex-wrap items-center justify-end gap-1.5">
                    <QuietPill label={`${fmtTokens(entry.prompt_tokens)} in`} />
                    <QuietPill label={`${fmtTokens(entry.completion_tokens)} out`} />
                    <QuietPill label={fmtDuration(entry.duration_ms)} />
                    <span className="font-mono text-[11px] text-text">{entry.has_cost_data ? fmtCost(entry.cost) : "--"}</span>
                    {!entry.has_cost_data && <StatusBadge label="pricing missing" variant="warning" />}
                  </div>
                }
                onClick={() => onSelectTrace(traceId)}
              />
            );
          })}
        </div>
      )}

      {data?.entries.length === 0 && <EmptyState message="No usage data found for these filters." />}

      {totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 pt-2">
          <ActionButton
            label="Previous"
            variant="secondary"
            size="small"
            disabled={page <= 1}
            icon={<ChevronLeft size={14} />}
            onPress={() => setPage((p) => Math.max(1, p - 1))}
          />
          <span className="text-[12px] text-text-dim">Page {page} of {totalPages}</span>
          <ActionButton
            label="Next"
            variant="secondary"
            size="small"
            disabled={page >= totalPages}
            icon={<ChevronRight size={14} />}
            onPress={() => setPage((p) => Math.min(totalPages, p + 1))}
          />
        </div>
      )}
    </div>
  );
}
