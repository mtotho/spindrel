import { transcribe } from "../agent";

/**
 * Server-side STT via POST /transcribe.
 *
 * Records audio using expo-av, then sends the raw float32 buffer
 * to the agent server for Whisper transcription.
 *
 * Future: add a "local" mode using @react-native-voice/voice
 * for on-device transcription (configurable via settings).
 */

export async function transcribeAudio(audioData: Float32Array): Promise<string> {
  if (audioData.length === 0) {
    return "";
  }

  const minSamples = 16000 * 0.1; // 0.1s at 16kHz
  if (audioData.length < minSamples) {
    return "";
  }

  return transcribe(audioData);
}
