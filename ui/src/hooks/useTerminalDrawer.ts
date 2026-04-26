import { useCallback, useState } from "react";

export interface OpenTerminalOptions {
  seedCommand?: string;
  cwd?: string;
  title?: string;
  subtitle?: string;
  width?: number;
}

/**
 * Imperative hook for opening the admin terminal drawer from inline
 * handlers. Mirrors the ergonomics of `useConfirm` — caller renders
 * `<TerminalDrawerSlot />` once and then calls `openTerminal({...})`.
 *
 * The slot is built by the consumer (typically inline) so this hook only
 * owns the open/options state.
 */
export function useTerminalDrawer() {
  const [open, setOpen] = useState(false);
  const [options, setOptions] = useState<OpenTerminalOptions>({});

  const openTerminal = useCallback((opts: OpenTerminalOptions = {}) => {
    setOptions(opts);
    setOpen(true);
  }, []);

  const closeTerminal = useCallback(() => {
    setOpen(false);
  }, []);

  return { open, options, openTerminal, closeTerminal };
}
