import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { BookOpen, Sparkles } from "lucide-react";
import { useSkills } from "@/src/api/hooks/useSkills";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { parseFrontmatter } from "@/app/(app)/admin/bots/[botId]/LearningSection";
import { Section } from "@/src/components/shared/FormControls";
import {
  EmptyState,
  QuietPill,
  SettingsControlRow,
  SettingsSearchBox,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

function fmtRelative(value?: string | null) {
  if (!value) return "never";
  const diff = Date.now() - new Date(value).getTime();
  if (!Number.isFinite(diff)) return "unknown";
  const mins = Math.round(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.round(mins / 60);
  if (hours < 48) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export function SkillsTab({ days }: { days: number }) {
  const navigate = useNavigate();
  const { data: skills, isLoading } = useSkills({ source_type: "tool", sort: "recent", days });
  const { data: bots } = useAdminBots();
  const [filter, setFilter] = useState("");

  const botNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    if (bots) for (const bot of bots) map[bot.id] = bot.name;
    return map;
  }, [bots]);

  const parsed = useMemo(() => {
    return (skills ?? []).map((skill) => {
      const frontmatter = parseFrontmatter(skill.content);
      return {
        ...skill,
        ...frontmatter,
        bot_name: skill.bot_id ? botNameMap[skill.bot_id] ?? skill.bot_id : "unknown bot",
        total_activity: skill.surface_count + (skill.total_auto_injects ?? 0),
      };
    });
  }, [skills, botNameMap]);

  const visible = useMemo(() => {
    const term = filter.trim().toLowerCase();
    if (!term) return parsed;
    return parsed.filter((skill) =>
      `${skill.name} ${skill.description ?? ""} ${skill.category ?? ""} ${skill.bot_name}`.toLowerCase().includes(term),
    );
  }, [parsed, filter]);

  const totalSurfacings = parsed.reduce((sum, skill) => sum + skill.surface_count, 0);
  const totalInjects = parsed.reduce((sum, skill) => sum + (skill.total_auto_injects ?? 0), 0);
  const activeSkills = parsed.filter((skill) => skill.total_activity > 0).length;
  const unusedSkills = parsed.length - activeSkills;

  return (
    <div className="flex flex-col gap-7">
      <Section title="Bot-Authored Skills" description="Skills created by bots via manage_bot_skill. This tab is for inspection and review, not direct editing.">
        {isLoading ? (
          <div className="grid gap-2 md:grid-cols-4">
            {[0, 1, 2, 3].map((item) => <div key={item} className="h-14 rounded-md bg-surface-raised/35" />)}
          </div>
        ) : (
          <SettingsStatGrid
            items={[
              { label: "Skills", value: parsed.length },
              { label: "Surfacings", value: totalSurfacings, tone: totalSurfacings ? "warning" : "default" },
              { label: "Auto-injects", value: totalInjects, tone: totalInjects ? "accent" : "default" },
              { label: "Unused", value: unusedSkills, tone: unusedSkills ? "warning" : "success" },
            ]}
          />
        )}
      </Section>

      <Section title="Skill Catalog" description="Quiet rows keep trigger quality, bot ownership, and activity scannable.">
        <div className="flex flex-col gap-3">
          <SettingsSearchBox value={filter} onChange={setFilter} placeholder="Filter skills..." className="max-w-xl" />
          {isLoading ? (
            <div className="flex flex-col gap-2">
              {[0, 1, 2].map((item) => <div key={item} className="h-14 rounded-md bg-surface-raised/35" />)}
            </div>
          ) : visible.length === 0 ? (
            <EmptyState message="No bot-authored skills match this filter." />
          ) : (
            <div className="flex flex-col gap-1.5">
              {visible.map((skill) => (
                <SettingsControlRow
                  key={skill.id}
                  onClick={() => navigate(`/admin/skills/${encodeURIComponent(skill.id)}`)}
                  leading={<Sparkles size={14} />}
                  title={
                    <span className="flex min-w-0 items-center gap-2">
                      <span className="truncate">{skill.name}</span>
                      {skill.total_activity > 0 ? (
                        <StatusBadge label="active" variant="info" />
                      ) : (
                        <StatusBadge label="unused" variant="neutral" />
                      )}
                    </span>
                  }
                  description={skill.description || `Created ${fmtRelative(skill.created_at)} by ${skill.bot_name}`}
                  meta={
                    <span className="inline-flex items-center gap-1.5">
                      <QuietPill label={skill.bot_name} maxWidthClass="max-w-[140px]" />
                      {skill.category && <QuietPill label={skill.category} maxWidthClass="max-w-[120px]" />}
                      <span>{skill.surface_count} uses</span>
                      <span>{skill.total_auto_injects ?? 0} injects</span>
                      <span>{fmtRelative(skill.last_surfaced_at)}</span>
                    </span>
                  }
                />
              ))}
            </div>
          )}
        </div>
      </Section>

      {parsed.length === 0 && !isLoading && (
        <EmptyState message="Skills appear here after bots save reusable procedures with manage_bot_skill." />
      )}

      <Section title="Review Guidance" description="Skill review jobs should improve triggers, prune stale procedures, and keep auto-inject behavior intentional.">
        <SettingsControlRow
          leading={<BookOpen size={14} />}
          title="Use Dreaming / Skill Review to make catalog changes"
          description="This page shows the catalog and activity. The safe mutating path is still the existing background skill-review job."
        />
      </Section>
    </div>
  );
}
