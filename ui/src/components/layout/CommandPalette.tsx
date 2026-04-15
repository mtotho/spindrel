/**
 * Global command palette (Ctrl+K / Cmd+K) for quick navigation.
 * Fuzzy-searches channels, bots, admin screens, skills, and integration pages.
 */
import { useEffect, useRef, useState, useMemo, useCallback } from "react";
import { useNavigate } from "react-router-dom";
import ReactDOM from "react-dom";
import {
  Search,
  Hash,
  Bot,
  Settings,
  Plug,
  Server,
  Cable,
  Layers,
  Wrench,
  BookOpen,
  FileText,
  Paperclip,
  Boxes,
  ClipboardList,
  Zap,
  Lock,
  Shield,
  ShieldCheck,
  Key,
  Webhook,
  FileCode,
  BarChart3,
  Activity,
  Users,
  ScrollText,
  HardDrive,
  Code2,
  CornerDownLeft,
  Brain,
} from "lucide-react";
import { useChannels } from "../../api/hooks/useChannels";
import { useBots } from "../../api/hooks/useBots";
import { useSidebarSections } from "../../api/hooks/useIntegrations";
import { useThemeTokens } from "../../theme/tokens";
import { useUIStore } from "../../stores/ui";

// ---------------------------------------------------------------------------
// Fuzzy matching
// ---------------------------------------------------------------------------

