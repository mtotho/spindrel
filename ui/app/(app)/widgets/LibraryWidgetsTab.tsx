/** Library tab — enumerates widget-library bundles (core / bot / workspace)
 *  and pins them directly. Complements the "HTML widgets" tab: that one
 *  shows built-in + integration + channel-workspace ``.html`` files; this
 *  one shows the ``widget://`` library namespace — the authored-by-bot +
 *  workspace-shared surface that Phase 8 of the Widget Library track opened
 *  up so users no longer need the bot's help to pin a library widget.
 *
 *  Pin envelope for library entries:
 *   - ``source_kind: "library"``
 *   - ``source_library_ref: "<scope>/<name>"``
 *   - renderer fetches body from ``/widgets/html-widget-content/library``.
 */
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  Bot as BotIcon,
  CheckCircle2,
  ChevronDown,
  FileCode,
  Loader2,
  Package,
  Pin,
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

type ScopeFilter = "all" | "core" | "bot" | "workspace";

interface Props {
  query: string;
  pinScope: PinScope;
  existingRefs: Set<string>;
  onPin: (payload: LibraryPinPayload) => Promise<void>;
}

/** Identity key for a library-scoped pin — the ``<scope>/<name>`` ref. */
export function libraryPinIdentity(envelope: ToolResultEnvelope): string | null {
  const ref = envelope.source_library_ref;
  if (typeof ref !== "string" || !ref) return null;
  return `library:${ref}`;
}

export function envelopeForLibraryEntry(
  entry: WidgetLibraryEntry,
  botId: string | null,
): ToolResultEnvelope {
  const label = entry.display_label ?? entry.name;
  return {
    content_type: HTML_INTERACTIVE_CT,
    body: "",
    plain_body: entry.description ?? label,
    display: "inline",
    display_label: label,
    source_bot_id: botId,
    source_kind: "library",
    source_library_ref: `${entry.scope}/${entry.name}`,
  } as ToolResultEnvelope;
}

export function LibraryWidgetsTab({
  query,
  pinScope,
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
    apiFetch<WidgetLibraryCatalog>(
      `/api/v1/widgets/library-widgets${qs.toString() ? `?${qs}` : ""}`,
    )
      .then((resp) => { if (!cancelled) setCatalog(resp); })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [botId]);

  const totals = useMemo(() => {
    if (!catalog) return { core: 0, bot: 0, workspace: 0, all: 0 };
    const c = catalog.core.length;
    const b = catalog.bot.length;
    const w = catalog.workspace.length;
    return { core: c, bot: b, workspace: w, all: c + b + w };
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
  const showBot = scopeFilter === "all" || scopeFilter === "bot";
  const showWs = scopeFilter === "all" || scopeFilter === "workspace";

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
      <div className="flex items-center gap-1.5 rounded-md bg-surface px-1.5 py-1 text-[11px]">
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
              key={`${e.scope}/${e.name}`}
              entry={e}
              botId={botId}
              already={existingRefs.has(`library:${e.scope}/${e.name}`)}
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
  const ref = `${entry.scope}/${entry.name}`;
  const label = entry.display_label ?? entry.name;

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
                  : entry.format === "template"
                    ? "bg-accent/15 text-accent"
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
            <span className="font-mono">widget://{ref}</span>
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
