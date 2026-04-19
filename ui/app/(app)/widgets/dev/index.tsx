import { PageHeader } from "@/src/components/layout/PageHeader";
import { useHashTab } from "@/src/hooks/useHashTab";
import { ToolsSandbox } from "./ToolsSandbox";
import { TemplatesTab } from "./TemplatesTab";
import { LibraryTab } from "./LibraryTab";
import { RecentTab } from "./RecentTab";

type DevTab = "library" | "templates" | "tools" | "recent";
const TABS: readonly DevTab[] = ["library", "templates", "tools", "recent"] as const;

const LABELS: Record<DevTab, string> = {
  library: "Library",
  templates: "Templates",
  tools: "Call tools",
  recent: "Recent",
};

export default function WidgetDevPanelPage() {
  const [tab, setTab] = useHashTab<DevTab>("library", TABS);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader
        variant="detail"
        backTo="/widgets"
        parentLabel="Widgets"
        title="Developer panel"
        subtitle="Browse the library, author templates, call tools, inspect recent results"
      />

      {/* Tab bar */}
      <div
        className="flex gap-1 overflow-x-auto border-b border-surface-border px-4 py-2 bg-surface-raised"
        role="tablist"
      >
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

      {/* Tab content */}
      {tab === "library" && <LibraryTab />}
      {tab === "templates" && <TemplatesTab />}
      {tab === "tools" && <ToolsSandbox />}

      {tab === "recent" && <RecentTab />}
    </div>
  );
}
