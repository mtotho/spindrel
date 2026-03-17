import { AppState, type AppStateStatus } from "react-native";
import { chatStream, getCachedBot, stripSilent, transcribe, type AudioInput, type VoiceState } from "../agent";
import { speak, stopSpeaking } from "../voice/tts";
import { startRecording, stopRecording, readAudioFile, readAudioFileBase64, type RecordingStatusCallback } from "../voice/recorder";
import { loadConfig } from "../config";
import { updateForegroundNotification, moveToForeground, moveToBackground } from "../native/VoiceServiceBridge";
import { setWakeWordCallback, startWakeWordDetection, stopWakeWordDetection, destroyWakeWord } from "../voice/wakeword";
import { playListenTone, type ListenSoundPreset } from "../voice/tone";
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
 * Trigger modes:
 *   - In-app mic / wake word: no overlay, stays in foreground
 *   - Background badge tap or wake word: we bring the app to the foreground
 *     so the JS thread receives audio frames (Android throttles JS when
 *     backgrounded). Overlay shown, then we run the full pipeline and
 *     move back to background when done.
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
    if (this.state !== "idle") {
      this.stop();
      return;
    }
    if (this.pipelineActive) return;

    this.pipelineActive = true;
    this.backgroundTriggered = true;

    const wasInForeground = this.isAppInForeground();
    if (!wasInForeground) {
      await moveToForeground().catch(() => {});
      await delay(400);
    }

    if (this.wakeWordActive) {
      await stopWakeWordDetection();
    }

    if (this.badgeActive) {
      await hideBadge().catch(() => {});
      this.badgeActive = false;
    }

    try {
      await this.processVoice();
    } catch (error) {
      console.error("Badge tap voice pipeline error:", error);
    } finally {
      this.backgroundTriggered = false;
      this.pipelineActive = false;

      if (!wasInForeground) {
        await moveToBackground().catch(() => {});
      }

      if (this.badgeEnabled && !this.isAppInForeground()) {
        await delay(200);
        await showBadge(this.state).catch(() => {});
        this.badgeActive = true;
      }

      await this.restartWakeWord();
    }
  }

  // ─── Background-triggered pipeline (wake word) ────────────────────

  private async onWakeWordDetected(): Promise<void> {
    if (this.state !== "idle" || this.pipelineActive) return;

    const wasInForeground = this.isAppInForeground();

    this.pipelineActive = true;
    this.backgroundTriggered = !wasInForeground;

    if (!wasInForeground) {
      await moveToForeground().catch(() => {});
      await delay(400);
    }

    await stopWakeWordDetection();

    const config = await loadConfig();
    const preset = (config.listenSound === "beep" || config.listenSound === "ping" ? config.listenSound : "chime") as ListenSoundPreset;
    await playListenTone(preset).catch(() => {});

    if (this.badgeActive) {
      await hideBadge().catch(() => {});
      this.badgeActive = false;
    }

    try {
      await this.processVoice(undefined, true);
    } catch (error) {
      console.error("Wake word voice pipeline error:", error);
    } finally {
      this.backgroundTriggered = false;
      this.pipelineActive = false;

      if (!wasInForeground) {
        await moveToBackground().catch(() => {});
      }

      if (this.badgeEnabled && !this.isAppInForeground()) {
        await delay(200);
        await showBadge(this.state).catch(() => {});
        this.badgeActive = true;
      }

      await this.restartWakeWord();
    }
  }

  private async restartWakeWord(): Promise<void> {
    if (!this.wakeWordActive) return;
    try {
      const config = await loadConfig();
      await startWakeWordDetection(config.wakeWord, config.picovoiceAccessKey, config.wakeWordSensitivity, config.wakeWordGain);
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
      await startWakeWordDetection(config.wakeWord, config.picovoiceAccessKey, config.wakeWordSensitivity, config.wakeWordGain);
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
   *
   * @param onMeter Optional metering callback for in-app UI
   * @param preserveRingBuffer When true, prepends the ring buffer audio
   *   to the recording — captures speech that overlapped the wake word
   */
  async processVoice(onMeter?: (metering: number) => void, preserveRingBuffer = false): Promise<string> {
    if (this.state !== "idle") return "";

    try {
      this.setState("listening");

      const statusCb: RecordingStatusCallback = (status) => {
        if (status.metering !== undefined) {
          onMeter?.(status.metering);
        }
      };

      let uri: string | null;
      try {
        uri = await startRecording(statusCb, preserveRingBuffer);
      } catch (error) {
        const msg = error instanceof Error ? error.message : "Recording failed";
        this.setState("idle", msg);
        throw error;
      }

      if (!uri || this.isCancelled()) {
        if (!this.isCancelled()) this.setState("idle");
        return "";
      }

      const config = await loadConfig();
      const bot = getCachedBot(config.botId);
      const useNative = config.audioNative || bot?.audio_input === "native";

      if (useNative) {
        return await this.processNativeAudio(uri);
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

      return await this.processTranscript(transcript);
    } finally {
      // Resume wake word when called directly (in-app mic), not from
      // onWakeWordDetected/onBadgeTapped which manage this themselves
      if (this.wakeWordActive && !this.pipelineActive) {
        this.restartWakeWord().catch(() => {});
      }
    }
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
    const config = await loadConfig();

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
      this.setState("responding", display);
      this.emitResponse(display);
      if (config.ttsEnabled && speakable) {
        await yieldToMain();
        await speak(speakable, { voice: config.ttsVoice || undefined, speed: config.ttsSpeed });
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
    this.emitTranscript(transcript);

    const config = await loadConfig();

    try {
      const result = await chatStream(transcript, {
        onToolStatus: (tool) => {
          this.setState("processing", `Using ${tool}...`);
        },
      });

      if (this.isCancelled()) return "";

      const { display, speakable } = stripSilent(result.response);
      this.setState("responding", display);
      this.emitResponse(display);
      if (config.ttsEnabled && speakable) {
        await yieldToMain();
        await speak(speakable, { voice: config.ttsVoice || undefined, speed: config.ttsSpeed });
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
      await destroyWakeWord();
      this.wakeWordActive = false;
    }
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

function yieldToMain(): Promise<void> {
  return new Promise((r) => setTimeout(r, 0));
}

export const voiceService = new VoiceService();
