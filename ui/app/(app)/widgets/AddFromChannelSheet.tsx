import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { X, CheckCircle2, Wrench, Search, Pin } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { envelopeIdentityKey } from "@/src/stores/pinnedWidgets";
import type { Channel, PinnedWidget } from "@/src/types/api";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Tab = "channel" | "build";

async function fetchChannelDetail(channelId: string): Promise<Channel> {
  return apiFetch<Channel>(`/api/v1/channels/${channelId}`);
}

interface ChannelWithPins {
  channel: Channel;
  pins: PinnedWidget[];
}

export default function AddFromChannelSheet({ open, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("channel");
  const [query, setQuery] = useState("");
  const { data: channels } = useChannels();
  const pins = useDashboardPinsStore((s) => s.pins);
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);

  // Parallel-fetch every channel's detail on open so we can prune empties and
  // show pin counts without per-row expansion cost.
  const [loaded, setLoaded] = useState<ChannelWithPins[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Close on Escape — standard modal UX.
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, onClose]);

  useEffect(() => {
    if (!open || !channels?.length) return;
    let cancelled = false;
    setLoaded(null);
    setLoadError(null);
    Promise.all(
      channels.map(async (ch) => {
        try {
          const detail = await fetchChannelDetail(ch.id);
          return { channel: ch, pins: detail.config?.pinned_widgets ?? [] };
        } catch {
          return { channel: ch, pins: [] as PinnedWidget[] };
        }
      }),
    ).then((rows) => {
      if (cancelled) return;
      setLoaded(rows);
    }).catch((e) => {
      if (cancelled) return;
      setLoadError(e instanceof Error ? e.message : String(e));
    });
    return () => { cancelled = true; };
  }, [open, channels]);

  const existingIdentities = useMemo(
    () => new Set(pins.map((p) => envelopeIdentityKey(p.tool_name, p.envelope))),
    [pins],
  );

  const filteredSections = useMemo(() => {
    if (!loaded) return [];
    const q = query.trim().toLowerCase();
    return loaded
      .filter((row) => row.pins.length > 0)
      .filter((row) => {
        if (!q) return true;
        if (row.channel.name.toLowerCase().includes(q)) return true;
        return row.pins.some((p) => {
          const label = (p.envelope?.display_label ?? p.display_name ?? p.tool_name).toLowerCase();
          return label.includes(q);
        });
      });
  }, [loaded, query]);

  if (!open) return null;

  return createPortal(
    <div className="fixed inset-0 z-[10030] flex justify-end">
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px]"
      />
      {/* Panel */}
      <div className="relative z-10 flex h-full w-full sm:w-[440px] flex-col border-l border-surface-border bg-surface-raised shadow-2xl">
        <header className="flex items-center justify-between border-b border-surface-border px-5 py-4">
          <div>
            <h2 className="text-[14px] font-semibold text-text">Add widget</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">
              Bring a pinned widget onto your dashboard
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1.5 text-text-muted hover:bg-surface-overlay hover:text-text transition-colors"
            aria-label="Close"
            title="Close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex gap-1 border-b border-surface-border px-4 pt-3 pb-0">
          <TabButton active={tab === "channel"} onClick={() => setTab("channel")}>
            From channel
          </TabButton>
          <TabButton active={tab === "build"} onClick={() => setTab("build")}>
            Build new
          </TabButton>
        </div>

        {tab === "channel" && (
          <div className="border-b border-surface-border px-4 py-2.5">
            <label className="flex items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 focus-within:border-accent/60">
              <Search size={13} className="text-text-dim" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search channels or widgets"
                className="flex-1 bg-transparent text-[12px] text-text placeholder-text-dim outline-none"
              />
              {query && (
                <button
                  type="button"
                  onClick={() => setQuery("")}
                  className="rounded p-0.5 text-text-dim hover:bg-surface-overlay"
                >
                  <X size={11} />
                </button>
              )}
            </label>
          </div>
        )}

        <div className="flex-1 overflow-auto">
          {tab === "channel" ? (
            <ChannelPinsTab
              loaded={loaded}
              loadError={loadError}
              sections={filteredSections}
              query={query}
              existingIdentities={existingIdentities}
              onPin={async (ch, pin) => {
                await pinWidget({
                  source_kind: "channel",
                  source_channel_id: ch.id,
                  source_bot_id: pin.bot_id,
                  tool_name: pin.tool_name,
                  widget_config: pin.config ?? {},
                  envelope: pin.envelope,
                  display_label:
                    pin.envelope?.display_label ?? pin.display_name ?? null,
                });
              }}
            />
          ) : (
            <BuildTab onClose={onClose} />
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function TabButton({
  active, children, onClick,
}: { active: boolean; children: React.ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "relative rounded-t-md px-3 py-1.5 text-[12px] font-medium transition-colors",
        active
          ? "text-accent"
          : "text-text-muted hover:text-text",
      ].join(" ")}
    >
      {children}
      {active && (
        <span className="absolute inset-x-0 -bottom-px h-0.5 bg-accent" />
      )}
    </button>
  );
}

