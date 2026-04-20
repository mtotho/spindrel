/** HTML widgets section of the dev-panel Library.
 *
 *  Sibling to the tool-renderer list shown by `WidgetLibraryTab`. Scans a
 *  selected channel's workspace for standalone `.html` widgets and exposes
 *  authoring affordances — copy path, open in file editor, preview.
 *
 *  Distinct from the "HTML widgets" tab on `AddFromChannelSheet`, which is
 *  end-user pinning; this is the authoring/inventory surface for template
 *  developers. */
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import {
  AlertTriangle,
  Copy,
  ExternalLink,
  FileCode,
  ScrollText,
  Tag,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { ChannelPicker } from "@/src/components/shared/ChannelPicker";
import { useChannels } from "@/src/api/hooks/useChannels";
import { useBots } from "@/src/api/hooks/useBots";
import {
  channelIdFromSlug,
  isChannelSlug,
} from "@/src/stores/dashboards";
import type { HtmlWidgetEntry } from "@/src/types/api";

const STORAGE_KEY = "widgets.dev.library.html.channel_id";

/** Resolve the initial channel for this section, in order:
 *    1. `?from=channel:<uuid>` query param (dev panel was opened from a channel dashboard)
 *    2. Last-selected channel from localStorage
 *    3. Empty string (user will pick from the dropdown) */
function useInitialChannelId(): string {
  const [params] = useSearchParams();
  return useMemo(() => {
    const fromSlug = params.get("from");
    if (fromSlug && isChannelSlug(fromSlug)) {
      const cid = channelIdFromSlug(fromSlug);
      if (cid) return cid;
    }
    try {
      return localStorage.getItem(STORAGE_KEY) ?? "";
    } catch {
      return "";
    }
  }, [params]);
}

export function HtmlWidgetsLibrarySection() {
  const initialChannelId = useInitialChannelId();
  const [channelId, setChannelId] = useState<string>(initialChannelId);
  const [widgets, setWidgets] = useState<HtmlWidgetEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const { data: channels } = useChannels();
  const { data: bots } = useBots();

  useEffect(() => {
    try {
      if (channelId) localStorage.setItem(STORAGE_KEY, channelId);
    } catch {
      /* localStorage disabled — safe to ignore */
    }
  }, [channelId]);

  useEffect(() => {
    if (!channelId) {
      setWidgets(null);
      return;
    }
    let cancelled = false;
    setWidgets(null);
    setError(null);
    apiFetch<{ widgets: HtmlWidgetEntry[] }>(
      `/api/v1/channels/${encodeURIComponent(channelId)}/workspace/html-widgets`,
    )
      .then((resp) => { if (!cancelled) setWidgets(resp.widgets ?? []); })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, [channelId]);

  return (
    <section className="rounded-lg border border-surface-border bg-surface-raised">
      <header className="flex flex-col gap-2 border-b border-surface-border px-4 py-3 sm:flex-row sm:items-center sm:justify-between sm:gap-3">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-text">
            HTML widgets{" "}
            {widgets && (
              <span className="ml-1 text-[11px] font-normal text-text-dim">
                ({widgets.length})
              </span>
            )}
          </h3>
          <p className="mt-0.5 text-[11px] text-text-muted">
            Standalone dashboard surfaces authored as <span className="font-mono">.html</span> in a channel workspace.
            Pinned directly — no tool call required.
          </p>
        </div>
        <div className="shrink-0 sm:min-w-[260px]">
          <ChannelPicker
            value={channelId}
            onChange={setChannelId}
            channels={channels ?? []}
            bots={bots ?? []}
            allowNone
            placeholder="Pick a channel to scan…"
          />
        </div>
      </header>

      {!channelId && (
        <div className="p-6 text-center text-[12px] text-text-muted">
          Pick a channel above to scan its workspace for HTML widgets.
          Non-channel widget roots (shared across channels) are not yet available — that unlocks with DX-5b.
        </div>
      )}

      {channelId && error && (
        <div className="p-5 text-[12px] text-danger">
          Failed to load widgets: {error}
        </div>
      )}

      {channelId && !error && widgets === null && (
        <div className="space-y-2 p-4">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-14 animate-pulse rounded-md bg-surface-overlay/40"
            />
          ))}
        </div>
      )}

      {channelId && !error && widgets && widgets.length === 0 && (
        <div className="p-6 text-center text-[12px] text-text-muted">
          No HTML widgets in this channel's workspace. Ask a bot to emit one,
          or drop a <span className="font-mono">data/widgets/&lt;slug&gt;/index.html</span> file yourself.
        </div>
      )}

      {channelId && widgets && widgets.length > 0 && (
        <ul className="divide-y divide-surface-border">
          {widgets.map((w) => (
            <HtmlWidgetLibraryRow
              key={w.path}
              entry={w}
              channelId={channelId}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

function HtmlWidgetLibraryRow({
  entry,
  channelId,
}: {
  entry: HtmlWidgetEntry;
  channelId: string;
}) {
  const absPath = `/workspace/channels/${channelId}/${entry.path}`;
  const [copied, setCopied] = useState(false);

  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(absPath);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard permission denied — silent */
    }
  };

  const rawHref =
    `/api/v1/channels/${encodeURIComponent(channelId)}/workspace/files/content?path=${encodeURIComponent(entry.path)}`;

  return (
    <li className="flex items-start gap-3 px-4 py-3">
      <FileCode size={16} className="mt-0.5 shrink-0 text-accent" />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="truncate text-[13px] font-medium text-text">
            {entry.name}
          </span>
          {entry.version && entry.version !== "0.0.0" && (
            <span className="text-[11px] text-text-dim">v{entry.version}</span>
          )}
          {entry.has_manifest && (
            <span
              className="inline-flex items-center gap-0.5 rounded bg-accent/15 px-1 py-px text-[10px] font-medium uppercase tracking-wider text-accent"
              title="Bundle declares a widget.yaml manifest (backend-capable)"
            >
              <ScrollText size={9} /> manifest
            </span>
          )}
          {entry.is_loose && (
            <span
              className="inline-flex items-center gap-0.5 rounded bg-warning/15 px-1 py-px text-[10px] font-medium uppercase tracking-wider text-warning"
              title="Outside a widgets/ folder. Move into data/widgets/<slug>/ to adopt the bundle convention."
            >
              <AlertTriangle size={9} /> loose
            </span>
          )}
        </div>
        {entry.description && (
          <p className="mt-0.5 text-[12px] text-text-muted">
            {entry.description}
          </p>
        )}
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[10px] text-text-dim">
          {entry.author && (
            <span className="rounded bg-surface-overlay px-1 py-px">
              by {entry.author}
            </span>
          )}
          {entry.tags.map((t) => (
            <span key={t} className="inline-flex items-center gap-0.5">
              <Tag size={8} /> {t}
            </span>
          ))}
          <span className="truncate font-mono">{entry.path}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={copyPath}
          className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-[11px] text-text-muted hover:bg-surface-overlay hover:text-text"
          title="Copy the absolute workspace path (use it as emit_html_widget's `path` argument)"
        >
          <Copy size={11} />
          {copied ? "Copied" : "Copy path"}
        </button>
        <a
          href={rawHref}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 rounded-md border border-surface-border px-2 py-1 text-[11px] text-text-muted hover:bg-surface-overlay hover:text-text"
          title="Open the raw HTML source in a new tab"
        >
          <ExternalLink size={11} />
          Source
        </a>
      </div>
    </li>
  );
}
