import { useState, useEffect } from "react";
import { View, Text, Pressable } from "react-native";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import {
  useMCPrefs,
  useMCOverview,
  useUpdateMCPrefs,
} from "@/src/api/hooks/useMissionControl";
import { Check, Hash, Bot, Settings, EyeOff, Eye } from "lucide-react";
import { useUIStore } from "@/src/stores/ui";

// ---------------------------------------------------------------------------
// Toggle row
// ---------------------------------------------------------------------------
function ToggleRow({
  label,
  sublabel,
  active,
  onToggle,
}: {
  label: string;
  sublabel?: string;
  active: boolean;
  onToggle: () => void;
}) {
  const t = useThemeTokens();
  return (
    <Pressable
      onPress={onToggle}
      className="flex-row items-center gap-3 rounded-lg border border-surface-border px-4 py-3 hover:bg-surface-overlay"
    >
      <View
        className="items-center justify-center rounded border"
        style={{
          width: 20,
          height: 20,
          borderColor: active ? t.accent : t.textDim,
          backgroundColor: active ? t.accent : "transparent",
        }}
      >
        {active && <Check size={14} color="#fff" />}
      </View>
      <View className="flex-1">
        <Text className="text-text text-sm">{label}</Text>
        {sublabel && (
          <Text className="text-text-dim text-xs">{sublabel}</Text>
        )}
      </View>
    </Pressable>
  );
}

