import { useState, useMemo } from "react";
import { Search, X, Plus, TrendingUp, Zap, AlertTriangle } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useEnrolledSkills,
  useEnrollSkill,
  useUnenrollSkill,
  type EnrolledSkill,
} from "@/src/api/hooks/useEnrolledSkills";
import { useDeleteSkill } from "@/src/api/hooks/useSkills";
import { useQueryClient } from "@tanstack/react-query";
import { AdvancedSection } from "@/src/components/shared/SettingsControls";
import type { SkillOption } from "@/src/types/api";
import { createPortal } from "react-dom";

const SOURCE_LABELS: Record<string, { label: string; bg: string; fg: string }> = {
  starter: { label: "starter", bg: "rgba(59,130,246,0.15)", fg: "#2563eb" },
  fetched: { label: "fetched", bg: "rgba(16,185,129,0.15)", fg: "#059669" },
  manual: { label: "manual", bg: "rgba(168,85,247,0.15)", fg: "#9333ea" },
  migration: { label: "migration", bg: "rgba(148,163,184,0.15)", fg: "#64748b" },
  authored: { label: "authored", bg: "rgba(249,115,22,0.15)", fg: "#ea580c" },
};

function SourceBadge({ source }: { source: string }) {
  const cfg = SOURCE_LABELS[source] ?? { label: source, bg: "#eee", fg: "#444" };
  return (
    <span
      style={{
        padding: "1px 6px",
        borderRadius: 3,
        fontSize: 9,
        fontWeight: 600,
        background: cfg.bg,
        color: cfg.fg,
      }}
    >
      {cfg.label}
    </span>
  );
}

function formatDate(iso: string | null): string {
  if (!iso) return "never";
  try {
    return new Date(iso).toISOString().slice(0, 10);
  } catch {
    return "—";
  }
}

/* ------------------------------------------------------------------ */
/*  Three-choice modal for removing authored skills                    */
/* ------------------------------------------------------------------ */

function RemoveAuthoredSkillModal({
  skill,
  botName,
  onCancel,
  onUnenroll,
  onDelete,
  isDeleting,
  isUnenrolling,
}: {
  skill: EnrolledSkill;
  botName: string;
  onCancel: () => void;
  onUnenroll: () => void;
  onDelete: () => void;
  isDeleting: boolean;
  isUnenrolling: boolean;
}) {
  const t = useThemeTokens();
  const busy = isDeleting || isUnenrolling;
  const otherBots = skill.enrolled_bot_count - 1;

  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={busy ? undefined : onCancel}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.45)",
          zIndex: 10020,
        }}
      />
      {/* Dialog */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 420,
          maxWidth: "90vw",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          padding: 20,
        }}
      >
        {/* Header */}
        <div
          style={{
            display: "flex", flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 12,
          }}
        >
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
            <AlertTriangle size={15} color={t.danger} />
            <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>
              Remove authored skill
            </span>
          </div>
          {!busy && (
            <button
              onClick={onCancel}
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                justifyContent: "center",
                background: "transparent",
                border: "none",
                cursor: "pointer",
                padding: 4,
              }}
            >
              <X size={16} color={t.textDim} />
            </button>
          )}
        </div>

        {/* Body */}
        <div style={{ fontSize: 13, color: t.textMuted, lineHeight: "20px", marginBottom: 8 }}>
          <strong style={{ color: t.text }}>&ldquo;{skill.name}&rdquo;</strong> was created by{" "}
          <strong style={{ color: t.text }}>{botName}</strong>.
        </div>

        <div style={{ fontSize: 12, color: t.textDim, lineHeight: "18px", marginBottom: 16 }}>
          You can remove it from this bot&rsquo;s working set, or delete it permanently from the
          catalog.
        </div>

        {otherBots > 0 && (
          <div
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              gap: 6,
              padding: "8px 10px",
              background: t.warningSubtle,
              border: `1px solid ${t.warningBorder}`,
              borderRadius: 6,
              fontSize: 12,
              color: t.warningMuted,
              marginBottom: 16,
            }}
          >
            <AlertTriangle size={13} />
            <span>
              {otherBots} other bot{otherBots !== 1 ? "s" : ""} also use{otherBots === 1 ? "s" : ""}{" "}
              this skill. Deleting it removes it from all bots.
            </span>
          </div>
        )}

        {/* Actions */}
        <div style={{ display: "flex", flexDirection: "row", justifyContent: "flex-end", gap: 8 }}>
          <button
            onClick={onCancel}
            disabled={busy}
            style={{
              padding: "6px 12px",
              borderRadius: 6,
              border: `1px solid ${t.surfaceBorder}`,
              background: "transparent",
              cursor: busy ? "default" : "pointer",
              fontSize: 12,
              color: t.textDim,
            }}
          >
            Cancel
          </button>
          <button
            onClick={onUnenroll}
            disabled={busy}
            style={{
              padding: "6px 12px",
              borderRadius: 6,
              border: `1px solid ${t.surfaceBorder}`,
              background: "transparent",
              cursor: busy ? "default" : "pointer",
              fontSize: 12,
              fontWeight: 600,
              color: t.text,
              opacity: busy ? 0.5 : 1,
            }}
          >
            {isUnenrolling ? "Removing..." : "Just unenroll"}
          </button>
          <button
            onClick={onDelete}
            disabled={busy}
            style={{
              padding: "6px 12px",
              borderRadius: 6,
              background: t.danger,
              border: "none",
              cursor: busy ? "default" : "pointer",
              fontSize: 12,
              fontWeight: 600,
              color: "#fff",
              opacity: busy ? 0.5 : 1,
            }}
          >
            {isDeleting ? "Deleting..." : "Delete permanently"}
          </button>
        </div>
      </div>
    </>,
    document.body,
  );
}

