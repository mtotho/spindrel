import { useEffect, useMemo, useRef, useState } from "react";
import { Terminal as XTerm } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import "@xterm/xterm/css/xterm.css";

import { apiFetch, ApiError } from "@/src/api/client";
import { useAuthStore, getAuthToken } from "@/src/stores/auth";
import { Spinner } from "@/src/components/shared/Spinner";

interface TerminalPanelProps {
  /** Command to inject into the shell on startup, e.g. "claude login". */
  seedCommand?: string;
  /** Working directory to start in. Falls back to $HOME on the server side. */
  cwd?: string;
  /** Called when the PTY exits (process EOF or session terminated). */
  onExit?: () => void;
  /** Optional className for the outer container — usually `flex-1` or sized. */
  className?: string;
  /** Optional compact title bar for embedded terminal drawers. */
  title?: string;
  /** Endpoint used to create the PTY session. Defaults to the generic admin terminal. */
  sessionCreatePath?: string;
  /** Extra POST body fields for custom terminal launch endpoints. */
  sessionCreateBody?: Record<string, unknown>;
}

type WireMessage =
  | { type: "data"; data: string }
  | { type: "exit" }
  | { type: "resize"; rows: number; cols: number };

function toWsUrl(httpUrl: string, path: string, token: string): string {
  const base = httpUrl.replace(/^http/i, (m) => (m.toLowerCase() === "http" ? "ws" : "wss"));
  const url = new URL(path, base.endsWith("/") ? base : base + "/");
  url.searchParams.set("token", token);
  return url.toString();
}

function encodeBytesToBase64(bytes: Uint8Array): string {
  let bin = "";
  for (let i = 0; i < bytes.length; i++) bin += String.fromCharCode(bytes[i]);
  return btoa(bin);
}

