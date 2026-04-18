/**
 * Import handoff store — used when the Recent tab hands a real tool-call
 * result to the Templates editor. The editor reads on mount and consumes
 * the payload; subsequent refreshes of the Templates tab do not re-apply.
 *
 * Kept trivial (zustand create, no middleware) so it doesn't outlive the
 * handoff — callers must always consume() after reading.
 */
import { create } from "zustand";

export interface WidgetImportPayload {
  toolName: string;
  samplePayload: unknown;
}

interface WidgetImportState {
  pending: WidgetImportPayload | null;
  set: (payload: WidgetImportPayload) => void;
  consume: () => WidgetImportPayload | null;
  clear: () => void;
}

export const useWidgetImportStore = create<WidgetImportState>()((set, get) => ({
  pending: null,
  set: (payload) => set({ pending: payload }),
  consume: () => {
    const payload = get().pending;
    if (payload) set({ pending: null });
    return payload;
  },
  clear: () => set({ pending: null }),
}));
