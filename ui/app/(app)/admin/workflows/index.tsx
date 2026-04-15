/**
 * Workflow list page — searchable, grouped by source type, with recent runs feed.
 */
import { Spinner } from "@/src/components/shared/Spinner";
import { useState, useMemo } from "react";

import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useWorkflows, useRecentWorkflowRuns } from "@/src/api/hooks/useWorkflows";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Plus, Search, Zap, ChevronRight,
  Loader2, CheckCircle2, XCircle, ShieldCheck, Clock, Minus,
  Bot, Terminal,
} from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import type { Workflow, WorkflowRun } from "@/src/types/api";
import { fmtTime } from "./WorkflowRunHelpers";
import { StatusFilterChips, filterRuns, type RunStatusFilter } from "./StatusFilterChips";

// ---------------------------------------------------------------------------
// Status helpers
// ---------------------------------------------------------------------------

function getRunStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { color: t.accent, bg: t.accentSubtle, border: t.accentBorder, icon: Loader2, label: "running" };
    case "complete":
    case "done":
      return { color: t.success, bg: t.successSubtle, border: t.successBorder, icon: CheckCircle2, label: "complete" };
    case "failed":
      return { color: t.danger, bg: t.dangerSubtle, border: t.dangerBorder, icon: XCircle, label: "failed" };
    case "cancelled":
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: Minus, label: "cancelled" };
    case "awaiting_approval":
      return { color: t.warning, bg: t.warningSubtle, border: t.warningBorder, icon: ShieldCheck, label: "awaiting approval" };
    default:
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: Clock, label: status };
  }
}

// Step type icon for card
const STEP_TYPE_ICONS: Record<string, { icon: typeof Bot; color: (t: ThemeTokens) => string }> = {
  agent: { icon: Bot, color: (t) => t.accent },
  tool: { icon: Zap, color: (t) => t.purple },
  exec: { icon: Terminal, color: (t) => t.warning },
};

// ---------------------------------------------------------------------------
// Recent Runs Feed
// ---------------------------------------------------------------------------

function RecentRunsFeed({ runs, t }: { runs: WorkflowRun[]; t: ThemeTokens }) {
  const [statusFilter, setStatusFilter] = useState<RunStatusFilter>("all");
  const filtered = useMemo(() => filterRuns(runs, statusFilter), [runs, statusFilter]);

  if (runs.length === 0) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
        marginBottom: 10,
      }}>
        <Clock size={13} color={t.textMuted} />
        <span style={{
          fontSize: 11, fontWeight: 600, color: t.textMuted,
          textTransform: "uppercase", letterSpacing: 1,
        }}>
          Recent Runs
        </span>
        <span style={{ fontSize: 10, color: t.textDim }}>{runs.length}</span>
        <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
      </div>

      <div style={{ marginBottom: 8 }}>
        <StatusFilterChips runs={runs} active={statusFilter} onChange={setStatusFilter} />
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {filtered.map((run) => (
          <RunRow key={run.id} run={run} t={t} />
        ))}
        {filtered.length === 0 && statusFilter !== "all" && (
          <div style={{ padding: 16, textAlign: "center", color: t.textDim, fontSize: 12 }}>
            No {statusFilter.replace(/_/g, " ")} runs.
          </div>
        )}
      </div>
    </div>
  );
}

function RunRow({ run, t }: { run: WorkflowRun; t: ThemeTokens }) {
  const s = getRunStatusStyle(run.status, t);
  const Icon = s.icon;
  const doneSteps = run.step_states.filter(
    (st) => st.status === "done" || st.status === "skipped" || st.status === "failed"
  ).length;
  const totalSteps = run.step_states.length;

  return (
    <Link to={`/admin/workflows/${run.workflow_id}?tab=runs&run=${run.id}` as any}>
      <button type="button"
        style={{
          backgroundColor: t.codeBg,
          borderRadius: 8,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          padding: 10,
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10 }}>
          {/* Status icon */}
          <div style={{
            width: 26, height: 26, borderRadius: 13, flexShrink: 0,
            display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "center",
            background: s.bg, border: `1px solid ${s.border}`,
          }}>
            <Icon size={13} color={s.color} />
          </div>

          {/* Main content */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                {run.workflow_id}
              </span>
              <span style={{
                display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 3,
                padding: "1px 6px", borderRadius: 4, fontSize: 10, fontWeight: 600,
                background: s.bg, border: `1px solid ${s.border}`, color: s.color,
              }}>
                {run.status.replace(/_/g, " ")}
              </span>
            </div>
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, marginTop: 3 }}>
              <span style={{ fontSize: 11, color: t.textMuted }}>{run.bot_id}</span>
              {run.triggered_by && (
                <span style={{ fontSize: 11, color: t.textMuted }}>via {run.triggered_by}</span>
              )}
              <span style={{ fontSize: 11, color: t.textMuted }}>{fmtTime(run.created_at)}</span>
            </div>
          </div>

          {/* Step progress */}
          <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexShrink: 0 }}>
            <div style={{
              display: "flex", flexDirection: "row", gap: 2, height: 4, borderRadius: 2,
              overflow: "hidden", width: 60,
            }}>
              {run.step_states.map((st, i) => {
                const color =
                  st.status === "done" ? t.success :
                  st.status === "running" ? t.accent :
                  st.status === "failed" ? t.danger :
                  st.status === "skipped" ? t.surfaceBorder :
                  t.inputBorder;
                return <div key={i} style={{ flex: 1, background: color, borderRadius: 1 }} />;
              })}
            </div>
            <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
              {doneSteps}/{totalSteps}
            </span>
            <ChevronRight size={14} color={t.textDim} />
          </div>
        </div>
      </button>
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Section headers
// ---------------------------------------------------------------------------

