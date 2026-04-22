import { forwardRef } from "react";
import { Link } from "react-router-dom";
import type { ScoredItem } from "../palette/types";
import { HighlightedLabel } from "../palette/HighlightedLabel";
import { useThemeTokens } from "../../theme/tokens";
import { formatRelativeTime } from "../../utils/format";
import type { PaletteItem } from "../palette/types";

interface HomeGridTileProps {
  scored: ScoredItem & { item: PaletteItem & { href: string } };
  selected: boolean;
  onHover: () => void;
  onClick: () => void;
}

export const HomeGridTile = forwardRef<HTMLAnchorElement, HomeGridTileProps>(
  function HomeGridTile({ scored, selected, onHover, onClick }, ref) {
    const t = useThemeTokens();
    const { item, matchIndices } = scored;
    const Icon = item.icon;
    const relative = formatRelativeTime(item.lastMessageAt);

    return (
      <Link
        ref={ref}
        to={item.href}
        role="gridcell"
        aria-label={item.label}
        onMouseEnter={onHover}
        onFocus={onHover}
        onClick={onClick}
        className={[
          "group flex flex-row items-center gap-2.5 rounded-lg no-underline",
          "transition-colors duration-100",
          "outline-none focus-visible:ring-2 focus-visible:ring-accent",
        ].join(" ")}
        style={{
          backgroundColor: selected ? t.surfaceOverlay : t.surfaceRaised,
          border: `1px solid ${selected ? t.accentBorder : t.surfaceBorder}`,
          padding: "10px 12px",
          cursor: "pointer",
          color: "inherit",
          boxShadow: selected ? "0 2px 8px rgba(0,0,0,0.12)" : "none",
        }}
        onMouseOver={(e) => {
          if (!selected) {
            e.currentTarget.style.backgroundColor = t.surfaceOverlay;
            e.currentTarget.style.boxShadow = "0 2px 8px rgba(0,0,0,0.12)";
          }
        }}
        onMouseOut={(e) => {
          if (!selected) {
            e.currentTarget.style.backgroundColor = t.surfaceRaised;
            e.currentTarget.style.boxShadow = "none";
          }
        }}
      >
        <div
          className="flex flex-row items-center justify-center w-8 h-8 rounded-md shrink-0"
          style={{ background: t.surfaceOverlay }}
        >
          <Icon size={16} color={t.textMuted} />
        </div>

        <div className="flex flex-col min-w-0 flex-1">
          <span
            className="truncate font-semibold leading-tight"
            style={{ fontSize: 13, color: t.text }}
          >
            <HighlightedLabel
              text={item.label}
              indices={matchIndices}
              color={t.text}
              accentColor={t.accent}
            />
          </span>
          {item.hint && (
            <span
              className="truncate leading-tight mt-0.5"
              style={{ fontSize: 11, color: t.textDim }}
            >
              {item.hint}
            </span>
          )}
        </div>

        {relative && (
          <span
            className="shrink-0 tabular-nums"
            style={{ fontSize: 10, color: t.textDim, fontWeight: 500 }}
            title={item.lastMessageAt ?? undefined}
          >
            {relative}
          </span>
        )}
      </Link>
    );
  },
);
