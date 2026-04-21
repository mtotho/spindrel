import { useMemo, useState } from "react";
import { BookOpen, Check, Search, Server, Wrench, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
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
  const t = useThemeTokens();
  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, padding: "14px 0 6px" }}>
      {icon}
      <span style={{ fontSize: 11, fontWeight: 700, color: t.textMuted, textTransform: "uppercase", letterSpacing: 0.8 }}>
        {label}
      </span>
      {count != null && (
        <span style={{ fontSize: 10, fontWeight: 600, color: t.textDim, background: t.surfaceOverlay, borderRadius: 4, padding: "0 6px" }}>
          {count}
        </span>
      )}
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

function ToolChip({ name }: { name: string }) {
  const t = useThemeTokens();
  return (
    <HoverPopover content={<ToolPreview data={{ name }} />}>
      <span
        style={{
          fontSize: 10,
          fontFamily: "monospace",
          padding: "1px 6px",
          borderRadius: 4,
          background: t.surfaceOverlay,
          color: t.textMuted,
          cursor: "help",
          borderBottom: `1px dashed ${t.textDim}40`,
        }}
      >
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
  const t = useThemeTokens();
  const nameEl = (
    <span style={{
      fontSize: 11,
      color: t.accent,
      fontWeight: 500,
      cursor: preview ? "help" : undefined,
      borderBottom: preview ? `1px dashed ${t.accent}40` : undefined,
    }}>
      {name}
    </span>
  );
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        padding: "4px 8px",
        borderRadius: 4,
        background: t.accentSubtle,
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        {preview ? <HoverPopover content={<SkillPreview data={preview} />}>{nameEl}</HoverPopover> : nameEl}
        <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace", marginLeft: 6 }}>{id}</span>
      </div>
      {badge && (
        <span style={{ fontSize: 9, fontWeight: 600, color: t.textDim, background: t.surfaceOverlay, borderRadius: 4, padding: "1px 6px" }}>
          {badge}
        </span>
      )}
      {removable && onRemove && (
        <button
          onClick={onRemove}
          title="Remove from this channel"
          style={{ display: "flex", border: "none", background: "transparent", cursor: "pointer", color: t.textDim, padding: 0 }}
        >
          <X size={11} />
        </button>
      )}
    </div>
  );
}

export function ToolsOverrideTab({ channelId, botId }: { channelId: string; botId?: string }) {
  const t = useThemeTokens();
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

      <SectionLabel icon={<BookOpen size={12} color={t.accent} />} label="Channel Skills" count={enrolled.length} />
      <div style={{ fontSize: 11, color: t.textDim, marginBottom: 8 }}>
        Channel-level skill enrollment augments the bot&apos;s normal working set for this channel only. Skills remain fetch-on-demand via <code style={{ fontSize: 10 }}>get_skill()</code>.
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
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
          <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic", padding: "4px 0" }}>
            No channel-specific skills enrolled.
          </div>
        )}
      </div>

      <SectionLabel icon={<Search size={12} color={t.textDim} />} label="Add Skills" count={addableSkills.length} />
      <div style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 6,
        background: t.inputBg,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 6,
        padding: "6px 10px",
        marginBottom: 8,
      }}>
        <Search size={13} color={t.textDim} />
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Filter skills..."
          style={{ flex: 1, background: "transparent", border: "none", outline: "none", color: t.text, fontSize: 12 }}
        />
        {search && (
          <button onClick={() => setSearch("")} style={{ background: "none", border: "none", cursor: "pointer", padding: 0 }}>
            <X size={10} color={t.textDim} />
          </button>
        )}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4, maxHeight: 240, overflow: "auto" }}>
        {addableSkills.slice(0, 80).map((skill) => (
          <button
            key={skill.id}
            onClick={() => enrollMut.mutate({ skillId: skill.id })}
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 6,
              width: "100%",
              textAlign: "left",
              padding: "6px 8px",
              borderRadius: 4,
              border: `1px solid ${t.surfaceBorder}`,
              background: t.surfaceRaised,
              cursor: "pointer",
              color: t.text,
            }}
          >
            <Check size={11} color={t.accent} />
            <span style={{ fontSize: 11, fontWeight: 500 }}>{skill.name}</span>
            <span style={{ fontSize: 9, color: t.textDim, fontFamily: "monospace" }}>{skill.id}</span>
          </button>
        ))}
        {addableSkills.length === 0 && (
          <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic", padding: "4px 0" }}>
            No matching skills available.
          </div>
        )}
      </div>

      <SectionLabel icon={<BookOpen size={12} color={t.accent} />} label="Resolved Skills" count={effective?.skills.length ?? 0} />
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
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

      <SectionLabel icon={<Wrench size={12} color={t.textDim} />} label="Resolved Tools" count={effective?.local_tools.length ?? 0} />
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
        {(effective?.local_tools ?? []).map((name) => <ToolChip key={name} name={name} />)}
      </div>

      <SectionLabel icon={<Server size={12} color={t.textDim} />} label="MCP Servers" count={effective?.mcp_servers.length ?? 0} />
      <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
        {(effective?.mcp_servers ?? []).map((name) => (
          <span key={name} style={{ fontSize: 10, fontFamily: "monospace", padding: "1px 6px", borderRadius: 4, background: t.surfaceOverlay, color: t.textMuted }}>
            {name}
          </span>
        ))}
      </div>
    </div>
  );
}
