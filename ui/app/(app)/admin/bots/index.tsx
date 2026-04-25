import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Bot, Brain, FileText, KeyRound, MessageSquare, Plus, ShieldAlert, Sparkles, Wrench } from "lucide-react";

import { useAdminBots } from "@/src/api/hooks/useBots";
import { useAdminUsers } from "@/src/api/hooks/useAdminUsers";
import { useUsageSummary, type CostByDimension } from "@/src/api/hooks/useUsage";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { SelectInput } from "@/src/components/shared/FormControls";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import type { BotConfig } from "@/src/types/api";

type SortKey = "name" | "model" | "calls" | "tokens" | "cost";
type SortDir = "asc" | "desc";

interface BotWithUsage {
  bot: BotConfig;
  usage: CostByDimension | null;
}

const SORT_OPTIONS: Array<{ label: string; value: SortKey }> = [
  { label: "Name", value: "name" },
  { label: "Model", value: "model" },
  { label: "Calls", value: "calls" },
  { label: "Tokens", value: "tokens" },
  { label: "Cost", value: "cost" },
];

function fmtTokens(n: number | undefined | null): string {
  if (!n) return "--";
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function fmtCost(v: number | null | undefined): string {
  if (v == null) return "--";
  if (v === 0) return "$0";
  if (v < 0.01) return `$${v.toFixed(4)}`;
  return `$${v.toFixed(2)}`;
}

function sortBots(items: BotWithUsage[], key: SortKey, dir: SortDir): BotWithUsage[] {
  return [...items].sort((a, b) => {
    let cmp = 0;
    if (key === "name") cmp = a.bot.name.localeCompare(b.bot.name);
    if (key === "model") cmp = a.bot.model.localeCompare(b.bot.model);
    if (key === "calls") cmp = (a.usage?.calls ?? 0) - (b.usage?.calls ?? 0);
    if (key === "tokens") cmp = (a.usage?.total_tokens ?? 0) - (b.usage?.total_tokens ?? 0);
    if (key === "cost") cmp = (a.usage?.cost ?? 0) - (b.usage?.cost ?? 0);
    return dir === "asc" ? cmp : -cmp;
  });
}

function enabledSurfaces(bot: BotConfig): string[] {
  const labels: string[] = [];
  const toolCount = (bot.local_tools?.length ?? 0) + (bot.client_tools?.length ?? 0) + (bot.pinned_tools?.length ?? 0);
  const skillCount = bot.skills?.length ?? 0;
  const delegateCount = (bot.delegation_config?.delegate_bots as string[] | undefined)?.length ?? bot.delegate_bots?.length ?? 0;
  if (toolCount) labels.push(`${toolCount} tools`);
  if (skillCount) labels.push(`${skillCount} skills`);
  if (bot.mcp_servers?.length) labels.push(`${bot.mcp_servers.length} MCP`);
  if (delegateCount) labels.push(`${delegateCount} delegates`);
  if (bot.memory?.enabled || bot.memory_scheme === "workspace-files") labels.push("Memory");
  if (bot.workspace?.enabled || bot.shared_workspace_id) labels.push("Workspace");
  return labels;
}

function warningBadges(bot: BotConfig): React.ReactNode[] {
  const badges: React.ReactNode[] = [];
  const workspace = bot.workspace ?? {};
  if (workspace.cross_workspace_access) badges.push(<StatusBadge key="cross-workspace" label="cross workspace" variant="warning" />);
  if (bot.api_permissions?.length) badges.push(<StatusBadge key="api" label={`${bot.api_permissions.length} api scopes`} variant="info" />);
  if (bot.system_prompt_workspace_file) badges.push(<QuietPill key="prompt-file" label="prompt file" />);
  if (bot.persona_from_workspace) badges.push(<QuietPill key="persona-file" label="persona file" />);
  return badges;
}

function BotIcon({ bot }: { bot: BotConfig }) {
  if (bot.avatar_url) return <img src={bot.avatar_url} alt="" className="h-8 w-8 rounded-full object-cover" />;
  return (
    <div className="flex h-8 w-8 items-center justify-center rounded-full bg-accent/10 text-accent">
      <Bot size={16} />
    </div>
  );
}

function BotRow({ item, ownerName, onOpen }: { item: BotWithUsage; ownerName: string | null; onOpen: () => void }) {
  const { bot, usage } = item;
  const surfaces = enabledSurfaces(bot);
  const warnings = warningBadges(bot);
  const promptPreview = bot.system_prompt?.replace(/\s+/g, " ").trim();

  return (
    <SettingsControlRow onClick={onOpen} className="overflow-hidden">
      <div className="flex min-w-0 flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div className="flex min-w-0 gap-3">
          <BotIcon bot={bot} />
          <div className="min-w-0 flex-1">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <span className="min-w-0 truncate text-[13px] font-semibold text-text">{bot.name}</span>
              {bot.display_name && bot.display_name !== bot.name && <QuietPill label={bot.display_name} maxWidthClass="max-w-[180px]" />}
              <QuietPill label={bot.id} maxWidthClass="max-w-[180px]" />
              {bot.source_type === "system" && <StatusBadge label="system" variant="neutral" />}
              {warnings}
            </div>
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-text-dim">
              <span className="inline-flex min-w-0 items-center gap-1">
                <Sparkles size={12} className="shrink-0" />
                <span className="truncate">{bot.model || "No model"}</span>
              </span>
              {ownerName && (
                <span className="inline-flex min-w-0 items-center gap-1">
                  <KeyRound size={12} className="shrink-0" />
                  <span className="truncate">{ownerName}</span>
                </span>
              )}
              {surfaces.length > 0 && (
                <span className="inline-flex min-w-0 items-center gap-1">
                  <Wrench size={12} className="shrink-0" />
                  <span className="truncate">{surfaces.join(" · ")}</span>
                </span>
              )}
            </div>
            {promptPreview && <div className="mt-2 line-clamp-2 text-[12px] leading-relaxed text-text-dim">{promptPreview}</div>}
          </div>
        </div>

        <div className="grid min-w-0 grid-cols-3 gap-2 md:w-[280px] md:shrink-0">
          <div className="rounded-md bg-surface-overlay/25 px-2 py-1.5">
            <div className="font-mono text-[12px] font-semibold text-text">{usage?.calls?.toLocaleString() ?? "--"}</div>
            <div className="mt-0.5 text-[9px] uppercase tracking-[0.08em] text-text-dim">calls</div>
          </div>
          <div className="rounded-md bg-surface-overlay/25 px-2 py-1.5">
            <div className="font-mono text-[12px] font-semibold text-text">{fmtTokens(usage?.total_tokens)}</div>
            <div className="mt-0.5 text-[9px] uppercase tracking-[0.08em] text-text-dim">tokens</div>
          </div>
          <div className="rounded-md bg-surface-overlay/25 px-2 py-1.5">
            <div className="font-mono text-[12px] font-semibold text-text">{fmtCost(usage?.cost)}</div>
            <div className="mt-0.5 text-[9px] uppercase tracking-[0.08em] text-text-dim">cost</div>
          </div>
        </div>
      </div>
    </SettingsControlRow>
  );
}

export default function AdminBotsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("name");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const { data: bots, isLoading } = useAdminBots();
  const { data: users } = useAdminUsers();
  const { data: usageData } = useUsageSummary({ after: "30d" });
  const { refreshing, onRefresh } = usePageRefresh([["admin-bots"], ["usage-summary"]]);

  const userNameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const u of users ?? []) m.set(u.id, u.display_name || u.email || u.id);
    return m;
  }, [users]);

  const usageByBot = useMemo(() => {
    const m = new Map<string, CostByDimension>();
    for (const row of usageData?.cost_by_bot ?? []) m.set(row.label, row);
    return m;
  }, [usageData]);

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const withUsage = (bots ?? []).map((bot) => ({ bot, usage: usageByBot.get(bot.id) ?? usageByBot.get(bot.name) ?? null }));
    const filtered = q
      ? withUsage.filter(({ bot }) =>
          [bot.id, bot.name, bot.display_name, bot.model, bot.source_type, bot.user_id ? userNameById.get(bot.user_id) : "", ...enabledSurfaces(bot)]
            .filter(Boolean)
            .join(" ")
            .toLowerCase()
            .includes(q),
        )
      : withUsage;
    return sortBots(filtered, sortKey, sortDir);
  }, [bots, query, sortDir, sortKey, usageByBot, userNameById]);

  const totals = useMemo(() => {
    const all = bots ?? [];
    return {
      bots: all.length,
      workspace: all.filter((bot) => bot.workspace?.enabled || bot.shared_workspace_id).length,
      api: all.filter((bot) => bot.api_permissions?.length).length,
      cost: usageData?.total_cost ?? null,
    };
  }, [bots, usageData]);

  return (
    <div className="flex min-w-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Bots"
        subtitle="Configure bot identity, instructions, tools, memory, and access."
        right={<ActionButton label="New Bot" icon={<Plus size={14} />} onPress={() => navigate("/admin/bots/new")} />}
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        className="flex-1"
        contentContainerStyle={{ maxWidth: 1152, width: "100%", margin: "0 auto", padding: "20px 24px", display: "flex", flexDirection: "column", gap: 24 }}
      >
        <SettingsStatGrid
          items={[
            { label: "Configured", value: totals.bots },
            { label: "Workspace linked", value: totals.workspace, tone: totals.workspace ? "accent" : "default" },
            { label: "API scoped", value: totals.api, tone: totals.api ? "warning" : "default" },
            { label: "30d cost", value: fmtCost(totals.cost), tone: totals.cost ? "accent" : "default" },
          ]}
        />

        <div className="flex flex-col gap-3 md:flex-row md:items-center">
          <SettingsSearchBox value={query} onChange={setQuery} placeholder="Filter bots..." className="min-w-0 flex-1 md:max-w-xl" />
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <div className="w-[170px]">
              <SelectInput value={sortKey} onChange={(v) => setSortKey(v as SortKey)} options={SORT_OPTIONS} />
            </div>
            <ActionButton label={sortDir === "asc" ? "Ascending" : "Descending"} variant="secondary" onPress={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))} />
          </div>
        </div>

        <div className="flex flex-col gap-2">
          <SettingsGroupLabel label="Current bots" count={rows.length} icon={<Bot size={13} className="text-text-dim" />} />
          {isLoading ? (
            <div className="py-10"><Spinner size={18} /></div>
          ) : rows.length === 0 ? (
            <EmptyState message={query ? "No bots match that filter." : "No bots configured yet."} action={<ActionButton label="Create bot" icon={<Plus size={14} />} onPress={() => navigate("/admin/bots/new")} />} />
          ) : (
            rows.map((item) => (
              <BotRow key={item.bot.id} item={item} ownerName={item.bot.user_id ? (userNameById.get(item.bot.user_id) ?? null) : null} onOpen={() => navigate(`/admin/bots/${item.bot.id}`)} />
            ))
          )}
        </div>

        <div className="grid gap-2 md:grid-cols-4">
          <SettingsControlRow leading={<FileText size={14} />} title="Prompt source" description="Workspace prompt files are shown as first-class source markers." />
          <SettingsControlRow leading={<Brain size={14} />} title="Memory" description="Memory and workspace-file schemes are visible before opening the editor." />
          <SettingsControlRow leading={<ShieldAlert size={14} />} title="Access flags" description="API scopes and cross-workspace access are surfaced on the row." />
          <SettingsControlRow leading={<MessageSquare size={14} />} title="Usage" description="30-day calls, tokens, and cost stay visible while scanning." />
        </div>
      </RefreshableScrollView>
    </div>
  );
}
