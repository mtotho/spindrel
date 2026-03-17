import { PorcupineManager, BuiltInKeywords } from "@picovoice/porcupine-react-native";

export type WakeWordCallback = () => void;

let manager: PorcupineManager | null = null;
let callback: WakeWordCallback | null = null;
let isRunning = false;

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
  if (isRunning) return;
  if (!accessKey) {
    console.warn("Picovoice access key not configured — wake word disabled");
    return;
  }

  const builtIn = KEYWORD_MAP[keyword.toLowerCase()];
  if (!builtIn) {
    console.warn(`Unknown wake word "${keyword}". Available: ${Object.keys(KEYWORD_MAP).join(", ")}`);
    return;
  }

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
  }
}

export async function stopWakeWordDetection(): Promise<void> {
  if (!isRunning || !manager) return;

  try {
    await manager.stop();
    manager.delete();
  } catch (error) {
    console.error("Error stopping Porcupine:", error);
  }

  manager = null;
  isRunning = false;
}

export function isWakeWordActive(): boolean {
  return isRunning;
}
