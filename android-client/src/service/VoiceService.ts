import { AppState, type AppStateStatus } from "react-native";
import { chatStream, getCachedBot, stripSilent, transcribe, type AudioInput, type VoiceState } from "../agent";
import { speak, stopSpeaking } from "../voice/tts";
import { startRecording, stopRecording, readAudioFile, readAudioFileBase64, type RecordingStatusCallback } from "../voice/recorder";
import { loadConfig } from "../config";
import { updateForegroundNotification, moveToBackground } from "../native/VoiceServiceBridge";
import { setWakeWordCallback, startWakeWordDetection, stopWakeWordDetection } from "../voice/wakeword";
import { showOverlay, updateOverlay, hideOverlay, dismissOverlayAfterDelay, hasOverlayPermission, showBadge, updateBadge, hideBadge, onBadgeTap } from "../native/OverlayBridge";

type StateListener = (state: VoiceState, detail?: string) => void;
type MessageListener = (userText: string, assistantText: string) => void;
type TranscriptListener = (transcript: string) => void;
type ResponseListener = (response: string) => void;

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
  private transcriptListeners: Set<TranscriptListener> = new Set();
  private responseListeners: Set<ResponseListener> = new Set();
  private wakeWordActive = false;
  private overlayPermissionGranted: boolean | null = null;
  private badgeActive = false;
  private badgeTapUnsub: (() => void) | null = null;
  private appState: AppStateStatus = AppState.currentState;
  private badgeEnabled = false;

  constructor() {
    setWakeWordCallback(() => this.onWakeWordDetected());
    AppState.addEventListener("change", (next) => {
      const wasForeground = this.appState === "active";
      this.appState = next;
      const isForeground = next === "active";

      if (wasForeground && !isForeground && this.badgeEnabled) {
        showBadge(this.state).catch(() => {});
        this.badgeActive = true;
      } else if (!wasForeground && isForeground && this.badgeEnabled) {
        // Don't hide the badge during an active voice interaction —
        // the user needs it to cancel. Only hide when idle.
        if (this.state === "idle") {
          hideBadge().catch(() => {});
          this.badgeActive = false;
          hideOverlay().catch(() => {});
        }
      }
    });
  }

  private isAppInForeground(): boolean {
    return this.appState === "active";
  }

  async checkOverlayPermission(): Promise<boolean> {
    this.overlayPermissionGranted = await hasOverlayPermission();
    return this.overlayPermissionGranted;
  }

  async enableBadge(): Promise<void> {
    if (this.overlayPermissionGranted === null) {
      await this.checkOverlayPermission();
    }
    if (!this.overlayPermissionGranted) return;

    this.badgeEnabled = true;
    this.badgeActive = false;

    if (!this.badgeTapUnsub) {
      this.badgeTapUnsub = onBadgeTap(() => this.onBadgeTapped());
    }

    // Only show the badge if the app is currently backgrounded
    if (!this.isAppInForeground()) {
      await showBadge(this.state).catch(() => {});
      this.badgeActive = true;
    }
  }

  async disableBadge(): Promise<void> {
    this.badgeEnabled = false;
    await hideBadge().catch(() => {});
    this.badgeActive = false;
    if (this.badgeTapUnsub) {
      this.badgeTapUnsub();
      this.badgeTapUnsub = null;
    }
  }

  private async onBadgeTapped(): Promise<void> {
    if (this.state === "listening") {
      this.stop();
      return;
    }
    if (this.state !== "idle") return;

    // Pause wake word if active — mic can't be shared
    if (this.wakeWordActive) {
      await stopWakeWordDetection();
    }

    let lastTranscript = "";
    let didMoveToBackground = false;
    const STATUS_DETAILS = new Set(["Transcribing...", "Sending audio..."]);
    const unsub = this.addListener((state, detail) => {
      if (state === "processing" && detail && !STATUS_DETAILS.has(detail) && !detail.startsWith("Using ")) {
        lastTranscript = detail;
      }
    });

    try {
      // processVoice calls startRecording which uses expo-av.
      // expo-av brings the Activity to foreground when accessing the mic.
      // We schedule moveToBackground after a delay to push it back once
      // expo-av has finished bringing it forward.
      const moveBackTimer = setTimeout(() => {
        didMoveToBackground = true;
        moveToBackground().catch(() => {});
      }, 600);

      const response = await this.processVoice();

      clearTimeout(moveBackTimer);
      if (!didMoveToBackground) {
        await moveToBackground().catch(() => {});
      }

      if (lastTranscript && response) {
        this.emitMessage(lastTranscript, response);
      }
    } catch (error) {
      console.error("Badge tap voice pipeline error:", error);
    } finally {
      unsub();
    }

    // Resume wake word if it was active
    if (this.wakeWordActive) {
      const config = await loadConfig();
      await startWakeWordDetection(config.wakeWord, config.picovoiceAccessKey);
    }
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

  addTranscriptListener(listener: TranscriptListener): () => void {
    this.transcriptListeners.add(listener);
    return () => this.transcriptListeners.delete(listener);
  }

  private emitTranscript(transcript: string): void {
    for (const listener of this.transcriptListeners) {
      listener(transcript);
    }
  }

  addResponseListener(listener: ResponseListener): () => void {
    this.responseListeners.add(listener);
    return () => this.responseListeners.delete(listener);
  }

  private emitResponse(response: string): void {
    for (const listener of this.responseListeners) {
      listener(response);
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
    this.updateOverlayForState(state, detail);
  }

  private async updateOverlayForState(state: VoiceState, detail?: string): Promise<void> {
    const config = await loadConfig();
    if (!config.overlayEnabled) return;
    if (this.overlayPermissionGranted === null) {
      await this.checkOverlayPermission();
    }
    if (!this.overlayPermissionGranted) return;

    const inForeground = this.isAppInForeground();

    try {
      // Badge color updates only when badge is visible (app backgrounded)
      if (this.badgeActive && !inForeground) {
        await updateBadge(state);
      }

      // Always allow hiding/dismissing the overlay (cleanup).
      // Only show/update the overlay when the app is NOT in the foreground.
      if (state === "idle") {
        await hideOverlay();
      } else if (!inForeground) {
        switch (state) {
          case "listening":
            await showOverlay("listening", "");
            break;
          case "processing":
            await updateOverlay("processing", detail || "");
            break;
          case "responding":
            await updateOverlay("responding", detail || "");
            break;
        }
      }
    } catch {
      // Overlay errors should never break the voice pipeline
    }
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
    const STATUS_DETAILS_WW = new Set(["Transcribing...", "Sending audio..."]);
    const unsub = this.addListener((state, detail) => {
      if (state === "processing" && detail && !STATUS_DETAILS_WW.has(detail) && !detail.startsWith("Using ")) {
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
   * Full voice pipeline: record audio → chat (with transcription or native audio) → TTS.
   *
   * When audioNative is enabled in config, audio is sent directly to the model
   * which interprets it and returns a transcript. Otherwise, audio is transcribed
   * via the server's /transcribe endpoint first.
   *
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

    const config = await loadConfig();
    const bot = getCachedBot(config.botId);
    const useNative = config.audioNative || bot?.audio_input === "native";

    if (useNative) {
      return this.processNativeAudio(uri);
    }

    // Traditional path: transcribe first, then chat
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
   * Native audio path: send raw audio directly to the model via chatStream.
   * The model interprets the audio and returns a transcript in the response.
   */
  private async processNativeAudio(uri: string): Promise<string> {
    this.setState("processing", "Sending audio...");

    let audioFile: { base64: string; format: string };
    try {
      audioFile = await readAudioFileBase64(uri);
    } catch (error) {
      const msg = error instanceof Error ? error.message : "Failed to read audio";
      this.setState("idle", msg);
      throw error;
    }

    const audio: AudioInput = {
      audioData: audioFile.base64,
      audioFormat: audioFile.format,
      audioNative: true,
    };

    let lastTranscript = "";

    try {
      const result = await chatStream("", {
        onTranscript: (text) => {
          lastTranscript = text;
          this.setState("processing", text);
          this.emitTranscript(text);
        },
        onToolStatus: (tool) => {
          this.setState("processing", `Using ${tool}...`);
        },
      }, audio);

      if (result.transcript && !lastTranscript) {
        lastTranscript = result.transcript;
        this.emitTranscript(lastTranscript);
      }

      const { display, speakable } = stripSilent(result.response);
      this.emitResponse(display);

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

  /**
   * Send a text message via the streaming chat endpoint.
   * Server sends SSE keepalive comments to prevent connection drops.
   */
  async processTranscript(transcript: string): Promise<string> {
    if (!transcript.trim()) return "";

    this.setState("processing", transcript);

    try {
      const result = await chatStream(transcript, {
        onToolStatus: (tool) => {
          this.setState("processing", `Using ${tool}...`);
        },
      });
      const { display, speakable } = stripSilent(result.response);
      this.emitResponse(display);

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
    await hideOverlay().catch(() => {});
    await this.disableBadge().catch(() => {});
    if (this.wakeWordActive) {
      await stopWakeWordDetection();
      this.wakeWordActive = false;
    }
  }
}

export const voiceService = new VoiceService();
