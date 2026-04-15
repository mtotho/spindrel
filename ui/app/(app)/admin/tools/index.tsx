import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useState, useMemo } from "react";

import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Search } from "lucide-react";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";

function TypeBadge({ tool }: { tool: ToolItem }) {
  const t = useThemeTokens();
  if (tool.server_name) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: "rgba(249,115,22,0.15)", color: "#ea580c",
      }}>
        mcp
      </span>
    );
  }
  if (tool.source_integration) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: t.purpleSubtle, color: t.purple,
      }}>
        integration
      </span>
    );
  }
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: t.accentSubtle, color: t.accent,
    }}>
      local
    </span>
  );
}

function fmtDate(iso: string | null | undefined) {
  if (!iso) return "\u2014";
  return new Date(iso).toLocaleDateString(undefined, {
    month: "short", day: "numeric", year: "numeric",
  });
}

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "subheader"; key: string; label: string; count: number }
  | { type: "tool"; key: string; tool: ToolItem };

function SectionHeader({ label, count, level, isWide }: { label: string; count: number; level: number; isWide: boolean }) {
  const t = useThemeTokens();
  const isSubheader = level > 0;
  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
      padding: isWide
        ? `${isSubheader ? 8 : 14}px 16px ${isSubheader ? 4 : 6}px ${isSubheader ? 32 : 16}px`
        : `${isSubheader ? 8 : 14}px 0 ${isSubheader ? 4 : 6}px ${isSubheader ? 16 : 0}px`,
    }}>
      <span style={{
        fontSize: isSubheader ? 10 : 11,
        fontWeight: 600,
        color: isSubheader ? t.textDim : t.textMuted,
        textTransform: "uppercase",
        letterSpacing: 1,
      }}>
        {label}
      </span>
      <span style={{ fontSize: 10, color: t.textDim, fontWeight: 500 }}>
        {count}
      </span>
      <div style={{ flex: 1, height: 1, background: t.surfaceBorder }} />
    </div>
  );
}

