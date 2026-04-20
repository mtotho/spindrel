/** HTML widgets section of the dev-panel Library.
 *
 *  Renders the unified widget catalog — built-in (ships with the repo),
 *  per-integration (under ``integrations/<id>/widgets/``), and per-channel
 *  workspace — as one scannable inventory with a provenance pill on every
 *  row. Replaces the earlier single-channel picker view: the point of the
 *  Library is "what can I pin?", and the answer should not depend on which
 *  channel happens to be selected. */
import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  Boxes,
  Copy,
  ExternalLink,
  FileCode,
  Hash,
  Package,
  ScrollText,
  Search,
  Tag,
} from "lucide-react";
import { apiFetch } from "@/src/api/client";
import type {
  HtmlWidgetCatalog,
  HtmlWidgetEntry,
} from "@/src/types/api";

type SourceFilter = "all" | "builtin" | "integration" | "channel";

export function HtmlWidgetsLibrarySection() {
  const [catalog, setCatalog] = useState<HtmlWidgetCatalog | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>("all");

  useEffect(() => {
    let cancelled = false;
    setCatalog(null);
    setError(null);
    apiFetch<HtmlWidgetCatalog>("/api/v1/widgets/html-widget-catalog")
      .then((resp) => { if (!cancelled) setCatalog(resp); })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      });
    return () => { cancelled = true; };
  }, []);

  const totals = useMemo(() => {
    if (!catalog) return { builtin: 0, integration: 0, channel: 0, all: 0 };
    const intCount = catalog.integrations.reduce((n, g) => n + g.entries.length, 0);
    const chCount = catalog.channels.reduce((n, g) => n + g.entries.length, 0);
    return {
      builtin: catalog.builtin.length,
      integration: intCount,
      channel: chCount,
      all: catalog.builtin.length + intCount + chCount,
    };
  }, [catalog]);

  const q = query.trim().toLowerCase();
  const match = (e: HtmlWidgetEntry) => {
    if (!q) return true;
    return (
      e.name.toLowerCase().includes(q)
      || e.slug.toLowerCase().includes(q)
      || e.description.toLowerCase().includes(q)
      || e.tags.some((t) => t.toLowerCase().includes(q))
    );
  };

  const showBuiltin = sourceFilter === "all" || sourceFilter === "builtin";
  const showIntegration = sourceFilter === "all" || sourceFilter === "integration";
  const showChannel = sourceFilter === "all" || sourceFilter === "channel";

  return (
    <section className="rounded-lg bg-surface-raised">
      <header className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <h3 className="text-[13px] font-semibold text-text">
            HTML widgets{" "}
            {catalog && (
              <span className="ml-1 text-[11px] font-normal text-text-dim">
                ({totals.all})
              </span>
            )}
          </h3>
          <p className="mt-0.5 text-[11px] text-text-muted">
            Standalone dashboard surfaces. Shipped with the app, included in an integration, or authored as <span className="font-mono">.html</span> in a channel workspace.
          </p>
        </div>
        <div className="flex items-center gap-1.5 rounded-md bg-surface px-1.5 py-1 text-[11px]">
          <FilterChip
            label={`All (${totals.all})`}
            active={sourceFilter === "all"}
            onClick={() => setSourceFilter("all")}
          />
          <FilterChip
            icon={<Package size={10} />}
            label={`Built-in (${totals.builtin})`}
            active={sourceFilter === "builtin"}
            onClick={() => setSourceFilter("builtin")}
          />
          <FilterChip
            icon={<Boxes size={10} />}
            label={`Integration (${totals.integration})`}
            active={sourceFilter === "integration"}
            onClick={() => setSourceFilter("integration")}
          />
          <FilterChip
            icon={<Hash size={10} />}
            label={`Channel (${totals.channel})`}
            active={sourceFilter === "channel"}
            onClick={() => setSourceFilter("channel")}
          />
        </div>
      </header>

      <div className="px-4 pb-3">
        <label className="flex items-center gap-2 rounded-md bg-surface px-2.5 py-1.5 focus-within:ring-1 focus-within:ring-accent/60">
          <Search size={13} className="text-text-dim" />
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Filter widgets…"
            className="flex-1 bg-transparent text-[12px] text-text placeholder-text-dim outline-none"
          />
        </label>
      </div>

      {error && (
        <div className="px-4 pb-4 text-[12px] text-danger">
          Failed to load catalog: {error}
        </div>
      )}

      {!error && catalog === null && (
        <div className="space-y-2 px-4 pb-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-14 animate-pulse rounded-md bg-surface-overlay/40" />
          ))}
        </div>
      )}

      {catalog && (
        <div className="flex flex-col gap-4 pb-4">
          {showBuiltin && catalog.builtin.length > 0 && (
            <Group
              icon={<Package size={13} className="text-accent" />}
              title="Built-in"
              subtitle="Ship with the app"
              entries={catalog.builtin.filter(match)}
              sourceLink={null}
            />
          )}
          {showIntegration && catalog.integrations.map((group) => {
            const filtered = group.entries.filter(match);
            if (filtered.length === 0) return null;
            return (
              <Group
                key={group.integration_id}
                icon={<Boxes size={13} className="text-accent" />}
                title={group.integration_id}
                subtitle={`integrations/${group.integration_id}/widgets/`}
                entries={filtered}
                sourceLink={null}
              />
            );
          })}
          {showChannel && catalog.channels.map((group) => {
            const filtered = group.entries.filter(match);
            if (filtered.length === 0) return null;
            return (
              <Group
                key={group.channel_id}
                icon={<Hash size={13} className="text-accent" />}
                title={group.channel_name}
                subtitle="Channel workspace"
                entries={filtered}
                sourceLink={null}
              />
            );
          })}
          {totals.all === 0 && (
            <p className="px-4 py-6 text-center text-[12px] text-text-muted">
              No HTML widgets found anywhere. Drop a <span className="font-mono">.html</span> into a channel workspace, bundle one into an integration, or author one under <span className="font-mono">app/tools/local/widgets/</span>.
            </p>
          )}
        </div>
      )}
    </section>
  );
}

