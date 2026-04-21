/** Library tab — the ONE pinnable-widget surface. Unifies five scopes:
 *
 *   1. ``core``        — widget://core/<name>/ (ships with the app)
 *   2. ``integration`` — integrations/<id>/widgets/ (per-integration)
 *   3. ``bot``         — widget://bot/<name>/ (this bot's private library)
 *   4. ``workspace``   — widget://workspace/<name>/ (shared library)
 *   5. ``channel``     — channel workspace .html files (when scoped)
 *
 *  Before unification there were two overlapping tabs ("Library" + "HTML
 *  widgets") with different backends. Integration-shipped widgets showed
 *  only in one tab; bot-authored widgets only in the other. Tool-renderer
 *  template entries polluted the Library with unpinnable "widgets" (can't
 *  pin ``get_task_result`` without an id). Unified endpoint filters both.
 *
 *  Pin envelopes, per scope:
 *   - core/bot/workspace → ``source_kind: "library"`` + ``source_library_ref``
 *   - integration       → ``source_kind: "integration"`` + ``source_integration_id`` + ``source_path``
 *   - channel           → ``source_kind: "channel"`` + ``source_channel_id`` + ``source_path``
 */
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  Bot as BotIcon,
  CheckCircle2,
  ChevronDown,
  FileCode,
  Hash,
  Loader2,
  Package,
  Pin,
  Plug,
  Search,
  Users,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import type {
  ToolResultEnvelope,
  WidgetLibraryCatalog,
  WidgetLibraryEntry,
} from "@/src/types/api";
import { useThemeTokens } from "@/src/theme/tokens";
import { RichToolResult } from "@/src/components/chat/RichToolResult";
import type { WidgetActionDispatcher } from "@/src/components/chat/renderers/ComponentRenderer";

const HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive";

const NOOP_DISPATCHER: WidgetActionDispatcher = {
  dispatchAction: async () => ({ envelope: null, apiResponse: null }),
};

export type PinScope = { kind: "user" } | { kind: "bot"; botId: string };

export interface LibraryPinPayload {
  entry: WidgetLibraryEntry;
  envelope: ToolResultEnvelope;
  botId: string | null;
}

type ScopeFilter = "all" | "core" | "integration" | "bot" | "workspace" | "channel";

interface Props {
  query: string;
  pinScope: PinScope;
  /** Channel id when pinning to a channel dashboard. Surfaces
   *  channel-workspace HTML widgets under the "Channel" section. */
  scopeChannelId?: string | null;
  existingRefs: Set<string>;
  onPin: (payload: LibraryPinPayload) => Promise<void>;
}

/** Identity key for any Library-sourced pin. Handles all five scopes so
 *  dedup works across the unified tab — library scopes key off
 *  ``source_library_ref``; scanner scopes key off ``source_kind::path``
 *  (same shape used by the old HTML-widgets tab's pinIdentity). */
export function libraryPinIdentity(envelope: ToolResultEnvelope): string | null {
  const ref = envelope.source_library_ref;
  if (typeof ref === "string" && ref) return `library:${ref}`;
  const kind = envelope.source_kind;
  const path = envelope.source_path;
  if (!path) return null;
  if (kind === "builtin") return `builtin::${path}`;
  if (kind === "integration" && envelope.source_integration_id) {
    return `integration::${envelope.source_integration_id}::${path}`;
  }
  if (kind === "channel" && envelope.source_channel_id) {
    return `channel::${envelope.source_channel_id}::${path}`;
  }
  return null;
}

/** Stable React key for a row. Unique across all scopes. */
function entryKey(e: WidgetLibraryEntry): string {
  if (e.scope === "integration") return `integration:${e.integration_id ?? ""}:${e.path ?? e.name}`;
  if (e.scope === "channel") return `channel:${e.channel_id ?? ""}:${e.path ?? e.name}`;
  return `${e.scope}/${e.name}`;
}

/** Dedup identity — matches what ``libraryPinIdentity`` computes against
 *  an existing pin's envelope, so rows whose widget is already pinned dim. */
function entryIdentity(e: WidgetLibraryEntry): string {
  if (e.scope === "integration") {
    return `integration::${e.integration_id ?? ""}::${e.path ?? ""}`;
  }
  if (e.scope === "channel") {
    return `channel::${e.channel_id ?? ""}::${e.path ?? ""}`;
  }
  return `library:${e.scope}/${e.name}`;
}