function ToolRow({ tool, onClick, isWide }: { tool: ToolItem; onClick: () => void; isWide: boolean }) {
  const t = useThemeTokens();
  const desc = tool.description || "";
  const source = tool.server_name || tool.source_file || tool.source_dir || "";

  if (!isWide) {
    return (
      <button
        onClick={onClick}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: t.inputBg, borderRadius: 8,
          border: `1px solid ${t.surfaceBorder}`, cursor: "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: t.text, flex: 1, fontFamily: "monospace" }}>
            {tool.tool_name}
          </span>
          <TypeBadge tool={tool} />
        </div>
        {desc && (
          <div style={{
            fontSize: 11, color: t.textMuted,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {desc.slice(0, 120)}
          </div>
        )}
        {source && (
          <div style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
            {source}
          </div>
        )}
      </button>
    );
  }

  return (
    <button
      onClick={onClick}
      style={{
        display: "grid", gridTemplateColumns: "200px 1fr 90px 120px",
        alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        border: "none",
        borderBottom: `1px solid ${t.surfaceBorder}`,
        cursor: "pointer",
        textAlign: "left", width: "100%",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = t.inputBg)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <span style={{
        fontSize: 12, fontFamily: "monospace", color: t.text, fontWeight: 600,
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>
        {tool.tool_name}
      </span>
      <div style={{ overflow: "hidden" }}>
        <div style={{
          fontSize: 12, color: t.textMuted,
          overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
        }}>
          {desc || "\u2014"}
        </div>
        {source && (
          <div style={{
            fontSize: 10, color: t.textDim, fontFamily: "monospace",
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
            marginTop: 2,
          }}>
            {source}
          </div>
        )}
      </div>
      <TypeBadge tool={tool} />
      <span style={{ fontSize: 11, color: t.textDim, textAlign: "right" }}>
        {fmtDate(tool.indexed_at)}
      </span>
    </button>
  );
}

export default function ToolsScreen() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: tools, isLoading } = useTools();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    if (!tools) return [];
    if (!search.trim()) return tools;
    const q = search.toLowerCase();
    return tools.filter(
      (t) =>
        t.tool_name.toLowerCase().includes(q) ||
        (t.description || "").toLowerCase().includes(q) ||
        (t.server_name || "").toLowerCase().includes(q) ||
        (t.source_integration || "").toLowerCase().includes(q),
    );
  }, [tools, search]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filtered.length) return [];

    const local: ToolItem[] = [];
    const integrationMap = new Map<string, ToolItem[]>();
    const mcpMap = new Map<string, ToolItem[]>();

    for (const t of filtered) {
      if (t.server_name) {
        const list = mcpMap.get(t.server_name);
        if (list) list.push(t); else mcpMap.set(t.server_name, [t]);
      } else if (t.source_integration) {
        const list = integrationMap.get(t.source_integration);
        if (list) list.push(t); else integrationMap.set(t.source_integration, [t]);
      } else {
        local.push(t);
      }
    }

    const items: RenderItem[] = [];

    // Local tools
    if (local.length) {
      items.push({ type: "header", key: "local", label: "Local", count: local.length });
      for (const t of local) items.push({ type: "tool", key: t.id, tool: t });
    }

    // Integration tools, sub-grouped
    const intKeys = [...integrationMap.keys()].sort();
    if (intKeys.length) {
      const totalInt = intKeys.reduce((n, k) => n + integrationMap.get(k)!.length, 0);
      items.push({ type: "header", key: "integrations", label: "Integrations", count: totalInt });
      for (const k of intKeys) {
        const list = integrationMap.get(k)!;
        items.push({ type: "subheader", key: `int-${k}`, label: fmtIntName(k), count: list.length });
        for (const t of list) items.push({ type: "tool", key: t.id, tool: t });
      }
    }

    // MCP tools, sub-grouped by server
    const mcpKeys = [...mcpMap.keys()].sort();
    if (mcpKeys.length) {
      const totalMcp = mcpKeys.reduce((n, k) => n + mcpMap.get(k)!.length, 0);
      items.push({ type: "header", key: "mcp", label: "MCP Servers", count: totalMcp });
      for (const k of mcpKeys) {
        const list = mcpMap.get(k)!;
        items.push({ type: "subheader", key: `mcp-${k}`, label: k, count: list.length });
        for (const t of list) items.push({ type: "tool", key: t.id, tool: t });
      }
    }

    return items;
  }, [filtered]);

  if (isLoading) {
    return (
      <div className="flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Tool Index" />

      {/* Pinned search bar */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
        padding: isWide ? "8px 16px" : "8px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: isWide ? 300 : undefined, flex: isWide ? undefined : 1,
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
        {tools && tools.length > 0 && (
          <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
            {search && filtered.length !== tools.length
              ? `${filtered.length} / ${tools.length}`
              : tools.length}{" "}
            tools
          </span>
        )}
      </div>

      {/* List */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
        {(!tools || tools.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", color: t.textDim, fontSize: 13,
          }}>
            No tools indexed yet. Tools are indexed automatically on server startup.
          </div>
        )}
        {tools && tools.length > 0 && filtered.length === 0 && (
          <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
            No tools match "{search}"
          </div>
        )}
        {renderItems.map((item) =>
          item.type === "header" ? (
            <SectionHeader key={item.key} label={item.label} count={item.count} level={0} isWide={isWide} />
          ) : item.type === "subheader" ? (
            <SectionHeader key={item.key} label={item.label} count={item.count} level={1} isWide={isWide} />
          ) : (
            <ToolRow
              key={item.key}
              tool={item.tool}
              isWide={isWide}
              onClick={() => navigate(`/admin/tools/${encodeURIComponent(item.tool.server_name ? item.tool.tool_key : item.tool.tool_name)}`)}
            />
          ),
        )}
      </RefreshableScrollView>
    </div>
  );
}
