import AsyncStorage from "@react-native-async-storage/async-storage";

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
  agentUrl: "http://10.0.2.2:8000",
  apiKey: "",
  botId: "default",
  clientId: "android-tablet",
  wakeWord: "jarvis",
  wakeWordEnabled: false,
  picovoiceAccessKey: "",
  ttsEnabled: true,
  ttsVoice: "",
  ttsSpeed: 1.0,
  listenSound: "chime",
  overlayEnabled: true,
};

export async function loadConfig(): Promise<AppConfig> {
  try {
    const raw = await AsyncStorage.getItem(STORAGE_KEY);
    if (raw) {
      return { ...DEFAULTS, ...JSON.parse(raw) };
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
