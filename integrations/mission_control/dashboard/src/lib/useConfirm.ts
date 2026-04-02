import { useState, useRef, useCallback } from "react";

/**
 * Two-step confirm hook. First click sets confirming=true,
 * auto-resets after 3 seconds. Caller renders "Are you sure?" on second click.
 */
export function useConfirm() {
  const [confirming, setConfirming] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>();

  const requestConfirm = useCallback(() => {
    setConfirming(true);
    clearTimeout(timer.current);
    timer.current = setTimeout(() => setConfirming(false), 3000);
  }, []);

  const cancel = useCallback(() => {
    clearTimeout(timer.current);
    setConfirming(false);
  }, []);

  const reset = useCallback(() => {
    clearTimeout(timer.current);
    setConfirming(false);
  }, []);

  return { confirming, requestConfirm, cancel, reset };
}
