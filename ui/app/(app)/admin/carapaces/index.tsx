import { useState, useMemo } from "react";
import { Spinner } from "@/src/components/shared/Spinner";
import { RefreshableScrollView } from "@/src/components/shared/RefreshableScrollView";
import { usePageRefresh } from "@/src/hooks/usePageRefresh";
import { useCarapaces } from "@/src/api/hooks/useCarapaces";
import { PageHeader } from "@/src/components/layout/PageHeader";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { Plus, Search, Layers, ChevronRight, HelpCircle } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { CarapaceHelpModal } from "./CarapaceHelpModal";
import type { Carapace } from "@/src/types/api";

function fmtIntName(key: string): string {
  const special: Record<string, string> = { arr: "ARR", github: "GitHub" };
  if (special[key]) return special[key];
  return key.replace(/(^|_)(\w)/g, (_, sep, c) => (sep ? " " : "") + c.toUpperCase());
}

type RenderItem =
  | { type: "header"; key: string; label: string; count: number }
  | { type: "subheader"; key: string; label: string; count: number }
  | { type: "card"; key: string; carapace: Carapace };

function SectionHeader({ label, count, level }: { label: string; count: number; level: number }) {
  const t = useThemeTokens();
  const isSubheader = level > 0;
  return (
    <div style={{
      display: "flex", flexDirection: "row", alignItems: "center", gap: 8,
      padding: `${isSubheader ? 8 : 14}px 0 ${isSubheader ? 4 : 6}px ${isSubheader ? 16 : 0}px`,
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

export default function CarapacesPage() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const { data: carapaces, isLoading } = useCarapaces();
  const { refreshing, onRefresh } = usePageRefresh([["carapaces"]]);
  const [search, setSearch] = useState("");
  const [showHelp, setShowHelp] = useState(false);

  const filtered = useMemo(() => {
    if (!carapaces) return [];
    const q = search.toLowerCase();
    if (!q) return carapaces;
    return carapaces.filter(
      (c) =>
        c.id.toLowerCase().includes(q) ||
        c.name.toLowerCase().includes(q) ||
        (c.description || "").toLowerCase().includes(q) ||
        c.tags.some((tag) => tag.toLowerCase().includes(q))
    );
  }, [carapaces, search]);

  const renderItems = useMemo((): RenderItem[] => {
    if (!filtered.length) return [];

    const manual: Carapace[] = [];
    const core: Carapace[] = [];
    const integrationMap = new Map<string, Carapace[]>();

    for (const c of filtered) {
      if (c.source_type === "manual") manual.push(c);
      else if (c.source_type === "integration") {
        const intName = c.source_path?.match(/integrations\/([^/]+)\//)?.[1] ?? "other";
        const list = integrationMap.get(intName);
        if (list) list.push(c); else integrationMap.set(intName, [c]);
      } else core.push(c);
    }

    const items: RenderItem[] = [];
    const addGroup = (key: string, label: string, list: Carapace[]) => {
      if (!list.length) return;
      items.push({ type: "header", key, label, count: list.length });
      for (const c of list) items.push({ type: "card", key: c.id, carapace: c });
    };

    addGroup("manual", "User Added", manual);
    addGroup("core", "Core", core);

    const intKeys = [...integrationMap.keys()].sort();
    if (intKeys.length) {
      const totalInt = intKeys.reduce((n, k) => n + integrationMap.get(k)!.length, 0);
      items.push({ type: "header", key: "integrations", label: "Integrations", count: totalInt });
      for (const k of intKeys) {
        const list = integrationMap.get(k)!;
        items.push({ type: "subheader", key: `int-${k}`, label: fmtIntName(k), count: list.length });
        for (const c of list) items.push({ type: "card", key: c.id, carapace: c });
      }
    }

    return items;
  }, [filtered]);

  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list"
        title="Capabilities"
        right={
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <button
              onClick={() => setShowHelp(true)}
              title="What are capabilities?"
              style={{
                display: "flex", flexDirection: "row", alignItems: "center",
                padding: "6px 8px", fontSize: 12,
                border: `1px solid ${t.surfaceBorder}`, borderRadius: 6,
                background: "transparent", color: t.textMuted, cursor: "pointer",
              }}
            >
              <HelpCircle size={14} />
            </button>
            <button
              onClick={() => navigate("/admin/carapaces/new")}
              style={{
                display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
                padding: "6px 14px", fontSize: 12, fontWeight: 600,
                border: "none", borderRadius: 6,
                background: t.accent, color: "#fff", cursor: "pointer",
              }}
            >
              <Plus size={14} />
              New
            </button>
          </div>
        }
      />

      {/* Pinned search bar */}
      <div style={{
        display: "flex", flexDirection: "row", alignItems: "center", gap: 10,
        padding: "8px 16px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
      }}>
        <div style={{
          display: "flex", flexDirection: "row", alignItems: "center", gap: 6,
          background: t.inputBg, border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 6, padding: "5px 10px",
          maxWidth: 300, flex: 1,
        }}>
          <Search size={13} color={t.textDim} />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter capabilities..."
            style={{
              background: "none", border: "none", outline: "none",
              color: t.text, fontSize: 12, flex: 1, width: "100%",
            }}
          />
        </div>
        {carapaces && carapaces.length > 0 && (
          <span style={{ fontSize: 11, color: t.textDim, whiteSpace: "nowrap" }}>
            {search && filtered.length !== carapaces.length
              ? `${filtered.length} / ${carapaces.length}`
              : carapaces.length}{" "}
            capabilities
          </span>
        )}
      </div>

      {isLoading ? (
        <div className="flex flex-1 items-center justify-center">
          <Spinner color={t.accent} />
        </div>
      ) : (
        <RefreshableScrollView refreshing={refreshing} onRefresh={onRefresh} style={{ flex: 1 }}>
          <div style={{ padding: 16, maxWidth: 960 }}>
            {(!carapaces || carapaces.length === 0) && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 60 }}>
                <Layers size={32} color={t.textMuted} />
                <span style={{ color: t.textMuted, marginTop: 12, fontSize: 14 }}>
                  No capabilities yet. Create one to get started.
                </span>
              </div>
            )}
            {carapaces && carapaces.length > 0 && filtered.length === 0 && (
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", paddingTop: 60 }}>
                <span style={{ color: t.textDim, fontSize: 13 }}>
                  No capabilities match "{search}"
                </span>
              </div>
            )}
            {renderItems.map((item) =>
              item.type === "header" ? (
                <SectionHeader key={item.key} label={item.label} count={item.count} level={0} />
              ) : item.type === "subheader" ? (
                <SectionHeader key={item.key} label={item.label} count={item.count} level={1} />
              ) : (
                <div key={item.key} style={{ marginBottom: 8 }}>
                  <CarapaceCard carapace={item.carapace} t={t} />
                </div>
              ),
            )}
          </div>
        </RefreshableScrollView>
      )}

      {showHelp && <CarapaceHelpModal onClose={() => setShowHelp(false)} />}
    </div>
  );
}

