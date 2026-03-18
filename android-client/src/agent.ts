import { loadConfig } from "./config";
import { getSessionId, newSessionId, setSessionId, setActiveBotId } from "./session";

export interface StreamEvent {
  type:
    | "skill_context"
    | "memory_context"
    | "knowledge_context"
    | "tool_start"
    | "tool_request"
    | "tool_result"
    | "response"
    | "transcript"
    | "error"
    | "compaction_start"
    | "compaction_done";
  session_id?: string;
  count?: number;
  tool?: string;
  arguments?: Record<string, unknown>;
  request_id?: string;
  text?: string;
  client_actions?: ClientAction[];
  detail?: string;
  error?: string;
  /** True when this event is from the compaction memory phase (post-response). */
  compaction?: boolean;
  /** compaction_done only: session title from the summary. */
  title?: string;
  memory_preview?: string;
  knowledge_preview?: string;
  memory_count?: number;
  saved?: boolean;
}

export interface ClientAction {
  action: string;
  params?: Record<string, unknown>;
}

export interface ChatResult {
  sessionId: string;
  response: string;
  transcript: string;
  clientActions: ClientAction[];
}

export type VoiceState = "idle" | "listening" | "processing" | "responding";

export interface AgentCallbacks {
  onStateChange?: (state: VoiceState, detail?: string) => void;
  onToolStatus?: (tool: string) => void;
  onTranscript?: (text: string) => void;
  onError?: (error: string) => void;
}

export interface AudioInput {
  audioData: string;  // base64-encoded audio
  audioFormat: string;  // e.g. "m4a", "wav", "webm"
  audioNative: boolean;
}

const SILENT_RE = /\[silent\]([\s\S]*?)\[\/silent\]/g;

export function stripSilent(text: string): { display: string; speakable: string } {
  if (!text.includes("[silent]")) {
    return { display: text, speakable: text };
  }
  const speakable = text.replace(SILENT_RE, "").trim();
  const display = text.replace(SILENT_RE, "$1");
  return { display, speakable };
}

async function apiFetch(path: string, options: RequestInit = {}): Promise<Response> {
  const config = await loadConfig();
  if (!config.apiKey) {
    throw new Error("API key not configured");
  }

  const url = `${config.agentUrl}${path}`;
  const resp = await fetch(url, {
    ...options,
    headers: {
      Authorization: `Bearer ${config.apiKey}`,
      "Content-Type": "application/json",
      ...options.headers,
    },
  });

  if (!resp.ok) {
    if (resp.status === 401) throw new Error("Authentication failed. Check your API key.");
    if (resp.status === 404) throw new Error("Not found (check bot ID or endpoint).");
    throw new Error(`Server error: ${resp.status}`);
  }

  return resp;
}

export async function healthCheck(): Promise<boolean> {
  try {
    const config = await loadConfig();
    const resp = await fetch(`${config.agentUrl}/health`);
    return resp.ok;
  } catch {
    return false;
  }
}

/**
 * Detailed connection test that returns success/failure with a human-readable
 * error message. Used by the settings screen for troubleshooting.
 */
export async function testConnection(): Promise<{ ok: boolean; message: string }> {
  const config = await loadConfig();
  const url = config.agentUrl;

  if (!url) {
    return { ok: false, message: "Server URL is empty" };
  }

  if (!url.startsWith("http://") && !url.startsWith("https://")) {
    return { ok: false, message: "URL must start with http:// or https://" };
  }

  // Step 1: health check (no auth required)
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    const resp = await fetch(`${url}/health`, { signal: controller.signal });
    clearTimeout(timeout);

    if (!resp.ok) {
      return { ok: false, message: `Server responded with status ${resp.status}` };
    }
  } catch (error: unknown) {
    if (error instanceof Error && error.name === "AbortError") {
      return { ok: false, message: `Connection timed out — is ${url} reachable from this device?` };
    }
    const msg = error instanceof Error ? error.message : String(error);
    if (msg.includes("Network request failed") || msg.includes("Failed to connect")) {
      return { ok: false, message: `Cannot reach ${url} — check the IP address and that the server is running` };
    }
    return { ok: false, message: `Connection failed: ${msg}` };
  }

  // Step 2: authenticated endpoint (tests API key)
  if (!config.apiKey) {
    return { ok: true, message: "Server reachable, but no API key configured" };
  }

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 8000);
    const resp = await fetch(`${url}/bots`, {
      headers: { Authorization: `Bearer ${config.apiKey}` },
      signal: controller.signal,
    });
    clearTimeout(timeout);

    if (resp.status === 401) {
      return { ok: false, message: "Server reachable, but API key is invalid" };
    }
    if (!resp.ok) {
      return { ok: false, message: `Auth test failed with status ${resp.status}` };
    }

    const bots = await resp.json();
    if (Array.isArray(bots)) {
      _cachedBots = bots;
    }
    const count = Array.isArray(bots) ? bots.length : 0;
    return { ok: true, message: `Connected — ${count} bot${count !== 1 ? "s" : ""} available` };
  } catch (error: unknown) {
    if (error instanceof Error && error.name === "AbortError") {
      return { ok: false, message: "Server reachable but /bots timed out" };
    }
    return { ok: false, message: `Auth test failed: ${error instanceof Error ? error.message : String(error)}` };
  }
}

