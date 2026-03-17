import AsyncStorage from "@react-native-async-storage/async-storage";
import { BUILD_API_KEY, BUILD_AGENT_URL, BUILD_PICOVOICE_KEY } from "./env.generated";

export interface AppConfig {
  agentUrl: string;
  apiKey: string;
  botId: string;
  clientId: string;
  wakeWord: string;
  wakeWordEnabled: boolean;
  picovoiceAccessKey: string;
  ttsEnabled: boolean;
  ttsVoice: string;
  ttsSpeed: number;
  listenSound: string;
  overlayEnabled: boolean;
  audioNative: boolean;
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
  picovoiceAccessKey: BUILD_PICOVOICE_KEY || "",
  ttsEnabled: true,
  ttsVoice: "",
  ttsSpeed: 1.0,
  listenSound: "chime",
  overlayEnabled: true,
  audioNative: false,
};

export async function loadConfig(): Promise<AppConfig> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw) {
      const saved = JSON.parse(raw);
      // Don't let empty saved values override build-time defaults.
      // If the user never set a value, the saved "" shouldn't clobber
      // a key that was baked in from .env at build time.
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
      return merged;
    }
  } catch {}
  return { ...DEFAULTS };
}

export async function saveConfig(config: Partial<AppConfig>): Promise<AppConfig> {
  const current = await loadConfig();
  const merged = { ...current, ...config };
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(merged));
  return merged;
}

export async function getConfigValue<K extends keyof AppConfig>(key: K): Promise<AppConfig[K]> {
  const config = await loadConfig();
  return config[key];
}
