/**
 * Wake word detection — thin wrapper around audio-pipeline.
 *
 * The audio pipeline manages VoiceProcessor and low-level Porcupine
 * internally. This module just maps keyword strings to BuiltInKeywords
 * and exposes start/stop/callback for VoiceService.
 */

import { BuiltInKeywords } from "@picovoice/porcupine-react-native";
import { startPipeline, stopPipeline, isPipelineActive, resumeWakeWord, pauseWakeWord } from "./audio-pipeline";

export type WakeWordCallback = () => void;

let callback: WakeWordCallback | null = null;

const KEYWORD_MAP: Record<string, BuiltInKeywords> = {
  alexa: BuiltInKeywords.ALEXA,
  americano: BuiltInKeywords.AMERICANO,
  blueberry: BuiltInKeywords.BLUEBERRY,
  bumblebee: BuiltInKeywords.BUMBLEBEE,
  computer: BuiltInKeywords.COMPUTER,
  grapefruit: BuiltInKeywords.GRAPEFRUIT,
  grasshopper: BuiltInKeywords.GRASSHOPPER,
  "hey google": BuiltInKeywords.HEY_GOOGLE,
  "hey siri": BuiltInKeywords.HEY_SIRI,
  jarvis: BuiltInKeywords.JARVIS,
  "ok google": BuiltInKeywords.OK_GOOGLE,
  picovoice: BuiltInKeywords.PICOVOICE,
  porcupine: BuiltInKeywords.PORCUPINE,
  terminator: BuiltInKeywords.TERMINATOR,
};

export function setWakeWordCallback(cb: WakeWordCallback): void {
  callback = cb;
}

export async function startWakeWordDetection(
  keyword: string,
  accessKey: string
): Promise<void> {
  if (!accessKey) {
    console.warn("Picovoice access key not configured — wake word disabled");
    return;
  }

  const builtIn = KEYWORD_MAP[keyword.toLowerCase()];
  if (!builtIn) {
    console.warn(`Unknown wake word "${keyword}". Available: ${Object.keys(KEYWORD_MAP).join(", ")}`);
    return;
  }

  if (isPipelineActive()) {
    resumeWakeWord();
    return;
  }

  try {
    await startPipeline({ accessKey, keyword: builtIn }, () => {
      callback?.();
    });
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error("Failed to start wake word pipeline:", msg);
  }
}

export async function stopWakeWordDetection(): Promise<void> {
  pauseWakeWord();
}

export async function destroyWakeWord(): Promise<void> {
  await stopPipeline();
}

export function isWakeWordActive(): boolean {
  return isPipelineActive();
}
