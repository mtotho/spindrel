import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Bot, Brain, Clock, Database, FileText, Search, Sparkles } from "lucide-react";
import { useHashTab } from "@/src/hooks/useHashTab";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { Section } from "@/src/components/shared/FormControls";
import { SelectDropdown } from "@/src/components/shared/SelectDropdown";
import { SourceFileInspector } from "@/src/components/shared/SourceFileInspector";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsSegmentedControl,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import {
  type LearningSearchResult,
  type LearningSearchSource,
  useKnowledgeLibrary,
  useLearningMemoryActivity,
  useLearningOverview,
  useLearningSearch,
} from "@/src/api/hooks/useLearningOverview";
import { DreamingTab } from "./DreamingTab";
import { SkillsTab } from "./SkillsTab";

const TABS = ["Overview", "Memory", "Knowledge", "History", "Dreaming", "Skills"] as const;
type Tab = (typeof TABS)[number];

const TIME_RANGES = [
  { label: "24h", value: "1", days: 1 },
  { label: "7d", value: "7", days: 7 },
  { label: "30d", value: "30", days: 30 },
  { label: "All", value: "0", days: 0 },
];

const SOURCE_OPTIONS: Array<{ key: LearningSearchSource; label: string; icon: React.ReactNode }> = [
  { key: "memory", label: "Memory", icon: <Brain size={13} /> },
  { key: "bot_knowledge", label: "Bot KB", icon: <BookOpen size={13} /> },
  { key: "channel_knowledge", label: "Channel KB", icon: <Database size={13} /> },
  { key: "history", label: "History", icon: <Clock size={13} /> },
];

function fmtRelative(value?: string | null) {
  if (!value) return "never";
  const diff = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(diff)) return "unknown";
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  const days = Math.round(hours / 24);
  return `${days}d ago`;
}

function sourceLabel(source: LearningSearchSource | string) {
  return SOURCE_OPTIONS.find((option) => option.key === source)?.label ?? source;
}

function resultMeta(result: LearningSearchResult) {
  return [
    result.bot_name,
    result.channel_name,
    result.section ? `section ${result.section}` : null,
    result.created_at ? fmtRelative(result.created_at) : null,
  ].filter(Boolean).join(" · ");
}

function SourceToggles({
  value,
  onChange,
}: {
  value: LearningSearchSource[];
  onChange: (sources: LearningSearchSource[]) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {SOURCE_OPTIONS.map((source) => {
        const active = value.includes(source.key);
        return (
          <button
            key={source.key}
            type="button"
            onClick={() => {
              if (active && value.length === 1) return;
              onChange(active ? value.filter((item) => item !== source.key) : [...value, source.key]);
            }}
            className={
              `inline-flex min-h-[32px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold transition-colors ` +
              (active
                ? "bg-accent/[0.08] text-accent"
                : "bg-surface-raised/40 text-text-dim hover:bg-surface-overlay/50 hover:text-text-muted")
            }
          >
            {source.icon}
            {source.label}
          </button>
        );
      })}
    </div>
  );
}

function ResultRow({
  result,
  active,
  onSelect,
}: {
  result: LearningSearchResult;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <SettingsControlRow
      active={active}
      onClick={onSelect}
      leading={<FileText size={14} />}
      title={
        <span className="flex min-w-0 items-center gap-2">
          <span className="truncate">{result.title}</span>
          <QuietPill label={sourceLabel(result.source)} maxWidthClass="max-w-[110px]" />
        </span>
      }
      description={
        <span className="line-clamp-2">
          {result.snippet || "No preview available."}
        </span>
      }
      meta={resultMeta(result)}
    />
  );
}

