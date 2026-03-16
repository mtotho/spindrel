import AsyncStorage from "@react-native-async-storage/async-storage";
import { v4 as uuidv4 } from "uuid";

const SESSION_KEY = "session_id";
const BOT_KEY = "active_bot_id";

export async function getSessionId(): Promise<string> {
  let id = await AsyncStorage.getItem(SESSION_KEY);
  if (!id) {
    id = uuidv4();
    await AsyncStorage.setItem(SESSION_KEY, id);
  }
  return id;
}

export async function newSessionId(): Promise<string> {
  const id = uuidv4();
  await AsyncStorage.setItem(SESSION_KEY, id);
  return id;
}

export async function setSessionId(id: string): Promise<void> {
  await AsyncStorage.setItem(SESSION_KEY, id);
}

export async function getActiveBotId(): Promise<string | null> {
  return AsyncStorage.getItem(BOT_KEY);
}

export async function setActiveBotId(botId: string): Promise<void> {
  await AsyncStorage.setItem(BOT_KEY, botId);
}
