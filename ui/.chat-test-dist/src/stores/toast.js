import { create } from "zustand";
let nextId = 0;
export const useToastStore = create()((set, get) => ({
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
export function toast(t) {
    return useToastStore.getState().push(t);
}
