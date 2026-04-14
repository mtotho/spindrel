import { useWindowSize } from "./useWindowSize";

/** Returns true when viewport width is below 640px (mobile breakpoint). */
export function useIsMobile(): boolean {
  const { width } = useWindowSize();
  return width < 640;
}
