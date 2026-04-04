/**
 * Modal overlay for triggering a workflow run.
 * Extracted from WorkflowRunsTab — same form logic (params, bot/channel/session dropdowns).
 */
import { useState, useEffect } from "react";
import { Text, Pressable, ActivityIndicator } from "react-native";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useWorkflow,
  useTriggerWorkflow,
} from "@/src/api/hooks/useWorkflows";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannels } from "@/src/api/hooks/useChannels";
import { Play, X } from "lucide-react";

interface Props {
  workflowId: string;
  onTriggered: (runId: string) => void;
  onClose: () => void;
}

export default function WorkflowTriggerModal({ workflowId, onTriggered, onClose }: Props) {
  const t = useThemeTokens();
  const { data: workflow } = useWorkflow(workflowId);
  const { data: bots } = useBots();
  const { data: channels } = useChannels();
  const triggerMut = useTriggerWorkflow(workflowId);

  const paramDefs = workflow?.params || {};
  const defaultBot = workflow?.defaults?.bot_id || "";
  const hasParams = Object.keys(paramDefs).length > 0;

  const [paramValues, setParamValues] = useState<Record<string, string>>({});
  const [botId, setBotId] = useState("");
  const [channelId, setChannelId] = useState("");
  const [sessionMode, setSessionMode] = useState("");
  const [validationErrors, setValidationErrors] = useState<Record<string, string>>({});

  // Escape key to close
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

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
        channel_id: channelId || undefined,
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
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed", inset: 0,
          background: "rgba(0,0,0,0.5)", zIndex: 10000,
        }}
      />
      {/* Card */}
      <div style={{
        position: "fixed", top: "50%", left: "50%",
        transform: "translate(-50%, -50%)",
        width: "min(90vw, 480px)", maxHeight: "80vh",
        background: t.codeBg, border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 12, zIndex: 10001,
        display: "flex", flexDirection: "column",
        boxShadow: `0 20px 60px ${t.overlayLight}`,
        overflow: "hidden",
      }}>
        {/* Header */}
        <div style={{
          display: "flex", alignItems: "center", justifyContent: "space-between",
          padding: "12px 16px", borderBottom: `1px solid ${t.surfaceBorder}`,
        }}>
          <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>Trigger Workflow</span>
          <Pressable onPress={onClose}>
            <X size={18} color={t.textMuted} />
          </Pressable>
        </div>

        {/* Body */}
        <div style={{
          flex: 1, overflow: "auto", padding: 16,
          display: "flex", flexDirection: "column", gap: 12,
        }}>
          {/* Param fields */}
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

          {/* Bot dropdown */}
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

          {/* Channel dropdown */}
          <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
            <label style={{ fontSize: 12, color: t.textMuted }}>
              Channel <span style={{ color: t.textDim }}>(optional — binds run to a channel)</span>
            </label>
            <select
              value={channelId}
              onChange={(e) => setChannelId(e.target.value)}
              style={{ ...inputStyle, padding: "6px 8px" }}
            >
              <option value="">None (headless)</option>
              {channels?.map((ch) => (
                <option key={ch.id} value={ch.id}>
                  {ch.display_name || ch.name || ch.client_id} ({ch.bot_id})
                </option>
              ))}
            </select>
          </div>

          {/* Session mode */}
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

          {/* Error */}
          {triggerMut.isError && (
            <div style={{ color: t.danger, fontSize: 12 }}>
              {triggerMut.error?.message || "Trigger failed"}
            </div>
          )}
        </div>

        {/* Footer */}
        <div style={{
          display: "flex", gap: 8, justifyContent: "flex-end",
          padding: "12px 16px", borderTop: `1px solid ${t.surfaceBorder}`,
        }}>
          <button
            onClick={onClose}
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
    </>
  );
}
