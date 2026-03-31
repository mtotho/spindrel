import { useState, useEffect, useMemo, useCallback } from "react";
import { ActivityIndicator, useWindowDimensions } from "react-native";
import { useRouter } from "expo-router";
import { Play, ExternalLink, ChevronDown, ChevronRight, Clock, Zap, Sparkles, RotateCcw, AlertTriangle } from "lucide-react";
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
// Quiet hours presets + picker
// ---------------------------------------------------------------------------
const QUIET_PRESETS: ReadonlyArray<{
  label: string; start: string; end: string; description: string;
}> = [
  { label: "Overnight",   start: "22:00", end: "06:30", description: "10 PM \u2013 6:30 AM" },
  { label: "Late Night",  start: "23:00", end: "07:00", description: "11 PM \u2013 7 AM" },
  { label: "Sleep In",    start: "00:00", end: "09:00", description: "Midnight \u2013 9 AM" },
  { label: "Work Hours",  start: "09:00", end: "17:00", description: "9 AM \u2013 5 PM" },
];

const COMMON_TIMEZONES = [
  { label: "Eastern (America/New_York)", value: "America/New_York" },
  { label: "Central (America/Chicago)", value: "America/Chicago" },
  { label: "Mountain (America/Denver)", value: "America/Denver" },
  { label: "Pacific (America/Los_Angeles)", value: "America/Los_Angeles" },
  { label: "UTC", value: "UTC" },
  { label: "London (Europe/London)", value: "Europe/London" },
  { label: "Berlin (Europe/Berlin)", value: "Europe/Berlin" },
  { label: "Tokyo (Asia/Tokyo)", value: "Asia/Tokyo" },
  { label: "Sydney (Australia/Sydney)", value: "Australia/Sydney" },
];

/** Parse "HH:MM" to fractional hours (e.g. "22:30" -> 22.5) */
function timeToHours(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return (h || 0) + (m || 0) / 60;
}

/** Format "HH:MM" to human-readable (e.g. "22:00" -> "10 PM") */
function fmtTime12(hhmm: string): string {
  const [h, m] = hhmm.split(":").map(Number);
  if (isNaN(h)) return "";
  const ampm = h >= 12 ? "PM" : "AM";
  const h12 = h === 0 ? 12 : h > 12 ? h - 12 : h;
  return m ? `${h12}:${String(m).padStart(2, "0")} ${ampm}` : `${h12} ${ampm}`;
}

