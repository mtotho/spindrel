import type { ReactNode } from "react";

export function HighlightedLabel({
  text,
  indices,
  color,
  accentColor,
}: {
  text: string;
  indices: number[];
  color: string;
  accentColor: string;
}) {
  if (indices.length === 0) {
    return <>{text}</>;
  }
  const set = new Set(indices);
  const parts: ReactNode[] = [];
  let run = "";
  let inMatch = false;

  for (let i = 0; i <= text.length; i++) {
    const isMatch = set.has(i);
    if (i === text.length || isMatch !== inMatch) {
      if (run) {
        parts.push(
          inMatch ? (
            <span key={i} style={{ color: accentColor, fontWeight: 600 }}>{run}</span>
          ) : (
            <span key={i} style={{ color }}>{run}</span>
          ),
        );
      }
      run = "";
      inMatch = isMatch;
    }
    if (i < text.length) run += text[i];
  }

  return <>{parts}</>;
}
