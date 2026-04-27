import { Link, useNavigate } from "react-router-dom";
import { AlertTriangle, ChevronRight, Home } from "lucide-react";

import { useChannels, useEnsureOrchestrator } from "../../../api/hooks/useChannels";
import { useProviders } from "../../../api/hooks/useProviders";
import { useAuthStore } from "../../../stores/auth";
import type { Channel } from "../../../types/api";

function isOrchestratorChannel(channel: Channel): boolean {
  return channel.client_id === "orchestrator:home";
}

/**
 * First-run / setup CTA at the top of the mobile hub. Three states:
 *  - orchestrator exists → highlight it as the "Home" hero card
 *  - admin without orchestrator and no provider → push to add a provider
 *  - admin without orchestrator with a provider → guided setup CTA
 *
 * Renders nothing when none of the above apply (e.g. non-admin user
 * already past setup).
 */
export function OnboardingSection() {
  const { data: channels, isLoading: channelsLoading } = useChannels();
  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const { data: providersData, isLoading: providersLoading } = useProviders(isAdmin);
  const navigate = useNavigate();
  const ensureOrchestrator = useEnsureOrchestrator();

  if (channelsLoading) return null;

  const orchestrator = channels?.find(isOrchestratorChannel);
  const hasProviders = providersLoading || (providersData?.providers?.length ?? 0) > 0;

  if (orchestrator) {
    return (
      <Link
        to={`/channels/${orchestrator.id}`}
        className="group flex items-center gap-3 rounded-md bg-accent/[0.08] px-4 py-3.5 transition-colors hover:bg-accent/[0.12]"
      >
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-accent/[0.16] text-accent">
          <Home size={22} />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-base font-semibold text-text">Home</span>
          <span className="block text-xs text-text-muted">
            Setup, projects, and system management
          </span>
        </span>
        <ChevronRight size={16} className="shrink-0 text-text-dim" />
      </Link>
    );
  }

  if (!isAdmin) return null;

  if (!hasProviders) {
    return (
      <Link
        to="/admin/providers"
        className="flex items-center gap-3 rounded-md bg-warning/10 px-4 py-3 text-warning-muted transition-colors hover:bg-warning/15"
      >
        <AlertTriangle size={18} className="shrink-0" />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium text-text">No LLM provider configured</span>
          <span className="block text-xs text-text-muted">
            Add one in Admin &gt; Providers to start chatting.
          </span>
        </span>
        <ChevronRight size={14} className="shrink-0 text-text-dim" />
      </Link>
    );
  }

  return (
    <button
      type="button"
      disabled={ensureOrchestrator.isPending}
      onClick={() => {
        ensureOrchestrator.mutate(undefined, {
          onSuccess: (data) => navigate(`/channels/${data.id}`),
        });
      }}
      className="flex items-center gap-3 rounded-md bg-accent/[0.08] px-4 py-3.5 text-left transition-colors hover:bg-accent/[0.12] disabled:opacity-60"
    >
      <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-md bg-accent/[0.16] text-accent">
        <Home size={22} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-base font-semibold text-text">
          {ensureOrchestrator.isPending ? "Setting up…" : "Guided Setup"}
        </span>
        <span className="block text-xs text-text-muted">
          AI-guided walkthrough for creating bots and channels
        </span>
        {ensureOrchestrator.isError ? (
          <span className="mt-1 block text-xs text-danger">
            {ensureOrchestrator.error instanceof Error
              ? ensureOrchestrator.error.message
              : "Failed to create orchestrator"}
          </span>
        ) : null}
      </span>
      <ChevronRight size={16} className="shrink-0 text-text-dim" />
    </button>
  );
}
