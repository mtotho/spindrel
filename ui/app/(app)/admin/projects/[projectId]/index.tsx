import { Link, useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, CheckCircle2, Clock3, ExternalLink, FileText, FolderGit2, FolderOpen, GitPullRequest, Hash, KeyRound, Layers, Play, Plus, RotateCw, Save, ServerCog, Terminal, Unlink, Users } from "lucide-react";
import { lazy, Suspense, useEffect, useMemo, useState } from "react";

import { useCreateProjectInstance, useManageProjectDependencyStack, useProject, useProjectChannels, useProjectCodingRunReviewBatches, useProjectCodingRuns, useProjectInstances, useProjectRunReceipts, useProjectRuntimeEnv, useProjectDependencyStack, useProjectSetup, useRunProjectSetup, useUpdateProject, useUpdateProjectSecretBindings } from "@/src/api/hooks/useProjects";
import { useCreateChannel, useChannels, usePatchChannelSettings } from "@/src/api/hooks/useChannels";
import { useAdminBots } from "@/src/api/hooks/useBots";
import { useSecretValues } from "@/src/api/hooks/useSecretValues";
import { useWorkspace } from "@/src/api/hooks/useWorkspaces";
import { ProjectRunsSection } from "./ProjectRunsSection";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { AnchorSection } from "@/src/components/shared/AnchorSection";
import { FormRow, Section, SelectInput, TabBar, TextInput } from "@/src/components/shared/FormControls";
import { PromptEditor } from "@/src/components/shared/LlmPrompt";
import { BotPicker } from "@/src/components/shared/BotPicker";
import { ChannelPicker } from "@/src/components/shared/ChannelPicker";
import {
  ActionButton,
  EmptyState,
  QuietPill,
  SaveStatusPill,
  SettingsControlRow,
  SettingsGroupLabel,
  StatusBadge,
} from "@/src/components/shared/SettingsControls";
import { Spinner } from "@/src/components/shared/Spinner";
import { WorkspaceFileBrowserSurface } from "@/src/components/workspace/WorkspaceFileBrowserSurface";
import { useHashTab } from "@/src/hooks/useHashTab";
import type { Channel, Project, ProjectCodingRun, ProjectCodingRunReviewBatch, ProjectInstance, ProjectRuntimeEnv, ProjectSetup } from "@/src/types/api";

const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

type ProjectTab = "overview" | "runs" | "channels" | "setup" | "instances" | "files" | "terminal" | "settings";

const TABS: Array<{ key: ProjectTab; label: string }> = [
  { key: "overview", label: "Overview" },
  { key: "runs", label: "Runs" },
  { key: "channels", label: "Channels" },
  { key: "setup", label: "Setup" },
  { key: "instances", label: "Instances" },
  { key: "files", label: "Files" },
  { key: "terminal", label: "Terminal" },
  { key: "settings", label: "Settings" },
];

const TAB_KEYS = TABS.map((tab) => tab.key);

function HeaderLink({ to, children, icon }: { to: string; children: React.ReactNode; icon: React.ReactNode }) {
  return (
    <Link
      to={to}
      className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted no-underline transition-colors hover:bg-surface-overlay/50 hover:text-text"
    >
      {icon}
      {children}
    </Link>
  );
}

function normalizePath(path: string): string {
  return path.replace(/^\/+|\/+$/g, "");
}

function ProjectBasicsSection({
  project,
  channels,
  setup,
  runtimeEnv,
  workspaceUri,
}: {
  project: Project;
  channels?: Array<Pick<Channel, "id" | "name" | "bot_id">>;
  setup?: ProjectSetup;
  runtimeEnv?: ProjectRuntimeEnv;
  workspaceUri: string;
}) {
  const attachedCount = channels?.length ?? project.attached_channel_count ?? 0;
  const setupReady = setup?.plan?.ready ?? false;
  const runtimeReady = runtimeEnv?.ready ?? false;
  return (
    <Section
      title="Basics"
      description="The minimum contract every Project-bound channel and agent run depends on."
    >
      <div data-testid="project-workspace-basics" className="grid gap-2 md:grid-cols-2">
        <SettingsControlRow
          leading={<FolderOpen size={14} />}
          title="Work surface"
          description={<span className="font-mono">{workspaceUri}</span>}
          meta={<StatusBadge label="Project root" variant="info" />}
        />
        <SettingsControlRow
          leading={<Users size={14} />}
          title="Attached channels"
          description={`${attachedCount} channel${attachedCount === 1 ? "" : "s"} use this root for files, search, exec, and harness cwd.`}
          meta={<StatusBadge label={attachedCount > 0 ? "Ready" : "None"} variant={attachedCount > 0 ? "success" : "warning"} />}
        />
        <SettingsControlRow
          leading={setupReady ? <CheckCircle2 size={14} /> : <Clock3 size={14} />}
          title="Setup"
          description={setupReady ? "Blueprint setup can run for this Project." : setup?.plan?.reasons?.[0] ?? "No setup plan is ready."}
          meta={<StatusBadge label={setupReady ? "Ready" : "Needs setup"} variant={setupReady ? "success" : "warning"} />}
        />
        <SettingsControlRow
          leading={runtimeReady ? <KeyRound size={14} /> : <AlertTriangle size={14} />}
          title="Runtime env"
          description={runtimeReady ? "Runtime keys are ready for Project terminals, exec, and harness turns." : runtimeEnv?.missing_secrets?.join(", ") || "Runtime env is not ready."}
          meta={<StatusBadge label={runtimeReady ? "Ready" : "Needs binding"} variant={runtimeReady ? "success" : "warning"} />}
        />
      </div>
    </Section>
  );
}

function countRunsByStatus(runs: ProjectCodingRun[]) {
  return runs.reduce(
    (acc, run) => {
      const status = run.review?.status || run.status;
      if (status === "ready_for_review" || status === "needs_review" || run.review?.actions?.can_mark_reviewed) acc.ready += 1;
      else if (status === "running" || status === "pending") acc.active += 1;
      else if (status === "blocked" || status === "failed" || status === "changes_requested") acc.blocked += 1;
      else if (run.review?.reviewed) acc.reviewed += 1;
      return acc;
    },
    { active: 0, ready: 0, blocked: 0, reviewed: 0 },
  );
}

function newestActivityLabel(values: Array<{ created_at?: string | null; updated_at?: string | null }>) {
  const dates = values
    .map((value) => value.updated_at || value.created_at)
    .filter((value): value is string => Boolean(value));
  if (dates.length === 0) return "No activity yet";
  const sorted = dates.sort();
  const newest = sorted[sorted.length - 1];
  if (!newest) return "No activity yet";
  return `Updated ${new Date(newest).toLocaleDateString(undefined, { month: "short", day: "numeric" })}`;
}

