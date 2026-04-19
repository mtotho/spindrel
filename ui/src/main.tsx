import "../global.css";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { RouterProvider } from "react-router-dom";
import { router } from "./router";
import { registerServiceWorker } from "./lib/registerSW";
import { useInstallPromptStore } from "./stores/installPrompt";
import { toast } from "./stores/toast";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <RouterProvider router={router} />
  </StrictMode>,
);

registerServiceWorker({
  onUpdateAvailable: (applyUpdate) => {
    toast({
      kind: "info",
      message: "New version available",
      action: { label: "Reload", onClick: applyUpdate },
      durationMs: 0, // sticky — user acts or dismisses explicitly
    });
  },
});

// Capture Chrome/Edge install-prompt so a "Install Spindrel" action can
// trigger it at a user-chosen moment. iOS has no programmatic equivalent;
// users use Safari's Share → Add to Home Screen.
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  useInstallPromptStore.getState().setEvent(e as Event & { prompt: () => Promise<void>; userChoice: Promise<{ outcome: "accepted" | "dismissed" }> });
});
window.addEventListener("appinstalled", () => {
  useInstallPromptStore.getState().setEvent(null);
});
