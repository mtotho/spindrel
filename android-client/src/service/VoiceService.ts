import { chatStream, stripSilent, type VoiceState, type AgentCallbacks } from "../agent";
import { speak, stopSpeaking } from "../voice/tts";
import { loadConfig } from "../config";

type StateListener = (state: VoiceState, detail?: string) => void;

/**
 * Orchestrates the full voice pipeline:
 *   IDLE → LISTENING → PROCESSING → RESPONDING → IDLE
 *
 * For now this is a simple class that can be driven manually
 * (e.g. from a "push to talk" button). Foreground service
 * integration comes in Phase 6, wake word in Phase 7.
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
   * Process a text transcript through the agent and speak the result.
   * This is the core pipeline minus STT (which will be added in Phase 5).
   */
  async processTranscript(transcript: string): Promise<string> {
    if (!transcript.trim()) return "";

    this.setState("processing", transcript);

    const callbacks: AgentCallbacks = {
      onStateChange: (s, d) => this.setState(s, d),
      onToolStatus: (tool) => this.setState("processing", `Using ${tool}...`),
      onError: (err) => this.setState("idle", err),
    };

    try {
      const result = await chatStream(transcript, callbacks);
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
    this.setState("idle");
  }
}

export const voiceService = new VoiceService();
