import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import { CheckCircle2, Circle, Play, Plus, RefreshCw, Terminal } from "lucide-react";

import { apiFetch } from "@/src/api/client";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { Spinner } from "@/src/components/shared/Spinner";
import { ActionButton } from "@/src/components/shared/SettingsControls";
import { TerminalDrawer } from "@/src/components/terminal/TerminalDrawer";
import { useTerminalDrawer } from "@/src/hooks/useTerminalDrawer";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";

interface HarnessRuntime {
  name: string;
  ok: boolean;
  detail: string;
  suggested_command: string | null;
}

interface HarnessesResponse {
  runtimes: HarnessRuntime[];
}

function useHarnesses() {
  return useQuery({
    queryKey: ["admin-harnesses"],
    queryFn: () => apiFetch<HarnessesResponse>("/api/v1/admin/harnesses"),
  });
}

const RUNTIME_LABEL: Record<string, string> = {
  "claude-code": "Claude Code",
};

export default function HarnessesScreen() {
  const { data, isLoading, isError, error, refetch } = useHarnesses();
  const { refreshing, onRefresh } = usePageRefresh([["admin-harnesses"]]);
  const { open, options, openTerminal, closeTerminal } = useTerminalDrawer();
  const navigate = useNavigate();

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Agent Harnesses"
        subtitle="External agent runtimes that can drive a bot end-to-end"
        right={
          <ActionButton
            label="Refresh"
            variant="ghost"
            size="small"
            icon={<RefreshCw size={13} />}
            onPress={() => { void refetch(); }}
          />
        }
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        style={{ flex: 1 }}
        contentContainerStyle={{ padding: 16, maxWidth: 720 }}
      >
        {isLoading && (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        )}

        {isError && (
          <div className="rounded-md border border-danger-border bg-danger-subtle px-4 py-3 text-[13px] text-danger">
            Failed to load harnesses: {(error as Error).message}
          </div>
        )}

        {data && (
          <div className="flex flex-col gap-3">
            <p className="text-[12px] leading-relaxed text-text-dim">
              A bot becomes a harness bot by setting its <code className="rounded bg-surface-overlay/50 px-1 py-0.5 text-[11px]">harness_runtime</code>
              {" "}field on the bot edit page. Authentication is per-host: each runtime
              picks up the OAuth credentials its CLI writes after{" "}
              <code className="rounded bg-surface-overlay/50 px-1 py-0.5 text-[11px]">claude login</code>
              {" "}/{" "}
              <code className="rounded bg-surface-overlay/50 px-1 py-0.5 text-[11px]">codex login</code>.
              See <code className="rounded bg-surface-overlay/50 px-1 py-0.5 text-[11px]">docs/guides/agent-harnesses.md</code>.
            </p>

            {data.runtimes.length === 0 && (
              <div className="rounded-md border border-surface-overlay bg-surface-raised px-4 py-3 text-[13px] text-text-dim">
                No harness runtimes registered.
              </div>
            )}

            {data.runtimes.map((rt) => (
              <RuntimeCard
                key={rt.name}
                runtime={rt}
                onRunSuggested={(cmd) => openTerminal({
                  title: `${RUNTIME_LABEL[rt.name] ?? rt.name} — auth`,
                  subtitle: cmd,
                  seedCommand: cmd,
                })}
                onCreateBot={() => navigate(`/admin/bots/new?harness=${encodeURIComponent(rt.name)}`)}
              />
            ))}
          </div>
        )}
      </RefreshableScrollView>

      <TerminalDrawer
        open={open}
        onClose={() => {
          closeTerminal();
          // Drawer close almost always means the user finished a setup step
          // (claude login, mkdir, git clone) — refresh status so the page
          // reflects the new state without a manual click.
          void refetch();
        }}
        seedCommand={options.seedCommand}
        cwd={options.cwd}
        title={options.title}
        subtitle={options.subtitle}
        width={options.width}
      />
    </div>
  );
}

function RuntimeCard({
  runtime,
  onRunSuggested,
  onCreateBot,
}: {
  runtime: HarnessRuntime;
  onRunSuggested: (cmd: string) => void;
  onCreateBot: () => void;
}) {
  const label = RUNTIME_LABEL[runtime.name] ?? runtime.name;
  return (
    <div className="rounded-lg border border-surface-overlay bg-surface-raised px-4 py-3">
      <div className="flex items-start gap-3">
        <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-surface-overlay/40">
          <Terminal size={16} className="text-text-muted" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="text-[14px] font-semibold text-text">{label}</h3>
            <span className="rounded bg-surface-overlay/40 px-1.5 py-0.5 font-mono text-[10px] text-text-dim">
              {runtime.name}
            </span>
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            {runtime.ok ? (
              <CheckCircle2 size={14} className="shrink-0 text-success" />
            ) : (
              <Circle size={14} className="shrink-0 text-text-dim" />
            )}
            <span
              className={
                runtime.ok
                  ? "text-[12px] text-success"
                  : "text-[12px] text-text-dim"
              }
            >
              {runtime.ok ? "Authenticated" : "Not authenticated"}
            </span>
          </div>
          <p className="mt-1 break-words font-mono text-[11px] leading-relaxed text-text-dim">
            {runtime.detail}
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {!runtime.ok && runtime.suggested_command && (
              <ActionButton
                label={`Run ${runtime.suggested_command}`}
                variant="primary"
                size="small"
                icon={<Play size={13} />}
                onPress={() => onRunSuggested(runtime.suggested_command!)}
              />
            )}
            <ActionButton
              label="Create harness bot"
              variant={runtime.ok ? "primary" : "ghost"}
              size="small"
              icon={<Plus size={13} />}
              onPress={onCreateBot}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
