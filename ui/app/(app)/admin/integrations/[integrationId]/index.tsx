import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Check,
  CheckCircle2,
  Copy,
  Download,
  ExternalLink,
  Key,
  Link,
  Play,
  Power,
  RefreshCw,
  RotateCcw,
  Square,
  Trash2,
  Unlink,
  X,
} from "lucide-react";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { Spinner } from "@/src/components/shared/Spinner";
import { Section, TextInput, Toggle } from "@/src/components/shared/FormControls";
import {
  ActionButton,
  EmptyState,
  InfoBanner,
  QuietPill,
  SettingsControlRow,
  SettingsGroupLabel,
  StatusBadge as SharedStatusBadge,
} from "@/src/components/shared/SettingsControls";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { LlmModelDropdown } from "@/src/components/shared/LlmModelDropdown";
import { MarkdownViewer } from "@/src/components/workspace/MarkdownViewer";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { writeToClipboard } from "@/src/utils/clipboard";
import { useAuthStore } from "@/src/stores/auth";
import {
  useAutoStart,
  useDeleteIntegrationSetting,
  useInstallDeps,
  useInstallNpmDeps,
  useInstallSystemDep,
  useIntegrationApiKey,
  useIntegrationSettings,
  useIntegrations,
  useOAuthDisconnect,
  useOAuthStatus,
  useProvisionIntegrationApiKey,
  useRestartProcess,
  useRevokeIntegrationApiKey,
  useSetAutoStart,
  useSetIntegrationStatus,
  useStartProcess,
  useStopProcess,
  useUpdateIntegrationSettings,
  type IntegrationItem,
} from "@/src/api/hooks/useIntegrations";
import { AssetPill, CapBadge, EnvVarPill, StatusBadge, formatUptime } from "../components";
import { DeviceStatusSection } from "./DeviceStatusSection";
import { IntegrationDebugSection } from "./IntegrationDebugSection";
import { MachineControlSetupSection } from "./MachineControlSetupSection";
import { ManifestEditor } from "./ManifestEditor";
import { ProcessLogsSection } from "./ProcessLogsSection";

function sourceBadgeVariant(source: string): "info" | "purple" | "neutral" {
  if (source === "db") return "info";
  if (source === "env") return "purple";
  return "neutral";
}

function WebhookRow({ webhook }: { webhook: IntegrationItem["webhook"] }) {
  const [copied, setCopied] = useState(false);
  if (!webhook) return null;
  const handleCopy = async () => {
    await writeToClipboard(webhook.url);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1500);
  };
  return (
    <SettingsControlRow
      title="Webhook"
      description={<code className="break-all font-mono">{webhook.path}</code>}
      action={
        <ActionButton
          label={copied ? "Copied" : "Copy URL"}
          onPress={() => void handleCopy()}
          variant="secondary"
          size="small"
          icon={<Copy size={12} />}
        />
      }
    />
  );
}

