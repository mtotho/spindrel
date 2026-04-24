import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  AlertTriangle,
  Bot,
  ChevronDown,
  ChevronRight,
  FileText,
  FolderTree,
  Plus,
  Puzzle,
  RefreshCw,
  ScrollText,
  Wrench,
} from "lucide-react";

import { useFileSync, useSkills, type FileSyncResult } from "@/src/api/hooks/useSkills";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { Spinner } from "@/src/components/shared/Spinner";
import { SelectDropdown, type SelectDropdownOption } from "@/src/components/shared/SelectDropdown";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsSegmentedControl,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

import {
  buildSkillLibraryGroups,
  childCount,
  countEntry,
  filterSkillEntry,
  skillSourceBucket,
  type SkillLibraryEntry,
  type SkillLibraryGroup,
  type SkillSourceBucket,
} from "./skillLibrary";

type SourceFilter = "all" | SkillSourceBucket;
type HealthFilter = "all" | "warnings" | "scripts" | "folders";

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  if (!Number.isFinite(diff)) return "unknown";
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

function sourceIcon(bucket: SkillSourceBucket) {
  if (bucket === "integration") return <Puzzle size={14} />;
  if (bucket === "bot") return <Bot size={14} />;
  if (bucket === "manual") return <Wrench size={14} />;
  return <FileText size={14} />;
}

function sourceBadge(bucket: SkillSourceBucket) {
  if (bucket === "integration") return <StatusBadge label="integration" variant="warning" />;
  if (bucket === "bot") return <StatusBadge label="bot" variant="purple" />;
  if (bucket === "manual") return <StatusBadge label="manual" variant="neutral" />;
  return <StatusBadge label="core" variant="info" />;
}

function syncMessage(result?: FileSyncResult) {
  if (!result) return null;
  const parts = [
    `${result.added} added`,
    `${result.updated} updated`,
    `${result.unchanged} unchanged`,
    `${result.deleted} deleted`,
  ];
  return parts.join(", ");
}

function skillHref(id: string) {
  return `/admin/skills/${encodeURIComponent(id)}`;
}

function filterEntryByHealth(entry: SkillLibraryEntry, filter: HealthFilter): SkillLibraryEntry | null {
  if (filter === "all") return entry;
  const childMatches = entry.children.flatMap((child) => {
    const next = filterEntryByHealth(child, filter);
    return next ? [next] : [];
  });
  const matches =
    filter === "warnings" ? entry.analysis.warnings.length > 0 :
    filter === "scripts" ? (entry.skill.script_count ?? 0) > 0 :
    entry.skill.has_children || entry.skill.skill_layout === "folder_root";
  return matches || childMatches.length > 0 ? { ...entry, children: childMatches } : null;
}