function ProjectOverviewSection({
  project,
  channels,
  setup,
  runtimeEnv,
  instances,
  workspaceUri,
  filesHref,
  setTab,
}: {
  project: Project;
  channels?: Array<Pick<Channel, "id" | "name" | "bot_id">>;
  setup?: ProjectSetup;
  runtimeEnv?: ProjectRuntimeEnv;
  instances?: ProjectInstance[];
  workspaceUri: string;
  filesHref: string;
  setTab: (tab: ProjectTab) => void;
}) {
  const { data: runs = [] } = useProjectCodingRuns(project.id);
  const { data: reviewBatches = [] } = useProjectCodingRunReviewBatches(project.id);
  const runCounts = countRunsByStatus(runs);
  const readyBatches = reviewBatches.filter(
    (batch) => (batch.actions?.can_start_review || batch.actions?.can_mark_reviewed) && (batch.unreviewed_run_ids?.length ?? batch.ready_run_ids?.length ?? batch.run_count) > 0,
  );
  const setupReady = setup?.plan?.ready ?? false;
  const runtimeReady = runtimeEnv?.ready ?? false;
  const attachedCount = channels?.length ?? project.attached_channel_count ?? 0;
  const activeInstances = (instances ?? []).filter((instance) => !["deleted", "expired"].includes(instance.status));
  const dependencyConfigured = Boolean(project.metadata_?.blueprint_snapshot?.dependency_stack);
  const latestRuns = runs.slice(0, 4);

  return (
    <div data-testid="project-overview-home" className="mx-auto flex w-full max-w-[1600px] flex-col gap-4 px-4 py-4 sm:px-6 lg:px-8">
      <AnchorSection
        icon={<FolderGit2 size={15} />}
        eyebrow="Project pulse"
        title="Ready for agent work"
        meta={newestActivityLabel(runs)}
        emphasis="primary"
        action={<ActionButton label="Start run" icon={<Play size={14} />} size="small" onPress={() => setTab("runs")} />}
      >
        <div className="grid gap-2 md:grid-cols-2 xl:grid-cols-4">
          <SettingsControlRow
            compact
            leading={<GitPullRequest size={14} />}
            title="Review queue"
            description={`${runCounts.ready} ready, ${runCounts.active} active, ${runCounts.blocked} blocked`}
            meta={<StatusBadge label={runCounts.ready > 0 ? "Review" : runCounts.active > 0 ? "Active" : "Clear"} variant={runCounts.blocked > 0 ? "warning" : runCounts.ready > 0 ? "info" : "success"} />}
            onClick={() => setTab("runs")}
          />
          <SettingsControlRow
            compact
            leading={<Users size={14} />}
            title="Attached channels"
            description={`${attachedCount} channel${attachedCount === 1 ? "" : "s"} can work from this Project root`}
            meta={<StatusBadge label={attachedCount > 0 ? "Ready" : "None"} variant={attachedCount > 0 ? "success" : "warning"} />}
            onClick={() => setTab("channels")}
          />
          <SettingsControlRow
            compact
            leading={runtimeReady ? <KeyRound size={14} /> : <AlertTriangle size={14} />}
            title="Runtime env"
            description={runtimeReady ? "Secrets and defaults are available to Project runs" : runtimeEnv?.missing_secrets?.join(", ") || "Runtime bindings need attention"}
            meta={<StatusBadge label={runtimeReady ? "Ready" : "Needs binding"} variant={runtimeReady ? "success" : "warning"} />}
            onClick={() => setTab("settings")}
          />
          <SettingsControlRow
            compact
            leading={setupReady ? <CheckCircle2 size={14} /> : <Clock3 size={14} />}
            title="Setup"
            description={setupReady ? "Blueprint setup can run for this Project" : setup?.plan?.reasons?.[0] ?? "No setup plan is ready"}
            meta={<StatusBadge label={setupReady ? "Ready" : "Needs setup"} variant={setupReady ? "success" : "warning"} />}
            onClick={() => setTab("setup")}
          />
        </div>
      </AnchorSection>

      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <div className="flex min-w-0 flex-col gap-4">
          <AnchorSection
            icon={<GitPullRequest size={15} />}
            eyebrow="Agent work"
            title="Recent runs"
            meta={`${runs.length} total`}
            action={<ActionButton label="Open runs" icon={<ExternalLink size={14} />} size="small" variant="secondary" onPress={() => setTab("runs")} />}
          >
            <div className="flex flex-col gap-2">
              {latestRuns.length === 0 ? (
                <EmptyState message="No Project coding runs yet." />
              ) : latestRuns.map((run) => (
                <SettingsControlRow
                  key={run.id}
                  leading={<GitPullRequest size={14} />}
                  title={run.task.title || run.request || "Project run"}
                  description={run.review?.blocker || run.review?.review_summary || run.request || "No run summary yet"}
                  meta={
                    <span className="inline-flex min-w-0 flex-wrap items-center gap-1.5">
                      <StatusBadge label={run.review?.status || run.status} variant={run.review?.blocker || run.status === "failed" ? "danger" : run.review?.actions?.can_mark_reviewed ? "info" : run.status === "running" ? "warning" : "neutral"} />
                      {run.receipt?.screenshots?.length ? <QuietPill label={`${run.receipt.screenshots.length} screenshots`} /> : null}
                    </span>
                  }
                  onClick={() => setTab("runs")}
                />
              ))}
            </div>
          </AnchorSection>

          <AnchorSection
            icon={<Users size={15} />}
            title="Project channels"
            meta={`${attachedCount} attached`}
            action={<ActionButton label="Manage" icon={<ExternalLink size={14} />} size="small" variant="secondary" onPress={() => setTab("channels")} />}
          >
            <div className="grid gap-2 md:grid-cols-2">
              {(channels ?? []).length === 0 ? (
                <EmptyState message="No channels are attached to this Project yet." />
              ) : (channels ?? []).slice(0, 4).map((channel) => (
                <SettingsControlRow
                  key={channel.id}
                  compact
                  leading={<Hash size={14} />}
                  title={channel.name}
                  description={channel.bot_id}
                  action={<HeaderLink to={`/channels/${channel.id}`} icon={<ExternalLink size={13} />}>Open</HeaderLink>}
                />
              ))}
            </div>
          </AnchorSection>
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          <AnchorSection icon={<FolderOpen size={15} />} title="Work surface" emphasis="secondary">
            <div className="flex flex-col gap-2">
              <SettingsControlRow
                compact
                leading={<FolderOpen size={14} />}
                title="Project root"
                description={<span className="font-mono">{workspaceUri}</span>}
                meta={<QuietPill label={project.slug} />}
              />
              <div className="flex flex-wrap gap-1">
                <HeaderLink to={filesHref} icon={<ExternalLink size={13} />}>Files</HeaderLink>
                <button
                  type="button"
                  className="inline-flex min-h-[34px] items-center gap-1.5 rounded-md px-2.5 text-[12px] font-semibold text-text-muted transition-colors hover:bg-surface-overlay/50 hover:text-text"
                  onClick={() => setTab("terminal")}
                >
                  <Terminal size={13} />
                  Terminal
                </button>
              </div>
            </div>
          </AnchorSection>

          <AnchorSection icon={<ServerCog size={15} />} title="Runtime and instances" emphasis="secondary">
            <div className="flex flex-col gap-2">
              <SettingsControlRow
                compact
                leading={<ServerCog size={14} />}
                title="Dependency stack"
                description={dependencyConfigured ? "Docker-backed dependencies are declared for Project work" : "No dependency stack declared"}
                meta={<StatusBadge label={dependencyConfigured ? "Configured" : "None"} variant={dependencyConfigured ? "info" : "neutral"} />}
                onClick={() => setTab("settings")}
              />
              <SettingsControlRow
                compact
                leading={<FolderOpen size={14} />}
                title="Fresh instances"
                description={`${activeInstances.length} active instance${activeInstances.length === 1 ? "" : "s"}`}
                meta={<QuietPill label={`${instances?.length ?? 0} total`} />}
                onClick={() => setTab("instances")}
              />
              <SettingsControlRow
                compact
                leading={<GitPullRequest size={14} />}
                title="Review batches"
                description={`${readyBatches.length} batch${readyBatches.length === 1 ? "" : "es"} waiting for review action`}
                meta={<StatusBadge label={readyBatches.length > 0 ? "Ready" : "Clear"} variant={readyBatches.length > 0 ? "info" : "success"} />}
                onClick={() => setTab("runs")}
              />
            </div>
          </AnchorSection>
        </div>
      </div>
    </div>
  );
}

