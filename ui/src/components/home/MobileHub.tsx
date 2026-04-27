import { PageHeader } from "../layout/PageHeader";
import { RefreshableScrollView } from "../shared/RefreshableScrollView";
import { usePageRefresh } from "../../hooks/usePageRefresh";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { contextualNavigationState } from "../../lib/contextualNavigation";

import { HubSections } from "./HubSections";
const HUB_BACK_STATE = contextualNavigationState("/", "Home");

/**
 * Mobile-only home hub. Replaces the legacy `HomeChannelsList` with a
 * stack of small section components, each driven by its own canonical
 * hook. Sections render `null` when they have nothing to show, so a
 * quiet workspace stays compact.
 *
 * Order is "alerts first → channels middle → exploration last": blocking
 * onboarding → attention → daily health → upcoming → channels → memory
 * pulse → pinned widgets → context bloat.
 */
export function MobileHub() {
  const { refreshing, onRefresh } = usePageRefresh();

  return (
    <div className="flex flex-col flex-1 overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Home"
        right={
          <Link
            to="/channels/new"
            state={HUB_BACK_STATE}
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-accent hover:bg-accent/[0.08] text-sm font-medium"
          >
            <Plus size={14} />
            <span>New</span>
          </Link>
        }
      />
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
        <div className="mx-auto box-border w-full max-w-[672px] px-4 py-4">
          <HubSections />
        </div>
      </RefreshableScrollView>
    </div>
  );
}
