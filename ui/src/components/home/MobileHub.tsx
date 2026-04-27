import { PageHeader } from "../layout/PageHeader";
import { RefreshableScrollView } from "../shared/RefreshableScrollView";
import { usePageRefresh } from "../../hooks/usePageRefresh";
import { Link } from "react-router-dom";
import { Plus } from "lucide-react";

import { HubSections } from "./HubSections";

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
            className="inline-flex items-center gap-1.5 rounded-md px-3 py-2 text-accent hover:bg-accent/[0.08] text-sm font-medium"
          >
            <Plus size={14} />
            <span>New</span>
          </Link>
        }
      />
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} className="flex-1">
        <div className="mx-auto box-border flex w-full max-w-[672px] flex-col gap-5 px-4 py-4">
          <OnboardingSection />
          <AttentionSection />
          <DailyHealthSection />
          <UpcomingSection />
          <ChannelsSection />
          <MemoryPulseSection />
          <PinnedWidgetsSection />
          <BloatSection />
        </div>
      </RefreshableScrollView>
    </div>
  );
}
