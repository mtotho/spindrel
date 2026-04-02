import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useWorkflows, useRecentWorkflowRuns } from "@/src/api/hooks/useWorkflows";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  Plus, Search, Zap, ChevronRight, HelpCircle,
  Loader2, CheckCircle2, XCircle, ShieldCheck, Clock, Minus,
} from "lucide-react";
import { Link, useRouter } from "expo-router";
import type { Workflow, WorkflowRun } from "@/src/types/api";

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
      return { color: t.textDim, bg: t.surfaceRaised, border: t.surfaceBorder, icon: HelpCircle, label: status };
  }
}

function fmtTimeAgo(iso: string): string {
  try {
    const d = new Date(iso);
    const now = new Date();
    const diffMs = now.getTime() - d.getTime();
    if (diffMs < 60000) return "just now";
    if (diffMs < 3600000) return `${Math.floor(diffMs / 60000)}m ago`;
    if (diffMs < 86400000) return `${Math.floor(diffMs / 3600000)}h ago`;
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
  } catch {
    return iso;
  }
}

// ---------------------------------------------------------------------------
// Recent Runs Feed
// ---------------------------------------------------------------------------

function RecentRunsFeed({ runs, t }: { runs: WorkflowRun[]; t: ThemeTokens }) {
  if (runs.length === 0) return null;

  return (
    <div style={{ marginBottom: 20 }}>
      <div style={{
        display: "flex", alignItems: "center", gap: 8,
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

      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {runs.map((run) => (
          <RunRow key={run.id} run={run} t={t} />
        ))}
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
    <Link href={`/admin/workflows/${run.workflow_id}?tab=runs&run=${run.id}` as any} asChild>
      <Pressable
        style={{
          backgroundColor: t.surfaceRaised,
          borderRadius: 8,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          padding: 10,
        }}
      >
        <div style={{
          display: "flex", alignItems: "center", gap: 10,
        }}>
          {/* Status icon */}
          <div style={{
            width: 26, height: 26, borderRadius: 13, flexShrink: 0,
            display: "flex", alignItems: "center", justifyContent: "center",
            background: s.bg, border: `1px solid ${s.border}`,
          }}>
            <Icon size={13} color={s.color} />
          </div>

          {/* Main content */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: t.text }}>
                {run.workflow_id}
              </span>
              <span style={{
                display: "inline-flex", alignItems: "center", gap: 3,
                padding: "1px 6px", borderRadius: 4, fontSize: 10, fontWeight: 600,
                background: s.bg, border: `1px solid ${s.border}`, color: s.color,
              }}>
                {run.status.replace(/_/g, " ")}
              </span>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 3 }}>
              <span style={{ fontSize: 11, color: t.textDim }}>
                {run.bot_id}
              </span>
              {run.triggered_by && (
                <span style={{ fontSize: 11, color: t.textDim }}>
                  via {run.triggered_by}
                </span>
              )}
              <span style={{ fontSize: 11, color: t.textDim }}>
                {fmtTimeAgo(run.created_at)}
              </span>
            </div>
          </div>

          {/* Step progress */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexShrink: 0 }}>
            {/* Mini step bar */}
            <div style={{
              display: "flex", gap: 2, height: 4, borderRadius: 2,
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
      </Pressable>
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
      display: "flex", alignItems: "center", gap: 8,
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
  const router = useRouter();
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
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Workflows"
        right={
          <div style={{ display: "flex", gap: 8 }}>
            <button
              onClick={() => router.push("/admin/workflows/new" as any)}
              style={{
                display: "flex", alignItems: "center", gap: 6,
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

      {/* Pinned search bar */}
      <div style={{
        display: "flex", alignItems: "center", gap: 10,
        padding: "8px 16px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
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
        <View className="flex-1 items-center justify-center">
          <ActivityIndicator color={t.accent} />
        </View>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
          <View style={{ padding: 16, maxWidth: 960 }}>
            {/* Recent Runs feed — always at the top */}
            {recentRuns && recentRuns.length > 0 && !search && (
              <RecentRunsFeed runs={recentRuns} t={t} />
            )}

            {(!workflows || workflows.length === 0) && (
              <View style={{ alignItems: "center", paddingTop: 60 }}>
                <Zap size={32} color={t.textMuted} />
                <Text style={{ color: t.textMuted, marginTop: 12, fontSize: 14 }}>
                  No workflows yet. Create one or add YAML files to workflows/.
                </Text>
              </View>
            )}
            {workflows && workflows.length > 0 && filtered.length === 0 && (
              <View style={{ alignItems: "center", paddingTop: 60 }}>
                <Text style={{ color: t.textDim, fontSize: 13 }}>
                  No workflows match &quot;{search}&quot;
                </Text>
              </View>
            )}
            {renderItems.map((item) =>
              item.type === "header" ? (
                <SectionHeader key={item.key} label={item.label} count={item.count} />
              ) : (
                <View key={item.key} style={{ marginBottom: 8 }}>
                  <WorkflowCard workflow={item.workflow} t={t} />
                </View>
              ),
            )}
          </View>
        </RefreshableScrollView>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Workflow card
// ---------------------------------------------------------------------------

function WorkflowCard({ workflow: w, t }: { workflow: Workflow; t: ThemeTokens }) {
  return (
    <Link href={`/admin/workflows/${w.id}` as any} asChild>
      <Pressable
        style={{
          backgroundColor: t.surfaceRaised,
          borderRadius: 10,
          borderWidth: 1,
          borderColor: t.surfaceBorder,
          padding: 14,
        }}
      >
        <View style={{ flexDirection: "row", alignItems: "center", justifyContent: "space-between" }}>
          <View style={{ flex: 1 }}>
            {/* Name + source badge */}
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Zap size={16} color={t.accent} />
              <Text style={{ color: t.text, fontWeight: "600", fontSize: 14 }}>
                {w.name}
              </Text>
              {w.source_type !== "manual" && (
                <View style={{
                  backgroundColor: t.accentSubtle, borderWidth: 1,
                  borderColor: t.accentBorder, paddingHorizontal: 6,
                  paddingVertical: 1, borderRadius: 4,
                }}>
                  <Text style={{ color: t.accent, fontSize: 10 }}>{w.source_type}</Text>
                </View>
              )}
              {w.session_mode === "shared" && (
                <View style={{
                  backgroundColor: t.purpleSubtle, borderWidth: 1,
                  borderColor: t.purpleBorder, paddingHorizontal: 6,
                  paddingVertical: 1, borderRadius: 4,
                }}>
                  <Text style={{ color: t.purple, fontSize: 10 }}>shared session</Text>
                </View>
              )}
            </View>

            {/* Description */}
            {w.description ? (
              <Text style={{ color: t.textMuted, fontSize: 12, marginTop: 4 }} numberOfLines={1}>
                {w.description}
              </Text>
            ) : null}

            {/* Metadata row */}
            <View style={{ flexDirection: "row", alignItems: "center", gap: 8, marginTop: 6, flexWrap: "wrap" }}>
              <Text style={{ color: t.textDim, fontSize: 11 }}>
                {w.steps.length} step{w.steps.length !== 1 ? "s" : ""}
              </Text>
              {Object.keys(w.params).length > 0 && (
                <Text style={{ color: t.textDim, fontSize: 11 }}>
                  {Object.keys(w.params).length} param{Object.keys(w.params).length !== 1 ? "s" : ""}
                </Text>
              )}
              {w.tags.length > 0 && (
                <View style={{ flexDirection: "row", gap: 4 }}>
                  {w.tags.map((tag) => (
                    <View key={tag} style={{
                      backgroundColor: t.purpleSubtle, borderWidth: 1,
                      borderColor: t.purpleBorder, paddingHorizontal: 5,
                      paddingVertical: 1, borderRadius: 3,
                    }}>
                      <Text style={{ color: t.purple, fontSize: 10 }}>{tag}</Text>
                    </View>
                  ))}
                </View>
              )}
            </View>
          </View>
          <ChevronRight size={16} color={t.textMuted} />
        </View>
      </Pressable>
    </Link>
  );
}
