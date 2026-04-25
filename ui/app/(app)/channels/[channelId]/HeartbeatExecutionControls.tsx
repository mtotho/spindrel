import { Gauge, SlidersHorizontal, Wrench } from "lucide-react";

import { Col, FormRow, Row, TextInput } from "@/src/components/shared/FormControls";
import {
  SettingsControlRow,
  SettingsGroupLabel,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";

const EXECUTION_DEPTH_OPTIONS = [
  {
    label: "Low",
    value: "low",
    description: "Short periodic checks with a tight ceiling.",
  },
  {
    label: "Medium",
    value: "medium",
    description: "Default balance for ordinary autonomous work.",
  },
  {
    label: "High",
    value: "high",
    description: "Longer investigative heartbeats with a larger escape hatch.",
  },
  {
    label: "Custom",
    value: "custom",
    description: "Manually tuned limits for this channel.",
  },
];

const TOOL_SURFACE_OPTIONS = [
  {
    label: "Focused escape",
    value: "focused_escape",
    description: "Retrieved tools, explicit tags, heartbeat helpers, and discovery escape hatches.",
  },
  {
    label: "Strict",
    value: "strict",
    description: "Only explicitly selected or retrieved tools. No broad discovery escape hatch.",
  },
  {
    label: "Full",
    value: "full",
    description: "Chat-like broad tool surface, including broad pinned tools.",
  },
];

export function normalizeExecutionPolicy(raw: any, defaultPolicy?: any, presets?: Record<string, any>) {
  const fallback = defaultPolicy ?? { preset: "medium" };
  const preset = typeof raw?.preset === "string" ? raw.preset : fallback.preset ?? "medium";
  const base = presets?.[preset] ?? presets?.[fallback.preset] ?? fallback;
  return {
    preset: presets?.[preset] || preset === "custom" ? preset : fallback.preset ?? "medium",
    tool_surface: raw?.tool_surface ?? fallback.tool_surface ?? "focused_escape",
    continuation_mode: raw?.continuation_mode ?? fallback.continuation_mode ?? "stateless",
    soft_max_llm_calls: raw?.soft_max_llm_calls ?? base.soft_max_llm_calls,
    hard_max_llm_calls: raw?.hard_max_llm_calls ?? base.hard_max_llm_calls,
    soft_current_prompt_tokens: raw?.soft_current_prompt_tokens ?? base.soft_current_prompt_tokens,
    target_seconds: raw?.target_seconds ?? base.target_seconds,
  };
}

function formatNumber(value: number | null | undefined) {
  if (value == null) return "default";
  return Number(value).toLocaleString();
}

function formatPresetSummary(policy: any) {
  return [
    `${formatNumber(policy.soft_max_llm_calls)} soft`,
    `${formatNumber(policy.hard_max_llm_calls)} hard`,
    `${formatNumber(policy.soft_current_prompt_tokens)} tokens`,
    `${formatNumber(policy.target_seconds)}s`,
  ].join(" / ");
}

function matchingPreset(policy: any, presets?: Record<string, any>) {
  if (!presets) return null;
  return Object.entries(presets).find(([, preset]) => (
    preset.soft_max_llm_calls === policy.soft_max_llm_calls
    && preset.hard_max_llm_calls === policy.hard_max_llm_calls
    && preset.soft_current_prompt_tokens === policy.soft_current_prompt_tokens
    && preset.target_seconds === policy.target_seconds
  ))?.[0] ?? null;
}

export function HeartbeatExecutionControls({
  policy,
  defaultPolicy,
  presets,
  isMobile,
  onPresetChange,
  onToolSurfaceChange,
  onNumberChange,
}: {
  policy: any;
  defaultPolicy?: any;
  presets?: Record<string, any>;
  isMobile: boolean;
  onPresetChange: (preset: string) => void;
  onToolSurfaceChange: (toolSurface: string) => void;
  onNumberChange: (field: string, value: string) => void;
}) {
  const normalized = normalizeExecutionPolicy(policy, defaultPolicy, presets);
  const effectivePreset = matchingPreset(normalized, presets);
  const isCustom = normalized.preset === "custom" || effectivePreset == null;
  const selectedToolSurface = TOOL_SURFACE_OPTIONS.find((option) => option.value === normalized.tool_surface)
    ?? TOOL_SURFACE_OPTIONS[0];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Execution depth" icon={<Gauge size={12} />} />
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-4">
          {EXECUTION_DEPTH_OPTIONS.map((option) => {
            const presetValues = option.value === "custom"
              ? normalized
              : normalizeExecutionPolicy({ preset: option.value }, defaultPolicy, presets);
            const active = option.value === "custom" ? isCustom : normalized.preset === option.value && !isCustom;
            return (
              <SettingsControlRow
                key={option.value}
                active={active}
                onClick={() => onPresetChange(option.value)}
                title={
                  <span className="flex min-w-0 items-center gap-1.5">
                    <span className="truncate">{option.label}</span>
                    {option.value === defaultPolicy?.preset && (
                      <StatusBadge label="Default" variant="neutral" />
                    )}
                  </span>
                }
                description={
                  <span className="flex flex-col gap-1">
                    <span>{option.description}</span>
                    <span className="font-mono text-[10px] text-text-dim">
                      {formatPresetSummary(presetValues)}
                    </span>
                  </span>
                }
              />
            );
          })}
        </div>
      </div>

      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Tool surface" icon={<Wrench size={12} />} />
        <div className="grid grid-cols-1 gap-2 lg:grid-cols-3">
          {TOOL_SURFACE_OPTIONS.map((option) => (
            <SettingsControlRow
              key={option.value}
              active={normalized.tool_surface === option.value}
              onClick={() => onToolSurfaceChange(option.value)}
              title={option.label}
              description={option.description}
            />
          ))}
        </div>
        <div className="text-[11px] leading-snug text-text-dim">
          Current: <span className="text-text-muted">{selectedToolSurface.label}</span>. Provider-state continuation remains reserved; heartbeat runs stay stateless.
        </div>
      </div>

      {isCustom && (
        <div className="flex flex-col gap-3 rounded-md bg-surface-raised/35 p-3">
          <SettingsGroupLabel label="Custom limits" icon={<SlidersHorizontal size={12} />} />
          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 150}>
              <FormRow label="Soft LLM calls">
                <TextInput
                  value={normalized.soft_max_llm_calls?.toString() ?? ""}
                  onChangeText={(v) => onNumberChange("soft_max_llm_calls", v)}
                  type="number"
                  min={1}
                />
              </FormRow>
            </Col>
            <Col minWidth={isMobile ? 0 : 150}>
              <FormRow label="Hard LLM calls">
                <TextInput
                  value={normalized.hard_max_llm_calls?.toString() ?? ""}
                  onChangeText={(v) => onNumberChange("hard_max_llm_calls", v)}
                  type="number"
                  min={1}
                />
              </FormRow>
            </Col>
          </Row>
          <Row stack={isMobile}>
            <Col minWidth={isMobile ? 0 : 190}>
              <FormRow label="Soft current tokens">
                <TextInput
                  value={normalized.soft_current_prompt_tokens?.toString() ?? ""}
                  onChangeText={(v) => onNumberChange("soft_current_prompt_tokens", v)}
                  type="number"
                  min={0}
                />
              </FormRow>
            </Col>
            <Col minWidth={isMobile ? 0 : 150}>
              <FormRow label="Target seconds">
                <TextInput
                  value={normalized.target_seconds?.toString() ?? ""}
                  onChangeText={(v) => onNumberChange("target_seconds", v)}
                  type="number"
                  min={1}
                />
              </FormRow>
            </Col>
          </Row>
        </div>
      )}
    </div>
  );
}
