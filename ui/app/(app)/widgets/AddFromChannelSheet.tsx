import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { X, CheckCircle2, ChevronDown, Loader2, Wrench, Pin, Clock } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useBots } from "@/src/api/hooks/useBots";
import { useChannel } from "@/src/api/hooks/useChannels";
import { envelopeIdentityKey } from "@/src/stores/pinnedWidgets";
import { toast } from "@/src/stores/toast";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import { useThemeTokens } from "@/src/theme/tokens";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";
import type {
  ToolResultEnvelope,
  WidgetDashboardPin,
} from "@/src/types/api";
import { PinScopePicker } from "./PinScopePicker";
import {
  WidgetLibrary,
  libraryPinIdentity,
} from "./WidgetLibrary";
import { WidgetPresetsPane } from "./WidgetPresetsPane";
import { WidgetBuilderSearchBar } from "./WidgetBuilderSearchBar";

/** Previews are read-only — widget `callTool` dispatches inside the sheet
 *  don't mutate anything. A no-op dispatcher makes that explicit. */
const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

interface Props {
  open: boolean;
  onClose: () => void;
  tab: Tab;
  onTabChange: (tab: Tab) => void;
  query: string;
  onQueryChange: (query: string) => void;
  /** Name of the active dashboard — used in the success toast. */
  dashboardName?: string;
  /** Called with the new pin's id after a successful add. The dashboard page
   *  uses this to scroll-into-view + accent-flash the new tile. */
  onPinned?: (pinId: string) => void;
  /** When set, the "Recent calls" tab pre-filters to calls in this channel
   *  and becomes the default tab (channel dashboards open here most often). */
  scopeChannelId?: string | null;
  selectedPresetId?: string;
  onSelectedPresetIdChange?: (presetId: string) => void;
  presetStep?: "catalog" | "configure" | "preview";
  onPresetStepChange?: (step: "catalog" | "configure" | "preview") => void;
}

type Tab = "presets" | "channel" | "recent" | "library" | "suites" | "build";

