import { useState, useEffect } from "react";
import { ActivityIndicator } from "react-native";
import { useIsMobile } from "@/src/hooks/useIsMobile";
import { Play, RotateCcw, Pencil, FileText, Workflow as WorkflowIcon } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  Section, FormRow, TextInput, SelectInput, Toggle,
  Row, Col,
} from "@/src/components/shared/FormControls";
import { AdvancedSection, ActionButton } from "@/src/components/shared/SettingsControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { FallbackModelList } from "@/src/components/shared/FallbackModelList";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { PromptTemplateLink } from "@/src/components/shared/PromptTemplateLink";
import { WorkspaceFilePrompt } from "@/src/components/shared/WorkspaceFilePrompt";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import { apiFetch } from "@/src/api/client";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { WorkflowSelector } from "@/src/components/shared/WorkflowSelector";
import { useWorkflows } from "@/src/api/hooks/useWorkflows";

import { QuietHoursPicker } from "./QuietHoursPicker";
import { HeartbeatHistoryList } from "./HeartbeatHistoryList";
import { ContextPreview, HeartbeatTemplatePreview } from "./HeartbeatContextPreview";

// ---------------------------------------------------------------------------
// Interval options for heartbeat
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
// Heartbeat Tab
// ---------------------------------------------------------------------------
export function HeartbeatTab({ channelId, workspaceId, botModel }: { channelId: string; workspaceId?: string | null; botModel?: string }) {
  const t = useThemeTokens();
  const isMobile = useIsMobile();
  const queryClient = useQueryClient();
  const { data, isLoading } = useQuery({
    queryKey: ["channel-heartbeat", channelId],
    queryFn: () => apiFetch<any>(`/api/v1/admin/channels/${channelId}/heartbeat`),
  });

  const [hbForm, setHbForm] = useState<any>(null);
  const [hbSaved, setHbSaved] = useState(false);
  const [customizedFromTemplateId, setCustomizedFromTemplateId] = useState<string | null>(null);
  const [templatePreviewExpanded, setTemplatePreviewExpanded] = useState(false);

  // Fetch templates to render linked template content
  const { data: allTemplates } = usePromptTemplates();
  const linkedTemplate = allTemplates?.find((tpl) => tpl.id === hbForm?.prompt_template_id);

  // Fetch workflows for the workflow selector
  const { data: workflows } = useWorkflows();

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
        quiet_start: data.config.quiet_start ?? "",
        quiet_end: data.config.quiet_end ?? "",
        timezone: data.config.timezone ?? "",
        workflow_id: data.config.workflow_id ?? null,
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
        quiet_start: "",
        quiet_end: "",
        timezone: "",
        workflow_id: null,
      });
    }
  }, [data]);

  const toggleMutation = useMutation({
    mutationFn: () => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat/toggle`, { method: "POST" }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
    },
  });

  const saveMutation = useMutation({
    mutationFn: (body: any) => apiFetch(`/api/v1/admin/channels/${channelId}/heartbeat`, {
      method: "PUT",
      body: JSON.stringify(body),
    }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["channel-heartbeat", channelId] });
      queryClient.invalidateQueries({ queryKey: ["channels"] });
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
  const isWorkflowMode = !!hbForm.workflow_id;
  const hasAction = isWorkflowMode
    ? !!hbForm.workflow_id
    : !!(hbForm.prompt || hbForm.prompt_template_id || hbForm.workspace_file_path);

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
        {/* ---- Schedule Section ---- */}
        <Section title="Schedule">
          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 200}>
              <FormRow label="Interval">
                <SelectInput
                  value={hbForm.interval_minutes?.toString() ?? "60"}
                  onChange={(v) => setHbForm((f: any) => ({ ...f, interval_minutes: parseInt(v) }))}
                  options={INTERVAL_OPTIONS}
                />
              </FormRow>
            </Col>
          </Row>
        </Section>

        {/* ---- Action: Workflow or Prompt ---- */}
        <Section title="Action">
          {/* Mode toggle: Prompt (default) vs Workflow */}
          <div style={{ display: "flex", gap: 2, marginBottom: 12 }}>
            {[
              { key: "prompt", label: "Prompt", icon: <FileText size={12} /> },
              { key: "workflow", label: "Workflow", icon: <WorkflowIcon size={12} /> },
            ].map((tab) => {
              const isActive = tab.key === "workflow" ? isWorkflowMode : !isWorkflowMode;
              return (
                <button
                  key={tab.key}
                  onClick={() => {
                    if (tab.key === "workflow" && !isWorkflowMode) {
                      const firstWf = workflows?.[0];
                      setHbForm((f: any) => ({ ...f, workflow_id: firstWf?.id ?? "" }));
                    } else if (tab.key === "prompt" && isWorkflowMode) {
                      setHbForm((f: any) => ({ ...f, workflow_id: null }));
                    }
                  }}
                  style={{
                    display: "flex", alignItems: "center", gap: 5,
                    padding: "6px 14px", borderRadius: 6, cursor: "pointer",
                    fontSize: 12, fontWeight: isActive ? 600 : 400,
                    border: `1px solid ${isActive ? t.accent : t.surfaceBorder}`,
                    background: isActive ? `${t.accent}15` : "transparent",
                    color: isActive ? t.accent : t.textMuted,
                    transition: "all 0.12s",
                  }}
                >
                  {tab.icon}
                  {tab.label}
                </button>
              );
            })}
          </div>

          {isWorkflowMode ? (
            /* ---- Workflow Selector ---- */
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              <FormRow label="Workflow" description="This workflow will be triggered on each heartbeat interval.">
                <WorkflowSelector
                  value={hbForm.workflow_id}
                  onChange={(id) => setHbForm((f: any) => ({ ...f, workflow_id: id }))}
                />
              </FormRow>
              {hbForm.workflow_id && (() => {
                const wf = workflows?.find((w: any) => w.id === hbForm.workflow_id);
                if (!wf) return null;
                return (
                  <div style={{
                    padding: "8px 12px", borderRadius: 6,
                    background: t.codeBg, border: `1px solid ${t.codeBorder}`,
                    fontSize: 12, color: t.textMuted, lineHeight: 1.5,
                  }}>
                    {wf.description && <div style={{ marginBottom: 4 }}>{wf.description}</div>}
                    <div style={{ fontSize: 11, color: t.textDim }}>
                      {wf.steps?.length ?? 0} step{(wf.steps?.length ?? 0) !== 1 ? "s" : ""}
                      {wf.tags?.length ? ` · ${wf.tags.join(", ")}` : ""}
                    </div>
                  </div>
                );
              })()}
            </div>
          ) : (
            /* ---- Prompt Editor ---- */
            <>
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
                    onLink={(id) => {
                      setHbForm((f: any) => ({ ...f, prompt_template_id: id, prompt: "" }));
                      setCustomizedFromTemplateId(null);
                      setTemplatePreviewExpanded(false);
                    }}
                    onUnlink={() => {
                      setHbForm((f: any) => ({ ...f, prompt_template_id: null }));
                    }}
                  />

                  {/* Template linked — read-only preview with customize option */}
                  {hbForm.prompt_template_id && linkedTemplate ? (
                    <HeartbeatTemplatePreview
                      content={linkedTemplate.content}
                      description={linkedTemplate.description}
                      expanded={templatePreviewExpanded}
                      onToggleExpand={() => setTemplatePreviewExpanded((v) => !v)}
                      onCustomize={() => {
                        setCustomizedFromTemplateId(hbForm.prompt_template_id);
                        setHbForm((f: any) => ({
                          ...f,
                          prompt: linkedTemplate.content,
                          prompt_template_id: null,
                        }));
                      }}
                    />
                  ) : (
                    <>
                      {/* "Customized" badge with reset option */}
                      {customizedFromTemplateId && (
                        <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
                          <div style={{
                            display: "flex", alignItems: "center", gap: 4,
                            fontSize: 10, fontWeight: 600, color: t.warning,
                          }}>
                            <Pencil size={10} />
                            Customized from template
                          </div>
                          <button
                            onClick={() => {
                              setHbForm((f: any) => ({
                                ...f,
                                prompt_template_id: customizedFromTemplateId,
                                prompt: "",
                              }));
                              setCustomizedFromTemplateId(null);
                              setTemplatePreviewExpanded(false);
                            }}
                            style={{
                              display: "inline-flex", alignItems: "center", gap: 3,
                              padding: "2px 8px", borderRadius: 4, cursor: "pointer",
                              fontSize: 10, fontWeight: 600,
                              border: `1px solid ${t.surfaceBorder}`,
                              background: "transparent", color: t.textDim,
                            }}
                          >
                            <RotateCcw size={10} />
                            Reset to Template
                          </button>
                        </div>
                      )}
                      <LlmPrompt
                        value={hbForm.prompt ?? ""}
                        onChange={(v) => setHbForm((f: any) => ({ ...f, prompt: v }))}
                        label="Heartbeat Prompt"
                        placeholder="Enter the heartbeat prompt..."
                        helpText="This prompt runs on the configured interval. Use @-tags to reference skills or tools."
                        rows={10}
                        fieldType="heartbeat"
                        channelId={channelId}
                      />
                    </>
                  )}
                </>
              )}
            </>
          )}
        </Section>

        {/* ---- Dispatch Section (only for prompt mode) ---- */}
        {!isWorkflowMode && (
          <Section title="Dispatch">
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
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
            </div>
          </Section>
        )}

        {/* Save + Fire */}
        <div style={{ marginTop: 20, display: "flex", gap: 8 }}>
          <ActionButton
            label={hbSaved ? "Saved!" : saveMutation.isPending ? "Saving..." : "Save Heartbeat"}
            onPress={() => saveMutation.mutate(hbForm)}
            variant={hbSaved ? "secondary" : "primary"}
          />
          <ActionButton
            label={hbFired ? "Fired!" : fireMutation.isPending ? "Firing..." : "Run Now"}
            onPress={() => fireMutation.mutate()}
            variant="secondary"
            disabled={!hasAction}
            icon={<Play size={12} />}
          />
        </div>

        {/* ---- Advanced Section (only for prompt mode) ---- */}
        {!isWorkflowMode && (
          <AdvancedSection>
            <Section title="Quiet Hours">
              <QuietHoursPicker
                start={hbForm.quiet_start ?? ""}
                end={hbForm.quiet_end ?? ""}
                timezone={hbForm.timezone ?? ""}
                onChangeStart={(v) => setHbForm((f: any) => ({ ...f, quiet_start: v }))}
                onChangeEnd={(v) => setHbForm((f: any) => ({ ...f, quiet_end: v }))}
                onChangeTimezone={(v) => setHbForm((f: any) => ({ ...f, timezone: v }))}
                inheritedRange={data?.default_quiet_hours}
                defaultTimezone={data?.default_timezone}
              />
            </Section>
            <Section title="Detection">
              <Toggle
                value={hbForm.repetition_detection ?? data?.default_repetition_detection ?? true}
                onChange={(v) => {
                  const globalDefault = data?.default_repetition_detection ?? true;
                  setHbForm((f: any) => ({ ...f, repetition_detection: v === globalDefault ? null : v }));
                }}
                label="Repetition detection"
                description={`Warn when consecutive heartbeat outputs are too similar.${hbForm.repetition_detection === null ? " (using global default)" : ""}`}
              />
            </Section>
            <Section title="Model">
              <Row stack={isMobile}>
                <Col minWidth={isMobile ? 0 : 200}>
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
            </Section>
            <Section title="Limits">
              <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
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
            </Section>
            <ContextPreview form={hbForm} data={data} />
          </AdvancedSection>
        )}
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
            <HeartbeatHistoryList history={data.history} isWide={!isMobile} />
          )}
        </div>
      )}
    </>
  );
}
