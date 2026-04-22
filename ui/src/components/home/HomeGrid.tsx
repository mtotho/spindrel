import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Search, AlertTriangle, ChevronRight, Compass } from "lucide-react";
import { useChannels, useEnsureOrchestrator } from "../../api/hooks/useChannels";
import { useProviders } from "../../api/hooks/useProviders";
import { useAuthStore } from "../../stores/auth";
import { useUIStore } from "../../stores/ui";
import { useThemeTokens } from "../../theme/tokens";
import { usePaletteItems } from "../palette/items";
import { usePaletteSearch } from "../palette/search";
import { HomeGridTile } from "./HomeGridTile";
import { NewChannelTile } from "./NewChannelTile";
import { Link } from "react-router-dom";
import { buildRecentHref } from "../../lib/recentPages";

const MIN_TILE_WIDTH = 220;
const GRID_GAP = 8;

/**
 * Full-screen palette-as-grid that owns the desktop `/` route.
 * Reuses the same item catalog + fuzzy search as the Ctrl+K palette overlay,
 * rendered as a dense, browsable tile grid instead of a vertical list.
 */
export function HomeGrid() {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const location = useLocation();
  const inputRef = useRef<HTMLInputElement>(null);
  const gridScrollRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<HTMLDivElement>(null);

  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState<number>(-1);
  const [columns, setColumns] = useState(4);
  // True only while the selection is being driven by the keyboard; hover-
  // driven selection must not auto-scroll or the page feels like it's
  // jumping on mouse movement.
  const isKeyboardNav = useRef(false);

  const isAdmin = useAuthStore((s) => s.user?.is_admin ?? false);
  const recordPageVisit = useUIStore((s) => s.recordPageVisit);

  const allItems = usePaletteItems();
  // The palette surfaces "Home" (self-link here) and "New channel" (replaced
  // by the pinned NewChannelTile below) — drop them to avoid duplicates.
  const items = useMemo(
    () => allItems.filter((it) => it.id !== "nav-home" && it.id !== "nav-new-channel"),
    [allItems],
  );

  const { groups: rawGroups, isEmpty } = usePaletteSearch(items, query, {
    currentHref: buildRecentHref(location.pathname, location.search, location.hash),
    searchLimit: 200,
  });

  // Home page order differs from the palette overlay's CATEGORY_ORDER: we push
  // admin/feature categories above Recent and Channels because `/` is the
  // setup + discovery surface, not the fast-nav surface. Palette overlay
  // (Ctrl+K) keeps Recent/Channels on top since that's the quick-jump use case.
  const HOME_CATEGORY_ORDER = [
    "Configure",
    "Automate",
    "Integrations",
    "Bots",
    "Monitor",
    "Security",
    "Developer",
    "Recent",
    "Channels",
    "Settings",
  ];
  const groups = useMemo(() => {
    if (!isEmpty) return rawGroups;
    const rank = (cat: string) => {
      const idx = HOME_CATEGORY_ORDER.indexOf(cat);
      return idx === -1 ? HOME_CATEGORY_ORDER.length : idx;
    };
    return [...rawGroups].sort((a, b) => rank(a.category) - rank(b.category));
  }, [rawGroups, isEmpty]);

  // Surface setup affordances when an admin has no orchestrator channel yet.
  const { data: channels, isLoading: channelsLoading } = useChannels();
  const ensureOrchestrator = useEnsureOrchestrator();
  const { data: providersData, isLoading: providersLoading } = useProviders(isAdmin);
  const hasProviders = providersLoading || (providersData?.providers?.length ?? 0) > 0;
  const orchestratorChannel = channels?.find((ch) => ch.client_id === "orchestrator:home");
  const showNoProviderBanner = isAdmin && !channelsLoading && !orchestratorChannel && !hasProviders;
  const showGuidedSetup = isAdmin && !channelsLoading && !orchestratorChannel && hasProviders;

  // Measure grid width → column count.
  useEffect(() => {
    const el = measureRef.current;
    if (!el) return;
    const update = () => {
      const width = el.clientWidth;
      if (width > 0) {
        const cols = Math.max(1, Math.floor((width + GRID_GAP) / (MIN_TILE_WIDTH + GRID_GAP)));
        setColumns(cols);
      }
    };
    update();
    const obs = new ResizeObserver(update);
    obs.observe(el);
    return () => obs.disconnect();
  }, []);

  // Each section is its own CSS grid, so keyboard nav has to respect section
  // boundaries — Down from a short 1-tile section must land on row 0 of the
  // next section, not N columns later in flat index space.
  type FlatTile =
    | { kind: "new" }
    | { kind: "item"; scored: import("../palette/types").ScoredItem };
  type Section = { category: string; tiles: FlatTile[] };

  const sections = useMemo<Section[]>(() => {
    const searching = query.trim().length > 0;
    const out: Section[] = [];
    for (const g of groups) {
      const tiles: FlatTile[] = [];
      if (g.category === "Channels" && !searching) tiles.push({ kind: "new" });
      for (const s of g.items) tiles.push({ kind: "item", scored: s });
      if (tiles.length > 0) out.push({ category: g.category, tiles });
    }
    return out;
  }, [groups, query]);

  const flatTiles = useMemo(
    () => sections.flatMap((s) => s.tiles),
    [sections],
  );

  // Flat index → (section, position-in-section). Also compute offsets so we
  // can translate back when moving between sections.
  const { positions, sectionOffsets } = useMemo(() => {
    const pos: { sectionIdx: number; posInSection: number }[] = [];
    const offsets: number[] = [];
    let offset = 0;
    sections.forEach((s, si) => {
      offsets.push(offset);
      s.tiles.forEach((_, i) => pos.push({ sectionIdx: si, posInSection: i }));
      offset += s.tiles.length;
    });
    return { positions: pos, sectionOffsets: offsets };
  }, [sections]);

  // Refs for each rendered tile, keyed by flat index.
  const tileRefs = useRef<(HTMLAnchorElement | null)[]>([]);
  tileRefs.current = tileRefs.current.slice(0, flatTiles.length);

  // Reset selection when the result set changes shape.
  useEffect(() => {
    setSelectedIndex(query.trim() ? (flatTiles.length > 0 ? 0 : -1) : -1);
  }, [query, flatTiles.length]);

  // Scroll the selected tile into view on keyboard nav only. Hover updates
  // selectedIndex too (for the highlight ring) but must not scroll, or the
  // page shifts under the user as they move the mouse over partially-
  // visible tiles near the viewport edge.
  useEffect(() => {
    if (selectedIndex < 0) return;
    if (!isKeyboardNav.current) return;
    tileRefs.current[selectedIndex]?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  function moveVertical(flatIdx: number, dir: 1 | -1): number {
    if (flatIdx < 0) return 0;
    const p = positions[flatIdx];
    if (!p) return flatIdx;
    const section = sections[p.sectionIdx];
    const col = p.posInSection % columns;
    const row = Math.floor(p.posInSection / columns);
    const nextRowStart = (row + dir) * columns;

    // Move within the current section if the target row exists.
    if (nextRowStart >= 0 && nextRowStart < section.tiles.length) {
      const rowLen = Math.min(columns, section.tiles.length - nextRowStart);
      const destCol = Math.min(col, rowLen - 1);
      return sectionOffsets[p.sectionIdx] + nextRowStart + destCol;
    }

    // Cross into neighbor section, preserving column when possible.
    const neighborIdx = p.sectionIdx + dir;
    if (neighborIdx < 0 || neighborIdx >= sections.length) return flatIdx;
    const ns = sections[neighborIdx];
    if (dir === 1) {
      const firstRowLen = Math.min(columns, ns.tiles.length);
      return sectionOffsets[neighborIdx] + Math.min(col, firstRowLen - 1);
    }
    // Up: land on the LAST row of the previous section, same column clamped.
    const lastRowStart = Math.floor((ns.tiles.length - 1) / columns) * columns;
    const lastRowLen = ns.tiles.length - lastRowStart;
    const destCol = Math.min(col, lastRowLen - 1);
    return sectionOffsets[neighborIdx] + lastRowStart + destCol;
  }

  function moveHorizontal(flatIdx: number, dir: 1 | -1): number {
    if (flatIdx < 0) return 0;
    const next = flatIdx + dir;
    return Math.max(0, Math.min(flatTiles.length - 1, next));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (flatTiles.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      isKeyboardNav.current = true;
      setSelectedIndex((i) => moveVertical(i, 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      isKeyboardNav.current = true;
      setSelectedIndex((i) => moveVertical(i, -1));
    } else if (e.key === "ArrowRight") {
      e.preventDefault();
      isKeyboardNav.current = true;
      setSelectedIndex((i) => moveHorizontal(i, 1));
    } else if (e.key === "ArrowLeft") {
      e.preventDefault();
      isKeyboardNav.current = true;
      setSelectedIndex((i) => moveHorizontal(i, -1));
    } else if (e.key === "Enter") {
      // Empty query + no keyboard selection = nothing to submit.
      // Non-empty query with no selection yet = jump to the top result.
      const idx = selectedIndex >= 0 ? selectedIndex : (query.trim() ? 0 : -1);
      if (idx < 0) return;
      const target = flatTiles[idx];
      if (!target) return;
      e.preventDefault();
      if (target.kind === "new") {
        navigate("/channels/new");
      } else {
        const href = target.scored.item.href;
        recordPageVisit(href);
        const hashIdx = href.indexOf("#");
        if (hashIdx >= 0) {
          navigate(href.slice(0, hashIdx));
          requestAnimationFrame(() => {
            window.location.hash = href.slice(hashIdx);
          });
        } else {
          navigate(href);
        }
      }
    } else if (e.key === "Escape") {
      if (query) {
        e.preventDefault();
        setQuery("");
      } else {
        inputRef.current?.blur();
      }
    }
  }

  // Precompute flat-index per group tile so highlight state threads through
  // grouped rendering without re-walking flatTiles in the render body.
  const flatIndexByScoredId = useMemo(() => {
    const map = new Map<string, number>();
    flatTiles.forEach((f, i) => {
      if (f.kind === "item") map.set(f.scored.item.id, i);
    });
    return map;
  }, [flatTiles]);
  const newChannelFlatIndex = flatTiles.findIndex((f) => f.kind === "new");

  const gridStyle: React.CSSProperties = {
    display: "grid",
    gridTemplateColumns: `repeat(auto-fill, minmax(${MIN_TILE_WIDTH}px, 1fr))`,
    gap: GRID_GAP,
  };

  return (
    <div
      className="flex flex-col flex-1 overflow-hidden"
      style={{ backgroundColor: t.surface }}
    >
      {/* Header + search */}
      <div
        className="flex flex-col gap-4 px-8 pt-8 pb-4"
        style={{ borderBottom: `1px solid ${t.surfaceBorder}` }}
      >
        <div className="flex flex-row items-center justify-between">
          <div className="flex flex-col">
            <h1
              className="m-0 font-semibold"
              style={{ fontSize: 22, color: t.text, lineHeight: "28px" }}
            >
              Spindrel
            </h1>
            <span style={{ fontSize: 13, color: t.textMuted }}>
              {isEmpty ? "Browse or search everything" : `Results for "${query}"`}
            </span>
          </div>
        </div>

        <div
          className="flex flex-row items-center gap-3 rounded-lg px-4"
          style={{
            backgroundColor: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            height: 48,
          }}
        >
          <Search size={18} color={t.textDim} />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search channels, bots, settings..."
            aria-label="Search"
            className="flex-1 bg-transparent border-none outline-none"
            style={{
              fontSize: 16,
              color: t.text,
              fontFamily: "inherit",
              minWidth: 0,
            }}
          />
          <kbd
            className="flex-shrink-0"
            style={{
              fontSize: 11,
              color: t.textDim,
              background: t.surface,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4,
              padding: "2px 6px",
            }}
          >
            Ctrl+K
          </kbd>
        </div>
      </div>

      {/* Scrollable grid area */}
      <div
        ref={gridScrollRef}
        className="flex-1 overflow-y-auto px-8 py-6"
      >
        <div ref={measureRef} style={{ width: "100%" }}>

          {/* Orchestrator hero / setup banners pinned above the grid */}
          {orchestratorChannel && (
            <Link
              to={`/channels/${orchestratorChannel.id}`}
              className="block no-underline mb-6"
              style={{ color: "inherit" }}
            >
              <div
                className="flex flex-row items-center gap-3 rounded-xl p-5"
                style={{
                  border: `1px solid ${t.accent}50`,
                  backgroundColor: t.accent + "08",
                  cursor: "pointer",
                }}
              >
                <div
                  className="flex items-center justify-center flex-shrink-0"
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 10,
                    backgroundColor: t.accent + "20",
                  }}
                >
                  <Compass size={22} color={t.accent} />
                </div>
                <div className="flex flex-col flex-1 min-w-0">
                  <span style={{ fontSize: 16, fontWeight: 700, color: t.text }}>Orchestrate</span>
                  <span style={{ fontSize: 13, color: t.textMuted }}>
                    Launchpad for pipelines, recent runs, and system status
                  </span>
                </div>
                <ChevronRight size={18} color={t.textDim} />
              </div>
            </Link>
          )}

          {showNoProviderBanner && (
            <Link
              to="/admin/providers"
              className="block no-underline mb-6"
              style={{ color: "inherit" }}
            >
              <div
                className="flex flex-row items-center gap-3 rounded-xl p-4"
                style={{
                  border: `1px solid ${t.warning}40`,
                  backgroundColor: t.warning + "08",
                  cursor: "pointer",
                }}
              >
                <AlertTriangle size={20} color={t.warning} />
                <div className="flex flex-col flex-1 min-w-0">
                  <span style={{ fontSize: 14, fontWeight: 600, color: t.text }}>
                    No LLM provider configured
                  </span>
                  <span style={{ fontSize: 12, color: t.textMuted }}>
                    Add one in Admin &gt; Providers to start chatting.
                  </span>
                </div>
                <ChevronRight size={16} color={t.textDim} />
              </div>
            </Link>
          )}

          {showGuidedSetup && (
            <button
              type="button"
              onClick={() =>
                ensureOrchestrator.mutate(undefined, {
                  onSuccess: (data) => navigate(`/channels/${data.id}`),
                })
              }
              disabled={ensureOrchestrator.isPending}
              className="block w-full text-left mb-6 cursor-pointer"
              style={{
                padding: 20,
                border: `1px solid ${t.accent}50`,
                backgroundColor: t.accent + "08",
                borderRadius: 12,
                font: "inherit",
                color: "inherit",
              }}
            >
              <div className="flex flex-row items-center gap-3">
                <div
                  className="flex items-center justify-center flex-shrink-0"
                  style={{
                    width: 44,
                    height: 44,
                    borderRadius: 10,
                    backgroundColor: t.accent + "20",
                  }}
                >
                  <Compass size={22} color={t.accent} />
                </div>
                <div className="flex flex-col flex-1 min-w-0">
                  <span style={{ fontSize: 16, fontWeight: 700, color: t.text }}>
                    {ensureOrchestrator.isPending ? "Setting up..." : "Guided Setup"}
                  </span>
                  <span style={{ fontSize: 13, color: t.textMuted }}>
                    AI-guided walkthrough for creating bots and channels
                  </span>
                </div>
                <ChevronRight size={18} color={t.textDim} />
              </div>
            </button>
          )}

          {/* Empty search result */}
          {!isEmpty && flatTiles.length === 0 && (
            <div
              className="text-center py-12"
              style={{ fontSize: 14, color: t.textDim }}
            >
              No results for &ldquo;{query}&rdquo;
            </div>
          )}

          {/* Grouped category grids */}
          {groups.map((group) => (
            <section
              key={group.category}
              className="mb-6"
              aria-label={group.category}
            >
              <div className="flex flex-row items-end justify-between mb-2">
                <h2
                  className="m-0"
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    letterSpacing: 0.5,
                    color: t.textDim,
                    textTransform: "uppercase",
                  }}
                >
                  {group.category}
                </h2>
                <span className="tabular-nums" style={{ fontSize: 11, color: t.textDim, opacity: 0.6 }}>
                  {group.items.length}
                </span>
              </div>
              <div role="grid" style={gridStyle}>
                {group.category === "Channels" && newChannelFlatIndex >= 0 && (
                  <div
                    ref={(el) => {
                      // NewChannelTile wraps its own Link ref inside; we only need
                      // to grab the anchor for scrollIntoView.
                      if (el) {
                        const anchor = el.querySelector("a");
                        tileRefs.current[newChannelFlatIndex] = anchor as HTMLAnchorElement | null;
                      }
                    }}
                  >
                    <NewChannelTile />
                  </div>
                )}
                {group.items.map((scored) => {
                  const flatIdx = flatIndexByScoredId.get(scored.item.id) ?? -1;
                  return (
                    <HomeGridTile
                      key={scored.item.id}
                      ref={(el) => {
                        if (flatIdx >= 0) tileRefs.current[flatIdx] = el;
                      }}
                      scored={scored}
                      selected={flatIdx === selectedIndex}
                      onHover={() => {
                        isKeyboardNav.current = false;
                        setSelectedIndex(flatIdx);
                      }}
                      onClick={() => {
                        recordPageVisit(scored.item.href);
                      }}
                    />
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
