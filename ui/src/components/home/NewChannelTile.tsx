import { Link } from "react-router-dom";
import { Plus } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";

/**
 * Pinned first tile in the Channels section of HomeGrid.
 * Same geometry as HomeGridTile so the grid rhythm stays intact — the
 * dashed accent border is what signals "empty slot / create new".
 */
export function NewChannelTile() {
  const t = useThemeTokens();
  return (
    <Link
      to="/channels/new"
      role="gridcell"
      aria-label="New channel"
      className={[
        "group flex flex-row items-center gap-2.5 rounded-lg no-underline",
        "transition-colors duration-100",
        "outline-none focus-visible:ring-2 focus-visible:ring-accent",
      ].join(" ")}
      style={{
        backgroundColor: "transparent",
        border: `1px dashed ${t.accentBorder}`,
        padding: "10px 12px",
        cursor: "pointer",
        color: "inherit",
      }}
      onMouseOver={(e) => {
        e.currentTarget.style.backgroundColor = t.accentSubtle;
        e.currentTarget.style.borderColor = t.accent;
      }}
      onMouseOut={(e) => {
        e.currentTarget.style.backgroundColor = "transparent";
        e.currentTarget.style.borderColor = t.accentBorder;
      }}
    >
      <div
        className="flex flex-row items-center justify-center w-8 h-8 rounded-md shrink-0"
        style={{ background: t.accentSubtle }}
      >
        <Plus size={16} color={t.accent} />
      </div>
      <div className="flex flex-col min-w-0 flex-1">
        <span
          className="truncate font-semibold leading-tight"
          style={{ fontSize: 13, color: t.accent }}
        >
          New channel
        </span>
        <span
          className="truncate leading-tight mt-0.5"
          style={{ fontSize: 11, color: t.textDim }}
        >
          Create a conversation
        </span>
      </div>
    </Link>
  );
}
