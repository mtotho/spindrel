import { transcribe } from "../agent";

/**
 * Server-side STT via POST /transcribe.
 *
 * Sends audio file bytes (M4A, WAV, etc.) to the agent server.
 * The server decodes via ffmpeg and runs Whisper transcription.
 *
 * Future: add a "local" mode using @react-native-voice/voice
 * for on-device transcription (configurable via settings).
 */

export async function transcribeAudio(audioData: ArrayBuffer, mimeType: string): Promise<string> {
  if (audioData.byteLength < 100) {
    return "";
  }

  return transcribe(audioData, mimeType);
}
