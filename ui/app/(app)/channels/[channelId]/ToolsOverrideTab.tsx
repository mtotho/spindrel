import { useMemo, useState } from "react";
import { BookOpen, Check, Search, Server, Wrench, X } from "lucide-react";
import {
  useChannelEffectiveTools,
  useChannelEnrolledSkills,
  useEnrollChannelSkill,
  useUnenrollChannelSkill,
} from "@/src/api/hooks/useChannels";
import { useBotEditorData } from "@/src/api/hooks/useBots";
import { EmptyState } from "@/src/components/shared/FormControls";
import { HoverPopover, SkillPreview, ToolPreview } from "@/src/components/shared/ItemPreviewPopover";
import { ActivationsSection } from "./integrations/ActivationsSection";

function SectionLabel({ icon, label, count }: { icon: React.ReactNode; label: string; count?: number }) {
  return (
    <div className="flex items-center gap-1.5 pt-3.5 pb-1.5">
      {icon}
      <span className="text-[10px] font-semibold uppercase tracking-[0.08em] text-text-dim/70">
        {label}
      </span>
      {count != null && (
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[10px] font-semibold text-text-dim">
          {count}
        </span>
      )}
    </div>
  );
}

function ToolChip({ name }: { name: string }) {
  return (
    <HoverPopover content={<ToolPreview data={{ name }} />}>
      <span className="inline-flex cursor-help items-center rounded-full bg-surface-overlay px-2 py-0.5 font-mono text-[10px] text-text-muted">
        {name}
      </span>
    </HoverPopover>
  );
}

