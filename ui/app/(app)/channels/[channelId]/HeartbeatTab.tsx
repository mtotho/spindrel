import { useState, useEffect } from "react";
import { ActivityIndicator } from "react-native";
import { useRouter } from "expo-router";
import { Play, ExternalLink, ChevronDown, ChevronRight } from "lucide-react";
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
function HeartbeatHistoryList({ history }: { history: any[] }) {
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
                  background: hb.status === "complete" ? "#166534" : hb.status === "failed" ? "#7f1d1d" : t.surfaceBorder,
                  color: hb.status === "complete" ? "#86efac" : hb.status === "failed" ? "#fca5a5" : t.textMuted,
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
                      fontSize: 12, color: "#fca5a5", marginBottom: 8,
                      padding: "6px 8px", background: "#1a0505", borderRadius: 4, border: "1px solid #7f1d1d",
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
// Heartbeat Tab
// ---------------------------------------------------------------------------
export function HeartbeatTab({ channelId, workspaceId }: { channelId: string; workspaceId?: string | null }) {
  const t = useThemeTokens();
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
        trigger_response: data.config.trigger_response ?? false,
        prompt_template_id: data.config.prompt_template_id ?? null,
        workspace_file_path: data.config.workspace_file_path ?? null,
        workspace_id: data.config.workspace_id ?? null,
        max_run_seconds: data.config.max_run_seconds ?? null,
      });
    } else if (data && !data.config) {
      setHbForm({
        interval_minutes: 60,
        model: "",
        model_provider_id: "",
        fallback_models: [],
        prompt: "",
        dispatch_results: true,
        trigger_response: false,
        prompt_template_id: null,
        workspace_file_path: null,
        workspace_id: null,
        max_run_seconds: null,
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
              background: enabled ? "#166534" : t.surfaceBorder,
              color: enabled ? "#86efac" : t.textMuted,
            }}
          >
            <span style={{
              width: 8, height: 8, borderRadius: 4,
              background: enabled ? "#86efac" : t.textDim,
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
              placeholder="Select model..."
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
                generateContext="A prompt for a scheduled/periodic AI task. Runs on a timer. The AI can check on things, perform maintenance, proactively engage, or run recurring workflows. Supports @-tags for tools and skills."
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
          <Toggle
            value={hbForm.trigger_response ?? false}
            onChange={(v) => setHbForm((f: any) => ({ ...f, trigger_response: v }))}
            label="Trigger agent response after posting"
            description="After posting the heartbeat result, the bot will process it and respond again."
          />
        </div>

        <div style={{ marginTop: 16 }}>
          <FormRow label="Max run time (seconds)">
            <TextInput
              value={hbForm.max_run_seconds?.toString() ?? ""}
              onChangeText={(v) => setHbForm((f: any) => ({ ...f, max_run_seconds: v ? parseInt(v) || null : null }))}
              placeholder={`${data?.default_max_run_seconds ?? 1200} (default)`}
              type="number"
            />
          </FormRow>
        </div>

        <div style={{ marginTop: 20, display: "flex", gap: 8 }}>
          <button
            onClick={() => saveMutation.mutate(hbForm)}
            style={{
              padding: "8px 20px", borderRadius: 8, border: "none", cursor: "pointer",
              background: hbSaved ? "rgba(34,197,94,0.15)" : t.accent,
              color: hbSaved ? "#22c55e" : "#fff",
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
              background: hbFired ? "rgba(34,197,94,0.15)" : (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? "#92400e" : t.surfaceBorder,
              color: hbFired ? "#22c55e" : (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? "#fcd34d" : t.textDim,
              fontSize: 13, fontWeight: 500,
              display: "flex", alignItems: "center", gap: 6,
            }}
          >
            <Play size={12} color={hbFired ? "#22c55e" : (hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path) ? "#fcd34d" : t.textDim} />
            {hbFired ? "Fired!" : fireMutation.isPending ? "Firing..." : "Run Now"}
          </button>
        </div>
      </div>

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
            <HeartbeatHistoryList history={data.history} />
          )}
        </div>
      )}
    </>
  );
}