function CarapaceCard({ carapace: c, t }: { carapace: Carapace; t: ThemeTokens }) {
  return (
    <Link
      to={`/admin/carapaces/${c.id.replaceAll("/", "--")}`}
      style={{ textDecoration: "none" }}
    >
      <div
        style={{
          backgroundColor: t.surfaceRaised,
          borderRadius: 10,
          border: `1px solid ${t.surfaceBorder}`,
          padding: 14,
          cursor: "pointer",
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
          }}
        >
          <div style={{ flex: 1 }}>
            {/* Name + source badge */}
            <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 8 }}>
              <Layers size={16} color={t.accent} />
              <span style={{ color: t.text, fontWeight: 600, fontSize: 14 }}>
                {c.name}
              </span>
              {c.source_type !== "manual" && (() => {
                const intName = c.source_type === "integration"
                  ? c.source_path?.match(/integrations\/([^/]+)\//)?.[1]
                  : null;
                const label = intName ? fmtIntName(intName) : c.source_type;
                const isInt = c.source_type === "integration";
                return (
                  <span
                    style={{
                      backgroundColor: isInt ? t.successSubtle : t.accentSubtle,
                      border: `1px solid ${isInt ? t.successBorder : t.accentBorder}`,
                      padding: "1px 6px",
                      borderRadius: 4,
                    }}
                  >
                    <span style={{ color: isInt ? t.success : t.accent, fontSize: 10 }}>{label}</span>
                  </span>
                );
              })()}
            </div>

            {/* Description */}
            {c.description ? (
              <div
                style={{
                  color: t.textMuted, fontSize: 12, marginTop: 4,
                  overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
                }}
              >
                {c.description}
              </div>
            ) : null}

            {/* Metadata row */}
            <div
              style={{
                display: "flex",
                flexDirection: "row",
                alignItems: "center",
                gap: 8,
                marginTop: 6,
                flexWrap: "wrap",
              }}
            >
              {c.local_tools.length > 0 && (
                <span style={{ color: t.textDim, fontSize: 11 }}>
                  {c.local_tools.length} tool{c.local_tools.length !== 1 ? "s" : ""}
                </span>
              )}
              {c.includes.length > 0 && (
                <span style={{ color: t.textDim, fontSize: 11 }}>
                  includes: {c.includes.join(", ")}
                </span>
              )}
              {c.tags.length > 0 && (
                <div style={{ display: "flex", flexDirection: "row", gap: 4 }}>
                  {c.tags.map((tag) => (
                    <span
                      key={tag}
                      style={{
                        backgroundColor: t.purpleSubtle,
                        border: `1px solid ${t.purpleBorder}`,
                        padding: "1px 5px",
                        borderRadius: 3,
                      }}
                    >
                      <span style={{ color: t.purple, fontSize: 10 }}>{tag}</span>
                    </span>
                  ))}
                </div>
              )}
            </div>
          </div>
          <ChevronRight size={16} color={t.textMuted} />
        </div>
      </div>
    </Link>
  );
}
