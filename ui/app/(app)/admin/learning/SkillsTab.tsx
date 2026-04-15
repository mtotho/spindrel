import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  BookOpen, TrendingUp, AlertTriangle, Flame, Zap,
  ChevronUp, ChevronDown, Sparkles,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills, type SkillItem } from "@/src/api/hooks/useSkills";
import { useAdminBots } from "@/src/api/hooks/useBots";
import {
  StatCard, HealthBadge, getHealth, parseFrontmatter, fmtRelative,
} from "@/app/(app)/admin/bots/[botId]/LearningSection";

type SortKey = "name" | "bot" | "activity" | "surface_count" | "total_auto_injects" | "last_surfaced_at" | "created_at";

// ---------------------------------------------------------------------------
// Inline activity bar — stacked horizontal bar for surfacings + injects
// ---------------------------------------------------------------------------

function ActivityBar({ surfacings, autoInjects, maxActivity }: {
  surfacings: number; autoInjects: number; maxActivity: number;
}) {
  const t = useThemeTokens();
  const total = surfacings + autoInjects;
  if (maxActivity === 0) return <div style={{ width: 60, height: 6, borderRadius: 3, background: t.surfaceBorder }} />;

  const widthPct = Math.max(4, (total / maxActivity) * 100);
  const surfPct = total > 0 ? (surfacings / total) * 100 : 0;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 2, minWidth: 60 }}>
      <div style={{
        width: 60, height: 6, borderRadius: 3, overflow: "hidden",
        background: t.surfaceBorder, position: "relative",
      }}>
        <div style={{
          position: "absolute", left: 0, top: 0, bottom: 0,
          width: `${widthPct}%`, borderRadius: 3, overflow: "hidden",
          display: "flex", flexDirection: "row",
        }}>
          {surfacings > 0 && (
            <div style={{ width: `${surfPct}%`, height: "100%", background: "#f59e0b" }} />
          )}
          {autoInjects > 0 && (
            <div style={{ flex: 1, height: "100%", background: "#a855f7" }} />
          )}
        </div>
      </div>
      <span style={{ fontSize: 8, color: t.textDim, textAlign: "right" }}>{total}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// SkillsTab
// ---------------------------------------------------------------------------

