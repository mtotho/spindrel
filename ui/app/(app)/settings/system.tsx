import { useEffect, useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  Bell,
  Brain,
  Cpu,
  Database,
  ExternalLink,
  HardDrive,
  Image as ImageIcon,
  Loader2,
  RefreshCw,
  RotateCcw,
  Save,
  Search,
  Server,
  Shield,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";
import { Spinner } from "@/src/components/shared/Spinner";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { Section, SelectInput, TextInput, Toggle } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SaveStatusPill,
  SettingsControlRow,
  SettingsGroupLabel,
  SettingsSearchBox,
  SettingsSegmentedControl,
  SettingsStatGrid,
  StatusBadge,
  type SaveStatusTone,
} from "@/src/components/shared/SettingsControls";
import {
  SettingItem,
  SettingsGroup,
  useResetSetting,
  useSettings,
  useUpdateSettings,
} from "@/src/api/hooks/useSettings";
import { useSystemStatus } from "@/src/api/hooks/useSystemStatus";
import { useVersion } from "@/src/api/hooks/useVersion";
import { useCheckUpdate, useTogglePause } from "@/src/api/hooks/useServerOps";
import { SettingsPromptField } from "@/src/components/settings/SettingsPromptField";
import { RestartConfirmModal } from "@/src/components/settings/RestartConfirmModal";
import { cn } from "@/src/lib/cn";

type SystemTab =
  | "Overview"
  | "Models"
  | "Memory & Context"
  | "Retrieval"
  | "Runtime & Tools"
  | "Media & Voice"
  | "Security & Access"
  | "Operations"
  | "Advanced";

const TABS: SystemTab[] = [
  "Overview",
  "Models",
  "Memory & Context",
  "Retrieval",
  "Runtime & Tools",
  "Media & Voice",
  "Security & Access",
  "Operations",
  "Advanced",
];

const LEGACY_HASH_MAP: Record<string, SystemTab> = {
  Global: "Overview",
  System: "Overview",
  General: "Overview",
  Paths: "Operations",
  "Chat History": "Memory & Context",
  "Memory & Learning": "Memory & Context",
  Heartbeat: "Memory & Context",
  "Embeddings & RAG": "Retrieval",
  "RAG Re-ranking": "Retrieval",
  Agent: "Runtime & Tools",
  "Tool Summarization": "Runtime & Tools",
  "Tool Policies": "Runtime & Tools",
  "Docker Stacks": "Runtime & Tools",
  Attachments: "Media & Voice",
  "Speech-to-Text": "Media & Voice",
  "Image Generation": "Media & Voice",
  "Prompt Generation": "Media & Voice",
  Security: "Security & Access",
  "API Rate Limiting": "Security & Access",
  "Data Retention": "Operations",
  Backup: "Operations",
};

