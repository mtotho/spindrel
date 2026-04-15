
import { Spinner } from "@/src/components/shared/Spinner";
import { useWindowSize } from "@/src/hooks/useWindowSize";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useNavigate } from "react-router-dom";
import { Plus, Search } from "lucide-react";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useState, useMemo } from "react";
import type { PromptTemplate } from "@/src/types/api";

function SourceBadge({ type }: { type: string }) {
  const tk = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: tk.accentSubtle, fg: tk.accent, label: "file" },
    integration: { bg: "rgba(249,115,22,0.15)", fg: "#ea580c", label: "integration" },
    manual: { bg: tk.surfaceOverlay, fg: tk.textMuted, label: "manual" },
    workspace_file: { bg: tk.purpleSubtle, fg: tk.purple, label: "workspace" },
  };
  const c = cfg[type] || cfg.manual;
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: c.bg, color: c.fg,
    }}>
      {c.label}
    </span>
  );
}

function ScopeBadge({ workspaceId }: { workspaceId?: string | null }) {
  const tk = useThemeTokens();
  if (!workspaceId) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: tk.successSubtle, color: tk.success,
      }}>
        global
      </span>
    );
  }
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: tk.accentSubtle, color: tk.accent,
    }}>
      workspace
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
  | { type: "template"; key: string; template: PromptTemplate };

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

function TagPills({ tags }: { tags: string[] }) {
  const tk = useThemeTokens();
  if (!tags || tags.length === 0) return null;
  const display = tags.slice(0, 5);
  const overflow = tags.length - display.length;
  return (
    <div style={{ display: "flex", flexDirection: "row", gap: 3, flexWrap: "wrap", alignItems: "center" }}>
      {display.map((tag) => {
        const isIntegration = tag.startsWith("integration:");
        return (
          <span
            key={tag}
            style={{
              padding: "1px 6px",
              borderRadius: 3,
              fontSize: 10,
              fontWeight: 600,
              background: isIntegration ? "rgba(34,197,94,0.12)" : tk.surfaceOverlay,
              color: isIntegration ? "#22c55e" : tk.textDim,
              whiteSpace: "nowrap",
            }}
          >
            {tag}
          </span>
        );
      })}
      {overflow > 0 && (
        <span style={{ fontSize: 10, color: tk.textDim }}>+{overflow} more</span>
      )}
    </div>
  );
}

