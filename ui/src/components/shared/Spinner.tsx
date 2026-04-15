/**
 * CSS-based loading spinner. Replaces ActivityIndicator from react-native.
 * Uses the .chat-spinner class from global.css.
 */
export function Spinner({ size = 20, color = "#3b82f6" }: { size?: number; color?: string }) {
  return (
    <div
      className="chat-spinner"
      style={{
        width: size,
        height: size,
        borderColor: color,
        borderTopColor: "transparent",
      }}
    />
  );
}
