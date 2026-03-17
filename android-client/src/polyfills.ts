import { getRandomValues } from "expo-crypto";

// uuid requires crypto.getRandomValues which Hermes doesn't provide natively
if (typeof globalThis.crypto === "undefined") {
  (globalThis as any).crypto = {};
}
if (typeof globalThis.crypto.getRandomValues === "undefined") {
  globalThis.crypto.getRandomValues = getRandomValues as any;
}