function ProjectBlueprintSection({ project }: { project: Project }) {
  const { data: secrets = [] } = useSecretValues();
  const updateBindings = useUpdateProjectSecretBindings(project.id);
  const [bindingsDraft, setBindingsDraft] = useState<Record<string, string>>({});

  const bindings = project.secret_bindings ?? [];
  const snapshot = project.metadata_?.blueprint_snapshot ?? {};
  const materialization = project.metadata_?.blueprint_materialization ?? {};
  const envDefaults = snapshot && typeof snapshot.env === "object" && !Array.isArray(snapshot.env) ? snapshot.env : {};
  const repos = Array.isArray(snapshot?.repos) ? snapshot.repos : [];
  const requiredSecrets = Array.isArray(snapshot?.required_secrets)
    ? snapshot.required_secrets.filter((name: unknown): name is string => typeof name === "string" && name.trim().length > 0)
    : bindings.map((binding) => binding.logical_name);
  const bindingNames = Array.from(new Set([...requiredSecrets, ...bindings.map((binding) => binding.logical_name)]));
  const currentBindings = useMemo(
    () => Object.fromEntries(bindings.map((binding) => [binding.logical_name, binding.secret_value_id ?? ""])),
    [bindings],
  );
  const secretOptions = useMemo(
    () => [
      { label: "Unbound", value: "" },
      ...secrets.map((secret) => ({
        label: secret.name,
        value: secret.id,
      })),
    ],
    [secrets],
  );

  useEffect(() => {
    setBindingsDraft(currentBindings);
  }, [currentBindings]);

  const dirty = JSON.stringify(bindingsDraft) !== JSON.stringify(currentBindings);
  const saveBindings = () => {
    const payload = Object.fromEntries(
      Object.entries(bindingsDraft).map(([name, secretId]) => [name, secretId || null]),
    );
    updateBindings.mutate(payload);
  };

  return (
    <Section
      title="Blueprint"
      description="The recipe used to create this Project and the declarations still attached to it."
      action={
        bindingNames.length > 0 ? (
          <ActionButton
            label="Save Bindings"
            icon={<Save size={14} />}
            disabled={!dirty || updateBindings.isPending}
            onPress={saveBindings}
          />
        ) : undefined
      }
    >
      <div data-testid="project-blueprint-section" className="flex flex-col gap-3">
        <SettingsControlRow
          leading={<Layers size={14} />}
          title={project.blueprint?.name ?? "No blueprint applied"}
          description={project.blueprint ? project.blueprint.description || project.blueprint.slug : "This Project was created directly."}
          meta={project.blueprint ? <QuietPill label={project.blueprint.slug} /> : <QuietPill label="direct" />}
        />

        {project.blueprint && (
          <div className="grid gap-2 md:grid-cols-3">
            <SettingsControlRow
              leading={<FolderOpen size={14} />}
              title="Materialized"
              description={`${(materialization.files_written ?? []).length} files, ${(materialization.folders_created ?? []).length} folders`}
              meta={<QuietPill label={`${(materialization.files_skipped ?? []).length} skipped`} />}
            />
            <SettingsControlRow
              leading={<FileText size={14} />}
              title="Repo declarations"
              description={repos.length > 0 ? repos.map((repo: Record<string, unknown>) => String(repo.name || repo.url || "repo")).join(", ") : "No repos declared"}
              meta={<QuietPill label={`${repos.length}`} />}
            />
            <SettingsControlRow
              leading={<Hash size={14} />}
              title="Env defaults"
              description={Object.keys(envDefaults).length > 0 ? Object.keys(envDefaults).join(", ") : "No env defaults declared"}
              meta={<QuietPill label={`${Object.keys(envDefaults).length}`} />}
            />
          </div>
        )}

        {bindingNames.length > 0 && (
          <div className="flex flex-col gap-2">
            <SettingsGroupLabel
              label="Secret bindings"
              count={bindingNames.length}
              icon={<KeyRound size={13} className="text-text-dim" />}
            />
            <div className="grid gap-2 md:grid-cols-2">
              {bindingNames.map((name) => {
                const binding = bindings.find((item) => item.logical_name === name);
                return (
                  <SettingsControlRow
                    key={name}
                    leading={<KeyRound size={14} />}
                    title={name}
                    description={binding?.secret_value_name ?? "No secret bound"}
                    meta={<QuietPill label={binding?.bound ? "bound" : "missing"} tone={binding?.bound ? "success" : "warning"} />}
                    action={
                      <div className="w-[220px]">
                        <SelectInput
                          value={bindingsDraft[name] ?? ""}
                          onChange={(value) => setBindingsDraft((current) => ({ ...current, [name]: value }))}
                          options={secretOptions}
                        />
                      </div>
                    }
                  />
                );
              })}
            </div>
          </div>
        )}
      </div>
    </Section>
  );
}

