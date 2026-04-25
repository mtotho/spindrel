import { useMemo, useState } from "react";
import { AlertTriangle, BookOpen, Clock, Flame, Search, Sparkles, TrendingUp, Zap } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useSkills, type SkillItem } from "@/src/api/hooks/useSkills";
import {
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

export function parseFrontmatter(content: string): { category?: string; triggers?: string[] } {
  const match = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!match) return {};
  const lines = match[1].split(/\r?\n/);
  let category: string | undefined;
  let triggers: string[] | undefined;

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
    const categoryMatch = line.match(/^category:\s*(.+)/);
    if (categoryMatch) category = categoryMatch[1].trim().replace(/^["']|["']$/g, "");

    const inlineTriggers = line.match(/^triggers:\s*\[(.+)]/);
    if (inlineTriggers) {
      triggers = inlineTriggers[1].split(",").map((value) => value.trim().replace(/^["']|["']$/g, "")).filter(Boolean);
      continue;
    }

    if (/^triggers:\s*$/.test(line)) {
      triggers = [];
      for (let next = index + 1; next < lines.length; next += 1) {
        const itemMatch = lines[next].match(/^\s+-\s+(.+)/);
        if (!itemMatch) break;
        triggers.push(itemMatch[1].trim().replace(/^["']|["']$/g, ""));
      }
    }
  }
  return { category, triggers };
}

export function fmtRelative(value: string | null | undefined): string {
  if (!value) return "never";
  const diffMs = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(diffMs)) return "unknown";
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(value).toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

export type Health = "new" | "hot" | "stale" | "dormant" | null;

export function getHealth(skill: SkillItem): Health {
  const ageDays = (Date.now() - new Date(skill.created_at).getTime()) / 86_400_000;
  const totalActivity = skill.surface_count + (skill.total_auto_injects ?? 0);

  if (totalActivity >= 10) return "hot";
  if (totalActivity === 0 && ageDays < 1) return "new";
  if (totalActivity === 0 && ageDays > 7) return "stale";
  if (totalActivity > 0 && skill.last_surfaced_at) {
    const lastDays = (Date.now() - new Date(skill.last_surfaced_at).getTime()) / 86_400_000;
    if (lastDays > 30) return "dormant";
  }
  return null;
}

export function HealthBadge({ health }: { health: Health }) {
  if (!health) return null;
  const variant = health === "hot" ? "danger" : health === "stale" ? "warning" : health === "new" ? "info" : "neutral";
  return <StatusBadge label={health} variant={variant} />;
}

type SortKey = "recent" | "name" | "surfacings" | "injects";

function normalizedSearchText(skill: SkillItem & { category?: string | null; triggers?: string[] }) {
  return [
    skill.name,
    skill.id,
    skill.category,
    ...(skill.triggers ?? []),
  ].filter(Boolean).join(" ").toLowerCase();
}

export function LearningSection({ botId }: { botId: string }) {
  const navigate = useNavigate();
  const { data: skills, isLoading } = useSkills({ bot_id: botId, source_type: "tool", sort: "recent" });
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("recent");

  const parsed = useMemo(() => {
    return (skills ?? []).map((skill) => ({ ...skill, ...parseFrontmatter(skill.content), health: getHealth(skill) }));
  }, [skills]);

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    const list = needle
      ? parsed.filter((skill) => normalizedSearchText(skill).includes(needle))
      : parsed;

    return [...list].sort((a, b) => {
      if (sortKey === "name") return a.name.localeCompare(b.name);
      if (sortKey === "surfacings") return b.surface_count - a.surface_count;
      if (sortKey === "injects") return (b.total_auto_injects ?? 0) - (a.total_auto_injects ?? 0);
      return new Date(b.created_at).getTime() - new Date(a.created_at).getTime();
    });
  }, [parsed, query, sortKey]);

  const totalSkills = parsed.length;
  const totalSurfacings = parsed.reduce((total, skill) => total + skill.surface_count, 0);
  const totalAutoInjects = parsed.reduce((total, skill) => total + (skill.total_auto_injects ?? 0), 0);
  const activeSkills = parsed.filter((skill) => skill.surface_count > 0 || (skill.total_auto_injects ?? 0) > 0).length;
  const neverSurfaced = parsed.filter((skill) => skill.surface_count === 0 && (skill.total_auto_injects ?? 0) === 0).length;
  const dormantSkills = parsed.filter((skill) => skill.health === "dormant").length;

  if (isLoading) {
    return (
      <div className="flex flex-col gap-2">
        {[0, 1, 2].map((item) => (
          <div key={item} className="h-16 rounded-md bg-surface-raised/40" />
        ))}
      </div>
    );
  }

  if (totalSkills === 0) {
    return (
      <EmptyState
        message="This bot has not authored any skills yet. Bot-authored skills appear here after the bot uses the skill management tool."
      />
    );
  }

  return (
    <div className="flex flex-col gap-5">
      <SettingsStatGrid
        items={[
          { label: "Skills", value: totalSkills, tone: "accent" },
          { label: "Active", value: activeSkills, tone: activeSkills ? "success" : "default" },
          { label: "Surfacings", value: totalSurfacings },
          { label: "Auto injects", value: totalAutoInjects },
        ]}
      />

      {(neverSurfaced > 0 || dormantSkills > 0) && (
        <InfoBanner variant={neverSurfaced > 0 ? "warning" : "info"} icon={<AlertTriangle size={14} />}>
          {neverSurfaced > 0
            ? `${neverSurfaced} bot-authored skill${neverSurfaced === 1 ? "" : "s"} have never surfaced. Review triggers or archive stale experiments.`
            : `${dormantSkills} skill${dormantSkills === 1 ? "" : "s"} surfaced before but not in the last 30 days.`}
        </InfoBanner>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <SettingsSearchBox
          value={query}
          onChange={setQuery}
          placeholder="Filter bot-authored skills..."
          className="min-w-[220px] flex-1"
        />
        <SettingsSegmentedControl
          value={sortKey}
          onChange={setSortKey}
          options={[
            { value: "recent", label: "Recent" },
            { value: "name", label: "Name" },
            { value: "surfacings", label: "Surfaced" },
            { value: "injects", label: "Injected" },
          ]}
        />
      </div>

      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Bot-authored skills" count={filtered.length} icon={<Sparkles size={12} className="text-text-dim" />} />
        {filtered.length === 0 ? (
          <EmptyState message="No skills match the current filter." />
        ) : (
          filtered.map((skill) => {
            const triggerPreview = skill.triggers?.length ? skill.triggers.slice(0, 3).join(", ") : "No triggers in front matter";
            return (
              <SettingsControlRow
                key={skill.id}
                leading={skill.health === "hot" ? <Flame size={14} /> : <BookOpen size={14} />}
                title={
                  <span className="flex min-w-0 items-center gap-2">
                    <span className="truncate">{skill.name}</span>
                    <HealthBadge health={skill.health} />
                  </span>
                }
                description={
                  <span className="line-clamp-2">
                    {triggerPreview}
                  </span>
                }
                meta={
                  <div className="flex flex-wrap gap-1.5">
                    {skill.category && <QuietPill label={skill.category} maxWidthClass="max-w-[120px]" />}
                    <QuietPill label={`created ${fmtRelative(skill.created_at)}`} />
                    <QuietPill label={`last ${fmtRelative(skill.last_surfaced_at)}`} />
                  </div>
                }
                action={
                  <div className="flex flex-wrap items-center justify-end gap-2 text-[11px] text-text-dim">
                    <span className="inline-flex items-center gap-1 tabular-nums"><TrendingUp size={11} />{skill.surface_count}</span>
                    <span className="inline-flex items-center gap-1 tabular-nums"><Zap size={11} />{skill.total_auto_injects ?? 0}</span>
                    <span className="inline-flex items-center gap-1 tabular-nums"><Clock size={11} />{fmtRelative(skill.last_surfaced_at)}</span>
                  </div>
                }
                onClick={() => navigate(`/admin/skills/${encodeURIComponent(skill.id)}`)}
              />
            );
          })
        )}
      </div>

      <InfoBanner icon={<Search size={14} />}>
        This list is bot-scoped. The global Skills page remains the catalog for file and integration skills.
      </InfoBanner>
    </div>
  );
}