function decodeBase64ToBytes(b64: string): Uint8Array {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

/**
 * xterm.js + WebSocket → admin PTY backend.
 *
 * Lifecycle: mount → POST /admin/terminal/sessions → connect WS with the
 * returned id → render xterm → on unmount, close WS (server kills the PTY).
 */
export function TerminalPanel({
  seedCommand,
  cwd,
  onExit,
  className,
  title,
  sessionCreatePath = "/api/v1/admin/terminal/sessions",
  sessionCreateBody,
}: TerminalPanelProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const termRef = useRef<XTerm | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const decoderRef = useRef<TextDecoder>(new TextDecoder("utf-8", { fatal: false }));
  const encoderRef = useRef<TextEncoder>(new TextEncoder());
  const onExitRef = useRef(onExit);

  const [status, setStatus] = useState<"connecting" | "open" | "closed" | "error">("connecting");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [exited, setExited] = useState(false);

  // Stable refs so the connect effect doesn't re-fire on every prop change.
  const seed = useMemo(() => seedCommand, [seedCommand]);
  const startCwd = useMemo(() => cwd, [cwd]);
  const createPath = useMemo(() => sessionCreatePath, [sessionCreatePath]);
  const createBody = useMemo(() => sessionCreateBody, [sessionCreateBody]);

  useEffect(() => {
    onExitRef.current = onExit;
  }, [onExit]);

  useEffect(() => {
    const target = containerRef.current;
    if (!target) return;

    const term = new XTerm({
      convertEol: false,
      cursorBlink: true,
      cursorStyle: "block",
      fontFamily: '"JetBrains Mono", "Fira Code", Menlo, Monaco, Consolas, monospace',
      fontSize: 13,
      theme: {
        background: "#0a0d12",
        foreground: "#d4d4d8",
        cursor: "#d4d4d8",
        cursorAccent: "#0a0d12",
        selectionBackground: "#3b82f6aa",
      },
      scrollback: 5000,
      allowProposedApi: true,
    });
    const fit = new FitAddon();
    term.loadAddon(fit);
    term.loadAddon(new WebLinksAddon());
    term.open(target);
    termRef.current = term;
    fitRef.current = fit;
    try {
      fit.fit();
    } catch {
      /* container may not have layout yet */
    }

    let cancelled = false;
    let ws: WebSocket | null = null;

    const send = (msg: WireMessage) => {
      if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
    };

    const dataDisposable = term.onData((data: string) => {
      const bytes = encoderRef.current.encode(data);
      send({ type: "data", data: encodeBytesToBase64(bytes) });
    });

    const ro = new ResizeObserver(() => {
      try {
        fit.fit();
      } catch {
        /* ignore */
      }
      if (term.cols && term.rows) {
        send({ type: "resize", rows: term.rows, cols: term.cols });
      }
    });
    ro.observe(target);

    (async () => {
      try {
        const { session_id } = await apiFetch<{ session_id: string }>(
          createPath,
          {
            method: "POST",
            body: JSON.stringify({
              seed_command: seed ?? null,
              cwd: startCwd ?? null,
              ...(createBody ?? {}),
            }),
          },
        );
        if (cancelled) return;

        const { serverUrl } = useAuthStore.getState();
        const token = getAuthToken();
        if (!serverUrl || !token) {
          setStatus("error");
          setErrorMsg("Not signed in.");
          return;
        }
        const wsUrl = toWsUrl(serverUrl, `/api/v1/admin/terminal/${session_id}`, token);
        ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        ws.onopen = () => {
          setStatus("open");
          // Sync size on open.
          if (term.cols && term.rows) {
            send({ type: "resize", rows: term.rows, cols: term.cols });
          }
          term.focus();
        };
        ws.onmessage = (ev) => {
          try {
            const msg = JSON.parse(ev.data) as WireMessage;
            if (msg.type === "data") {
              const bytes = decodeBase64ToBytes(msg.data);
              term.write(bytes);
            } else if (msg.type === "exit") {
              setExited(true);
              setStatus("closed");
              term.write("\r\n\x1b[2;37m[session exited]\x1b[0m\r\n");
              onExitRef.current?.();
            }
          } catch {
            /* ignore malformed frames */
          }
        };
        ws.onerror = () => {
          setStatus("error");
          setErrorMsg("WebSocket error — server may be unreachable.");
        };
        ws.onclose = (ev) => {
          if (status !== "error") setStatus("closed");
          if (!exited && ev.code !== 1000 && ev.code !== 1005) {
            const codeHint = {
              4401: "Authentication failed.",
              4403: "Admin access required.",
              4404: "Terminal session not found or disabled.",
            } as Record<number, string>;
            setErrorMsg((prev) => prev ?? codeHint[ev.code] ?? `Connection closed (code ${ev.code}).`);
          }
        };
      } catch (e) {
        if (cancelled) return;
        setStatus("error");
        if (e instanceof ApiError) {
          if (e.status === 404) setErrorMsg("Terminal disabled by server (DISABLE_ADMIN_TERMINAL).");
          else if (e.status === 403) setErrorMsg("Admin access required.");
          else if (e.status === 429) setErrorMsg(e.detail ?? "Too many concurrent terminals.");
          else setErrorMsg(e.detail ?? `Failed to start terminal (HTTP ${e.status}).`);
        } else {
          setErrorMsg((e as Error).message ?? "Failed to start terminal.");
        }
      }
    })();

    return () => {
      cancelled = true;
      try {
        ro.disconnect();
      } catch {
        /* ignore */
      }
      try {
        dataDisposable.dispose();
      } catch {
        /* ignore */
      }
      try {
        ws?.close(1000);
      } catch {
        /* ignore */
      }
      try {
        term.dispose();
      } catch {
        /* ignore */
      }
      termRef.current = null;
      fitRef.current = null;
      wsRef.current = null;
    };
    // Reconnect on seed/cwd change is intentional — those define the session.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [seed, startCwd, createPath, createBody]);

  return (
    <div className={`relative flex min-h-0 flex-1 flex-col bg-[#0a0d12] ${className ?? ""}`}>
      {title && (
        <div className="flex h-8 shrink-0 items-center border-b border-white/10 px-3 font-mono text-[11px] text-zinc-400">
          {title}
        </div>
      )}
      <div ref={containerRef} className={`absolute inset-x-0 bottom-0 p-2 ${title ? "top-8" : "top-0"}`} />
      {status === "connecting" && (
        <div className="absolute inset-0 flex items-center justify-center bg-[#0a0d12]/90">
          <div className="flex items-center gap-2 text-[12px] text-text-dim">
            <Spinner /> Starting shell…
          </div>
        </div>
      )}
      {status === "error" && errorMsg && (
        <div className="absolute inset-x-0 top-0 z-10 bg-danger-subtle px-3 py-2 text-[12px] text-danger">
          {errorMsg}
        </div>
      )}
    </div>
  );
}

export default TerminalPanel;