function ProjectRuntimeSection({ runtimeEnv }: { runtimeEnv?: ProjectRuntimeEnv }) {
  const envKeys = runtimeEnv?.env_default_keys ?? [];
  const secretKeys = runtimeEnv?.secret_keys ?? [];
  const missingSecrets = runtimeEnv?.missing_secrets ?? [];
  const invalidKeys = [...(runtimeEnv?.invalid_env_keys ?? []), ...(runtimeEnv?.reserved_env_keys ?? [])];
  const hasWarnings = missingSecrets.length > 0 || invalidKeys.length > 0;
  const statusLabel = !runtimeEnv ? "loading" : hasWarnings ? "warning" : "ready";
  const statusVariant = !runtimeEnv ? "neutral" : hasWarnings ? "warning" : "success";
  const statusIcon = !runtimeEnv ? <Clock3 size={14} /> : hasWarnings ? <AlertTriangle size={14} /> : <CheckCircle2 size={14} />;
  const title = !runtimeEnv
    ? "Runtime env loading"
    : hasWarnings
      ? "Runtime env needs bindings"
      : envKeys.length > 0 || secretKeys.length > 0
        ? "Runtime env available"
        : "No runtime env declared";

  return (
    <Section
      title="Runtime Environment"
      description="Project Blueprint env defaults and bound secrets are injected into Project terminals, exec tools, and harness turns."
    >
      <div data-testid="project-runtime-env-readiness" className="flex flex-col gap-3">
        <SettingsControlRow
          leading={statusIcon}
          title={title}
          description={
            !runtimeEnv
              ? "Runtime keys will appear here once the Project snapshot and secret bindings load."
              : hasWarnings
              ? "Missing secret bindings warn here; general Project runtimes still start with available values."
              : "Values are process-only and are not rendered in Project settings, prompt context, or setup logs."
          }
          meta={<StatusBadge label={statusLabel} variant={statusVariant} />}
        />
        <div className="grid gap-2 md:grid-cols-2">
          <SettingsControlRow
            leading={<Hash size={14} />}
            title="Env defaults"
            description={envKeys.length > 0 ? envKeys.join(", ") : "No default keys declared"}
            meta={<QuietPill label={`${envKeys.length}`} />}
          />
          <SettingsControlRow
            leading={<KeyRound size={14} />}
            title="Bound secrets"
            description={secretKeys.length > 0 ? secretKeys.join(", ") : "No bound secret keys available"}
            meta={<QuietPill label={`${secretKeys.length}`} tone={secretKeys.length > 0 ? "success" : "neutral"} />}
          />
        </div>
        {missingSecrets.length > 0 && (
          <SettingsControlRow
            leading={<AlertTriangle size={14} />}
            title="Missing required secrets"
            description={missingSecrets.join(", ")}
            meta={<StatusBadge label="warning" variant="warning" />}
          />
        )}
        {invalidKeys.length > 0 && (
          <SettingsControlRow
            leading={<AlertTriangle size={14} />}
            title="Skipped env keys"
            description={invalidKeys.join(", ")}
            meta={<StatusBadge label="skipped" variant="warning" />}
          />
        )}
      </div>
    </Section>
  );
}

