import { OnboardingSection } from "./sections/OnboardingSection";
import { AttentionSection } from "./sections/AttentionSection";
import { DailyHealthSection } from "./sections/DailyHealthSection";
import { UpcomingSection } from "./sections/UpcomingSection";
import { ChannelsSection } from "./sections/ChannelsSection";
import { MemoryPulseSection } from "./sections/MemoryPulseSection";
import { PinnedWidgetsSection } from "./sections/PinnedWidgetsSection";
import { BloatSection } from "./sections/BloatSection";

/**
 * The hub's section stack — Onboarding → Attention → Daily Health →
 * Upcoming → Channels → Memory pulse → Pinned widgets → Context bloat.
 * Reused by both the mobile-only `<MobileHub />` and the Starboard
 * "Hub" station so the two surfaces stay structurally identical.
 *
 * No outer chrome — the host (page or starboard panel) owns padding,
 * scroll, header, and pull-to-refresh.
 */
export function HubSections() {
  return (
    <div className="flex flex-col gap-5">
      <OnboardingSection />
      <AttentionSection />
      <DailyHealthSection />
      <UpcomingSection />
      <ChannelsSection />
      <MemoryPulseSection />
      <PinnedWidgetsSection />
      <BloatSection />
    </div>
  );
}