function SectionHeader({ label, count }: { label: string; count: number }) {
  const t = useThemeTokens();
  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
      padding: "14px 0 6px 0",
    }}>
      <span style={{
        fontSize: 11, fontWeight: 600, color: t.textMuted,
        textTransform: "uppercase", letterSpacing: 1,
      }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color: t.textDim, fontWeight: 500 }}>{count}</span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "card"; key: string; workflow: Workflow };

export default function WorkflowsPage() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: workflows, isLoading } = useWorkflows();
  const { data: recentRuns } = useRecentWorkflowRuns();
  const { refreshing, onRefresh } = usePageRefresh([["workflows"], ["workflow-runs-recent"]]);
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!workflows) return [];
    const q = search.toLowerCase();
    if (!q) return workflows;
    return workflows.filter(
      (w) =>
        w.id.toLowerCase().includes(q) ||
        w.name.toLowerCase().includes(q) ||
        (w.description || "").toLowerCase().includes(q) ||
        w.tags.some((tag) => tag.toLowerCase().includes(q))
    );
  }, [workflows, search]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filtered.length) return [];

    const manual: Workflow[] = [];
    const file: Workflow[] = [];
    const integration: Workflow[] = [];

    for (const w of filtered) {
      if (w.source_type === "manual" || w.source_type === "bot") manual.push(w);
      else if (w.source_type === "integration") integration.push(w);
      else file.push(w);
    }

    const items: RenderItem[] = [];
    const addGroup = (key: string, label: string, list: Workflow[]) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length });
      for (const w of list) items.push({ type: "card", key: w.id, workflow: w });
    };

    addGroup("manual", "User Created", manual);
    addGroup("file", "File-Managed", file);
    addGroup("integration", "Integration", integration);

    return items;
  }, [filtered]);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Workflows"
        right={
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <button
              onClick={() => navigate("/admin/workflows/new")}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: "none", borderRadius: 6,
                background: t.accent, color: "#fff", cursor: "pointer",
              }}
            >
              <Plus size={14} />
              New
            </button>
          </div>
        }
      />

      {/* Search bar */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
        padding: "8px 16px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: 300, flex: 1,
        }}>
          <Search size={13} color={t.textDim} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter workflows..."
            style={{
              background: "none", border: "none", outline: "none",
              color: t.text, fontSize: 12, flex: 1, width: "100%",
            }}
          />
        </div>
        {workflows && workflows.length > 0 && (
          <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
            {search && filtered.length !== workflows.length
              ? `${filtered.length} / ${workflows.length}`
              : workflows.length}{" "}
            workflows
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner />
        </div>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
          <div style={{ padding: 16, maxWidth: 960 }}>
            {/* Recent Runs */}
            {recentRuns && recentRuns.length > 0 && !search && (
              <RecentRunsFeed runs={recentRuns} t={t} />
            )}

            {(!workflows || workflows.length === 0) && (
              <div style={{ display: "flex", alignItems: "center", paddingTop: 60, gap: 12 }}>
                <Zap size={36} color={t.surfaceBorder} />
                <span style={{ color: t.textMuted, fontSize: 15, fontWeight: "600" }}>
                  No workflows yet
                </span>
                <span style={{ color: t.textDim, fontSize: 13, textAlign: "center", maxWidth: 300 }}>
                  Create a workflow to automate multi-step tasks, or add YAML files to the workflows/ directory.
                </span>
                <button type="button"
                  onClick={() => navigate("/admin/workflows/new")}
                  style={{
                    display: "flex",
                    flexDirection: "row", alignItems: "center", gap: 6,
                    paddingInline: 16, paddingBlock: 8, borderRadius: 8,
                    backgroundColor: t.accent, marginTop: 8,
                  }}
                >
                  <Plus size={14} color="#fff" />
                  <span style={{ color: "#fff", fontSize: 13, fontWeight: "600" }}>Create Workflow</span>
                </button>
              </div>
            )}
            {workflows && workflows.length > 0 && filtered.length === 0 && (
              <div style={{ display: "flex", alignItems: "center", paddingTop: 60 }}>
                <span style={{ color: t.textDim, fontSize: 13 }}>
                  No workflows match &quot;{search}&quot;
                </span>
              </div>
            )}
            {renderItems.map((item) =>
              item.type === "header" ? (
                <SectionHeader key={item.key} label={item.label} count={item.count} />
              ) : (
                <div key={item.key} style={{ marginBottom: 8 }}>
                  <WorkflowCard workflow={item.workflow} recentRuns={recentRuns} t={t} />
                </div>
              ),
            )}
          </div>
        </RefreshableScrollView>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Workflow card
// ---------------------------------------------------------------------------

function WorkflowCard({ workflow: w, recentRuns, t }: {
  workflow: Workflow;
  recentRuns?: WorkflowRun[];
  t: ThemeTokens;
}) {
  // Get recent runs for this workflow (up to 5 status dots)
  const myRuns = useMemo(
    () => (recentRuns || []).filter((r) => r.workflow_id === w.id).slice(0, 5),
    [recentRuns, w.id],
  );

  // Compute step type summary
  const stepTypeSummary = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const step of w.steps) {
      const type = step.type || "agent";
      counts[type] = (counts[type] || 0) + 1;
    }
    return Object.entries(counts);
  }, [w.steps]);

  return (
    <Link to={`/admin/workflows/${w.id}` as any}>
      <button type="button"
        style={{
          backgroundColor: t.codeBg,
          borderRadius: 10,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          padding: 14,
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <div style={{ flex: 1 }}>
            {/* Name + badges */}
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
              <Zap size={16} color={t.accent} />
              <span style={{ color: t.text, fontWeight: "600", fontSize: 14 }}>
                {w.name}
              </span>
              {w.source_type !== "manual" && (
                <div style={{
                  backgroundColor: t.accentSubtle, borderWidth: 1,
                  borderColor: t.accentBorder, paddingInline: 6,
                  paddingBlock: 1, borderRadius: 4,
                }}>
                  <span style={{ color: t.accent, fontSize: 10 }}>{w.source_type}</span>
                </div>
              )}
              {w.session_mode === "shared" && (
                <div style={{
                  backgroundColor: t.purpleSubtle, borderWidth: 1,
                  borderColor: t.purpleBorder, paddingInline: 6,
                  paddingBlock: 1, borderRadius: 4,
                }}>
                  <span style={{ color: t.purple, fontSize: 10 }}>shared</span>
                </div>
              )}
            </div>

            {/* Description */}
            {w.description ? (
              <span style={{ color: t.textMuted, fontSize: 12, marginTop: 4 }}>
                {w.description}
              </span>
            ) : null}

            {/* Metadata row */}
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 10, marginTop: 6, flexWrap: "wrap" }}>
              {/* Step type summary */}
              <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
                {stepTypeSummary.map(([type, count]) => {
                  const st = STEP_TYPE_ICONS[type] || STEP_TYPE_ICONS.agent;
                  const StIcon = st.icon;
                  return (
                    <span key={type} style={{
                      display: "inline-flex", flexDirection: "row", alignItems: "center", gap: 2,
                      fontSize: 11, color: t.textDim,
                    }}>
                      <StIcon size={10} color={st.color(t)} />
                      {count}
                    </span>
                  );
                })}
              </div>
              {Object.keys(w.params).length > 0 && (
                <span style={{ color: t.textDim, fontSize: 11 }}>
                  {Object.keys(w.params).length} param{Object.keys(w.params).length !== 1 ? "s" : ""}
                </span>
              )}
              {/* Tags */}
              {w.tags.length > 0 && (
                <div style={{ display: "flex", flexDirection: "row", gap: 4 }}>
                  {w.tags.map((tag) => (
                    <div key={tag} style={{
                      backgroundColor: t.purpleSubtle, borderWidth: 1,
                      borderColor: t.purpleBorder, paddingInline: 5,
                      paddingBlock: 1, borderRadius: 3,
                    }}>
                      <span style={{ color: t.purple, fontSize: 10 }}>{tag}</span>
                    </div>
                  ))}
                </div>
              )}
              {/* Mini run status dots */}
              {myRuns.length > 0 && (
                <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 3, marginLeft: 4 }}>
                  {myRuns.map((run) => {
                    const rs = getRunStatusStyle(run.status, t);
                    return (
                      <div key={run.id} style={{
                        width: 7, height: 7, borderRadius: 4,
                        background: rs.color,
                      }}
                      title={`${run.status} — ${fmtTime(run.created_at)}`}
                      />
                    );
                  })}
                </div>
              )}
            </div>
          </div>
          <ChevronRight size={16} color={t.textMuted} />
        </div>
      </button>
    </Link>
  );
}