const DOMAIN_KEYS: Record<Exclude<SystemTab, "Overview" | "Advanced">, string[]> = {
  Models: [
    "LLM_FALLBACK_MODEL",
    "MISSION_CONTROL_AI_MODEL",
    "MISSION_CONTROL_AI_MODEL_PROVIDER_ID",
    "MISSION_CONTROL_AI_TEMPERATURE",
    "COMPACTION_MODEL",
    "MEMORY_FLUSH_MODEL",
    "MEMORY_HYGIENE_MODEL",
    "SKILL_REVIEW_MODEL",
    "TOOL_RESULT_SUMMARIZE_MODEL",
    "CONTEXTUAL_RETRIEVAL_MODEL",
    "RAG_RERANK_MODEL",
    "IMAGE_GENERATION_MODEL",
    "PROMPT_GENERATION_MODEL",
    "EMBEDDING_MODEL",
  ],
  "Memory & Context": [
    "DEFAULT_HISTORY_MODE",
    "COMPACTION_INTERVAL",
    "COMPACTION_KEEP_TURNS",
    "PREVIOUS_SUMMARY_INJECT_CHARS",
    "HISTORY_WRITE_FILES",
    "MEMORY_FLUSH_ENABLED",
    "MEMORY_FLUSH_DEFAULT_PROMPT",
    "SECTION_INDEX_ENABLED",
    "SECTION_INDEX_MAX_INJECT_CHARS",
    "CONTEXT_PRUNING_ENABLED",
    "CONTEXT_PRUNING_THRESHOLD",
    "IN_LOOP_CONTEXT_COMPRESSION_ENABLED",
    "IN_LOOP_CONTEXT_THRESHOLD",
    "MEMORY_HYGIENE_ENABLED",
    "MEMORY_HYGIENE_PROMPT",
    "MEMORY_HYGIENE_INTERVAL_HOURS",
    "SKILL_REVIEW_ENABLED",
    "SKILL_REVIEW_PROMPT",
    "MEMORY_MD_NUDGE_THRESHOLD",
  ],
  Retrieval: [
    "RAG_TOP_K",
    "MEMORY_RETRIEVAL_LIMIT",
    "MEMORY_SIMILARITY_THRESHOLD",
    "MEMORY_MAX_INJECT_CHARS",
    "TOOL_RETRIEVAL_ENABLED",
    "TOOL_RETRIEVAL_TOP_K",
    "TOOL_RETRIEVAL_MIN_SCORE",
    "RAG_RERANK_ENABLED",
    "RAG_RERANK_TOP_N",
    "RAG_RERANK_MIN_SCORE",
    "HYBRID_SEARCH_ENABLED",
    "HYBRID_SEARCH_KEYWORD_WEIGHT",
    "CONTEXTUAL_RETRIEVAL_ENABLED",
    "CONTEXTUAL_RETRIEVAL_CHUNK_SIZE",
    "EMBEDDING_MODEL",
  ],
  "Runtime & Tools": [
    "AGENT_MAX_ITERATIONS",
    "LLM_MAX_RETRIES",
    "LLM_RETRY_INITIAL_WAIT",
    "LLM_RATE_LIMIT_RETRY_ENABLED",
    "PARALLEL_TOOL_EXECUTION",
    "PARALLEL_TOOL_MAX_CONCURRENT",
    "TOOL_LOOP_DETECTION_ENABLED",
    "TOOL_RESULT_SUMMARIZE_ENABLED",
    "TOOL_RESULT_SUMMARIZE_MODEL",
    "TOOL_POLICY_DEFAULT_ACTION",
    "TOOL_POLICY_REQUIRE_APPROVAL",
    "DOCKER_STACK_AUTO_START",
    "DOCKER_STACK_STOP_TIMEOUT_SECONDS",
  ],
  "Media & Voice": [
    "ATTACHMENT_MAX_SIZE_MB",
    "ATTACHMENT_MAX_COUNT",
    "ATTACHMENT_ALLOWED_MIME_TYPES",
    "STT_PROVIDER",
    "WHISPER_MODEL",
    "WHISPER_LANGUAGE",
    "IMAGE_GENERATION_MODEL",
    "PROMPT_GENERATION_MODEL",
  ],
  "Security & Access": [
    "API_KEY",
    "SECRET_REDACTION_ENABLED",
    "CORS_ORIGINS",
    "RATE_LIMIT_ENABLED",
    "RATE_LIMIT_REQUESTS_PER_MINUTE",
    "SYSTEM_PAUSED",
    "SYSTEM_PAUSE_BEHAVIOR",
    "GLOBAL_BASE_PROMPT",
    "WIDGET_THEME_DEFAULT_REF",
  ],
  Operations: [
    "SPINDREL_HOME",
    "TIMEZONE",
    "LOG_LEVEL",
    "DATA_RETENTION_ENABLED",
    "DATA_RETENTION_DAYS",
    "DATA_RETENTION_DRY_RUN",
  ],
};

const DOMAIN_DESCRIPTIONS: Record<SystemTab, string> = {
  Overview: "Health, status, and the admin surfaces that own each operational domain.",
  Models: "Default model choices for chat, compaction, retrieval, image generation, and prompt generation.",
  "Memory & Context": "Conversation history, compaction, memory hygiene, skill review, and context pruning.",
  Retrieval: "Knowledge search, memory retrieval, hybrid search, contextual retrieval, and re-ranking.",
  "Runtime & Tools": "Agent loop limits, retry behavior, tool execution, result summarization, and tool policy defaults.",
  "Media & Voice": "Attachments, speech-to-text, image generation, and prompt-generation defaults.",
  "Security & Access": "API key, pause behavior, CORS, rate limiting, and global prompt controls.",
  Operations: "Paths, logging, retention, backups, and maintenance links.",
  Advanced: "Full server settings registry. Use this when a setting is not promoted into a domain section yet.",
};

