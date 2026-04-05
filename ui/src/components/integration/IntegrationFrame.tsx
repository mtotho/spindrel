import { useRef, useCallback, useEffect } from "react";
import { useAuthStore } from "../../stores/auth";
import { useThemeStore } from "../../stores/theme";

interface IntegrationFrameProps {
  src: string;
}

/**
 * Reusable iframe wrapper for integration web UIs.
 *
 * - Borderless, fills container (parent must have flex-1)
 * - On iframe load: sends auth token + theme via postMessage
 * - Watches theme store and re-sends on changes
 */
export function IntegrationFrame({ src }: IntegrationFrameProps) {
  const iframeRef = useRef<HTMLIFrameElement>(null);
  const token = useAuthStore((s) => s.accessToken || s.apiKey);
  const serverUrl = useAuthStore((s) => s.serverUrl);
  const themeMode = useThemeStore((s) => s.mode);

  const sendMessage = useCallback(
    (data: Record<string, unknown>) => {
      const iframe = iframeRef.current;
      if (!iframe?.contentWindow) return;
      iframe.contentWindow.postMessage(data, "*");
    },
    [],
  );

  const sendAuth = useCallback(() => {
    sendMessage({ type: "spindrel:auth", token, serverUrl });
  }, [sendMessage, token, serverUrl]);

  const sendTheme = useCallback(() => {
    sendMessage({ type: "spindrel:theme", mode: themeMode });
  }, [sendMessage, themeMode]);

  // Re-send theme whenever it changes
  useEffect(() => {
    sendTheme();
  }, [sendTheme]);

  const handleLoad = useCallback(() => {
    sendAuth();
    sendTheme();
  }, [sendAuth, sendTheme]);

  return (
    <div style={{ flex: 1, display: "flex", flexDirection: "column" }}>
      <iframe
        ref={iframeRef}
        src={src}
        onLoad={handleLoad}
        style={{
          width: "100%",
          height: "100%",
          border: "none",
          display: "block",
        }}
        allow="clipboard-read; clipboard-write"
      />
    </div>
  );
}