export interface BotInfo {
  id: string;
  name: string;
  model: string;
  audio_input?: string;
}

export async function listBots(): Promise<BotInfo[]> {
  const resp = await apiFetch("/bots");
  return resp.json();
}

let _cachedBots: BotInfo[] = [];

export async function refreshBotCache(): Promise<BotInfo[]> {
  _cachedBots = await listBots();
  return _cachedBots;
}

export function getCachedBot(botId: string): BotInfo | undefined {
  return _cachedBots.find((b) => b.id === botId);
}

export interface SessionSummary {
  id: string;
  client_id: string;
  bot_id: string;
  title?: string;
  created_at: string;
  last_active: string;
}

export interface SessionMessage {
  id: string;
  role: string;
  content?: string;
  tool_calls?: unknown[];
  tool_call_id?: string;
  created_at: string;
}

export interface SessionDetail {
  session: SessionSummary;
  messages: SessionMessage[];
}

export async function listSessions(
  clientId?: string
): Promise<SessionSummary[]> {
  const params = clientId ? `?client_id=${encodeURIComponent(clientId)}` : "";
  const resp = await apiFetch(`/sessions${params}`);
  return resp.json();
}

export async function getSession(sessionId: string): Promise<SessionDetail> {
  const resp = await apiFetch(`/sessions/${sessionId}`);
  return resp.json();
}

/**
 * Send a message using the non-streaming endpoint.
 * Simple but doesn't support real-time status or tool_request.
 */
export async function chat(
  message: string,
  callbacks?: AgentCallbacks,
  audio?: AudioInput,
): Promise<ChatResult> {
  const config = await loadConfig();
  const sessionId = await getSessionId();

  callbacks?.onStateChange?.("processing");

  const body: Record<string, unknown> = {
    message,
    session_id: sessionId,
    client_id: config.clientId,
    bot_id: config.botId,
  };
  if (audio) {
    body.audio_data = audio.audioData;
    body.audio_format = audio.audioFormat;
    body.audio_native = audio.audioNative;
  }

  const resp = await apiFetch("/chat", {
    method: "POST",
    body: JSON.stringify(body),
  });

  const data = await resp.json();
  const result: ChatResult = {
    sessionId: data.session_id,
    response: data.response,
    transcript: data.transcript || "",
    clientActions: data.client_actions || [],
  };

  if (result.transcript) {
    callbacks?.onTranscript?.(result.transcript);
  }

  await handleClientActions(result.clientActions, config.botId);
  return result;
}

/**
 * Send a message using the SSE streaming endpoint.
 * Supports real-time tool status, tool_request, and progressive updates.
 *
 * Uses XMLHttpRequest for reliable SSE support in React Native.
 * Server sends `: keepalive` comments to prevent idle connection drops.
 */
