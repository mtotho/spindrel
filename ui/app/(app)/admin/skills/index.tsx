
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import {
  Plus, RefreshCw, AlertTriangle, Search, TrendingUp, Zap,
  Trash2, Users, X, ChevronDown, Bot, Puzzle, FileText, Wrench,
} from "lucide-react";
import { useSkills, useFileSync, useDeleteSkill, type SkillItem, type FileSyncResult } from "@/src/api/hooks/useSkills";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useState, useMemo, useRef, useEffect } from "react";

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */

/** Strip markdown cruft from the first meaningful line of skill content */
function extractDescription(skill: SkillItem): string {
  if (skill.description) return skill.description;
  const lines = (skill.content || "").split("\n");
  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;
    if (line.startsWith("---")) continue;       // frontmatter fence
    if (line.startsWith("name:")) continue;      // frontmatter field
    if (/^#+\s/.test(line)) continue;            // heading
    return line.replace(/^[#*>-]+\s*/, "");      // strip any leading markdown chars
  }
  return "";
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
}

function fmtRelative(iso: string | null | undefined): string {
  if (!iso) return "never";
  const d = new Date(iso);
  const diffMs = Date.now() - d.getTime();
  const mins = Math.floor(diffMs / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  if (days < 7) return `${days}d ago`;
  return fmtDate(iso);
}

function fmtShortDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short", day: "numeric",
  });
}

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

/* ------------------------------------------------------------------ */
/*  Filter dropdown                                                    */
/* ------------------------------------------------------------------ */

type FilterValue =
  | null                                    // show all
  | { kind: "source"; value: string }       // source_type filter
  | { kind: "bot"; value: string }          // specific bot
  | { kind: "integration"; value: string }; // specific integration