function SettingsForm({ integrationId }: { integrationId: string }) {
  const { data, isLoading } = useIntegrationSettings(integrationId);
  const updateMut = useUpdateIntegrationSettings(integrationId);
  const deleteMut = useDeleteIntegrationSetting(integrationId);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [initialized, setInitialized] = useState(false);
  const settings = data?.settings ?? [];

  if (settings.length > 0 && !initialized) {
    const initial: Record<string, string> = {};
    for (const setting of settings) {
      initial[setting.key] = setting.secret && setting.is_set ? "" : (setting.value ?? "");
    }
    setDraft(initial);
    setInitialized(true);
  }

  if (isLoading) return <div className="text-[12px] text-text-dim">Loading settings...</div>;
  if (settings.length === 0) return <EmptyState message="No configurable settings." />;

  const handleSave = () => {
    const updates: Record<string, string> = {};
    for (const setting of settings) {
      const value = draft[setting.key] ?? "";
      if (setting.secret && setting.is_set && value === "") continue;
      if (!setting.secret && value === (setting.value ?? "")) continue;
      if (value !== "" || setting.source === "db") updates[setting.key] = value;
    }
    if (Object.keys(updates).length > 0) updateMut.mutate(updates);
  };

  const handleReset = (key: string) => {
    deleteMut.mutate(key);
    setDraft((current) => ({ ...current, [key]: "" }));
  };

  return (
    <div className="flex flex-col gap-4">
      {settings.map((setting) => (
        <div key={setting.key} className="flex flex-col gap-2">
          <div className="flex flex-wrap items-center gap-1.5">
            <label className="font-mono text-[12px] font-semibold text-text-muted">{setting.key}</label>
            <SharedStatusBadge label={setting.source} variant={sourceBadgeVariant(setting.source)} />
            {!setting.required && <QuietPill label="optional" />}
            {setting.source === "db" && (
              <button
                type="button"
                onClick={() => handleReset(setting.key)}
                title="Reset to env/default"
                className="inline-flex h-7 w-7 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-text"
              >
                <RotateCcw size={12} />
              </button>
            )}
          </div>
          {setting.type === "model_selection" ? (
            <LlmModelDropdown
              value={draft[setting.key] ?? ""}
              onChange={(modelId) => setDraft((current) => ({ ...current, [setting.key]: modelId }))}
              placeholder={setting.description || "Select model..."}
              allowClear
            />
          ) : setting.type === "boolean" ? (
            <Toggle
              value={(draft[setting.key] ?? setting.value ?? setting.default ?? "true").toLowerCase() === "true"}
              onChange={(next) => setDraft((current) => ({ ...current, [setting.key]: String(next) }))}
              label={(draft[setting.key] ?? setting.value ?? setting.default ?? "true").toLowerCase() === "true" ? "Enabled" : "Disabled"}
            />
          ) : (
            <TextInput
              type={setting.secret ? "password" : "text"}
              value={draft[setting.key] ?? ""}
              onChangeText={(next) => setDraft((current) => ({ ...current, [setting.key]: next }))}
              placeholder={setting.secret && setting.is_set ? "••••• (unchanged)" : setting.description}
            />
          )}
          {setting.description && <div className="text-[11px] leading-snug text-text-dim">{setting.description}</div>}
        </div>
      ))}
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton
          label={updateMut.isPending ? "Saving..." : "Save settings"}
          onPress={handleSave}
          disabled={updateMut.isPending}
          size="small"
        />
        {updateMut.isSuccess && <SharedStatusBadge label="Saved" variant="success" />}
        {updateMut.isError && <SharedStatusBadge label="Error saving" variant="danger" />}
      </div>
    </div>
  );
}

