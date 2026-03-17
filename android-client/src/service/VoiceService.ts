import { AppState, type AppStateStatus } from "react-native";
import { chatStream, getCachedBot, stripSilent, transcribe, type AudioInput, type VoiceState } from "../agent";
import { speak, stopSpeaking } from "../voice/tts";
import { startRecording, stopRecording, readAudioFile, readAudioFileBase64, type RecordingStatusCallback } from "../voice/recorder";
import { loadConfig } from "../config";
import { updateForegroundNotification, moveToBackground } from "../native/VoiceServiceBridge";
import { setWakeWordCallback, startWakeWordDetection, stopWakeWordDetection } from "../voice/wakeword";
import { showOverlay, updateOverlay, hideOverlay, dismissOverlayAfterDelay, hasOverlayPermission, showBadge, updateBadge, hideBadge, onBadgeTap, onOverlayTap } from "../native/OverlayBridge";

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
 * Two trigger modes:
 *   - In-app: user taps mic button, no overlay, stays in foreground
 *   - Background: wake word or badge tap — overlay shown, app stays in
 *     foreground during the entire pipeline (recording + transcription +
 *     chat + TTS), then moves to background when finished.
 *
 * The app MUST stay foregrounded during the pipeline because React Native's
 * JS bridge and network layer are throttled on Fire OS when backgrounded,
 * even with a foreground service running.
 */
export class VoiceService {
  private state: VoiceState = "idle";
  private previousState: VoiceState = "idle";
  private listeners: Set<StateListener> = new Set();
  private messageListeners: Set<MessageListener> = new Set();
  private transcriptListeners: Set<TranscriptListener> = new Set();
  private responseListeners: Set<ResponseListener> = new Set();
  private wakeWordActive = false;
  private overlayPermissionGranted: boolean | null = null;
  private badgeActive = false;
  private badgeTapUnsub: (() => void) | null = null;
  private overlayTapUnsub: (() => void) | null = null;
  private appState: AppStateStatus = AppState.currentState;
  private badgeEnabled = false;
  /** True while a wake-word or badge-tap pipeline is running */
  private backgroundTriggered = false;
  /** Prevents concurrent pipeline executions from overlapping wake word / badge events */
  private pipelineActive = false;