export function EnrolledSkillsPanel({
  botId,
  botName,
  catalogSkills,
}: {
  botId: string;
  botName: string;
  catalogSkills: SkillOption[];
}) {
  const t = useThemeTokens();
  const queryClient = useQueryClient();
  const { data: enrolled, isLoading } = useEnrolledSkills(botId);
  const enrollMut = useEnrollSkill(botId);
  const unenrollMut = useUnenrollSkill(botId);
  const deleteMut = useDeleteSkill();
  const [filter, setFilter] = useState("");
  const [showAddPicker, setShowAddPicker] = useState(false);
  const [pickerFilter, setPickerFilter] = useState("");
  const [removeTarget, setRemoveTarget] = useState<EnrolledSkill | null>(null);

  const enrolledIds = useMemo(
    () => new Set((enrolled ?? []).map((e) => e.skill_id)),
    [enrolled]
  );

  const filtered = useMemo(() => {
    if (!enrolled) return [];
    if (!filter) return enrolled;
    const f = filter.toLowerCase();
    return enrolled.filter(
      (e) =>
        e.skill_id.toLowerCase().includes(f) ||
        e.name.toLowerCase().includes(f) ||
        (e.description ?? "").toLowerCase().includes(f)
    );
  }, [enrolled, filter]);

  const grouped = useMemo(() => {
    const groups: Record<string, EnrolledSkill[]> = {};
    for (const e of filtered) {
      (groups[e.source] ??= []).push(e);
    }
    return groups;
  }, [filtered]);

  const sourceOrder = ["starter", "manual", "fetched", "authored", "migration"];
  const orderedGroups = sourceOrder
    .map((src) => [src, grouped[src]] as const)
    .filter(([, list]) => list && list.length > 0);

  const pickerCandidates = useMemo(() => {
    const f = pickerFilter.toLowerCase();
    return catalogSkills
      .filter(
        (s) =>
          !enrolledIds.has(s.id) &&
          (!f ||
            s.id.toLowerCase().includes(f) ||
            s.name.toLowerCase().includes(f))
      )
      .slice(0, 30);
  }, [catalogSkills, enrolledIds, pickerFilter]);

  const handleRemoveClick = (e: EnrolledSkill) => {
    if (e.source === "authored") {
      setRemoveTarget(e);
    } else {
      unenrollMut.mutate(e.skill_id);
    }
  };

  const handleUnenrollOnly = () => {
    if (!removeTarget) return;
    unenrollMut.mutate(removeTarget.skill_id, {
      onSuccess: () => setRemoveTarget(null),
    });
  };

  const handleDeletePermanently = () => {
    if (!removeTarget) return;
    deleteMut.mutate(removeTarget.skill_id, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: ["bot-enrolled-skills", botId] });
        setRemoveTarget(null);
      },
    });
  };

  return (
    <AdvancedSection title="Working Set (Enrolled Skills)" defaultOpen>
      <div style={{ paddingTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 11, color: t.textDim, lineHeight: 1.4 }}>
          Skills the bot has accumulated as its persistent working set. The
          starter pack seeds new bots; successful <code style={{ fontSize: 10 }}>get_skill()</code> calls
          enroll new skills automatically; the memory hygiene loop prunes
          unused ones over time.
        </div>

        {isLoading && (
          <div style={{ fontSize: 11, color: t.textDim }}>Loading…</div>
        )}

        {enrolled && enrolled.length === 0 && (
          <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>
            No skills enrolled yet. The bot will accrete skills as it uses them.
          </div>
        )}

        {enrolled && enrolled.length > 0 && (
          <>
            <div
              style={{
                display: "flex", flexDirection: "row",
                alignItems: "center",
                gap: 6,
                background: t.inputBg,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 6,
                padding: "4px 8px",
              }}
            >
              <Search size={12} color={t.textDim} />
              <input
                type="text"
                value={filter}
                onChange={(e) => setFilter(e.target.value)}
                placeholder={`Filter ${enrolled.length} enrolled skill${enrolled.length !== 1 ? "s" : ""}…`}
                style={{
                  flex: 1,
                  background: "transparent",
                  border: "none",
                  outline: "none",
                  color: t.text,
                  fontSize: 12,
                }}
              />
            </div>

            {orderedGroups.map(([source, list]) => (
              <div key={source}>
                <div
                  style={{
                    display: "flex", flexDirection: "row",
                    alignItems: "center",
                    gap: 8,
                    padding: "10px 0 4px",
                  }}
                >
                  <span
                    style={{
                      fontSize: 10,
                      fontWeight: 600,
                      color: t.textMuted,
                      textTransform: "uppercase",
                      letterSpacing: 1,
                    }}
                  >
                    {source}
                  </span>
                  <span style={{ fontSize: 10, color: t.textDim }}>{list.length}</span>
                  <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
                </div>
                {list.map((e) => (
                  <div
                    key={e.skill_id}
                    style={{
                      padding: "8px 4px",
                      borderBottom: `1px solid ${t.surfaceBorder}`,
                      display: "flex", flexDirection: "row",
                      alignItems: "flex-start",
                      gap: 8,
                    }}
                  >
                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div
                        style={{
                          display: "flex", flexDirection: "row",
                          alignItems: "center",
                          gap: 6,
                          flexWrap: "wrap",
                        }}
                      >
                        <span style={{ fontSize: 12, fontWeight: 500, color: t.text }}>
                          {e.name}
                        </span>
                        <span
                          style={{
                            fontSize: 10,
                            color: t.textDim,
                            fontFamily: "monospace",
                          }}
                        >
                          {e.skill_id}
                        </span>
                        <SourceBadge source={e.source} />
                      </div>
                      {e.description && (
                        <div
                          style={{
                            fontSize: 10,
                            color: t.textDim,
                            marginTop: 2,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {e.description}
                        </div>
                      )}
                      <div
                        style={{
                          display: "flex", flexDirection: "row",
                          alignItems: "center",
                          gap: 8,
                          marginTop: 3,
                          fontSize: 10,
                          color: t.textDim,
                        }}
                      >
                        <TrendingUp size={10} />
                        <span>
                          surfaced <strong style={{ color: t.text }}>{e.surface_count}</strong>x
                        </span>
                        {(e.auto_inject_count ?? 0) > 0 && (
                          <>
                            <span>·</span>
                            <Zap size={10} color="#a855f7" />
                            <span>
                              injected <strong style={{ color: "#a855f7" }}>{e.auto_inject_count}</strong>x
                            </span>
                          </>
                        )}
                        <span>·</span>
                        <span>last {formatDate(
                          // Show the most recent activity date (surfaced or auto-injected)
                          e.last_surfaced_at && e.last_auto_injected_at
                            ? new Date(e.last_surfaced_at) > new Date(e.last_auto_injected_at)
                              ? e.last_surfaced_at : e.last_auto_injected_at
                            : e.last_surfaced_at || e.last_auto_injected_at
                        )}</span>
                        <span>·</span>
                        <span>enrolled {formatDate(e.enrolled_at)}</span>
                      </div>
                    </div>
                    <button
                      onClick={() => handleRemoveClick(e)}
                      disabled={unenrollMut.isPending}
                      title="Remove from working set"
                      style={{
                        display: "inline-flex", flexDirection: "row",
                        alignItems: "center",
                        gap: 3,
                        fontSize: 10,
                        color: "#dc2626",
                        background: "none",
                        border: "none",
                        cursor: "pointer",
                        whiteSpace: "nowrap",
                        marginTop: 1,
                        padding: "2px 4px",
                      }}
                    >
                      <X size={12} />
                      Remove
                    </button>
                  </div>
                ))}
              </div>
            ))}
          </>
        )}

        <div style={{ marginTop: 8 }}>
          {!showAddPicker ? (
            <button
              onClick={() => setShowAddPicker(true)}
              style={{
                display: "inline-flex", flexDirection: "row",
                alignItems: "center",
                gap: 4,
                fontSize: 11,
                color: t.accent,
                background: "none",
                border: `1px dashed ${t.surfaceBorder}`,
                cursor: "pointer",
                padding: "6px 10px",
                borderRadius: 6,
              }}
            >
              <Plus size={12} />
              Add skill manually
            </button>
          ) : (
            <div
              style={{
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 8,
                padding: 10,
                display: "flex",
                flexDirection: "column",
                gap: 8,
              }}
            >
              <div
                style={{
                  display: "flex", flexDirection: "row",
                  alignItems: "center",
                  gap: 6,
                  background: t.inputBg,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 6,
                  padding: "4px 8px",
                }}
              >
                <Search size={12} color={t.textDim} />
                <input
                  type="text"
                  value={pickerFilter}
                  onChange={(e) => setPickerFilter(e.target.value)}
                  placeholder="Search catalog skills…"
                  autoFocus
                  style={{
                    flex: 1,
                    background: "transparent",
                    border: "none",
                    outline: "none",
                    color: t.text,
                    fontSize: 12,
                  }}
                />
                <button
                  onClick={() => {
                    setShowAddPicker(false);
                    setPickerFilter("");
                  }}
                  style={{
                    background: "none",
                    border: "none",
                    cursor: "pointer",
                    color: t.textDim,
                    padding: 0,
                  }}
                >
                  <X size={12} />
                </button>
              </div>
              <div style={{ maxHeight: 240, overflow: "auto" }}>
                {pickerCandidates.length === 0 ? (
                  <div
                    style={{
                      fontSize: 11,
                      color: t.textDim,
                      padding: "8px 4px",
                      fontStyle: "italic",
                    }}
                  >
                    No matching skills.
                  </div>
                ) : (
                  pickerCandidates.map((s) => (
                    <button
                      key={s.id}
                      onClick={() =>
                        enrollMut.mutate(
                          { skillId: s.id, source: "manual" },
                          {
                            onSuccess: () => {
                              setShowAddPicker(false);
                              setPickerFilter("");
                            },
                          }
                        )
                      }
                      disabled={enrollMut.isPending}
                      style={{
                        display: "block",
                        width: "100%",
                        textAlign: "left",
                        padding: "6px 4px",
                        background: "none",
                        border: "none",
                        borderBottom: `1px solid ${t.surfaceBorder}`,
                        cursor: "pointer",
                        color: t.text,
                      }}
                    >
                      <div
                        style={{
                          display: "flex", flexDirection: "row",
                          alignItems: "center",
                          gap: 6,
                          fontSize: 12,
                        }}
                      >
                        <span style={{ fontWeight: 500 }}>{s.name}</span>
                        <span
                          style={{
                            fontSize: 10,
                            color: t.textDim,
                            fontFamily: "monospace",
                          }}
                        >
                          {s.id}
                        </span>
                      </div>
                      {s.description && (
                        <div
                          style={{
                            fontSize: 10,
                            color: t.textDim,
                            marginTop: 2,
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                        >
                          {s.description}
                        </div>
                      )}
                    </button>
                  ))
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Authored skill removal modal */}
      {removeTarget && (
        <RemoveAuthoredSkillModal
          skill={removeTarget}
          botName={botName}
          onCancel={() => setRemoveTarget(null)}
          onUnenroll={handleUnenrollOnly}
          onDelete={handleDeletePermanently}
          isDeleting={deleteMut.isPending}
          isUnenrolling={unenrollMut.isPending}
        />
      )}
    </AdvancedSection>
  );
}
