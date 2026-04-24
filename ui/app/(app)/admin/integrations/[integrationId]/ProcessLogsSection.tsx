import { useEffect, useRef, useState } from "react";
import { ChevronDown, ChevronRight, Terminal } from "lucide-react";
import { useProcessLogs } from "@/src/api/hooks/useIntegrations";
import { ActionButton, SettingsGroupLabel } from "@/src/components/shared/SettingsControls";

export function ProcessLogsSection({
  integrationId,
  processRunning,
}: {
  integrationId: string;
  processRunning: boolean;
}) {
  const { data } = useProcessLogs(integrationId);
  const [expanded, setExpanded] = useState(processRunning);
  const scrollRef = useRef<HTMLPreElement>(null);
  const wasAtBottomRef = useRef(true);
  const lines = data?.lines ?? [];
  const total = data?.total ?? 0;

  useEffect(() => {
    const el = scrollRef.current;
    if (!el || !wasAtBottomRef.current) return;
    el.scrollTop = el.scrollHeight;
  }, [lines.length]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    wasAtBottomRef.current = el.scrollTop + el.clientHeight >= el.scrollHeight - 20;
  };

  if (total === 0 && !processRunning) return null;

  return (
    <div className="flex flex-col gap-3">
      <SettingsGroupLabel
        label="Process Logs"
        count={total}
        icon={<Terminal size={13} className="text-text-dim" />}
        action={
          <ActionButton
            label={expanded ? "Hide" : "Show"}
            onPress={() => setExpanded((current) => !current)}
            variant="secondary"
            size="small"
            icon={expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
          />
        }
      />
      {expanded && (
        <pre
          ref={scrollRef}
          onScroll={handleScroll}
          className="m-0 max-h-[400px] overflow-auto rounded-md bg-surface-raised/45 px-3 py-2 font-mono text-[11px] leading-relaxed text-text whitespace-pre-wrap break-words"
        >
          {lines.length === 0 ? (
            <span className="text-text-dim">No log output yet</span>
          ) : (
            lines.map((line) => (
              <div key={line.index}>
                <span className="mr-2 text-text-dim">{new Date(line.ts).toLocaleTimeString()}</span>
                {line.text}
              </div>
            ))
          )}
        </pre>
      )}
    </div>
  );
}
