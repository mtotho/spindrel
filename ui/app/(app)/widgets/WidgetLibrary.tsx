/** Unified widget library surface. Replaces the two older tabs:
 *
 *   - Dev Panel ``HtmlWidgetsLibrarySection`` (couldn't see bot scope)
 *   - Add-Widget sheet ``LibraryWidgetsTab`` (required a pin-scoped bot)
 *
 *  One component, two modes (``pin`` | ``browse``) and two bot-enumeration
 *  flavors (``single-bot`` | ``all-bots``). Same rows, filters, and inline
 *  preview everywhere; only the action column differs — Pin button shows in
 *  pin mode and disables when no dashboard target is available.
 *
 *  Top-level tabs split **Pinnable** widgets (core / integration / bot /
 *  workspace / channel — standalone HTML bundles) from **Tool renderers**
 *  (``template.yaml`` packages that render a specific tool's output and
 *  can't be pinned standalone).
 *
 *  Inline preview expands each row with Live / Source / Manifest tabs.
 *  Only one row is expanded at a time — opening another collapses the
 *  previous automatically.
 */
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  Bot as BotIcon,
  CheckCircle2,
  ChevronDown,
  Eye,
  FileCode,
  FileText,
  Hash,
  Loader2,
  Package,
  Pin,
  Plug,
  ScrollText,
  Users,
  Wrench,
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
import { ToolRenderersPane } from "./ToolRenderersPane";

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

type ScopeFilter =
  | "all"
  | "core"
  | "integration"
  | "bot"
  | "workspace"
  | "channel";

type TopTab = "pinnable" | "renderers";

export interface WidgetLibraryProps {
  mode: "pin" | "browse";
  /** Controls bot scope enumeration. ``single-bot`` drives the old
   *  ``?bot_id=`` endpoint (Add Widget sheet). ``all-bots`` hits the
   *  dev-panel variant and surfaces every bot's library grouped by bot. */
  botEnumeration?: "single-bot" | "all-bots";
  /** Pin-mode only. */
  pinScope?: PinScope;
  /** Optional bot context used to enumerate/resolve bot and workspace
   *  libraries when pin auth is still "You". */
  libraryBotId?: string | null;
  scopeChannelId?: string | null;
  existingRefs?: Set<string>;
  onPin?: (payload: LibraryPinPayload) => Promise<void>;
  onToolRendererPinCreated?: (pinId: string) => void;
  /** Optional external filter text (Add Widget sheet has a global search). */
  query?: string;
}

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

