import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { X, ChevronDown, ChevronRight, CheckCircle2, Wrench } from "lucide-react";
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

/** Load a channel's full record so we can read `config.pinned_widgets`.
 *  useChannels() returns the list endpoint which doesn't carry the config blob. */
async function fetchChannelDetail(channelId: string): Promise<Channel> {
  return apiFetch<Channel>(`/api/v1/channels/${channelId}`);
}

export default function AddFromChannelSheet({ open, onClose }: Props) {
  const [tab, setTab] = useState<Tab>("channel");
  const { data: channels } = useChannels();
  const pins = useDashboardPinsStore((s) => s.pins);
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);

  // Dashboard identity set for "Already on dashboard" hinting.
  const existingIdentities = useMemo(
    () => new Set(pins.map((p) => envelopeIdentityKey(p.tool_name, p.envelope))),
    [pins],
  );

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex justify-end">
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close"
        className="absolute inset-0 bg-black/40"
        onClick={onClose}
      />
      {/* Panel */}
      <div className="relative z-10 flex h-full w-[480px] max-w-[92vw] flex-col border-l border-surface-border bg-surface-raised shadow-2xl">
        <header className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <h2 className="text-[14px] font-semibold">Add widget</h2>
          <button
            type="button"
            onClick={onClose}
            className="rounded p-1 text-text-muted hover:bg-surface-overlay"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex gap-1 border-b border-surface-border px-3 py-2">
          <TabButton active={tab === "channel"} onClick={() => setTab("channel")}>
            From channel
          </TabButton>
          <TabButton active={tab === "build"} onClick={() => setTab("build")}>
            Build new
          </TabButton>
        </div>

        <div className="flex-1 overflow-auto">
          {tab === "channel" ? (
            <ChannelPinsTab
              channels={channels ?? []}
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
    </div>
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
        "rounded px-2.5 py-1 text-[12px] font-medium transition-colors",
        active
          ? "bg-accent/10 text-accent"
          : "text-text-muted hover:bg-surface-overlay hover:text-text",
      ].join(" ")}
    >
      {children}
    </button>
  );
}

function ChannelPinsTab({
  channels, existingIdentities, onPin,
}: {
  channels: Channel[];
  existingIdentities: Set<string>;
  onPin: (channel: Channel, pin: PinnedWidget) => Promise<void>;
}) {
  if (channels.length === 0) {
    return (
      <p className="p-6 text-[12px] text-text-muted">
        No channels yet — create a channel and pin a widget there first.
      </p>
    );
  }
  return (
    <ul className="divide-y divide-surface-border">
      {channels.map((ch) => (
        <ChannelSection
          key={ch.id}
          channel={ch}
          existingIdentities={existingIdentities}
          onPin={onPin}
        />
      ))}
    </ul>
  );
}

function ChannelSection({
  channel, existingIdentities, onPin,
}: {
  channel: Channel;
  existingIdentities: Set<string>;
  onPin: (channel: Channel, pin: PinnedWidget) => Promise<void>;
}) {
  const [open, setOpen] = useState(false);
  const [detail, setDetail] = useState<Channel | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || detail || loading) return;
    setLoading(true);
    fetchChannelDetail(channel.id)
      .then((d) => setDetail(d))
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  }, [open, detail, loading, channel.id]);

  const pinned = detail?.config?.pinned_widgets ?? [];

  return (
    <li>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-surface-overlay"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <span className="flex-1 truncate text-[13px] font-medium">{channel.name}</span>
        {detail && (
          <span className="text-[11px] uppercase tracking-wider text-text-dim">
            {pinned.length} pin{pinned.length === 1 ? "" : "s"}
          </span>
        )}
      </button>
      {open && (
        <div className="px-4 pb-3">
          {loading && (
            <p className="text-[12px] text-text-muted">Loading…</p>
          )}
          {error && (
            <p className="text-[12px] text-red-400">Error: {error}</p>
          )}
          {!loading && !error && pinned.length === 0 && (
            <p className="text-[12px] text-text-muted">
              No widgets pinned in this channel.
            </p>
          )}
          {pinned.length > 0 && (
            <ul className="space-y-1">
              {pinned.map((p) => {
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
          )}
        </div>
      )}
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
        "flex w-full items-center gap-2 rounded border border-surface-border px-3 py-2 text-left transition-colors",
        busy
          ? "opacity-60"
          : "hover:bg-surface-overlay hover:border-accent/40",
      ].join(" ")}
    >
      <span className="flex-1 truncate text-[12px]">{label}</span>
      <span className="text-[10px] uppercase tracking-wider text-text-dim">
        {pin.tool_name.split("-")[0] ?? pin.tool_name}
      </span>
      {already && (
        <span
          className="inline-flex items-center gap-1 rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] text-text-dim"
          title="Already on dashboard"
        >
          <CheckCircle2 size={10} /> pinned
        </span>
      )}
      {error && (
        <span className="text-[10px] text-red-400">{error}</span>
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
      <p className="text-[13px] text-text-muted">
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