function ProcessControls({ integrationId }: { integrationId: string }) {
  const startMut = useStartProcess(integrationId);
  const stopMut = useStopProcess(integrationId);
  const restartMut = useRestartProcess(integrationId);
  const { data: autoStartData } = useAutoStart(integrationId, true);
  const setAutoStartMut = useSetAutoStart(integrationId);
  const { data: integrations } = useIntegrations();
  const item = integrations?.integrations?.find((integration) => integration.id === integrationId);
  const ps = item?.process_status;
  const running = ps?.status === "running";
  const pending = startMut.isPending || stopMut.isPending || restartMut.isPending;
  const err = startMut.error || stopMut.error || restartMut.error;

  return (
    <div className="flex flex-col gap-3">
      <SettingsControlRow
        leading={<Power size={14} />}
        title={running ? "Running" : "Stopped"}
        description={
          <span>
            {running && ps?.pid ? `pid ${ps.pid}` : "Background process"}
            {running && ps?.uptime_seconds != null ? ` · ${formatUptime(ps.uptime_seconds)}` : ""}
            {!running && ps?.exit_code != null && ps.exit_code !== 0 ? ` · exit ${ps.exit_code}` : ""}
          </span>
        }
        meta={<SharedStatusBadge label={running ? "running" : "stopped"} variant={running ? "success" : "neutral"} />}
        action={
          <div className="flex flex-wrap items-center gap-1.5">
            {!running ? (
              <ActionButton
                label="Start"
                onPress={() => startMut.mutate()}
                disabled={pending}
                size="small"
                icon={<Play size={12} />}
              />
            ) : (
              <>
                <ActionButton
                  label="Stop"
                  onPress={() => stopMut.mutate()}
                  disabled={pending}
                  variant="danger"
                  size="small"
                  icon={<Square size={12} />}
                />
                <ActionButton
                  label="Restart"
                  onPress={() => restartMut.mutate()}
                  disabled={pending}
                  variant="secondary"
                  size="small"
                  icon={<RefreshCw size={12} />}
                />
              </>
            )}
          </div>
        }
      />
      {err && (
        <InfoBanner variant="danger">
          {(err as any)?.message || "Process action failed"}
        </InfoBanner>
      )}
      <Toggle
        value={autoStartData?.auto_start ?? true}
        onChange={(next) => setAutoStartMut.mutate(next)}
        label="Auto-start on server startup"
      />
    </div>
  );
}

function DependencySection({ item, kind }: { item: IntegrationItem; kind: "python" | "npm" | "system" }) {
  const installPython = useInstallDeps(item.id);
  const installNpm = useInstallNpmDeps(item.id);
  const installSystem = useInstallSystemDep(item.id);
  const deps =
    kind === "python"
      ? item.python_dependencies?.map((dep) => ({ name: dep.package, installed: dep.installed, install: dep.package }))
      : kind === "npm"
        ? item.npm_dependencies?.map((dep) => ({ name: dep.package, installed: dep.installed, install: dep.package }))
        : item.system_dependencies?.map((dep) => ({ name: dep.binary, installed: dep.installed, install: dep.apt_package }));

  if (!deps || deps.length === 0) return null;
  const allInstalled = deps.every((dep) => dep.installed);
  const pending = installPython.isPending || installNpm.isPending || installSystem.isPending;
  const failed = installPython.isError || installNpm.isError || installSystem.isError;

  const handleInstall = () => {
    if (kind === "python") installPython.mutate();
    else if (kind === "npm") installNpm.mutate();
    else deps.filter((dep) => !dep.installed).forEach((dep) => installSystem.mutate(dep.install));
  };

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5">
        {deps.map((dep) => (
          <SharedStatusBadge
            key={dep.name}
            label={dep.name}
            variant={dep.installed ? "success" : "danger"}
          />
        ))}
      </div>
      {!allInstalled ? (
        <div className="flex flex-wrap items-center gap-2">
          <ActionButton
            label={pending ? "Installing..." : `Install ${kind === "npm" ? "npm packages" : kind === "system" ? "system dependencies" : "dependencies"}`}
            onPress={handleInstall}
            disabled={pending}
            size="small"
            icon={<Download size={12} />}
          />
          {failed && <SharedStatusBadge label="Install failed" variant="danger" />}
        </div>
      ) : (
        <SharedStatusBadge label="All dependencies available" variant="success" />
      )}
    </div>
  );
}

