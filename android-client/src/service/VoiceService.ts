import { chat, stripSilent, transcribe, type VoiceState } from "../agent";
import { speak, stopSpeaking } from "../voice/tts";
import { startRecording, stopRecording, readAudioFile, type RecordingStatusCallback } from "../voice/recorder";
import { loadConfig } from "../config";
import { updateForegroundNotification } from "../native/VoiceServiceBridge";
import { setWakeWordCallback, startWakeWordDetection, stopWakeWordDetection } from "../voice/wakeword";

type StateListener = (state: VoiceState, detail?: string) => void;
type MessageListener = (userText: string, assistantText: string) => void;

const NOTIFICATION_TEXT: Record<VoiceState, string> = {
  idle: "Listening for wake word...",
  listening: "Hearing you...",
  processing: "Thinking...",
  responding: "Speaking...",
};

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
  private messageListeners: Set<MessageListener> = new Set();
  private wakeWordActive = false;

  constructor() {
    setWakeWordCallback(() => this.onWakeWordDetected());
  }

  addListener(listener: StateListener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  addMessageListener(listener: MessageListener): () => void {
    this.messageListeners.add(listener);
    return () => this.messageListeners.delete(listener);
  }

  private emitMessage(userText: string, assistantText: string): void {
    for (const listener of this.messageListeners) {
      listener(userText, assistantText);
    }
  }

  getState(): VoiceState {
    return this.state;
  }

  private setState(state: VoiceState, detail?: string): void {
    this.state = state;
    for (const listener of this.listeners) {
      listener(state, detail);
    }
    const notifText = detail && state === "responding"
      ? detail.slice(0, 100)
      : NOTIFICATION_TEXT[state];
    updateForegroundNotification(notifText).catch(() => {});
  }

  /**
   * Enable or disable continuous wake word detection.
   * When enabled, the wake word triggers the full voice pipeline automatically.
   */
  async setWakeWordEnabled(enabled: boolean): Promise<void> {
    if (enabled && !this.wakeWordActive) {
      const config = await loadConfig();
      if (!config.picovoiceAccessKey) {
        console.warn("Cannot enable wake word: no Picovoice access key");
        return;
      }
      await startWakeWordDetection(config.wakeWord, config.picovoiceAccessKey);
      this.wakeWordActive = true;
    } else if (!enabled && this.wakeWordActive) {
      await stopWakeWordDetection();
      this.wakeWordActive = false;
    }
  }

  private async onWakeWordDetected(): Promise<void> {
    if (this.state !== "idle") return;

    // Pause wake word listening while we handle the voice interaction.
    // Porcupine and expo-av both capture from the mic — they can't run simultaneously.
    await stopWakeWordDetection();

    let lastTranscript = "";
    const unsub = this.addListener((state, detail) => {
      if (state === "processing" && detail && detail !== "Transcribing...") {
        lastTranscript = detail;
      }
    });

    try {
      const response = await this.processVoice();
      if (lastTranscript && response) {
        this.emitMessage(lastTranscript, response);
      }
    } catch (error) {
      console.error("Wake word voice pipeline error:", error);
    } finally {
      unsub();
    }

    // Resume wake word listening if still enabled
    if (this.wakeWordActive) {
      const config = await loadConfig();
      await startWakeWordDetection(config.wakeWord, config.picovoiceAccessKey);
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
      const audioFile = await readAudioFile(uri);
      transcript = await transcribe(audioFile.data, audioFile.mimeType);
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

  async stopAll(): Promise<void> {
    this.stop();
    if (this.wakeWordActive) {
      await stopWakeWordDetection();
      this.wakeWordActive = false;
    }
  }
}

export const voiceService = new VoiceService();
