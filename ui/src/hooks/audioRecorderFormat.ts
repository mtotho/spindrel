/** Preferred MIME types in order; first supported wins. */
export const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

/** Extract a simple format string from a MIME type, e.g. audio/webm;codecs=opus -> webm. */
export function mimeToFormat(mime: string): string {
  const base = mime.split(";")[0];
  return base.split("/")[1] || "webm";
}