function FilterChip({
  label, active, onClick, icon,
}: {
  label: string; active: boolean; onClick: () => void; icon?: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={[
        "inline-flex items-center gap-1 rounded px-2 py-1 transition-colors",
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

function Group({
  icon, title, subtitle, entries,
}: {
  icon: React.ReactNode;
  title: string;
  subtitle: string;
  entries: HtmlWidgetEntry[];
  sourceLink: string | null;
}) {
  return (
    <div className="mx-4 overflow-hidden rounded-md bg-surface">
      <div className="flex items-baseline gap-2 px-3 py-2">
        {icon}
        <span className="text-[12px] font-semibold text-text">{title}</span>
        <span className="text-[11px] text-text-dim">· {subtitle}</span>
        <span className="ml-auto text-[10px] text-text-dim">
          {entries.length} widget{entries.length === 1 ? "" : "s"}
        </span>
      </div>
      <ul className="divide-y divide-surface-border/40">
        {entries.map((e) => (
          <HtmlWidgetLibraryRow key={`${e.source}:${e.integration_id ?? ""}:${e.path}`} entry={e} />
        ))}
      </ul>
    </div>
  );
}

function HtmlWidgetLibraryRow({ entry }: { entry: HtmlWidgetEntry }) {
  const [copied, setCopied] = useState(false);

  const fullyQualifiedPath = useMemo(() => {
    if (entry.source === "builtin") return `app/tools/local/widgets/${entry.path}`;
    if (entry.source === "integration") {
      return `integrations/${entry.integration_id}/widgets/${entry.path}`;
    }
    return entry.path;
  }, [entry]);

  const rawHref = useMemo(() => {
    if (entry.source === "builtin") {
      return `/api/v1/widgets/html-widget-content/builtin?path=${encodeURIComponent(entry.path)}`;
    }
    if (entry.source === "integration" && entry.integration_id) {
      return `/api/v1/widgets/html-widget-content/integrations/${encodeURIComponent(entry.integration_id)}?path=${encodeURIComponent(entry.path)}`;
    }
    return null;
  }, [entry]);

  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(fullyQualifiedPath);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard permission denied — silent */
    }
  };

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
          <span className="truncate font-mono">{fullyQualifiedPath}</span>
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          onClick={copyPath}
          className="inline-flex items-center gap-1 rounded-md bg-surface-overlay px-2 py-1 text-[11px] text-text-muted hover:text-text"
          title="Copy the repo path"
        >
          <Copy size={11} />
          {copied ? "Copied" : "Copy"}
        </button>
        {rawHref && (
          <a
            href={rawHref}
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-1 rounded-md bg-surface-overlay px-2 py-1 text-[11px] text-text-muted hover:text-text"
            title="Open raw HTML source"
          >
            <ExternalLink size={11} />
            Source
          </a>
        )}
      </div>
    </li>
  );
}
