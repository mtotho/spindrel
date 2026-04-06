import { useRouter } from "expo-router";
import { useWindowDimensions } from "react-native";
import { ArrowLeft, ChevronRight } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

interface DetailHeaderProps {
  parentLabel: string;
  parentHref: string;
  title: string;
  subtitle?: string;
  right?: React.ReactNode;
  /** Hide the title area (e.g. to give right-slot content full width) */
  hideTitle?: boolean;
  /** Inline mode: no padding/border — for use inside scroll containers that provide their own padding */
  inline?: boolean;
}

export function DetailHeader({ parentLabel, parentHref, title, subtitle, right, hideTitle, inline }: DetailHeaderProps) {
  const t = useThemeTokens();
  const router = useRouter();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  const navigateToParent = () => {
    router.push(parentHref as any);
  };

  return (
    <div style={{
      display: "flex", alignItems: "center", gap: isMobile ? 8 : 12,
      ...(!inline && {
        padding: isMobile ? "10px 12px" : "10px 16px",
        borderBottom: `1px solid ${t.surfaceRaised}`,
        minHeight: 52,
      }),
      flexShrink: 0,
    }}>
      {/* Parent link: arrow + label */}
      <button
        onClick={navigateToParent}
        style={{
          display: "flex", alignItems: "center", gap: 6,
          background: "none", border: "none", cursor: "pointer", padding: 0,
          flexShrink: 0,
        }}
      >
        <div style={{
          width: 32, height: 32, display: "flex", alignItems: "center", justifyContent: "center",
          borderRadius: 6, flexShrink: 0,
        }}>
          <ArrowLeft size={18} color={t.textMuted} />
        </div>
        {!isMobile && (
          <span style={{ fontSize: 13, color: t.textMuted, fontWeight: 500, whiteSpace: "nowrap" }}>
            {parentLabel}
          </span>
        )}
      </button>

      {/* Separator */}
      {!isMobile && !hideTitle && (
        <ChevronRight size={14} color={t.textDim} style={{ flexShrink: 0 }} />
      )}

      {/* Title + subtitle */}
      {!hideTitle && (
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{
            fontSize: 14, fontWeight: 700, color: t.text,
            overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
          }}>
            {title}
          </div>
          {subtitle && (
            <div style={{ fontSize: 10, color: t.textDim, fontFamily: "monospace" }}>
              {subtitle}
            </div>
          )}
        </div>
      )}

      {/* Right slot */}
      {right && (
        <div style={{ display: "flex", alignItems: "center", gap: 8, ...(hideTitle ? { flex: 1 } : { flexShrink: 0 }) }}>
          {right}
        </div>
      )}
    </div>
  );
}
