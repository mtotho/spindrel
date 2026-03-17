/**
 * On-device transcription using Picovoice Cheetah (singleton).
 * Uses the same Picovoice access key as wake word.
 *
 * Model file: android-client/cheetah_params.pv (bundled with the app via Metro assetExts).
 * Initialize once with initCheetah(); feed frames during recording via processCheetahFrame();
 * call flushCheetah() when recording stops.
 */

import { Asset } from "expo-asset";
import { Platform } from "react-native";
import { Cheetah } from "@picovoice/cheetah-react-native";

let cachedModelPath: string | null = null;
let cheetah: Cheetah | null = null;

/** Path to the bundled Cheetah model (android-client/cheetah_params.pv). */
const CHEETAH_MODEL_MODULE = require("../../cheetah_params.pv");

/**
 * Resolve the bundled Cheetah model to a local file path.
 */
export async function getCheetahModelPath(): Promise<string> {
  if (cachedModelPath) return cachedModelPath;

  const asset = Asset.fromModule(CHEETAH_MODEL_MODULE);
  await asset.downloadAsync();
  if (!asset.localUri) {
    throw new Error("Failed to resolve Cheetah model asset to local path");
  }
  const path =
    Platform.OS === "android" && asset.localUri.startsWith("file://")
      ? asset.localUri.replace(/^file:\/\//, "")
      : asset.localUri;
  cachedModelPath = path;
  return path;
}

/**
 * Initialize the Cheetah singleton. No-op if already initialized.
 * Call before starting a recording when using local transcription.
 */
export async function initCheetah(accessKey: string): Promise<void> {
  if (cheetah) return;
  if (!accessKey?.trim()) {
    throw new Error("Picovoice access key required for local transcription");
  }
  const modelPath = await getCheetahModelPath();
  cheetah = await Cheetah.create(accessKey, modelPath);
}

/**
 * Frame length Cheetah expects (samples per frame). Use for chunking ring-buffer PCM.
 */
export function getCheetahFrameLength(): number {
  return cheetah?.frameLength ?? 512;
}

/**
 * Process one frame of PCM (16-bit samples as number[]). Call from the pipeline's
 * frameListener during recording when local STT is enabled. Returns any new
 * transcript fragment (may be empty).
 */
export function processCheetahFrame(frame: number[]): Promise<string> {
  if (!cheetah) return Promise.resolve("");
  return cheetah.process(frame).then((r) => r.transcript ?? "");
}

/**
 * Flush remaining transcript at end of recording. Call after the last frame.
 */
export function flushCheetah(): Promise<string> {
  if (!cheetah) return Promise.resolve("");
  return cheetah.flush().then((r) => r.transcript ?? "");
}

/**
 * Release the Cheetah instance (e.g. on app teardown). Optional.
 */
export async function destroyCheetah(): Promise<void> {
  if (cheetah) {
    await cheetah.delete();
    cheetah = null;
  }
}
