import { useState, useEffect, useMemo } from "react";
import { ActivityIndicator, useWindowDimensions } from "react-native";
import { useRouter } from "expo-router";
import { Play, ExternalLink, ChevronDown, ChevronRight, Clock, Zap, Sparkles } from "lucide-react";
import { ToolCallsList } from "@/src/components/shared/ToolCallsList";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col,
} from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { apiFetch } from "@/src/api/client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";

// ---------------------------------------------------------------------------
// Interval options for heartbeat (shared with main settings)
// ---------------------------------------------------------------------------
const INTERVAL_OPTIONS = [
  { label: "5 minutes", value: "5" },
  { label: "15 minutes", value: "15" },
  { label: "30 minutes", value: "30" },
  { label: "1 hour", value: "60" },
  { label: "2 hours", value: "120" },
  { label: "4 hours", value: "240" },
  { label: "8 hours", value: "480" },
  { label: "12 hours", value: "720" },
  { label: "24 hours", value: "1440" },
];

// ---------------------------------------------------------------------------
// Heartbeat History List (expandable rows with result + trace link)
// ---------------------------------------------------------------------------
function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function fmtTokens(n: number): string {
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function HeartbeatHistoryList({ history, isWide }: { history: any[]; isWide?: boolean }) {
  const t = useThemeTokens();
  const router = useRouter();
  const [expandedId, setExpandedId] = useState<string | null>(null);

  return (
    <>
      <div style={{ fontSize: 10, fontWeight: 600, color: t.textDim, letterSpacing: "0.05em", textTransform: "uppercase", marginBottom: 8 }}>
        Recent Runs
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {history.map((hb: any) => {
          const isExpanded = expandedId === hb.id;
          const hasContent = hb.result || hb.error || hb.correlation_id;
          return (
            <div key={hb.id}>
              <div
                onClick={() => hasContent && setExpandedId(isExpanded ? null : hb.id)}
                style={{
                  display: "flex", justifyContent: "space-between", alignItems: "center",
                  padding: "8px 12px", background: isExpanded ? t.surfaceOverlay : t.surfaceRaised,
                  borderRadius: isExpanded ? "6px 6px 0 0" : 6,
                  border: `1px solid ${isExpanded ? t.accent : t.surfaceOverlay}`,
                  cursor: hasContent ? "pointer" : "default",
                  transition: "background 0.1s, border-color 0.1s",
                }}
              >
                <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                  {hasContent && (
                    isExpanded
                      ? <ChevronDown size={12} color={t.textDim} />
                      : <ChevronRight size={12} color={t.textDim} />
                  )}
                  <span style={{ fontSize: 12, color: t.textMuted }}>
                    {new Date(hb.run_at).toLocaleString()}
                  </span>
                  {hb.completed_at && (
                    <span style={{ fontSize: 10, color: t.textDim }}>
                      ({Math.round((new Date(hb.completed_at).getTime() - new Date(hb.run_at).getTime()) / 1000)}s)
                    </span>
                  )}
                </div>
                <span style={{
                  fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                  background: hb.status === "complete" ? t.successSubtle : hb.status === "failed" ? t.dangerSubtle : t.surfaceBorder,
                  color: hb.status === "complete" ? t.success : hb.status === "failed" ? t.danger : t.textMuted,
                }}>
                  {hb.status}
                </span>
              </div>
              {isExpanded && (
                <div style={{
                  padding: "10px 12px", background: "#151515",
                  borderRadius: "0 0 6px 6px",
                  border: `1px solid ${t.accent}`, borderTop: "none",
                }}>
                  {hb.error && (
                    <div style={{
                      fontSize: 12, color: t.danger, marginBottom: 8,
                      padding: "6px 8px", background: t.dangerSubtle, borderRadius: 4, border: `1px solid ${t.dangerBorder}`,
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>
                      {hb.error}
                    </div>
                  )}
                  {hb.result && (
                    <div style={{
                      fontSize: 12, color: t.text, lineHeight: 1.5,
                      maxHeight: 200, overflowY: "auto",
                      whiteSpace: "pre-wrap", wordBreak: "break-word",
                    }}>
                      {hb.result}
                    </div>
                  )}
                  {/* Stats row */}
                  {(hb.iterations > 0 || hb.total_tokens > 0 || hb.duration_ms != null) && (
                    <div style={{
                      display: "flex", alignItems: "center", gap: 12,
                      marginTop: 8, fontSize: 10, color: t.textDim,
                    }}>
                      {hb.duration_ms != null && (
                        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                          <Clock size={10} /> {fmtDuration(hb.duration_ms)}
                        </span>
                      )}
                      {hb.total_tokens > 0 && (
                        <span style={{ display: "flex", alignItems: "center", gap: 3 }}>
                          <Zap size={10} /> {fmtTokens(hb.total_tokens)} tokens
                        </span>
                      )}
                      {hb.iterations > 0 && (
                        <span>{hb.iterations} iter</span>
                      )}
                    </div>
                  )}
                  {/* Tool calls */}
                  {hb.tool_calls?.length > 0 && (
                    <ToolCallsList toolCalls={hb.tool_calls} isWide={isWide} />
                  )}
                  {hb.correlation_id && (
                    <div
                      onClick={() => router.push(`/admin/logs/${hb.correlation_id}`)}
                      style={{
                        display: "inline-flex", alignItems: "center", gap: 5,
                        marginTop: 8, fontSize: 11, color: t.accent, cursor: "pointer",
                      }}
                    >
                      <ExternalLink size={11} color={t.accent} />
                      View trace
                    </div>
                  )}
                  {!hb.result && !hb.error && (
                    <div style={{ fontSize: 11, color: t.textDim, fontStyle: "italic" }}>No output recorded</div>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </>
  );
}

// ---------------------------------------------------------------------------
// Context Preview Builder
// ---------------------------------------------------------------------------
function buildMetadataPreview(form: any, data: any): string {
  const interval = form?.interval_minutes ?? 60;
  const dispatchResults = form?.dispatch_results ?? true;
  const dispatchMode = form?.dispatch_mode ?? "always";
  const prevMaxChars = form?.previous_result_max_chars;
  const globalDefault = data?.default_previous_result_chars ?? 500;
  const effectiveMax = prevMaxChars ?? globalDefault;

  const lines = [
    "[SCHEDULED HEARTBEAT]",
    "You are running a scheduled heartbeat — an automated periodic prompt (not a user message).",
    "Your job: follow the prompt below, analyze what is relevant, and produce a concise result.",
    "Current time: {current_time}",
    `Channel: ${data?.channel_name ?? "{channel_name}"}`,
    `Heartbeat interval: every ${interval} minutes`,
    "Run number: {run_number}",
    "Last heartbeat: {last_run_time}",
    "Activity since last heartbeat: {activity_summary}",
  ];

  if (effectiveMax === 0) {
    lines.push("Previous heartbeat conclusion: {full_previous_result}");
  } else {
    lines.push(`Previous heartbeat conclusion: {previous_result_truncated_to_${effectiveMax}_chars}`);
    lines.push("(Use get_last_heartbeat tool for full previous output if needed)");
  }

  if (dispatchResults && dispatchMode === "optional") {
    lines.push(
      "Dispatch: Your response will NOT be automatically posted. " +
      "You have a post_heartbeat_to_channel tool \u2014 call it ONLY if you have " +
      "something worth sharing. If nothing noteworthy, just respond normally " +
      "and nothing will be posted to the channel."
    );
  } else if (dispatchResults) {
    lines.push("Dispatch: Your response will be posted to the channel.");
  }

  const repEnabled = form?.repetition_detection ?? data?.default_repetition_detection ?? true;
  if (repEnabled) {
    lines.push("");
    lines.push("Recent heartbeat outputs (newest first):");
    lines.push("  #1 ({N}m ago): {first_line_of_result} [tools: ...]");
    lines.push("  #2 ({N}m ago): {first_line_of_result} [tools: ...]");
    lines.push("");
    lines.push("{repetition_warning_if_detected}");
  }

  lines.push(
    "",
    "--- [system: current-turn marker] ---",
    "Everything above is context and conversation history. The user's CURRENT message follows — respond to it directly.",
    "",
    "--- [user message: heartbeat prompt] ---",
    "{heartbeat_prompt}",
  );
  return lines.join("\n");
}

function ContextPreview({ form, data }: { form: any; data: any }) {
  const t = useThemeTokens();
  const [expanded, setExpanded] = useState(false);
  const preview = useMemo(() => buildMetadataPreview(form, data), [form, data]);

  return (
    <div style={{ marginTop: 20 }}>
      <div
        onClick={() => setExpanded((v) => !v)}
        style={{
          display: "flex", alignItems: "center", gap: 6, cursor: "pointer",
          fontSize: 11, fontWeight: 600, color: t.textDim,
          letterSpacing: "0.05em", textTransform: "uppercase",
        }}
      >
        {expanded ? <ChevronDown size={12} color={t.textDim} /> : <ChevronRight size={12} color={t.textDim} />}
        Context Preview
      </div>
      {expanded && (
        <pre style={{
          marginTop: 8, padding: 12, background: "#111", borderRadius: 6,
          border: `1px solid ${t.surfaceBorder}`,
          fontSize: 11, lineHeight: 1.6, color: t.textMuted,
          whiteSpace: "pre-wrap", wordBreak: "break-word",
          maxHeight: 400, overflowY: "auto",
          fontFamily: "monospace",
        }}>
          {preview}
        </pre>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Heartbeat Tab
// ---------------------------------------------------------------------------
export function HeartbeatTab({ channelId, workspaceId, botModel }: { channelId: string; workspaceId?: string | null; botModel?: string }) {
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-heartbeat", channelId],
    queryFn: () => apiFetch<any>(`/api/v1/admin/channels/${channelId}/heartbeat`),
  });

  const [hbForm, setHbForm] = useState<any>(null);
  const [hbSaved, setHbSaved] = useState(false);

  useEffect(() => {
    if (data?.config) {
      setHbForm({
        interval_minutes: data.config.interval_minutes ?? 60,
        model: data.config.model ?? "",
        model_provider_id: data.config.model_provider_id ?? "",
        fallback_models: data.config.fallback_models ?? [],
        prompt: data.config.prompt ?? "",
        dispatch_results: data.config.dispatch_results ?? true,
        dispatch_mode: data.config.dispatch_mode ?? "always",
        trigger_response: data.config.trigger_response ?? false,
        prompt_template_id: data.config.prompt_template_id ?? null,
        workspace_file_path: data.config.workspace_file_path ?? null,
        workspace_id: data.config.workspace_id ?? null,
        max_run_seconds: data.config.max_run_seconds ?? null,
        previous_result_max_chars: data.config.previous_result_max_chars ?? null,
        repetition_detection: data.config.repetition_detection ?? null,
      });
    } else if (data && !data.config) {
      setHbForm({
        interval_minutes: 60,
        model: "",
        model_provider_id: "",
        fallback_models: [],
        prompt: "",
        dispatch_results: true,
        dispatch_mode: "always",
        trigger_response: false,
        prompt_template_id: null,
        workspace_file_path: null,
        workspace_id: null,
        max_run_seconds: null,
        previous_result_max_chars: null,
        repetition_detection: null,
      });
    }
  }, [data]);

  const toggleMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat/toggle`, { method: "POST" }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] }),
  });

  const saveMutation = useMutation({
    mutationFn: (body: any) => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      setHbSaved(true);
      setTimeout(() => setHbSaved(false), 2500);
    },
  });

  const [hbFired, setHbFired] = useState(false);
  const fireMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat/fire`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      setHbFired(true);
      setTimeout(() => setHbFired(false), 3000);
    },
  });

  const inferMutation = useMutation({
    mutationFn: () =>
      apiFetch<{ prompt: string; workspace_file_path: string | null; workspace_id: string | null }>(
        `/api/v1/admin/channels/${channelId}/heartbeat/infer`,
        { method: "POST" },
      ),
    onSuccess: (result) => {
      if (result.workspace_file_path) {
        setHbForm((f: any) => ({
          ...f,
          prompt: result.prompt,
          workspace_file_path: result.workspace_file_path,
          workspace_id: result.workspace_id,
          prompt_template_id: null,
        }));
      } else {
        setHbForm((f: any) => ({ ...f, prompt: result.prompt }));
      }
      queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
    },
  });

  if (isLoading || !hbForm) return <ActivityIndicator color={t.accent} />;

  const enabled = data?.config?.enabled ?? false;

  return (
    <>
      {/* Enable toggle + save */}
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <Section title="Heartbeat">
          <div />
        </Section>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button
            onClick={() => toggleMutation.mutate()}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", borderRadius: 8, fontSize: 13, fontWeight: 500, border: "none", cursor: "pointer",
              background: enabled ? t.successSubtle : t.surfaceBorder,
              color: enabled ? t.success : t.textMuted,
            }}
          >
            <span style={{
              width: 8, height: 8, borderRadius: 4,
              background: enabled ? t.success : t.textDim,
            }} />
            {enabled ? "Enabled" : "Disabled"}
          </button>
        </div>
      </div>

      <div style={{ opacity: enabled ? 1 : 0.5 }}>
        <Row>
          <Col>
            <FormRow label="Interval">
              <SelectInput
                value={hbForm.interval_minutes?.toString() ?? "60"}
                onChange={(v) => setHbForm((f: any) => ({ ...f, interval_minutes: parseInt(v) }))}
                options={INTERVAL_OPTIONS}
              />
            </FormRow>
          </Col>
          <Col>
            <LlmModelDropdown
              label="Model"
              value={hbForm.model ?? ""}
              onChange={(v) => setHbForm((f: any) => ({ ...f, model: v }))}
              placeholder={`inherit (${botModel ?? "bot default"})`}
              allowClear
            />
          </Col>
        </Row>

        <FormRow label="Fallback Models" description="Ordered fallback chain for heartbeat runs.">
          <FallbackModelList
            value={hbForm.fallback_models ?? []}
            onChange={(v) => setHbForm((f: any) => ({ ...f, fallback_models: v }))}
          />
        </FormRow>

        <div style={{ marginTop: 16 }}>
          <button
            onClick={() => inferMutation.mutate()}
            disabled={inferMutation.isPending}
            style={{
              display: "flex", alignItems: "center", gap: 6, marginBottom: 12,
              padding: "7px 14px", borderRadius: 6, border: `1px solid ${t.accent}40`,
              background: `${t.accent}12`, cursor: inferMutation.isPending ? "wait" : "pointer",
              fontSize: 12, fontWeight: 600, color: t.accent,
              opacity: inferMutation.isPending ? 0.6 : 1,
            }}
          >
            <Sparkles size={13} />
            {inferMutation.isPending ? "Inferring..." : "Infer Project Heartbeat"}
          </button>
          {inferMutation.isError && (
            <div style={{ fontSize: 11, color: t.danger, marginBottom: 8 }}>
              Failed to infer heartbeat: {(inferMutation.error as any)?.message || "Unknown error"}
            </div>
          )}
          <WorkspaceFilePrompt
            workspaceId={hbForm.workspace_id ?? workspaceId}
            filePath={hbForm.workspace_file_path}
            onLink={(path, wsId) => setHbForm((f: any) => ({ ...f, workspace_file_path: path, workspace_id: wsId, prompt_template_id: null }))}
            onUnlink={() => setHbForm((f: any) => ({ ...f, workspace_file_path: null, workspace_id: null }))}
          />
          {!hbForm.workspace_file_path && (
            <>
              <PromptTemplateLink
                templateId={hbForm.prompt_template_id ?? null}
                onLink={(id) => setHbForm((f: any) => ({ ...f, prompt_template_id: id }))}
                onUnlink={() => setHbForm((f: any) => ({ ...f, prompt_template_id: null }))}
              />
              <LlmPrompt
                value={hbForm.prompt ?? ""}
                onChange={(v) => setHbForm((f: any) => ({ ...f, prompt: v }))}
                label="Heartbeat Prompt"
                placeholder={hbForm.prompt_template_id ? "Using linked template..." : "Enter the heartbeat prompt..."}
                helpText="This prompt runs on the configured interval. Use @-tags to reference skills or tools."
                rows={10}
                fieldType="heartbeat"
                channelId={channelId}
              />
            </>
          )}
        </div>

        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
          <Toggle
            value={hbForm.dispatch_results ?? true}
            onChange={(v) => setHbForm((f: any) => ({ ...f, dispatch_results: v }))}
            label="Post results to channel"
          />
          {hbForm.dispatch_results && (
            <FormRow label="Dispatch mode" description="How heartbeat results are posted.">
              <SelectInput
                value={hbForm.dispatch_mode ?? "always"}
                onChange={(v) => setHbForm((f: any) => ({ ...f, dispatch_mode: v }))}
                options={[
                  { label: "Always post", value: "always" },
                  { label: "LLM decides (via tool)", value: "optional" },
                ]}
              />
            </FormRow>
          )}
          <Toggle
            value={hbForm.trigger_response ?? false}
            onChange={(v) => setHbForm((f: any) => ({ ...f, trigger_response: v }))}
            label="Trigger agent response after posting"
            description="After posting the heartbeat result, the bot will process it and respond again."
          />
          <Toggle
            value={hbForm.repetition_detection ?? data?.default_repetition_detection ?? true}
            onChange={(v) => {
              const globalDefault = data?.default_repetition_detection ?? true;
              setHbForm((f: any) => ({ ...f, repetition_detection: v === globalDefault ? null : v }));
            }}
            label="Repetition detection"
            description={`Warn when consecutive heartbeat outputs are too similar.${hbForm.repetition_detection === null ? " (using global default)" : ""}`}
          />
        </div>

        <div style={{ marginTop: 16, display: "flex", flexDirection: "column", gap: 12 }}>
          <FormRow label="Max run time (seconds)">
            <TextInput
              value={hbForm.max_run_seconds?.toString() ?? ""}
              onChangeText={(v) => setHbForm((f: any) => ({ ...f, max_run_seconds: v ? parseInt(v) || null : null }))}
              placeholder={`${data?.default_max_run_seconds ?? 1200} (default)`}
              type="number"
            />
          </FormRow>
          <FormRow label="Previous result max chars" description="Per-heartbeat override. 0 = no truncation.">
            <TextInput
              value={hbForm.previous_result_max_chars?.toString() ?? ""}
              onChangeText={(v) => setHbForm((f: any) => ({ ...f, previous_result_max_chars: v ? parseInt(v) || null : null }))}
              placeholder={`${data?.default_previous_result_chars ?? 500} (global default)`}
              type="number"
            />
          </FormRow>
        </div>

        <div style={{ marginTop: 20, display: "flex", gap: 8 }}>
          <button
            onClick={() => saveMutation.mutate(hbForm)}
            style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              background: hbSaved ? t.successSubtle : t.accent,
              color: hbSaved ? t.success : "#fff",
              fontSize: 13, fontWeight: 600,
            }}
          >
            {hbSaved ? "Saved!" : saveMutation.isPending ? "Saving..." : "Save Heartbeat"}
          </button>
          <button
            onClick={() => fireMutation.mutate()}
            disabled={!hbForm.prompt && !hbForm.prompt_template_id && !hbForm.workspace_file_path}
            style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              background: hbFired ? t.successSubtle : (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? t.warningSubtle : t.surfaceBorder,
              color: hbFired ? t.success : (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? t.warningMuted : t.textDim,
              fontSize: 13, fontWeight: 500,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <Play size={12} color={hbFired ? t.success : (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? t.warningMuted : t.textDim} />
            {hbFired ? "Fired!" : fireMutation.isPending ? "Firing..." : "Run Now"}
          </button>
        </div>
      </div>

      {/* Context Preview */}
      <ContextPreview form={hbForm} data={data} />

      {/* Status + History */}
      {data?.config && (
        <div style={{ marginTop: 24, borderTop: `1px solid ${t.surfaceBorder}`, paddingTop: 16 }}>
          <div style={{ fontSize: 12, color: t.textDim, display: "flex", gap: 16, marginBottom: 12 }}>
            {data.config.last_run_at && (
              <span>Last run: <span style={{ color: t.textMuted }}>{new Date(data.config.last_run_at).toLocaleString()}</span></span>
            )}
            {data.config.next_run_at && enabled && (
              <span>Next run: <span style={{ color: t.textMuted }}>{new Date(data.config.next_run_at).toLocaleString()}</span></span>
            )}
          </div>

          {data.history?.length > 0 && (
            <HeartbeatHistoryList history={data.history} isWide={isWide} />
          )}
        </div>
      )}
    </>
  );
}
