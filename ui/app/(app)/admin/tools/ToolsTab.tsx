import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { useMemo } from "react";

import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { useTools, type ToolItem } from "@/src/api/hooks/useTools";
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

function WidgetChip({ tool, onClick }: { tool: ToolItem; onClick: (e: React.MouseEvent) => void }) {
  const active = tool.active_widget_package;
  const count = tool.widget_package_count ?? 0;
  const extraCount = count > 1 ? count - 1 : 0;

  if (!active) {
    return <span className="text-text-dim text-[11px]">—</span>;
  }

  const isUser = active.source === "user";
  return (
    <button
      onClick={onClick}
      className={
        "inline-flex items-center gap-1.5 rounded px-2 py-[2px] text-[11px] font-medium transition-colors " +
        (isUser
          ? "bg-purple/10 text-purple hover:bg-purple/20"
          : "bg-surface-overlay text-text-muted hover:bg-surface-border")
      }
      title={isUser ? active.name : "Default template"}
    >
      <span className="truncate max-w-[120px]">
        {isUser ? active.name : "Default"}
      </span>
      {extraCount > 0 && (
        <span className="bg-accent/10 text-accent rounded px-1 text-[10px]">
          +{extraCount}
        </span>
      )}
    </button>
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

function ToolRow({
  tool, onClick, onWidgetClick, isWide,
}: {
  tool: ToolItem;
  onClick: () => void;
  onWidgetClick: (e: React.MouseEvent) => void;
  isWide: boolean;
}) {
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
        <div className="flex items-center gap-2">
          {source && (
            <div style={{ fontSize: 11, color: t.textDim, fontFamily: "monospace" }}>
              {source}
            </div>
          )}
          <div className="ml-auto">
            <WidgetChip tool={tool} onClick={onWidgetClick} />
          </div>
        </div>
      </button>
    );
  }

  return (
    <button
      onClick={onClick}
      style={{
        display: "grid", gridTemplateColumns: "200px 1fr 90px 160px 120px",
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
      <WidgetChip tool={tool} onClick={onWidgetClick} />
      <span style={{ fontSize: 11, color: t.textDim, textAlign: "right" }}>
        {fmtDate(tool.indexed_at)}
      </span>
    </button>
  );
}

interface ToolsTabProps {
  search: string;
  onOpenLibrary: (toolName: string) => void;
}

export function ToolsTab({ search, onOpenLibrary }: ToolsTabProps) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: tools, isLoading } = useTools();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;

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
    if (local.length) {
      items.push({ type: "header", key: "local", label: "Local", count: local.length });
      for (const t of local) items.push({ type: "tool", key: t.id, tool: t });
    }
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
      <div className="flex flex-1 items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <RefreshableScrollView
      refreshing={refreshing}
      onRefresh={onRefresh}
      style={{ flex: 1 }}
      contentContainerStyle={{ padding: isWide ? undefined : "0 12px" }}
    >
      {(!tools || tools.length === 0) && (
        <div style={{ padding: 40, textAlign: "center", color: t.textDim, fontSize: 13 }}>
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
            onClick={() =>
              navigate(`/admin/tools/${encodeURIComponent(item.tool.server_name ? item.tool.tool_key : item.tool.tool_name)}`)
            }
            onWidgetClick={(e) => {
              e.stopPropagation();
              const bareName = item.tool.tool_name.includes("-")
                ? item.tool.tool_name.split("-").slice(1).join("-")
                : item.tool.tool_name;
              onOpenLibrary(bareName);
            }}
          />
        ),
      )}
    </RefreshableScrollView>
  );
}
