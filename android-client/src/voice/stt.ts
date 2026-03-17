import { loadConfig } from "../config";
import { transcribe as transcribeOnServer } from "../agent";

/**
 * Transcribe audio via the server (POST /transcribe, faster-whisper).
 * Used when recording produced a WAV URI (server or fallback path).
 *
 * Local (Cheetah) transcription is done in the pipeline during recording;
 * the pipeline returns { transcript } directly and transcribeAudio is not called.
 */
export async function transcribeAudio(audioData: ArrayBuffer, mimeType: string): Promise<string> {
  if (audioData.byteLength < 100) {
    return "";
  }
  return transcribeOnServer(audioData, mimeType);
}
