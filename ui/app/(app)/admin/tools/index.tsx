import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { useTools } from "@/src/api/hooks/useTools";
import { useWidgetPackages } from "@/src/api/hooks/useWidgetPackages";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { TabBar } from "@/src/components/shared/FormControls";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWindowSize } from "@/src/hooks/useWindowSize";

import { ToolsTab } from "./ToolsTab";
import { WidgetLibraryTab } from "./library/WidgetLibraryTab";

type TabKey = "tools" | "library";
const TAB_KEYS = new Set<TabKey>(["tools", "library"]);

export default function ToolsScreen() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const { data: tools } = useTools();
  const { data: packages } = useWidgetPackages();
  const { width } = useWindowSize();
  const isWide = width >= 768;

  const tabParam = (searchParams.get("tab") as TabKey | null) ?? "tools";
  const activeTab: TabKey = TAB_KEYS.has(tabParam) ? tabParam : "tools";
  const initialToolFilter = searchParams.get("tool") ?? "";
  const [search, setSearch] = useState("");

  const counts = useMemo(() => ({
    tools: tools?.length ?? 0,
    library: packages?.length ?? 0,
  }), [tools, packages]);

  const setTab = (key: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", key);
    setSearchParams(next);
  };

  const handleOpenLibrary = (toolName: string) => {
    const next = new URLSearchParams(searchParams);
    next.set("tab", "library");
    next.set("tool", toolName);
    setSearchParams(next);
  };

  const headerRight = activeTab === "library" ? (
    <button
      onClick={() => navigate("/admin/widget-packages/new")}
      className="rounded-md bg-accent text-white text-[12px] font-semibold px-3 py-1.5 hover:opacity-90 transition-opacity"
    >
      + New package
    </button>
  ) : null;

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Tools" right={headerRight} />

      {/* Tabs + search bar */}
      <div
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 12,
          padding: isWide ? "8px 16px" : "8px 12px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          flexWrap: "wrap",
        }}
      >
        <TabBar
          tabs={[
            { key: "tools", label: `Tools (${counts.tools})` },
            { key: "library", label: `Widget Library (${counts.library})` },
          ]}
          active={activeTab}
          onChange={setTab}
        />
        {activeTab === "tools" && (
          <div style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
            background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px",
            maxWidth: isWide ? 300 : undefined, flex: isWide ? undefined : 1,
            marginLeft: "auto",
          }}>
            <Search size={13} color={t.textDim} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter tools..."
              style={{
                background: "none", border: "none", outline: "none",
                color: t.text, fontSize: 12, flex: 1, width: "100%",
              }}
            />
          </div>
        )}
      </div>

      {activeTab === "tools" ? (
        <ToolsTab search={search} onOpenLibrary={handleOpenLibrary} />
      ) : (
        <WidgetLibraryTab initialToolFilter={initialToolFilter} />
      )}
    </div>
  );
}
