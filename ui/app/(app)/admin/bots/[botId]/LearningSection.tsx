import { useMemo, useState } from "react";
import {
  BookOpen, TrendingUp, AlertTriangle, Clock,
  ChevronUp, ChevronDown, Flame,
} from "lucide-react";
import { useRouter } from "expo-router";
import { useThemeTokens } from "@/src/theme/tokens";
import { useSkills, type SkillItem } from "@/src/api/hooks/useSkills";

// ---------------------------------------------------------------------------
// Frontmatter parser — extracts category + triggers from YAML frontmatter
// ---------------------------------------------------------------------------
export function parseFrontmatter(content: string): { category?: string; triggers?: string[] } {
  const m = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (!m) return {};
  const lines = m[1].split(/\r?\n/);
  let category: string | undefined;
  let triggers: string[] | undefined;

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const catMatch = line.match(/^category:\s*(.+)/);
    if (catMatch) category = catMatch[1].trim().replace(/^["']|["']$/g, "");

    // Inline: triggers: [a, b, c]
    const trigInline = line.match(/^triggers:\s*\[(.+)]/);
    if (trigInline) {
      triggers = trigInline[1].split(",").map((t) => t.trim().replace(/^["']|["']$/g, ""));
      continue;
    }
    // YAML list: triggers:\n  - a\n  - b
    if (/^triggers:\s*$/.test(line)) {
      triggers = [];
      for (let j = i + 1; j < lines.length; j++) {
        const itemMatch = lines[j].match(/^\s+-\s+(.+)/);
        if (itemMatch) {
          triggers.push(itemMatch[1].trim().replace(/^["']|["']$/g, ""));
        } else break;
      }
    }
  }
  return { category, triggers };
}

// ---------------------------------------------------------------------------
// Relative time formatter
// ---------------------------------------------------------------------------
export function fmtRelative(iso: string | null | undefined): string {
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
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

// ---------------------------------------------------------------------------
// Health badge
// ---------------------------------------------------------------------------
export type Health = "new" | "hot" | "stale" | "dormant" | null;

export function getHealth(s: SkillItem): Health {
  const ageMs = Date.now() - new Date(s.created_at).getTime();
  const ageDays = ageMs / 86_400_000;

  if (s.surface_count >= 10) return "hot";
  if (s.surface_count === 0 && ageDays < 1) return "new";
  if (s.surface_count === 0 && ageDays > 7) return "stale";
  if (s.surface_count > 0 && s.last_surfaced_at) {
    const lastMs = Date.now() - new Date(s.last_surfaced_at).getTime();
    if (lastMs > 30 * 86_400_000) return "dormant";
  }
  return null;
}

const HEALTH_CFG: Record<string, { bg: string; fg: string; label: string }> = {
  new: { bg: "rgba(59,130,246,0.15)", fg: "#3b82f6", label: "new" },
  hot: { bg: "rgba(239,68,68,0.15)", fg: "#ef4444", label: "hot" },
  stale: { bg: "rgba(234,179,8,0.15)", fg: "#ca8a04", label: "stale" },
  dormant: { bg: "rgba(156,163,175,0.15)", fg: "#6b7280", label: "dormant" },
};

export function HealthBadge({ health }: { health: Health }) {
  if (!health) return null;
  const c = HEALTH_CFG[health];
  return (
    <span style={{
      padding: "1px 6px", borderRadius: 3, fontSize: 9, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {c.label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------
export function StatCard({ label, value, icon, color }: {
  label: string; value: number; icon: React.ReactNode; color?: string;
}) {
  const t = useThemeTokens();
  return (
    <div style={{
      flex: 1, minWidth: 120, padding: "10px 12px", borderRadius: 8,
      background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
        {icon}
        <span style={{ fontSize: 10, color: t.textDim, textTransform: "uppercase", fontWeight: 600, letterSpacing: 0.5 }}>
          {label}
        </span>
      </div>
      <div style={{ fontSize: 20, fontWeight: 700, color: color || t.text }}>{value}</div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sort config
// ---------------------------------------------------------------------------
type SortKey = "name" | "surface_count" | "last_surfaced_at" | "created_at";

// ---------------------------------------------------------------------------
// LearningSection
// ---------------------------------------------------------------------------
export function LearningSection({ botId }: { botId: string }) {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: skills, isLoading } = useSkills({ bot_id: botId, source_type: "tool", sort: "recent" });
  const [sortKey, setSortKey] = useState<SortKey>("created_at");
  const [sortAsc, setSortAsc] = useState(false);

  const parsed = useMemo(() => {
    if (!skills) return [];
    return skills.map((s) => ({ ...s, ...parseFrontmatter(s.content), health: getHealth(s) }));
  }, [skills]);

  const sorted = useMemo(() => {
    const list = [...parsed];
    list.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "name": cmp = a.name.localeCompare(b.name); break;
        case "surface_count": cmp = a.surface_count - b.surface_count; break;
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

  // Stats
  const totalSkills = parsed.length;
  const totalSurfacings = parsed.reduce((n, s) => n + s.surface_count, 0);
  const activeSkills = parsed.filter((s) => s.surface_count > 0).length;
  const neverSurfaced = parsed.filter((s) => s.surface_count === 0).length;
  const dormantSkills = parsed.filter((s) => s.health === "dormant").length;

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
      <div style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Learning</div>
      <div style={{ fontSize: 11, color: t.textDim }}>
        Skills created by the bot via the <code style={{ color: t.textMuted }}>manage_bot_skill</code> tool.
        Surface count tracks how often each skill is retrieved by the RAG pipeline.
      </div>

      {/* Empty state */}
      {totalSkills === 0 && (
        <div style={{
          padding: 24, textAlign: "center", borderRadius: 8,
          background: t.surfaceRaised, border: `1px solid ${t.surfaceBorder}`,
        }}>
          <BookOpen size={24} color={t.textDim} style={{ marginBottom: 8 }} />
          <div style={{ fontSize: 13, color: t.textMuted, marginBottom: 4 }}>
            This bot hasn't created any skills yet.
          </div>
          <div style={{ fontSize: 11, color: t.textDim }}>
            Skills are created automatically when the bot uses the <code style={{ color: t.textMuted }}>manage_bot_skill</code> tool.
          </div>
        </div>
      )}

      {totalSkills > 0 && (
        <>
          {/* Stats row */}
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <StatCard label="Total Skills" value={totalSkills} icon={<BookOpen size={12} color="#059669" />} />
            <StatCard label="Total Surfacings" value={totalSurfacings} icon={<TrendingUp size={12} color="#3b82f6" />} />
            <StatCard label="Active" value={activeSkills} icon={<Flame size={12} color="#ef4444" />} />
            <StatCard
              label="Never Surfaced"
              value={neverSurfaced}
              icon={<AlertTriangle size={12} color={t.textDim} />}
            />
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
                <strong>{neverSurfaced}</strong> skill{neverSurfaced !== 1 ? "s have" : " has"} never been surfaced — review their triggers or consider deleting.
              </span>
            </div>
          )}
          {dormantSkills > 0 && (
            <div style={{
              display: "flex", alignItems: "center", gap: 8,
              padding: "8px 12px", borderRadius: 6,
              background: t.surfaceOverlay, border: `1px solid ${t.surfaceBorder}`,
            }}>
              <Clock size={14} color={t.textMuted} />
              <span style={{ fontSize: 11, color: t.textMuted }}>
                <strong>{dormantSkills}</strong> skill{dormantSkills !== 1 ? "s" : ""} surfaced before but not in the last 30 days.
              </span>
            </div>
          )}

          {/* Skills table */}
          <div style={{ overflowX: "auto" }}>
            <table style={{
              width: "100%", borderCollapse: "collapse", fontSize: 11,
            }}>
              <thead>
                <tr style={{ borderBottom: `2px solid ${t.surfaceBorder}` }}>
                  {([
                    ["name", "Name"],
                    [null, "Category"],
                    [null, "Triggers"],
                    ["surface_count", "Surfacings"],
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
                  <tr
                    key={s.id}
                    style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
                  >
                    {/* Name + created date */}
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
                    {/* Triggers */}
                    <td style={{ padding: "8px 8px", maxWidth: 180 }}>
                      {s.triggers && s.triggers.length > 0 ? (
                        <span style={{
                          color: t.textDim, overflow: "hidden", textOverflow: "ellipsis",
                          whiteSpace: "nowrap", display: "block", maxWidth: 180,
                        }}>
                          {s.triggers.join(", ")}
                        </span>
                      ) : (
                        <span style={{ color: t.textDim }}>—</span>
                      )}
                    </td>
                    {/* Surface count */}
                    <td style={{ padding: "8px 8px", textAlign: "right" }}>
                      <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
                        {s.surface_count >= 10 && <Flame size={10} color="#ef4444" />}
                        <span style={{ color: s.surface_count > 0 ? t.text : t.textDim, fontWeight: s.surface_count >= 10 ? 600 : 400 }}>
                          {s.surface_count}
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
