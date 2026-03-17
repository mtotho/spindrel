import { PorcupineManager, BuiltInKeywords } from "@picovoice/porcupine-react-native";

export type WakeWordCallback = () => void;

let manager: PorcupineManager | null = null;
let callback: WakeWordCallback | null = null;
let isRunning = false;
let transitioning = false;

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
  if (isRunning || transitioning) return;
  if (!accessKey) {
    console.warn("Picovoice access key not configured — wake word disabled");
    return;
  }

  const builtIn = KEYWORD_MAP[keyword.toLowerCase()];
  if (!builtIn) {
    console.warn(`Unknown wake word "${keyword}". Available: ${Object.keys(KEYWORD_MAP).join(", ")}`);
    return;
  }

  transitioning = true;
  try {
    manager = await PorcupineManager.fromBuiltInKeywords(
      accessKey,
      [builtIn],
      (_keywordIndex) => {
        callback?.();
      },
      (error) => {
        console.error("Porcupine processing error:", error.message);
      }
    );

    await manager.start();
    isRunning = true;
  } catch (error) {
    const msg = error instanceof Error ? error.message : String(error);
    console.error("Failed to start Porcupine:", msg);
    manager = null;
  } finally {
    transitioning = false;
  }
}

export async function stopWakeWordDetection(): Promise<void> {
  if (!isRunning || !manager || transitioning) return;

  // Capture to local and null out immediately to prevent concurrent
  // calls from operating on the same manager instance
  transitioning = true;
  const mgr = manager;
  manager = null;
  isRunning = false;

  try {
    await mgr.stop();
    mgr.delete();
  } catch (error) {
    console.error("Error stopping Porcupine:", error);
  } finally {
    transitioning = false;
  }
}

export function isWakeWordActive(): boolean {
  return isRunning;
}