const DOMAIN_TABS = TABS.filter((tab): tab is Exclude<SystemTab, "Overview" | "Advanced"> => (
  tab !== "Overview" && tab !== "Advanced"
));

const DOMAIN_ICONS: Record<Exclude<SystemTab, "Overview" | "Advanced">, React.ReactNode> = {
  Models: <Cpu size={15} />,
  "Memory & Context": <Brain size={15} />,
  Retrieval: <Database size={15} />,
  "Runtime & Tools": <Wrench size={15} />,
  "Media & Voice": <ImageIcon size={15} />,
  "Security & Access": <Shield size={15} />,
  Operations: <HardDrive size={15} />,
};

const DOMAIN_SURFACES: Record<Exclude<SystemTab, "Overview" | "Advanced">, Array<{ label: string; href: string }>> = {
  Models: [
    { label: "Providers", href: "/admin/providers" },
    { label: "Config state", href: "/admin/config-state" },
  ],
  "Memory & Context": [
    { label: "Memory & Knowledge", href: "/admin/learning" },
    { label: "Automations", href: "/admin/automations" },
  ],
  Retrieval: [
    { label: "Memory & Knowledge", href: "/admin/learning#Knowledge" },
    { label: "Tools", href: "/admin/tools" },
  ],
  "Runtime & Tools": [
    { label: "Tool policies", href: "/admin/tool-policies" },
    { label: "Docker stacks", href: "/admin/docker-stacks" },
  ],
  "Media & Voice": [
    { label: "Attachments", href: "/admin/attachments" },
    { label: "Providers", href: "/admin/providers" },
  ],
  "Security & Access": [
    { label: "API keys", href: "/admin/api-keys" },
    { label: "Secrets", href: "/admin/secret-values" },
  ],
  Operations: [
    { label: "Diagnostics", href: "/admin/diagnostics" },
    { label: "Config state", href: "/admin/config-state" },
  ],
};

