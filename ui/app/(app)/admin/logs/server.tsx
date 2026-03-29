import { useState, useEffect, useRef, useCallback } from "react";
import { View, useWindowDimensions } from "react-native";
import { MobileHeader } from "@/src/components/layout/MobileHeader";
import { LogsTabBar } from "@/src/components/logs/LogsTabBar";
import { useServerLogs, useLogLevel, useSetLogLevel, type ServerLogEntry } from "@/src/api/hooks/useServerLogs";
import { useThemeTokens } from "@/src/theme/tokens";
import { Search, ArrowDown, Settings } from "lucide-react";

// ---------------------------------------------------------------------------
// Level colors
// ---------------------------------------------------------------------------
const LEVEL_COLORS: Record<string, string> = {
  DEBUG: "#22c55e",
  INFO: "#94a3b8",
  WARNING: "#eab308",
  ERROR: "#ef4444",
  CRITICAL: "#dc2626",
};

const LEVEL_OPTIONS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"];

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------
export default function ServerLogsScreen() {
  const t = useThemeTokens();
  const { width } = useWindowDimensions();
  const isMobile = width < 768;

  // Filters
  const [levelFilter, setLevelFilter] = useState("INFO");
  const [searchText, setSearchText] = useState("");

  // Accumulated entries
  const [entries, setEntries] = useState<ServerLogEntry[]>([]);
  const lastTimestampRef = useRef<number>(0);
  const initialLoadDone = useRef(false);

  // Auto-scroll state
  const scrollRef = useRef<HTMLDivElement>(null);
  const [stickToBottom, setStickToBottom] = useState(true);
  const userScrolledRef = useRef(false);

  // Server log level
  const { data: logLevelData } = useLogLevel();
  const setLogLevelMut = useSetLogLevel();
  const [showVerbosity, setShowVerbosity] = useState(false);

  // Polling query — fetches new entries every 2s
  const { data } = useServerLogs(
    {
      tail: initialLoadDone.current ? 200 : 500,
      level: levelFilter,
      search: searchText || undefined,
    },
    { refetchInterval: 2000 },
  );

  // Merge new entries, dedup by timestamp+message
  useEffect(() => {
    if (!data?.entries.length) {
      if (data && !initialLoadDone.current) {
        initialLoadDone.current = true;
      }
      return;
    }

    if (!initialLoadDone.current) {
      // First load — take all
      setEntries(data.entries);
      lastTimestampRef.current = data.entries[data.entries.length - 1].timestamp;
      initialLoadDone.current = true;
      return;
    }

    // Subsequent polls — append only new entries
    const lastTs = lastTimestampRef.current;
    const newEntries = data.entries.filter((e) => e.timestamp > lastTs);
    if (newEntries.length > 0) {
      setEntries((prev) => {
        const combined = [...prev, ...newEntries];
        // Cap at 2000 displayed
        return combined.length > 2000 ? combined.slice(-2000) : combined;
      });
      lastTimestampRef.current = newEntries[newEntries.length - 1].timestamp;
    }
  }, [data]);

  // Reset entries when filters change
  useEffect(() => {
    initialLoadDone.current = false;
    lastTimestampRef.current = 0;
    setEntries([]);
  }, [levelFilter, searchText]);

  // Auto-scroll to bottom
  useEffect(() => {
    if (stickToBottom && scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [entries, stickToBottom]);

  const handleScroll = useCallback(() => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    if (!atBottom && !userScrolledRef.current) {
      userScrolledRef.current = true;
      setStickToBottom(false);
    } else if (atBottom && userScrolledRef.current) {
      userScrolledRef.current = false;
      setStickToBottom(true);
    }
  }, []);

  const jumpToBottom = useCallback(() => {
    setStickToBottom(true);
    userScrolledRef.current = false;
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, []);

  return (
    <View className="flex-1 bg-surface">
      <MobileHeader title="Server Logs" subtitle={`${entries.length} entries`} />
      <LogsTabBar active="server" />

      {/* Toolbar */}
      <div
        style={{
          display: "flex",
          gap: 8,
          padding: isMobile ? "8px 12px" : "8px 20px",
          borderBottom: `1px solid ${t.surfaceRaised}`,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        {/* Search */}
        <div style={{ position: "relative", flex: isMobile ? "1 1 100%" : "0 0 auto" }}>
          <Search size={12} style={{ position: "absolute", left: 8, top: 8, color: t.textDim }} />
          <input
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            placeholder="Search logs..."
            style={{
              background: t.surfaceRaised,
              color: t.text,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6,
              padding: "5px 10px 5px 26px",
              fontSize: 12,
              outline: "none",
              width: isMobile ? "100%" : 200,
            }}
          />
        </div>

        {/* Level filter */}
        <select
          value={levelFilter}
          onChange={(e) => setLevelFilter(e.target.value)}
          style={{
            background: t.surfaceRaised,
            color: t.textMuted,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 6,
            padding: "5px 10px",
            fontSize: 12,
            outline: "none",
          }}
        >
          {LEVEL_OPTIONS.map((lvl) => (
            <option key={lvl} value={lvl}>
              {lvl}+
            </option>
          ))}
        </select>

        {/* Server verbosity toggle */}
        <div style={{ position: "relative" }}>
          <button
            onClick={() => setShowVerbosity(!showVerbosity)}
            style={{
              display: "flex",
              alignItems: "center",
              gap: 4,
              background: t.surfaceRaised,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 6,
              padding: "5px 10px",
              fontSize: 12,
              color: t.textMuted,
              cursor: "pointer",
            }}
          >
            <Settings size={11} />
            Server: {logLevelData?.level ?? "..."}
          </button>
          {showVerbosity && (
            <div
              style={{
                position: "absolute",
                top: "100%",
                left: 0,
                marginTop: 4,
                background: t.surface,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 6,
                boxShadow: "0 4px 12px rgba(0,0,0,0.2)",
                zIndex: 10,
                minWidth: 140,
              }}
            >
              {LEVEL_OPTIONS.map((lvl) => (
                <button
                  key={lvl}
                  onClick={() => {
                    setLogLevelMut.mutate(lvl);
                    setShowVerbosity(false);
                  }}
                  style={{
                    display: "block",
                    width: "100%",
                    textAlign: "left",
                    padding: "6px 12px",
                    fontSize: 12,
                    color: lvl === logLevelData?.level ? t.text : t.textMuted,
                    fontWeight: lvl === logLevelData?.level ? 600 : 400,
                    background: "transparent",
                    border: "none",
                    cursor: "pointer",
                  }}
                >
                  {lvl}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Log output */}
      <div
        ref={scrollRef}
        onScroll={handleScroll}
        style={{
          flex: 1,
          overflow: "auto",
          fontFamily: "monospace",
          fontSize: 12,
          lineHeight: "1.6",
          padding: isMobile ? "8px 8px" : "8px 20px",
          background: t.surface,
        }}
      >
        {entries.map((entry, i) => (
          <div
            key={`${entry.timestamp}-${i}`}
            style={{
              color: LEVEL_COLORS[entry.level] ?? t.text,
              whiteSpace: "pre-wrap",
              wordBreak: "break-all",
            }}
          >
            {entry.formatted}
          </div>
        ))}
        {entries.length === 0 && (
          <div style={{ padding: 40, textAlign: "center", color: t.textDim }}>
            No log entries.
          </div>
        )}
      </div>

      {/* Jump to bottom button */}
      {!stickToBottom && (
        <button
          onClick={jumpToBottom}
          style={{
            position: "absolute",
            bottom: 20,
            right: 20,
            display: "flex",
            alignItems: "center",
            gap: 4,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
            borderRadius: 8,
            padding: "8px 14px",
            fontSize: 12,
            color: t.textMuted,
            cursor: "pointer",
            boxShadow: "0 2px 8px rgba(0,0,0,0.2)",
            zIndex: 10,
          }}
        >
          <ArrowDown size={12} /> Jump to bottom
        </button>
      )}
    </View>
  );
}
