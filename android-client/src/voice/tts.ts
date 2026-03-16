import * as Speech from "expo-speech";

let currentlyPlaying = false;

export interface TtsOptions {
  voice?: string;
  speed?: number;
}

export async function speak(text: string, options?: TtsOptions): Promise<void> {
  if (!text.trim()) return;

  currentlyPlaying = true;
  const speechOptions: Speech.SpeechOptions = {
    language: "en-US",
    rate: options?.speed ?? 1.0,
    onDone: () => {
      currentlyPlaying = false;
    },
    onStopped: () => {
      currentlyPlaying = false;
    },
    onError: () => {
      currentlyPlaying = false;
    },
  };

  if (options?.voice) {
    speechOptions.voice = options.voice;
  }

  return new Promise<void>((resolve) => {
    speechOptions.onDone = () => { currentlyPlaying = false; resolve(); };
    speechOptions.onStopped = () => { currentlyPlaying = false; resolve(); };
    speechOptions.onError = () => { currentlyPlaying = false; resolve(); };
    Speech.speak(text, speechOptions);
  });
}

export function stopSpeaking(): void {
  if (currentlyPlaying) {
    Speech.stop();
    currentlyPlaying = false;
  }
}

export function isSpeaking(): boolean {
  return currentlyPlaying;
}
