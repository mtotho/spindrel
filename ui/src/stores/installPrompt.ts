/* beforeinstallprompt event holder.
 *
 * Chrome/Edge fire `beforeinstallprompt` when PWA install criteria are met.
 * The browser default prompt is suppressed so we can trigger it from an
 * in-app action at a meaningful moment (user-facing "Install Spindrel"
 * button in settings / sidebar footer). iOS Safari doesn't fire this event
 * — users add via Share → Add to Home Screen. */
import { create } from "zustand";

export type BeforeInstallPromptEvent = Event & {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
};

interface InstallPromptState {
  event: BeforeInstallPromptEvent | null;
  setEvent: (e: BeforeInstallPromptEvent | null) => void;
  /** Trigger the browser install UI. Returns the user's choice, or null
   *  when no prompt is available (wrong browser, already installed, etc). */
  promptInstall: () => Promise<"accepted" | "dismissed" | null>;
}

export const useInstallPromptStore = create<InstallPromptState>((set, get) => ({
  event: null,
  setEvent: (event) => set({ event }),
  promptInstall: async () => {
    const e = get().event;
    if (!e) return null;
    await e.prompt();
    const choice = await e.userChoice;
    // Event can only be used once.
    set({ event: null });
    return choice.outcome;
  },
}));
