import { create } from "zustand";

export type WidgetLogLevel = "info" | "warn" | "error";

export interface WidgetLogEntry {
  id: string;
  ts: number;
  level: WidgetLogLevel;
  message: string;
  pinId: string | null;
  channelId: string | null;
  botId: string | null;
  botName: string | null;
  widgetPath: string | null;
}

interface WidgetLogState {
  entries: WidgetLogEntry[];
  push: (entry: Omit<WidgetLogEntry, "id">) => void;
  clear: () => void;
}

const LOG_CAP = 500;
let nextId = 0;

export const useWidgetLogStore = create<WidgetLogState>()((set) => ({
  entries: [],
  push: (entry) => {
    const id = `wl-${++nextId}-${entry.ts}`;
    set((s) => {
      const next = s.entries.length >= LOG_CAP
        ? [...s.entries.slice(s.entries.length - LOG_CAP + 1), { id, ...entry }]
        : [...s.entries, { id, ...entry }];
      return { entries: next };
    });
  },
  clear: () => set({ entries: [] }),
}));

export function pushWidgetLog(entry: Omit<WidgetLogEntry, "id">): void {
  useWidgetLogStore.getState().push(entry);
}