function entryKey(e: WidgetLibraryEntry): string {
  if (e.scope === "integration") return `integration:${e.integration_id ?? ""}:${e.path ?? e.name}`;
  if (e.scope === "channel") return `channel:${e.channel_id ?? ""}:${e.path ?? e.name}`;
  if (e.scope === "bot") return `bot:${e.bot_id ?? ""}:${e.name}`;
  return `${e.scope}/${e.name}`;
}

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
  pinBotId: string | null,
  resolutionBotId: string | null,
): ToolResultEnvelope {
  const label = entry.display_label ?? entry.name;
  const sourceBotId = effectiveEntryBotId(entry, pinBotId, resolutionBotId);
  const base = {
    content_type: HTML_INTERACTIVE_CT,
    body: "",
    plain_body: entry.description ?? label,
    display: "inline",
    display_label: label,
    panel_title: entry.panel_title ?? null,
    show_panel_title: entry.show_panel_title ?? null,
    source_bot_id: sourceBotId,
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
  return {
    ...base,
    source_kind: "library",
    source_library_ref: `${entry.scope}/${entry.name}`,
  } as ToolResultEnvelope;
}

function effectiveEntryBotId(
  entry: WidgetLibraryEntry,
  pinBotId: string | null,
  resolutionBotId: string | null,
): string | null {
  if (entry.scope === "bot" || entry.scope === "workspace") {
    return resolutionBotId ?? entry.bot_id ?? null;
  }
  return pinBotId ?? entry.bot_id ?? null;
}

export function WidgetLibrary({
  mode,
  botEnumeration = "single-bot",
  pinScope,
  libraryBotId,
  scopeChannelId,
  existingRefs,
  onPin,
  onToolRendererPinCreated,
  query = "",
}: WidgetLibraryProps) {
  const [catalog, setCatalog] = useState<WidgetLibraryCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");
  const [topTab, setTopTab] = useState<TopTab>("pinnable");
  const [expandedKey, setExpandedKey] = useState<string | null>(null);
  const [localQuery, setLocalQuery] = useState("");
  const effectiveQuery = query || localQuery;

  const pinBotId = pinScope?.kind === "bot" ? pinScope.botId : null;
  const resolutionBotId = pinBotId ?? libraryBotId ?? null;

  useEffect(() => {
    let cancelled = false;
    setCatalog(null);
    setError(null);
    let url: string;
    if (botEnumeration === "all-bots") {
      const qs = new URLSearchParams();
      if (scopeChannelId) qs.set("channel_id", scopeChannelId);
      url = `/api/v1/widgets/library-widgets/all-bots${qs.toString() ? `?${qs}` : ""}`;
    } else {
      const qs = new URLSearchParams();
      if (resolutionBotId) qs.set("bot_id", resolutionBotId);
      if (scopeChannelId) qs.set("channel_id", scopeChannelId);
      url = `/api/v1/widgets/library-widgets${qs.toString() ? `?${qs}` : ""}`;
    }
    apiFetch<WidgetLibraryCatalog>(url)
      .then((resp) => { if (!cancelled) setCatalog(resp); })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [resolutionBotId, scopeChannelId, botEnumeration]);

  const q = effectiveQuery.trim().toLowerCase();
  const match = (e: WidgetLibraryEntry) => {
    if (!q) return true;
    if (e.name.toLowerCase().includes(q)) return true;
    if ((e.display_label ?? "").toLowerCase().includes(q)) return true;
    if ((e.description ?? "").toLowerCase().includes(q)) return true;
    if ((e.tags ?? []).some((t) => t.toLowerCase().includes(q))) return true;
    if ((e.bot_name ?? "").toLowerCase().includes(q)) return true;
    return false;
  };

  const totals = useMemo(() => {
    if (!catalog) return { core: 0, integration: 0, bot: 0, workspace: 0, channel: 0, all: 0 };
    const c = catalog.core.length;
    const i = catalog.integration.length;
    const b = catalog.bot.length;
    const w = catalog.workspace.length;
    const ch = catalog.channel.length;
    return { core: c, integration: i, bot: b, workspace: w, channel: ch, all: c + i + b + w + ch };
  }, [catalog]);

  const showCore = scopeFilter === "all" || scopeFilter === "core";
  const showIntegration = scopeFilter === "all" || scopeFilter === "integration";
  const showBot = scopeFilter === "all" || scopeFilter === "bot";
  const showWs = scopeFilter === "all" || scopeFilter === "workspace";
  const showChannel = scopeFilter === "all" || scopeFilter === "channel";

  const allowPin = mode === "pin" && !!onPin;

  const botsByBucket = useMemo(() => {
    if (!catalog) return new Map<string, WidgetLibraryEntry[]>();
    const by = new Map<string, WidgetLibraryEntry[]>();
    for (const entry of catalog.bot) {
      const key = entry.bot_id ?? "unknown";
      const arr = by.get(key) ?? [];
      arr.push(entry);
      by.set(key, arr);
    }
    return by;
  }, [catalog]);

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="flex items-center gap-2 border-b border-surface-border/50 px-1 pb-2">
        <TopTabButton
          label={`Pinnable ${catalog ? `(${totals.all})` : ""}`}
          active={topTab === "pinnable"}
          onClick={() => setTopTab("pinnable")}
          icon={<Pin size={11} />}
        />
        <TopTabButton
          label="Tool renderers"
          active={topTab === "renderers"}
          onClick={() => setTopTab("renderers")}
          icon={<Wrench size={11} />}
        />
        {mode === "browse" && !query && (
          <input
            value={localQuery}
            onChange={(e) => setLocalQuery(e.target.value)}
            placeholder="Filter..."
            className="ml-auto w-48 rounded-md bg-surface-overlay px-2 py-1 text-[11px] text-text placeholder-text-dim outline-none focus:ring-1 focus:ring-accent/60"
          />
        )}
      </div>

      {topTab === "pinnable" && (
        <PinnablePane
          catalog={catalog}
          error={error}
          totals={totals}
          scopeFilter={scopeFilter}
          setScopeFilter={setScopeFilter}
          match={match}
          showCore={showCore}
          showIntegration={showIntegration}
          showBot={showBot}
          showWs={showWs}
          showChannel={showChannel}
          pinBotId={pinBotId}
          resolutionBotId={resolutionBotId}
          scopeChannelId={scopeChannelId ?? null}
          botEnumeration={botEnumeration}
          botsByBucket={botsByBucket}
          allowPin={allowPin}
          existingRefs={existingRefs ?? new Set()}
          onPin={onPin}
          expandedKey={expandedKey}
          setExpandedKey={setExpandedKey}
        />
      )}

      {topTab === "renderers" && (
        <ToolRenderersPane
          query={effectiveQuery}
          mode={mode}
          pinScope={pinScope}
          scopeChannelId={scopeChannelId ?? null}
          onPinCreated={onToolRendererPinCreated}
        />
      )}
    </div>
  );
}

function TopTabButton({
  label, active, onClick, icon,
}: { label: string; active: boolean; onClick: () => void; icon?: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[12px] font-medium transition-colors",
        active
          ? "bg-accent/15 text-accent"
          : "text-text-muted hover:bg-surface-overlay hover:text-text",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

function PinnablePane({
  catalog, error, totals, scopeFilter, setScopeFilter, match,
  showCore, showIntegration, showBot, showWs, showChannel,
  pinBotId, resolutionBotId, scopeChannelId, botEnumeration, botsByBucket,
  allowPin, existingRefs, onPin, expandedKey, setExpandedKey,
}: {
  catalog: WidgetLibraryCatalog | null;
  error: string | null;
  totals: { core: number; integration: number; bot: number; workspace: number; channel: number; all: number };
  scopeFilter: ScopeFilter;
  setScopeFilter: (s: ScopeFilter) => void;
  match: (e: WidgetLibraryEntry) => boolean;
  showCore: boolean;
  showIntegration: boolean;
  showBot: boolean;
  showWs: boolean;
  showChannel: boolean;
  pinBotId: string | null;
  resolutionBotId: string | null;
  scopeChannelId: string | null;
  botEnumeration: "single-bot" | "all-bots";
  botsByBucket: Map<string, WidgetLibraryEntry[]>;
  allowPin: boolean;
  existingRefs: Set<string>;
  onPin?: (payload: LibraryPinPayload) => Promise<void>;
  expandedKey: string | null;
  setExpandedKey: (k: string | null) => void;
}) {
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

  const singleBotNoBotPicked =
    botEnumeration === "single-bot" && !resolutionBotId;

  return (
    <>
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
          disabled={singleBotNoBotPicked && totals.bot === 0}
        />
        <ScopeChip
          icon={<Users size={10} />}
          label={`Workspace (${totals.workspace})`}
          active={scopeFilter === "workspace"}
          onClick={() => setScopeFilter("workspace")}
          disabled={singleBotNoBotPicked && totals.workspace === 0}
        />
        {(scopeChannelId || totals.channel > 0) && (
          <ScopeChip
            icon={<Hash size={10} />}
            label={`Channel (${totals.channel})`}
            active={scopeFilter === "channel"}
            onClick={() => setScopeFilter("channel")}
          />
        )}
      </div>

      {singleBotNoBotPicked && (
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
            pinBotId={pinBotId}
            resolutionBotId={resolutionBotId}
            existingRefs={existingRefs}
            allowPin={allowPin}
            onPin={onPin}
            expandedKey={expandedKey}
            setExpandedKey={setExpandedKey}
          />
        )}
        {showIntegration && (
          <Section
            icon={<Plug size={13} className="text-accent" />}
            title="Integrations"
            subtitle="Widgets shipped by enabled integrations"
            entries={catalog.integration.filter(match)}
            pinBotId={pinBotId}
            resolutionBotId={resolutionBotId}
            existingRefs={existingRefs}
            allowPin={allowPin}
            onPin={onPin}
            expandedKey={expandedKey}
            setExpandedKey={setExpandedKey}
            emptyHint="No integration-shipped widgets on this instance."
          />
        )}
        {showBot && botEnumeration === "all-bots" && (
          <>
            {Array.from(botsByBucket.entries()).map(([bId, entries]) => {
              const filtered = entries.filter(match);
              if (filtered.length === 0) return null;
              const botName = entries[0]?.bot_name ?? bId;
              return (
                <Section
                  key={`bot-${bId}`}
                  icon={<BotIcon size={13} className="text-accent" />}
                  title={`Bot library · ${botName}`}
                  subtitle={`widget://bot/… written by ${botName}`}
                  entries={filtered}
                  pinBotId={pinBotId}
                  resolutionBotId={bId}
                  existingRefs={existingRefs}
                  allowPin={allowPin}
                  onPin={onPin}
                  expandedKey={expandedKey}
                  setExpandedKey={setExpandedKey}
                />
              );
            })}
            {botsByBucket.size === 0 && (
              <Section
                icon={<BotIcon size={13} className="text-accent" />}
                title="Bot libraries"
                subtitle="widget://bot/… authored by any bot"
                entries={[]}
                pinBotId={pinBotId}
                resolutionBotId={null}
                existingRefs={existingRefs}
                allowPin={allowPin}
                onPin={onPin}
                expandedKey={expandedKey}
                setExpandedKey={setExpandedKey}
                emptyHint="No bot-authored library widgets yet. Ask a bot: 'save this into your library'."
              />
            )}
          </>
        )}
        {showBot && botEnumeration === "single-bot" && (
          <Section
            icon={<BotIcon size={13} className="text-accent" />}
            title="Bot library"
            subtitle={
              resolutionBotId
                ? "Widgets this bot has authored under widget://bot/…"
                : "Pick a bot above to reveal this scope"
            }
            entries={catalog.bot.filter(match)}
            pinBotId={pinBotId}
            resolutionBotId={resolutionBotId}
            existingRefs={existingRefs}
            allowPin={allowPin}
            onPin={onPin}
            expandedKey={expandedKey}
            setExpandedKey={setExpandedKey}
            emptyHint={
              resolutionBotId
                ? "No bot-authored library widgets yet. Ask the bot: 'save this into your library'."
                : null
            }
          />
        )}
        {showWs && (
          <Section
            icon={<Users size={13} className="text-accent" />}
            title="Workspace library"
            subtitle="widget://workspace/… shared across bots"
            entries={catalog.workspace.filter(match)}
            pinBotId={pinBotId}
            resolutionBotId={resolutionBotId}
            existingRefs={existingRefs}
            allowPin={allowPin}
            onPin={onPin}
            expandedKey={expandedKey}
            setExpandedKey={setExpandedKey}
            emptyHint={
              botEnumeration === "all-bots" || resolutionBotId
                ? "Empty. Needs a shared workspace — bots in a shared workspace can author under widget://workspace/…"
                : null
            }
          />
        )}
        {showChannel && (
          <Section
            icon={<Hash size={13} className="text-accent" />}
            title="Channel workspace"
            subtitle="HTML widgets dropped into a channel's workspace"
            entries={catalog.channel.filter(match)}
            pinBotId={pinBotId}
            resolutionBotId={resolutionBotId}
            existingRefs={existingRefs}
            allowPin={allowPin}
            onPin={onPin}
            expandedKey={expandedKey}
            setExpandedKey={setExpandedKey}
            emptyHint="Drop an HTML file under a channel's workspace (or ask the bot: 'save this widget to the channel')."
          />
        )}
        {totals.all === 0 && (
          <p className="px-2 py-6 text-center text-[12px] text-text-muted">
            No library widgets available.
          </p>
        )}
      </div>
    </>
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
  icon, title, subtitle, entries, pinBotId, resolutionBotId, existingRefs, allowPin, onPin, emptyHint,
  expandedKey, setExpandedKey,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  entries: WidgetLibraryEntry[];
  pinBotId: string | null;
  resolutionBotId: string | null;
  existingRefs: Set<string>;
  allowPin: boolean;
  onPin?: (payload: LibraryPinPayload) => Promise<void>;
  emptyHint?: string | null;
  expandedKey: string | null;
  setExpandedKey: (k: string | null) => void;
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
          {entries.map((e) => {
            const key = entryKey(e);
            return (
              <LibraryRow
                key={key}
                entry={e}
                pinBotId={pinBotId}
                resolutionBotId={resolutionBotId}
                already={existingRefs.has(entryIdentity(e))}
                allowPin={allowPin}
                onPin={onPin}
                expanded={expandedKey === key}
                onToggle={() => setExpandedKey(expandedKey === key ? null : key)}
              />
            );
          })}
        </ul>
      )}
    </div>
  );
}

function LibraryRow({
  entry, pinBotId, resolutionBotId, already, allowPin, onPin, expanded, onToggle,
}: {
  entry: WidgetLibraryEntry;
  pinBotId: string | null;
  resolutionBotId: string | null;
  already: boolean;
  allowPin: boolean;
  onPin?: (payload: LibraryPinPayload) => Promise<void>;
  expanded: boolean;
  onToggle: () => void;
}) {
  const label = entry.display_label ?? entry.name;
  const effectiveBotId = effectiveEntryBotId(entry, pinBotId, resolutionBotId);
  const provenance =
    entry.scope === "integration"
      ? `integrations/${entry.integration_id ?? "?"}/widgets/${entry.path ?? ""}`
      : entry.scope === "channel"
        ? `channel:${entry.channel_id?.slice(0, 8) ?? ""}/${entry.path ?? ""}`
        : `widget://${entry.scope}/${entry.name}`;

  return (
    <li
      className={[
        "transition-colors",
        already && "opacity-70",
        !already && expanded && "bg-surface-overlay/40",
      ].filter(Boolean).join(" ")}
    >
      <button
        type="button"
        onClick={onToggle}
        aria-expanded={expanded}
        className="group flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-overlay/60"
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
            {entry.scope === "bot" && entry.bot_name && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-accent/15 px-1 py-px text-[10px] font-medium text-accent"
                title="Bot-authored via widget://bot/"
              >
                <BotIcon size={9} /> {entry.bot_name}
              </span>
            )}
            {entry.group_kind && entry.group_ref && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-accent/10 px-1 py-px text-[10px] font-medium text-accent"
                title="Related widget group"
              >
                <Boxes size={9} /> {entry.group_kind}:{entry.group_ref}
              </span>
            )}
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
              <span
                className="inline-flex items-center gap-0.5 rounded bg-warning/15 px-1 py-px text-warning"
                title="Outside a widgets/ dir — detected via window.spindrel reference"
              >
                <AlertTriangle size={8} /> loose
              </span>
            )}
            {entry.has_manifest && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-accent/10 px-1 py-px text-accent"
                title="Bundle declares a widget.yaml manifest"
              >
                <ScrollText size={8} /> manifest
              </span>
            )}
            {entry.theme_support && entry.theme_support !== "none" && (
              <span
                className="rounded bg-surface-overlay px-1 py-px"
                title="Supports the widget theme system"
              >
                theme
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
      {expanded && (
        <PreviewPanel
          entry={entry}
          pinBotId={pinBotId}
          resolutionBotId={resolutionBotId}
          allowPin={allowPin && !already}
          onPin={
            allowPin && onPin
              ? async () =>
                  onPin({
                    entry,
                    envelope: envelopeForLibraryEntry(entry, pinBotId, resolutionBotId),
                    botId: effectiveBotId,
                  })
              : undefined
          }
          onClose={onToggle}
        />
      )}
    </li>
  );
}

