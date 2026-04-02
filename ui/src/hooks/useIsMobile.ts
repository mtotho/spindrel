import { useWindowDimensions } from "react-native";

/** Returns true when viewport width is below 640px (mobile breakpoint). */
export function useIsMobile(): boolean {
  const { width } = useWindowDimensions();
  return width < 640;
}
