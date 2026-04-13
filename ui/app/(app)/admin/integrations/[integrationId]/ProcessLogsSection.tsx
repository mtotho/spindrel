import { useState, useRef, useEffect } from "react";
import { ChevronDown, ChevronRight, Terminal } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";
import { useProcessLogs } from "@/src/api/hooks/useIntegrations";

export function ProcessLogsSection({
  integrationId,
  processRunning,
}: {
  integrationId: string;
  processRunning: boolean;
}) {
  const t = useThemeTokens();
  const { data } = useProcessLogs(integrationId);
  const [expanded, setExpanded] = useState(processRunning);
  const scrollRef = useRef<HTMLPreElement>(null);
  const wasAtBottomRef = useRef(true);

  const lines = data?.lines ?? [];
  const total = data?.total ?? 0;

  // Auto-scroll to bottom when new lines arrive, if already at bottom
  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !wasAtBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    wasAtBottomRef.current =
      el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
  };

  if (total === 0 && !processRunning) return null;

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 10,
        padding: 14,
        background: t.inputBg,
        borderRadius: 8,
        border: `1px solid ${t.surfaceRaised}`,
      }}
    >
      <button
        onClick={() => setExpanded(!expanded)}
        style={{
          display: "flex",
          alignItems: "center",
          gap: 6,
          background: "none",
          border: "none",
          cursor: "pointer",
          padding: 0,
        }}
      >
        {expanded ? (
          <ChevronDown size={12} color={t.textDim} />
        ) : (
          <ChevronRight size={12} color={t.textDim} />
        )}
        <Terminal size={12} color={t.textDim} />
        <span
          style={{
            fontSize: 10,
            fontWeight: 700,
            color: t.textDim,
            textTransform: "uppercase",
            letterSpacing: 0.6,
          }}
        >
          Process Logs
        </span>
        {total > 0 && (
          <span
            style={{
              fontSize: 10,
              color: t.textMuted,
              fontFamily: "monospace",
            }}
          >
            ({total} lines)
          </span>
        )}
      </button>

      {expanded && (
        <pre
          ref={scrollRef}
          onScroll={handleScroll}
          style={{
            margin: 0,
            padding: 10,
            borderRadius: 6,
            background: t.surface,
            border: `1px solid ${t.surfaceBorder}`,
            fontSize: 11,
            fontFamily: "monospace",
            color: t.text,
            overflow: "auto",
            maxHeight: 400,
            whiteSpace: "pre-wrap",
            wordBreak: "break-word",
            lineHeight: 1.5,
          }}
        >
          {lines.length === 0 ? (
            <span style={{ color: t.textDim }}>No log output yet</span>
          ) : (
            lines.map((line) => (
              <div key={line.index}>
                <span style={{ color: t.textDim, marginRight: 8 }}>
                  {new Date(line.ts).toLocaleTimeString()}
                </span>
                {line.text}
              </div>
            ))
          )}
        </pre>
      )}
    </div>
  );
}
