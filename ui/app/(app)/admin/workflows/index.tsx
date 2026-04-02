import { useState, useMemo } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useWorkflows, useRecentWorkflowRuns } from "@/src/api/hooks/useWorkflows";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { Plus, Search, Zap, ChevronRight, HelpCircle, Loader2, CheckCircle2, XCircle, ShieldCheck } from "lucide-react";
import { Link, useRouter } from "expo-router";
import type { Workflow, WorkflowRun } from "@/src/types/api";

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "card"; key: string; workflow: Workflow };

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

export default function WorkflowsPage() {
  const t = useThemeTokens();
  const router = useRouter();
  const { data: workflows, isLoading } = useWorkflows();
  const { data: recentRuns } = useRecentWorkflowRuns();
  const { refreshing, onRefresh } = usePageRefresh([["workflows"], ["workflow-runs-recent"]]);
  const [search, setSearch] = useState("");

  // Map: workflow_id -> latest run
  const latestRunByWorkflow = useMemo(() => {
    const map = new Map<string, WorkflowRun>();
    if (!recentRuns) return map;
    for (const run of recentRuns) {
      if (!map.has(run.workflow_id)) map.set(run.workflow_id, run);
    }
    return map;
  }, [recentRuns]);

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
                  <WorkflowCard workflow={item.workflow} t={t} latestRun={latestRunByWorkflow.get(item.workflow.id)} />
                </View>
              ),
            )}
          </View>
        </RefreshableScrollView>
      )}
    </View>
  );
}

function getRunStatusStyle(status: string, t: ThemeTokens) {
  switch (status) {
    case "running":
      return { color: t.accent, icon: Loader2, label: "running" };
    case "complete":
    case "done":
      return { color: t.success, icon: CheckCircle2, label: "complete" };
    case "failed":
      return { color: t.danger, icon: XCircle, label: "failed" };
    case "awaiting_approval":
      return { color: t.warning, icon: ShieldCheck, label: "awaiting approval" };
    default:
      return { color: t.textDim, icon: HelpCircle, label: status };
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
    return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  } catch {
    return iso;
  }
}

function WorkflowCard({ workflow: w, t, latestRun }: { workflow: Workflow; t: ThemeTokens; latestRun?: WorkflowRun }) {
  const runStyle = latestRun ? getRunStatusStyle(latestRun.status, t) : null;
  const RunIcon = runStyle?.icon;

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
              {w.secrets.length > 0 && (
                <Text style={{ color: t.textDim, fontSize: 11 }}>
                  {w.secrets.length} secret{w.secrets.length !== 1 ? "s" : ""}
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
              {/* Latest run status */}
              {latestRun && runStyle && RunIcon && (
                <>
                  <View style={{ width: 1, height: 10, backgroundColor: t.surfaceBorder }} />
                  <View style={{ flexDirection: "row", alignItems: "center", gap: 4 }}>
                    <RunIcon size={11} color={runStyle.color} />
                    <Text style={{ color: runStyle.color, fontSize: 11, fontWeight: "500" }}>
                      {runStyle.label}
                    </Text>
                    <Text style={{ color: t.textDim, fontSize: 10 }}>
                      {fmtTimeAgo(latestRun.created_at)}
                    </Text>
                  </View>
                </>
              )}
            </View>
          </View>
          <ChevronRight size={16} color={t.textMuted} />
        </View>
      </Pressable>
    </Link>
  );
}