export function SkillsTab({ days }: { days: number }) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: skills, isLoading } = useSkills({ source_type: "tool", sort: "recent", days });
  const { data: bots } = useAdminBots();
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortAsc, setSortAsc] = useState(false);

  const botNameMap = useMemo(() => {
    const map: Record<string, string> = {};
    if (bots) for (const b of bots) map[b.id] = b.name;
    return map;
  }, [bots]);

  const parsed = useMemo(() => {
    if (!skills) return [];
    return skills.map((s) => ({
      ...s,
      ...parseFrontmatter(s.content),
      health: getHealth(s),
      bot_name: s.bot_id ? botNameMap[s.bot_id] ?? s.bot_id : "—",
      totalActivity: s.surface_count + (s.total_auto_injects ?? 0),
    }));
  }, [skills, botNameMap]);

  const sorted = useMemo(() => {
    const list = [...parsed];
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "name": cmp = a.name.localeCompare(b.name); break;
        case "bot": cmp = a.bot_name.localeCompare(b.bot_name); break;
        case "activity": cmp = a.totalActivity - b.totalActivity; break;
        case "surface_count": cmp = a.surface_count - b.surface_count; break;
        case "total_auto_injects": cmp = (a.total_auto_injects ?? 0) - (b.total_auto_injects ?? 0); break;
        case "last_surfaced_at": {
          const at = a.last_surfaced_at ? new Date(a.last_surfaced_at).getTime() : 0;
          const bt = b.last_surfaced_at ? new Date(b.last_surfaced_at).getTime() : 0;
          cmp = at - bt; break;
        }
        case "created_at": {
          cmp = new Date(a.created_at).getTime() - new Date(b.created_at).getTime(); break;
        }
      }
      return sortAsc ? cmp : -cmp;
    });
    return list;
  }, [parsed, sortKey, sortAsc]);

  const totalSkills = parsed.length;
  const totalSurfacings = parsed.reduce((n, s) => n + s.surface_count, 0);
  const totalAutoInjects = parsed.reduce((n, s) => n + (s.total_auto_injects ?? 0), 0);
  const activeSkills = parsed.filter((s) => s.totalActivity > 0).length;
  const neverSurfaced = parsed.filter((s) => s.totalActivity === 0).length;
  const maxActivity = Math.max(...parsed.map((s) => s.totalActivity), 1);

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const SortIcon = sortAsc ? ChevronUp : ChevronDown;

  if (isLoading) {
    return (
      <div style={{ display: "flex", flexDirection: "row", justifyContent: "center", padding: 40 }}>
        <div style={{ color: t.textDim, fontSize: 12 }}>Loading skills...</div>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Bot-Authored Skills</div>
        <div style={{ fontSize: 11, color: t.textDim, marginTop: 2 }}>
          Skills created by bots via <code style={{ color: t.textMuted, fontSize: 10 }}>manage_bot_skill</code>.{" "}
          <span style={{ color: "#f59e0b" }}>Amber</span> = surfacings, <span style={{ color: "#a855f7" }}>purple</span> = auto-injects.
        </div>
      </div>

      {totalSkills === 0 && (
        <div style={{
          padding: 32, textAlign: "center", borderRadius: 10,
          background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <Sparkles size={28} color={t.textDim} style={{ marginBottom: 8 }} />
          <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 4 }}>
            No bot-authored skills yet
          </div>
          <div style={{ fontSize: 11, color: t.textDim }}>
            Skills appear when bots use <code style={{ color: t.textMuted }}>manage_bot_skill</code> to document procedures.
          </div>
        </div>
      )}

      {totalSkills > 0 && (
        <>
          {/* Stats row */}
          <div style={{ display: "flex", flexDirection: "row", gap: 10, flexWrap: "wrap" }}>
            <StatCard label="Total Skills" value={totalSkills} icon={<BookOpen size={12} color="#059669" />} />
            <StatCard label="Surfacings" value={totalSurfacings} icon={<TrendingUp size={12} color="#f59e0b" />} />
            <StatCard label="Auto-Injects" value={totalAutoInjects} icon={<Zap size={12} color="#a855f7" />} />
            <StatCard label="Active" value={activeSkills} icon={<Flame size={12} color="#ef4444" />} />
            <StatCard label="Unused" value={neverSurfaced} icon={<AlertTriangle size={12} color={t.textDim} />} />
          </div>

          {/* Health callouts */}
          {neverSurfaced > 0 && (
            <div style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
              padding: "8px 12px", borderRadius: 8,
              background: "rgba(234,179,8,0.06)", border: "1px solid rgba(234,179,8,0.15)",
            }}>
              <AlertTriangle size={13} color="#d97706" />
              <span style={{ fontSize: 11, color: "#d97706" }}>
                <strong>{neverSurfaced}</strong> skill{neverSurfaced !== 1 ? "s" : ""} never used — review triggers or consider removing.
              </span>
            </div>
          )}

          {/* Skills table */}
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{
                  borderBottom: `2px solid ${t.surfaceBorder}`,
                  background: t.surfaceOverlay,
                }}>
                  {([
                    ["name", "Name"],
                    ["bot", "Bot"],
                    [null, "Category"],
                    ["activity", "Activity"],
                    ["surface_count", "Surfacings"],
                    ["total_auto_injects", "Injects"],
                    ["last_surfaced_at", "Last Active"],
                    [null, "Health"],
                  ] as const).map(([key, label], i) => (
                    <th
                      key={label}
                      onClick={key ? () => toggleSort(key as SortKey) : undefined}
                      style={{
                        textAlign: i >= 3 ? "right" : "left",
                        padding: "7px 8px", fontWeight: 700, color: t.textDim,
                        cursor: key ? "pointer" : "default",
                        userSelect: "none", whiteSpace: "nowrap",
                        fontSize: 9, textTransform: "uppercase", letterSpacing: 0.5,
                      }}
                    >
                      <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3 }}>
                        {label}
                        {key && sortKey === (key as SortKey) && <SortIcon size={10} />}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((s) => (
                  <tr
                    key={s.id}
                    style={{
                      borderBottom: `1px solid ${t.surfaceBorder}`,
                      transition: "background 0.1s",
                    }}
                    onMouseEnter={(e) => { e.currentTarget.style.background = t.surfaceOverlay; }}
                    onMouseLeave={(e) => { e.currentTarget.style.background = "transparent"; }}
                  >
                    {/* Name */}
                    <td style={{ padding: "8px 8px", maxWidth: 200 }}>
                      <button
                        onClick={() => navigate(`/admin/skills/${encodeURIComponent(s.id)}`)}
                        style={{
                          background: "none", border: "none", cursor: "pointer", padding: 0,
                          color: t.accent, fontWeight: 500, fontSize: 11, textAlign: "left",
                          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                          display: "block", maxWidth: "100%",
                        }}
                      >
                        {s.name}
                      </button>
                      <div style={{ fontSize: 9, color: t.textDim, marginTop: 1 }}>
                        created {fmtRelative(s.created_at)}
                      </div>
                    </td>
                    {/* Bot */}
                    <td style={{ padding: "8px 8px" }}>
                      <span style={{ fontSize: 11, color: t.textMuted }}>{s.bot_name}</span>
                    </td>
                    {/* Category */}
                    <td style={{ padding: "8px 8px" }}>
                      {s.category ? (
                        <span style={{
                          padding: "2px 7px", borderRadius: 4, fontSize: 9, fontWeight: 600,
                          background: t.accentSubtle, color: t.accent,
                        }}>
                          {s.category}
                        </span>
                      ) : (
                        <span style={{ color: t.textDim }}>—</span>
                      )}
                    </td>
                    {/* Activity bar */}
                    <td style={{ padding: "8px 8px", textAlign: "right" }}>
                      <div style={{ display: "flex", flexDirection: "row", justifyContent: "flex-end" }}>
                        <ActivityBar
                          surfacings={s.surface_count}
                          autoInjects={s.total_auto_injects ?? 0}
                          maxActivity={maxActivity}
                        />
                      </div>
                    </td>
                    {/* Surfacings */}
                    <td style={{ padding: "8px 8px", textAlign: "right" }}>
                      <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                        {s.surface_count >= 10 && <Flame size={10} color="#ef4444" />}
                        <span style={{
                          color: s.surface_count > 0 ? t.text : t.textDim,
                          fontWeight: s.surface_count >= 10 ? 600 : 400,
                          fontVariantNumeric: "tabular-nums",
                        }}>
                          {s.surface_count}
                        </span>
                      </span>
                    </td>
                    {/* Auto-Injects */}
                    <td style={{ padding: "8px 8px", textAlign: "right" }}>
                      <span style={{ display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                        {(s.total_auto_injects ?? 0) >= 10 && <Zap size={10} color="#a855f7" />}
                        <span style={{
                          color: (s.total_auto_injects ?? 0) > 0 ? t.text : t.textDim,
                          fontWeight: (s.total_auto_injects ?? 0) >= 10 ? 600 : 400,
                          fontVariantNumeric: "tabular-nums",
                        }}>
                          {s.total_auto_injects ?? 0}
                        </span>
                      </span>
                    </td>
                    {/* Last active */}
                    <td style={{ padding: "8px 8px", textAlign: "right", color: t.textDim, whiteSpace: "nowrap" }}>
                      {fmtRelative(s.last_surfaced_at)}
                    </td>
                    {/* Health */}
                    <td style={{ padding: "8px 8px", textAlign: "right" }}>
                      <HealthBadge health={s.health} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}
