import { create } from "zustand";

export type ToastKind = "success" | "info" | "error";

export interface ToastMessage {
  id: string;
  kind: ToastKind;
  message: string;
  action?: { label: string; onClick: () => void };
}

interface ToastState {
  toasts: ToastMessage[];
  push: (t: Omit<ToastMessage, "id"> & { durationMs?: number }) => string;
  dismiss: (id: string) => void;
}

let nextId = 0;

export const useToastStore = create<ToastState>()((set, get) => ({
  toasts: [],
  push: ({ durationMs = 2200, ...t }) => {
    const id = `t-${++nextId}-${Date.now()}`;
    set((s) => ({ toasts: [...s.toasts, { id, ...t }] }));
    if (durationMs > 0) {
      setTimeout(() => get().dismiss(id), durationMs);
    }
    return id;
  },
  dismiss: (id) => {
    set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) }));
  },
}));

export function toast(t: Omit<ToastMessage, "id"> & { durationMs?: number }) {
  return useToastStore.getState().push(t);
}