type PreviewTab = "live" | "source" | "manifest";

function PreviewPanel({
  entry, pinBotId, resolutionBotId, allowPin, onPin, onClose,
}: {
  entry: WidgetLibraryEntry;
  pinBotId: string | null;
  resolutionBotId: string | null;
  allowPin: boolean;
  onPin?: () => Promise<void>;
  onClose: () => void;
}) {
  const t = useThemeTokens();
  const [tab, setTab] = useState<PreviewTab>("live");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const effectiveBotId = effectiveEntryBotId(entry, pinBotId, resolutionBotId);
  const envelope = useMemo(
    () => envelopeForLibraryEntry(entry, pinBotId, resolutionBotId),
    [entry, pinBotId, resolutionBotId],
  );
  const needsBot = entry.scope === "bot" || entry.scope === "workspace";
  const canPreview = !needsBot || !!effectiveBotId;

  const handlePin = async () => {
    if (!onPin) return;
    setBusy(true);
    setError(null);
    try {
      await onPin();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setBusy(false);
    }
  };

  return (
    <div className="border-t border-surface-border/50">
      <div className="flex items-center gap-1 px-3 pt-2">
        <PreviewTabButton
          active={tab === "live"}
          onClick={() => setTab("live")}
          icon={<Eye size={10} />}
          label="Live"
        />
        <PreviewTabButton
          active={tab === "source"}
          onClick={() => setTab("source")}
          icon={<FileCode size={10} />}
          label="Source"
        />
        <PreviewTabButton
          active={tab === "manifest"}
          onClick={() => setTab("manifest")}
          icon={<FileText size={10} />}
          label="Manifest"
        />
        <button
          type="button"
          onClick={onClose}
          className="ml-auto rounded-md px-2 py-1 text-[10px] text-text-muted hover:bg-surface-overlay hover:text-text"
        >
          Collapse
        </button>
      </div>
      <div className="px-3 pb-3 pt-2">
        {tab === "live" && (
          <div className="max-h-[480px] overflow-y-auto rounded-md bg-surface-overlay/40 p-2">
            {canPreview ? (
              <RichToolResult envelope={envelope} dispatcher={NOOP_DISPATCHER} t={t} />
            ) : (
              <p className="p-4 text-center text-[12px] text-text-muted">
                Live preview needs a bot context — pick a bot above to load this widget.
              </p>
            )}
          </div>
        )}
        {tab === "source" && <SourceView entry={entry} botId={effectiveBotId} />}
        {tab === "manifest" && <ManifestView entry={entry} botId={effectiveBotId} />}
      </div>
      {error && (
        <div className="mx-3 mb-2 rounded-md bg-danger/10 px-2 py-1 text-[11px] text-danger">
          {error}
        </div>
      )}
      {allowPin && onPin && (
        <div className="flex items-center justify-end gap-2 border-t border-surface-border/50 px-3 py-2">
          <button
            type="button"
            onClick={handlePin}
            disabled={busy || (needsBot && !effectiveBotId)}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-2.5 py-1 text-[11px] font-medium text-white hover:opacity-90 disabled:opacity-50"
            title={needsBot && !effectiveBotId ? "Pick a bot above first" : undefined}
          >
            {busy ? <Loader2 size={11} className="animate-spin" /> : <Pin size={11} />}
            Add to dashboard
          </button>
        </div>
      )}
    </div>
  );
}

