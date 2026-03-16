/**
 * STT via server-side transcription.
 *
 * Records audio and POSTs raw PCM to the server's /transcribe endpoint.
 * The server runs faster-whisper (or another configured STT provider).
 */

import { loadConfig } from "../config";

export type SttCallback = (transcript: string) => void;
export type SttErrorCallback = (error: string) => void;

let onResult: SttCallback | null = null;
let onError: SttErrorCallback | null = null;

export function setSttCallbacks(result: SttCallback, error: SttErrorCallback): void {
  onResult = result;
  onError = error;
}

/**
 * Transcribe pre-recorded audio via the server.
 * Accepts a Float32Array of 16kHz mono PCM samples.
 */
export async function transcribeAudio(audio: Float32Array): Promise<string | null> {
  const config = await loadConfig();
  if (!config.apiKey || !config.agentUrl) {
    onError?.("API key or agent URL not configured");
    return null;
  }

  try {
    const resp = await fetch(`${config.agentUrl}/transcribe`, {
      method: "POST",
      headers: {
        Authorization: `Bearer ${config.apiKey}`,
        "Content-Type": "application/octet-stream",
      },
      body: audio.buffer,
    });

    if (!resp.ok) {
      const detail = await resp.text().catch(() => `HTTP ${resp.status}`);
      onError?.(`Transcription failed: ${detail}`);
      return null;
    }

    const data = await resp.json();
    const text = data.text || "";
    if (text) {
      onResult?.(text);
    }
    return text || null;
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    onError?.(`Transcription error: ${msg}`);
    return null;
  }
}

export async function startListening(): Promise<void> {
  onError?.(
    "Direct mic recording not yet implemented on Android — " +
      "use transcribeAudio() with pre-recorded audio instead"
  );
}

export async function stopListening(): Promise<void> {
  // no-op — recording is handled externally
}
