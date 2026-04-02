import { Platform } from "react-native";

/**
 * Download content as a file (web only).
 * On non-web platforms this is a no-op.
 */
export function downloadBlob(
  content: string,
  filename: string,
  mimeType: string = "text/plain",
): void {
  if (Platform.OS !== "web") return;
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
