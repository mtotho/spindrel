/** Lists standalone HTML widgets scanned from a channel's workspace.
 *
 *  Unlike Recent calls (tool-output renderers) or From channel (pins already
 *  placed elsewhere), this surfaces bot/user-authored `.html` files as
 *  first-class catalog entries. Pinning synthesizes an `emit_html_widget`
 *  path-mode envelope so the existing renderer handles it with no extra
 *  backend plumbing. */
import { useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  Loader2,
  Pin,
  Activity,
  AlertTriangle,
  LayoutDashboard,
  Tag,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import * as LucideIcons from "lucide-react";
import type { HtmlWidgetEntry, ToolResultEnvelope } from "@/src/types/api";

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

/** Build the identity string we use to suppress already-pinned widgets.
 *  Mirrors how the existing `envelopeIdentityKey` treats path-mode HTML
 *  widgets: tool=emit_html_widget, key on source_path+channel. */
export function htmlWidgetPinIdentity(channelId: string, path: string): string {
  return `emit_html_widget::${channelId}::${path}`;
}

/** Synthesize a path-mode `emit_html_widget` envelope from a scanner entry.
 *  The renderer then fetches the file through the existing
 *  `/channels/{id}/workspace/files/content` endpoint + polls for changes. */
function envelopeForEntry(
  entry: HtmlWidgetEntry,
  channelId: string,
): ToolResultEnvelope {
  return {
    content_type: HTML_INTERACTIVE_CONTENT_TYPE,
    body: "",
    plain_body: entry.description || entry.display_label,
    display: "inline",
    truncated: false,
    record_id: null,
    byte_size: entry.size,
    display_label: entry.display_label,
    source_path: entry.path,
    source_channel_id: channelId,
    source_bot_id: null,
  };
}

export interface HtmlWidgetsTabProps {
  loaded: HtmlWidgetEntry[] | null;
  loadError: string | null;
  query: string;
  channelId: string;
  existingPaths: Set<string>;
  onPin: (entry: HtmlWidgetEntry, envelope: ToolResultEnvelope) => Promise<void>;
}

export function HtmlWidgetsTab({
  loaded,
  loadError,
  query,
  channelId,
  existingPaths,
  onPin,
}: HtmlWidgetsTabProps) {
  const [selectedPath, setSelectedPath] = useState<string | null>(null);

  const filtered = useMemo(() => {
    if (!loaded) return [];
    const q = query.trim().toLowerCase();
    if (!q) return loaded;
    return loaded.filter((e) => {
      if (e.name.toLowerCase().includes(q)) return true;
      if (e.description.toLowerCase().includes(q)) return true;
      if (e.path.toLowerCase().includes(q)) return true;
      if (e.tags.some((t) => t.toLowerCase().includes(q))) return true;
      return false;
    });
  }, [loaded, query]);

  if (loadError) {
    return (
      <p className="p-5 text-[12px] text-danger">
        Failed to load HTML widgets: {loadError}
      </p>
    );
  }
  if (loaded === null) {
    return (
      <div className="space-y-2 p-4">
        {[0, 1, 2].map((i) => (
          <div
            key={i}
            className="h-14 animate-pulse rounded-md bg-surface-overlay/40"
          />
        ))}
      </div>
    );
  }
  if (filtered.length === 0) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-2 p-8 text-center">
        <div className="rounded-full bg-surface-overlay p-3">
          <Activity size={16} className="text-text-dim" />
        </div>
        <p className="text-[13px] font-medium text-text">
          {query ? "No matches" : "No HTML widgets here yet"}
        </p>
        <p className="max-w-[280px] text-[11px] text-text-muted">
          {query
            ? "Try a different name, tag, or description."
            : "Ask your bot to create one — the emit_html_widget skill walks through the bundle layout and frontmatter."}
        </p>
      </div>
    );
  }

  return (
    <ul className="divide-y divide-surface-border">
      {filtered.map((entry) => {
        const identity = htmlWidgetPinIdentity(channelId, entry.path);
        const already = existingPaths.has(identity);
        const selected = selectedPath === entry.path;
        return (
          <li key={entry.path} className="px-3 py-1.5">
            <HtmlWidgetRow
              entry={entry}
              channelId={channelId}
              already={already}
              selected={selected}
              onSelect={() =>
                setSelectedPath(selected ? null : entry.path)
              }
              onConfirm={async () => {
                await onPin(entry, envelopeForEntry(entry, channelId));
              }}
              onCancel={() => setSelectedPath(null)}
            />
          </li>
        );
      })}
    </ul>
  );
}

function HtmlWidgetRow({
  entry,
  channelId: _channelId,
  already,
  selected,
  onSelect,
  onConfirm,
  onCancel,
}: {
  entry: HtmlWidgetEntry;
  channelId: string;
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
        "rounded-md border transition-colors",
        selected
          ? "border-accent/50 bg-surface"
          : "border-transparent bg-surface",
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
    <div className="border-t border-surface-border/70 px-3 py-2">
      <p className="text-[11px] text-text-muted">
        Pins this workspace file as a path-mode HTML widget. Edits to the file
        refresh the pinned widget within a few seconds.
      </p>
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
