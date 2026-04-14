import { useMemo, useState } from "react";
import { useRouter } from "expo-router";
import {
  BookOpen, TrendingUp, AlertTriangle, Flame, Zap,
  ChevronUp, ChevronDown,
} from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills, type SkillItem } from "@/src/api/hooks/useSkills";
import { useAdminBots } from "@/src/api/hooks/useBots";
import {
  StatCard, HealthBadge, getHealth, parseFrontmatter, fmtRelative,
} from "@/app/(app)/admin/bots/[botId]/LearningSection";

type SortKey = "name" | "bot" | "surface_count" | "total_auto_injects" | "last_surfaced_at" | "created_at";

export function SkillsTab() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: skills, isLoading } = useSkills({ source_type: "tool", sort: "recent" });
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
    }));
  }, [skills, botNameMap]);

  const sorted = useMemo(() => {
    const list = [...parsed];
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "name": cmp = a.name.localeCompare(b.name); break;
        case "bot": cmp = a.bot_name.localeCompare(b.bot_name); break;
        case "surface_count": cmp = a.surface_count - b.surface_count; break;
        case "total_auto_injects": cmp = a.total_auto_injects - b.total_auto_injects; break;
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
  const activeSkills = parsed.filter((s) => s.surface_count > 0 || (s.total_auto_injects ?? 0) > 0).length;
  const neverSurfaced = parsed.filter((s) => s.surface_count === 0 && (s.total_auto_injects ?? 0) === 0).length;

  const toggleSort = (key: SortKey) => {
    if (sortKey === key) setSortAsc(!sortAsc);
    else { setSortKey(key); setSortAsc(false); }
  };

  const SortIcon = sortAsc ? ChevronUp : ChevronDown;

  if (isLoading) {
    return <div style={{ color: t.textDim, fontSize: 12, padding: 20 }}>Loading...</div>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Bot-Authored Skills</div>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Skills created by bots via the <code style={{ color: t.textMuted }}>manage_bot_skill</code> tool across all bots.
      </div>

      {totalSkills === 0 && (
        <div style={{
          padding: 24, textAlign: "center", borderRadius: 8,
          background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <BookOpen size={24} color={t.textDim} style={{ marginBottom: 8 }} />
          <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 4 }}>
            No bot-authored skills yet.
          </div>
          <div style={{ fontSize: 11, color: t.textDim }}>
            Skills are created automatically when bots use the <code style={{ color: t.textMuted }}>manage_bot_skill</code> tool.
          </div>
        </div>
      )}

      {totalSkills > 0 && (
        <>
          {/* Stats row */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <StatCard label="Total Skills" value={totalSkills} icon={<BookOpen size={12} color="#059669" />} />
            <StatCard label="Total Surfacings" value={totalSurfacings} icon={<TrendingUp size={12} color="#3b82f6" />} />
            <StatCard label="Auto-Injects" value={totalAutoInjects} icon={<Zap size={12} color="#a855f7" />} />
            <StatCard label="Active" value={activeSkills} icon={<Flame size={12} color="#ef4444" />} />
            <StatCard label="Never Surfaced" value={neverSurfaced} icon={<AlertTriangle size={12} color={t.textDim} />} />
          </div>

          {/* Health callouts */}
          {neverSurfaced > 0 && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "8px 12px", borderRadius: 6,
              background: "rgba(234,179,8,0.08)", border: "1px solid rgba(234,179,8,0.2)",
            }}>
              <AlertTriangle size={14} color="#d97706" />
              <span style={{ fontSize: 11, color: "#d97706" }}>
                <strong>{neverSurfaced}</strong> skill{neverSurfaced !== 1 ? "s have" : " has"} never been surfaced or auto-injected.
              </span>
            </div>
          )}

          {/* Skills table */}
          <div style={{ overflowX: "auto" }}>
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${t.surfaceBorder}` }}>
                  {([
                    ["name", "Name"],
                    ["bot", "Bot"],
                    [null, "Category"],
                    ["surface_count", "Surfacings"],
                    ["total_auto_injects", "Auto-Injects"],
                    ["last_surfaced_at", "Last Surfaced"],
                    [null, "Health"],
                  ] as const).map(([key, label], i) => (
                    <th
                      key={label}
                      onClick={key ? () => toggleSort(key as SortKey) : undefined}
                      style={{
                        textAlign: i >= 3 ? "right" : "left",
                        padding: "6px 8px", fontWeight: 600, color: t.textMuted,
                        cursor: key ? "pointer" : "default",
                        userSelect: "none", whiteSpace: "nowrap",
                      }}
                    >
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 3 }}>
                        {label}
                        {key && sortKey === key && <SortIcon size={10} />}
                      </span>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {sorted.map((s) => (
                  <tr key={s.id} style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}>
                    {/* Name */}
                    <td style={{ padding: "8px 8px", maxWidth: 200 }}>
                      <button
                        onClick={() => router.push(`/admin/skills/${encodeURIComponent(s.id)}` as any)}
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
                          padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600,
                          background: t.accentSubtle, color: t.accent,
                        }}>
                          {s.category}
                        </span>
                      ) : (
                        <span style={{ color: t.textDim }}>—</span>
                      )}
                    </td>
                    {/* Surfacings */}
                    <td style={{ padding: "8px 8px", textAlign: "right" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                        {s.surface_count >= 10 && <Flame size={10} color="#ef4444" />}
                        <span style={{ color: s.surface_count > 0 ? t.text : t.textDim, fontWeight: s.surface_count >= 10 ? 600 : 400 }}>
                          {s.surface_count}
                        </span>
                      </span>
                    </td>
                    {/* Auto-Injects */}
                    <td style={{ padding: "8px 8px", textAlign: "right" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                        {(s.total_auto_injects ?? 0) >= 10 && <Zap size={10} color="#a855f7" />}
                        <span style={{ color: (s.total_auto_injects ?? 0) > 0 ? t.text : t.textDim, fontWeight: (s.total_auto_injects ?? 0) >= 10 ? 600 : 400 }}>
                          {s.total_auto_injects ?? 0}
                        </span>
                      </span>
                    </td>
                    {/* Last surfaced */}
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
