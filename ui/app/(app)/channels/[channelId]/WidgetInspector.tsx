/**
 * WidgetInspector — live debug trace for a pinned HTML widget.
 *
 * Reads the per-pin event ring at GET /api/v1/widget-debug/events, rendered
 * as a newest-first timeline of tool calls, attachment loads, JS errors,
 * unhandled promise rejections, console output, and explicit
 * spindrel.log.* entries. Poll cadence is 2s while open; the drawer
 * becomes inert (no polls, no listeners) the moment it closes.
 *
 * Paired with the ambient capture hooks in InteractiveHtmlRenderer.tsx's
 * preamble. The bot reads the same ring via `inspect_widget_pin(pin_id)`.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { X, RefreshCw, Trash2, ChevronDown, ChevronRight } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { writeToClipboard } from "@/src/utils/clipboard";

interface WidgetDebugEvent {
  kind: string;
  ts?: number | null;
  ts_server?: number;
  [key: string]: unknown;
}

interface EventsResponse {
  pin_id: string;
  events: WidgetDebugEvent[];
}

interface Props {
  pinId: string;
  pinLabel?: string;
  onClose: () => void;
}

const KIND_ACCENT: Record<string, string> = {
  "tool-call": "text-accent",
  "load-attachment": "text-accent",
  "load-asset": "text-accent",
  error: "text-red-400",
  rejection: "text-red-400",
  console: "text-text-muted",
  log: "text-text-muted",
};

function kindBadgeClass(kind: string): string {
  return KIND_ACCENT[kind] ?? "text-text-muted";
}

function formatTimestamp(ev: WidgetDebugEvent): string {
  const ms = (typeof ev.ts === "number" ? ev.ts : null) ??
    (ev.ts_server ? ev.ts_server * 1000 : Date.now());
  const d = new Date(ms);
  return d.toLocaleTimeString("en-US", { hour12: false }) +
    "." + String(d.getMilliseconds()).padStart(3, "0");
}

function primaryLine(ev: WidgetDebugEvent): string {
  switch (ev.kind) {
    case "tool-call": {
      const tool = String(ev.tool ?? "?");
      const ok = ev.ok === false ? "✗" : "✓";
      const dur = ev.durationMs != null ? ` · ${ev.durationMs}ms` : "";
      const tail = ev.ok === false ? ` — ${ev.error ?? ""}` : "";
      return `${ok} ${tool}${dur}${tail}`;
    }
    case "load-attachment": {
      const id = String(ev.id ?? "?");
      const ok = ev.ok === false ? "✗" : "✓";
      const size = ev.sizeBytes != null ? ` · ${ev.sizeBytes}B` : "";
      return `${ok} attachment ${id.slice(0, 8)}…${size}`;
    }
    case "load-asset": {
      const path = String(ev.path ?? "?");
      const ok = ev.ok === false ? "✗" : "✓";
      return `${ok} asset ${path}`;
    }
    case "error":
      return `error: ${String(ev.message ?? "unknown")}`;
    case "rejection":
      return `rejection: ${String(ev.reason ?? "unknown")}`;
    case "console": {
      const level = String(ev.level ?? "log");
      const args = Array.isArray(ev.args) ? ev.args : [];
      const first = args.length ? JSON.stringify(args[0]) : "";
      return `console.${level}: ${first.length > 120 ? first.slice(0, 120) + "…" : first}`;
    }
    case "log":
      return `${String(ev.level ?? "info")}: ${String(ev.message ?? "")}`;
    default:
      return ev.kind;
  }
}

function EventRow({ ev, idx }: { ev: WidgetDebugEvent; idx: number }) {
  const [open, setOpen] = useState(false);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const toggle = useCallback(() => setOpen((v) => !v), []);
  const handleCopy = useCallback(async () => {
    try {
      await writeToClipboard(JSON.stringify(ev, null, 2));
      setCopyState("copied");
    } catch {
      setCopyState("error");
    }
  }, [ev]);

  useEffect(() => {
    if (copyState === "idle") return;
    const id = window.setTimeout(() => setCopyState("idle"), 1500);
    return () => window.clearTimeout(id);
  }, [copyState]);

  const color = kindBadgeClass(ev.kind);
  return (
    <div className="border-b border-surface-border/60 last:border-0">
      <button
        type="button"
        onClick={toggle}
        className="w-full flex items-start gap-2 px-3 py-2 text-left hover:bg-surface-overlay transition-colors"
      >
        {open ? (
          <ChevronDown size={12} className="mt-0.5 shrink-0 text-text-muted" />
        ) : (
          <ChevronRight size={12} className="mt-0.5 shrink-0 text-text-muted" />
        )}
        <span className="text-[10px] font-mono text-text-dim shrink-0 mt-0.5">
          {formatTimestamp(ev)}
        </span>
        <span className={`text-[10px] font-semibold uppercase tracking-wide shrink-0 ${color}`}>
          {ev.kind}
        </span>
        <span className="flex-1 text-[12px] font-mono truncate text-text">
          {primaryLine(ev)}
        </span>
      </button>
      {open && (
        <div className="px-3 pb-3 pl-8">
          <pre
            className="m-0 max-h-[320px] overflow-auto rounded border border-surface-border/60 bg-surface-overlay/60 p-2 text-[11px] font-mono whitespace-pre-wrap break-all text-text"
            aria-label={`event-${idx}-detail`}
          >
            {JSON.stringify(ev, null, 2)}
          </pre>
          <button
            type="button"
            onClick={() => { void handleCopy(); }}
            className={
              "mt-2 rounded-md border px-2 py-1 text-[10px] font-medium transition-colors " +
              (copyState === "copied"
                ? "border-success/40 bg-success/10 text-success"
                : copyState === "error"
                  ? "border-danger/40 bg-danger/10 text-danger"
                  : "border-surface-border text-text-dim hover:bg-surface-overlay hover:text-text")
            }
          >
            {copyState === "copied"
              ? "Copied"
              : copyState === "error"
                ? "Copy failed"
                : "Copy JSON"}
          </button>
        </div>
      )}
    </div>
  );
}

export function WidgetInspector({ pinId, pinLabel, onClose }: Props) {
  const [events, setEvents] = useState<WidgetDebugEvent[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [paused, setPaused] = useState(false);
  const mountedRef = useRef(true);

  const fetchEvents = useCallback(async () => {
    if (!pinId) return;
    setLoading(true);
    try {
      const data = await apiFetch<EventsResponse>(
        `/api/v1/widget-debug/events?pin_id=${encodeURIComponent(pinId)}&limit=100`,
      );
      if (!mountedRef.current) return;
      setEvents(Array.isArray(data.events) ? data.events : []);
      setError(null);
    } catch (e) {
      if (!mountedRef.current) return;
      setError((e as Error).message);
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, [pinId]);

  const clearEvents = useCallback(async () => {
    if (!pinId) return;
    try {
      await apiFetch(`/api/v1/widget-debug/events?pin_id=${encodeURIComponent(pinId)}`, {
        method: "DELETE",
      });
      setEvents([]);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [pinId]);

  useEffect(() => {
    mountedRef.current = true;
    void fetchEvents();
    return () => {
      mountedRef.current = false;
    };
  }, [fetchEvents]);

  useEffect(() => {
    if (paused) return;
    const id = window.setInterval(() => { void fetchEvents(); }, 2000);
    return () => window.clearInterval(id);
  }, [paused, fetchEvents]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <>
      <div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]"
        onClick={onClose}
        role="presentation"
      />
      <div
        className="fixed right-0 top-0 bottom-0 z-50 w-full sm:w-[520px] flex flex-col border-l border-surface-border bg-surface-raised shadow-2xl"
        role="dialog"
        aria-label="Widget inspector"
      >
        <header className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <div className="flex flex-col min-w-0">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
              Inspect widget
            </span>
            <span className="text-[13px] font-mono text-text truncate">
              {pinLabel ?? pinId}
            </span>
          </div>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPaused((v) => !v)}
              className="px-2 py-1 rounded-md text-[11px] text-text-muted hover:bg-surface-overlay hover:text-text"
              title={paused ? "Resume polling" : "Pause polling"}
            >
              {paused ? "Resume" : "Pause"}
            </button>
            <button
              type="button"
              onClick={() => { void fetchEvents(); }}
              className="p-1.5 rounded-md text-text-muted hover:bg-surface-overlay hover:text-text"
              title="Refresh"
              aria-label="Refresh"
            >
              <RefreshCw size={14} className={loading ? "animate-spin" : ""} />
            </button>
            <button
              type="button"
              onClick={() => { void clearEvents(); }}
              className="p-1.5 rounded-md text-text-muted hover:bg-surface-overlay hover:text-text"
              title="Clear"
              aria-label="Clear"
            >
              <Trash2 size={14} />
            </button>
            <button
              type="button"
              onClick={onClose}
              className="p-1.5 rounded-md text-text-muted hover:bg-surface-overlay hover:text-text"
              title="Close"
              aria-label="Close"
            >
              <X size={16} />
            </button>
          </div>
        </header>

        <div className="border-b border-surface-border px-4 py-2 text-[11px] text-text-dim">
          {events.length === 0
            ? "No events yet. The widget emits traces while it runs — trigger an interaction or reload it."
            : `${events.length} event${events.length === 1 ? "" : "s"} (newest first). Server ring holds up to 50 per pin; wipes on restart.`}
        </div>

        {error && (
          <div className="border-b border-danger/40 bg-danger/10 px-4 py-2 text-[12px] text-danger">
            {error}
          </div>
        )}

        <div className="flex-1 overflow-y-auto">
          {events.map((ev, idx) => (
            <EventRow key={`${idx}-${ev.ts_server ?? idx}`} ev={ev} idx={idx} />
          ))}
        </div>
      </div>
    </>
  );
}