function decodeHash(hash: string): string {
  if (!hash) return "";
  try {
    return decodeURIComponent(hash.replace(/^#/, ""));
  } catch {
    return hash.replace(/^#/, "");
  }
}

function settingMap(groups: SettingsGroup[]) {
  const map = new Map<string, SettingItem>();
  for (const group of groups) {
    for (const setting of group.settings) map.set(setting.key, setting);
  }
  return map;
}

function settingsForDomain(tab: Exclude<SystemTab, "Overview" | "Advanced">, settingsByKey: Map<string, SettingItem>) {
  return DOMAIN_KEYS[tab].map((key) => settingsByKey.get(key)).filter(Boolean) as SettingItem[];
}

function providerCompanionKey(key: string): string | null {
  if (key.endsWith("_MODEL")) return `${key}_PROVIDER_ID`;
  return null;
}

function formatSettingValue(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "string") return value;
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function parseSettingValue(item: SettingItem, value: string): unknown {
  if (item.nullable && value.trim() === "") return null;
  if (item.type === "bool") return value === "true";
  if (item.type === "int") return value.trim() === "" ? null : parseInt(value, 10);
  if (item.type === "float") return value.trim() === "" ? null : parseFloat(value);
  return value;
}

function saveTone(status: "idle" | "dirty" | "pending" | "saved" | "error"): SaveStatusTone {
  return status;
}

function SettingControl({
  item,
  value,
  values,
  onChange,
  onChangeKey,
}: {
  item: SettingItem;
  value: string;
  values: Record<string, string>;
  onChange: (value: string) => void;
  onChangeKey: (key: string, value: string) => void;
}) {
  if (item.type === "bool") {
    return (
      <Toggle
        value={value === "true"}
        onChange={(next) => {
          if (!item.read_only) onChange(next ? "true" : "false");
        }}
        label={value === "true" ? "Enabled" : "Disabled"}
      />
    );
  }

  if (item.options?.length) {
    return (
      <SelectInput
        value={value}
        onChange={(next) => {
          if (!item.read_only) onChange(next);
        }}
        options={item.options.map((option) => ({ label: option, value: option }))}
      />
    );
  }

  if (item.widget === "model" || item.widget === "embedding_model" || item.widget === "image_model") {
    const providerKey = providerCompanionKey(item.key);
    const placeholder =
      item.widget === "embedding_model"
        ? "Select embedding model..."
        : item.widget === "image_model"
          ? "Select image-gen model..."
          : "Select model...";
    return (
      <div className="max-w-[420px]">
        <LlmModelDropdown
          value={value}
          selectedProviderId={providerKey ? values[providerKey] || null : undefined}
          onChange={(model, providerId) => {
            if (item.read_only) return;
            onChange(model);
            if (providerKey) onChangeKey(providerKey, providerId ?? "");
          }}
          placeholder={placeholder}
          allowClear={item.nullable}
          variant={item.widget === "embedding_model" ? "embedding" : "llm"}
          capabilityFilter={item.widget === "image_model" ? "image_generation" : undefined}
        />
      </div>
    );
  }

  if (item.widget === "textarea" || item.key.includes("PROMPT")) {
    return (
      <SettingsPromptField
        item={item}
        value={value}
        onChange={onChange}
      />
    );
  }

  if (item.key === "CORS_ORIGINS") {
    return (
      <textarea
        value={value}
        onChange={(event) => onChange(event.target.value)}
        readOnly={item.read_only}
        rows={item.widget === "textarea" || item.key.includes("PROMPT") ? 8 : 4}
        className="min-h-[120px] w-full resize-y rounded-md border border-input-border bg-input px-3 py-2 text-[13px] leading-relaxed text-text outline-none placeholder:text-text-dim focus:border-accent focus:ring-2 focus:ring-accent/40"
        placeholder={item.nullable ? "Unset" : undefined}
      />
    );
  }

  return (
    <TextInput
      value={value}
      onChangeText={onChange}
      type={item.type === "int" || item.type === "float" ? "number" : "text"}
      placeholder={item.nullable ? "Unset" : undefined}
      disabled={item.read_only}
    />
  );
}

function SettingsDomainSection({
  title,
  description,
  settings,
  values,
  dirtyKeys,
  status,
  updatePending,
  resetPending,
  onChange,
  onSave,
  onReset,
}: {
  title: string;
  description: string;
  settings: SettingItem[];
  values: Record<string, string>;
  dirtyKeys: Set<string>;
  status: "idle" | "dirty" | "pending" | "saved" | "error";
  updatePending: boolean;
  resetPending: boolean;
  onChange: (key: string, value: string) => void;
  onSave: (keys?: string[]) => void;
  onReset: (item: SettingItem) => void;
}) {
  const sectionDirtyKeys = Array.from(new Set(
    settings.flatMap((item) => {
      const keys = [item.key];
      const companion = providerCompanionKey(item.key);
      if (companion) keys.push(companion);
      return keys;
    }).filter((key) => dirtyKeys.has(key)),
  ));
  const sectionStatus = status === "dirty" && sectionDirtyKeys.length === 0 ? "idle" : status;

  return (
    <Section
      title={title}
      description={description}
      action={
        <div className="flex items-center gap-2">
          <SaveStatusPill
            tone={saveTone(sectionStatus)}
            label={
              sectionStatus === "pending"
                ? "Saving"
                : sectionStatus === "saved"
                  ? "Saved"
                  : sectionStatus === "error"
                    ? "Save failed"
                    : `${sectionDirtyKeys.length} pending`
            }
          />
          <ActionButton
            label="Save"
            onPress={() => onSave(sectionDirtyKeys)}
            disabled={!sectionDirtyKeys.length || updatePending}
            icon={updatePending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          />
        </div>
      }
    >
      {settings.length === 0 ? (
        <EmptyState message="No registry settings are currently mapped into this domain." />
      ) : (
        <div className="flex flex-col gap-2">
          {settings.map((item) => (
            <div key={item.key} className="rounded-md bg-surface-raised/40 px-3 py-3">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-1.5">
                    <span className="text-[12px] font-semibold text-text">{item.label}</span>
                    {item.overridden && <StatusBadge label="Overridden" variant="info" />}
                    {item.read_only && <QuietPill label="read only" />}
                  </div>
                  <div className="mt-0.5 text-[11px] leading-snug text-text-dim">{item.description}</div>
                  <div className="mt-1 font-mono text-[10px] text-text-dim/80">{item.key}</div>
                </div>
                {item.overridden && (
                  <ActionButton
                    label="Reset"
                    size="small"
                    variant="ghost"
                    onPress={() => onReset(item)}
                    disabled={resetPending}
                    icon={<RotateCcw size={12} />}
                  />
                )}
              </div>
              <div className="mt-3">
                <SettingControl
                  item={item}
                  value={values[item.key] ?? ""}
                  values={values}
                  onChange={(next) => onChange(item.key, next)}
                  onChangeKey={onChange}
                />
              </div>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

function OverviewPanel({ groups, settingsByKey }: { groups: SettingsGroup[]; settingsByKey: Map<string, SettingItem> }) {
  const { data: status } = useSystemStatus();
  const { data: version } = useVersion();
  const checkUpdate = useCheckUpdate();
  const togglePause = useTogglePause();
  const [showRestart, setShowRestart] = useState(false);

  const overridden = groups.reduce((count, group) => count + group.settings.filter((item) => item.overridden).length, 0);
  const totalSettings = groups.reduce((count, group) => count + group.settings.length, 0);
  const paused = status?.paused ?? settingsByKey.get("SYSTEM_PAUSED")?.value === true;

  const links = [
    { label: "Providers", description: "Provider accounts, models, and credentials.", href: "/admin/providers", icon: <Server size={15} /> },
    { label: "Memory & Knowledge", description: "Inspect memory, knowledge, skills, and dreaming jobs.", href: "/admin/learning", icon: <Database size={15} /> },
    { label: "Usage", description: "Costs, token spikes, traces, and anomaly investigation.", href: "/admin/usage", icon: <Activity size={15} /> },
    { label: "Notifications", description: "Reusable alert targets, bot grants, and delivery history.", href: "/admin/notifications", icon: <Bell size={15} /> },
    { label: "Machines", description: "Provider profiles, targets, readiness probes, and leases.", href: "/admin/machines", icon: <HardDrive size={15} /> },
    { label: "Integrations", description: "Integration activation, assets, and manifests.", href: "/admin/integrations", icon: <Wrench size={15} /> },
    { label: "Security", description: "Secrets, API keys, approvals, and tool policies.", href: "/admin/api-keys", icon: <Shield size={15} /> },
  ];

  return (
    <div className="flex flex-col gap-6">
      <Section
        title="System status"
        description="Operational state and high-level maintenance actions."
        action={
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge label={paused ? "Paused" : "Running"} variant={paused ? "warning" : "success"} />
            <ActionButton
              label={togglePause.isPending ? "Working" : paused ? "Resume" : "Pause"}
              onPress={() => togglePause.mutate(!paused)}
              size="small"
              variant={paused ? "primary" : "secondary"}
            />
            <ActionButton
              label="Restart"
              onPress={() => setShowRestart(true)}
              size="small"
              variant="danger"
              icon={<RefreshCw size={12} />}
            />
          </div>
        }
      >
        <SettingsStatGrid
          items={[
            { label: "Version", value: version ? `v${version}` : "..." },
            { label: "Settings", value: totalSettings },
            { label: "Overrides", value: overridden, tone: overridden ? "accent" : "default" },
            { label: "Groups", value: groups.length },
          ]}
        />
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            label={checkUpdate.isFetching ? "Checking" : "Check for update"}
            onPress={() => checkUpdate.refetch()}
            disabled={checkUpdate.isFetching}
            icon={checkUpdate.isFetching ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          />
          {checkUpdate.data?.update_available && (
            <StatusBadge label={`v${checkUpdate.data.latest} available`} variant="info" />
          )}
          {checkUpdate.data && !checkUpdate.data.update_available && !checkUpdate.data.error && (
            <StatusBadge label="Up to date" variant="success" />
          )}
          {checkUpdate.data?.latest_url && (
            <a
              href={checkUpdate.data.latest_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-accent hover:bg-accent/[0.08]"
            >
              Release <ExternalLink size={12} />
            </a>
          )}
        </div>
      </Section>

      <Section title="System domains" description="Jump by operational intent instead of raw environment variable group. Each domain keeps detailed ownership links close by.">
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-3">
          {DOMAIN_TABS.map((tab) => {
            const settings = settingsForDomain(tab, settingsByKey);
            const overriddenCount = settings.filter((item) => item.overridden).length;
            const missingCount = DOMAIN_KEYS[tab].length - settings.length;
            return (
              <Link key={tab} to={`/settings/system#${encodeURIComponent(tab)}`}>
                <SettingsControlRow
                  leading={DOMAIN_ICONS[tab]}
                  title={tab}
                  description={DOMAIN_DESCRIPTIONS[tab]}
                  meta={
                    <div className="flex flex-wrap items-center gap-1.5">
                      <QuietPill label={`${settings.length} settings`} />
                      {overriddenCount > 0 && <StatusBadge label={`${overriddenCount} overrides`} variant="info" />}
                      {missingCount > 0 && <QuietPill label={`${missingCount} unmapped`} />}
                    </div>
                  }
                />
              </Link>
            );
          })}
        </div>
      </Section>

      <Section title="Canonical admin surfaces" description="Settings summarizes global defaults. These pages own the detailed workflows.">
        <div className="grid gap-2 md:grid-cols-2">
          {links.map((link) => (
            <Link key={link.href} to={link.href} className="block">
              <SettingsControlRow
                leading={link.icon}
                title={link.label}
                description={link.description}
                action={<ExternalLink size={13} className="text-text-dim" />}
              />
            </Link>
          ))}
        </div>
      </Section>

      {showRestart && <RestartConfirmModal onClose={() => setShowRestart(false)} />}
    </div>
  );
}

function AdvancedPanel({
  groups,
  values,
  dirtyKeys,
  status,
  updatePending,
  resetPending,
  onChange,
  onSave,
  onReset,
}: {
  groups: SettingsGroup[];
  values: Record<string, string>;
  dirtyKeys: Set<string>;
  status: "idle" | "dirty" | "pending" | "saved" | "error";
  updatePending: boolean;
  resetPending: boolean;
  onChange: (key: string, value: string) => void;
  onSave: (keys?: string[]) => void;
  onReset: (item: SettingItem) => void;
}) {
  const [query, setQuery] = useState("");
  const filteredGroups = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return groups;
    return groups
      .map((group) => ({
        ...group,
        settings: group.settings.filter((item) =>
          `${group.group} ${item.key} ${item.label} ${item.description}`.toLowerCase().includes(q),
        ),
      }))
      .filter((group) => group.settings.length > 0);
  }, [groups, query]);

  return (
    <div className="flex flex-col gap-5">
      <InfoBanner variant="info" icon={<Search size={14} />}>
        Advanced is the full schema registry. Promote frequently used controls into domain sections before creating page-local settings UIs.
      </InfoBanner>
      <SettingsSearchBox value={query} onChange={setQuery} placeholder="Filter settings registry..." className="max-w-xl" />
      {filteredGroups.length === 0 ? (
        <EmptyState message="No settings match that filter." />
      ) : (
        filteredGroups.map((group) => (
          <SettingsDomainSection
            key={group.group}
            title={group.group}
            description={`${group.settings.length} registry setting${group.settings.length === 1 ? "" : "s"}.`}
            settings={group.settings}
            values={values}
            dirtyKeys={dirtyKeys}
            status={status}
            updatePending={updatePending}
            resetPending={resetPending}
            onChange={onChange}
            onSave={onSave}
            onReset={onReset}
          />
        ))
      )}
    </div>
  );
}

function DomainPanel({
  tab,
  settingsByKey,
  values,
  dirtyKeys,
  status,
  updatePending,
  resetPending,
  onChange,
  onSave,
  onReset,
}: {
  tab: Exclude<SystemTab, "Overview" | "Advanced">;
  settingsByKey: Map<string, SettingItem>;
  values: Record<string, string>;
  dirtyKeys: Set<string>;
  status: "idle" | "dirty" | "pending" | "saved" | "error";
  updatePending: boolean;
  resetPending: boolean;
  onChange: (key: string, value: string) => void;
  onSave: (keys?: string[]) => void;
  onReset: (item: SettingItem) => void;
}) {
  const settings = useMemo(() => settingsForDomain(tab, settingsByKey), [tab, settingsByKey]);
  const overriddenCount = settings.filter((item) => item.overridden).length;
  const readOnlyCount = settings.filter((item) => item.read_only).length;
  const missingCount = DOMAIN_KEYS[tab].length - settings.length;
  const surfaces = DOMAIN_SURFACES[tab];

  return (
    <div className="flex flex-col gap-6">
      <Section title="Domain map" description="The setting rows below are global defaults. These linked surfaces own the deeper workflows and inspection views.">
        <SettingsStatGrid
          items={[
            { label: "Mapped", value: settings.length },
            { label: "Overrides", value: overriddenCount, tone: overriddenCount ? "accent" : "default" },
            { label: "Read only", value: readOnlyCount },
            { label: "Unmapped", value: missingCount, tone: missingCount ? "warning" : "success" },
          ]}
        />
        <div className="grid gap-2 md:grid-cols-2">
          {surfaces.map((surface) => (
            <Link key={surface.href} to={surface.href}>
              <SettingsControlRow
                leading={DOMAIN_ICONS[tab]}
                title={surface.label}
                description={`Open the canonical ${surface.label.toLowerCase()} surface.`}
                action={<ExternalLink size={13} className="text-text-dim" />}
              />
            </Link>
          ))}
        </div>
      </Section>
      <SettingsDomainSection
        title={tab}
        description={DOMAIN_DESCRIPTIONS[tab]}
        settings={settings}
        values={values}
        dirtyKeys={dirtyKeys}
        status={status}
        updatePending={updatePending}
        resetPending={resetPending}
        onChange={onChange}
        onSave={onSave}
        onReset={onReset}
      />
    </div>
  );
}

export default function SystemSettingsPage() {
  const { data, isLoading, error } = useSettings();
  const updateSettings = useUpdateSettings();
  const resetSetting = useResetSetting();
  const location = useLocation();
  const navigate = useNavigate();

  const requested = decodeHash(location.hash);
  const activeTab: SystemTab = TABS.includes(requested as SystemTab)
    ? (requested as SystemTab)
    : LEGACY_HASH_MAP[requested] ?? "Overview";

  const groups = data?.groups ?? [];
  const allSettings = useMemo(() => groups.flatMap((group) => group.settings), [groups]);
  const settingsByKey = useMemo(() => settingMap(groups), [groups]);
  const settingsSignature = useMemo(
    () => allSettings.map((item) => `${item.key}:${formatSettingValue(item.value)}`).join("|"),
    [allSettings],
  );
  const [values, setValues] = useState<Record<string, string>>({});
  const [status, setStatus] = useState<"idle" | "dirty" | "pending" | "saved" | "error">("idle");

  useEffect(() => {
    setValues(Object.fromEntries(allSettings.map((item) => [item.key, formatSettingValue(item.value)])));
    setStatus("idle");
  }, [settingsSignature, allSettings]);

  const dirtyKeys = useMemo(() => new Set(
    allSettings
      .filter((item) => !item.read_only && values[item.key] !== formatSettingValue(item.value))
      .map((item) => item.key),
  ), [allSettings, values]);

  const handleSettingChange = (key: string, value: string) => {
    setValues((prev) => ({ ...prev, [key]: value }));
    setStatus("dirty");
  };

  const saveSettings = async (keys?: string[]) => {
    const requestedKeys = keys?.length ? keys : Array.from(dirtyKeys);
    const expandedKeys = new Set(requestedKeys);
    for (const key of requestedKeys) {
      const companion = providerCompanionKey(key);
      if (companion) expandedKeys.add(companion);
    }
    const keysToSave = Array.from(expandedKeys).filter((key) => dirtyKeys.has(key));
    if (!keysToSave.length) return;
    const updates: Record<string, unknown> = {};
    for (const key of keysToSave) {
      const item = settingsByKey.get(key);
      if (!item || item.read_only) continue;
      updates[key] = parseSettingValue(item, values[key] ?? "");
    }
    if (Object.keys(updates).length === 0) return;
    setStatus("pending");
    try {
      await updateSettings.mutateAsync(updates);
      setStatus("saved");
      window.setTimeout(() => setStatus("idle"), 1800);
    } catch {
      setStatus("error");
    }
  };

  const revertSettings = () => {
    setValues(Object.fromEntries(allSettings.map((item) => [item.key, formatSettingValue(item.value)])));
    setStatus("idle");
  };

  const resetSystemSetting = async (item: SettingItem) => {
    await resetSetting.mutateAsync(item.key);
  };

  const effectiveStatus: "idle" | "dirty" | "pending" | "saved" | "error" =
    status === "idle" && dirtyKeys.size ? "dirty" : status;

  const setTab = (tab: SystemTab) => {
    navigate(`/settings/system#${encodeURIComponent(tab)}`, { replace: true });
  };

  if (isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Spinner size={18} />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-4 p-6">
        <InfoBanner variant="danger" icon={<AlertTriangle size={14} />}>
          Failed to load server settings.
        </InfoBanner>
      </div>
    );
  }

  return (
    <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-4 py-5 md:px-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <SettingsGroupLabel label="Admin settings" icon={<SlidersHorizontal size={13} className="text-text-dim" />} />
          <h2 className="mt-1 text-[18px] font-semibold tracking-[-0.01em] text-text">System control center</h2>
          <p className="mt-1 max-w-[72ch] text-[12px] leading-relaxed text-text-dim">{DOMAIN_DESCRIPTIONS[activeTab]}</p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <SaveStatusPill
            tone={saveTone(effectiveStatus)}
            label={
              effectiveStatus === "pending"
                ? "Saving changes"
                : effectiveStatus === "saved"
                  ? "Saved"
                  : effectiveStatus === "error"
                    ? "Save failed"
                    : effectiveStatus === "dirty"
                      ? `${dirtyKeys.size} unsaved`
                      : ""
            }
          />
          <ActionButton
            label="Revert"
            onPress={revertSettings}
            variant="secondary"
            disabled={!dirtyKeys.size || updateSettings.isPending}
          />
          <ActionButton
            label={updateSettings.isPending ? "Saving" : "Save"}
            onPress={() => saveSettings()}
            disabled={!dirtyKeys.size || updateSettings.isPending}
            icon={updateSettings.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
          />
          <Link to="/admin/config-state" className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted hover:bg-surface-overlay/60 hover:text-text">
            Config state <ExternalLink size={12} />
          </Link>
          <Link to="/admin/diagnostics" className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted hover:bg-surface-overlay/60 hover:text-text">
            Diagnostics <ExternalLink size={12} />
          </Link>
        </div>
      </div>

      <div className="sticky top-0 z-10 -mx-4 bg-surface/95 px-4 py-2 backdrop-blur md:-mx-6 md:px-6">
        <div className="flex flex-col gap-2 xl:flex-row xl:items-center">
          <div className="-mx-1 min-w-0 overflow-x-auto px-1 xl:flex-1">
            <SettingsSegmentedControl<SystemTab>
              value={activeTab}
              onChange={setTab}
              options={TABS.map((tab) => ({ value: tab, label: tab }))}
              className="w-max min-w-full"
            />
          </div>
          <div className="flex shrink-0 items-center justify-end gap-2 xl:ml-auto">
            <SaveStatusPill
              tone={saveTone(effectiveStatus)}
              label={
                effectiveStatus === "pending"
                  ? "Saving changes"
                  : effectiveStatus === "saved"
                    ? "Saved"
                    : effectiveStatus === "error"
                      ? "Save failed"
                      : effectiveStatus === "dirty"
                        ? `${dirtyKeys.size} unsaved`
                        : ""
              }
            />
            <ActionButton
              label={updateSettings.isPending ? "Saving" : "Save"}
              onPress={() => saveSettings()}
              disabled={!dirtyKeys.size || updateSettings.isPending}
              icon={updateSettings.isPending ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            />
          </div>
        </div>
      </div>

      <div className={cn("flex flex-col gap-6", activeTab === "Advanced" && "pb-8")}>
        {activeTab === "Overview" ? (
          <OverviewPanel groups={groups} settingsByKey={settingsByKey} />
        ) : activeTab === "Advanced" ? (
          <AdvancedPanel
            groups={groups}
            values={values}
            dirtyKeys={dirtyKeys}
            status={effectiveStatus}
            updatePending={updateSettings.isPending}
            resetPending={resetSetting.isPending}
            onChange={handleSettingChange}
            onSave={saveSettings}
            onReset={resetSystemSetting}
          />
        ) : (
          <DomainPanel
            tab={activeTab}
            settingsByKey={settingsByKey}
            values={values}
            dirtyKeys={dirtyKeys}
            status={effectiveStatus}
            updatePending={updateSettings.isPending}
            resetPending={resetSetting.isPending}
            onChange={handleSettingChange}
            onSave={saveSettings}
            onReset={resetSystemSetting}
          />
        )}
      </div>
    </div>
  );
}