function SkillRow({
  entry,
  depth = 0,
  expanded,
  onToggle,
  onOpen,
}: {
  entry: SkillLibraryEntry;
  depth?: number;
  expanded: Set<string>;
  onToggle: (id: string) => void;
  onOpen: (id: string) => void;
}) {
  const bucket = skillSourceBucket(entry.skill);
  const hasChildren = entry.children.length > 0;
  const isOpen = expanded.has(entry.skill.id);
  const warnings = entry.analysis.warnings.length;
  const scripts = entry.skill.script_count ?? 0;
  const children = childCount(entry);

  return (
    <div className="flex flex-col gap-1.5">
      <SettingsControlRow className={depth ? "ml-5" : ""}>
        <div className="flex min-w-0 items-center gap-2.5">
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              if (hasChildren) onToggle(entry.skill.id);
            }}
            className="inline-flex h-7 w-7 items-center justify-center rounded-md text-text-dim hover:bg-surface-overlay/60 hover:text-text"
            aria-label={hasChildren ? (isOpen ? "Collapse skill group" : "Expand skill group") : "Skill"}
          >
            {hasChildren ? (isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />) : sourceIcon(bucket)}
          </button>
          <button type="button" onClick={() => onOpen(entry.skill.id)} className="min-w-0 flex-1 text-left">
            <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1">
              <span className="min-w-0 truncate text-[12px] font-semibold text-text">{entry.skill.name || entry.skill.id}</span>
              {hasChildren && <StatusBadge label="folder" variant="neutral" />}
              {sourceBadge(bucket)}
              {warnings > 0 && <StatusBadge label={`${warnings} warning${warnings === 1 ? "" : "s"}`} variant="warning" />}
            </div>
            <div className="mt-0.5 text-[11px] leading-snug text-text-dim">
              {entry.skill.description || entry.analysis.body.split("\n").find((line) => line.trim()) || "No description provided."}
            </div>
            <div className="mt-1 inline-flex flex-wrap items-center gap-1.5 text-[10px] text-text-dim">
              <QuietPill label={entry.skill.id} maxWidthClass="max-w-[220px]" />
              {entry.skill.category && <QuietPill label={entry.skill.category} maxWidthClass="max-w-[120px]" />}
              {children > 0 && <span>{children} child{children === 1 ? "" : "ren"}</span>}
              {scripts > 0 && <span>{scripts} script{scripts === 1 ? "" : "s"}</span>}
              <span>{entry.skill.chunk_count} chunks</span>
              <span>updated {fmtRelative(entry.skill.updated_at)}</span>
            </div>
          </button>
        </div>
      </SettingsControlRow>
      {hasChildren && isOpen && (
        <div className="flex flex-col gap-1.5">
          {entry.children.map((child) => (
            <SkillRow
              key={child.skill.id}
              entry={child}
              depth={depth + 1}
              expanded={expanded}
              onToggle={onToggle}
              onOpen={onOpen}
            />
          ))}
        </div>
      )}
    </div>
  );
}