/** Returns [score, matchedIndices[]]. Score 0 = no match. */
function fuzzyMatch(query: string, target: string): [number, number[]] {
  const q = query.toLowerCase();
  const t = target.toLowerCase();
  if (q.length === 0) return [1, []];

  // Exact substring — highlight the contiguous range
  const substringIdx = t.indexOf(q);
  if (substringIdx >= 0) {
    const indices = Array.from({ length: q.length }, (_, i) => substringIdx + i);
    return [100 + (q.length / t.length) * 50, indices];
  }

  let qi = 0;
  let score = 0;
  let consecutive = 0;
  let lastMatch = -1;
  const indices: number[] = [];

  for (let ti = 0; ti < t.length && qi < q.length; ti++) {
    if (t[ti] === q[qi]) {
      indices.push(ti);
      qi++;
      score += 1 + consecutive * 2;
      if (ti === 0 || t[ti - 1] === " " || t[ti - 1] === "-" || t[ti - 1] === "/") {
        score += 5;
      }
      if (lastMatch >= 0 && ti - lastMatch === 1) {
        consecutive++;
      } else {
        consecutive = 0;
      }
      lastMatch = ti;
    }
  }

  return qi === q.length ? [score, indices] : [0, []];
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface PaletteItem {
  id: string;
  label: string;
  hint?: string;
  href: string;
  icon: React.ComponentType<{ size: number; color: string }>;
  category: string;
}

interface ScoredItem {
  item: PaletteItem;
  score: number;
  matchIndices: number[];
}

// ---------------------------------------------------------------------------
// Static admin items
// ---------------------------------------------------------------------------

const ADMIN_ITEMS: PaletteItem[] = [
  // -- Configure --
  { id: "nav-bots", label: "Bots", href: "/admin/bots", icon: Bot, category: "Configure" },
  { id: "nav-integrations", label: "Integrations", href: "/admin/integrations", icon: Plug, category: "Configure" },
  { id: "nav-providers", label: "Providers", href: "/admin/providers", icon: Server, category: "Configure" },
  { id: "nav-mcp", label: "MCP Servers", href: "/admin/mcp-servers", icon: Cable, category: "Configure" },
  { id: "nav-carapaces", label: "Capabilities", href: "/admin/carapaces", icon: Layers, category: "Configure" },
  { id: "nav-tools", label: "Tools", href: "/admin/tools", icon: Wrench, category: "Configure" },
  { id: "nav-skills", label: "Skills", href: "/admin/skills", icon: BookOpen, category: "Configure" },
  { id: "nav-templates", label: "Templates", href: "/admin/prompt-templates", icon: FileText, category: "Configure" },
  { id: "nav-attachments", label: "Attachments", href: "/admin/attachments", icon: Paperclip, category: "Configure" },
  { id: "nav-docker", label: "Docker Stacks", href: "/admin/docker-stacks", icon: Boxes, category: "Configure" },
  // -- Automate --
  { id: "nav-learning", label: "Learning Center", href: "/admin/learning", icon: Brain, category: "Automate" },
  { id: "nav-learning-overview", label: "Learning: Overview", hint: "Learning Center", href: "/admin/learning#Overview", icon: Brain, category: "Automate" },
  { id: "nav-learning-dreaming", label: "Learning: Dreaming", hint: "Learning Center", href: "/admin/learning#Dreaming", icon: Brain, category: "Automate" },
  { id: "nav-learning-skills", label: "Learning: Skills", hint: "Learning Center", href: "/admin/learning#Skills", icon: Brain, category: "Automate" },
  { id: "nav-tasks", label: "Tasks", href: "/admin/tasks", icon: ClipboardList, category: "Automate" },
  { id: "nav-workflows", label: "Workflows", href: "/admin/workflows", icon: Zap, category: "Automate" },
  // -- Security --
  { id: "nav-secrets", label: "Secrets", href: "/admin/secret-values", icon: Lock, category: "Security" },
  { id: "nav-policies", label: "Policies", href: "/admin/tool-policies", icon: Shield, category: "Security" },
  { id: "nav-approvals", label: "Approvals", href: "/admin/approvals", icon: ShieldCheck, category: "Security" },
  // -- Developer --
  { id: "nav-apikeys", label: "API Keys", href: "/admin/api-keys", icon: Key, category: "Developer" },
  { id: "nav-webhooks", label: "Webhooks", href: "/admin/webhooks", icon: Webhook, category: "Developer" },
  { id: "nav-apidocs", label: "API Docs", href: "/admin/api-docs", icon: FileCode, category: "Developer" },
  // -- Monitor --
  { id: "nav-usage", label: "Usage", href: "/admin/usage", icon: BarChart3, category: "Monitor" },
  { id: "nav-usage-overview", label: "Usage: Overview", hint: "Usage", href: "/admin/usage#Overview", icon: BarChart3, category: "Monitor" },
  { id: "nav-usage-forecast", label: "Usage: Forecast", hint: "Usage", href: "/admin/usage#Forecast", icon: BarChart3, category: "Monitor" },
  { id: "nav-usage-logs", label: "Usage: Logs", hint: "Usage", href: "/admin/usage#Logs", icon: BarChart3, category: "Monitor" },
  { id: "nav-usage-charts", label: "Usage: Charts", hint: "Usage", href: "/admin/usage#Charts", icon: BarChart3, category: "Monitor" },
  { id: "nav-usage-limits", label: "Usage: Limits", hint: "Usage", href: "/admin/usage#Limits", icon: BarChart3, category: "Monitor" },
  { id: "nav-usage-alerts", label: "Usage: Alerts", hint: "Usage", href: "/admin/usage#Alerts", icon: BarChart3, category: "Monitor" },
  { id: "nav-toolcalls", label: "Tool Calls", href: "/admin/tool-calls", icon: Activity, category: "Monitor" },
  { id: "nav-users", label: "Users", href: "/admin/users", icon: Users, category: "Monitor" },
  { id: "nav-logs", label: "Logs", href: "/admin/logs", icon: ScrollText, category: "Monitor" },
  { id: "nav-logs-traces", label: "Logs: Traces", hint: "Logs", href: "/admin/logs/traces", icon: ScrollText, category: "Monitor" },
  { id: "nav-logs-server", label: "Logs: Server", hint: "Logs", href: "/admin/logs/server", icon: ScrollText, category: "Monitor" },
  { id: "nav-logs-fallbacks", label: "Logs: Fallbacks", hint: "Logs", href: "/admin/logs/fallbacks", icon: ScrollText, category: "Monitor" },
  { id: "nav-diagnostics", label: "Diagnostics", href: "/admin/diagnostics", icon: HardDrive, category: "Monitor" },
  { id: "nav-config", label: "Config State", href: "/admin/config-state", icon: Code2, category: "Monitor" },
  // -- Settings (top-level + sub-pages) --
  { id: "nav-settings", label: "Settings", href: "/settings", icon: Settings, category: "Settings" },
  { id: "nav-settings-global", label: "Settings: Global", hint: "Settings", href: "/settings#Global", icon: Settings, category: "Settings" },
  { id: "nav-settings-system", label: "Settings: System", hint: "Settings", href: "/settings#System", icon: Settings, category: "Settings" },
  { id: "nav-settings-paths", label: "Settings: Paths", hint: "Settings", href: "/settings#Paths", icon: Settings, category: "Settings" },
  { id: "nav-settings-general", label: "Settings: General", hint: "Settings", href: "/settings#General", icon: Settings, category: "Settings" },
  { id: "nav-settings-agent", label: "Settings: Agent", hint: "Settings", href: "/settings#Agent", icon: Settings, category: "Settings" },
  { id: "nav-settings-chat-history", label: "Settings: Chat History", hint: "Settings", href: "/settings#Chat History", icon: Settings, category: "Settings" },
  { id: "nav-settings-embeddings", label: "Settings: Embeddings & RAG", hint: "Settings", href: "/settings#Embeddings & RAG", icon: Settings, category: "Settings" },
  { id: "nav-settings-reranking", label: "Settings: RAG Re-ranking", hint: "Settings", href: "/settings#RAG Re-ranking", icon: Settings, category: "Settings" },
  { id: "nav-settings-attachments", label: "Settings: Attachments", hint: "Settings", href: "/settings#Attachments", icon: Settings, category: "Settings" },
  { id: "nav-settings-memory", label: "Settings: Memory & Learning", hint: "Settings", href: "/settings#Memory & Learning", icon: Settings, category: "Settings" },
  { id: "nav-settings-heartbeat", label: "Settings: Heartbeat", hint: "Settings", href: "/settings#Heartbeat", icon: Settings, category: "Settings" },
  { id: "nav-settings-tool-summarization", label: "Settings: Tool Summarization", hint: "Settings", href: "/settings#Tool Summarization", icon: Settings, category: "Settings" },
  { id: "nav-settings-tool-policies", label: "Settings: Tool Policies", hint: "Settings", href: "/settings#Tool Policies", icon: Settings, category: "Settings" },
  { id: "nav-settings-image-gen", label: "Settings: Image Generation", hint: "Settings", href: "/settings#Image Generation", icon: Settings, category: "Settings" },
  { id: "nav-settings-stt", label: "Settings: Speech-to-Text", hint: "Settings", href: "/settings#Speech-to-Text", icon: Settings, category: "Settings" },
  { id: "nav-settings-prompt-gen", label: "Settings: Prompt Generation", hint: "Settings", href: "/settings#Prompt Generation", icon: Settings, category: "Settings" },
  { id: "nav-settings-docker", label: "Settings: Docker Stacks", hint: "Settings", href: "/settings#Docker Stacks", icon: Settings, category: "Settings" },
  { id: "nav-settings-rate-limiting", label: "Settings: API Rate Limiting", hint: "Settings", href: "/settings#API Rate Limiting", icon: Settings, category: "Settings" },
  { id: "nav-settings-security", label: "Settings: Security", hint: "Settings", href: "/settings#Security", icon: Settings, category: "Settings" },
  { id: "nav-settings-data-retention", label: "Settings: Data Retention", hint: "Settings", href: "/settings#Data Retention", icon: Settings, category: "Settings" },
  { id: "nav-settings-backup", label: "Settings: Backup", hint: "Settings", href: "/settings#Backup", icon: Settings, category: "Settings" },
];

// ---------------------------------------------------------------------------
// Highlighted label renderer
// ---------------------------------------------------------------------------

function HighlightedLabel({
  text,
  indices,
  color,
  accentColor,
}: {
  text: string;
  indices: number[];
  color: string;
  accentColor: string;
}) {
  if (indices.length === 0) {
    return <>{text}</>;
  }
  const set = new Set(indices);
  const parts: React.ReactNode[] = [];
  let run = "";
  let inMatch = false;

  for (let i = 0; i <= text.length; i++) {
    const isMatch = set.has(i);
    if (i === text.length || isMatch !== inMatch) {
      if (run) {
        parts.push(
          inMatch ? (
            <span key={i} style={{ color: accentColor, fontWeight: 600 }}>{run}</span>
          ) : (
            <span key={i} style={{ color }}>{run}</span>
          ),
        );
      }
      run = "";
      inMatch = isMatch;
    }
    if (i < text.length) run += text[i];
  }

  return <>{parts}</>;
}

// ---------------------------------------------------------------------------
// Hook: global keyboard shortcut
// ---------------------------------------------------------------------------

export function useCommandPaletteShortcut() {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    function handler(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
    }
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);

  return { open, setOpen };
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const t = useThemeTokens();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const closeMobileSidebar = useUIStore((s) => s.closeMobileSidebar);
  const [query, setQuery] = useState("");
  const [selectedIndex, setSelectedIndex] = useState(0);

  // Animation state
  const [mounted, setMounted] = useState(false);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (open) {
      setMounted(true);
      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          setVisible(true);
          // Focus immediately once the DOM is there
          inputRef.current?.focus();
        });
      });
    } else {
      setVisible(false);
      const timer = setTimeout(() => setMounted(false), 180);
      return () => clearTimeout(timer);
    }
  }, [open]);

  // Data sources
  const { data: channels } = useChannels();
  const { data: bots } = useBots();
  const { data: sidebarData } = useSidebarSections();

  // Build flat item list
  const allItems = useMemo<PaletteItem[]>(() => {
    const items: PaletteItem[] = [];

    if (channels) {
      for (const ch of channels) {
        items.push({
          id: `ch-${ch.id}`,
          label: ch.name,
          hint: ch.integration ? `${ch.integration}` : undefined,
          href: `/channels/${ch.id}`,
          icon: Hash,
          category: "Channels",
        });
      }
    }

    if (bots) {
      for (const bot of bots) {
        items.push({
          id: `bot-${bot.id}`,
          label: bot.name,
          hint: "Edit bot",
          href: `/admin/bots/${bot.id}`,
          icon: Bot,
          category: "Bots",
        });
      }
    }

    items.push(...ADMIN_ITEMS);

    if (sidebarData?.sections) {
      for (const section of sidebarData.sections) {
        for (const item of section.items) {
          items.push({
            id: `int-${section.id}-${item.href}`,
            label: item.label,
            hint: section.title,
            href: item.href,
            icon: Plug,
            category: section.title,
          });
        }
      }
    }

    return items;
  }, [channels, bots, sidebarData]);

  // Filter + sort by fuzzy score, preserving match indices
  const scoredResults = useMemo<ScoredItem[]>(() => {
    if (!query.trim()) {
      // Group by category for empty state
      return allItems.slice(0, 24).map((item) => ({ item, score: 1, matchIndices: [] }));
    }

    return allItems
      .map((item) => {
        const [labelScore, labelIndices] = fuzzyMatch(query, item.label);
        const [hintScore] = item.hint ? fuzzyMatch(query, item.hint) : [0, []];
        const [catScore] = fuzzyMatch(query, item.category);
        const bestScore = Math.max(labelScore, hintScore * 0.5, catScore * 0.3);
        return {
          item,
          score: bestScore,
          matchIndices: labelScore >= hintScore * 0.5 ? labelIndices : [],
        };
      })
      .filter((r) => r.score > 0)
      .sort((a, b) => b.score - a.score)
      .slice(0, 30);
  }, [query, allItems]);

  // Group results by category for display
  const groupedResults = useMemo(() => {
    const groups: { category: string; items: { scored: ScoredItem; flatIndex: number }[] }[] = [];
    const catMap = new Map<string, { scored: ScoredItem; flatIndex: number }[]>();
    let flatIndex = 0;

    for (const scored of scoredResults) {
      const cat = scored.item.category;
      let arr = catMap.get(cat);
      if (!arr) {
        arr = [];
        catMap.set(cat, arr);
        groups.push({ category: cat, items: arr });
      }
      arr.push({ scored, flatIndex });
      flatIndex++;
    }

    return { groups, totalCount: flatIndex };
  }, [scoredResults]);

  // Reset state on open
  useEffect(() => {
    if (open) {
      setQuery("");
      setSelectedIndex(0);
    }
  }, [open]);

  // Scroll selected item into view
  useEffect(() => {
    if (!listRef.current) return;
    const el = listRef.current.querySelector(`[data-idx="${selectedIndex}"]`) as HTMLElement | null;
    el?.scrollIntoView({ block: "nearest" });
  }, [selectedIndex]);

  const go = useCallback(
    (href: string) => {
      onClose();
      closeMobileSidebar();
      const hashIdx = href.indexOf("#");
      if (hashIdx >= 0) {
        const path = href.slice(0, hashIdx);
        const hash = href.slice(hashIdx);
        // Navigate to the path first, then set the hash so useHashTab picks it up
        navigate(path);
        requestAnimationFrame(() => {
          window.location.hash = hash;
        });
      } else {
        navigate(href);
      }
    },
    [onClose, closeMobileSidebar, navigate],
  );

  const totalCount = groupedResults.totalCount;

  const onKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        onClose();
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelectedIndex((i) => (totalCount > 0 ? Math.min(i + 1, totalCount - 1) : 0));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelectedIndex((i) => Math.max(i - 1, 0));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const scored = scoredResults[selectedIndex];
        if (scored) go(scored.item.href);
      }
    },
    [onClose, scoredResults, selectedIndex, go, totalCount],
  );

  if (!mounted || typeof document === "undefined") return null;

  const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent);
  const modKey = isMac ? "\u2318" : "Ctrl";

  return ReactDOM.createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          backdropFilter: "blur(4px)",
          WebkitBackdropFilter: "blur(4px)",
          zIndex: 10030,
          opacity: visible ? 1 : 0,
          transition: "opacity 160ms ease-out",
        }}
      />
      {/* Palette */}
      <div
        style={{
          position: "fixed",
          top: "min(20%, 160px)",
          left: "50%",
          width: 560,
          maxWidth: "92vw",
          maxHeight: "min(70vh, 480px)",
          zIndex: 10031,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.35), 0 0 0 1px rgba(255,255,255,0.04) inset",
          display: "flex",
          flexDirection: "column",
          overflow: "hidden",
          // Animate in/out
          opacity: visible ? 1 : 0,
          transform: visible
            ? "translate(-50%, 0) scale(1)"
            : "translate(-50%, -8px) scale(0.98)",
          transition: visible
            ? "opacity 160ms ease-out, transform 160ms ease-out"
            : "opacity 120ms ease-in, transform 120ms ease-in",
        }}
      >
        {/* Search input */}
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 10,
            padding: "14px 16px",
            borderBottom: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}><Search size={16} color={t.textDim} /></span>
          <input
            ref={inputRef}
            autoFocus
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setSelectedIndex(0);
            }}
            onKeyDown={onKeyDown}
            placeholder="Search channels, bots, settings..."
            style={{
              flex: 1,
              background: "none",
              border: "none",
              outline: "none",
              fontSize: 15,
              color: t.text,
              fontFamily: "inherit",
            }}
          />
          <kbd
            style={{
              fontSize: 11,
              color: t.textDim,
              background: t.surface,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 4,
              padding: "2px 6px",
              flexShrink: 0,
            }}
          >
            esc
          </kbd>
        </div>

        {/* Results list */}
        <div
          ref={listRef}
          style={{
            overflow: "auto",
            flex: 1,
            padding: "4px 0",
          }}
        >
          {scoredResults.length === 0 && query.trim() && (
            <div
              style={{
                padding: "32px 16px",
                textAlign: "center",
                fontSize: 13,
                color: t.textDim,
              }}
            >
              No results for &ldquo;{query}&rdquo;
            </div>
          )}
          {groupedResults.groups.map((group) => (
            <div key={group.category}>
              {/* Category header */}
              <div
                style={{
                  padding: "8px 18px 4px",
                  fontSize: 11,
                  fontWeight: 600,
                  letterSpacing: 0.3,
                  color: t.textDim,
                  textTransform: "uppercase",
                }}
              >
                {group.category}
              </div>
              {group.items.map(({ scored, flatIndex }) => {
                const { item, matchIndices } = scored;
                const Icon = item.icon;
                const selected = flatIndex === selectedIndex;
                return (
                  <div
                    key={item.id}
                    data-idx={flatIndex}
                    onClick={() => go(item.href)}
                    onMouseEnter={() => setSelectedIndex(flatIndex)}
                    style={{
                      display: "flex", flexDirection: "row",
                      alignItems: "center",
                      gap: 10,
                      padding: "7px 14px",
                      margin: "0 6px",
                      borderRadius: 6,
                      cursor: "pointer",
                      backgroundColor: selected ? t.accentSubtle : "transparent",
                      transition: "background-color 80ms ease",
                    }}
                  >
                    <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}>
                      <Icon size={16} color={selected ? t.accent : t.textDim} />
                    </span>
                    <span
                      style={{
                        flex: 1,
                        fontSize: 14,
                        color: selected ? t.text : t.textMuted,
                        fontWeight: selected ? 500 : 400,
                        overflow: "hidden",
                        textOverflow: "ellipsis",
                        whiteSpace: "nowrap",
                      }}
                    >
                      <HighlightedLabel
                        text={item.label}
                        indices={matchIndices}
                        color={selected ? t.text : t.textMuted}
                        accentColor={t.accent}
                      />
                    </span>
                    {item.hint && (
                      <span
                        style={{
                          fontSize: 12,
                          color: t.textDim,
                          whiteSpace: "nowrap",
                          flexShrink: 0,
                        }}
                      >
                        {item.hint}
                      </span>
                    )}
                    {selected && (
                      <span style={{ flexShrink: 0, display: "flex", flexDirection: "row" }}>
                        <CornerDownLeft size={12} color={t.textDim} />
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Footer hint */}
        <div
          style={{
            display: "flex", flexDirection: "row",
            alignItems: "center",
            gap: 16,
            padding: "8px 16px",
            borderTop: `1px solid ${t.surfaceBorder}`,
            fontSize: 11,
            color: t.textDim,
          }}
        >
          <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Kbd t={t}>&uarr;</Kbd>
            <Kbd t={t}>&darr;</Kbd>
            navigate
          </span>
          <span style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Kbd t={t}>&crarr;</Kbd>
            open
          </span>
          <span style={{ marginLeft: "auto", display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
            <Kbd t={t}>{modKey}+K</Kbd>
            toggle
          </span>
        </div>
      </div>
    </>,
    document.body,
  );
}

// Small kbd tag component to reduce repetition
function Kbd({ t, children }: { t: ReturnType<typeof useThemeTokens>; children: React.ReactNode }) {
  return (
    <kbd
      style={{
        background: t.surface,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 3,
        padding: "1px 5px",
        fontSize: 10,
        fontFamily: "inherit",
        lineHeight: "16px",
      }}
    >
      {children}
    </kbd>
  );
}