function ChannelPinsTab({
  loaded, loadError, sections, query, existingIdentities, onPin,
}: {
  loaded: ChannelWithPins[] | null;
  loadError: string | null;
  sections: ChannelWithPins[];
  query: string;
  existingIdentities: Set<string>;
  onPin: (channel: Channel, pin: PinnedWidget) => Promise<void>;
}) {
  if (loadError) {
    return (
      <p className="p-5 text-[12px] text-danger">
        Failed to load channels: {loadError}
      </p>
    );
  }
  if (loaded === null) {
    return (
      <div className="space-y-2 p-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-14 animate-pulse rounded-md bg-surface-overlay/40" />
        ))}
      </div>
    );
  }
  if (sections.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <div className="rounded-full bg-surface-overlay p-3">
          <Pin size={16} className="text-text-dim" />
        </div>
        <p className="text-[13px] font-medium text-text">
          {query ? "No matches" : "No pinned widgets yet"}
        </p>
        <p className="max-w-[260px] text-[11px] text-text-muted">
          {query
            ? "Try a different channel or widget name."
            : "Pin a widget in any channel's OmniPanel first, then come back here to surface it on your dashboard."}
        </p>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-surface-border">
      {sections.map(({ channel, pins }) => (
        <ChannelSection
          key={channel.id}
          channel={channel}
          pins={pins}
          existingIdentities={existingIdentities}
          onPin={onPin}
        />
      ))}
    </ul>
  );
}

function ChannelSection({
  channel, pins, existingIdentities, onPin,
}: {
  channel: Channel;
  pins: PinnedWidget[];
  existingIdentities: Set<string>;
  onPin: (channel: Channel, pin: PinnedWidget) => Promise<void>;
}) {
  return (
    <li className="py-2">
      <div className="flex items-center justify-between px-4 py-1">
        <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-text-dim">
          {channel.name}
        </span>
        <span className="text-[10px] text-text-dim">
          {pins.length} pin{pins.length === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="mt-1 space-y-1 px-3">
        {pins.map((p) => {
          const identity = envelopeIdentityKey(p.tool_name, p.envelope);
          const already = existingIdentities.has(identity);
          return (
            <li key={p.id}>
              <PinRow
                pin={p}
                already={already}
                onClick={() => onPin(channel, p)}
              />
            </li>
          );
        })}
      </ul>
    </li>
  );
}

function PinRow({
  pin, already, onClick,
}: { pin: PinnedWidget; already: boolean; onClick: () => void | Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const label =
    pin.envelope?.display_label ?? pin.display_name ?? pin.tool_name;
  const integration =
    pin.tool_name.includes("-") ? pin.tool_name.split("-")[0] : pin.tool_name;

  const handleClick = async () => {
    setBusy(true);
    setError(null);
    try {
      await onClick();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <button
      type="button"
      disabled={busy}
      onClick={handleClick}
      className={[
        "group flex w-full items-center gap-2.5 rounded-md border border-transparent bg-surface px-3 py-2 text-left transition-colors",
        busy
          ? "opacity-60"
          : "hover:border-accent/40 hover:bg-surface-overlay",
      ].join(" ")}
    >
      <div className="flex-1 min-w-0">
        <div className="truncate text-[12px] font-medium text-text">{label}</div>
        <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-text-dim">
          <span className="rounded bg-surface-overlay px-1 py-px uppercase tracking-wider">
            {integration}
          </span>
          {error && <span className="text-danger">{error}</span>}
        </div>
      </div>
      {already ? (
        <span
          className="inline-flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-[10px] text-accent"
          title="Already on dashboard"
        >
          <CheckCircle2 size={10} /> Pinned
        </span>
      ) : (
        <span className="text-[10px] text-text-dim opacity-0 transition-opacity group-hover:opacity-100">
          Add
        </span>
      )}
    </button>
  );
}

function BuildTab({ onClose }: { onClose: () => void }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 p-8 text-center">
      <div className="rounded-full bg-accent/10 p-3">
        <Wrench size={18} className="text-accent" />
      </div>
      <p className="max-w-[260px] text-[12px] text-text-muted">
        Run any tool, shape its output, and pin the result to this dashboard.
      </p>
      <Link
        to="/widgets/dev#tools"
        onClick={onClose}
        className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90"
      >
        Open developer panel
      </Link>
    </div>
  );
}