function OAuthSection({ item }: { item: IntegrationItem }) {
  const oauth = item.oauth;
  if (!oauth) return null;
  const requiredVarsSet = item.env_vars.filter((envVar) => envVar.required).every((envVar) => envVar.is_set);
  const { data: status, isLoading } = useOAuthStatus(item.id, oauth.status);
  const disconnectMut = useOAuthDisconnect(item.id, oauth.disconnect);
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const [selectedScopes, setSelectedScopes] = useState<string[]>(oauth.scope_services.slice(0, 3));

  if (!requiredVarsSet) {
    return <div className="text-[12px] text-text-dim">Save the required credentials above first, then connect your account here.</div>;
  }
  if (isLoading) return <div className="text-[12px] text-text-dim">Checking connection...</div>;

  const toggleScope = (scope: string) => {
    setSelectedScopes((current) =>
      current.includes(scope) ? current.filter((item) => item !== scope) : [...current, scope],
    );
  };

  const handleConnect = () => {
    const { serverUrl } = useAuthStore.getState();
    window.open(`${serverUrl}${oauth.auth_start}?scopes=${selectedScopes.join(",")}`, "_blank");
  };

  if (status?.connected) {
    return (
      <div className="flex flex-col gap-3">
        <SettingsControlRow
          leading={<Link size={14} />}
          title={status.email ? `Connected as ${status.email}` : "Connected"}
          meta={<SharedStatusBadge label="connected" variant="success" />}
          action={
            <ActionButton
              label={disconnectMut.isPending ? "Disconnecting..." : "Disconnect"}
              onPress={async () => {
                const ok = await confirm(
                  "Disconnect account? Bots will lose access to this integration's OAuth services.",
                  { title: "Disconnect", confirmLabel: "Disconnect", variant: "danger" },
                );
                if (ok) disconnectMut.mutate();
              }}
              disabled={disconnectMut.isPending}
              variant="danger"
              size="small"
              icon={<Unlink size={12} />}
            />
          }
        />
        {status.scopes && status.scopes.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {status.scopes.map((scope) => <QuietPill key={scope} label={scope} maxWidthClass="max-w-[220px]" />)}
          </div>
        )}
        <ConfirmDialogSlot />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="text-[12px] text-text-dim">Select services to authorize, then connect your account.</div>
      <div className="flex flex-wrap gap-1.5">
        {oauth.scope_services.map((scope) => {
          const active = selectedScopes.includes(scope);
          return (
            <button
              key={scope}
              type="button"
              onClick={() => toggleScope(scope)}
              className={
                `inline-flex min-h-[32px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold transition-colors ` +
                (active ? "bg-accent/[0.08] text-accent" : "bg-surface-raised/40 text-text-dim hover:bg-surface-overlay/50")
              }
            >
              {active ? <Check size={10} /> : <X size={10} />}
              {scope}
            </button>
          );
        })}
      </div>
      <ActionButton
        label="Connect account"
        onPress={handleConnect}
        disabled={selectedScopes.length === 0}
        size="small"
        icon={<Link size={13} />}
      />
    </div>
  );
}

function ApiKeySection({ integrationId }: { integrationId: string }) {
  const { data, isLoading } = useIntegrationApiKey(integrationId, true);
  const provisionMut = useProvisionIntegrationApiKey(integrationId);
  const revokeMut = useRevokeIntegrationApiKey(integrationId);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const displayKey = revealedKey ?? provisionMut.data?.key_value ?? null;

  const handleProvision = () => {
    setRevealedKey(null);
    provisionMut.mutate(undefined, {
      onSuccess: (result) => {
        if (result.key_value) setRevealedKey(result.key_value);
      },
    });
  };

  const handleCopyKey = async () => {
    if (!displayKey) return;
    await writeToClipboard(displayKey);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 2000);
  };

  if (isLoading) return <div className="text-[12px] text-text-dim">Loading...</div>;

  return (
    <div className="flex flex-col gap-3">
      {data?.provisioned ? (
        <SettingsControlRow
          leading={<Key size={14} />}
          title={`${data.key_prefix}...`}
          description={data.scopes ? `${data.scopes.length} scope${data.scopes.length !== 1 ? "s" : ""}` : undefined}
          meta={<SharedStatusBadge label="provisioned" variant="success" />}
          action={
            <div className="flex flex-wrap items-center gap-1.5">
              <ActionButton
                label="Regenerate"
                onPress={handleProvision}
                disabled={provisionMut.isPending}
                variant="secondary"
                size="small"
                icon={<RefreshCw size={12} />}
              />
              <ActionButton
                label="Revoke"
                onPress={() => revokeMut.mutate()}
                disabled={revokeMut.isPending}
                variant="danger"
                size="small"
                icon={<Trash2 size={12} />}
              />
            </div>
          }
        />
      ) : (
        <SettingsControlRow
          title="No key provisioned"
          description="Generate a scoped key for this integration."
          action={
            <ActionButton
              label={provisionMut.isPending ? "Generating..." : "Generate key"}
              onPress={handleProvision}
              disabled={provisionMut.isPending}
              size="small"
              icon={<Key size={12} />}
            />
          }
        />
      )}
      {data?.scopes && data.scopes.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {data.scopes.map((scope) => <QuietPill key={scope} label={scope} maxWidthClass="max-w-[220px]" />)}
        </div>
      )}
      {displayKey && (
        <InfoBanner variant="warning">
          <div className="flex min-w-0 items-center gap-2">
            <code className="min-w-0 flex-1 break-all font-mono text-[11px] text-text">{displayKey}</code>
            <button
              type="button"
              onClick={() => void handleCopyKey()}
              className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-text-dim transition-colors hover:bg-surface-overlay/60 hover:text-text"
              title="Copy key"
            >
              {copied ? <Check size={14} className="text-success" /> : <Copy size={14} />}
            </button>
          </div>
        </InfoBanner>
      )}
    </div>
  );
}

