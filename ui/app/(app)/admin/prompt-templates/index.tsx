import { View, ScrollView, ActivityIndicator, useWindowDimensions } from "react-native";
import { useRouter } from "expo-router";
import { Plus, Search } from "lucide-react";
import { usePromptTemplates } from "@/src/api/hooks/usePromptTemplates";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { useThemeTokens } from "@/src/theme/tokens";
import { useState, useMemo } from "react";
import type { PromptTemplate } from "@/src/types/api";

function SourceBadge({ type }: { type: string }) {
  const tk = useThemeTokens();
  const cfg: Record<string, { bg: string; fg: string; label: string }> = {
    file: { bg: "rgba(59,130,246,0.15)", fg: "#2563eb", label: "file" },
    manual: { bg: "rgba(100,100,100,0.15)", fg: tk.textMuted, label: "manual" },
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
  if (!workspaceId) {
    return (
      <span style={{
        padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
        background: "rgba(34,197,94,0.12)", color: "#16a34a",
      }}>
        global
      </span>
    );
  }
  return (
    <span style={{
      padding: "2px 8px", borderRadius: 4, fontSize: 11, fontWeight: 600,
      background: "rgba(59,130,246,0.12)", color: "#2563eb",
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

function TemplateRow({ template, onPress, isWide }: { template: PromptTemplate; onPress: () => void; isWide: boolean }) {
  const tk = useThemeTokens();
  const preview = template.content.split("\n").find((l) => l.trim() && !l.startsWith("#") && !l.startsWith("---"))?.trim() || "";

  if (!isWide) {
    return (
      <button
        onClick={onPress}
        style={{
          display: "flex", flexDirection: "column", gap: 6,
          padding: "12px 16px", background: tk.inputBg, borderRadius: 8,
          border: `1px solid ${tk.surfaceRaised}`, cursor: "pointer", textAlign: "left",
          width: "100%",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: tk.text, flex: 1 }}>
            {template.name}
          </span>
          <ScopeBadge workspaceId={template.workspace_id} />
          <SourceBadge type={template.source_type} />
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 12, fontSize: 11, color: tk.textDim }}>
          {template.category && <span>{template.category}</span>}
        </div>
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
      onClick={onPress}
      style={{
        display: "grid", gridTemplateColumns: "1fr 100px 80px 80px 100px",
        alignItems: "center", gap: 12,
        padding: "10px 16px", background: "transparent",
        borderBottom: `1px solid ${tk.surfaceRaised}`, cursor: "pointer",
        textAlign: "left", width: "100%", border: "none",
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
  const router = useRouter();
  const { data: templates, isLoading } = usePromptTemplates();
  const { width } = useWindowDimensions();
  const isWide = width >= 768;
  const [search, setSearch] = useState("");

  const filteredTemplates = useMemo(() => {
    if (!templates) return [];
    if (!search.trim()) return templates;
    const q = search.toLowerCase();
    return templates.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        (t.category || "").toLowerCase().includes(q) ||
        (t.description || "").toLowerCase().includes(q),
    );
  }, [templates, search]);

  if (isLoading) {
    return (
      <View className="flex-1 bg-surface items-center justify-center">
        <ActivityIndicator color={tk.accent} />
      </View>
    );
  }

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader
        title="Prompt Templates"
        right={
          <button
            onClick={() => router.push("/admin/prompt-templates/new" as any)}
            style={{
              display: "flex", alignItems: "center", gap: 6,
              padding: "6px 14px", fontSize: 12, fontWeight: 600,
              border: "none", borderRadius: 6,
              background: tk.accent, color: "#fff", cursor: "pointer",
            }}
          >
            <Plus size={14} />
            New Template
          </button>
        }
      />

      {/* Search bar */}
      <div style={{
        padding: isWide ? "8px 16px" : "8px 12px",
        borderBottom: `1px solid ${tk.surfaceRaised}`,
      }}>
        <div style={{
          display: "flex", alignItems: "center", gap: 6,
          background: tk.surfaceRaised, border: `1px solid ${tk.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: isWide ? 300 : undefined,
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
      </div>

      {/* Table header (desktop only) */}
      {isWide && filteredTemplates.length > 0 && (
        <div style={{
          display: "grid", gridTemplateColumns: "1fr 100px 80px 80px 100px",
          gap: 12, padding: "8px 16px",
          borderBottom: `1px solid ${tk.surfaceOverlay}`,
          fontSize: 10, fontWeight: 600, color: tk.textDim, textTransform: "uppercase", letterSpacing: 1,
        }}>
          <span>Name</span>
          <span>Category</span>
          <span>Scope</span>
          <span>Source</span>
          <span style={{ textAlign: "right" }}>Updated</span>
        </div>
      )}

      {/* List */}
      <ScrollView style={{ flex: 1 }} contentContainerStyle={{
        padding: isWide ? 0 : 12,
        gap: isWide ? 0 : 8,
      }}>
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
        {filteredTemplates.map((tmpl) => (
          <TemplateRow
            key={tmpl.id}
            template={tmpl}
            isWide={isWide}
            onPress={() => router.push(`/admin/prompt-templates/${tmpl.id}` as any)}
          />
        ))}
      </ScrollView>
    </View>
  );
}
