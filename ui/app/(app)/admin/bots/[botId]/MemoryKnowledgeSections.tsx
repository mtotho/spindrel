import { useState } from "react";
import { BookOpen, Brain, ChevronDown, Clock, FileText, FolderTree, Play, Sparkles } from "lucide-react";

import { useMemorySchemeDefaults } from "@/src/api/hooks/useMemorySchemeDefaults";
import { useMemoryHygieneStatus, useMemoryHygieneRuns, useTriggerMemoryHygiene, type JobStatus } from "@/src/api/hooks/useMemoryHygiene";
import { Col, FormRow, Row, TextInput, Toggle } from "@/src/components/shared/FormControls";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { LlmPrompt } from "@/src/components/shared/LlmPrompt";
import { SourceTextEditor } from "@/src/components/shared/SourceTextEditor";
import {
  ActionButton,
  AdvancedSection,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSegmentedControl,
  SettingsStatGrid,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import type { BotConfig } from "@/src/types/api";

import { HygieneHistoryList } from "./HygieneHistoryList";

const DIR_STRUCTURE = `memory/
├── MEMORY.md
├── logs/
│   ├── YYYY-MM-DD.md
│   └── archive/
└── reference/
    └── *.md`;

const MEMORY_PATHS = [
  {
    path: "memory/MEMORY.md",
    title: "Durable baseline",
    description: "Stable facts and preferences that should be admitted into context first.",
    icon: <FileText size={14} />,
  },
  {
    path: "memory/logs/",
    title: "Daily logs",
    description: "Recent working memory stays hot; older logs remain searchable after hygiene.",
    icon: <Clock size={14} />,
  },
  {
    path: "memory/reference/",
    title: "Reference notes",
    description: "Longer docs and runbooks the bot can discover and read when needed.",
    icon: <BookOpen size={14} />,
  },
];

const JOB_CONFIG = {
  maintenance: {
    label: "Memory Maintenance",
    shortLabel: "Maintenance",
    description: "Tidies daily logs, promotes stable facts, and keeps MEMORY.md useful.",
    variant: "warning" as const,
    jobType: "memory_hygiene" as const,
    fields: {
      enabled: "memory_hygiene_enabled" as const,
      interval: "memory_hygiene_interval_hours" as const,
      only_if_active: "memory_hygiene_only_if_active" as const,
      target_hour: "memory_hygiene_target_hour" as const,
      model: "memory_hygiene_model" as const,
      model_provider: "memory_hygiene_model_provider_id" as const,
      prompt: "memory_hygiene_prompt" as const,
      extra_instructions: "memory_hygiene_extra_instructions" as const,
    },
  },
  skill_review: {
    label: "Skill Review",
    shortLabel: "Skill Review",
    description: "Runs deeper review for bot-authored skills, pruning, and auto-inject quality.",
    variant: "purple" as const,
    jobType: "skill_review" as const,
    fields: {
      enabled: "skill_review_enabled" as const,
      interval: "skill_review_interval_hours" as const,
      only_if_active: "skill_review_only_if_active" as const,
      target_hour: "skill_review_target_hour" as const,
      model: "skill_review_model" as const,
      model_provider: "skill_review_model_provider_id" as const,
      prompt: "skill_review_prompt" as const,
      extra_instructions: "skill_review_extra_instructions" as const,
    },
  },
} as const;

type JobKey = keyof typeof JOB_CONFIG;

function fmtTime(value: string | null | undefined): string {
  if (!value) return "never";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function boolSettingLabel(value: boolean | null | undefined, resolved: boolean) {
  if (value == null) return `Inherit (${resolved ? "on" : "off"})`;
  return value ? "Enabled" : "Disabled";
}

function JobSettingToggle({
  value,
  resolved,
  onChange,
}: {
  value: boolean | null | undefined;
  resolved: boolean;
  onChange: (value: boolean | null) => void;
}) {
  return (
    <SettingsSegmentedControl
      value={value == null ? "inherit" : value ? "enabled" : "disabled"}
      onChange={(next) => onChange(next === "inherit" ? null : next === "enabled")}
      options={[
        { value: "inherit", label: `Inherit (${resolved ? "on" : "off"})` },
        { value: "enabled", label: "Enabled" },
        { value: "disabled", label: "Disabled" },
      ]}
    />
  );
}

function PromptPreview({ label, content }: { label: string; content: string }) {
  if (!content) return null;
  return (
    <AdvancedSection title={label}>
      <SourceTextEditor value={content} readOnly language="markdown" minHeight={180} maxHeight={340} />
    </AdvancedSection>
  );
}

function JobSection({
  jobKey,
  draft,
  update,
  botId,
  status,
  triggerMut,
}: {
  jobKey: JobKey;
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  botId: string | undefined;
  status: JobStatus | undefined;
  triggerMut: ReturnType<typeof useTriggerMemoryHygiene>;
}) {
  const cfg = JOB_CONFIG[jobKey];
  const [expanded, setExpanded] = useState(false);
  const { data: runsData } = useMemoryHygieneRuns(botId, cfg.jobType);

  const enabledValue = draft[cfg.fields.enabled];
  const resolvedEnabled = status?.enabled ?? false;
  const onlyActiveValue = draft[cfg.fields.only_if_active];
  const resolvedOnlyActive = status?.only_if_active ?? true;
  const overridden = Boolean(draft[cfg.fields.prompt]);
  const customInstructions = Boolean(draft[cfg.fields.extra_instructions]);
  const lastStatus = status?.last_task_status;

  return (
    <div className="flex flex-col gap-2">
      <SettingsControlRow
        leading={<Sparkles size={14} />}
        title={cfg.label}
        description={`${resolvedEnabled ? `Every ${status?.interval_hours ?? "?"}h` : "Disabled"} · last ${fmtTime(status?.last_run_at)} · next ${fmtTime(status?.next_run_at)}`}
        meta={
          <div className="flex flex-wrap gap-1.5">
            <StatusBadge label={resolvedEnabled ? "on" : "off"} variant={resolvedEnabled ? cfg.variant : "neutral"} />
            {lastStatus && <StatusBadge label={lastStatus} variant={lastStatus === "complete" ? "success" : lastStatus === "failed" ? "danger" : "neutral"} />}
            {overridden && <StatusBadge label="prompt override" variant="warning" />}
            {customInstructions && <QuietPill label="extra instructions" />}
          </div>
        }
        action={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            {botId && (
              <ActionButton
                label={triggerMut.isPending ? "Running" : "Run now"}
                size="small"
                variant={cfg.variant === "purple" ? "secondary" : "primary"}
                icon={<Play size={12} />}
                disabled={triggerMut.isPending}
                onPress={() => triggerMut.mutate({ botId, jobType: cfg.jobType })}
              />
            )}
            <ActionButton
              label={expanded ? "Hide" : "Configure"}
              size="small"
              variant="secondary"
              icon={<ChevronDown size={12} className={expanded ? "rotate-180" : ""} />}
              onPress={() => setExpanded((value) => !value)}
            />
          </div>
        }
      />

      {expanded && (
        <div className="rounded-md bg-surface-raised/30 px-3 py-3">
          <p className="mb-3 text-[12px] leading-relaxed text-text-dim">{cfg.description}</p>
          <div className="flex flex-col gap-4">
            <FormRow label="Enable">
              <JobSettingToggle
                value={enabledValue as boolean | null | undefined}
                resolved={resolvedEnabled}
                onChange={(value) => update({ [cfg.fields.enabled]: value } as Partial<BotConfig>)}
              />
            </FormRow>
            <Row>
              <Col>
                <FormRow label="Interval" description={`Current resolved value: ${status?.interval_hours ?? 24} hours.`}>
                  <TextInput
                    value={String(draft[cfg.fields.interval] ?? "")}
                    onChangeText={(value) => update({ [cfg.fields.interval]: value ? parseInt(value, 10) : null } as Partial<BotConfig>)}
                    placeholder={String(status?.interval_hours ?? 24)}
                    type="number"
                    min={1}
                  />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Only if active" description="Skip scheduled runs if the bot has had no user activity.">
                  <SettingsSegmentedControl
                    value={onlyActiveValue == null ? "inherit" : onlyActiveValue ? "yes" : "no"}
                    onChange={(next) => update({ [cfg.fields.only_if_active]: next === "inherit" ? null : next === "yes" } as Partial<BotConfig>)}
                    options={[
                      { value: "inherit", label: boolSettingLabel(null, resolvedOnlyActive) },
                      { value: "yes", label: "Yes" },
                      { value: "no", label: "No" },
                    ]}
                  />
                </FormRow>
              </Col>
            </Row>
            <Row>
              <Col>
                <FormRow label="Target hour" description="Local hour, or -1 to disable start-hour staggering.">
                  <TextInput
                    value={draft[cfg.fields.target_hour] != null ? String(draft[cfg.fields.target_hour]) : ""}
                    onChangeText={(value) => {
                      if (value === "") update({ [cfg.fields.target_hour]: null } as Partial<BotConfig>);
                      else {
                        const parsed = parseInt(value, 10);
                        if (!Number.isNaN(parsed) && parsed >= -1 && parsed <= 23) {
                          update({ [cfg.fields.target_hour]: parsed } as Partial<BotConfig>);
                        }
                      }
                    }}
                    placeholder={status?.target_hour != null && status.target_hour >= 0 ? `${status.target_hour}` : "-1"}
                    type="number"
                    min={-1}
                  />
                </FormRow>
              </Col>
              <Col>
                <FormRow label="Model override" description={status?.model ? `Inherited: ${status.model}` : "Falls back to the bot model."}>
                  <LlmModelDropdown
                    value={(draft[cfg.fields.model] as string | null | undefined) ?? ""}
                    onChange={(modelId, providerId) => update({
                      [cfg.fields.model]: modelId || null,
                      [cfg.fields.model_provider]: providerId ?? null,
                    } as Partial<BotConfig>)}
                    placeholder={status?.model || "bot default"}
                    selectedProviderId={draft[cfg.fields.model_provider] as string | null | undefined}
                    allowClear
                  />
                </FormRow>
              </Col>
            </Row>
            <AdvancedSection title="Additional instructions" defaultOpen={customInstructions}>
              <FormRow label="Appended instructions" description="These append to the built-in job prompt without replacing it.">
                <textarea
                  value={(draft[cfg.fields.extra_instructions] as string | null | undefined) ?? ""}
                  onChange={(event) => update({ [cfg.fields.extra_instructions]: event.target.value || null } as Partial<BotConfig>)}
                  rows={3}
                  placeholder="Extra guidance for this bot's scheduled run..."
                  className="min-h-[96px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-sm text-text outline-none transition-colors placeholder:text-text-dim focus:border-accent focus:ring-2 focus:ring-accent/40"
                />
              </FormRow>
            </AdvancedSection>
            <AdvancedSection title="Full prompt override" defaultOpen={overridden}>
              <LlmPrompt
                value={(draft[cfg.fields.prompt] as string | null | undefined) ?? ""}
                onChange={(value) => update({ [cfg.fields.prompt]: value || null } as Partial<BotConfig>)}
                rows={8}
                placeholder="Leave empty to use the built-in default prompt..."
                fieldType={cfg.fields.prompt}
                botId={botId}
              />
              {overridden && (
                <div className="mt-2">
                  <ActionButton label="Reset to default" variant="secondary" size="small" onPress={() => update({ [cfg.fields.prompt]: null } as Partial<BotConfig>)} />
                </div>
              )}
            </AdvancedSection>
            {!overridden && status?.resolved_prompt && (
              <PromptPreview label={`Built-in ${cfg.shortLabel} prompt`} content={status.resolved_prompt} />
            )}
            {botId && runsData?.runs?.length ? <HygieneHistoryList runs={runsData.runs} /> : null}
          </div>
        </div>
      )}
    </div>
  );
}

function MemoryHygieneSubsection({
  draft,
  update,
  botId,
}: {
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  botId: string | undefined;
}) {
  const { data: status } = useMemoryHygieneStatus(botId);
  const triggerMut = useTriggerMemoryHygiene();

  return (
    <div className="flex flex-col gap-3">
      <SettingsGroupLabel label="Dreaming jobs" count={2} icon={<Sparkles size={12} className="text-text-dim" />} />
      <JobSection
        jobKey="maintenance"
        draft={draft}
        update={update}
        botId={botId}
        status={status?.memory_hygiene}
        triggerMut={triggerMut}
      />
      <JobSection
        jobKey="skill_review"
        draft={draft}
        update={update}
        botId={botId}
        status={status?.skill_review}
        triggerMut={triggerMut}
      />
    </div>
  );
}

export function MemorySection({
  draft,
  update,
  botId,
}: {
  draft: BotConfig;
  update: (patch: Partial<BotConfig>) => void;
  botId: string | undefined;
}) {
  const { data: defaults } = useMemorySchemeDefaults();
  const builtInPrompt = defaults?.prompt ?? "";
  const memoryEnabled = draft.memory_scheme === "workspace-files" || draft.memory?.enabled;

  return (
    <div className="flex flex-col gap-6">
      <SettingsStatGrid
        items={[
          { label: "Mode", value: draft.memory_scheme === "workspace-files" ? "files" : memoryEnabled ? "legacy" : "off", tone: memoryEnabled ? "accent" : "default" },
          { label: "Workspace", value: draft.shared_workspace_id ? "linked" : "pending", tone: "accent" },
          { label: "Skills", value: draft.skills?.length ?? 0 },
          { label: "Prompt", value: builtInPrompt ? "built-in" : "loading" },
        ]}
      />

      <InfoBanner icon={<Brain size={14} />}>
        Workspace-files memory is the active model: durable facts live in files, recent logs stay searchable, and scheduled jobs keep the bot's memory useful.
      </InfoBanner>

      <div className="flex flex-col gap-2">
        <SettingsGroupLabel label="Bot memory files" icon={<FolderTree size={12} className="text-text-dim" />} />
        {MEMORY_PATHS.map((item) => (
          <SettingsControlRow
            key={item.path}
            leading={item.icon}
            title={item.title}
            description={item.description}
            meta={<QuietPill label={item.path} maxWidthClass="max-w-[220px]" />}
          />
        ))}
      </div>

      <AdvancedSection title="Directory structure">
        <SourceTextEditor value={DIR_STRUCTURE} readOnly language="text" minHeight={150} maxHeight={220} />
      </AdvancedSection>

      <PromptPreview label="Built-in memory prompt" content={builtInPrompt} />

      <MemoryHygieneSubsection draft={draft} update={update} botId={botId} />
    </div>
  );
}
