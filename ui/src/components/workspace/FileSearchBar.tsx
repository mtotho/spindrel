import { useRef, useEffect, useCallback } from "react";
import { Search, X, ChevronUp, ChevronDown } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";

interface FileSearchBarProps {
  query: string;
  onQueryChange: (q: string) => void;
  matchCount: number;
  currentMatch: number; // 0-indexed
  onNext: () => void;
  onPrev: () => void;
  onClose: () => void;
}

export function FileSearchBar({
  query, onQueryChange, matchCount, currentMatch, onNext, onPrev, onClose,
}: FileSearchBarProps) {
  const t = useThemeTokens();
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      onClose();
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (e.shiftKey) onPrev();
      else onNext();
    }
  }, [onClose, onNext, onPrev]);

  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: 6,
        padding: "4px 12px",
        borderBottom: `1px solid ${t.surfaceBorder}`,
        background: t.surfaceOverlay,
        flexShrink: 0,
      }}
    >
      <Search size={13} color={t.textDim} />
      <input
        ref={inputRef}
        type="text"
        value={query}
        onChange={(e) => onQueryChange(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Find in file..."
        style={{
          flex: 1,
          background: t.inputBg,
          border: `1px solid ${t.inputBorder}`,
          borderRadius: 4,
          padding: "3px 8px",
          color: t.inputText,
          fontSize: 12,
          outline: "none",
          minWidth: 0,
          maxWidth: 300,
        }}
      />
      {query && (
        <span style={{ fontSize: 11, color: t.textMuted, whiteSpace: "nowrap" }}>
          {matchCount > 0 ? `${currentMatch + 1} of ${matchCount}` : "No results"}
        </span>
      )}
      <button
        onClick={onPrev}
        disabled={matchCount === 0}
        title="Previous (Shift+Enter)"
        style={{
          background: "none", border: "none", padding: 2, cursor: matchCount ? "pointer" : "default",
          color: matchCount ? t.textMuted : t.textDim, display: "flex",
        }}
      >
        <ChevronUp size={14} />
      </button>
      <button
        onClick={onNext}
        disabled={matchCount === 0}
        title="Next (Enter)"
        style={{
          background: "none", border: "none", padding: 2, cursor: matchCount ? "pointer" : "default",
          color: matchCount ? t.textMuted : t.textDim, display: "flex",
        }}
      >
        <ChevronDown size={14} />
      </button>
      <button
        onClick={onClose}
        title="Close (Esc)"
        style={{
          background: "none", border: "none", padding: 2, cursor: "pointer",
          color: t.textMuted, display: "flex",
        }}
      >
        <X size={14} />
      </button>
    </div>
  );
}

/** Highlights search matches in a line of text, returns array of spans */
export function highlightMatches(
  text: string,
  query: string,
  lineIndex: number,
  matchPositions: Array<{ line: number; col: number }>,
  currentMatch: number,
  highlightBg: string,
  currentHighlightBg: string,
): React.ReactNode[] {
  if (!query || !text) return [text || " "];

  const lowerText = text.toLowerCase();
  const lowerQuery = query.toLowerCase();
  const parts: React.ReactNode[] = [];
  let lastEnd = 0;

  // Find all matches in this line
  let searchFrom = 0;
  while (searchFrom < lowerText.length) {
    const idx = lowerText.indexOf(lowerQuery, searchFrom);
    if (idx === -1) break;

    // Is this the current match?
    const isCurrent = matchPositions.some(
      (m, mi) => mi === currentMatch && m.line === lineIndex && m.col === idx
    );

    if (idx > lastEnd) {
      parts.push(text.slice(lastEnd, idx));
    }
    parts.push(
      <mark
        key={`${idx}-${lineIndex}`}
        data-current-match={isCurrent ? "true" : undefined}
        style={{
          background: isCurrent ? currentHighlightBg : highlightBg,
          color: "inherit",
          borderRadius: 2,
          padding: "0 1px",
        }}
      >
        {text.slice(idx, idx + query.length)}
      </mark>
    );
    lastEnd = idx + query.length;
    searchFrom = idx + 1; // allow overlapping matches
  }

  if (lastEnd < text.length) {
    parts.push(text.slice(lastEnd));
  }
  if (parts.length === 0) return [text || " "];
  return parts;
}

/** Compute all match positions (line, col) for a query in lines */
export function computeMatchPositions(
  lines: string[],
  query: string,
): Array<{ line: number; col: number }> {
  if (!query) return [];
  const lowerQuery = query.toLowerCase();
  const positions: Array<{ line: number; col: number }> = [];
  for (let i = 0; i < lines.length; i++) {
    const lowerLine = lines[i].toLowerCase();
    let searchFrom = 0;
    while (searchFrom < lowerLine.length) {
      const idx = lowerLine.indexOf(lowerQuery, searchFrom);
      if (idx === -1) break;
      positions.push({ line: i, col: idx });
      searchFrom = idx + 1;
    }
  }
  return positions;
}
