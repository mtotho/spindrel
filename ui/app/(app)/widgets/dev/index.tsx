import { useMemo, useState } from "react";
import { BookOpen } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useHashTab } from "@/src/hooks/useHashTab";
import { WidgetTemplatesDocsModal } from "@/app/(app)/admin/tools/library/WidgetTemplatesDocsModal";
import {
  channelIdFromSlug,
  isChannelSlug,
} from "@/src/stores/dashboards";
import { useChannel } from "@/src/api/hooks/useChannels";
import { useDashboardsStore } from "@/src/stores/dashboards";
import { ToolsSandbox } from "./ToolsSandbox";
import { TemplatesTab } from "./TemplatesTab";
import { LibraryTab } from "./LibraryTab";
import { RecentTab } from "./RecentTab";
import { ThemesTab } from "./ThemesTab";
import { DashboardTargetPicker } from "./DashboardTargetPicker";

type DevTab = "library" | "templates" | "themes" | "tools" | "recent";
const TABS: readonly DevTab[] = ["library", "templates", "themes", "tools", "recent"] as const;

const LABELS: Record<DevTab, string> = {
  library: "Library",
  templates: "Templates",
  themes: "Themes",
  tools: "Call tools",
  recent: "Recent",
};

/** Read `?from=<slug>` once at mount. Persisted in state so the picker can
 *  strip the query param without losing the back-navigation target. */
function useOriginSlug(): string | null {
  const [params] = useSearchParams();
  const [initial] = useState(() => params.get("from"));
  return initial;
}

export default function WidgetDevPanelPage() {
  const [tab, setTab] = useHashTab<DevTab>("library", TABS);
  const [docsOpen, setDocsOpen] = useState(false);
  const originSlug = useOriginSlug();

  // Channel dashboard: route back via the pretty /widgets/channel/<id> form.
  // User dashboard: /widgets/<slug>. No origin: default lands on /widgets.
  const backTo = useMemo(() => {
    if (!originSlug) return "/widgets";
    if (isChannelSlug(originSlug)) {
      const chId = channelIdFromSlug(originSlug);
      return chId ? `/widgets/channel/${chId}` : "/widgets";
    }
    return `/widgets/${originSlug}`;
  }, [originSlug]);

  const originChannelId = originSlug && isChannelSlug(originSlug)
    ? channelIdFromSlug(originSlug)
    : null;
  const { data: channelRow } = useChannel(originChannelId ?? undefined);
  const dashboards = useDashboardsStore((s) => s.list);
  const originDashboard = originSlug
    ? dashboards.find((d) => d.slug === originSlug)
    : null;
  const parentLabel = useMemo(() => {
    if (!originSlug) return "Widgets";
    if (originChannelId) return channelRow?.name ? `#${channelRow.name}` : "Channel dashboard";
    return originDashboard?.name ?? "Widgets";
  }, [originSlug, originChannelId, channelRow?.name, originDashboard?.name]);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader
        variant="detail"
        backTo={backTo}
        parentLabel={parentLabel}
        title="Developer panel"
        subtitle="Browse the library, author templates, manage themes, call tools, inspect recent results"
      />

      {/* Tab bar — tabs left, docs affordance right. */}
      <div
        className="flex items-center gap-1 px-2 sm:px-4 py-2 bg-surface-raised"
        role="tablist"
      >
        <div className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto scrollbar-thin">
          {TABS.map((name) => (
            <button
              key={name}
              onClick={() => setTab(name)}
              role="tab"
              aria-selected={tab === name}
              className={
                "shrink-0 px-3 py-1.5 rounded-md text-[12px] transition-colors bg-transparent border-none focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40 " +
                (tab === name
                  ? "bg-accent/[0.12] text-accent font-semibold"
                  : "text-text-muted font-medium hover:bg-surface-overlay")
              }
            >
              {LABELS[name]}
            </button>
          ))}
        </div>
        <DashboardTargetPicker />
        <button
          type="button"
          onClick={() => setDocsOpen(true)}
          className="shrink-0 inline-flex items-center gap-1.5 rounded-md border border-surface-border px-2 py-1 text-[12px] font-medium text-text-muted hover:bg-surface-overlay hover:text-text transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-accent/40"
          aria-label="Read widget templates documentation"
          title="Read the docs"
        >
          <BookOpen size={12} />
          <span className="hidden sm:inline">Docs</span>
        </button>
      </div>

      {/* Tab content */}
      {tab === "library" && <LibraryTab originChannelId={originChannelId} />}
      {tab === "templates" && <TemplatesTab />}
      {tab === "themes" && <ThemesTab originChannelId={originChannelId} />}
      {tab === "tools" && <ToolsSandbox />}
      {tab === "recent" && <RecentTab />}

      {docsOpen && <WidgetTemplatesDocsModal onClose={() => setDocsOpen(false)} />}
    </div>
  );
}
