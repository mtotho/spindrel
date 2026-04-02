import { useState } from "react";
import { ChevronDown } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { SECTIONS, type SectionKey } from "./constants";

export function SectionNav({
  active,
  onSelect,
  filter,
  matchingSections,
  isMobile,
}: {
  active: SectionKey;
  onSelect: (k: SectionKey) => void;
  filter: string;
  matchingSections: Set<SectionKey>;
  isMobile: boolean;
}) {
  const t = useThemeTokens();
  const [mobileOpen, setMobileOpen] = useState(false);

  if (isMobile) {
    const activeLabel = SECTIONS.find((s) => s.key === active)?.label ?? active;
    return (
      <div style={{ position: "relative", borderBottom: `1px solid ${t.surfaceRaised}` }}>
        <button
          onClick={() => setMobileOpen(!mobileOpen)}
          style={{
            display: "flex", alignItems: "center", gap: 8, width: "100%",
            padding: "12px 16px", background: t.surface, border: "none",
            color: t.text, fontSize: 15, fontWeight: 600, cursor: "pointer",
            minHeight: 48,
          }}
        >
          <span style={{ flex: 1, textAlign: "left" }}>{activeLabel}</span>
          <ChevronDown size={16} color={t.textDim} style={{ transform: mobileOpen ? "rotate(180deg)" : "none", transition: "transform 0.15s" } as any} />
        </button>
        {mobileOpen && (
          <div style={{
            position: "absolute", top: "100%", left: 0, right: 0, zIndex: 20,
            background: t.surface, border: `1px solid ${t.surfaceRaised}`, borderTop: "none",
            maxHeight: 400, overflowY: "auto",
          }}>
            {SECTIONS.map((s) => {
              const dimmed = filter && !matchingSections.has(s.key);
              return (
                <button
                  key={s.key}
                  onClick={() => { onSelect(s.key); setMobileOpen(false); }}
                  style={{
                    display: "block", width: "100%", padding: "12px 16px", border: "none",
                    background: active === s.key ? t.surfaceRaised : "transparent",
                    color: dimmed ? t.surfaceBorder : active === s.key ? t.accent : t.textMuted,
                    fontSize: 14, fontWeight: active === s.key ? 600 : 400,
                    cursor: "pointer", textAlign: "left",
                    minHeight: 44,
                  }}
                >
                  {s.label}
                </button>
              );
            })}
          </div>
        )}
      </div>
    );
  }

  return (
    <div style={{
      width: 150, flexShrink: 0, borderRight: `1px solid ${t.surfaceRaised}`,
      paddingTop: 8, overflowY: "auto",
    }}>
      {SECTIONS.map((s) => {
        const dimmed = filter && !matchingSections.has(s.key);
        return (
          <button
            key={s.key}
            onClick={() => onSelect(s.key)}
            style={{
              display: "block", width: "100%", padding: "7px 12px", border: "none",
              background: active === s.key ? t.surfaceRaised : "transparent",
              borderLeft: active === s.key ? `2px solid ${t.accent}` : "2px solid transparent",
              color: dimmed ? t.surfaceBorder : active === s.key ? t.text : t.textMuted,
              fontSize: 12, fontWeight: active === s.key ? 600 : 400,
              cursor: "pointer", textAlign: "left", transition: "all 0.1s",
            }}
          >
            {s.label}
          </button>
        );
      })}
    </div>
  );
}
