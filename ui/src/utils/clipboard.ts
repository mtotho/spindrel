/**
 * Safe clipboard write with fallback for non-HTTPS contexts.
 *
 * navigator.clipboard is undefined when the page is served over plain HTTP.
 * Falls back to a textarea + document.execCommand("copy") approach.
 */
export async function writeToClipboard(text: string): Promise<void> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }
  } catch {
    // Clipboard API failed — fall through to textarea fallback
  }

  // Fallback for non-HTTPS / unsupported browsers
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  document.execCommand("copy");
  document.body.removeChild(ta);
}