function ReadmeSection({ content }: { content: string }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="flex flex-col gap-2">
      <ActionButton
        label={expanded ? "Hide setup instructions" : "Setup instructions"}
        onPress={() => setExpanded((current) => !current)}
        variant="secondary"
        size="small"
      />
      {expanded && (
        <div className="max-h-[420px] overflow-auto rounded-md bg-surface-raised/35">
          <MarkdownViewer content={content} />
        </div>
      )}
    </div>
  );
}

function StatusControl({ item }: { item: IntegrationItem }) {
  const mutation = useSetIntegrationStatus(item.id);
  const { confirm, ConfirmDialogSlot } = useConfirm();
  const enabled = item.lifecycle_status === "enabled";
  const missingRequired = item.env_vars.filter((envVar) => envVar.required && !envVar.is_set);
  const needsSetup = enabled && missingRequired.length > 0;

  return (
    <div className="flex flex-col gap-2">
      <SettingsControlRow
        leading={<Power size={14} />}
        title={!enabled ? "Available - not adopted" : needsSetup ? "Enabled - needs setup" : "Enabled"}
        description={
          needsSetup
            ? `Fill ${missingRequired.length} required setting${missingRequired.length === 1 ? "" : "s"} to activate: ${missingRequired.map((envVar) => envVar.key).join(", ")}.`
            : enabled
              ? "This integration is active."
              : "Settings are preserved when you remove an integration from Active."
        }
        meta={<StatusBadge status={needsSetup ? "needs_setup" : item.lifecycle_status} />}
        action={
          !enabled ? (
            <ActionButton
              label={mutation.isPending ? "Enabling..." : "Enable"}
              onPress={() => mutation.mutate("enabled")}
              disabled={mutation.isPending}
              size="small"
            />
          ) : (
            <ActionButton
              label={mutation.isPending ? "Disabling..." : "Disable"}
              onPress={async () => {
                const ok = await confirm(
                  "Remove from Active? The process will stop and tools will unload. Settings are preserved.",
                  { title: "Remove from Active", confirmLabel: "Remove", variant: "warning" },
                );
                if (ok) mutation.mutate("available");
              }}
              disabled={mutation.isPending}
              variant="danger"
              size="small"
            />
          )
        }
      />
      <ConfirmDialogSlot />
    </div>
  );
}