// ---------------------------------------------------------------------------
// Sidebar Visibility (uses generic Zustand store)
// ---------------------------------------------------------------------------
function SidebarVisibilitySection() {
  const t = useThemeTokens();
  const hiddenSections = useUIStore((s) => s.hiddenSidebarSections);
  const toggleSection = useUIStore((s) => s.toggleSidebarSection);
  const isHidden = hiddenSections.includes("mission-control");

  return (
    <View>
      <View className="flex-row items-center gap-2 mb-3">
        {isHidden ? (
          <EyeOff size={14} color={t.textDim} />
        ) : (
          <Eye size={14} color={t.textDim} />
        )}
        <Text className="text-text-dim text-xs font-semibold tracking-wider">
          SIDEBAR
        </Text>
      </View>
      <ToggleRow
        label="Show in sidebar"
        sublabel="Display Mission Control navigation in the sidebar"
        active={!isHidden}
        onToggle={() => toggleSection("mission-control")}
      />
    </View>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------
export default function MCSettings() {
  const { data: prefs, isLoading: prefsLoading } = useMCPrefs();
  const { data: overview } = useMCOverview();
  const updatePrefs = useUpdateMCPrefs();
  const { refreshing, onRefresh } = usePageRefresh([["mc-prefs"], ["mc-overview"]]);
  const t = useThemeTokens();

  // Local state for tracked selections (null = all)
  const [trackedChannels, setTrackedChannels] = useState<Set<string> | null>(null);
  const [trackedBots, setTrackedBots] = useState<Set<string> | null>(null);
  const [initialized, setInitialized] = useState(false);

  // Sync from server prefs
  useEffect(() => {
    if (prefs && !initialized) {
      setTrackedChannels(
        prefs.tracked_channel_ids ? new Set(prefs.tracked_channel_ids) : null
      );
      setTrackedBots(
        prefs.tracked_bot_ids ? new Set(prefs.tracked_bot_ids) : null
      );
      setInitialized(true);
    }
  }, [prefs, initialized]);

  const channels = overview?.channels || [];
  const bots = overview?.bots || [];
  const isDirty =
    initialized &&
    (JSON.stringify(trackedChannels ? [...trackedChannels].sort() : null) !==
      JSON.stringify(prefs?.tracked_channel_ids?.sort() ?? null) ||
      JSON.stringify(trackedBots ? [...trackedBots].sort() : null) !==
        JSON.stringify(prefs?.tracked_bot_ids?.sort() ?? null));

  const handleSave = () => {
    updatePrefs.mutate({
      tracked_channel_ids: trackedChannels ? [...trackedChannels] : null,
      tracked_bot_ids: trackedBots ? [...trackedBots] : null,
    });
  };

  const toggleChannel = (id: string) => {
    if (!trackedChannels) {
      // Currently tracking all → switch to explicit list with just this one excluded
      const all = new Set(channels.map((ch) => ch.id));
      all.delete(id);
      setTrackedChannels(all);
    } else if (trackedChannels.has(id)) {
      const next = new Set(trackedChannels);
      next.delete(id);
      // If all are unchecked, stay as explicit empty set
      setTrackedChannels(next);
    } else {
      const next = new Set(trackedChannels);
      next.add(id);
      // If all are checked, go back to null (all)
      if (next.size === channels.length) {
        setTrackedChannels(null);
      } else {
        setTrackedChannels(next);
      }
    }
  };

  const toggleBot = (id: string) => {
    if (!trackedBots) {
      const all = new Set(bots.map((b) => b.id));
      all.delete(id);
      setTrackedBots(all);
    } else if (trackedBots.has(id)) {
      const next = new Set(trackedBots);
      next.delete(id);
      setTrackedBots(next);
    } else {
      const next = new Set(trackedBots);
      next.add(id);
      if (next.size === bots.length) {
        setTrackedBots(null);
      } else {
        setTrackedBots(next);
      }
    }
  };

  const isChannelTracked = (id: string) =>
    trackedChannels === null || trackedChannels.has(id);

  const isBotTracked = (id: string) =>
    trackedBots === null || trackedBots.has(id);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="MC Settings"
        subtitle="Configure tracking preferences"
        right={
          isDirty ? (
            <Pressable
              onPress={handleSave}
              className="rounded-lg bg-accent px-4 py-2"
              disabled={updatePrefs.isPending}
            >
              <Text style={{ color: "#fff", fontWeight: "600", fontSize: 13 }}>
                {updatePrefs.isPending ? "Saving..." : "Save"}
              </Text>
            </Pressable>
          ) : null
        }
      />

      <RefreshableScrollView
        refreshing={refreshing}
        onRefresh={onRefresh}
        contentContainerStyle={{ padding: 16, gap: 20, paddingBottom: 40 }}
      >
        {prefsLoading ? (
          <Text className="text-text-muted text-sm">Loading...</Text>
        ) : (
          <>
            {/* Sidebar visibility */}
            <SidebarVisibilitySection />

            {/* Channel tracking */}
            <View>
              <View className="flex-row items-center gap-2 mb-3">
                <Hash size={14} color={t.textDim} />
                <Text className="text-text-dim text-xs font-semibold tracking-wider">
                  TRACKED CHANNELS
                </Text>
                <Text className="text-text-dim text-[10px]">
                  {trackedChannels === null
                    ? `All (${channels.length})`
                    : `${trackedChannels.size} of ${channels.length}`}
                </Text>
              </View>
              <View className="gap-2">
                {channels.map((ch) => (
                  <ToggleRow
                    key={ch.id}
                    label={ch.name}
                    sublabel={ch.bot_name || ch.bot_id}
                    active={isChannelTracked(ch.id)}
                    onToggle={() => toggleChannel(ch.id)}
                  />
                ))}
              </View>
            </View>

            {/* Bot tracking */}
            <View>
              <View className="flex-row items-center gap-2 mb-3">
                <Bot size={14} color={t.textDim} />
                <Text className="text-text-dim text-xs font-semibold tracking-wider">
                  TRACKED BOTS
                </Text>
                <Text className="text-text-dim text-[10px]">
                  {trackedBots === null
                    ? `All (${bots.length})`
                    : `${trackedBots.size} of ${bots.length}`}
                </Text>
              </View>
              <View className="gap-2">
                {bots.map((bot) => (
                  <ToggleRow
                    key={bot.id}
                    label={bot.name}
                    sublabel={bot.model}
                    active={isBotTracked(bot.id)}
                    onToggle={() => toggleBot(bot.id)}
                  />
                ))}
              </View>
            </View>
          </>
        )}
      </RefreshableScrollView>
    </View>
  );
}