interface SuiteEntry {
  suite_id: string;
  name: string;
  description: string;
  members: string[];
  schema_version: number;
}

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
  tab,
  onTabChange,
  query,
  onQueryChange,
  dashboardName,
  onPinned,
  scopeChannelId,
  selectedPresetId,
  onSelectedPresetIdChange,
  presetStep,
  onPresetStepChange,
}: Props) {
  // "From channel" is the promote-channel-pin-upward tab — only meaningful
  // on the global (non-channel) dashboard. Inside a channel dashboard it's
  // redundant (you ARE that channel's board) so the tab hides, and Recent
  // calls becomes the natural landing.
  const showChannelTab = !scopeChannelId;
  const pins = useDashboardPinsStore((s) => s.pins);
  const pinWidget = useDashboardPinsStore((s) => s.pinWidget);
  const pinSuite = useDashboardPinsStore((s) => s.pinSuite);

  // Single batch query: channel dashboards with ≥1 pin, grouped and named.
  // Replaces the old per-channel fan-out against ``channel.config.pinned_widgets``
  // (migration 213 moved that storage into ``widget_dashboard_pins``).
  const [loaded, setLoaded] = useState<ChannelPinsGroup[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  // Recent tool-call envelopes — filtered to scopeChannelId when provided.
  const [recent, setRecent] = useState<RecentCall[] | null>(null);
  const [recentError, setRecentError] = useState<string | null>(null);

  // Discoverable widget suites (groups of bundles that share a dashboard-scoped DB).
  const [suites, setSuites] = useState<SuiteEntry[] | null>(null);
  const [suitesError, setSuitesError] = useState<string | null>(null);
  const [pendingSuiteId, setPendingSuiteId] = useState<string | null>(null);

  // Auth scope for adhoc interactive-HTML pins (HTML widgets tab + Suites tab).
  // - "user": iframe uses the viewer's own bearer → per-viewer credentials.
  // - {bot: id}: iframe mints a bot-scoped JWT → every viewer sees the same
  //   data through the bot's ceiling (lets a pin expose something the viewer
  //   couldn't read directly). Default "user" — matches the per-dashboard
  //   mental model. No scope picker on "Recent calls" / "From channel" —
  //   those pins already carry an emitting bot via the envelope.
  const [pinScope, setPinScope] = useState<
    { kind: "user" } | { kind: "bot"; botId: string }
  >({ kind: "user" });
  const { data: allBots } = useBots();
  const { data: scopedChannel } = useChannel(scopeChannelId ?? undefined);
  const libraryBotId =
    pinScope.kind === "bot" ? pinScope.botId : scopedChannel?.bot_id ?? null;

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

  // Fetch installed suites. Cheap endpoint (file-mtime cached server-side).
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    setSuites(null);
    setSuitesError(null);
    apiFetch<{ suites: SuiteEntry[] }>("/api/v1/widgets/suites")
      .then((resp) => { if (!cancelled) setSuites(resp.suites ?? []); })
      .catch((e) => {
        if (!cancelled) setSuitesError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [open]);

  const existingIdentities = useMemo(
    () => new Set(pins.map((p) => envelopeIdentityKey(p.tool_name, p.envelope, p.widget_config ?? null))),
    [pins],
  );

  // Identity set for any Library-sourced pin. ``libraryPinIdentity`` is
  // scope-aware — widget:// scopes → ``library:<scope>/<name>``; scanner
  // scopes (integration / channel) → the ``<source_kind>::path`` identity
  // used by the old HtmlWidgetsTab so cross-tab dedup still works.
  const existingLibraryRefs = useMemo(() => {
    const set = new Set<string>();
    for (const p of pins) {
      const id = libraryPinIdentity(p.envelope);
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
    <div className="fixed inset-0 z-[10030] flex items-end justify-center">
      {/* Backdrop */}
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 bg-black/60 backdrop-blur-[2px]"
      />
      <div className="relative z-10 flex h-[min(88dvh,980px)] w-full max-w-[min(1600px,calc(100vw-24px))] flex-col overflow-hidden bg-surface-raised shadow-[0_8px_32px_rgba(0,0,0,0.4)]">
        <header className="flex items-start justify-between gap-4 px-6 pt-5 pb-2">
          <div>
            <h2 className="text-base font-bold text-text">Widget builder</h2>
            <p className="mt-0.5 text-[11px] text-text-muted">
              Browse, configure, preview, and pin widgets into {dashboardName ?? "this dashboard"}.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-md text-text-muted transition-colors hover:bg-surface-overlay hover:text-text"
            aria-label="Close"
            title="Close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex flex-wrap gap-1 px-5 pt-1 pb-0">
          <TabButton active={tab === "presets"} onClick={() => onTabChange("presets")}>
            Presets
          </TabButton>
          <TabButton active={tab === "recent"} onClick={() => onTabChange("recent")}>
            Recent calls
          </TabButton>
          {showChannelTab && (
            <TabButton active={tab === "channel"} onClick={() => onTabChange("channel")}>
              From channel
            </TabButton>
          )}
          <TabButton active={tab === "library"} onClick={() => onTabChange("library")}>
            Library
          </TabButton>
          {suites && suites.length > 0 && (
            <TabButton active={tab === "suites"} onClick={() => onTabChange("suites")}>
              Suites
            </TabButton>
          )}
          <TabButton active={tab === "build"} onClick={() => onTabChange("build")}>
            Authoring
          </TabButton>
        </div>

        {(tab === "suites" || tab === "library") && (
          <div className="mx-5 mt-2">
            <PinScopePicker
              scope={pinScope}
              onChange={setPinScope}
              bots={allBots ?? null}
            />
          </div>
        )}

        {(tab === "channel" || tab === "library" || tab === "presets") && (
          <WidgetBuilderSearchBar
            className="px-5 py-3"
            value={query}
            onChange={onQueryChange}
            placeholder={
              tab === "library"
                ? "Search library widgets"
                : tab === "presets"
                ? "Search presets"
                : "Search channels or widgets"
            }
          />
        )}

        <div className="flex-1 min-w-0 overflow-x-hidden overflow-y-auto">
          {tab === "presets" && (
            <WidgetPresetsPane
              mode="pin"
              query={query}
              scopeChannelId={scopeChannelId ?? null}
              layout="builder"
              selectedPresetId={selectedPresetId}
              onSelectedPresetIdChange={onSelectedPresetIdChange}
              step={presetStep}
              onStepChange={onPresetStepChange}
              onPinCreated={(pinId) => {
                toast({
                  kind: "success",
                  message: `Added preset to ${dashboardName ?? "dashboard"}`,
                  action: onPinned
                    ? {
                        label: "View",
                        onClick: () => {
                          onPinned(pinId);
                          onClose();
                        },
                      }
                    : undefined,
                });
                onPinned?.(pinId);
              }}
            />
          )}
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
          {tab === "library" && (
            <WidgetLibrary
              mode="pin"
              botEnumeration="single-bot"
              query={query}
              pinScope={pinScope}
              libraryBotId={libraryBotId}
              scopeChannelId={scopeChannelId ?? null}
              existingRefs={existingLibraryRefs}
              onToolRendererPinCreated={(pinId) => {
                toast({
                  kind: "success",
                  message: `Added widget to ${dashboardName ?? "dashboard"}`,
                  action: onPinned
                    ? {
                        label: "View",
                        onClick: () => {
                          onPinned(pinId);
                          onClose();
                        },
                      }
                    : undefined,
                });
                onPinned?.(pinId);
                onClose();
              }}
              onPin={async ({ entry, envelope, botId }) => {
                // Scope determines pin shape. widget:// scopes ride the
                // existing library_ref path; scanner scopes (integration /
                // channel) match what the old HtmlWidgetsTab produced so
                // the renderer + dedup identity stay unchanged.
                let toolArgs: Record<string, unknown>;
                let sourceKind: "adhoc" | "channel" = "adhoc";
                let pinChannelId: string | null = scopeChannelId ?? null;
                if (entry.scope === "integration") {
                  toolArgs = {
                    source: "integration",
                    integration_id: entry.integration_id,
                    path: entry.path,
                  };
                } else if (entry.scope === "channel") {
                  const cid =
                    envelope.source_channel_id ?? entry.channel_id ?? scopeChannelId ?? null;
                  toolArgs = cid && entry.path
                    ? { path: `/workspace/channels/${cid}/${entry.path}` }
                    : { path: entry.path };
                  sourceKind = cid ? "channel" : "adhoc";
                  pinChannelId = cid;
                } else {
                  toolArgs = {
                    library_ref: `${entry.scope}/${entry.name}`,
                  };
                }
                const created = await pinWidget({
                  source_kind: sourceKind,
                  source_channel_id: pinChannelId,
                  source_bot_id: botId,
                  tool_name: "emit_html_widget",
                  tool_args: toolArgs,
                  envelope,
                  display_label: entry.display_label ?? entry.name,
                });
                const label = entry.display_label ?? entry.name;
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
          {tab === "suites" && (
            <SuitesTab
              suites={suites}
              loadError={suitesError}
              pendingSuiteId={pendingSuiteId}
              onPin={async (suite) => {
                setPendingSuiteId(suite.suite_id);
                try {
                  const created = await pinSuite(suite.suite_id, {
                    source_bot_id:
                      pinScope.kind === "bot" ? pinScope.botId : null,
                    source_channel_id: scopeChannelId ?? null,
                  });
                  toast({
                    kind: "success",
                    message: `Pinned ${suite.name} (${created.length} widget${created.length === 1 ? "" : "s"}) to ${dashboardName ?? "dashboard"}`,
                    action: onPinned && created.length > 0
                      ? {
                          label: "View",
                          onClick: () => {
                            onPinned(created[0].id);
                            onClose();
                          },
                        }
                      : undefined,
                  });
                  if (created.length > 0) onPinned?.(created[0].id);
                } catch (err) {
                  toast({
                    kind: "error",
                    message: `Pin suite failed: ${err instanceof Error ? err.message : String(err)}`,
                  });
                } finally {
                  setPendingSuiteId(null);
                }
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
        "relative rounded-md px-2.5 py-1.5 text-[12px] font-medium transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40",
        active
          ? "text-accent"
          : "text-text-muted hover:text-text",
      ].join(" ")}
    >
      {children}
      {active && (
        <span className="absolute -bottom-px left-2 right-2 h-[2px] rounded-full bg-accent" />
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
          const identity = envelopeIdentityKey(p.tool_name, p.envelope, p.widget_config ?? null);
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

function SuitesTab({
  suites,
  loadError,
  pendingSuiteId,
  onPin,
}: {
  suites: SuiteEntry[] | null;
  loadError: string | null;
  pendingSuiteId: string | null;
  onPin: (suite: SuiteEntry) => void;
}) {
  if (loadError) {
    return (
      <div className="p-6 text-[12px] text-text-muted">
        Failed to load suites: {loadError}
      </div>
    );
  }
  if (suites === null) {
    return (
      <div className="flex items-center justify-center p-6 text-[12px] text-text-muted">
        <Loader2 size={13} className="mr-2 animate-spin" /> Loading…
      </div>
    );
  }
  if (suites.length === 0) {
    return (
      <div className="p-6 text-[12px] text-text-muted">
        No widget suites installed on this server.
      </div>
    );
  }
  return (
    <div className="flex flex-col gap-2 p-4">
      <p className="text-[11px] text-text-dim">
        A suite pins several widgets that share a dashboard-scoped SQLite DB — install once, every
        member sees the same data on this dashboard. Other dashboards get their own isolated copy.
      </p>
      {suites.map((suite) => {
        const pending = pendingSuiteId === suite.suite_id;
        return (
          <div
            key={suite.suite_id}
            className="rounded-md bg-surface p-3 shadow-sm"
          >
            <div className="flex items-start justify-between gap-3">
              <div className="flex-1">
                <h3 className="text-[13px] font-semibold text-text">{suite.name}</h3>
                {suite.description && (
                  <p className="mt-0.5 text-[11px] text-text-muted">{suite.description}</p>
                )}
                <p className="mt-1.5 text-[11px] text-text-dim">
                  {suite.members.length} member{suite.members.length === 1 ? "" : "s"}:{" "}
                  {suite.members.join(", ")}
                </p>
              </div>
              <button
                type="button"
                disabled={pending}
                onClick={() => onPin(suite)}
                className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {pending ? (
                  <>
                    <Loader2 size={12} className="animate-spin" /> Pinning…
                  </>
                ) : (
                  <>
                    <Pin size={12} /> Pin suite
                  </>
                )}
              </button>
            </div>
          </div>
        );
      })}
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