function DetailPane({ result, onClose }: { result: LearningSearchResult | null; onClose: () => void }) {
  const navigate = useNavigate();
  if (!result) {
    return (
      <aside className="hidden xl:flex xl:w-[340px] xl:shrink-0 xl:flex-col xl:gap-3">
        <div className="rounded-md bg-surface-raised/35 px-4 py-8 text-center text-[12px] text-text-dim">
          Select a result or activity row to inspect source metadata.
        </div>
      </aside>
    );
  }
  if (result.source_file) {
    return (
      <SourceFileInspector
        target={result.source_file}
        title={result.title}
        subtitle={result.snippet}
        fallbackUrl={result.open_url}
        onOpenFallback={(url) => navigate(url)}
        onClose={onClose}
      />
    );
  }
  return (
    <aside className="flex flex-col gap-3 xl:w-[360px] xl:shrink-0">
      <div className="rounded-md bg-surface-raised/45 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
              {sourceLabel(result.source)}
            </div>
            <h3 className="mt-1 truncate text-[14px] font-semibold text-text">{result.title}</h3>
          </div>
          <ActionButton label="Close" variant="ghost" size="small" onPress={onClose} />
        </div>
        <p className="mt-3 whitespace-pre-wrap text-[12px] leading-relaxed text-text-muted">
          {result.snippet || "No preview available."}
        </p>
      </div>
      <div className="rounded-md bg-surface-raised/35 px-4 py-3 text-[12px] text-text-muted">
        <div className="grid gap-2">
          {result.bot_name && <div><span className="text-text-dim">Bot:</span> {result.bot_name}</div>}
          {result.channel_name && <div><span className="text-text-dim">Channel:</span> {result.channel_name}</div>}
          {result.file_path && <div className="break-all"><span className="text-text-dim">Path:</span> {result.file_path}</div>}
          {result.section && <div><span className="text-text-dim">Section:</span> #{result.section}</div>}
          {result.created_at && <div><span className="text-text-dim">When:</span> {fmtRelative(result.created_at)}</div>}
          {result.correlation_id && <div className="break-all"><span className="text-text-dim">Run:</span> {result.correlation_id}</div>}
        </div>
        {result.open_url && (
          <div className="mt-3">
            <ActionButton label="Open location" size="small" onPress={() => navigate(result.open_url!)} />
          </div>
        )}
      </div>
    </aside>
  );
}

function SearchWorkbench({
  days,
  defaultSources = ["memory", "bot_knowledge", "channel_knowledge", "history"],
  onSelectResult,
  selectedId,
}: {
  days: number;
  defaultSources?: LearningSearchSource[];
  onSelectResult: (result: LearningSearchResult) => void;
  selectedId?: string | null;
}) {
  const { data: bots } = useAdminBots();
  const { data: channels } = useChannels();
  const searchMutation = useLearningSearch();
  const [query, setQuery] = useState("");
  const [sources, setSources] = useState<LearningSearchSource[]>(defaultSources);
  const [botId, setBotId] = useState("");
  const [channelId, setChannelId] = useState("");

  const botOptions = useMemo(() => [
    { value: "", label: "All bots" },
    ...(bots ?? []).map((bot) => ({ value: bot.id, label: bot.name, searchText: `${bot.name} ${bot.id}` })),
  ], [bots]);
  const channelOptions = useMemo(() => [
    { value: "", label: "All channels" },
    ...(channels ?? []).map((channel) => ({ value: channel.id, label: channel.name, searchText: `${channel.name} ${channel.id}` })),
  ], [channels]);

  const runSearch = () => {
    const trimmed = query.trim();
    if (!trimmed) return;
    searchMutation.mutate({
      query: trimmed,
      sources,
      bot_ids: botId ? [botId] : undefined,
      channel_ids: channelId ? [channelId] : undefined,
      days,
      top_k_per_source: 6,
    });
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-md bg-surface-raised/35 p-3 md:p-4">
        <div className="flex flex-col gap-3">
          <div className="flex min-h-[44px] items-center gap-2 rounded-md bg-input px-3 text-text-dim focus-within:ring-2 focus-within:ring-accent/30">
            <Search size={16} className="shrink-0" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") runSearch();
              }}
              placeholder="Search memory, knowledge, and archived history..."
              className="min-w-0 flex-1 bg-transparent text-[14px] text-text outline-none placeholder:text-text-dim"
            />
            <ActionButton
              label={searchMutation.isPending ? "Searching" : "Search"}
              size="small"
              disabled={!query.trim() || searchMutation.isPending}
              onPress={runSearch}
            />
          </div>
          <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
            <SourceToggles value={sources} onChange={setSources} />
            <div className="grid gap-2 sm:grid-cols-2 lg:w-[520px]">
              <SelectDropdown value={botId} onChange={setBotId} options={botOptions} searchable popoverWidth="content" size="sm" />
              <SelectDropdown value={channelId} onChange={setChannelId} options={channelOptions} searchable popoverWidth="content" size="sm" />
            </div>
          </div>
        </div>
      </div>

      {searchMutation.isError && (
        <div className="rounded-md bg-danger/10 px-3 py-2 text-[12px] text-danger">
          Search failed. Check server logs for the source-specific failure.
        </div>
      )}

      {searchMutation.isPending && !searchMutation.data && (
        <div className="flex flex-col gap-2">
          <SettingsGroupLabel label="Search Results" />
          <div className="flex flex-col gap-1.5">
            {[0, 1, 2].map((item) => (
              <div key={item} className="h-16 rounded-md bg-surface-raised/35" />
            ))}
          </div>
        </div>
      )}

      {searchMutation.data && (
        <div className="flex flex-col gap-2">
          <div className="flex items-center justify-between gap-3">
            <SettingsGroupLabel
              label={searchMutation.isPending ? "Refreshing Results" : "Search Results"}
              count={searchMutation.data.results.length}
            />
            {searchMutation.isPending && (
              <span className="text-[11px] font-semibold uppercase tracking-[0.08em] text-text-dim">
                Searching
              </span>
            )}
          </div>
          {searchMutation.data.results.length === 0 ? (
            <EmptyState message="No matching durable context found." />
          ) : (
            <div className="flex flex-col gap-1.5">
              {searchMutation.data.results.map((result) => (
                <ResultRow
                  key={result.id}
                  result={result}
                  active={selectedId === result.id}
                  onSelect={() => onSelectResult(result)}
                />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function OverviewTab({ days, onSelectResult, selectedId }: { days: number; onSelectResult: (result: LearningSearchResult) => void; selectedId?: string | null }) {
  const { data, isLoading } = useLearningOverview(days);
  const { data: library } = useKnowledgeLibrary();
  const memoryWrites = data?.memory_activity.length ?? 0;
  const kbFiles = library?.items.reduce((sum, item) => sum + item.file_count, 0) ?? 0;
  return (
    <div className="flex flex-col gap-7">
      <SearchWorkbench days={days} onSelectResult={onSelectResult} selectedId={selectedId} />
      <Section title="Recent Context Activity" description="A compact view of what changed recently across memory, knowledge, dreaming, and skills.">
        {isLoading ? (
          <div className="grid gap-2 md:grid-cols-4">
            {["h-14", "h-14", "h-14", "h-14"].map((height, index) => (
              <div key={index} className={`${height} rounded-md bg-surface-raised/35`} />
            ))}
          </div>
        ) : (
          <SettingsStatGrid
            items={[
              { label: "Memory writes", value: memoryWrites, tone: memoryWrites ? "accent" : "default" },
              { label: "KB files", value: kbFiles, tone: kbFiles ? "success" : "default" },
              { label: "Dreaming bots", value: `${data?.dreaming_enabled_count ?? 0}/${data?.total_bots ?? 0}` },
              { label: "Skill surfacings", value: data?.surfacings ?? 0 },
            ]}
          />
        )}
      </Section>
      <MemoryActivityPreview days={days} onSelectResult={onSelectResult} selectedId={selectedId} limit={8} />
    </div>
  );
}

function MemoryActivityPreview({
  days,
  onSelectResult,
  selectedId,
  limit,
}: {
  days: number;
  onSelectResult: (result: LearningSearchResult) => void;
  selectedId?: string | null;
  limit?: number;
}) {
  const { data, isLoading } = useLearningMemoryActivity(days);
  const rows = (data ?? []).slice(0, limit);
  return (
    <Section title="Memory Timeline" description="Existing file tool events: who changed which memory file, and whether the change came from a hygiene job.">
      {isLoading ? (
        <div className="flex flex-col gap-2">
          {[0, 1, 2].map((item) => <div key={item} className="h-14 rounded-md bg-surface-raised/35" />)}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState message="No memory writes in this window." />
      ) : (
        <div className="flex flex-col gap-1.5">
          {rows.map((row, index) => {
            const id = [
              "activity",
              row.correlation_id ?? row.created_at ?? index,
              row.file_path,
              row.created_at ?? index,
              index,
            ].join(":");
            const result: LearningSearchResult = {
              id,
              source: "memory",
              title: row.file_path,
              snippet: `${row.operation} by ${row.bot_name || row.bot_id}${row.job_type ? ` during ${row.job_type}` : ""}`,
              bot_id: row.bot_id,
              bot_name: row.bot_name,
              file_path: row.file_path,
              created_at: row.created_at,
              correlation_id: row.correlation_id,
              metadata: { operation: row.operation, job_type: row.job_type, is_hygiene: row.is_hygiene },
              open_url: row.bot_id ? `/admin/bots/${row.bot_id}#learning` : undefined,
              source_file: row.source_file,
            };
            return (
              <SettingsControlRow
                key={id}
                active={selectedId === id}
                onClick={() => onSelectResult(result)}
                leading={<Brain size={14} />}
                title={<span className="truncate">{row.file_path}</span>}
                description={`${row.operation} · ${row.bot_name || row.bot_id || "unknown bot"}`}
                meta={
                  <span className="inline-flex items-center gap-1.5">
                    {row.job_type && <QuietPill label={row.job_type.replace("_", " ")} maxWidthClass="max-w-[120px]" />}
                    <span>{fmtRelative(row.created_at)}</span>
                  </span>
                }
              />
            );
          })}
        </div>
      )}
    </Section>
  );
}

function MemoryTab({ days, onSelectResult, selectedId }: { days: number; onSelectResult: (result: LearningSearchResult) => void; selectedId?: string | null }) {
  return (
    <div className="flex flex-col gap-7">
      <SearchWorkbench days={days} defaultSources={["memory"]} onSelectResult={onSelectResult} selectedId={selectedId} />
      <MemoryActivityPreview days={days} onSelectResult={onSelectResult} selectedId={selectedId} />
    </div>
  );
}

function KnowledgeTab({ days, onSelectResult, selectedId }: { days: number; onSelectResult: (result: LearningSearchResult) => void; selectedId?: string | null }) {
  const { data, isLoading } = useKnowledgeLibrary();
  const [filter, setFilter] = useState("");
  const items = useMemo(() => {
    const term = filter.trim().toLowerCase();
    return (data?.items ?? []).filter((item) => {
      if (!term) return true;
      return `${item.owner_name} ${item.path_prefix} ${item.source}`.toLowerCase().includes(term);
    });
  }, [data?.items, filter]);
  return (
    <div className="flex flex-col gap-7">
      <SearchWorkbench days={days} defaultSources={["bot_knowledge", "channel_knowledge"]} onSelectResult={onSelectResult} selectedId={selectedId} />
      <Section title="Knowledge Library" description="Convention-based bot and channel knowledge-base indexes. This is inventory and inspection only.">
        <div className="flex flex-col gap-3">
          <SettingsSearchBox value={filter} onChange={setFilter} placeholder="Filter knowledge bases..." className="max-w-xl" />
          {isLoading ? (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((item) => <div key={item} className="h-14 rounded-md bg-surface-raised/35" />)}
            </div>
          ) : items.length === 0 ? (
            <EmptyState message="No indexed knowledge-base files found yet." />
          ) : (
            <div className="flex flex-col gap-1.5">
              {items.map((item) => (
                <SettingsControlRow
                  key={`${item.source}:${item.owner_id}`}
                  leading={item.source === "bot_knowledge" ? <Bot size={14} /> : <Database size={14} />}
                  title={item.owner_name}
                  description={item.path_prefix}
                  meta={
                    <span className="inline-flex items-center gap-1.5">
                      <QuietPill label={sourceLabel(item.source)} />
                      <span>{item.file_count} files</span>
                      <span>{item.chunk_count} chunks</span>
                      {item.last_indexed_at && <span>{fmtRelative(item.last_indexed_at)}</span>}
                    </span>
                  }
                />
              ))}
            </div>
          )}
        </div>
      </Section>
    </div>
  );
}

function HistoryTab({ days, onSelectResult, selectedId }: { days: number; onSelectResult: (result: LearningSearchResult) => void; selectedId?: string | null }) {
  return (
    <div className="flex flex-col gap-7">
      <SearchWorkbench days={days} defaultSources={["history"]} onSelectResult={onSelectResult} selectedId={selectedId} />
      <Section title="Archived Sections" description="History search mirrors the agent-facing conversation-history search path. It searches compacted sections, not active live messages.">
        <EmptyState message="Run a history search above to inspect archived section matches." />
      </Section>
    </div>
  );
}

export default function LearningCenterPage() {
  const { refreshing, onRefresh } = usePageRefresh();
  const [tab, setTab] = useHashTab<Tab>("Overview", TABS);
  const [daysValue, setDaysValue] = useState("30");
  const [selectedResult, setSelectedResult] = useState<LearningSearchResult | null>(null);
  const days = TIME_RANGES.find((range) => range.value === daysValue)?.days ?? 30;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Memory & Knowledge"
        subtitle="Search and inspect what bots remember, know, and retrieve."
      />
      <div className="flex flex-col gap-3 px-4 pb-3 pt-2 md:px-6">
        <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <div className="min-w-0 flex-1 overflow-x-auto pb-1 [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            <SettingsSegmentedControl
              value={tab}
              onChange={(next) => {
                setTab(next);
                setSelectedResult(null);
              }}
              options={TABS.map((name) => ({ value: name, label: name }))}
              className="w-max"
            />
          </div>
          <div className="w-[120px] shrink-0">
            <SelectDropdown
              value={daysValue}
              onChange={setDaysValue}
              options={TIME_RANGES.map((range) => ({ value: range.value, label: range.label }))}
              size="sm"
              popoverWidth="content"
            />
          </div>
        </div>
      </div>
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="min-h-0 flex-1">
        <div className="flex flex-col gap-6 px-4 pb-8 pt-2 md:px-6 xl:flex-row xl:items-start">
          <main className="min-w-0 flex-1">
            {tab === "Overview" && <OverviewTab days={days} onSelectResult={setSelectedResult} selectedId={selectedResult?.id} />}
            {tab === "Memory" && <MemoryTab days={days} onSelectResult={setSelectedResult} selectedId={selectedResult?.id} />}
            {tab === "Knowledge" && <KnowledgeTab days={days} onSelectResult={setSelectedResult} selectedId={selectedResult?.id} />}
            {tab === "History" && <HistoryTab days={days} onSelectResult={setSelectedResult} selectedId={selectedResult?.id} />}
            {tab === "Dreaming" && <DreamingTab />}
            {tab === "Skills" && <SkillsTab days={days} />}
          </main>
          {(tab === "Overview" || tab === "Memory" || tab === "Knowledge" || tab === "History") && (
            <DetailPane result={selectedResult} onClose={() => setSelectedResult(null)} />
          )}
        </div>
      </RefreshableScrollView>
    </div>
  );
}
