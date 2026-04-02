/**
 * Persisted scope context — reads initial value from MC prefs,
 * writes back on change. All pages consume useScope() instead of local state.
 */
import { createContext, useContext, useState, useCallback, useEffect } from "react";
import type { ReactNode } from "react";
import { usePrefs, useUpdatePrefs } from "../hooks/useMC";

interface ScopeCtx {
  scope: string | undefined;
  setScope: (s: string | undefined) => void;
}

const Ctx = createContext<ScopeCtx>({ scope: undefined, setScope: () => {} });

export function ScopeProvider({ children }: { children: ReactNode }) {
  const { data: prefs } = usePrefs();
  const updatePrefs = useUpdatePrefs();
  const [scope, setScopeLocal] = useState<string | undefined>(undefined);
  const [initialized, setInitialized] = useState(false);

  // Seed from persisted prefs on first load
  useEffect(() => {
    if (prefs && !initialized) {
      const saved = (prefs.layout_prefs as Record<string, unknown>)?.scope as string | undefined;
      if (saved === "personal") setScopeLocal("personal");
      setInitialized(true);
    }
  }, [prefs, initialized]);

  const setScope = useCallback(
    (s: string | undefined) => {
      setScopeLocal(s);
      updatePrefs.mutate({
        layout_prefs: { ...(prefs?.layout_prefs || {}), scope: s ?? "fleet" },
      });
    },
    [prefs, updatePrefs],
  );

  return <Ctx.Provider value={{ scope, setScope }}>{children}</Ctx.Provider>;
}

export function useScope() {
  return useContext(Ctx);
}