function FilterDropdown({
  skills,
  value,
  onChange,
}: {
  skills: SkillItem[];
  value: FilterValue;
  onChange: (v: FilterValue) => void;
}) {
  const t = useThemeTokens();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  // Close on outside click
  useEffect(() => {
    if (!open) return;
    const handler = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [open]);

  // Build menu items from data
  const menu = useMemo(() => {
    const items: { key: string; label: string; icon: typeof Bot; count: number; filter: FilterValue; color: string; indent?: boolean }[] = [];
    const counts = { tool: 0, file: 0, manual: 0, integration: 0 };
    const botCounts = new Map<string, number>();
    const intCounts = new Map<string, number>();

    for (const s of skills) {
      if (s.source_type === "tool") {
        counts.tool++;
        if (s.bot_id) botCounts.set(s.bot_id, (botCounts.get(s.bot_id) || 0) + 1);
      } else if (s.source_type === "file") counts.file++;
      else if (s.source_type === "manual") counts.manual++;
      else if (s.source_type === "integration") {
        counts.integration++;
        const name = s.id.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
        intCounts.set(name, (intCounts.get(name) || 0) + 1);
      }
    }

    if (counts.tool > 0) {
      items.push({ key: "s:tool", label: "Bot-authored", icon: Bot, count: counts.tool, filter: { kind: "source", value: "tool" }, color: "#059669" });
      // Sub-items for each bot
      for (const [bid, n] of [...botCounts.entries()].sort((a, b) => b[1] - a[1])) {
        items.push({ key: `b:${bid}`, label: bid, icon: Bot, count: n, filter: { kind: "bot", value: bid }, color: "#059669", indent: true });
      }
    }
    if (counts.file > 0)
      items.push({ key: "s:file", label: "Core", icon: FileText, count: counts.file, filter: { kind: "source", value: "file" }, color: t.accent });
    if (counts.manual > 0)
      items.push({ key: "s:manual", label: "User added", icon: Wrench, count: counts.manual, filter: { kind: "source", value: "manual" }, color: t.textMuted });
    if (counts.integration > 0) {
      items.push({ key: "s:integration", label: "Integrations", icon: Puzzle, count: counts.integration, filter: { kind: "source", value: "integration" }, color: "#ea580c" });
      for (const [name, n] of [...intCounts.entries()].sort()) {
        items.push({ key: `i:${name}`, label: fmtIntName(name), icon: Puzzle, count: n, filter: { kind: "integration", value: name }, color: "#ea580c", indent: true });
      }
    }

    return items;
  }, [skills, t.accent, t.textMuted]);

  // Active label
  const activeLabel = value
    ? menu.find((m) => m.filter && JSON.stringify(m.filter) === JSON.stringify(value))?.label || "Filtered"
    : "All sources";

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        onClick={() => setOpen(!open)}
        style={{
          display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 5,
          padding: "5px 10px", borderRadius: 6, fontSize: 12,
          border: `1px solid ${value ? t.accentBorder : t.surfaceBorder}`,
          background: value ? t.accentSubtle : "transparent",
          color: value ? t.accent : t.textMuted,
          cursor: "pointer", fontWeight: value ? 600 : 400,
          whiteSpace: "nowrap",
        }}
      >
        {activeLabel}
        <ChevronDown size={12} />
      </button>

      {value && (
        <button
          onClick={(e) => { e.stopPropagation(); onChange(null); }}
          style={{
            position: "absolute", top: -4, right: -4,
            width: 16, height: 16, borderRadius: 8,
            display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
            background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
            cursor: "pointer", color: t.textDim, padding: 0,
          }}
        >
          <X size={8} />
        </button>
      )}

      {open && (
        <div style={{
          position: "absolute", top: "calc(100% + 4px)", left: 0,
          minWidth: 220, maxHeight: 360, overflowY: "auto",
          background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 8, boxShadow: "0 8px 24px rgba(0,0,0,0.25)",
          zIndex: 100, padding: "4px 0",
        }}>
          {/* "All" option */}
          <button
            onClick={() => { onChange(null); setOpen(false); }}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 8, width: "100%",
              padding: "7px 12px", background: !value ? t.surfaceOverlay : "transparent",
              border: "none", cursor: "pointer", color: t.text, fontSize: 12,
              textAlign: "left", fontWeight: !value ? 600 : 400,
            }}
            onMouseEnter={(e) => { if (value) e.currentTarget.style.background = t.inputBg; }}
            onMouseLeave={(e) => { if (value) e.currentTarget.style.background = "transparent"; }}
          >
            All sources
            <span style={{ marginLeft: "auto", fontSize: 10, color: t.textDim }}>{skills.length}</span>
          </button>

          <div style={{ height: 1, background: t.surfaceBorder, margin: "4px 0" }} />

          {menu.map((item) => {
            const isActive = value && JSON.stringify(value) === JSON.stringify(item.filter);
            const Icon = item.icon;
            return (
              <button
                key={item.key}
                onClick={() => { onChange(item.filter); setOpen(false); }}
                style={{
                  display: "flex", flexDirection: "row", alignItems: "center", gap: 8, width: "100%",
                  padding: `6px 12px 6px ${item.indent ? 28 : 12}px`,
                  background: isActive ? t.surfaceOverlay : "transparent",
                  border: "none", cursor: "pointer",
                  color: isActive ? t.text : t.textMuted,
                  fontSize: item.indent ? 11 : 12,
                  textAlign: "left", fontWeight: isActive ? 600 : 400,
                }}
                onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = t.inputBg; }}
                onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = "transparent"; }}
              >
                {!item.indent && <Icon size={13} color={item.color} />}
                <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{item.label}</span>
                <span style={{ fontSize: 10, color: t.textDim, flexShrink: 0 }}>{item.count}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Badges                                                             */
/* ------------------------------------------------------------------ */

function CategoryBadge({ category }: { category: string }) {
  const t = useThemeTokens();
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3, fontSize: 10, fontWeight: 500,
      background: t.surfaceOverlay, color: t.textMuted,
    }}>
      {category}
    </span>
  );
}

function SourceBadge({ type, detail }: { type: string; detail?: string }) {
  const t = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: t.accentSubtle, fg: t.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: t.surfaceOverlay, fg: t.textMuted, label: "manual" },
    tool: { bg: "rgba(16,185,129,0.15)", fg: "#059669", label: "bot-authored" },
  };
  const c = cfg[type] || cfg.manual;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}
      title={detail || undefined}
    >
      {c.label}
    </span>
  );
}

/* ------------------------------------------------------------------ */
/*  Render item types                                                  */
/* ------------------------------------------------------------------ */