function TemplateRow({ template, onClick, isWide }: { template: PromptTemplate; onClick: () => void; isWide: boolean }) {
  const tk = useThemeTokens();
  const preview = template.content.split("\n").find((l) => l.trim() && !l.startsWith("#") && !l.startsWith("---"))?.trim() || "";

  if (!isWide) {
    return (
      <button
        onClick={onClick}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: tk.inputBg, borderRadius: 8,
          border: `1px solid ${tk.surfaceBorder}`, cursor: "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: tk.text, flex: 1 }}>
            {template.name}
          </span>
          <ScopeBadge workspaceId={template.workspace_id} />
          <SourceBadge type={template.source_type} />
        </div>
        <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 12, fontSize: 11, color: tk.textDim }}>
          {template.category && <span>{template.category}</span>}
        </div>
        {(template.tags || []).length > 0 && <TagPills tags={template.tags || []} />}
        {preview && (
          <div style={{ fontSize: 11, color: tk.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
            {preview.slice(0, 120)}
          </div>
        )}
      </button>
    );
  }

  return (
    <button
      onClick={onClick}
      style={{
        display: "grid", gridTemplateColumns: "1fr 100px 80px 80px 100px",
        alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        border: "none",
        borderBottom: `1px solid ${tk.surfaceBorder}`,
        cursor: "pointer",
        textAlign: "left", width: "100%",
      }}
      onMouseEnter={(e) => (e.currentTarget.style.background = tk.inputBg)}
      onMouseLeave={(e) => (e.currentTarget.style.background = "transparent")}
    >
      <div style={{ overflow: "hidden" }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: tk.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {template.name}
        </div>
        {template.description && (
          <div style={{ fontSize: 11, color: tk.textDim, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", marginTop: 2 }}>
            {template.description}
          </div>
        )}
        {(template.tags || []).length > 0 && (
          <div style={{ marginTop: 3 }}>
            <TagPills tags={template.tags || []} />
          </div>
        )}
      </div>
      <span style={{ fontSize: 11, color: tk.textMuted }}>{template.category || "\u2014"}</span>
      <ScopeBadge workspaceId={template.workspace_id} />
      <SourceBadge type={template.source_type} />
      <span style={{ fontSize: 11, color: tk.textDim, textAlign: "right" }}>{fmtDate(template.updated_at)}</span>
    </button>
  );
}

export default function PromptTemplatesScreen() {
  const tk = useThemeTokens();
  const navigate = useNavigate();
  const { data: templates, isLoading } = usePromptTemplates();
  const { refreshing, onRefresh } = usePageRefresh();
  const { width } = useWindowSize();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");
  const [categoryFilter, setCategoryFilter] = useState<string | null>(null);
  const [tagFilter, setTagFilter] = useState<string | null>(null);

  const categories = useMemo(() => {
    if (!templates) return [];
    const cats = new Set(templates.map((t) => t.category).filter(Boolean) as string[]);
    return Array.from(cats).sort();
  }, [templates]);

  const allTags = useMemo(() => {
    if (!templates) return [];
    const tagSet = new Set<string>();
    for (const t of templates) {
      for (const tag of t.tags || []) tagSet.add(tag);
    }
    // Sort: integration:* tags first, then the rest alphabetically
    return Array.from(tagSet).sort((a, b) => {
      const aInt = a.startsWith("integration:");
      const bInt = b.startsWith("integration:");
      if (aInt && !bInt) return -1;
      if (!aInt && bInt) return 1;
      return a.localeCompare(b);
    });
  }, [templates]);

  const filteredTemplates = useMemo(() => {
    if (!templates) return [];
    let result = templates;
    if (categoryFilter) {
      result = result.filter((t) => t.category === categoryFilter);
    }
    if (tagFilter) {
      result = result.filter((t) => (t.tags || []).includes(tagFilter));
    }
    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          (t.category || "").toLowerCase().includes(q) ||
          (t.description || "").toLowerCase().includes(q) ||
          (t.tags || []).some((tag: string) => tag.toLowerCase().includes(q)),
      );
    }
    return result;
  }, [templates, search, categoryFilter, tagFilter]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filteredTemplates.length) return [];

    const manual: PromptTemplate[] = [];
    const workspaceFile: PromptTemplate[] = [];
    const core: PromptTemplate[] = [];
    const integrationMap = new Map<string, PromptTemplate[]>();

    for (const t of filteredTemplates) {
      if (t.source_type === "manual" || t.source_type === "workspace_file") {
        if (t.source_type === "workspace_file") workspaceFile.push(t);
        else manual.push(t);
      } else if (t.source_type === "integration") {
        const name = t.source_path?.match(/^integrations\/([^/]+)\//)?.[1] ?? "other";
        const list = integrationMap.get(name);
        if (list) list.push(t); else integrationMap.set(name, [t]);
      } else {
        core.push(t);
      }
    }

    const items: RenderItem[] = [];

    const addGroup = (key: string, label: string, list: PromptTemplate[]) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length });
      for (const t of list) items.push({ type: "template", key: t.id, template: t });
    };

    addGroup("manual", "User Added", manual);
    addGroup("workspace", "Workspace File", workspaceFile);
    addGroup("core", "Core", core);

    const intKeys = [...integrationMap.keys()].sort();
    if (intKeys.length) {
      const totalInt = intKeys.reduce((n, k) => n + integrationMap.get(k)!.length, 0);
      items.push({ type: "header", key: "integrations", label: "Integrations", count: totalInt });
      for (const k of intKeys) {
        const list = integrationMap.get(k)!;
        items.push({ type: "subheader", key: `int-${k}`, label: fmtIntName(k), count: list.length });
        for (const t of list) items.push({ type: "template", key: t.id, template: t });
      }
    }

    return items;
  }, [filteredTemplates]);

  if (isLoading) {
    return (
      <div className="flex-1 bg-surface items-center justify-center">
        <Spinner />
      </div>
    );
  }

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Prompt Templates"
        right={
          <button
            onClick={() => navigate("/admin/prompt-templates/new")}
            style={{
              display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: tk.accent, color: "#fff", cursor: "pointer",
            }}
          >
            <Plus size={14} />
            New
          </button>
        }
      />

      {/* Search bar + category chips */}
      <div style={{
        padding: isWide ? "8px 16px" : "8px 12px",
        borderBottom: `1px solid ${tk.surfaceBorder}`,
        display: "flex", flexDirection: "column", gap: 8,
      }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <div style={{
            display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
            background: tk.inputBg, border: `1px solid ${tk.surfaceBorder}`,
            borderRadius: 6, padding: "5px 10px",
            maxWidth: isWide ? 300 : undefined, flex: isWide ? undefined : 1,
          }}>
            <Search size={13} color={tk.textDim} />
            <input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Filter templates..."
              style={{
                background: "none", border: "none", outline: "none",
                color: tk.text, fontSize: 12, flex: 1, width: "100%",
              }}
            />
          </div>
          {templates && templates.length > 0 && (
            <span style={{ fontSize: 11, color: tk.textDim, whiteSpace: "nowrap" }}>
              {(search || categoryFilter || tagFilter) && filteredTemplates.length !== templates.length
                ? `${filteredTemplates.length} / ${templates.length}`
                : templates.length}{" "}
              templates
            </span>
          )}
        </div>
        {categories.length > 0 && (
          <div style={{ display: "flex", flexDirection: "row", gap: 6, flexWrap: "wrap" }}>
            <button
              onClick={() => setCategoryFilter(null)}
              style={{
                padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 600,
                border: `1px solid ${!categoryFilter ? tk.accent : tk.surfaceBorder}`,
                background: !categoryFilter ? tk.accentSubtle : "transparent",
                color: !categoryFilter ? tk.accent : tk.textDim,
                cursor: "pointer",
              }}
            >
              All
            </button>
            {categories.map((cat) => (
              <button
                key={cat}
                onClick={() => setCategoryFilter(categoryFilter === cat ? null : cat)}
                style={{
                  padding: "3px 10px", borderRadius: 12, fontSize: 11, fontWeight: 600,
                  border: `1px solid ${categoryFilter === cat ? tk.accent : tk.surfaceBorder}`,
                  background: categoryFilter === cat ? tk.accentSubtle : "transparent",
                  color: categoryFilter === cat ? tk.accent : tk.textDim,
                  cursor: "pointer",
                }}
              >
                {cat}
              </button>
            ))}
          </div>
        )}
        {allTags.length > 0 && (
          <div style={{ display: "flex", flexDirection: "row", gap: 4, flexWrap: "wrap", alignItems: "center" }}>
            <span style={{ fontSize: 10, color: tk.textDim, fontWeight: 600, marginRight: 2 }}>Tags:</span>
            {allTags.map((tag) => {
              const isIntegration = tag.startsWith("integration:");
              const active = tagFilter === tag;
              return (
                <button
                  key={tag}
                  onClick={() => setTagFilter(active ? null : tag)}
                  style={{
                    padding: "2px 8px", borderRadius: 10, fontSize: 10, fontWeight: 600,
                    border: `1px solid ${active ? (isIntegration ? "#22c55e" : tk.accent) : tk.surfaceBorder}`,
                    background: active ? (isIntegration ? "rgba(34,197,94,0.12)" : tk.accentSubtle) : "transparent",
                    color: active ? (isIntegration ? "#22c55e" : tk.accent) : (isIntegration ? "#22c55e" : tk.textDim),
                    cursor: "pointer",
                  }}
                >
                  {tag}
                </button>
              );
            })}
          </div>
        )}
      </div>

      {/* List */}
      <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
        {(!templates || templates.length === 0) && (
          <div style={{
            padding: 40, textAlign: "center", color: tk.textDim, fontSize: 13,
          }}>
            No prompt templates yet. Create one or drop <code style={{ color: tk.textMuted }}>.md</code> files in{" "}
            <code style={{ color: tk.textMuted }}>prompts/</code>.
          </div>
        )}
        {templates && templates.length > 0 && filteredTemplates.length === 0 && (
          <div style={{ padding: 40, textAlign: "center", color: tk.textDim, fontSize: 13 }}>
            No templates match "{search}"
          </div>
        )}
        {renderItems.map((item) =>
          item.type === "header" ? (
            <SectionHeader key={item.key} label={item.label} count={item.count} level={0} isWide={isWide} />
          ) : item.type === "subheader" ? (
            <SectionHeader key={item.key} label={item.label} count={item.count} level={1} isWide={isWide} />
          ) : (
            <TemplateRow
              key={item.key}
              template={item.template}
              isWide={isWide}
              onClick={() => navigate(`/admin/prompt-templates/${item.template.id}`)}
            />
          ),
        )}
      </RefreshableScrollView>
    </div>
  );
}
