import { useState, useEffect, useMemo } from "react";
import { usePrefs, useUpdatePrefs } from "../hooks/useMC";
import { useOverview } from "../hooks/useOverview";
import { useScope } from "../lib/ScopeContext";
import LoadingSpinner from "../components/LoadingSpinner";
import ErrorBanner from "../components/ErrorBanner";
import InfoPanel from "../components/InfoPanel";
import ScopeToggle from "../components/ScopeToggle";

export default function Settings() {
  const { data: prefs, isLoading: prefsLoading, error: prefsError } = usePrefs();
  const { scope } = useScope();
  const { data: overview } = useOverview(scope);
  const updatePrefs = useUpdatePrefs();

  const [trackedChannels, setTrackedChannels] = useState<string[]>([]);
  const [trackedBots, setTrackedBots] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (prefs) {
      setTrackedChannels(prefs.tracked_channel_ids || []);
      setTrackedBots(prefs.tracked_bot_ids || []);
      setDirty(false);
    }
  }, [prefs]);

  const channels = useMemo(() => overview?.channels || [], [overview]);
  const bots = useMemo(() => overview?.bots || [], [overview]);

  const toggleChannel = (id: string) => {
    setTrackedChannels((prev) =>
      prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id],
    );
    setDirty(true);
    setSaved(false);
  };

  const toggleBot = (id: string) => {
    setTrackedBots((prev) =>
      prev.includes(id) ? prev.filter((b) => b !== id) : [...prev, id],
    );
    setDirty(true);
    setSaved(false);
  };

  const handleSave = async () => {
    await updatePrefs.mutateAsync({
      tracked_channel_ids: trackedChannels.length > 0 ? trackedChannels : null,
      tracked_bot_ids: trackedBots.length > 0 ? trackedBots : null,
    });
    setDirty(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 2500);
  };

  if (prefsLoading) return <div className="p-6"><LoadingSpinner /></div>;
  if (prefsError) return <div className="p-6"><ErrorBanner message={prefsError.message} /></div>;

  return (
    <div className="p-6 max-w-3xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-content">Settings</h1>
          <p className="text-sm text-content-dim mt-1">Configure tracked channels and bots</p>
        </div>
        <div className="flex items-center gap-3">
          {dirty && (
            <button
              onClick={handleSave}
              disabled={updatePrefs.isPending}
              className="px-4 py-2 text-xs rounded-md bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-50"
            >
              {updatePrefs.isPending ? "Saving..." : saved ? "✔ Saved" : "Save Changes"}
            </button>
          )}
          <ScopeToggle />
        </div>
      </div>

      <InfoPanel
        id="settings"
        description="Control which channels and bots appear in your dashboard."
        tips={[
          "Default is all — select specific ones to narrow your view.",
          "Settings affect all dashboard pages (Kanban, Journal, Memory, etc.).",
        ]}
      />

      {/* Tracked Channels */}
      <div className="bg-surface-2 rounded-xl border border-surface-3 p-4 mb-6">
        <h2 className="text-sm font-semibold text-content mb-1">Tracked Channels</h2>
        <p className="text-xs text-content-dim mb-3">
          {trackedChannels.length === 0
            ? "All channels are tracked (default)"
            : `${trackedChannels.length} channel${trackedChannels.length !== 1 ? "s" : ""} selected`}
        </p>
        <div className="space-y-1">
          {channels.map((ch) => {
            const checked = trackedChannels.length === 0 || trackedChannels.includes(ch.id);
            return (
              <label
                key={ch.id}
                className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-surface-3 cursor-pointer transition-colors"
              >
                <input type="checkbox" checked={checked} onChange={() => toggleChannel(ch.id)} className="rounded border-surface-3" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm text-content truncate block">{ch.name || ch.id.slice(0, 8)}</span>
                  {ch.bot_name && <span className="text-xs text-content-dim">{ch.bot_name}</span>}
                </div>
                {ch.workspace_enabled && <span className="w-2 h-2 rounded-full bg-green-400 flex-shrink-0" />}
              </label>
            );
          })}
        </div>
      </div>

      {/* Tracked Bots */}
      <div className="bg-surface-2 rounded-xl border border-surface-3 p-4">
        <h2 className="text-sm font-semibold text-content mb-1">Tracked Bots</h2>
        <p className="text-xs text-content-dim mb-3">
          {trackedBots.length === 0
            ? "All bots are tracked (default)"
            : `${trackedBots.length} bot${trackedBots.length !== 1 ? "s" : ""} selected`}
        </p>
        <div className="space-y-1">
          {bots.map((bot) => {
            const checked = trackedBots.length === 0 || trackedBots.includes(bot.id);
            return (
              <label
                key={bot.id}
                className="flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-surface-3 cursor-pointer transition-colors"
              >
                <input type="checkbox" checked={checked} onChange={() => toggleBot(bot.id)} className="rounded border-surface-3" />
                <div className="flex-1 min-w-0">
                  <span className="text-sm text-content">{bot.name}</span>
                  {bot.model && <span className="text-xs text-content-dim ml-2">{bot.model}</span>}
                </div>
                <span className="text-xs text-content-dim">{bot.channel_count} ch</span>
              </label>
            );
          })}
        </div>
      </div>
    </div>
  );
}
