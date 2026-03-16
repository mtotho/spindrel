/**
 * Wake word detection wrapper — placeholder for Porcupine.
 *
 * Not installed yet (Phase 7). This module defines the interface
 * so the rest of the app can reference it now.
 */

export type WakeWordCallback = () => void;

let callback: WakeWordCallback | null = null;

export function setWakeWordCallback(cb: WakeWordCallback): void {
  callback = cb;
}

export async function startWakeWordDetection(): Promise<void> {
  console.warn("Wake word detection not yet implemented (Phase 7)");
}

export async function stopWakeWordDetection(): Promise<void> {
  // no-op until Phase 7
}
