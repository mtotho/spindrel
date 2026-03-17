import { loadConfig } from "./config";
import { getSessionId, newSessionId, setSessionId, setActiveBotId } from "./session";

export interface StreamEvent {
  type: "skill_context" | "tool_start" | "tool_request" | "tool_result" | "response" | "error";
  session_id?: string;
  count?: number;
  tool?: string;
  arguments?: Record<string, unknown>;
  request_id?: string;
  text?: string;
  client_actions?: ClientAction[];
  detail?: string;
  error?: string;
}

export interface ClientAction {
  action: string;
  params?: Record<string, unknown>;
}

export interface ChatResult {
  sessionId: string;
  response: string;
  clientActions: ClientAction[];
}

export type VoiceState = "idle" | "listening" | "processing" | "responding";

export interface AgentCallbacks {
  onStateChange?: (state: VoiceState, detail?: string) => void;
  onToolStatus?: (tool: string) => void;
  onError?: (error: string) => void;
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

export async function listBots(): Promise<Array<{ id: string; name: string; model: string }>> {
  const resp = await apiFetch("/bots");
  return resp.json();
}

export async function listSessions(
  clientId?: string
): Promise<Array<{ id: string; title?: string; bot_id: string; last_active: string }>> {
  const params = clientId ? `?client_id=${encodeURIComponent(clientId)}` : "";
  const resp = await apiFetch(`/sessions${params}`);
  return resp.json();
}

/**
 * Send a message using the non-streaming endpoint.
 * Simple but doesn't support real-time status or tool_request.
 */
export async function chat(message: string, callbacks?: AgentCallbacks): Promise<ChatResult> {
  const config = await loadConfig();
  const sessionId = await getSessionId();

  callbacks?.onStateChange?.("processing");

  const resp = await apiFetch("/chat", {
    method: "POST",
    body: JSON.stringify({
      message,
      session_id: sessionId,
      client_id: config.clientId,
      bot_id: config.botId,
    }),
  });

  const data = await resp.json();
  const result: ChatResult = {
    sessionId: data.session_id,
    response: data.response,
    clientActions: data.client_actions || [],
  };

  await handleClientActions(result.clientActions, config.botId);
  return result;
}

/**
 * Send a message using the SSE streaming endpoint.
 * Supports real-time tool status, tool_request, and progressive updates.
 *
 * Uses XMLHttpRequest for reliable SSE support in React Native.
 */
export async function chatStream(
  message: string,
  callbacks?: AgentCallbacks
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

          if (event.type === "response") {
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
    xhr.send(
      JSON.stringify({
        message,
        session_id: sessionId,
        client_id: config.clientId,
        bot_id: config.botId,
      })
    );
  });
}

function handleStreamEvent(event: StreamEvent, callbacks?: AgentCallbacks): void {
  switch (event.type) {
    case "skill_context":
      callbacks?.onStateChange?.("processing", `Using ${event.count} skill chunks`);
      break;
    case "tool_start":
      callbacks?.onToolStatus?.(event.tool || "tool");
      break;
    case "tool_result":
      if (event.error) {
        callbacks?.onError?.(`Tool error: ${event.error}`);
      }
      break;
    case "error":
      callbacks?.onError?.(event.detail || "Unknown error");
      break;
  }
}

/**
 * Send raw float32 audio to the server for transcription.
 * The server runs Whisper and returns {"text": "..."}.
 *
 * @param audioData - Float32Array of audio samples at 16kHz mono
 * @returns The transcribed text, or empty string if nothing was recognized
 */
export async function transcribe(audioData: Float32Array): Promise<string> {
  const config = await loadConfig();
  if (!config.apiKey) {
    throw new Error("API key not configured");
  }

  const resp = await fetch(`${config.agentUrl}/transcribe`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${config.apiKey}`,
      "Content-Type": "application/octet-stream",
    },
    body: audioData.buffer,
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
