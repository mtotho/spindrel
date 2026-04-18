import { useMemo, useState } from "react";
import { Search } from "lucide-react";
import { useNavigate } from "react-router-dom";

import { useTools } from "@/src/api/hooks/useTools";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useWindowSize } from "@/src/hooks/useWindowSize";

import { ToolsTab } from "./ToolsTab";

export default function ToolsScreen() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: tools } = useTools();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");

  const toolCount = useMemo(() => tools?.length ?? 0, [tools]);

  const handleOpenLibrary = (toolName: string) => {
    navigate(`/widgets/dev?tool=${encodeURIComponent(toolName)}#library`);
  };

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Tools" />

      <div
        style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 12,
          padding: isWide ? "8px 16px" : "8px 12px",
          borderBottom: `1px solid ${t.surfaceBorder}`,
          flexWrap: "wrap",
        }}
      >
        <span className="text-[12px] text-text-muted">
          {toolCount} tool{toolCount === 1 ? "" : "s"}
        </span>
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
      </div>

      <ToolsTab search={search} onOpenLibrary={handleOpenLibrary} />
    </div>
  );
}
