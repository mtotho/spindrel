import { useWindowDimensions } from "react-native";

type ColumnMode = "single" | "double" | "triple";

const BREAKPOINTS = { double: 768, triple: 1200 };

export function useResponsiveColumns(): ColumnMode {
  const { width } = useWindowDimensions();
  if (width >= BREAKPOINTS.triple) return "triple";
  if (width >= BREAKPOINTS.double) return "double";
  return "single";
}