function DenseChipGroup<T>({
  items,
  initialLimit = 18,
  getKey,
  renderItem,
}: {
  items: T[];
  initialLimit?: number;
  getKey: (item: T) => string;
  renderItem: (item: T) => React.ReactNode;
}) {
  const [expanded, setExpanded] = useState(false);
  const visibleItems = expanded ? items : items.slice(0, initialLimit);
  const hiddenCount = items.length - visibleItems.length;

  return (
    <div className="flex flex-wrap gap-1.5">
      {visibleItems.map((item) => (
        <span key={getKey(item)}>{renderItem(item)}</span>
      ))}
      {items.length > initialLimit && (
        <button
          type="button"
          onClick={() => setExpanded((current) => !current)}
          className="inline-flex shrink-0 items-center rounded-full bg-surface-overlay/35 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-[0.05em] text-text-muted transition-colors hover:bg-surface-overlay/60 hover:text-text"
        >
          {expanded ? "Show fewer" : `+${hiddenCount} more`}
        </button>
      )}
    </div>
  );
}

function AssetList({ title, items, tone = "neutral" }: { title: string; items?: string[]; tone?: "neutral" | "info" | "purple" }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="flex flex-col gap-1.5">
      <SettingsGroupLabel label={title} count={items.length} />
      <DenseChipGroup
        items={items}
        getKey={(item) => item}
        renderItem={(item) => <AssetPill label={item} tone={tone} />}
      />
    </div>
  );
}

