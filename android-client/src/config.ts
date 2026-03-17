import AsyncStorage from "@react-native-async-storage/async-storage";
import { BUILD_API_KEY, BUILD_AGENT_URL, BUILD_PICOVOICE_KEY } from "./env.generated";

export interface AppConfig {
  agentUrl: string;
  apiKey: string;
  botId: string;
  clientId: string;
  wakeWord: string;
  wakeWordEnabled: boolean;
  wakeWordSensitivity: number;
  /** Mic gain for wake word (1.0 = normal, 1.5–2.0 can help on quiet devices). */
  wakeWordGain: number;
  /** Ms of recording to trim from the start after wake word (stops "jarvis" etc. from being transcribed). Default 800. */
  wakeWordTrimMs: number;
  picovoiceAccessKey: string;
  ttsEnabled: boolean;
  ttsVoice: string;
  ttsSpeed: number;
  listenSound: string;
  overlayEnabled: boolean;
  audioNative: boolean;
  /** "server" = POST to agent /transcribe (Whisper); "local" = on-device Picovoice Cheetah */
  transcriptionMode: "server" | "local";
}

export const BUILT_IN_WAKE_WORDS = [
  "alexa",
  "americano",
  "blueberry",
  "bumblebee",
  "computer",
  "grapefruit",
  "grasshopper",
  "hey google",
  "hey siri",
  "jarvis",
  "ok google",
  "picovoice",
  "porcupine",
  "terminator",
] as const;

const STORAGE_KEY = "agent_config";

const DEFAULTS: AppConfig = {
  agentUrl: BUILD_AGENT_URL || "http://10.0.2.2:8000",
  apiKey: BUILD_API_KEY || "",
  botId: "default",
  clientId: "android-tablet",
  wakeWord: "jarvis",
  wakeWordEnabled: false,
  wakeWordSensitivity: 1,
  wakeWordGain: 1.0,
  wakeWordTrimMs: 800,
  picovoiceAccessKey: BUILD_PICOVOICE_KEY || "",
  ttsEnabled: true,
  ttsVoice: "en-US-language",
  ttsSpeed: 1.0,
  listenSound: "chime",
  overlayEnabled: true,
  audioNative: false,
  transcriptionMode: "server",
};

let cachedConfig: AppConfig | null = null;

export async function loadConfig(): Promise<AppConfig> {
  if (cachedConfig) return cachedConfig;

  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      const merged = { ...DEFAULTS };
      for (const key of Object.keys(saved) as Array<keyof AppConfig>) {
        const val = saved[key];
        if (val !== undefined && val !== null) {
          if (typeof val === "string" && val === "" && DEFAULTS[key] !== "") {
            continue;
          }
          (merged as any)[key] = val;
        }
      }
      cachedConfig = merged;
      return merged;
    }
  } catch {}
  cachedConfig = { ...DEFAULTS };
  return cachedConfig;
}

export async function saveConfig(config: Partial<AppConfig>): Promise<AppConfig> {
  cachedConfig = null;
  const current = await loadConfig();
  const merged = { ...current, ...config };
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  cachedConfig = merged;
  return merged;
}

export async function getConfigValue<K extends keyof AppConfig>(key: K): Promise<AppConfig[K]> {
  const config = await loadConfig();
  return config[key];
}