function QuietHoursPicker({ start, end, timezone, onChangeStart, onChangeEnd, onChangeTimezone, inheritedRange, defaultTimezone }: {
  start: string;
  end: string;
  timezone: string;
  onChangeStart: (v: string) => void;
  onChangeEnd: (v: string) => void;
  onChangeTimezone: (v: string) => void;
  inheritedRange?: string | null;
  defaultTimezone?: string | null;
}) {
  const t = useThemeTokens();
  const hasValue = !!(start || end);

  // Find matching preset
  const activePreset = QUIET_PRESETS.find(p => p.start === start && p.end === end);

  // Compute visual bar segments for the 24h timeline
  const barSegments = useMemo(() => {
    const s = start || (inheritedRange ? inheritedRange.split("-")[0] : "");
    const e = end || (inheritedRange ? inheritedRange.split("-")[1] : "");
    if (!s || !e) return null;
    const startH = timeToHours(s);
    const endH = timeToHours(e);
    // Wrap-around: e.g. 22:00-06:30 means quiet from 22 to 24 and 0 to 6.5
    if (startH > endH) {
      return [
        { left: (startH / 24) * 100, width: ((24 - startH) / 24) * 100 },
        { left: 0, width: (endH / 24) * 100 },
      ];
    }
    return [{ left: (startH / 24) * 100, width: ((endH - startH) / 24) * 100 }];
  }, [start, end, inheritedRange]);

  const applyPreset = useCallback((p: typeof QUIET_PRESETS[number]) => {
    onChangeStart(p.start);
    onChangeEnd(p.end);
  }, [onChangeStart, onChangeEnd]);

  const clear = useCallback(() => {
    onChangeStart("");
    onChangeEnd("");
    onChangeTimezone("");
  }, [onChangeStart, onChangeEnd, onChangeTimezone]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {/* Presets */}
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
        {QUIET_PRESETS.map((p) => {
          const isActive = activePreset?.label === p.label;
          return (
            <button
              key={p.label}
              onClick={() => applyPreset(p)}
              style={{
                padding: "5px 12px", borderRadius: 6, cursor: "pointer",
                fontSize: 12, fontWeight: isActive ? 700 : 500,
                border: `1px solid ${isActive ? t.accent : t.surfaceBorder}`,
                background: isActive ? `${t.accent}18` : t.inputBg,
                color: isActive ? t.accent : t.textMuted,
                transition: "all 0.12s",
              }}
              title={p.description}
            >
              {p.label}
              <span style={{ fontSize: 10, marginLeft: 4, color: isActive ? t.accent : t.textDim, opacity: 0.8 }}>
                {p.description}
              </span>
            </button>
          );
        })}
        {hasValue && (
          <button
            onClick={clear}
            style={{
              display: "flex", alignItems: "center", gap: 4,
              padding: "5px 10px", borderRadius: 6, cursor: "pointer",
              fontSize: 11, fontWeight: 600, border: "none",
              background: "none", color: t.textDim,
            }}
            title={inheritedRange ? `Reset to inherited (${inheritedRange})` : "Clear quiet hours"}
          >
            <RotateCcw size={11} />
            {inheritedRange ? "Reset" : "Clear"}
          </button>
        )}
      </div>

      {/* 24h visual bar */}
      {barSegments && (
        <div style={{ position: "relative", height: 28, borderRadius: 6, overflow: "hidden" }}>
          {/* Background — active hours */}
          <div style={{
            position: "absolute", inset: 0, borderRadius: 6,
            background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          }} />
          {/* Quiet segments */}
          {barSegments.map((seg, i) => (
            <div key={i} style={{
              position: "absolute", top: 0, bottom: 0,
              left: `${seg.left}%`, width: `${seg.width}%`,
              background: `${t.accent}25`, borderLeft: i === 0 && seg.left > 0 ? `2px solid ${t.accent}` : undefined,
              borderRight: `2px solid ${t.accent}`,
            }} />
          ))}
          {/* Hour markers */}
          {[0, 3, 6, 9, 12, 15, 18, 21].map((h) => (
            <span key={h} style={{
              position: "absolute", top: 1, fontSize: 8, color: t.textDim,
              left: `${(h / 24) * 100}%`, transform: "translateX(-50%)",
              userSelect: "none", pointerEvents: "none",
            }}>
              {h === 0 ? "12a" : h === 12 ? "12p" : h < 12 ? `${h}a` : `${h - 12}p`}
            </span>
          ))}
          {/* Summary text */}
          <span style={{
            position: "absolute", bottom: 2, left: "50%", transform: "translateX(-50%)",
            fontSize: 10, fontWeight: 600, color: t.textMuted, whiteSpace: "nowrap",
            pointerEvents: "none",
          }}>
            {start && end ? `Quiet ${fmtTime12(start)} \u2013 ${fmtTime12(end)}` :
             inheritedRange ? `Inherited: ${inheritedRange}` : ""}
          </span>
        </div>
      )}

      {/* Manual time inputs + timezone */}
      <Row>
        <Col>
          <FormRow label="Start" description="When quiet hours begin">
            <TextInput
              value={start}
              onChangeText={onChangeStart}
              placeholder={inheritedRange ? inheritedRange.split("-")[0] : "HH:MM"}
              type="time"
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow label="End" description="When quiet hours end">
            <TextInput
              value={end}
              onChangeText={onChangeEnd}
              placeholder={inheritedRange ? inheritedRange.split("-")[1] : "HH:MM"}
              type="time"
            />
          </FormRow>
        </Col>
        <Col>
          <FormRow label="Timezone">
            <SelectInput
              value={timezone}
              onChange={onChangeTimezone}
              options={[
                { label: defaultTimezone ? `Inherit (${defaultTimezone})` : "Server default", value: "" },
                ...COMMON_TIMEZONES,
              ]}
            />
          </FormRow>
        </Col>
      </Row>

      {/* Inherited indicator */}
      {!hasValue && inheritedRange && (
        <div style={{ fontSize: 10, color: t.textDim, fontStyle: "italic" }}>
          Using global default: {inheritedRange}{defaultTimezone ? ` (${defaultTimezone})` : ""}
        </div>
      )}
    </div>
  );
}

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
                {hb.repetition_detected && (
                  <span style={{
                    fontSize: 10, padding: "2px 8px", borderRadius: 4, fontWeight: 600,
                    background: t.warningSubtle, color: t.warningMuted,
                    display: "inline-flex", alignItems: "center", gap: 3,
                  }}>
                    <AlertTriangle size={10} /> repetitive
                  </span>
                )}
              </div>
              {isExpanded && (
                <div style={{
                  padding: "10px 12px", background: t.codeBg,
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
    "You are running a scheduled heartbeat \u2014 an automated periodic prompt (not a user message).",
    "Your job: follow the prompt below, analyze what is relevant, and produce a concise result.",
    "Current time: {current_time}",
    `Channel: ${data?.channel_name ?? "{channel_name}"}`,
    `Heartbeat interval: every ${interval} minutes`,
    "Run number: {run_number}",
    "Last heartbeat: {last_run_time}",
    "Activity since last heartbeat: {activity_summary}",
  ];

  // Quiet hours line
  const qStart = form?.quiet_start;
  const qEnd = form?.quiet_end;
  const qTz = form?.timezone;
  if (qStart && qEnd) {
    lines.push(`Quiet hours: ${qStart}\u2013${qEnd} (${qTz || data?.default_timezone || "server default"})`);
  } else if (data?.default_quiet_hours) {
    lines.push(`Quiet hours: ${data.default_quiet_hours} (global default, ${data.default_timezone})`);
  }

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
    "Everything above is context and conversation history. The user's CURRENT message follows \u2014 respond to it directly.",
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
          marginTop: 8, padding: 12, background: t.codeBg, borderRadius: 6,
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
        quiet_start: data.config.quiet_start ?? "",
        quiet_end: data.config.quiet_end ?? "",
        timezone: data.config.timezone ?? "",
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
        {/* ---- Schedule Section ---- */}
        <Section title="Schedule">
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
          </Row>

          <div style={{ marginTop: 12 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: t.textDim, marginBottom: 8, letterSpacing: "0.03em" }}>
              Quiet Hours
            </div>
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
          </div>
        </Section>

        {/* ---- Prompt Section ---- */}
        <Section title="Prompt">
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
        </Section>

        {/* ---- Dispatch Section ---- */}
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
        </Section>

        {/* ---- Advanced Section ---- */}
        <Section title="Advanced">
          <Row>
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
          <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 12 }}>
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