function SkillChip({
  id,
  name,
  removable,
  onRemove,
  preview,
  badge,
}: {
  id: string;
  name: string;
  removable?: boolean;
  onRemove?: () => void;
  preview?: { id: string; name: string; description?: string | null; source_type?: string };
  badge?: string;
}) {
  const nameEl = (
    <span
      className={`text-[11px] font-medium text-accent${preview ? " cursor-help" : ""}`}
    >
      {name}
    </span>
  );
  return (
    <div className="flex items-center gap-1.5 rounded-md bg-accent/[0.08] px-2 py-1">
      <div className="flex-1 min-w-0">
        {preview ? <HoverPopover content={<SkillPreview data={preview} />}>{nameEl}</HoverPopover> : nameEl}
        <span className="ml-1.5 font-mono text-[9px] text-text-dim">{id}</span>
      </div>
      {badge && (
        <span className="rounded-full bg-surface-overlay px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-[0.08em] text-text-dim">
          {badge}
        </span>
      )}
      {removable && onRemove && (
        <button
          type="button"
          onClick={onRemove}
          title="Remove from this channel"
          className="inline-flex items-center p-0 text-text-dim hover:text-text transition-colors"
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}

export function ToolsOverrideTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const { data: effective } = useChannelEffectiveTools(channelId);
  const { data: editorData, isLoading: editorLoading } = useBotEditorData(botId);
  const { data: enrolled = [] } = useChannelEnrolledSkills(channelId);
  const enrollMut = useEnrollChannelSkill(channelId);
  const unenrollMut = useUnenrollChannelSkill(channelId);
  const [search, setSearch] = useState("");

  const skillPreviewMap = useMemo(() => {
    const map = new Map<string, { id: string; name: string; description?: string | null; source_type?: string }>();
    for (const skill of editorData?.all_skills ?? []) {
      map.set(skill.id, skill);
    }
    return map;
  }, [editorData]);

  const enrolledIds = useMemo(() => new Set(enrolled.map((s) => s.skill_id)), [enrolled]);
  const addableSkills = useMemo(() => {
    const q = search.trim().toLowerCase();
    return (editorData?.all_skills ?? []).filter((skill) => {
      if (enrolledIds.has(skill.id)) return false;
      if (!q) return true;
      return (
        skill.id.toLowerCase().includes(q) ||
        skill.name.toLowerCase().includes(q) ||
        (skill.description || "").toLowerCase().includes(q)
      );
    });
  }, [editorData, enrolledIds, search]);

  if (editorLoading) {
    return <EmptyState message="Loading..." />;
  }
  if (!editorData) {
    return <EmptyState message="Loading..." />;
  }

  return (
    <div>
      <ActivationsSection channelId={channelId} />

      <SectionLabel icon={<BookOpen size={12} className="text-accent" />} label="Channel Skills" count={enrolled.length} />
      <p className="mb-2 text-[11px] text-text-dim leading-snug">
        Channel-level skill enrollment augments the bot&apos;s normal working set for this channel only. Skills remain fetch-on-demand via{" "}
        <code className="rounded bg-surface-overlay px-1 py-px font-mono text-[10px] text-text-muted">get_skill()</code>.
      </p>

      <div className="flex flex-col gap-1">
        {enrolled.map((skill) => (
          <SkillChip
            key={skill.skill_id}
            id={skill.skill_id}
            name={skill.name}
            removable
            onRemove={() => unenrollMut.mutate(skill.skill_id)}
            preview={skillPreviewMap.get(skill.skill_id)}
            badge="channel"
          />
        ))}
        {enrolled.length === 0 && (
          <div className="py-1 text-[11px] italic text-text-dim">
            No channel-specific skills enrolled.
          </div>
        )}
      </div>

      <SectionLabel icon={<Search size={12} className="text-text-dim" />} label="Add Skills" count={addableSkills.length} />
      <div className="mb-2 flex items-center gap-1.5 rounded-md border border-input-border bg-input px-3 py-1.5 focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/40 transition-colors">
        <Search size={13} className="text-text-dim shrink-0" />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter skills..."
          className="flex-1 bg-transparent text-[12px] text-text outline-none placeholder:text-text-dim"
        />
        {search && (
          <button
            type="button"
            onClick={() => setSearch("")}
            className="inline-flex items-center p-0 text-text-dim hover:text-text transition-colors"
          >
            <X size={10} />
          </button>
        )}
      </div>
      <div className="flex max-h-60 flex-col gap-1 overflow-auto">
        {addableSkills.slice(0, 80).map((skill) => (
          <button
            key={skill.id}
            type="button"
            onClick={() => enrollMut.mutate({ skillId: skill.id })}
            className="flex w-full items-center gap-1.5 rounded-md border border-surface-border bg-surface-raised px-2 py-1.5 text-left text-text hover:bg-surface-overlay/60 transition-colors"
          >
            <Check size={11} className="text-accent shrink-0" />
            <span className="text-[11px] font-medium">{skill.name}</span>
            <span className="font-mono text-[9px] text-text-dim">{skill.id}</span>
          </button>
        ))}
        {addableSkills.length === 0 && (
          <div className="py-1 text-[11px] italic text-text-dim">
            No matching skills available.
          </div>
        )}
      </div>

      <SectionLabel icon={<BookOpen size={12} className="text-accent" />} label="Resolved Skills" count={effective?.skills.length ?? 0} />
      <div className="flex flex-col gap-1">
        {(effective?.skills ?? []).map((skill) => (
          <SkillChip
            key={skill.id}
            id={skill.id}
            name={skill.name || skill.id}
            preview={skillPreviewMap.get(skill.id)}
            badge={enrolledIds.has(skill.id) ? "channel" : "bot"}
          />
        ))}
      </div>

      <SectionLabel icon={<Wrench size={12} className="text-text-dim" />} label="Resolved Tools" count={effective?.local_tools.length ?? 0} />
      <div className="flex flex-wrap gap-1">
        {(effective?.local_tools ?? []).map((name) => <ToolChip key={name} name={name} />)}
      </div>

      <SectionLabel icon={<Server size={12} className="text-text-dim" />} label="MCP Servers" count={effective?.mcp_servers.length ?? 0} />
      <div className="flex flex-wrap gap-1">
        {(effective?.mcp_servers ?? []).map((name) => (
          <span
            key={name}
            className="inline-flex items-center rounded-full bg-surface-overlay px-2 py-0.5 font-mono text-[10px] text-text-muted"
          >
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
