import { chat, stripSilent, transcribe, type VoiceState } from "../agent";
import { speak, stopSpeaking } from "../voice/tts";
import { startRecording, stopRecording, wavFileToFloat32, type RecordingStatusCallback } from "../voice/recorder";
import { loadConfig } from "../config";

type StateListener = (state: VoiceState, detail?: string) => void;

/**
 * Orchestrates the full voice pipeline:
 *   IDLE → LISTENING → PROCESSING → RESPONDING → IDLE
 *
 * Supports two modes:
 *   - processTranscript(text): skip recording, go straight to chat
 *   - processVoice(): record → transcribe → chat → TTS
 */
export class VoiceService {
  private state: VoiceState = "idle";
  private listeners: Set<StateListener> = new Set();

  addListener(listener: StateListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  getState(): VoiceState {
    return this.state;
  }

  private setState(state: VoiceState, detail?: string): void {
    this.state = state;
    for (const listener of this.listeners) {
      listener(state, detail);
    }
  }

  /**
   * Full voice pipeline: record audio → server transcription → chat → TTS.
   * Returns the assistant's display text, or empty string if cancelled.
   */
  async processVoice(onMeter?: (metering: number) => void): Promise<string> {
    if (this.state !== "idle") return "";

    this.setState("listening");

    const statusCb: RecordingStatusCallback = (status) => {
      if (status.metering !== undefined) {
        onMeter?.(status.metering);
      }
    };

    let uri: string | null;
    try {
      uri = await startRecording(statusCb);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Recording failed";
      this.setState("idle", msg);
      throw error;
    }

    if (!uri) {
      this.setState("idle");
      return "";
    }

    this.setState("processing", "Transcribing...");

    let transcript: string;
    try {
      const audioData = await wavFileToFloat32(uri);
      transcript = await transcribe(audioData);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Transcription failed";
      this.setState("idle", msg);
      throw error;
    }

    if (!transcript.trim()) {
      this.setState("idle", "No speech detected");
      return "";
    }

    return this.processTranscript(transcript);
  }

  /**
   * Process a text transcript through the agent and speak the result.
   */
  /**
   * Uses the non-streaming POST /chat endpoint. React Native's XHR
   * doesn't keep SSE connections alive during server-side tool execution,
   * causing the server to detect a disconnection and abort. The non-streaming
   * endpoint runs the exact same agent loop (tools execute fine) and returns
   * the final response as JSON.
   */
  async processTranscript(transcript: string): Promise<string> {
    if (!transcript.trim()) return "";

    this.setState("processing", transcript);

    try {
      const result = await chat(transcript);
      const { display, speakable } = stripSilent(result.response);

      const config = await loadConfig();
      if (config.ttsEnabled && speakable) {
        this.setState("responding", display);
        await speak(speakable);
      } else {
        this.setState("responding", display);
      }

      this.setState("idle");
      return display;
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Unknown error";
      this.setState("idle", msg);
      throw error;
    }
  }

  stop(): void {
    stopSpeaking();
    stopRecording();
    this.setState("idle");
  }
}

export const voiceService = new VoiceService();
