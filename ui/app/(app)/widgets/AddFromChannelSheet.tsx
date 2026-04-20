import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { X, CheckCircle2, ChevronDown, Loader2, Wrench, Search, Pin, Clock } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { envelopeIdentityKey } from "@/src/stores/pinnedWidgets";
import { toast } from "@/src/stores/toast";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import { useThemeTokens } from "@/src/theme/tokens";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import type {
  HtmlWidgetCatalog,
  HtmlWidgetEntry,
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";
import { HtmlWidgetsTab, pinIdentity } from "./HtmlWidgetsTab";

/** Previews are read-only — widget `callTool` dispatches inside the sheet
 *  don't mutate anything. A no-op dispatcher makes that explicit. */
const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

interface Props {
  open: boolean;
  onClose: () => void;
  /** Name of the active dashboard — used in the success toast. */
  dashboardName?: string;
  /** Called with the new pin's id after a successful add. The dashboard page
   *  uses this to scroll-into-view + accent-flash the new tile. */
  onPinned?: (pinId: string) => void;
  /** When set, the "Recent calls" tab pre-filters to calls in this channel
   *  and becomes the default tab (channel dashboards open here most often). */
  scopeChannelId?: string | null;
}

type Tab = "channel" | "recent" | "html-widgets" | "build";

interface RecentCall {
  id: string;
  tool_name: string;
  bot_id: string | null;
  channel_id: string | null;
  channel_name: string | null;
  tool_args: Record<string, unknown>;
  envelope: ToolResultEnvelope;
  display_label: string | null;
  created_at: string | null;
}

interface ChannelPinsGroup {
  dashboard_slug: string;
  channel_id: string | null;
  channel_name: string;
  pins: WidgetDashboardPin[];
}

export default function AddFromChannelSheet({
  open,
  onClose,
  dashboardName,
  onPinned,
  scopeChannelId,
}: Props) {
  // "From channel" is the promote-channel-pin-upward tab — only meaningful
  // on the global (non-channel) dashboard. Inside a channel dashboard it's
  // redundant (you ARE that channel's board) so the tab hides, and Recent
  // calls becomes the natural landing.
  const showChannelTab = !scopeChannelId;
  // "HTML widgets" exposes the unified catalog (built-in + integration +
  // channel-workspace), so it's always available — even on the global
  // dashboard where there's no channel scope.
  const showHtmlWidgetsTab = true;
  const [tab, setTab] = useState<Tab>(
    scopeChannelId ? "recent" : "channel",
  );
  const [query, setQuery] = useState("");
  const pins = useDashboardPinsStore((s) => s.pins);
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);

  // Single batch query: channel dashboards with ≥1 pin, grouped and named.
  // Replaces the old per-channel fan-out against ``channel.config.pinned_widgets``
  // (migration 213 moved that storage into ``widget_dashboard_pins``).
  const [loaded, setLoaded] = useState<ChannelPinsGroup[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Recent tool-call envelopes — filtered to scopeChannelId when provided.
  const [recent, setRecent] = useState<RecentCall[] | null>(null);
  const [recentError, setRecentError] = useState<string | null>(null);

  // Full HTML-widget catalog: built-in + per-integration + per-channel.
  const [htmlCatalog, setHtmlCatalog] = useState<HtmlWidgetCatalog | null>(null);
  const [htmlError, setHtmlError] = useState<string | null>(null);

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
    if (!open || !showChannelTab) return;
    let cancelled = false;
    setLoaded(null);
    setLoadError(null);
    apiFetch<{ channels: ChannelPinsGroup[] }>(
      "/api/v1/widgets/dashboards/channel-pins",
    )
      .then((resp) => {
        if (!cancelled) setLoaded(resp.channels ?? []);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [open, showChannelTab]);

  // Fetch recent widget-producing tool calls, refetched whenever the sheet
  // opens or the channel scope changes.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setRecent(null);
    setRecentError(null);
    const qs = new URLSearchParams({ limit: "30" });
    if (scopeChannelId) qs.set("channel_id", scopeChannelId);
    apiFetch<{ calls: RecentCall[] }>(`/api/v1/widgets/recent-calls?${qs}`)
      .then((resp) => {
        if (!cancelled) setRecent(resp.calls ?? []);
      })
      .catch((e) => {
        if (!cancelled) setRecentError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [open, scopeChannelId]);

  // Fetch the unified HTML-widget catalog — built-in, per-integration, and
  // per-channel. Mtime-cached on the backend so re-firing on every sheet
  // open is cheap. Same endpoint backs the dev-panel Library section.
  useEffect(() => {
    if (!open || !showHtmlWidgetsTab) return;
    let cancelled = false;
    setHtmlCatalog(null);
    setHtmlError(null);
    apiFetch<HtmlWidgetCatalog>("/api/v1/widgets/html-widget-catalog")
      .then((resp) => { if (!cancelled) setHtmlCatalog(resp); })
      .catch((e) => {
        if (!cancelled) setHtmlError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [open, showHtmlWidgetsTab]);

  const existingIdentities = useMemo(
    () => new Set(pins.map((p) => envelopeIdentityKey(p.tool_name, p.envelope))),
    [pins],
  );

  // Identity set for path-mode HTML-widget pins — now source-kind aware so
  // built-in / integration / channel entries all dedup correctly against an
  // existing pin.
  const existingHtmlIdentities = useMemo(() => {
    const set = new Set<string>();
    for (const p of pins) {
      if (p.tool_name !== "emit_html_widget") continue;
      const id = pinIdentity(p.envelope);
      if (id) set.add(id);
    }
    return set;
  }, [pins]);

  const filteredSections = useMemo(() => {
    if (!loaded) return [];
    const q = query.trim().toLowerCase();
    return loaded
      .filter((row) => row.pins.length > 0)
      .filter((row) => {
        if (!q) return true;
        if (row.channel_name.toLowerCase().includes(q)) return true;
        return row.pins.some((p) => {
          const label = (p.envelope?.display_label ?? p.tool_name).toLowerCase();
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
      {/* Panel — shadow + surface-raised separates it from the scrim; no
          border-l needed (chrome lines read as low-polish admin UI). */}
      <div className="relative z-10 flex h-full w-full sm:w-[440px] flex-col bg-surface-raised shadow-2xl">
        <header className="flex items-center justify-between px-5 pt-4 pb-3">
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

        <div className="flex gap-1 px-4 pt-3 pb-0">
          <TabButton active={tab === "recent"} onClick={() => setTab("recent")}>
            Recent calls
          </TabButton>
          {showChannelTab && (
            <TabButton active={tab === "channel"} onClick={() => setTab("channel")}>
              From channel
            </TabButton>
          )}
          {showHtmlWidgetsTab && (
            <TabButton active={tab === "html-widgets"} onClick={() => setTab("html-widgets")}>
              HTML widgets
            </TabButton>
          )}
          <TabButton active={tab === "build"} onClick={() => setTab("build")}>
            Build new
          </TabButton>
        </div>

        {(tab === "channel" || tab === "html-widgets") && (
          <div className="px-4 py-2.5">
            <label className="flex items-center gap-2 rounded-md border border-surface-border bg-surface px-2.5 py-1.5 focus-within:border-accent/60">
              <Search size={13} className="text-text-dim" />
              <input
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder={
                  tab === "html-widgets"
                    ? "Search HTML widgets"
                    : "Search channels or widgets"
                }
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
          {tab === "recent" && (
            <RecentCallsTab
              loaded={recent}
              loadError={recentError}
              query={query}
              existingIdentities={existingIdentities}
              scoped={!!scopeChannelId}
              onPin={async (call) => {
                const created = await pinWidget({
                  source_kind: call.channel_id ? "channel" : "adhoc",
                  source_channel_id: call.channel_id ?? null,
                  source_bot_id: call.bot_id ?? null,
                  tool_name: call.tool_name,
                  tool_args: call.tool_args,
                  envelope: call.envelope,
                  display_label:
                    call.display_label ?? call.envelope?.display_label ?? null,
                });
                const label =
                  call.display_label ?? call.envelope?.display_label ?? call.tool_name;
                toast({
                  kind: "success",
                  message: `Added ${label} to ${dashboardName ?? "dashboard"}`,
                  action: onPinned
                    ? {
                        label: "View",
                        onClick: () => {
                          onPinned(created.id);
                          onClose();
                        },
                      }
                    : undefined,
                });
                onPinned?.(created.id);
              }}
            />
          )}
          {tab === "channel" && showChannelTab && (
            <ChannelPinsTab
              loaded={loaded}
              loadError={loadError}
              sections={filteredSections}
              query={query}
              existingIdentities={existingIdentities}
              onPin={async (group, pin) => {
                const created = await pinWidget({
                  source_kind: pin.source_channel_id ? "channel" : "adhoc",
                  source_channel_id: pin.source_channel_id ?? group.channel_id,
                  source_bot_id: pin.source_bot_id ?? null,
                  tool_name: pin.tool_name,
                  tool_args: pin.tool_args ?? undefined,
                  widget_config: pin.widget_config ?? {},
                  envelope: pin.envelope,
                  display_label:
                    pin.display_label ?? pin.envelope?.display_label ?? null,
                });
                const label =
                  pin.display_label
                  ?? pin.envelope?.display_label
                  ?? pin.tool_name;
                toast({
                  kind: "success",
                  message: `Added ${label} to ${dashboardName ?? "dashboard"}`,
                  action: onPinned
                    ? {
                        label: "View",
                        onClick: () => {
                          onPinned(created.id);
                          onClose();
                        },
                      }
                    : undefined,
                });
                onPinned?.(created.id);
              }}
            />
          )}
          {tab === "html-widgets" && showHtmlWidgetsTab && (
            <HtmlWidgetsTab
              catalog={htmlCatalog}
              loadError={htmlError}
              query={query}
              existingIdentities={existingHtmlIdentities}
              onPin={async (entry, envelope) => {
                // Tool args carry a source-specific marker so the pin can be
                // rehydrated later even if the renderer evolves. For channel
                // entries we keep the legacy absolute-path form that
                // emit_html_widget already understands; for built-in / integration
                // entries the envelope's source_kind + path is the source of
                // truth.
                const toolArgs: Record<string, unknown> = (() => {
                  if (entry.source === "channel") {
                    // Channel entries require a channel id; envelopeForEntry
                    // attached it. Fall back to the scope if present.
                    const cid =
                      envelope.source_channel_id ?? scopeChannelId ?? null;
                    if (cid) {
                      return { path: `/workspace/channels/${cid}/${entry.path}` };
                    }
                  }
                  if (entry.source === "builtin") {
                    return { source: "builtin", path: entry.path };
                  }
                  if (entry.source === "integration") {
                    return {
                      source: "integration",
                      integration_id: entry.integration_id,
                      path: entry.path,
                    };
                  }
                  return { path: entry.path };
                })();
                // ``source_channel_id`` on the pin row is required when the
                // dashboard is a channel dashboard (service-layer validation).
                // For built-in / integration widgets the envelope doesn't
                // carry a channel id — fall back to the dashboard's scope so
                // the pin row is locatable and the channel-dashboard guard
                // doesn't 400.
                const pinChannelId =
                  envelope.source_channel_id ?? scopeChannelId ?? null;
                const created = await pinWidget({
                  source_kind: entry.source === "channel" ? "channel" : "adhoc",
                  source_channel_id: pinChannelId,
                  source_bot_id: null,
                  tool_name: "emit_html_widget",
                  tool_args: toolArgs,
                  envelope,
                  display_label: entry.display_label,
                });
                toast({
                  kind: "success",
                  message: `Added ${entry.display_label} to ${dashboardName ?? "dashboard"}`,
                  action: onPinned
                    ? {
                        label: "View",
                        onClick: () => {
                          onPinned(created.id);
                          onClose();
                        },
                      }
                    : undefined,
                });
                onPinned?.(created.id);
              }}
            />
          )}
          {tab === "build" && <BuildTab onClose={onClose} />}
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
  loaded: ChannelPinsGroup[] | null;
  loadError: string | null;
  sections: ChannelPinsGroup[];
  query: string;
  existingIdentities: Set<string>;
  onPin: (group: ChannelPinsGroup, pin: WidgetDashboardPin) => Promise<void>;
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
          {query ? "No matches" : "No channel widgets yet"}
        </p>
        <p className="max-w-[260px] text-[11px] text-text-muted">
          {query
            ? "Try a different channel or widget name."
            : "Pin a widget on any channel's dashboard first, then come back here to promote it to this dashboard."}
        </p>
      </div>
    );
  }
  return (
    <ul className="divide-y divide-surface-border">
      {sections.map((group) => (
        <ChannelSection
          key={group.dashboard_slug}
          group={group}
          existingIdentities={existingIdentities}
          onPin={onPin}
        />
      ))}
    </ul>
  );
}

function ChannelSection({
  group, existingIdentities, onPin,
}: {
  group: ChannelPinsGroup;
  existingIdentities: Set<string>;
  onPin: (group: ChannelPinsGroup, pin: WidgetDashboardPin) => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  return (
    <li className="py-2">
      <div className="flex items-center justify-between px-4 py-1">
        <span className="truncate text-[11px] font-semibold uppercase tracking-wider text-text-dim">
          {group.channel_name}
        </span>
        <span className="text-[10px] text-text-dim">
          {group.pins.length} pin{group.pins.length === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="mt-1 space-y-1 px-3">
        {group.pins.map((p) => {
          const identity = envelopeIdentityKey(p.tool_name, p.envelope);
          const already = existingIdentities.has(identity);
          const selected = selectedId === p.id;
          return (
            <li key={p.id}>
              <PinRow
                pin={p}
                already={already}
                selected={selected}
                onSelect={() => setSelectedId(selected ? null : p.id)}
                onConfirm={() => onPin(group, p)}
                onCancel={() => setSelectedId(null)}
              />
            </li>
          );
        })}
      </ul>
    </li>
  );
}

function PinRow({
  pin, already, selected, onSelect, onConfirm, onCancel,
}: {
  pin: WidgetDashboardPin;
  already: boolean;
  selected: boolean;
  onSelect: () => void;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const label =
    pin.display_label ?? pin.envelope?.display_label ?? pin.tool_name;
  const integration =
    pin.tool_name.includes("-") ? pin.tool_name.split("-")[0] : pin.tool_name;

  return (
    <div
      className={[
        "rounded-md border transition-colors",
        selected ? "border-accent/50 bg-surface" : "border-transparent bg-surface",
        already && "opacity-70",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button
        type="button"
        onClick={onSelect}
        disabled={already}
        aria-disabled={already}
        aria-expanded={selected}
        title={already ? "Already on this dashboard" : undefined}
        className={[
          "group flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors rounded-md",
          already && "cursor-not-allowed",
          !already && !selected && "hover:bg-surface-overlay",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="flex-1 min-w-0">
          <div className={"truncate text-[12px] font-medium " + (already ? "text-text-muted" : "text-text")}>
            {label}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-text-dim">
            <span className="rounded bg-surface-overlay px-1 py-px uppercase tracking-wider">
              {integration}
            </span>
          </div>
        </div>
        {already ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
            <CheckCircle2 size={10} /> Pinned
          </span>
        ) : (
          <ChevronDown
            size={13}
            className={
              "shrink-0 text-text-dim transition-transform "
              + (selected ? "rotate-180 text-accent" : "group-hover:text-text")
            }
          />
        )}
      </button>
      {selected && !already && (
        <PreviewPanel
          envelope={pin.envelope}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      )}
    </div>
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

function RecentCallsTab({
  loaded,
  loadError,
  query,
  existingIdentities,
  scoped,
  onPin,
}: {
  loaded: RecentCall[] | null;
  loadError: string | null;
  query: string;
  existingIdentities: Set<string>;
  scoped: boolean;
  onPin: (call: RecentCall) => Promise<void>;
}) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const filtered = useMemo(() => {
    if (!loaded) return [];
    const q = query.trim().toLowerCase();
    if (!q) return loaded;
    return loaded.filter((c) => {
      const label = (c.display_label ?? c.envelope?.display_label ?? c.tool_name).toLowerCase();
      if (label.includes(q)) return true;
      if (c.tool_name.toLowerCase().includes(q)) return true;
      if (c.channel_name?.toLowerCase().includes(q)) return true;
      return false;
    });
  }, [loaded, query]);

  if (loadError) {
    return (
      <p className="p-5 text-[12px] text-danger">
        Failed to load recent calls: {loadError}
      </p>
    );
  }
  if (loaded === null) {
    return (
      <div className="space-y-2 p-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-12 animate-pulse rounded-md bg-surface-overlay/40" />
        ))}
      </div>
    );
  }
  if (filtered.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <div className="rounded-full bg-surface-overlay p-3">
          <Clock size={16} className="text-text-dim" />
        </div>
        <p className="text-[13px] font-medium text-text">
          {query ? "No matches" : "No recent widget calls"}
        </p>
        <p className="max-w-[260px] text-[11px] text-text-muted">
          {query
            ? "Try a different tool or widget name."
            : scoped
              ? "Run any widget-returning tool in this channel, then come back here."
              : "Run any widget-returning tool in a channel, then come back here."}
        </p>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-surface-border">
      {filtered.map((call) => {
        const identity = envelopeIdentityKey(call.tool_name, call.envelope);
        const already = existingIdentities.has(identity);
        const selected = selectedId === call.id;
        return (
          <li key={call.id} className="px-3 py-1.5">
            <RecentCallRow
              call={call}
              already={already}
              selected={selected}
              showChannel={!scoped}
              onSelect={() => setSelectedId(selected ? null : call.id)}
              onConfirm={() => onPin(call)}
              onCancel={() => setSelectedId(null)}
            />
          </li>
        );
      })}
    </ul>
  );
}

function RecentCallRow({
  call,
  already,
  selected,
  showChannel,
  onSelect,
  onConfirm,
  onCancel,
}: {
  call: RecentCall;
  already: boolean;
  selected: boolean;
  showChannel: boolean;
  onSelect: () => void;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const label = call.display_label ?? call.envelope?.display_label ?? call.tool_name;
  const integration = call.tool_name.includes("-")
    ? call.tool_name.split("-")[0]
    : call.tool_name;

  return (
    <div
      className={[
        "rounded-md border transition-colors",
        selected ? "border-accent/50 bg-surface" : "border-transparent bg-surface",
        already && "opacity-70",
      ]
        .filter(Boolean)
        .join(" ")}
    >
      <button
        type="button"
        onClick={onSelect}
        disabled={already}
        aria-disabled={already}
        aria-expanded={selected}
        title={already ? "Already on this dashboard" : undefined}
        className={[
          "group flex w-full items-center gap-2.5 px-3 py-2 text-left transition-colors rounded-md",
          already && "cursor-not-allowed",
          !already && !selected && "hover:bg-surface-overlay",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <div className="flex-1 min-w-0">
          <div className={"truncate text-[12px] font-medium " + (already ? "text-text-muted" : "text-text")}>
            {label}
          </div>
          <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-text-dim">
            <span className="rounded bg-surface-overlay px-1 py-px uppercase tracking-wider">
              {integration}
            </span>
            {showChannel && call.channel_name && (
              <span className="truncate">#{call.channel_name}</span>
            )}
          </div>
        </div>
        {already ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
            <CheckCircle2 size={10} /> Pinned
          </span>
        ) : (
          <ChevronDown
            size={13}
            className={
              "shrink-0 text-text-dim transition-transform "
              + (selected ? "rotate-180 text-accent" : "group-hover:text-text")
            }
          />
        )}
      </button>
      {selected && !already && (
        <PreviewPanel
          envelope={call.envelope}
          onConfirm={onConfirm}
          onCancel={onCancel}
        />
      )}
    </div>
  );
}

/** Shared rendered-widget preview + confirm/cancel footer. Used by both the
 *  Recent-calls and From-channel flows so the click-to-preview-then-confirm
 *  gesture looks identical in each tab. */
function PreviewPanel({
  envelope,
  onConfirm,
  onCancel,
}: {
  envelope: ToolResultEnvelope;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const t = useThemeTokens();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleConfirm = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-surface-border/70 px-3 py-2">
      <div className="max-h-[280px] overflow-y-auto rounded-md bg-surface-overlay/40 p-2">
        <RichToolResult envelope={envelope} dispatcher={NOOP_DISPATCHER} t={t} />
      </div>
      {error && (
        <div className="mt-2 rounded-md border border-danger/30 bg-danger/10 px-2 py-1 text-[11px] text-danger">
          {error}
        </div>
      )}
      <div className="mt-2 flex items-center justify-end gap-2">
        <button
          type="button"
          onClick={onCancel}
          disabled={busy}
          className="rounded-md border border-surface-border px-2.5 py-1 text-[11px] font-medium text-text-muted hover:bg-surface-overlay disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={handleConfirm}
          disabled={busy}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1 text-[11px] font-medium text-white hover:opacity-90 disabled:opacity-50"
        >
          {busy ? <Loader2 size={11} className="animate-spin" /> : <Pin size={11} />}
          Add to dashboard
        </button>
      </div>
    </div>
  );
}