type RenderItem =
  | { type: "header"; key: string; label: string; count: number; icon?: typeof Bot; color?: string }
  | { type: "subheader"; key: string; label: string; count: number }
  | { type: "bot-group"; key: string; botId: string; skills: SkillItem[] }
  | { type: "skill"; key: string; skill: SkillItem };

/* ------------------------------------------------------------------ */
/*  Section header — prominent, with icon + count badge                */
/* ------------------------------------------------------------------ */

function SectionHeader({ label, count, level, isWide, icon: Icon, color }: {
  label: string; count: number; level: number; isWide: boolean;
  icon?: typeof Bot; color?: string;
}) {
  const t = useThemeTokens();
  const isSubheader = level > 0;
  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
      padding: isWide
        ? `${isSubheader ? 10 : 20}px 16px ${isSubheader ? 6 : 8}px ${isSubheader ? 32 : 16}px`
        : `${isSubheader ? 10 : 20}px 0 ${isSubheader ? 6 : 8}px ${isSubheader ? 16 : 0}px`,
    }}>
      {!isSubheader && Icon && (
        <Icon size={14} color={color || t.textMuted} />
      )}
      <span style={{
        fontSize: isSubheader ? 11 : 12,
        fontWeight: 700,
        color: isSubheader ? t.textDim : t.text,
        textTransform: "uppercase",
        letterSpacing: isSubheader ? 1 : 0.8,
      }}>
        {label}
      </span>
      <span style={{
        fontSize: 10, fontWeight: 600,
        color: color || t.textDim,
        background: isSubheader ? "transparent" : (color ? `${color}15` : t.surfaceOverlay),
        padding: isSubheader ? 0 : "1px 6px",
        borderRadius: 3,
      }}>
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Bot-authored skill card — with visual hierarchy                    */
/* ------------------------------------------------------------------ */

function SkillCard({
  skill,
  onClick,
  onDelete,
}: {
  skill: SkillItem;
  onClick: () => void;
  onDelete: () => void;
}) {
  const t = useThemeTokens();
  const [hovered, setHovered] = useState(false);
  const description = extractDescription(skill);
  const hasActivity = skill.surface_count > 0 || skill.total_auto_injects > 0;
  const isHot = skill.surface_count >= 10;

  return (
    <button
      onClick={onClick}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      style={{
        display: "flex", flexDirection: "column",
        padding: 0, overflow: "hidden",
        background: t.surfaceRaised,
        borderRadius: 8,
        border: `1px solid ${hovered ? t.accentBorder : t.surfaceBorder}`,
        cursor: "pointer", textAlign: "left",
        width: "100%",
        position: "relative",
        transition: "border-color 0.15s, box-shadow 0.15s",
        boxShadow: hovered ? "0 2px 8px rgba(0,0,0,0.15)" : "none",
      }}
    >
      {/* Activity indicator — thin bar at top */}
      <div style={{
        height: 2,
        background: isHot ? "#059669" : hasActivity ? t.accentBorder : t.surfaceBorder,
        transition: "background 0.2s",
      }} />

      <div style={{ padding: "12px 14px 10px", display: "flex", flexDirection: "column", gap: 4 }}>
        {/* Delete button — hover only */}
        {hovered && (
          <button
            onClick={(e) => { e.stopPropagation(); onDelete(); }}
            title="Delete skill permanently"
            style={{
              position: "absolute", top: 8, right: 8,
              display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
              width: 22, height: 22, borderRadius: 4,
              background: t.dangerSubtle, border: `1px solid ${t.dangerBorder}`,
              cursor: "pointer", color: t.danger, padding: 0,
            }}
          >
            <Trash2 size={11} />
          </button>
        )}

        {/* Name */}
        <div style={{
          fontSize: 13, fontWeight: 600, color: t.text, lineHeight: 1.3,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          paddingRight: hovered ? 26 : 0,
        }}>
          {skill.name}
        </div>

        {/* Category badge */}
        {skill.category && (
          <div>
            <CategoryBadge category={skill.category} />
          </div>
        )}

        {/* Description */}
        {description && (
          <div style={{
            fontSize: 11, color: t.textDim, lineHeight: 1.4,
            overflow: "hidden", textOverflow: "ellipsis",
            display: "-webkit-box", WebkitLineClamp: 2, WebkitBoxOrient: "vertical",
          }}>
            {description}
          </div>
        )}

        {/* Footer — activity + enrollment + date */}
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          marginTop: 4, paddingTop: 6,
          borderTop: `1px solid ${t.surfaceBorder}`,
          fontSize: 10, color: t.textDim,
        }}>
          {hasActivity ? (
            <span style={{
              display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
              color: isHot ? "#059669" : t.textMuted,
            }}>
              {isHot && <TrendingUp size={10} />}
              {skill.surface_count}x surfaced
              {skill.total_auto_injects > 0 && (
                <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 2, color: "#a855f7" }}>
                  <Zap size={9} /> {skill.total_auto_injects}
                </span>
              )}
            </span>
          ) : (
            <span>unused</span>
          )}
          <span style={{ color: t.surfaceBorder }}>·</span>
          {skill.enrolled_bot_count > 0 ? (
            <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 2 }}>
              <Users size={9} /> {skill.enrolled_bot_count}
            </span>
          ) : (
            <span>no bots</span>
          )}
          <span style={{ flex: 1 }} />
          <span>{fmtShortDate(skill.updated_at)}</span>
        </div>
      </div>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Bot group — labeled card grid for one bot's authored skills        */
