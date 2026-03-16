/**
 * STT wrapper — placeholder for @react-native-voice/voice.
 *
 * Not installed yet (Phase 5). This module defines the interface
 * so the rest of the app can reference it now.
 */

export type SttCallback = (transcript: string) => void;
export type SttErrorCallback = (error: string) => void;

let onResult: SttCallback | null = null;
let onError: SttErrorCallback | null = null;

export function setSttCallbacks(result: SttCallback, error: SttErrorCallback): void {
  onResult = result;
  onError = error;
}

export async function startListening(): Promise<void> {
  onError?.("STT not yet implemented — install @react-native-voice/voice (Phase 5)");
}

export async function stopListening(): Promise<void> {
  // no-op until Phase 5
}