  constructor() {
    setWakeWordCallback(() => this.onWakeWordDetected());

    this.overlayTapUnsub = onOverlayTap(() => {
      if (this.state !== "idle") {
        this.stop();
      }
    });

    AppState.addEventListener("change", (next) => {
      const wasForeground = this.appState === "active";
      this.appState = next;
      const isForeground = next === "active";

      if (wasForeground && !isForeground) {
        // App went to background — show badge unless a pipeline is active
        if (this.badgeEnabled && !this.backgroundTriggered) {
          showBadge(this.state).catch(() => {});
          this.badgeActive = true;
        }
      } else if (!wasForeground && isForeground) {
        // App came to foreground — clean up only when idle and not mid-pipeline
        if (this.state === "idle" && !this.backgroundTriggered) {
          if (this.badgeActive) {
            hideBadge().catch(() => {});
            this.badgeActive = false;
          }
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

  // ─── Background-triggered pipeline (badge tap) ────────────────────

  private async onBadgeTapped(): Promise<void> {
    // Allow cancelling from any active state
    if (this.state !== "idle") {
      this.stop();
      return;
    }
    if (this.pipelineActive) return;

    this.pipelineActive = true;
    this.backgroundTriggered = true;

    if (this.wakeWordActive) {
      await stopWakeWordDetection();
    }

    // Hide badge — the overlay pill takes over
    if (this.badgeActive) {
      await hideBadge().catch(() => {});
      this.badgeActive = false;
    }

    let lastTranscript = "";
    const STATUS_DETAILS = new Set(["Transcribing...", "Sending audio..."]);
    const unsub = this.addListener((state, detail) => {
      if (state === "processing" && detail && !STATUS_DETAILS.has(detail) && !detail.startsWith("Using ")) {
        lastTranscript = detail;
      }
    });

    try {
      // The app will stay foregrounded during recording (expo-av brings it
      // forward) and during network calls (required for XHR to work on
      // Fire OS). The overlay is drawn on top via SYSTEM_ALERT_WINDOW.
      // We only moveToBackground AFTER the full pipeline completes.
      const response = await this.processVoice();

      if (lastTranscript && response) {
        this.emitMessage(lastTranscript, response);
      }
    } catch (error) {
      console.error("Badge tap voice pipeline error:", error);
    } finally {
      unsub();
      this.backgroundTriggered = false;
      this.pipelineActive = false;

      // Pipeline done — return to kiosk browser and re-show badge
      await moveToBackground().catch(() => {});

      if (this.badgeEnabled) {
        // Brief delay so AppState catches up with moveToBackground
        await delay(200);
        await showBadge(this.state).catch(() => {});
        this.badgeActive = true;
      }
    }

    await this.restartWakeWord();
  }

  // ─── Background-triggered pipeline (wake word) ────────────────────

  private async onWakeWordDetected(): Promise<void> {
    if (this.state !== "idle" || this.pipelineActive) return;

    this.pipelineActive = true;
    this.backgroundTriggered = true;

    await stopWakeWordDetection();

    if (this.badgeActive) {
      await hideBadge().catch(() => {});
      this.badgeActive = false;
    }

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
      this.backgroundTriggered = false;
      this.pipelineActive = false;

      await moveToBackground().catch(() => {});

      if (this.badgeEnabled) {
        await delay(200);
        await showBadge(this.state).catch(() => {});
        this.badgeActive = true;
      }
    }

    await this.restartWakeWord();
  }

  private async restartWakeWord(): Promise<void> {
    if (!this.wakeWordActive) return;
    try {
      const config = await loadConfig();
      await startWakeWordDetection(config.wakeWord, config.picovoiceAccessKey);
    } catch (e) {
      console.error("Failed to restart wake word:", e);
    }
  }

  // ─── Listeners ────────────────────────────────────────────────────

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

  // ─── State management ─────────────────────────────────────────────

  getState(): VoiceState {
    return this.state;
  }

  private setState(state: VoiceState, detail?: string): void {
    this.previousState = this.state;
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

  /** Returns true if stop() was called and the pipeline should bail out */
  private isCancelled(): boolean {
    return this.state === "idle";
  }

  private async updateOverlayForState(state: VoiceState, detail?: string): Promise<void> {
    const config = await loadConfig();
    if (!config.overlayEnabled) return;
    if (this.overlayPermissionGranted === null) {
      await this.checkOverlayPermission();
    }
    if (!this.overlayPermissionGranted) return;

    const inForeground = this.isAppInForeground();
    // Show overlay when backgrounded OR during a background-triggered pipeline
    // (the overlay draws over our own app via SYSTEM_ALERT_WINDOW)
    const shouldShowOverlay = !inForeground || this.backgroundTriggered;

    try {
      if (this.badgeActive && !inForeground) {
        await updateBadge(state);
      }

      if (state === "idle") {
        if (this.previousState === "responding") {
          dismissOverlayAfterDelay(3000).catch(() => {});
        } else {
          await hideOverlay();
        }
      } else if (shouldShowOverlay) {
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

  // ─── Wake word ────────────────────────────────────────────────────

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

  // ─── Voice pipeline ───────────────────────────────────────────────

  /**
   * Full voice pipeline: record audio → chat (with transcription or native audio) → TTS.
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

    // Bail if cancelled via stop() during recording
    if (!uri || this.isCancelled()) {
      if (!this.isCancelled()) this.setState("idle");
      return "";
    }

    const config = await loadConfig();
    const bot = getCachedBot(config.botId);
    const useNative = config.audioNative || bot?.audio_input === "native";

    if (useNative) {
      return this.processNativeAudio(uri);
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

    if (this.isCancelled()) return "";

    if (!transcript.trim()) {
      this.setState("idle", "No speech detected");
      return "";
    }

    return this.processTranscript(transcript);
  }

  /**
   * Native audio path: send raw audio directly to the model via chatStream.
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

    if (this.isCancelled()) return "";

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

      if (this.isCancelled()) return "";

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
      if (this.isCancelled()) return "";
      const msg = error instanceof Error ? error.message : "Unknown error";
      this.setState("idle", msg);
      throw error;
    }
  }

  /**
   * Send a text message via the streaming chat endpoint.
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

      if (this.isCancelled()) return "";

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
      if (this.isCancelled()) return "";
      const msg = error instanceof Error ? error.message : "Unknown error";
      this.setState("idle", msg);
      throw error;
    }
  }

  // ─── Stop / cleanup ───────────────────────────────────────────────

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

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

export const voiceService = new VoiceService();
