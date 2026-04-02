import * as fs from "fs";
import * as path from "path";

const CONFIG_PATH = "/home/agent/.spindrel-chat/config.json";

export interface ChatConfig {
  serverUrl: string;
  token: string;
  channelId?: string;
  botId?: string;
  sessionId?: string;
  userId?: string;
  userEmail?: string;
}

export interface SSEEvent {
  event: string;
  data: any;
}

export interface HistoryMessage {
  id: string;
  role: string;
  content: string | null;
  created_at: string;
  metadata?: Record<string, any>;
}

/**
 * Read auth config written by the editor proxy.
 * Falls back to AGENT_SERVER_API_KEY env var.
 */
export function readConfig(): ChatConfig | null {
  // Try config file first
  try {
    if (fs.existsSync(CONFIG_PATH)) {
      const raw = fs.readFileSync(CONFIG_PATH, "utf-8");
      const cfg = JSON.parse(raw);
      if (cfg.serverUrl && cfg.token) {
        return cfg;
      }
    }
  } catch {
    // Fall through to env var
  }

  // Fall back to env var
  const apiKey = process.env.AGENT_SERVER_API_KEY;
  const serverUrl =
    process.env.AGENT_SERVER_URL || "http://localhost:8000";
  if (apiKey) {
    return { serverUrl, token: apiKey };
  }

  return null;
}

/**
 * Watch the config file for changes (token refresh, channel rebind).
 */
export function watchConfig(
  callback: (config: ChatConfig | null) => void
): fs.FSWatcher | null {
  const dir = path.dirname(CONFIG_PATH);
  try {
    if (!fs.existsSync(dir)) {
      return null;
    }
    return fs.watch(dir, (_eventType: string, filename: string | null) => {
      if (filename === "config.json") {
        callback(readConfig());
      }
    });
  } catch {
    return null;
  }
}

function authHeaders(token: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
  };
}

export async function cancelRequest(
  config: ChatConfig,
  clientId: string,
  botId: string
): Promise<void> {
  await fetch(`${config.serverUrl}/chat/cancel`, {
    method: "POST",
    headers: authHeaders(config.token),
    body: JSON.stringify({ client_id: clientId, bot_id: botId }),
  });
}

/**
 * Fetch recent messages from the active session to show chat history.
 */
export async function fetchRecentMessages(
  config: ChatConfig,
  limit: number = 10
): Promise<HistoryMessage[]> {
  if (!config.sessionId) {
    return [];
  }
  const resp = await fetch(
    `${config.serverUrl}/sessions/${config.sessionId}/messages?limit=${limit}`,
    { headers: authHeaders(config.token) }
  );
  if (!resp.ok) {
    return [];
  }
  const page = (await resp.json()) as { messages: HistoryMessage[]; has_more: boolean };
  return page.messages;
}

/**
 * Stream a chat message. Yields parsed SSE events.
 * Returns an AbortController so the caller can cancel.
 */
export function streamChat(
  config: ChatConfig,
  params: {
    message: string;
    channelId: string;
    botId: string;
    clientId: string;
  },
  onEvent: (event: SSEEvent) => void,
  onDone: () => void,
  onError: (error: Error) => void
): AbortController {
  const controller = new AbortController();

  const body = {
    message: params.message,
    channel_id: params.channelId,
    bot_id: params.botId,
    client_id: params.clientId,
  };

  fetch(`${config.serverUrl}/chat/stream`, {
    method: "POST",
    headers: authHeaders(config.token),
    body: JSON.stringify(body),
    signal: controller.signal,
  })
    .then(async (resp) => {
      if (!resp.ok) {
        const text = await resp.text();
        onError(new Error(`Chat request failed: ${resp.status} ${text}`));
        return;
      }
      if (!resp.body) {
        onError(new Error("No response body"));
        return;
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          break;
        }
        buffer += decoder.decode(value, { stream: true });

        // Parse SSE lines
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        let currentData = "";

        for (const line of lines) {
          if (line.startsWith(": ")) {
            // Keepalive comment, skip
            continue;
          }
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            currentData = line.slice(6);
          } else if (line === "" && currentData) {
            // Empty line = end of event
            try {
              const data = JSON.parse(currentData);
              onEvent({
                event: currentEvent || "message",
                data,
              });
            } catch {
              // Non-JSON data, emit as-is
              onEvent({
                event: currentEvent || "message",
                data: currentData,
              });
            }
            currentEvent = "";
            currentData = "";
          }
        }
      }
      onDone();
    })
    .catch((err: any) => {
      if (err.name !== "AbortError") {
        onError(err);
      }
    });

  return controller;
}
