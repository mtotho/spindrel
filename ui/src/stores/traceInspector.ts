import { create } from "zustand";

export interface TraceInspectorRequest {
  correlationId: string;
  title?: string;
  subtitle?: string;
}

interface TraceInspectorState {
  request: TraceInspectorRequest | null;
  openTrace: (request: TraceInspectorRequest | string) => void;
  closeTrace: () => void;
}

export const useTraceInspectorStore = create<TraceInspectorState>()((set) => ({
  request: null,
  openTrace: (request) => set({
    request: typeof request === "string" ? { correlationId: request } : request,
  }),
  closeTrace: () => set({ request: null }),
}));

export function openTraceInspector(request: TraceInspectorRequest | string) {
  useTraceInspectorStore.getState().openTrace(request);
}