/* ------------------------------------------------------------------ */

function BotGroupSection({
  botId,
  skills,
  isWide,
  onSkillPress,
  onSkillDelete,
}: {
  botId: string;
  skills: SkillItem[];
  isWide: boolean;
  onSkillPress: (id: string) => void;
  onSkillDelete: (skill: SkillItem) => void;
}) {
  const t = useThemeTokens();
  // Summary stats for the bot
  const totalSurfaced = skills.reduce((n, s) => n + s.surface_count, 0);

  return (
    <div style={{ padding: isWide ? "0 16px" : 0 }}>
      {/* Bot sub-header */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
        padding: "10px 0 8px",
      }}>
        <Bot size={13} color="#059669" />
        <span style={{ fontSize: 12, fontWeight: 700, color: "#059669" }}>
          {botId}
        </span>
        <span style={{ fontSize: 10, color: t.textDim }}>
          {skills.length} skill{skills.length !== 1 ? "s" : ""}
        </span>
        {totalSurfaced > 0 && (
          <span style={{ fontSize: 10, color: t.textDim }}>
            · {totalSurfaced} total surfacings
          </span>
        )}
        <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
      </div>

      {/* Card grid */}
      <div style={{
        display: "grid",
        gridTemplateColumns: isWide ? "repeat(auto-fill, minmax(260px, 1fr))" : "1fr",
        gap: 8,
        paddingBottom: 12,
      }}>
        {skills.map((skill) => (
          <SkillCard
            key={skill.id}
            skill={skill}
            onClick={() => onSkillPress(skill.id)}
            onDelete={() => onSkillDelete(skill)}
          />
        ))}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Table row for non-bot-authored skills                              */
/* ------------------------------------------------------------------ */

function SkillRow({ skill, onClick, isWide }: { skill: SkillItem; onClick: () => void; isWide: boolean }) {
  const t = useThemeTokens();
  const isBotAuthored = skill.source_type === "tool";
  const wsDetail = isBotAuthored && skill.bot_id
    ? `authored by ${skill.bot_id}`
    : undefined;
  const description = extractDescription(skill);

  if (!isWide) {
    // Mobile: card layout
    return (
      <button
        onClick={onClick}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: t.surfaceRaised, borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`, cursor: "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {skill.name}
          </span>
          {skill.category && <CategoryBadge category={skill.category} />}
          <SourceBadge type={skill.source_type} detail={wsDetail} />
        </div>
        {description && (
          <div style={{ fontSize: 11, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {description}
          </div>
        )}
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, fontSize: 10, color: t.textDim }}>
          {skill.enrolled_bot_count > 0 && (
            <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 2 }}>
              <Users size={9} /> {skill.enrolled_bot_count}
            </span>
          )}
          {skill.surface_count > 0 && (
            <span>{skill.surface_count}x surfaced</span>
          )}
          <span style={{ flex: 1 }} />
          <span>{fmtShortDate(skill.updated_at)}</span>
        </div>
      </button>
    );
  }

  // Desktop: table row
  return (
    <button
      onClick={onClick}
      style={{
        display: "grid", gridTemplateColumns: "1fr 90px 60px 80px 100px",
        alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        border: "none",
        borderBottom: `1px solid ${t.surfaceBorder}`,
        cursor: "pointer",
        textAlign: "left", width: "100%",
      }}
      onMouseEnter={(e) => { e.currentTarget.style.background = t.inputBg; }}
      onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
    >
      {/* Name + description */}
      <div style={{ overflow: "hidden" }}>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6, overflow: "hidden" }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {skill.name}
          </span>
          {skill.category && <CategoryBadge category={skill.category} />}
        </div>
        {description && (
          <div style={{ fontSize: 11, color: t.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>
            {description}
          </div>
        )}
      </div>
      <SourceBadge type={skill.source_type} detail={wsDetail} />
      {/* Enrolled */}
      <span style={{ textAlign: "right", fontSize: 10, color: skill.enrolled_bot_count > 0 ? t.textMuted : t.textDim }}>
        {skill.enrolled_bot_count > 0 ? (
          <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 2, justifyContent: "flex-end" }}>
            <Users size={10} /> {skill.enrolled_bot_count}
          </span>
        ) : "--"}
      </span>
      {/* Activity */}
      <span style={{ textAlign: "right" }}>
        {skill.surface_count > 0 ? (
          <span style={{
            display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
            fontSize: 10, color: skill.surface_count >= 10 ? "#059669" : t.textMuted,
          }}
            title={`Surfaced ${skill.surface_count}x, auto-injected ${skill.total_auto_injects}x`}
          >
            {skill.surface_count >= 10 && <TrendingUp size={10} />}
            {skill.surface_count}
            {skill.total_auto_injects > 0 && (
              <>
                <span style={{ color: t.textDim }}>·</span>
                <Zap size={9} color="#a855f7" />
                <span style={{ color: "#a855f7" }}>{skill.total_auto_injects}</span>
              </>
            )}
          </span>
        ) : (
          <span style={{ fontSize: 10, color: t.textDim }}>--</span>
        )}
      </span>
      <span style={{ fontSize: 11, color: t.textDim, textAlign: "right" }}>{fmtDate(skill.updated_at)}</span>
    </button>
  );
}

/* ------------------------------------------------------------------ */
/*  Sync result banner                                                 */
/* ------------------------------------------------------------------ */

function SyncResultBanner({ result, onDismiss }: { result: FileSyncResult; onDismiss: () => void }) {
  const t = useThemeTokens();
  const hasErrors = result.errors && result.errors.length > 0;
  const bg = hasErrors ? t.dangerSubtle : t.successSubtle;
  const border = hasErrors ? t.dangerBorder : t.successBorder;
  const color = hasErrors ? t.danger : t.success;
  return (
    <div style={{
      padding: "10px 16px", background: bg, border: `1px solid ${border}`,
      margin: "8px 12px 0", borderRadius: 8, fontSize: 12, color, lineHeight: 1.6,
    }}>
      <div style={{ display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div>
          <strong>Sync complete:</strong> +{result.added} added, ~{result.updated} updated,
          {" "}{result.unchanged} unchanged, -{result.deleted} deleted
          {result._diagnostics && (
            <div style={{ fontSize: 11, color: t.textMuted, marginTop: 4 }}>
              {result._diagnostics.files_on_disk.length} files found on disk
              {" "}(cwd: <code>{result._diagnostics.cwd}</code>)
            </div>
          )}
          {hasErrors && result.errors.map((e, i) => (
            <div key={i} style={{ color: t.danger, marginTop: 4, display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
              <AlertTriangle size={12} /> {e}
            </div>
          ))}
        </div>
        <button onClick={onDismiss} style={{
          background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 16, padding: "0 4px",
        }}>&times;</button>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Main screen                                                        */
/* ------------------------------------------------------------------ */

export default function SkillsScreen() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: skills, isLoading } = useSkills();
  const syncMut = useFileSync();
  const deleteMut = useDeleteSkill();
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [syncResult, setSyncResult] = useState<FileSyncResult | null>(null);
  const [syncError, setSyncError] = useState<string | null>(null);
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<FilterValue>(null);

  const filteredSkills = useMemo(() => {
    if (!skills) return [];
    let result = skills;

    // Apply dropdown filter
    if (filter) {
      result = result.filter((s) => {
        switch (filter.kind) {
          case "source":
            return s.source_type === filter.value;
          case "bot":
            return s.bot_id === filter.value;
          case "integration":
            return s.source_type === "integration" &&
              s.id.match(/^integrations\/([^/]+)\//)?.[1] === filter.value;
          default:
            return true;
        }
      });
    }

    // Apply text search
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (s) =>
          s.name.toLowerCase().includes(q) ||
          s.id.toLowerCase().includes(q) ||
          (s.description || "").toLowerCase().includes(q) ||
          (s.category || "").toLowerCase().includes(q) ||
          (s.triggers || []).some((tr) => tr.toLowerCase().includes(q)),
      );
    }

    return result;
  }, [skills, search, filter]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filteredSkills.length) return [];

    const manual: SkillItem[] = [];
    const botAuthored: SkillItem[] = [];
    const core: SkillItem[] = [];
    const integrationMap = new Map<string, SkillItem[]>();

    for (const s of filteredSkills) {
      if (s.source_type === "tool") botAuthored.push(s);
      else if (s.source_type === "manual") manual.push(s);
      else if (s.source_type === "integration") {
        const name = s.id.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
        const list = integrationMap.get(name);
        if (list) list.push(s); else integrationMap.set(name, [s]);
      } else core.push(s);
    }

    // Sort bot-authored by most recent first
    botAuthored.sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime());

    const items: RenderItem[] = [];

    // Bot-authored: group by bot_id, render as card groups
    if (botAuthored.length) {
      items.push({ type: "header", key: "bot-authored", label: "Bot-Authored", count: botAuthored.length, icon: Bot, color: "#059669" });
      const botGroups = new Map<string, SkillItem[]>();
      for (const s of botAuthored) {
        const bid = s.bot_id || "unknown";
        const list = botGroups.get(bid);
        if (list) list.push(s); else botGroups.set(bid, [s]);
      }
      const sortedBots = [...botGroups.entries()].sort((a, b) => b[1].length - a[1].length);
      for (const [bid, bSkills] of sortedBots) {
        items.push({ type: "bot-group", key: `bot-${bid}`, botId: bid, skills: bSkills });
      }
    }

    const addGroup = (key: string, label: string, skills: SkillItem[], icon?: typeof Bot, color?: string) => {
      if (!skills.length) return;
      items.push({ type: "header", key, label, count: skills.length, icon, color });
      for (const s of skills) items.push({ type: "skill", key: s.id, skill: s });
    };

    addGroup("manual", "User Added", manual, Wrench, t.textMuted);
    addGroup("core", "Core", core, FileText, t.accent);

    const intKeys = [...integrationMap.keys()].sort();
    if (intKeys.length) {
      const totalInt = intKeys.reduce((n, k) => n + integrationMap.get(k)!.length, 0);
      items.push({ type: "header", key: "integrations", label: "Integrations", count: totalInt, icon: Puzzle, color: "#ea580c" });
      for (const k of intKeys) {
        const skills = integrationMap.get(k)!;
        items.push({ type: "subheader", key: `int-${k}`, label: fmtIntName(k), count: skills.length });
        for (const s of skills) items.push({ type: "skill", key: s.id, skill: s });
      }
    }

    return items;
  }, [filteredSkills, t.accent, t.textMuted]);

  const handleSync = () => {
    setSyncResult(null);
    setSyncError(null);
    syncMut.mutate(undefined, {
      onSuccess: (data) => setSyncResult(data),
      onError: (err) => setSyncError((err as Error).message || "Sync failed"),
    });
  };

  const handleDeleteSkill = async (skill: SkillItem) => {
    const enrolledMsg = skill.enrolled_bot_count > 0
      ? ` It is enrolled in ${skill.enrolled_bot_count} bot${skill.enrolled_bot_count !== 1 ? "s" : ""}.`
      : "";
    const ok = await confirm(
      `Delete "${skill.name}" permanently?${enrolledMsg} This cannot be undone.`,
      { title: "Delete skill", variant: "danger", confirmLabel: "Delete" },
    );
    if (ok) deleteMut.mutate(skill.id);
  };

  const navigateToSkill = (id: string) => {
    navigate(`/admin/skills/${encodeURIComponent(id)}`);
  };

  if (isLoading) {
    return (
      <div className="flex flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  const hasFilters = !!search || !!filter;

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Skills"
        right={
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <button
              onClick={handleSync}
              disabled={syncMut.isPending}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                background: "transparent", color: t.textMuted, cursor: "pointer",
              }}
            >
              <RefreshCw size={14} style={syncMut.isPending ? { animation: "spin 1s linear infinite" } : undefined} />
              {syncMut.isPending ? "Syncing..." : "Sync"}
            </button>
            <button
              onClick={() => navigate("/admin/skills/new")}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: "none", borderRadius: 6,
                background: t.accent, color: "#fff", cursor: "pointer",
              }}
            >
              <Plus size={14} />
              New Skill
            </button>
          </div>
        }
      />

      {/* Search + filter bar */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
        padding: isWide ? "8px 16px" : "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: isWide ? 260 : undefined, flex: isWide ? undefined : 1,
        }}>
          <Search size={13} color={t.textDim} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search skills..."
            style={{
              background: "none", border: "none", outline: "none",
              color: t.text, fontSize: 12, flex: 1, width: "100%",
            }}
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              style={{ background: "none", border: "none", cursor: "pointer", padding: 0, display: "flex", flexDirection: "row" }}
            >
              <X size={12} color={t.textDim} />
            </button>
          )}
        </div>

        {skills && skills.length > 0 && (
          <FilterDropdown skills={skills} value={filter} onChange={setFilter} />
        )}

        <span style={{ flex: 1 }} />

        {skills && skills.length > 0 && (
          <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
            {hasFilters && filteredSkills.length !== skills.length
              ? `${filteredSkills.length} / ${skills.length}`
              : skills.length}{" "}
            skills
          </span>
        )}
      </div>

      {/* Sync result banner */}
      {syncResult && (
        <SyncResultBanner result={syncResult} onDismiss={() => setSyncResult(null)} />
      )}
      {syncError && (
        <div style={{
          padding: "10px 16px", background: t.dangerSubtle,
          border: `1px solid ${t.dangerBorder}`,
          margin: "8px 12px 0", borderRadius: 8, fontSize: 12, color: t.danger,
          display: "flex", flexDirection: "row", justifyContent: "space-between", alignItems: "center",
        }}>
          <span><AlertTriangle size={12} style={{ marginRight: 6 }} />Sync failed: {syncError}</span>
          <button onClick={() => setSyncError(null)} style={{
            background: "none", border: "none", color: t.textDim, cursor: "pointer", fontSize: 16,
          }}>&times;</button>
        </div>
      )}

      {/* List */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }} contentContainerStyle={!isWide ? { padding: "0 12px" } : undefined}>
        {(!skills || skills.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", color: t.textDim, fontSize: 13,
          }}>
            No skills yet. Create one or drop <code style={{ color: t.textMuted }}>.md</code> files in{" "}
            <code style={{ color: t.textMuted }}>skills/</code> and click Sync Files.
          </div>
        )}
        {skills && skills.length > 0 && filteredSkills.length === 0 && (
          <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
            No skills match {search ? `"${search}"` : "this filter"}.
            <button
              onClick={() => { setSearch(""); setFilter(null); }}
              style={{
                display: "block", margin: "8px auto 0", background: "none",
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                padding: "4px 12px", fontSize: 11, color: t.accent, cursor: "pointer",
              }}
            >
              Clear filters
            </button>
          </div>
        )}

        {renderItems.map((item) => {
          if (item.type === "header") {
            return <SectionHeader key={item.key} label={item.label} count={item.count} level={0} isWide={isWide} icon={item.icon} color={item.color} />;
          }
          if (item.type === "subheader") {
            return <SectionHeader key={item.key} label={item.label} count={item.count} level={1} isWide={isWide} />;
          }
          if (item.type === "bot-group") {
            return (
              <BotGroupSection
                key={item.key}
                botId={item.botId}
                skills={item.skills}
                isWide={isWide}
                onSkillPress={navigateToSkill}
                onSkillDelete={handleDeleteSkill}
              />
            );
          }
          return (
            <SkillRow
              key={item.key}
              skill={item.skill}
              isWide={isWide}
              onClick={() => navigateToSkill(item.skill.id)}
            />
          );
        })}
      </RefreshableScrollView>

      <ConfirmDialogSlot />
    </div>
  );
}