export function envelopeForLibraryEntry(
  entry: WidgetLibraryEntry,
  botId: string | null,
): ToolResultEnvelope {
  const label = entry.display_label ?? entry.name;
  const base = {
    content_type: HTML_INTERACTIVE_CT,
    body: "",
    plain_body: entry.description ?? label,
    display: "inline",
    display_label: label,
    source_bot_id: botId,
  } as ToolResultEnvelope;

  if (entry.scope === "integration") {
    return {
      ...base,
      source_kind: "integration",
      source_integration_id: entry.integration_id ?? null,
      source_path: entry.path ?? null,
    } as ToolResultEnvelope;
  }
  if (entry.scope === "channel") {
    return {
      ...base,
      source_kind: "channel",
      source_channel_id: entry.channel_id ?? null,
      source_path: entry.path ?? null,
    } as ToolResultEnvelope;
  }
  // widget:// scopes (core / bot / workspace) — library_ref path.
  return {
    ...base,
    source_kind: "library",
    source_library_ref: `${entry.scope}/${entry.name}`,
  } as ToolResultEnvelope;
}

export function LibraryWidgetsTab({
  query,
  pinScope,
  scopeChannelId,
  existingRefs,
  onPin,
}: Props) {
  const [catalog, setCatalog] = useState<WidgetLibraryCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");

  const botId = pinScope.kind === "bot" ? pinScope.botId : null;

  useEffect(() => {
    let cancelled = false;
    setCatalog(null);
    setError(null);
    const qs = new URLSearchParams();
    if (botId) qs.set("bot_id", botId);
    if (scopeChannelId) qs.set("channel_id", scopeChannelId);
    apiFetch<WidgetLibraryCatalog>(
      `/api/v1/widgets/library-widgets${qs.toString() ? `?${qs}` : ""}`,
    )
      .then((resp) => { if (!cancelled) setCatalog(resp); })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [botId, scopeChannelId]);

  const totals = useMemo(() => {
    if (!catalog) return { core: 0, integration: 0, bot: 0, workspace: 0, channel: 0, all: 0 };
    const c = catalog.core.length;
    const i = catalog.integration.length;
    const b = catalog.bot.length;
    const w = catalog.workspace.length;
    const ch = catalog.channel.length;
    return { core: c, integration: i, bot: b, workspace: w, channel: ch, all: c + i + b + w + ch };
  }, [catalog]);

  const q = query.trim().toLowerCase();
  const match = (e: WidgetLibraryEntry) => {
    if (!q) return true;
    if (e.name.toLowerCase().includes(q)) return true;
    if ((e.display_label ?? "").toLowerCase().includes(q)) return true;
    if ((e.description ?? "").toLowerCase().includes(q)) return true;
    if ((e.tags ?? []).some((t) => t.toLowerCase().includes(q))) return true;
    return false;
  };

  const showCore = scopeFilter === "all" || scopeFilter === "core";
  const showIntegration = scopeFilter === "all" || scopeFilter === "integration";
  const showBot = scopeFilter === "all" || scopeFilter === "bot";
  const showWs = scopeFilter === "all" || scopeFilter === "workspace";
  const showChannel = scopeFilter === "all" || scopeFilter === "channel";

  if (error) {
    return (
      <p className="p-5 text-[12px] text-danger">
        Failed to load library: {error}
      </p>
    );
  }
  if (catalog === null) {
    return (
      <div className="space-y-2 p-4">
        {[0, 1, 2].map((i) => (
          <div key={i} className="h-14 animate-pulse rounded-md bg-surface-overlay/40" />
        ))}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex flex-wrap items-center gap-1.5 rounded-md bg-surface px-1.5 py-1 text-[11px]">
        <ScopeChip
          label={`All (${totals.all})`}
          active={scopeFilter === "all"}
          onClick={() => setScopeFilter("all")}
        />
        <ScopeChip
          icon={<Package size={10} />}
          label={`Core (${totals.core})`}
          active={scopeFilter === "core"}
          onClick={() => setScopeFilter("core")}
        />
        <ScopeChip
          icon={<Plug size={10} />}
          label={`Integrations (${totals.integration})`}
          active={scopeFilter === "integration"}
          onClick={() => setScopeFilter("integration")}
        />
        <ScopeChip
          icon={<BotIcon size={10} />}
          label={`Bot (${totals.bot})`}
          active={scopeFilter === "bot"}
          onClick={() => setScopeFilter("bot")}
          disabled={!botId && totals.bot === 0}
        />
        <ScopeChip
          icon={<Users size={10} />}
          label={`Workspace (${totals.workspace})`}
          active={scopeFilter === "workspace"}
          onClick={() => setScopeFilter("workspace")}
          disabled={!botId && totals.workspace === 0}
        />
        {scopeChannelId && (
          <ScopeChip
            icon={<Hash size={10} />}
            label={`Channel (${totals.channel})`}
            active={scopeFilter === "channel"}
            onClick={() => setScopeFilter("channel")}
          />
        )}
      </div>

      {!botId && (
        <div className="flex items-start gap-2 rounded-md bg-accent/5 px-3 py-2 text-[11px] text-text-muted">
          <AlertTriangle size={12} className="mt-0.5 shrink-0 text-accent/70" />
          <span>
            Pick a bot above to see its private <span className="font-mono">bot/</span> and
            shared <span className="font-mono">workspace/</span> libraries. Core widgets are
            always visible.
          </span>
        </div>
      )}

      <div className="flex flex-col gap-3">
        {showCore && (
          <Section
            icon={<Package size={13} className="text-accent" />}
            title="Core"
            subtitle="Ship with the app — reference widgets and chip templates"
            entries={catalog.core.filter(match)}
            botId={botId}
            existingRefs={existingRefs}
            onPin={onPin}
          />
        )}
        {showIntegration && (
          <Section
            icon={<Plug size={13} className="text-accent" />}
            title="Integrations"
            subtitle="Widgets shipped by enabled integrations (Frigate, OpenWeather, …)"
            entries={catalog.integration.filter(match)}
            botId={botId}
            existingRefs={existingRefs}
            onPin={onPin}
            emptyHint="No integration-shipped widgets on this instance."
          />
        )}
        {showBot && (
          <Section
            icon={<BotIcon size={13} className="text-accent" />}
            title="Bot library"
            subtitle={
              botId
                ? "Widgets this bot has authored under widget://bot/…"
                : "Pick a bot above to reveal this scope"
            }
            entries={catalog.bot.filter(match)}
            botId={botId}
            existingRefs={existingRefs}
            onPin={onPin}
            emptyHint={
              botId
                ? "No bot-authored library widgets yet. Ask the bot: 'save this into your library'."
                : null
            }
          />
        )}
        {showWs && (
          <Section
            icon={<Users size={13} className="text-accent" />}
            title="Workspace library"
            subtitle={
              botId
                ? "Widgets shared across every bot in this workspace"
                : "Pick a bot above to reveal this scope"
            }
            entries={catalog.workspace.filter(match)}
            botId={botId}
            existingRefs={existingRefs}
            onPin={onPin}
            emptyHint={
              botId
                ? "Empty. Needs a shared workspace — bots in a shared workspace can author under widget://workspace/…"
                : null
            }
          />
        )}
        {showChannel && scopeChannelId && (
          <Section
            icon={<Hash size={13} className="text-accent" />}
            title="Channel workspace"
            subtitle="HTML widgets dropped into this channel's workspace"
            entries={catalog.channel.filter(match)}
            botId={botId}
            existingRefs={existingRefs}
            onPin={onPin}
            emptyHint="Drop an HTML file under this channel's workspace (or ask the bot: 'save this widget to the channel')."
          />
        )}
        {totals.all === 0 && (
          <p className="px-2 py-6 text-center text-[12px] text-text-muted">
            No library widgets available.
          </p>
        )}
      </div>
    </div>
  );
}

function ScopeChip({
  label, active, onClick, icon, disabled,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
  icon?: React.ReactNode;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className={[
        "inline-flex items-center gap-1 rounded px-2 py-1 transition-colors",
        active
          ? "bg-accent/15 text-accent"
          : "text-text-muted hover:bg-surface-overlay hover:text-text",
        disabled && "cursor-not-allowed opacity-50",
      ].filter(Boolean).join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

function Section({
  icon, title, subtitle, entries, botId, existingRefs, onPin, emptyHint,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  entries: WidgetLibraryEntry[];
  botId: string | null;
  existingRefs: Set<string>;
  onPin: (payload: LibraryPinPayload) => Promise<void>;
  emptyHint?: string | null;
}) {
  return (
    <div className="overflow-hidden rounded-md bg-surface">
      <div className="flex items-baseline gap-2 px-3 py-2">
        {icon}
        <span className="text-[12px] font-semibold text-text">{title}</span>
        <span className="text-[11px] text-text-dim">· {subtitle}</span>
        <span className="ml-auto text-[10px] text-text-dim">
          {entries.length} widget{entries.length === 1 ? "" : "s"}
        </span>
      </div>
      {entries.length === 0 && emptyHint && (
        <p className="px-3 pb-3 text-[11px] text-text-dim">
          {emptyHint}
        </p>
      )}
      {entries.length > 0 && (
        <ul className="divide-y divide-surface-border/40">
          {entries.map((e) => (
            <LibraryRow
              key={entryKey(e)}
              entry={e}
              botId={botId}
              already={existingRefs.has(entryIdentity(e)) }
              onPin={onPin}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function LibraryRow({
  entry, botId, already, onPin,
}: {
  entry: WidgetLibraryEntry;
  botId: string | null;
  already: boolean;
  onPin: (payload: LibraryPinPayload) => Promise<void>;
}) {
  const [expanded, setExpanded] = useState(false);
  const label = entry.display_label ?? entry.name;
  // widget:// scopes use a library_ref path; scanner scopes surface the
  // actual on-disk path instead. Both monospaced so they read as identifiers.
  const provenance =
    entry.scope === "integration"
      ? `integrations/${entry.integration_id ?? "?"}/widgets/${entry.path ?? ""}`
      : entry.scope === "channel"
        ? `channel:${entry.channel_id?.slice(0, 8) ?? ""}/${entry.path ?? ""}`
        : `widget://${entry.scope}/${entry.name}`;

  return (
    <li className={[
      "transition-colors",
      already && "opacity-70",
      !already && expanded && "bg-surface-overlay/40",
    ].filter(Boolean).join(" ")}>
      <button
        type="button"
        onClick={() => !already && setExpanded((v) => !v)}
        disabled={already}
        aria-expanded={expanded}
        className={[
          "group flex w-full items-start gap-3 px-4 py-3 text-left transition-colors",
          already ? "cursor-not-allowed" : "hover:bg-surface-overlay/60",
        ].join(" ")}
      >
        <FileCode size={16} className="mt-0.5 shrink-0 text-accent" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate text-[13px] font-medium text-text">
              {label}
            </span>
            {entry.version && entry.version !== "0.0.0" && (
              <span className="text-[11px] text-text-dim">v{entry.version}</span>
            )}
            <span
              className={[
                "inline-flex items-center gap-0.5 rounded px-1 py-px text-[10px] font-medium uppercase tracking-wider",
                entry.format === "suite"
                  ? "bg-warning/15 text-warning"
                  : "bg-surface-overlay text-text-muted",
              ].join(" ")}
              title={`Bundle format: ${entry.format}`}
            >
              {entry.format}
            </span>
          </div>
          {entry.description && (
            <p className="mt-0.5 text-[12px] text-text-muted">
              {entry.description}
            </p>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-text-dim">
            <span className="font-mono truncate max-w-full">{provenance}</span>
            {entry.scope === "integration" && entry.integration_id && (
              <span className="rounded bg-accent/10 px-1 py-px text-accent">
                {entry.integration_id}
              </span>
            )}
            {entry.is_loose && (
              <span className="rounded bg-warning/15 px-1 py-px text-warning" title="Outside a widgets/ dir — detected via window.spindrel reference">
                loose
              </span>
            )}
            {(entry.tags ?? []).slice(0, 4).map((t) => (
              <span key={t} className="rounded bg-surface-overlay px-1 py-px">
                #{t}
              </span>
            ))}
          </div>
        </div>
        {already ? (
          <span className="inline-flex shrink-0 items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
            <CheckCircle2 size={10} /> Pinned
          </span>
        ) : (
          <ChevronDown
            size={13}
            className={[
              "shrink-0 text-text-dim transition-transform",
              expanded && "rotate-180 text-accent",
            ].filter(Boolean).join(" ")}
          />
        )}
      </button>
      {expanded && !already && (
        <PreviewPanel
          entry={entry}
          botId={botId}
          onConfirm={async () => {
            await onPin({
              entry,
              envelope: envelopeForLibraryEntry(entry, botId),
              botId,
            });
          }}
          onCancel={() => setExpanded(false)}
        />
      )}
    </li>
  );
}

function PreviewPanel({
  entry, botId, onConfirm, onCancel,
}: {
  entry: WidgetLibraryEntry;
  botId: string | null;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const t = useThemeTokens();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const envelope = useMemo(
    () => envelopeForLibraryEntry(entry, botId),
    [entry, botId],
  );
  // ``bot`` and ``workspace`` scopes need a bot_id for the content endpoint.
  // ``core`` works without one — surface the gap as a note rather than an
  // interactive preview so the user understands why.
  const needsBot = entry.scope !== "core";
  const canPreview = !needsBot || !!botId;

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
    <div className="border-t border-surface-border/50 px-4 py-3">
      <div className="max-h-[320px] overflow-y-auto rounded-md bg-surface-overlay/40 p-2">
        {canPreview ? (
          <RichToolResult envelope={envelope} dispatcher={NOOP_DISPATCHER} t={t} />
        ) : (
          <p className="p-4 text-center text-[12px] text-text-muted">
            Preview needs a bot context — pick a bot above to load this widget.
          </p>
        )}
      </div>
      {error && (
        <div className="mt-2 rounded-md bg-danger/10 px-2 py-1 text-[11px] text-danger">
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
          disabled={busy || (needsBot && !botId)}
          className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1 text-[11px] font-medium text-white hover:opacity-90 disabled:opacity-50"
          title={needsBot && !botId ? "Pick a bot above first" : undefined}
        >
          {busy ? <Loader2 size={11} className="animate-spin" /> : <Pin size={11} />}
          Add to dashboard
        </button>
      </div>
    </div>
  );
}