export async function chatStream(
  message: string,
  callbacks?: AgentCallbacks,
  audio?: AudioInput,
): Promise<ChatResult> {
  const config = await loadConfig();
  const sessionId = await getSessionId();

  callbacks?.onStateChange?.("processing");

  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${config.agentUrl}/chat/stream`);
    xhr.setRequestHeader("Authorization", `Bearer ${config.apiKey}`);
    xhr.setRequestHeader("Content-Type", "application/json");

    let lastIndex = 0;
    let responseText = "";
    let transcriptText = "";
    let clientActions: ClientAction[] = [];
    let resultSessionId = sessionId;

    xhr.onprogress = () => {
      const newText = xhr.responseText.substring(lastIndex);
      lastIndex = xhr.responseText.length;

      const lines = newText.split("\n");
      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        try {
          const event: StreamEvent = JSON.parse(line.substring(6));
          handleStreamEvent(event, callbacks);

          if (event.type === "transcript") {
            transcriptText = event.text || "";
          }

          if (event.type === "response" && !event.compaction) {
            responseText = event.text || "";
            clientActions = event.client_actions || [];
            if (event.session_id) resultSessionId = event.session_id;
          }

          if (event.type === "tool_request" && event.request_id) {
            submitToolResult(event.request_id, "[unsupported on this client]").catch(() => {});
          }
        } catch {}
      }
    };

    xhr.onload = async () => {
      if (xhr.status !== 200) {
        const errMsg =
          xhr.status === 401
            ? "Authentication failed"
            : `Server error: ${xhr.status}`;
        callbacks?.onError?.(errMsg);
        reject(new Error(errMsg));
        return;
      }

      await handleClientActions(clientActions, config.botId);
      resolve({
        sessionId: resultSessionId,
        response: responseText,
        transcript: transcriptText,
        clientActions,
      });
    };

    xhr.onerror = () => {
      const msg = "Connection failed. Check server URL.";
      callbacks?.onError?.(msg);
      reject(new Error(msg));
    };

    xhr.ontimeout = () => {
      const msg = "Request timed out.";
      callbacks?.onError?.(msg);
      reject(new Error(msg));
    };

    xhr.timeout = 120000;

    const body: Record<string, unknown> = {
      message,
      session_id: sessionId,
      client_id: config.clientId,
      bot_id: config.botId,
    };
    if (audio) {
      body.audio_data = audio.audioData;
      body.audio_format = audio.audioFormat;
      body.audio_native = audio.audioNative;
    }
    xhr.send(JSON.stringify(body));
  });
}

const TOOL_LABELS: Record<string, string> = {
  web_search: "Searching the web",
  fetch_url: "Reading webpage",
  search_memories: "Searching memories",
  save_memory: "Saving to memory",
  upsert_knowledge: "Updating knowledge",
  get_knowledge: "Getting knowledge",
  search_knowledge: "Searching knowledge",
  update_persona: "Updating persona",
};

function handleStreamEvent(event: StreamEvent, callbacks?: AgentCallbacks): void {
  const status = (msg: string) => {
    callbacks?.onStateChange?.("processing", msg);
    callbacks?.onToolStatus?.(msg);
  };

  switch (event.type) {
    case "skill_context":
      status(`Using ${event.count ?? 0} skill chunks`);
      break;
    case "memory_context":
      status(`Recalled ${event.count ?? 0} memor${event.count === 1 ? "y" : "ies"}`);
      break;
    case "knowledge_context":
      status(`Recalled ${event.count ?? 0} knowledge chunks`);
      break;
    case "compaction_start":
      status("Compaction: saving memories/knowledge");
      break;
    case "compaction_done":
      status(event.title ? `Compaction: ${event.title}` : "Compaction done");
      break;
    case "tool_start": {
      const tool = event.tool || "tool";
      const label = TOOL_LABELS[tool] || tool;
      status(event.compaction ? `Compaction: ${label}` : label);
      break;
    }
    case "tool_result":
      if (event.error) {
        callbacks?.onError?.(`Tool error: ${event.error}`);
      } else if (event.compaction && event.tool) {
        const label =
          event.tool === "save_memory" && event.saved
            ? "Saved to memory"
            : TOOL_LABELS[event.tool] || event.tool;
        status(`Compaction: ${label}`);
      }
      break;
    case "transcript":
      callbacks?.onTranscript?.(event.text || "");
      break;
    case "error":
      callbacks?.onError?.(event.detail || "Unknown error");
      break;
  }
}

/**
 * Send an audio file to the server for transcription.
 * The server decodes the file (via ffmpeg) and runs Whisper.
 *
 * @param audioData - Raw file bytes (M4A, WAV, OGG, etc.)
 * @param mimeType - MIME type of the audio file
 * @returns The transcribed text, or empty string if nothing was recognized
 */
export async function transcribe(audioData: ArrayBuffer, mimeType: string): Promise<string> {
  const config = await loadConfig();
  if (!config.apiKey) {
    throw new Error("API key not configured");
  }

  const resp = await fetch(`${config.agentUrl}/transcribe`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.apiKey}`,
      "Content-Type": mimeType,
    },
    body: audioData,
  });

  if (!resp.ok) {
    if (resp.status === 400) {
      const data = await resp.json();
      throw new Error(data.detail || "Bad audio data");
    }
    if (resp.status === 401) throw new Error("Authentication failed.");
    throw new Error(`Transcription error: ${resp.status}`);
  }

  const data = await resp.json();
  return data.text || "";
}

async function submitToolResult(requestId: string, result: string): Promise<void> {
  await apiFetch("/chat/tool_result", {
    method: "POST",
    body: JSON.stringify({ request_id: requestId, result }),
  });
}

async function handleClientActions(
  actions: ClientAction[],
  currentBotId: string
): Promise<void> {
  for (const action of actions) {
    switch (action.action) {
      case "new_session":
        await newSessionId();
        break;
      case "switch_bot": {
        const botId = action.params?.bot_id as string | undefined;
        if (botId) await setActiveBotId(botId);
        break;
      }
      case "switch_session": {
        const sid = action.params?.session_id as string | undefined;
        if (sid) await setSessionId(sid);
        break;
      }
    }
  }
}
