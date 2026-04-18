import { PageHeader } from "@/src/components/layout/PageHeader";
import { useHashTab } from "@/src/hooks/useHashTab";
import { ToolsSandbox } from "./ToolsSandbox";

type DevTab = "tools" | "templates" | "recent";
const TABS: readonly DevTab[] = ["tools", "templates", "recent"] as const;

const LABELS: Record<DevTab, string> = {
  tools: "Tools",
  templates: "Templates",
  recent: "Recent calls",
};

export default function WidgetDevPanelPage() {
  const [tab, setTab] = useHashTab<DevTab>("tools", TABS);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader
        variant="detail"
        backTo="/widgets"
        parentLabel="Widgets"
        title="Developer panel"
        subtitle="Run tools, test templates, inspect recent results"
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
      {tab === "tools" && <ToolsSandbox />}

      {tab === "templates" && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="rounded-lg border border-dashed border-surface-border p-10 text-center text-[12px] text-text-dim max-w-md">
            <div className="font-semibold text-text mb-1">Template sandbox</div>
            Paste a widget YAML template and context JSON to evaluate in isolation. Coming next.
          </div>
        </div>
      )}

      {tab === "recent" && (
        <div className="flex-1 flex items-center justify-center p-8">
          <div className="rounded-lg border border-dashed border-surface-border p-10 text-center text-[12px] text-text-dim max-w-md">
            <div className="font-semibold text-text mb-1">Recent calls</div>
            Browse recent tool results and load them into the Tools or Templates sandbox. Coming next.
          </div>
        </div>
      )}
    </div>
  );
}
