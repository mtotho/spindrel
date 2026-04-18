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
  tools: "Tools",
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
        subtitle="Browse the library, author templates, run tools, inspect recent results"
      />

      {/* Tab bar */}
      <div className="flex gap-1 border-b border-surface-border px-4 py-2 bg-surface-raised">
        {TABS.map((name) => (
          <button
            key={name}
            onClick={() => setTab(name)}
            className={
              "px-3 py-1.5 rounded-md text-[12px] font-medium transition-colors bg-transparent border-none " +
              (tab === name
                ? "bg-accent/[0.12] text-accent"
                : "text-text-muted hover:bg-surface-overlay")
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
