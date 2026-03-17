import { NativeModules, NativeEventEmitter, Platform } from "react-native";
import type { VoiceState } from "../agent";

const { OverlayModule } = NativeModules;
const overlayEmitter = Platform.OS === "android" ? new NativeEventEmitter(OverlayModule) : null;

// --- Permission ---

export async function hasOverlayPermission(): Promise<boolean> {
  if (Platform.OS !== "android") return false;
  return OverlayModule.hasPermission();
}

export async function requestOverlayPermission(): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.requestPermission();
}

// --- Overlay pill (transient, during voice interaction) ---

export async function showOverlay(state: VoiceState, text: string = ""): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.show(state, text);
}

export async function updateOverlay(state: VoiceState, text: string = ""): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.update(state, text);
}

export async function hideOverlay(): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.hide();
}

export async function dismissOverlayAfterDelay(delayMs: number = 3000): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.dismissAfterDelay(delayMs);
}

// --- Badge (persistent floating mic button) ---

export async function showBadge(state: VoiceState = "idle"): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.showBadge(state);
}

export async function updateBadge(state: VoiceState): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.updateBadge(state);
}

export async function hideBadge(): Promise<void> {
  if (Platform.OS !== "android") return;
  await OverlayModule.hideBadge();
}

export function onBadgeTap(callback: () => void): () => void {
  if (!overlayEmitter) return () => {};
  const subscription = overlayEmitter.addListener("onBadgeTap", callback);
  return () => subscription.remove();
}
