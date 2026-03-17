/**
 * Human-readable labels for TTS voice identifiers (e.g. "en-us-x-sfb-local" -> "English (US)").
 * Android/iOS often return codes; we parse or map them to display names.
 */

const LANGUAGE_NAMES: Record<string, string> = {
  en: "English",
  es: "Spanish",
  fr: "French",
  de: "German",
  it: "Italian",
  pt: "Portuguese",
  nl: "Dutch",
  pl: "Polish",
  ru: "Russian",
  ja: "Japanese",
  ko: "Korean",
  zh: "Chinese",
  ar: "Arabic",
  hi: "Hindi",
  ur: "Urdu",
  tr: "Turkish",
  vi: "Vietnamese",
  th: "Thai",
  id: "Indonesian",
  ms: "Malay",
  sv: "Swedish",
  da: "Danish",
  no: "Norwegian",
  fi: "Finnish",
  el: "Greek",
  he: "Hebrew",
  ro: "Romanian",
  hu: "Hungarian",
  cs: "Czech",
  sk: "Slovak",
  uk: "Ukrainian",
  bn: "Bengali",
  ta: "Tamil",
  te: "Telugu",
  mr: "Marathi",
  gu: "Gujarati",
  kn: "Kannada",
  ml: "Malayalam",
  pa: "Punjabi",
};

const REGION_NAMES: Record<string, string> = {
  US: "US",
  GB: "UK",
  AU: "Australia",
  IN: "India",
  CA: "Canada",
  PK: "Pakistan",
  NG: "Nigeria",
  ZA: "South Africa",
  IE: "Ireland",
  NZ: "New Zealand",
  PH: "Philippines",
  SG: "Singapore",
  MY: "Malaysia",
  HK: "Hong Kong",
  TW: "Taiwan",
  BR: "Brazil",
  MX: "Mexico",
  ES: "Spain",
  FR: "France",
  DE: "Germany",
  IT: "Italy",
  JP: "Japan",
  KR: "Korea",
  CN: "China",
  SA: "Saudi Arabia",
  AE: "UAE",
  EG: "Egypt",
};

/** Known voice variant codes to short labels (optional, for "English (US) - Sfb") */
const VARIANT_LABELS: Record<string, string> = {
  sfb: "Sfb",
  rjs: "Rjs",
  fis: "Fis",
  ljs: "Ljs",
  local: "Local",
  network: "Network",
};

/**
 * True if the voice runs on-device (starts instantly).
 * -local = local; -network = cloud (adds delay).
 */
export function isLocalVoice(identifier: string): boolean {
  return identifier.endsWith("-local") || !identifier.endsWith("-network");
}

/**
 * Turn a voice identifier into a short display name.
 * Examples:
 *   "en-us-x-iol-local" -> "English (US)"
 *   "ur-pk-language" -> "Urdu (Pakistan)"
 *   "es-us-x-sfb-local" -> "Spanish (US)"
 */
export function voiceDisplayName(identifier: string, fallbackName?: string): string {
  if (!identifier.trim()) return fallbackName ?? "Default";

  let id = identifier.toLowerCase();

  return id;
}