function PreviewTabButton({
  active, onClick, icon, label,
}: { active: boolean; onClick: () => void; icon: React.ReactNode; label: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "inline-flex items-center gap-1 rounded-md px-2 py-1 text-[10px] font-medium transition-colors",
        active
          ? "bg-accent/15 text-accent"
          : "text-text-muted hover:bg-surface-overlay hover:text-text",
      ].join(" ")}
    >
      {icon}
      {label}
    </button>
  );
}

function sourceUrlForEntry(entry: WidgetLibraryEntry, botId: string | null): string | null {
  if (entry.scope === "integration" && entry.integration_id) {
    return `/api/v1/widgets/html-widget-content/integrations/${encodeURIComponent(entry.integration_id)}?path=${encodeURIComponent(entry.path ?? "")}`;
  }
  if (entry.scope === "channel" && entry.channel_id) {
    return `/api/v1/widgets/html-widget-content/channels/${encodeURIComponent(entry.channel_id)}?path=${encodeURIComponent(entry.path ?? "")}`;
  }
  if (entry.scope === "core") {
    return `/api/v1/widgets/html-widget-content/library?ref=${encodeURIComponent(`core/${entry.name}`)}`;
  }
  if ((entry.scope === "bot" || entry.scope === "workspace") && botId) {
    return `/api/v1/widgets/html-widget-content/library?ref=${encodeURIComponent(`${entry.scope}/${entry.name}`)}&bot_id=${encodeURIComponent(botId)}`;
  }
  return null;
}