export default function IntegrationDetailScreen() {
  const { integrationId } = useParams<{ integrationId: string }>();
  const navigate = useNavigate();
  const { data, isLoading } = useIntegrations();
  const { refreshing, onRefresh } = usePageRefresh();
  const item = data?.integrations?.find((integration) => integration.id === integrationId);

  if (isLoading) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <Spinner />
      </div>
    );
  }

  if (!item) {
    return (
      <div className="flex flex-1 items-center justify-center bg-surface">
        <div className="flex flex-col items-center gap-3">
          <div className="text-[13px] text-text-dim">Integration not found.</div>
          <ActionButton label="Back to Integrations" onPress={() => navigate("/admin/integrations")} />
        </div>
      </div>
    );
  }

  const envSetCount = item.env_vars.filter((envVar) => envVar.is_set).length;
  const headerStatus = item.lifecycle_status === "enabled" && item.env_vars.some((envVar) => envVar.required && !envVar.is_set)
    ? "needs_setup"
    : item.lifecycle_status;
  const liveToolNames = item.tool_names && item.tool_names.length > 0 ? item.tool_names : item.tool_files ?? [];
  const hasAssets = liveToolNames.length > 0 || (item.skill_files?.length ?? 0) > 0 || (item.tool_widget_names?.length ?? 0) > 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Integrations"
        backTo="/admin/integrations"
        title={item.name}
        subtitle={item.id}
        right={<StatusBadge status={headerStatus} />}
      />
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="min-h-0 flex-1">
        <div className="mx-auto flex w-full max-w-4xl flex-col gap-7 px-4 py-5 md:px-6">
          <StatusControl item={item} />

          <div className={item.lifecycle_status === "available" ? "flex flex-col gap-7 opacity-70" : "flex flex-col gap-7"}>
            <Section title="Overview" description="Declared surfaces and runtime identity for this integration.">
              <div className="flex flex-col gap-3">
                <div className="flex flex-wrap gap-1.5">
                  <CapBadge label="router" active={item.has_router} />
                  <CapBadge label="renderer" active={item.has_renderer} />
                  <CapBadge label="hooks" active={item.has_hooks} />
                  <CapBadge label="tools" active={item.has_tools} />
                  <CapBadge label="skills" active={item.has_skills} />
                  <CapBadge label="widgets" active={item.has_tool_widgets} />
                  <CapBadge label="process" active={item.has_process} />
                  <CapBadge label="machines" active={Boolean(item.machine_control)} />
                </div>
                <WebhookRow webhook={item.webhook} />
                <SettingsControlRow
                  title="Source"
                  description={item.source}
                  meta={<SharedStatusBadge label={item.source} variant="neutral" />}
                />
              </div>
            </Section>

            <DeviceStatusSection integrationId={item.id} />

            <Section title="Manifest" description="Inspect and edit the integration manifest.">
              <ManifestEditor integrationId={item.id} />
            </Section>

            {item.events && item.events.length > 0 && (
              <Section title={`Events (${item.events.length})`} description="Events this integration can emit for task triggers and binding filters.">
                <div className="flex flex-col gap-1.5">
                  {item.events.map((event) => (
                    <SettingsControlRow
                      key={event.type}
                      title={<code className="font-mono">{event.type}</code>}
                      description={event.description || event.label}
                      meta={event.category ? <SharedStatusBadge label={event.category} variant="info" /> : undefined}
                    />
                  ))}
                </div>
              </Section>
            )}

            {hasAssets && (
              <Section title="Detected Assets" description="Live registered assets and manifest-discovered files.">
                <div className="flex flex-col gap-4">
                  <AssetList title={`Tools${item.tool_names?.length ? "" : " - files on disk"}`} items={liveToolNames} tone={item.tool_names?.length ? "info" : "neutral"} />
                  <AssetList title="Skills" items={item.skill_files} tone="purple" />
                  <AssetList title="Tool Widgets" items={item.tool_widget_names} tone="purple" />
                </div>
              </Section>
            )}

            {item.machine_control && (
              <Section title="Machine Setup" description="Provider-wide status for this machine-control integration.">
                <MachineControlSetupSection
                  integrationId={item.id}
                  machineControl={item.machine_control}
                  enableRemoteProvisioning={Boolean(item.api_permissions)}
                />
              </Section>
            )}

            {item.readme && (
              <Section title="Documentation">
                <ReadmeSection content={item.readme} />
              </Section>
            )}

            {item.env_vars.length > 0 && (
              <Section title={`Environment Variables (${envSetCount}/${item.env_vars.length} set)`}>
                <DenseChipGroup
                  items={item.env_vars}
                  initialLimit={12}
                  getKey={(envVar) => envVar.key}
                  renderItem={(envVar) => <EnvVarPill v={envVar} />}
                />
              </Section>
            )}

            {item.env_vars.length > 0 && (
              <Section title="Configuration">
                <SettingsForm integrationId={item.id} />
              </Section>
            )}

            {item.python_dependencies && item.python_dependencies.length > 0 && (
              <Section title="Python Dependencies">
                <DependencySection item={item} kind="python" />
              </Section>
            )}

            {item.npm_dependencies && item.npm_dependencies.length > 0 && (
              <Section title="npm Dependencies">
                <DependencySection item={item} kind="npm" />
              </Section>
            )}

            {item.system_dependencies && item.system_dependencies.length > 0 && (
              <Section title="System Dependencies">
                <DependencySection item={item} kind="system" />
              </Section>
            )}

            {item.oauth && (
              <Section title="OAuth Connection">
                <OAuthSection item={item} />
              </Section>
            )}

            {item.has_process && (
              <Section title="Process">
                {item.process_launchable !== false ? (
                  <ProcessControls integrationId={item.id} />
                ) : (
                  <EmptyState message={item.process_description || "Background process disabled. No command is defined."} />
                )}
              </Section>
            )}

            {item.has_process && (
              <Section title="Process Logs">
                <ProcessLogsSection integrationId={item.id} processRunning={item.process_status?.status === "running"} />
              </Section>
            )}

            {item.api_permissions && !item.machine_control && (
              <Section title="API Key">
                <ApiKeySection integrationId={item.id} />
              </Section>
            )}

            <Section title="Activity & Debug">
              <IntegrationDebugSection integrationId={item.id} debugActions={item.debug_actions} />
            </Section>
          </div>
        </div>
      </RefreshableScrollView>
    </div>
  );
}
