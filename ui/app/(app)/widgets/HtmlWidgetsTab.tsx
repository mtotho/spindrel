/** Lists standalone HTML widgets from every source — built-in, integration,
 *  and channel workspaces — so a user pinning to a dashboard can see the
 *  whole library regardless of which dashboard they're on.
 *
 *  Pinning synthesizes an `emit_html_widget`-shaped envelope carrying the
 *  widget's provenance (`source_kind` + source-specific id) so the
 *  renderer fetches content from the right endpoint. */
import { useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Boxes,
  CheckCircle2,
  ChevronDown,
  Hash,
  LayoutDashboard,
  Loader2,
  Package,
  Pin,
  Tag,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import * as LucideIcons from "lucide-react";
import type {
  HtmlWidgetCatalog,
  HtmlWidgetEntry,
  ToolResultEnvelope,
} from "@/src/types/api";

const HTML_INTERACTIVE_CONTENT_TYPE = "application/vnd.spindrel.html+interactive";

/** Look up a lucide-react icon by name (case-insensitive PascalCase).
 *  Falls back to LayoutDashboard for unknown names. */
function resolveIcon(name: string | null): LucideIcon {
  if (!name) return LayoutDashboard;
  const pascal = name
    .split(/[-_\s]+/)
    .filter(Boolean)
    .map((s) => s[0].toUpperCase() + s.slice(1))
    .join("");
  const icons = LucideIcons as unknown as Record<string, LucideIcon>;
  return icons[pascal] ?? LayoutDashboard;
}

/** Stable dedup key for a catalog entry, used to suppress already-pinned
 *  widgets from the picker. Keys on (source, source-id, path). */
export function catalogEntryIdentity(entry: HtmlWidgetEntry): string {
  if (entry.source === "builtin") return `builtin::${entry.path}`;
  if (entry.source === "integration") {
    return `integration::${entry.integration_id ?? ""}::${entry.path}`;
  }
  // Channel source — path alone isn't enough since the same slug can exist
  // in multiple channels; caller passes the channel id in for that case.
  return `channel::${entry.path}`;
}

/** Identity for an existing pin — matches what ``catalogEntryIdentity``
 *  produces for freshly-scanned catalog rows so we can cheaply O(1) look up
 *  "is this widget already on the dashboard?" per pin. */
export function pinIdentity(envelope: ToolResultEnvelope): string | null {
  if (!envelope?.source_path) return null;
  const kind = envelope.source_kind
    ?? (envelope.source_integration_id ? "integration" : "channel");
  if (kind === "builtin") return `builtin::${envelope.source_path}`;
  if (kind === "integration" && envelope.source_integration_id) {
    return `integration::${envelope.source_integration_id}::${envelope.source_path}`;
  }
  if (kind === "channel" && envelope.source_channel_id) {
    return `channel::${envelope.source_channel_id}::${envelope.source_path}`;
  }
  return null;
}

/** Synthesize the envelope that will be persisted on the pin. Uses the
 *  entry's provenance to pick the right `source_kind` + id. */
function envelopeForEntry(
  entry: HtmlWidgetEntry,
  channelId: string | null,
): ToolResultEnvelope {
  const base: ToolResultEnvelope = {
    content_type: HTML_INTERACTIVE_CONTENT_TYPE,
    body: "",
    plain_body: entry.description || entry.display_label,
    display: "inline",
    truncated: false,
    record_id: null,
    byte_size: entry.size,
    display_label: entry.display_label,
    source_path: entry.path,
    source_bot_id: null,
    // A sidecar widget.yaml declaring `extra_csp:` carries cross-origin
    // allowances (Google Maps, Mapbox, etc.) through the pin without
    // needing a fresh emit_html_widget call. Missing → baseline CSP.
    extra_csp: entry.extra_csp ?? null,
  };
  if (entry.source === "builtin") {
    return { ...base, source_kind: "builtin" };
  }
  if (entry.source === "integration") {
    return {
      ...base,
      source_kind: "integration",
      source_integration_id: entry.integration_id,
    };
  }
  // "channel" — we need a channel id. If the caller doesn't have one we
  // can't pin this entry; the row is disabled upstream.
  return {
    ...base,
    source_kind: "channel",
    source_channel_id: channelId,
  };
}

/** Identity tag for a catalog entry against a pins list. Channel entries
 *  need the caller's channel id since the catalog's ``channels[]`` group
 *  carries the channel id separately from the entry. */
function entryIdentityForChannel(
  entry: HtmlWidgetEntry,
  channelId: string,
): string {
  if (entry.source === "channel") {
    return `channel::${channelId}::${entry.path}`;
  }
  return catalogEntryIdentity(entry);
}

export interface HtmlWidgetsTabProps {
  catalog: HtmlWidgetCatalog | null;
  loadError: string | null;
  query: string;
  /** Identity set of already-pinned widgets (via ``pinIdentity``). Matching
   *  rows render as disabled "Pinned" chips. */
  existingIdentities: Set<string>;
  onPin: (entry: HtmlWidgetEntry, envelope: ToolResultEnvelope) => Promise<void>;
}

export function HtmlWidgetsTab({
  catalog,
  loadError,
  query,
  existingIdentities,
  onPin,
}: HtmlWidgetsTabProps) {
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

  const q = query.trim().toLowerCase();
  const match = (entry: HtmlWidgetEntry) => {
    if (!q) return true;
    return (
      entry.name.toLowerCase().includes(q)
      || entry.description.toLowerCase().includes(q)
      || entry.slug.toLowerCase().includes(q)
      || entry.tags.some((t) => t.toLowerCase().includes(q))
    );
  };

  if (loadError) {
    return (
      <p className="p-5 text-[12px] text-danger">
        Failed to load HTML widgets: {loadError}
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

  const builtinMatches = catalog.builtin.filter(match);
  const integrationGroups = catalog.integrations
    .map((g) => ({ ...g, entries: g.entries.filter(match) }))
    .filter((g) => g.entries.length > 0);
  const channelGroups = catalog.channels
    .map((g) => ({ ...g, entries: g.entries.filter(match) }))
    .filter((g) => g.entries.length > 0);

  const totalMatches =
    builtinMatches.length
    + integrationGroups.reduce((n, g) => n + g.entries.length, 0)
    + channelGroups.reduce((n, g) => n + g.entries.length, 0);

  if (totalMatches === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <div className="rounded-full bg-surface-overlay p-3">
          <Activity size={16} className="text-text-dim" />
        </div>
        <p className="text-[13px] font-medium text-text">
          {q ? "No matches" : "No HTML widgets available"}
        </p>
        <p className="max-w-[280px] text-[11px] text-text-muted">
          {q
            ? "Try a different name, tag, or description."
            : "The app ships built-ins at app/tools/local/widgets/; integrations can bundle their own under integrations/<id>/widgets/; bots/users can drop .html into a channel workspace."}
        </p>
      </div>
    );
  }

  const renderEntry = (
    entry: HtmlWidgetEntry,
    channelIdForEntry: string | null,
  ) => {
    const key = `${entry.source}:${entry.integration_id ?? channelIdForEntry ?? ""}:${entry.path}`;
    const identity = channelIdForEntry && entry.source === "channel"
      ? entryIdentityForChannel(entry, channelIdForEntry)
      : catalogEntryIdentity(entry);
    const already = existingIdentities.has(identity);
    const selected = selectedKey === key;
    return (
      <li key={key} className="px-3 py-1.5">
        <HtmlWidgetRow
          entry={entry}
          already={already}
          selected={selected}
          onSelect={() => setSelectedKey(selected ? null : key)}
          onConfirm={async () => {
            await onPin(entry, envelopeForEntry(entry, channelIdForEntry));
          }}
          onCancel={() => setSelectedKey(null)}
        />
      </li>
    );
  };

  return (
    <div className="pb-2">
      {builtinMatches.length > 0 && (
        <SectionHeader
          icon={<Package size={11} />}
          label="Built-in"
          subtitle="Ship with the app"
          count={builtinMatches.length}
        />
      )}
      {builtinMatches.length > 0 && (
        <ul className="divide-y divide-surface-border/50">
          {builtinMatches.map((e) => renderEntry(e, null))}
        </ul>
      )}
      {integrationGroups.map((g) => (
        <div key={g.integration_id}>
          <SectionHeader
            icon={<Boxes size={11} />}
            label={g.integration_id}
            subtitle="Integration"
            count={g.entries.length}
          />
          <ul className="divide-y divide-surface-border/50">
            {g.entries.map((e) => renderEntry(e, null))}
          </ul>
        </div>
      ))}
      {channelGroups.map((g) => (
        <div key={g.channel_id}>
          <SectionHeader
            icon={<Hash size={11} />}
            label={g.channel_name}
            subtitle="Channel workspace"
            count={g.entries.length}
          />
          <ul className="divide-y divide-surface-border/50">
            {g.entries.map((e) => renderEntry(e, g.channel_id))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function SectionHeader({
  icon, label, subtitle, count,
}: { icon: React.ReactNode; label: string; subtitle: string; count: number }) {
  return (
    <div className="flex items-center justify-between px-4 pt-3 pb-1">
      <div className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-dim">
        {icon}
        <span className="text-text">{label}</span>
        <span>· {subtitle}</span>
      </div>
      <span className="text-[10px] text-text-dim">
        {count} widget{count === 1 ? "" : "s"}
      </span>
    </div>
  );
}

function HtmlWidgetRow({
  entry,
  already,
  selected,
  onSelect,
  onConfirm,
  onCancel,
}: {
  entry: HtmlWidgetEntry;
  already: boolean;
  selected: boolean;
  onSelect: () => void;
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
  const Icon = resolveIcon(entry.icon);

  return (
    <div
      className={[
        "rounded-md transition-colors",
        selected ? "bg-surface-overlay" : "bg-surface",
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
          "group flex w-full items-start gap-2.5 px-3 py-2 text-left transition-colors rounded-md",
          already && "cursor-not-allowed",
          !already && !selected && "hover:bg-surface-overlay",
        ]
          .filter(Boolean)
          .join(" ")}
      >
        <Icon
          size={14}
          className={
            already
              ? "mt-0.5 shrink-0 text-text-dim"
              : "mt-0.5 shrink-0 text-accent"
          }
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span
              className={
                "truncate text-[12px] font-medium "
                + (already ? "text-text-muted" : "text-text")
              }
            >
              {entry.name}
            </span>
            {entry.version && entry.version !== "0.0.0" && (
              <span className="shrink-0 text-[10px] text-text-dim">
                v{entry.version}
              </span>
            )}
            {entry.is_loose && (
              <span
                className="inline-flex items-center gap-0.5 rounded bg-warning/15 px-1 py-px text-[9px] font-medium uppercase tracking-wider text-warning"
                title="Outside a widgets/ folder. Move into data/widgets/<slug>/ to clear."
              >
                <AlertTriangle size={8} /> loose
              </span>
            )}
          </div>
          {entry.description && (
            <div className="mt-0.5 line-clamp-2 text-[11px] text-text-muted">
              {entry.description}
            </div>
          )}
          <div className="mt-1 flex flex-wrap items-center gap-1.5 text-[10px] text-text-dim">
            {entry.author && (
              <span className="rounded bg-surface-overlay px-1 py-px">
                by {entry.author}
              </span>
            )}
            {entry.tags.map((t) => (
              <span key={t} className="inline-flex items-center gap-0.5">
                <Tag size={8} />
                {t}
              </span>
            ))}
            <span className="truncate font-mono">{entry.path}</span>
          </div>
        </div>
        {already ? (
          <span className="mt-0.5 inline-flex shrink-0 items-center gap-1 rounded-full bg-accent/10 px-2 py-0.5 text-[10px] font-medium text-accent">
            <CheckCircle2 size={10} /> Pinned
          </span>
        ) : (
          <ChevronDown
            size={13}
            className={
              "mt-1 shrink-0 text-text-dim transition-transform "
              + (selected ? "rotate-180 text-accent" : "group-hover:text-text")
            }
          />
        )}
      </button>
      {selected && !already && (
        <ConfirmFooter onConfirm={onConfirm} onCancel={onCancel} />
      )}
    </div>
  );
}

function ConfirmFooter({
  onConfirm,
  onCancel,
}: {
  onConfirm: () => Promise<void>;
  onCancel: () => void;
}) {
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
    <div className="px-3 py-2">
      <p className="text-[11px] text-text-muted">
        Pins the file as a path-mode HTML widget. Edits to the source refresh
        the pinned widget within a few seconds.
      </p>
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
          className="rounded-md bg-surface-overlay px-2.5 py-1 text-[11px] font-medium text-text-muted hover:text-text disabled:opacity-50"
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
