import * as fs from "fs";
import * as path from "path";

const CONFIG_PATH = "/home/agent/.spindrel-chat/config.json";

export interface ChatConfig {
  serverUrl: string;
  token: string;
  userId?: string;
  userEmail?: string;
}

export interface SSEEvent {
  event: string;
  data: any;
}

export interface Channel {
  id: string;
  name: string;
  bot_id: string;
  active_session_id?: string;
}

export interface Bot {
  id: string;
  name: string;
  model: string;
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
 * Watch the config file for changes (token refresh).
 */
export function watchConfig(
  callback: (config: ChatConfig | null) => void
): fs.FSWatcher | null {
  const dir = path.dirname(CONFIG_PATH);
  try {
    if (!fs.existsSync(dir)) {
      return null;
    }
    return fs.watch(dir, (_eventType, filename) => {
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

export async function createChannel(
  config: ChatConfig,
  name: string,
  botId: string
): Promise<Channel> {
  const resp = await fetch(`${config.serverUrl}/api/v1/channels`, {
    method: "POST",
    headers: authHeaders(config.token),
    body: JSON.stringify({
      name,
      bot_id: botId,
      client_id: `vscode:${name}`,
    }),
  });
  if (!resp.ok) {
    throw new Error(`Failed to create channel: ${resp.status} ${resp.statusText}`);
  }
  return (await resp.json()) as Channel;
}

export async function listChannels(
  config: ChatConfig
): Promise<Channel[]> {
  const resp = await fetch(`${config.serverUrl}/api/v1/channels`, {
    headers: authHeaders(config.token),
  });
  if (!resp.ok) {
    throw new Error(`Failed to list channels: ${resp.status}`);
  }
  return (await resp.json()) as Channel[];
}

export async function getBots(config: ChatConfig): Promise<Bot[]> {
  const resp = await fetch(`${config.serverUrl}/bots`, {
    headers: authHeaders(config.token),
  });
  if (!resp.ok) {
    throw new Error(`Failed to list bots: ${resp.status}`);
  }
  return (await resp.json()) as Bot[];
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
    .catch((err) => {
      if (err.name !== "AbortError") {
        onError(err);
      }
    });

  return controller;
}