function formatRunTime(value?: string | null) {
  if (!value) return "pending";
  return new Date(value).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function setupTone(status: string): "success" | "warning" | "danger" | "neutral" {
  if (status === "succeeded" || status === "ready" || status === "cloned" || status === "already_present") return "success";
  if (status === "failed" || status === "invalid") return "danger";
  if (status === "running" || status === "skipped") return "warning";
  return "neutral";
}

function DependencyStackSection({ project }: { project: Project }) {
  const { data: dependencyStack } = useProjectDependencyStack(project.id);
  const manageStack = useManageProjectDependencyStack(project.id);
  const configured = dependencyStack?.configured ?? false;
  const spec = dependencyStack?.spec ?? {};
  const instance = dependencyStack?.instance ?? null;
  const status = instance?.status ?? (configured ? "not prepared" : "not configured");
  const commandNames = Object.keys(spec.commands ?? instance?.commands ?? {});
  const envKeys = Object.keys(instance?.env ?? spec.env ?? {});
  const busy = manageStack.isPending;
  const runAction = (action: string) => manageStack.mutate({ action });

  return (
    <Section
      title="Dependency Stack"
      description="Docker-backed databases and services for Project work. Agents start app servers themselves with native bash."
      action={
        configured ? (
          <div className="flex flex-wrap justify-end gap-1">
            <ActionButton
              label={instance ? "Reload" : "Prepare"}
              icon={<RotateCw size={14} />}
              size="small"
              disabled={busy}
              onPress={() => runAction(instance ? "reload" : "prepare")}
            />
            <ActionButton
              label="Health"
              size="small"
              variant="secondary"
              disabled={busy || !instance}
              onPress={() => runAction("health")}
            />
          </div>
        ) : undefined
      }
    >
      <div data-testid="project-dependency-stack" className="flex flex-col gap-2">
        <SettingsControlRow
          leading={<ServerCog size={14} />}
          title={configured ? `Stack ${status}` : "No dependency stack declared"}
          description={
            configured
              ? (
                <span className="flex min-w-0 flex-col gap-0.5">
                  <span className="truncate font-mono text-[11px] text-text-dim">{spec.source_path || instance?.source_path || "inline compose spec"}</span>
                  <span>Agents use the provided env and launch their own dev server on an unused or assigned port.</span>
                  {envKeys.length > 0 && <span className="truncate text-[11px] text-text-dim">Env: {envKeys.join(", ")}</span>}
                  {commandNames.length > 0 && <span className="truncate text-[11px] text-text-dim">Commands: {commandNames.join(", ")}</span>}
                  {instance?.error_message && <span className="truncate text-[11px] text-danger">{instance.error_message}</span>}
                </span>
              )
              : "Declare dependency_stack on the Project Blueprint to let Spindrel prepare Docker-backed dependencies."
          }
          meta={<StatusBadge label={status} variant={status === "running" ? "success" : configured ? "warning" : "neutral"} />}
          action={
            instance ? (
              <div className="flex flex-wrap justify-end gap-1">
                <ActionButton label="Restart" size="small" variant="secondary" disabled={busy} onPress={() => runAction("restart")} />
                <ActionButton label="Logs" size="small" variant="ghost" disabled={busy} onPress={() => manageStack.mutate({ action: "logs", tail: 80 })} />
              </div>
            ) : undefined
          }
        />
        {manageStack.data?.logs && (
          <pre className="max-h-52 overflow-auto rounded-md bg-surface-raised/40 p-3 text-[11px] leading-5 text-text-muted">
            {String(manageStack.data.logs)}
          </pre>
        )}
        {manageStack.data?.body && (
          <pre className="max-h-32 overflow-auto rounded-md bg-surface-raised/40 p-3 text-[11px] leading-5 text-text-muted">
            {String(manageStack.data.body)}
          </pre>
        )}
        {manageStack.error && (
          <SettingsControlRow
            leading={<AlertTriangle size={14} />}
            title="Dependency stack action failed"
            description={manageStack.error instanceof Error ? manageStack.error.message : "The dependency stack request failed."}
            meta={<StatusBadge label="failed" variant="danger" />}
          />
        )}
      </div>
    </Section>
  );
}

function ProjectSetupSection({ project, setup }: { project: Project; setup?: ProjectSetup }) {
  const { data: secrets = [] } = useSecretValues();
  const updateBindings = useUpdateProjectSecretBindings(project.id);
  const runSetup = useRunProjectSetup(project.id);
  const [bindingsDraft, setBindingsDraft] = useState<Record<string, string>>({});

  const plan = setup?.plan;
  const repos = Array.isArray(plan?.repos) ? plan.repos : [];
  const commands = Array.isArray(plan?.commands) ? plan.commands : [];
  const secretSlots = Array.isArray(plan?.secret_slots) ? plan.secret_slots : [];
  const runs = setup?.runs ?? [];
  const latestRun = runs[0];
  const currentBindings = useMemo(
    () => Object.fromEntries((project.secret_bindings ?? []).map((binding) => [binding.logical_name, binding.secret_value_id ?? ""])),
    [project.secret_bindings],
  );
  const secretOptions = useMemo(
    () => [
      { label: "Unbound", value: "" },
      ...secrets.map((secret) => ({
        label: secret.name,
        value: secret.id,
      })),
    ],
    [secrets],
  );

  useEffect(() => {
    setBindingsDraft(currentBindings);
  }, [currentBindings]);

  const bindingsDirty = JSON.stringify(bindingsDraft) !== JSON.stringify(currentBindings);
  const missingSecrets = plan?.missing_secrets ?? [];
  const invalidRepos = repos.filter((repo) => repo.status === "invalid");
  const invalidCommands = commands.filter((command) => command.status === "invalid");
  const readyLabel = plan?.ready
    ? commands.length > 0 ? "Ready to run setup" : "Ready to clone"
    : repos.length === 0 && commands.length === 0
      ? "No setup work declared"
      : missingSecrets.length > 0
        ? "Missing secrets"
        : "Needs review";
  const readyTone = plan?.ready ? "success" : (repos.length === 0 && commands.length === 0) || invalidRepos.length > 0 || invalidCommands.length > 0 ? "danger" : "warning";

  const saveBindings = () => {
    const payload = Object.fromEntries(
      Object.entries(bindingsDraft).map(([name, secretId]) => [name, secretId || null]),
    );
    updateBindings.mutate(payload);
  };

  return (
    <div data-testid="project-workspace-setup" className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
      <Section
        title="Setup"
        description="Clone repos and run setup commands declared by this Project's applied Blueprint snapshot."
        action={
          <ActionButton
            label={runSetup.isPending ? "Running" : "Run Setup"}
            icon={<Play size={14} />}
            disabled={!plan?.ready || runSetup.isPending}
            onPress={() => runSetup.mutate()}
          />
        }
      >
        <div data-testid="project-workspace-setup-ready" className="flex flex-col gap-3">
          <SettingsControlRow
            leading={plan?.ready ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}
            title={readyLabel}
            description={
              plan?.ready
                ? "Setup can prepare this Project root with declared repos and commands."
                : missingSecrets.length > 0
                  ? missingSecrets.join(", ")
                  : invalidRepos.length > 0
                    ? "One or more repo declarations need a safe path or supported URL."
                    : invalidCommands.length > 0
                      ? "One or more setup commands need a command, safe cwd, or valid timeout."
                      : "Add repo declarations or setup commands to the Blueprint before running setup."
            }
            meta={<StatusBadge label={readyLabel} variant={readyTone} />}
          />
          {runSetup.error && (
            <SettingsControlRow
              leading={<AlertTriangle size={14} />}
              title="Setup did not start"
              description={runSetup.error instanceof Error ? runSetup.error.message : "The setup request failed."}
              meta={<StatusBadge label="failed" variant="danger" />}
            />
          )}
        </div>
      </Section>

      <DependencyStackSection project={project} />

      <Section title="Command Plan" description="Commands run in order after repository setup. Cwd values are Project-relative.">
        <div className="flex flex-col gap-2">
          <SettingsGroupLabel label="Commands" count={commands.length} icon={<Terminal size={13} className="text-text-dim" />} />
          {commands.length === 0 ? (
            <EmptyState message="This Project snapshot does not declare setup commands yet." />
          ) : (
            commands.map((command, index) => (
              <SettingsControlRow
                key={`${command.name ?? index}-command`}
                leading={<Terminal size={14} />}
                title={String(command.name || `Command ${index + 1}`)}
                description={
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate font-mono text-xs">{String(command.command || "missing command")}</span>
                    <span className="truncate font-mono text-[11px] text-text-dim">/{project.root_path}{command.cwd ? `/${String(command.cwd)}` : ""} · {String(command.timeout_seconds || 600)}s</span>
                    {Array.isArray(command.errors) && command.errors.length > 0 && (
                      <span className="text-xs text-danger-muted">{command.errors.join(", ")}</span>
                    )}
                  </span>
                }
                meta={<StatusBadge label={String(command.status || "pending")} variant={setupTone(String(command.status || "pending"))} />}
              />
            ))
          )}
        </div>
      </Section>

      <Section title="Repo Plan" description="Targets are Project-relative. Existing paths are reported and left untouched.">
        <div className="flex flex-col gap-2">
          <SettingsGroupLabel label="Repos" count={repos.length} icon={<FolderGit2 size={13} className="text-text-dim" />} />
          {repos.length === 0 ? (
            <EmptyState message="This Project snapshot does not declare any repos yet." />
          ) : (
            repos.map((repo, index) => (
              <SettingsControlRow
                key={`${repo.path ?? repo.name}-${index}`}
                leading={<FolderGit2 size={14} />}
                title={String(repo.name || repo.path || "repo")}
                description={
                  <span className="flex min-w-0 flex-col gap-0.5">
                    <span className="truncate font-mono text-xs">{String(repo.url || "missing url")}</span>
                    <span className="truncate font-mono text-[11px] text-text-dim">/{project.root_path}/{String(repo.path || "")}</span>
                    {Array.isArray(repo.errors) && repo.errors.length > 0 && (
                      <span className="text-xs text-danger-muted">{repo.errors.join(", ")}</span>
                    )}
                  </span>
                }
                meta={<StatusBadge label={String(repo.status || "pending")} variant={setupTone(String(repo.status || "pending"))} />}
              />
            ))
          )}
        </div>
      </Section>

      {secretSlots.length > 0 && (
        <Section
          title="Secret Slots"
          description="Bindings are scoped to this Project and backed by the encrypted secret vault."
          action={
            <ActionButton
              label="Save Bindings"
              icon={<Save size={14} />}
              disabled={!bindingsDirty || updateBindings.isPending}
              onPress={saveBindings}
            />
          }
        >
          <div className="grid gap-2 md:grid-cols-2">
            {secretSlots.map((slot) => (
              <SettingsControlRow
                key={String(slot.logical_name)}
                leading={<KeyRound size={14} />}
                title={String(slot.logical_name)}
                description={String(slot.secret_value_name || "No secret bound")}
                meta={<StatusBadge label={slot.bound ? "bound" : "missing"} variant={slot.bound ? "success" : "warning"} />}
                action={
                  <div className="w-[220px]">
                    <SelectInput
                      value={bindingsDraft[String(slot.logical_name)] ?? ""}
                      onChange={(value) => setBindingsDraft((current) => ({ ...current, [String(slot.logical_name)]: value }))}
                      options={secretOptions}
                    />
                  </div>
                }
              />
            ))}
          </div>
        </Section>
      )}

      <Section title="Run History" description="Logs are redacted before they are stored or returned.">
        <div data-testid="project-workspace-setup-run-history" className="flex flex-col gap-2">
          {!latestRun ? (
            <EmptyState message="Setup has not run for this Project." />
          ) : (
            <>
              <SettingsControlRow
                leading={<Clock3 size={14} />}
                title={`Latest run ${latestRun.status}`}
                description={formatRunTime(latestRun.completed_at ?? latestRun.started_at)}
                meta={<StatusBadge label={latestRun.status} variant={setupTone(latestRun.status)} />}
              />
              {(latestRun.result?.repos ?? []).map((repo: Record<string, any>, index: number) => (
                <SettingsControlRow
                  key={`${repo.path ?? index}-result`}
                  leading={<FolderGit2 size={14} />}
                  title={String(repo.path || repo.name || "repo")}
                  description={String(repo.message || "No output recorded.")}
                  meta={<StatusBadge label={String(repo.status || "unknown")} variant={setupTone(String(repo.status || "unknown"))} />}
                />
              ))}
              {(latestRun.result?.commands ?? []).map((command: Record<string, any>, index: number) => (
                <SettingsControlRow
                  key={`${command.name ?? index}-command-result`}
                  leading={<Terminal size={14} />}
                  title={String(command.name || `Command ${index + 1}`)}
                  description={String(command.message || "No output recorded.")}
                  meta={<StatusBadge label={String(command.status || "unknown")} variant={setupTone(String(command.status || "unknown"))} />}
                />
              ))}
              {(latestRun.logs ?? []).length > 0 && (
                <pre className="max-h-[220px] overflow-auto rounded-md bg-surface-raised/45 px-3 py-2 font-mono text-[11px] leading-5 text-text-muted">
                  {(latestRun.logs ?? []).join("\n")}
                </pre>
              )}
            </>
          )}
        </div>
      </Section>
    </div>
  );
}

function ProjectChannelsSection({
  project,
  channels,
}: {
  project: Project;
  channels?: Pick<Channel, "id" | "name" | "bot_id">[];
}) {
  const navigate = useNavigate();
  const { data: allChannels = [] } = useChannels();
  const { data: bots = [] } = useAdminBots();
  const createChannel = useCreateChannel();
  const patchChannel = usePatchChannelSettings();
  const [newChannelName, setNewChannelName] = useState("");
  const [newChannelBotId, setNewChannelBotId] = useState("");
  const [selectedChannelId, setSelectedChannelId] = useState("");

  useEffect(() => {
    if (!newChannelBotId && bots.length > 0) {
      setNewChannelBotId(bots[0].id);
    }
  }, [bots, newChannelBotId]);

  const attachedIds = useMemo(() => new Set((channels ?? []).map((channel) => channel.id)), [channels]);
  const attachableChannels = useMemo(
    () => allChannels.filter((channel) => !attachedIds.has(channel.id)),
    [allChannels, attachedIds],
  );

  const attachSelected = () => {
    if (!selectedChannelId || patchChannel.isPending) return;
    patchChannel.mutate({
      channelId: selectedChannelId,
      settings: { project_id: project.id },
    }, {
      onSuccess: () => setSelectedChannelId(""),
    });
  };

  const detachChannel = (channelId: string) => {
    patchChannel.mutate({
      channelId,
      settings: { project_id: null },
    });
  };

  const createProjectChannel = () => {
    const botId = newChannelBotId || bots[0]?.id;
    if (!botId || createChannel.isPending) return;
    createChannel.mutate({
      name: newChannelName.trim() || `${project.name} channel`,
      bot_id: botId,
      project_id: project.id,
    }, {
      onSuccess: (channel) => {
        setNewChannelName("");
        navigate(`/channels/${channel.id}`);
      },
    });
  };

  return (
    <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
      <Section
        title="Project Channels"
        description="Channels attached here use this Project as their working surface."
        action={
          <ActionButton
            label="Create Channel"
            icon={<Plus size={14} />}
            disabled={!newChannelBotId || createChannel.isPending}
            onPress={createProjectChannel}
          />
        }
      >
        <div data-testid="project-workspace-channel-create" className="grid gap-3 rounded-md bg-surface-raised/35 px-3 py-3 md:grid-cols-[minmax(0,1.2fr)_minmax(220px,0.8fr)]">
          <FormRow label="Channel name">
            <TextInput
              value={newChannelName}
              onChangeText={setNewChannelName}
              placeholder={`${project.name} channel`}
            />
          </FormRow>
          <FormRow label="Primary bot">
            <BotPicker
              value={newChannelBotId}
              onChange={setNewChannelBotId}
              bots={bots}
              placeholder="Select bot..."
              disabled={bots.length === 0}
            />
          </FormRow>
        </div>
      </Section>

      <Section
        title="Attached Channels"
        description="Open, inspect, or remove channels from this Project."
      >
        <div data-testid="project-workspace-attached-channels" className="flex flex-col gap-2">
          <SettingsGroupLabel
            label="Attached"
            count={channels?.length ?? 0}
            icon={<Users size={13} className="text-text-dim" />}
          />
          {(!channels || channels.length === 0) ? (
            <EmptyState message="No channels are attached to this Project." />
          ) : (
            channels.map((channel) => (
              <SettingsControlRow
                key={channel.id}
                leading={<Hash size={14} />}
                title={channel.name}
                description={channel.bot_id}
                meta={<QuietPill label="project" />}
                action={
                  <div className="flex flex-wrap items-center justify-end gap-1">
                    <HeaderLink to={`/channels/${channel.id}`} icon={<ExternalLink size={13} />}>Open</HeaderLink>
                    <HeaderLink to={`/channels/${channel.id}/settings#agent`} icon={<Users size={13} />}>Settings</HeaderLink>
                    <ActionButton
                      label="Detach"
                      icon={<Unlink size={13} />}
                      size="small"
                      variant="secondary"
                      disabled={patchChannel.isPending}
                      onPress={() => detachChannel(channel.id)}
                    />
                  </div>
                }
              />
            ))
          )}
        </div>
      </Section>

      <Section
        title="Attach Existing Channel"
        description="Move an existing channel onto this Project workspace."
      >
        <div data-testid="project-workspace-channel-attach" className="grid gap-3 rounded-md bg-surface-raised/35 px-3 py-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <FormRow label="Channel">
            <ChannelPicker
              value={selectedChannelId}
              onChange={setSelectedChannelId}
              channels={attachableChannels}
              bots={bots}
              placeholder="Select channel..."
              disabled={attachableChannels.length === 0}
            />
          </FormRow>
          <ActionButton
            label="Attach"
            icon={<Plus size={14} />}
            disabled={!selectedChannelId || patchChannel.isPending}
            onPress={attachSelected}
          />
        </div>
        {attachableChannels.length === 0 && (
          <div className="mt-2">
            <EmptyState message="Every visible channel is already attached to this Project." />
          </div>
        )}
      </Section>
    </div>
  );
}

function ProjectInstancesSection({
  project,
  instances,
}: {
  project: Project;
  instances?: ProjectInstance[];
}) {
  const createInstance = useCreateProjectInstance(project.id);
  const latest = instances?.[0];
  const readyCount = (instances ?? []).filter((instance) => instance.status === "ready").length;

  return (
    <div data-testid="project-workspace-instances" className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
      <Section
        title="Fresh Instances"
        description="Temporary Project workspaces created from this Project's frozen Blueprint snapshot."
        action={
          <ActionButton
            label={createInstance.isPending ? "Creating" : "Create Instance"}
            icon={<Plus size={14} />}
            disabled={createInstance.isPending}
            onPress={() => createInstance.mutate()}
          />
        }
      >
        <div className="grid gap-2 md:grid-cols-3">
          <SettingsControlRow
            leading={<Layers size={14} />}
            title="Instance source"
            description={project.blueprint?.name ?? "No blueprint snapshot"}
            meta={<QuietPill label={project.blueprint ? "snapshot" : "direct"} />}
          />
          <SettingsControlRow
            leading={<CheckCircle2 size={14} />}
            title="Ready instances"
            description={`${readyCount} ready out of ${(instances ?? []).length}`}
            meta={<QuietPill label={`${readyCount}`} tone={readyCount > 0 ? "success" : "neutral"} />}
          />
          <SettingsControlRow
            leading={<Clock3 size={14} />}
            title="Latest"
            description={latest ? formatRunTime(latest.created_at) : "No instance has been created"}
            meta={<StatusBadge label={latest?.status ?? "none"} variant={setupTone(latest?.status ?? "pending")} />}
          />
        </div>
        {createInstance.error && (
          <div className="mt-3">
            <SettingsControlRow
              leading={<AlertTriangle size={14} />}
              title="Instance was not created"
              description={createInstance.error instanceof Error ? createInstance.error.message : "The create request failed."}
              meta={<StatusBadge label="failed" variant="danger" />}
            />
          </div>
        )}
      </Section>

      <Section title="Instance History" description="Task runs can create these automatically when Fresh Project instance is enabled.">
        <div className="flex flex-col gap-2">
          {(!instances || instances.length === 0) ? (
            <EmptyState message="No fresh Project instances have been created yet." />
          ) : (
            instances.map((instance) => (
              <SettingsControlRow
                key={instance.id}
                leading={<FolderOpen size={14} />}
                title={`/${instance.root_path}`}
                description={`${instance.owner_kind ?? "manual"}${instance.owner_id ? ` · ${instance.owner_id}` : ""}`}
                meta={<StatusBadge label={instance.status} variant={setupTone(instance.status)} />}
                action={
                  <HeaderLink
                    to={`/admin/workspaces/${instance.workspace_id}/files?path=${encodeURIComponent(`/${instance.root_path}`)}`}
                    icon={<ExternalLink size={13} />}
                  >
                    Files
                  </HeaderLink>
                }
              />
            ))
          )}
        </div>
      </Section>
    </div>
  );
}

export default function ProjectDetail() {
  const { projectId } = useParams<{ projectId: string }>();
  const { data: project, isLoading } = useProject(projectId);
  const { data: channels } = useProjectChannels(projectId);
  const { data: setup } = useProjectSetup(projectId);
  const { data: instances } = useProjectInstances(projectId);
  const { data: receipts } = useProjectRunReceipts(projectId);
  const { data: runtimeEnv } = useProjectRuntimeEnv(projectId);
  const { data: workspace } = useWorkspace(project?.workspace_id);
  const updateProject = useUpdateProject(projectId);
  const [tab, setTab] = useHashTab<ProjectTab>("overview", TAB_KEYS);
  const [prompt, setPrompt] = useState("");
  const [promptFilePath, setPromptFilePath] = useState("");
  const [terminalPath, setTerminalPath] = useState<string | null>(null);

  useEffect(() => {
    setPrompt(project?.prompt ?? "");
    setPromptFilePath(project?.prompt_file_path ?? "");
  }, [project?.prompt, project?.prompt_file_path]);

  useEffect(() => {
    if (project?.root_path) setTerminalPath(normalizePath(project.root_path));
  }, [project?.root_path]);

  const dirty = prompt !== (project?.prompt ?? "") || promptFilePath !== (project?.prompt_file_path ?? "");
  const root = project ? normalizePath(project.root_path) : "";
  const workspaceUri = project ? `workspace://${project.workspace_id}/${root}` : "";
  const terminalCwd = project ? `workspace://${project.workspace_id}/${terminalPath || root}` : "";
  const terminalLabel = terminalPath ? `/${terminalPath}` : `/${root}`;
  const filesHref = project ? `/admin/workspaces/${project.workspace_id}/files?path=${encodeURIComponent(`/${root}`)}` : "";

  const tabItems = useMemo(() => TABS, []);

  if (isLoading || !project) {
    return <div className="flex flex-1 items-center justify-center bg-surface"><Spinner /></div>;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col bg-surface">
      <PageHeader
        variant="detail"
        chrome="flow"
        title={project.name}
        subtitle={`/${project.root_path}`}
        backTo="/admin/projects"
        right={
          <div className="flex flex-wrap items-center justify-end gap-1.5">
            <HeaderLink to={filesHref} icon={<ExternalLink size={13} />}>Files</HeaderLink>
            <HeaderLink to={`/admin/terminal?cwd=${encodeURIComponent(workspaceUri)}`} icon={<Terminal size={13} />}>Terminal</HeaderLink>
          </div>
        }
      />

      <div className="shrink-0 px-5 pt-3 md:px-6">
        <TabBar tabs={tabItems} active={tab} onChange={(value) => setTab(value as ProjectTab)} />
      </div>

      <div className="min-h-0 flex-1 overflow-hidden">
        {tab === "overview" && (
          <div className="h-full overflow-auto">
            <ProjectOverviewSection
              project={project}
              channels={channels}
              setup={setup}
              runtimeEnv={runtimeEnv}
              instances={instances}
              workspaceUri={workspaceUri}
              filesHref={filesHref}
              setTab={setTab}
            />
          </div>
        )}

        {tab === "files" && (
          <div data-testid="project-workspace-files" className="flex h-full min-h-0 flex-col">
            {!workspace ? (
              <div className="flex flex-1 items-center justify-center"><Spinner /></div>
            ) : (
              <WorkspaceFileBrowserSurface
                workspace={workspace}
                rootPath={root}
                rootLabel="Project"
                title={project.name}
                settingsHref={`/admin/projects/${project.id}#settings`}
                onOpenTerminal={(path) => {
                  setTerminalPath(path || root);
                  setTab("terminal");
                }}
              />
            )}
          </div>
        )}

        {tab === "terminal" && (
          <div data-testid="project-workspace-terminal" className="flex h-full min-h-0 flex-col bg-[#0a0d12]">
            <div className="flex h-10 shrink-0 items-center gap-2 border-b border-white/10 bg-[#0d1117] px-3">
              <Terminal size={15} className="text-accent" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[12px] font-semibold text-zinc-200">Terminal</div>
                <div className="truncate font-mono text-[10px] text-zinc-500">{terminalLabel}</div>
              </div>
            </div>
            <Suspense fallback={<div className="flex flex-1 items-center justify-center text-[12px] text-zinc-500">Starting terminal...</div>}>
              <TerminalPanel cwd={terminalCwd} />
            </Suspense>
          </div>
        )}

        {tab === "setup" && (
          <div className="h-full overflow-auto">
            <ProjectSetupSection project={project} setup={setup} />
          </div>
        )}

        {tab === "instances" && (
          <div className="h-full overflow-auto">
            <ProjectInstancesSection project={project} instances={instances} />
          </div>
        )}

        {tab === "runs" && (
          <div className="h-full overflow-auto">
            <ProjectRunsSection project={project} channels={channels} receipts={receipts} />
          </div>
        )}

        {tab === "settings" && (
          <div className="h-full overflow-auto">
            <div className="mx-auto flex w-full max-w-[1120px] flex-col gap-7 px-5 py-5 md:px-6">
              <ProjectBasicsSection
                project={project}
                channels={channels}
                setup={setup}
                runtimeEnv={runtimeEnv}
                workspaceUri={workspaceUri}
              />

              <Section
                title="Instructions"
                description="Shared turn guidance for channels attached to this Project."
                action={
                  <div className="flex items-center gap-2">
                    <SaveStatusPill
                      tone={updateProject.isPending ? "pending" : dirty ? "dirty" : "idle"}
                      label={updateProject.isPending ? "Saving" : "Unsaved"}
                    />
                    <ActionButton
                      label="Save"
                      icon={<Save size={14} />}
                      disabled={!dirty || updateProject.isPending}
                      onPress={() => updateProject.mutate({ prompt, prompt_file_path: promptFilePath.trim() || null })}
                    />
                  </div>
                }
              >
                <div data-testid="project-workspace-instructions" className="flex flex-col gap-3">
                  <PromptEditor
                    value={prompt}
                    onChange={setPrompt}
                    label="Project instructions"
                    placeholder="Optional instructions shared by every attached channel..."
                    helpText="Applied before channel-level prompt content for Project-bound turns."
                    rows={7}
                    fieldType="project_prompt"
                    generateContext={`Project: ${project.name}. Root: /${project.root_path}`}
                  />
                  <FormRow label="Prompt file" description="Optional Project-root relative file that can own these instructions later.">
                    <TextInput
                      value={promptFilePath}
                      onChangeText={setPromptFilePath}
                      placeholder=".spindrel/project-prompt.md"
                    />
                  </FormRow>
                </div>
              </Section>

              <Section
                title="Workspace Scope"
                description="Runtime cwd, file browser, terminal, search, and harness turns resolve from this root."
              >
                <div data-testid="project-workspace-file-scope" className="grid gap-2 md:grid-cols-2">
                  <SettingsControlRow
                    leading={<FolderOpen size={14} />}
                    title="Root URI"
                    description={<span className="font-mono">{workspaceUri}</span>}
                    meta={<QuietPill label={project.workspace_id} maxWidthClass="max-w-[180px]" />}
                    action={<HeaderLink to={filesHref} icon={<ExternalLink size={13} />}>Open location</HeaderLink>}
                  />
                  <SettingsControlRow
                    leading={<FileText size={14} />}
                    title="Project knowledge"
                    description={<span className="font-mono">/{root}/.spindrel/knowledge-base</span>}
                    meta={<QuietPill label="not migrated" />}
                  />
                </div>
              </Section>

              <ProjectBlueprintSection project={project} />
              <ProjectRuntimeSection runtimeEnv={runtimeEnv} />
            </div>
          </div>
        )}

        {tab === "channels" && (
          <div className="h-full overflow-auto">
            <ProjectChannelsSection project={project} channels={channels} />
          </div>
        )}
      </div>
    </div>
  );
}