function SourceView({ entry, botId }: { entry: WidgetLibraryEntry; botId: string | null }) {
  const [content, setContent] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const url = sourceUrlForEntry(entry, botId);

  useEffect(() => {
    let cancelled = false;
    setContent(null);
    setError(null);
    if (!url) {
      setError("Source endpoint unavailable — pick a bot to load bot/workspace sources.");
      return;
    }
    apiFetch<{ path: string; content: string }>(url)
      .then((resp) => { if (!cancelled) setContent(resp.content ?? ""); })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [url]);

  if (error) {
    return <p className="text-[12px] text-danger">{error}</p>;
  }
  if (content === null) {
    return <div className="h-20 animate-pulse rounded-md bg-surface-overlay/40" />;
  }
  return (
    <pre className="max-h-[480px] overflow-auto rounded-md bg-surface-overlay/40 p-3 text-[11px] leading-relaxed text-text">
      <code>{content}</code>
    </pre>
  );
}

interface ManifestResponse {
  manifest: Record<string, unknown> | null;
  raw: string | null;
  source_path: string;
}

function ManifestView({ entry, botId }: { entry: WidgetLibraryEntry; botId: string | null }) {
  const [data, setData] = useState<ManifestResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setData(null);
    setError(null);
    const qs = new URLSearchParams();
    qs.set("scope", entry.scope);
    if (entry.scope === "integration") {
      if (entry.integration_id) qs.set("integration_id", entry.integration_id);
      if (entry.path) qs.set("path", entry.path);
    } else if (entry.scope === "channel") {
      if (entry.channel_id) qs.set("channel_id", entry.channel_id);
      if (entry.path) qs.set("path", entry.path);
    } else {
      qs.set("name", entry.name);
      if (entry.scope === "bot" || entry.scope === "workspace") {
        if (botId) qs.set("bot_id", botId);
      }
    }
    apiFetch<ManifestResponse>(`/api/v1/widgets/widget-manifest?${qs}`)
      .then((resp) => { if (!cancelled) setData(resp); })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [entry, botId]);

  if (error) {
    return <p className="text-[12px] text-danger">{error}</p>;
  }
  if (data === null) {
    return <div className="h-20 animate-pulse rounded-md bg-surface-overlay/40" />;
  }
  if (!data.raw) {
    return (
      <p className="rounded-md bg-surface-overlay/40 px-3 py-4 text-center text-[12px] text-text-muted">
        No manifest declared. This bundle has no <span className="font-mono">widget.yaml</span>.
      </p>
    );
  }
  return (
    <pre className="max-h-[480px] overflow-auto rounded-md bg-surface-overlay/40 p-3 text-[11px] leading-relaxed text-text">
      <code>{data.raw}</code>
    </pre>
  );
}
