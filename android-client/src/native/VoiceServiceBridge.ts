import { NativeModules, Platform } from "react-native";

const { VoiceServiceModule } = NativeModules;

export async function startForegroundService(): Promise<void> {
  if (Platform.OS !== "android") return;
  await VoiceServiceModule.startService();
}

export async function stopForegroundService(): Promise<void> {
  if (Platform.OS !== "android") return;
  await VoiceServiceModule.stopService();
}

export async function updateForegroundNotification(text: string): Promise<void> {
  if (Platform.OS !== "android") return;
  await VoiceServiceModule.updateNotification(text);
}

export async function moveToBackground(): Promise<void> {
  if (Platform.OS !== "android") return;
  await VoiceServiceModule.moveToBackground();
}

export async function moveToForeground(): Promise<void> {
  if (Platform.OS !== "android") return;
  await VoiceServiceModule.moveToForeground();
}