export default function SkillsScreen() {
  const navigate = useNavigate();
  const { data: skills = [], isLoading, refetch } = useSkills({ sort: "name" });
  const syncMut = useFileSync();
  const [query, setQuery] = useState("");
  const [source, setSource] = useState<SourceFilter>("all");
  const [health, setHealth] = useState<HealthFilter>("all");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  const groups = useMemo(() => buildSkillLibraryGroups(skills), [skills]);

  const visibleGroups = useMemo(() => {
    return groups.flatMap((group): SkillLibraryGroup[] => {
      if (source !== "all" && group.bucket !== source) return [];
      const entries = group.entries.flatMap((entry) => {
        const queryMatch = filterSkillEntry(entry, query);
        const healthMatch = queryMatch ? filterEntryByHealth(queryMatch, health) : null;
        return healthMatch ? [healthMatch] : [];
      });
      if (!entries.length) return [];
      return [{ ...group, entries, count: entries.reduce((sum, entry) => sum + countEntry(entry), 0) }];
    });
  }, [groups, health, query, source]);

  const stats = useMemo(() => {
    let warnings = 0;
    let folders = 0;
    let scripts = 0;
    for (const group of groups) {
      const walk = (entry: SkillLibraryEntry) => {
        warnings += entry.analysis.warnings.length ? 1 : 0;
        folders += entry.skill.has_children || entry.skill.skill_layout === "folder_root" ? 1 : 0;
        scripts += entry.skill.script_count ?? 0;
        entry.children.forEach(walk);
      };
      group.entries.forEach(walk);
    }
    return { warnings, folders, scripts };
  }, [groups]);

  const sourceOptions: SelectDropdownOption[] = [
    { value: "all", label: "All sources", meta: skills.length },
    { value: "core", label: "Core", icon: <FileText size={13} />, meta: skills.filter((s) => skillSourceBucket(s) === "core").length },
    { value: "integration", label: "Integrations", icon: <Puzzle size={13} />, meta: skills.filter((s) => skillSourceBucket(s) === "integration").length },
    { value: "bot", label: "Bot-authored", icon: <Bot size={13} />, meta: skills.filter((s) => skillSourceBucket(s) === "bot").length },
    { value: "manual", label: "Manual", icon: <Wrench size={13} />, meta: skills.filter((s) => skillSourceBucket(s) === "manual").length },
  ];

  const toggleExpanded = (id: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const expandAllVisible = () => {
    const next = new Set<string>();
    for (const group of visibleGroups) {
      const walk = (entry: SkillLibraryEntry) => {
        if (entry.children.length) next.add(entry.skill.id);
        entry.children.forEach(walk);
      };
      group.entries.forEach(walk);
    }
    setExpanded(next);
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="list"
        title="Skills"
        subtitle="Canonical skill library across core files, integrations, bot-authored procedures, and manual entries."
        right={
          <div className="flex items-center gap-1.5">
            <ActionButton
              label="Sync Files"
              variant="secondary"
              icon={<RefreshCw size={14} className={syncMut.isPending ? "animate-spin" : ""} />}
              disabled={syncMut.isPending}
              onPress={() => syncMut.mutate()}
            />
            <ActionButton label="New Skill" icon={<Plus size={14} />} onPress={() => navigate("/admin/skills/new")} />
          </div>
        }
      />

      <RefreshableScrollView
        refreshing={isLoading || syncMut.isPending}
        className="flex-1"
        onRefresh={async () => { await refetch(); }}
        contentContainerStyle={{ padding: "24px", maxWidth: 1240, margin: "0 auto", width: "100%" }}
      >
        <div className="flex flex-col gap-7">
          {syncMut.data && (
            <InfoBanner variant={syncMut.data.errors?.length ? "warning" : "success"} icon={<RefreshCw size={13} />}>
              File sync complete: {syncMessage(syncMut.data)}
              {syncMut.data.errors?.length ? ` (${syncMut.data.errors.length} errors)` : ""}
            </InfoBanner>
          )}
          {syncMut.error && (
            <InfoBanner variant="danger" icon={<AlertTriangle size={13} />}>
              {(syncMut.error as Error)?.message || "File sync failed."}
            </InfoBanner>
          )}

          <SettingsStatGrid
            items={[
              { label: "Skills", value: skills.length },
              { label: "Folders", value: stats.folders, tone: stats.folders ? "accent" : "default" },
              { label: "Scripts", value: stats.scripts, tone: stats.scripts ? "warning" : "default" },
              { label: "Metadata warnings", value: stats.warnings, tone: stats.warnings ? "warning" : "success" },
            ]}
          />

          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-2 md:flex-row md:items-center">
              <SettingsSearchBox
                value={query}
                onChange={setQuery}
                placeholder="Filter skills, triggers, paths..."
                className="md:max-w-lg"
              />
              <div className="w-full md:w-56">
                <SelectDropdown
                  value={source}
                  options={sourceOptions}
                  onChange={(value) => setSource(value as SourceFilter)}
                  size="sm"
                  popoverWidth="content"
                />
              </div>
              <SettingsSegmentedControl<HealthFilter>
                value={health}
                onChange={setHealth}
                options={[
                  { value: "all", label: "All" },
                  { value: "warnings", label: "Warnings", count: stats.warnings },
                  { value: "scripts", label: "Scripts", count: stats.scripts },
                  { value: "folders", label: "Folders", count: stats.folders },
                ]}
              />
              <ActionButton label="Expand" variant="ghost" size="small" icon={<FolderTree size={13} />} onPress={expandAllVisible} />
            </div>

            {isLoading ? (
              <div className="flex items-center justify-center py-20">
                <Spinner />
              </div>
            ) : visibleGroups.length === 0 ? (
              <EmptyState message="No skills match the current filters." />
            ) : (
              <div className="flex flex-col gap-6">
                {visibleGroups.map((group) => (
                  <div key={group.key} className="flex flex-col gap-2">
                    <SettingsGroupLabel
                      label={group.label}
                      count={group.count}
                      icon={<span className="text-text-dim">{sourceIcon(group.bucket)}</span>}
                      action={group.bucket === "integration" ? <QuietPill label="integration package" /> : undefined}
                    />
                    <div className="flex flex-col gap-1.5">
                      {group.entries.map((entry) => (
                        <SkillRow
                          key={entry.skill.id}
                          entry={entry}
                          expanded={expanded}
                          onToggle={toggleExpanded}
                          onOpen={(id) => navigate(skillHref(id))}
                        />
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <InfoBanner variant="info" icon={<ScrollText size={13} />}>
            File and integration skills are inspect-first here. Bot-authored skill health and review activity stay in Memory & Knowledge.
          </InfoBanner>
        </div>
      </RefreshableScrollView>
    </div>
  );
}
