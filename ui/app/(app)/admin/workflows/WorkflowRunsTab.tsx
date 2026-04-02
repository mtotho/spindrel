import { useState, useEffect } from "react";
import { View, Text, Pressable, ActivityIndicator } from "react-native";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import {
  useWorkflow,
  useWorkflowRuns,
  useTriggerWorkflow,
} from "@/src/api/hooks/useWorkflows";
import { useBots } from "@/src/api/hooks/useBots";
import {
  Play,
  ChevronRight,
} from "lucide-react";
import type { WorkflowRun } from "@/src/types/api";

import { StatusBadge, fmtTime } from "./WorkflowRunHelpers";
import WorkflowRunDetail from "./WorkflowRunDetail";

// ---------------------------------------------------------------------------
// Main tab
// ---------------------------------------------------------------------------

export default function WorkflowRunsTab({ workflowId, initialRunId }: { workflowId: string; initialRunId?: string }) {
  const t = useThemeTokens();
  const { data: runs, isLoading } = useWorkflowRuns(workflowId);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(initialRunId ?? null);
  const [showTrigger, setShowTrigger] = useState(false);

  if (selectedRunId) {
    return (
      <WorkflowRunDetail
        runId={selectedRunId}
        workflowId={workflowId}
        onBack={() => setSelectedRunId(null)}
        onNavigateToRun={(id) => setSelectedRunId(id)}
      />
    );
  }

  return (
    <View style={{ gap: 12 }}>
      {/* Header row */}
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <Text style={{ color: t.textMuted, fontSize: 12 }}>
          {runs ? `${runs.length} run${runs.length !== 1 ? "s" : ""}` : ""}
        </Text>
        <button
          onClick={() => setShowTrigger(!showTrigger)}
          style={{
            display: "flex", alignItems: "center", gap: 5,
            padding: "5px 12px", fontSize: 12, fontWeight: 600,
            border: "none", borderRadius: 6,
            background: t.accent, color: "#fff", cursor: "pointer",
          }}
        >
          <Play size={13} />
          Trigger Run
        </button>
      </div>

      {/* Trigger form */}
      {showTrigger && (
        <TriggerForm
          workflowId={workflowId}
          t={t}
          onTriggered={(runId) => {
            setShowTrigger(false);
            setSelectedRunId(runId);
          }}
          onCancel={() => setShowTrigger(false)}
        />
      )}

      {/* Run list */}
      {isLoading ? (
        <View style={{ alignItems: "center", padding: 24 }}>
          <ActivityIndicator color={t.accent} />
        </View>
      ) : !runs || runs.length === 0 ? (
        <div style={{
          padding: 32, textAlign: "center", color: t.textMuted, fontSize: 13,
          background: t.codeBg, borderRadius: 8, border: `1px solid ${t.surfaceBorder}`,
        }}>
          No runs yet. Trigger one to get started.
        </div>
      ) : (
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {runs.map((run) => (
            <RunCard key={run.id} run={run} t={t} onSelect={() => setSelectedRunId(run.id)} />
          ))}
        </div>
      )}
    </View>
  );
}

// ---------------------------------------------------------------------------
// Run card (list item)
// ---------------------------------------------------------------------------

function RunCard({ run, t, onSelect }: { run: WorkflowRun; t: ThemeTokens; onSelect: () => void }) {
  const doneSteps = run.step_states.filter((s) =>
    s.status === "done" || s.status === "skipped" || s.status === "failed"
  ).length;
  const totalSteps = run.step_states.length;

  return (
    <Pressable
      onPress={onSelect}
      style={{
        backgroundColor: t.codeBg, borderRadius: 8,
        borderWidth: 1, borderColor: t.surfaceBorder, padding: 12,
      }}
    >
      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <StatusBadge status={run.status} t={t} />
          <span style={{ fontSize: 12, color: t.textDim, fontFamily: "monospace" }}>
            {run.id.slice(0, 8)}
          </span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 11, color: t.textDim }}>
            {doneSteps}/{totalSteps} steps
          </span>
          <ChevronRight size={14} color={t.textDim} />
        </div>
      </div>
      <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
        <span style={{ fontSize: 11, color: t.textDim }}>
          bot: {run.bot_id}
        </span>
        {run.triggered_by && (
          <span style={{ fontSize: 11, color: t.textDim }}>
            via {run.triggered_by}
          </span>
        )}
        {run.session_mode === "shared" && (
          <span style={{
            fontSize: 10, color: t.purple, background: t.purpleSubtle,
            border: `1px solid ${t.purpleBorder}`, borderRadius: 4,
            padding: "0 5px",
          }}>
            shared
          </span>
        )}
        <span style={{ fontSize: 11, color: t.textDim }}>
          {fmtTime(run.created_at)}
        </span>
      </div>
      {/* Mini step bar */}
      <div style={{ display: "flex", gap: 2, marginTop: 8, height: 4, borderRadius: 2, overflow: "hidden" }}>
        {run.step_states.map((s, i) => {
          const color =
            s.status === "done" ? t.success :
            s.status === "running" ? t.accent :
            s.status === "failed" ? t.danger :
            s.status === "skipped" ? t.surfaceBorder :
            t.inputBorder;
          return <div key={i} style={{ flex: 1, background: color, borderRadius: 1 }} />;
        })}
      </div>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Trigger form with proper param fields + bot dropdown
// ---------------------------------------------------------------------------

