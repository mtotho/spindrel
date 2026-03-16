import * as Speech from "expo-speech";

let currentlyPlaying = false;

export async function speak(text: string): Promise<void> {
  if (!text.trim()) return;

  currentlyPlaying = true;
  return new Promise<void>((resolve) => {
    Speech.speak(text, {
      language: "en-US",
      rate: 1.0,
      onDone: () => {
        currentlyPlaying = false;
        resolve();
      },
      onStopped: () => {
        currentlyPlaying = false;
        resolve();
      },
      onError: () => {
        currentlyPlaying = false;
        resolve();
      },
    });
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