function TriggerForm({
  workflowId, t, onTriggered, onCancel,
}: {
  workflowId: string;
  t: ThemeTokens;
  onTriggered: (runId: string) => void;
  onCancel: () => void;
}) {
  const { data: workflow } = useWorkflow(workflowId);
  const { data: bots } = useBots();
  const triggerMut = useTriggerWorkflow(workflowId);

  const paramDefs = workflow?.params || {};
  const defaultBot = workflow?.defaults?.bot_id || "";
  const hasParams = Object.keys(paramDefs).length > 0;

  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [botId, setBotId] = useState("");
  const [sessionMode, setSessionMode] = useState("");
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (!workflow) return;
    const defaults: Record<string, string> = {};
    for (const [k, v] of Object.entries(workflow.params || {})) {
      const def = v as any;
      if (def.default != null) defaults[k] = String(def.default);
    }
    setParamValues((prev) => ({ ...defaults, ...prev }));
  }, [workflow]);

  const handleTrigger = async () => {
    setValidationErrors({});
    const params: Record<string, any> = {};
    for (const [k, v] of Object.entries(paramDefs)) {
      const def = v as any;
      const val = paramValues[k];
      if (def.required && (!val || val.trim() === "")) {
        setValidationErrors((prev) => ({ ...prev, [k]: `"${k}" is required` }));
        return;
      }
      if (val !== undefined && val !== "") {
        if (def.type === "number") params[k] = Number(val);
        else if (def.type === "boolean") params[k] = val === "true";
        else params[k] = val;
      }
    }

    try {
      const run = await triggerMut.mutateAsync({
        params,
        bot_id: botId || defaultBot || undefined,
        session_mode: sessionMode || undefined,
      });
      onTriggered(run.id);
    } catch {
      // handled by mutation
    }
  };

  const inputStyle: React.CSSProperties = {
    background: t.inputBg, border: `1px solid ${t.inputBorder}`,
    borderRadius: 6, padding: "6px 10px", color: t.inputText,
    fontSize: 12, outline: "none", width: "100%",
  };

  return (
    <div style={{
      padding: 12, borderRadius: 8,
      background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
      display: "flex", flexDirection: "column", gap: 10,
    }}>
      <div style={{ fontSize: 13, fontWeight: 600, color: t.text }}>Trigger Workflow</div>

      {hasParams && (
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          {Object.entries(paramDefs).map(([name, def]: [string, any]) => (
            <div key={name} style={{ display: "flex", flexDirection: "column", gap: 3 }}>
              <label style={{ fontSize: 12, color: t.textMuted }}>
                {name}
                {def.required && <span style={{ color: t.danger }}> *</span>}
                {def.description && (
                  <span style={{ color: t.textDim, fontWeight: "normal" }}> — {def.description}</span>
                )}
              </label>
              {def.type === "boolean" ? (
                <select
                  value={paramValues[name] || ""}
                  onChange={(e) => {
                    setParamValues((p) => ({ ...p, [name]: e.target.value }));
                    setValidationErrors((prev) => { const n = { ...prev }; delete n[name]; return n; });
                  }}
                  style={{ ...inputStyle, padding: "6px 8px", borderColor: validationErrors[name] ? t.danger : t.inputBorder }}
                >
                  <option value="">— select —</option>
                  <option value="true">true</option>
                  <option value="false">false</option>
                </select>
              ) : (
                <input
                  value={paramValues[name] || ""}
                  onChange={(e) => {
                    setParamValues((p) => ({ ...p, [name]: e.target.value }));
                    setValidationErrors((prev) => { const n = { ...prev }; delete n[name]; return n; });
                  }}
                  placeholder={def.default != null ? `default: ${def.default}` : def.required ? "required" : "optional"}
                  style={{ ...inputStyle, borderColor: validationErrors[name] ? t.danger : t.inputBorder }}
                />
              )}
              {validationErrors[name] && (
                <span style={{ fontSize: 11, color: t.danger }}>{validationErrors[name]}</span>
              )}
            </div>
          ))}
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <label style={{ fontSize: 12, color: t.textMuted }}>
          Bot {defaultBot && <span style={{ color: t.textDim }}>(default: {defaultBot})</span>}
        </label>
        <select
          value={botId}
          onChange={(e) => setBotId(e.target.value)}
          style={{ ...inputStyle, padding: "6px 8px" }}
        >
          <option value="">{defaultBot ? `Default (${defaultBot})` : "\u2014 select bot \u2014"}</option>
          {bots?.map((b) => (
            <option key={b.id} value={b.id}>{b.name || b.id}</option>
          ))}
        </select>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
        <label style={{ fontSize: 12, color: t.textMuted }}>
          Session Mode <span style={{ color: t.textDim }}>(default: {workflow?.session_mode || "isolated"})</span>
        </label>
        <select
          value={sessionMode}
          onChange={(e) => setSessionMode(e.target.value)}
          style={{ ...inputStyle, padding: "6px 8px" }}
        >
          <option value="">Default ({workflow?.session_mode || "isolated"})</option>
          <option value="isolated">Isolated (separate context per step)</option>
          <option value="shared">Shared (visible in chat)</option>
        </select>
      </div>

      {triggerMut.isError && (
        <div style={{ color: t.danger, fontSize: 12 }}>
          {triggerMut.error?.message || "Trigger failed"}
        </div>
      )}

      <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
        <button
          onClick={onCancel}
          style={{
            padding: "5px 12px", fontSize: 12, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, background: "transparent", color: t.textMuted, cursor: "pointer",
          }}
        >
          Cancel
        </button>
        <button
          onClick={handleTrigger}
          disabled={triggerMut.isPending}
          style={{
            display: "flex", alignItems: "center", gap: 4,
            padding: "5px 12px", fontSize: 12, fontWeight: 600,
            border: "none", borderRadius: 6,
            background: t.accent, color: "#fff", cursor: "pointer",
            opacity: triggerMut.isPending ? 0.6 : 1,
          }}
        >
          <Play size={13} />
          {triggerMut.isPending ? "Triggering..." : "Run"}
        </button>
      </div>
    </div>
  );
}
