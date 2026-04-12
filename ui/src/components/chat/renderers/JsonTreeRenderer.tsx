/**
 * JSON tree renderer with collapsible objects/arrays.
 *
 * Used for any envelope whose content_type is `application/json`. Falls
 * back to a plain pretty-printed view if the body fails to parse.
 */
import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import type { ThemeTokens } from "../../../theme/tokens";

interface Props {
  body: string;
  t: ThemeTokens;
}

export function JsonTreeRenderer({ body, t }: Props) {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return (
      <pre
        style={{
          margin: 0,
          padding: "8px 12px",
          borderRadius: 8,
          background: t.codeBg,
          border: `1px solid ${t.codeBorder}`,
          fontFamily: "'Menlo', monospace",
          fontSize: 12,
          color: t.contentText,
          whiteSpace: "pre-wrap",
          maxHeight: 400,
          overflowY: "auto",
        }}
      >
        {body}
      </pre>
    );
  }

  return (
    <div
      style={{
        padding: "8px 12px",
        borderRadius: 8,
        background: t.codeBg,
        border: `1px solid ${t.codeBorder}`,
        fontFamily: "'Menlo', monospace",
        fontSize: 12,
        lineHeight: 1.55,
        color: t.contentText,
        maxHeight: 400,
        overflowY: "auto",
      }}
    >
      <JsonNode value={parsed} t={t} keyPath="$" depth={0} />
    </div>
  );
}

function JsonNode({
  value,
  t,
  keyPath,
  depth,
  defaultOpen = true,
}: {
  value: unknown;
  t: ThemeTokens;
  keyPath: string;
  depth: number;
  defaultOpen?: boolean;
}) {
  // Auto-collapse deeply nested values to keep first-paint compact.
  const [open, setOpen] = useState(defaultOpen && depth < 2);

  if (value === null) return <span style={{ color: t.textDim }}>null</span>;
  if (typeof value === "boolean") return <span style={{ color: t.purple }}>{String(value)}</span>;
  if (typeof value === "number") return <span style={{ color: t.warning }}>{value}</span>;
  if (typeof value === "string")
    return <span style={{ color: t.success }}>"{value}"</span>;

  if (Array.isArray(value)) {
    if (value.length === 0) return <span style={{ color: t.textDim }}>[]</span>;
    return (
      <span>
        <ToggleChevron open={open} onClick={() => setOpen((o) => !o)} t={t} />
        <span style={{ color: t.textMuted }}>[{value.length}]</span>
        {open && (
          <div style={{ marginLeft: 14 }}>
            {value.map((item, i) => (
              <div key={`${keyPath}.${i}`}>
                <span style={{ color: t.textDim }}>{i}: </span>
                <JsonNode value={item} t={t} keyPath={`${keyPath}.${i}`} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  if (typeof value === "object") {
    const entries = Object.entries(value as Record<string, unknown>);
    if (entries.length === 0) return <span style={{ color: t.textDim }}>{`{}`}</span>;
    return (
      <span>
        <ToggleChevron open={open} onClick={() => setOpen((o) => !o)} t={t} />
        <span style={{ color: t.textMuted }}>{`{${entries.length}}`}</span>
        {open && (
          <div style={{ marginLeft: 14 }}>
            {entries.map(([k, v]) => (
              <div key={`${keyPath}.${k}`}>
                <span style={{ color: t.accent }}>"{k}"</span>
                <span style={{ color: t.textMuted }}>: </span>
                <JsonNode value={v} t={t} keyPath={`${keyPath}.${k}`} depth={depth + 1} />
              </div>
            ))}
          </div>
        )}
      </span>
    );
  }

  return <span style={{ color: t.textDim }}>{String(value)}</span>;
}

function ToggleChevron({
  open,
  onClick,
  t,
}: {
  open: boolean;
  onClick: () => void;
  t: ThemeTokens;
}) {
  const Icon = open ? ChevronDown : ChevronRight;
  return (
    <span
      onClick={onClick}
      style={{
        display: "inline-block",
        verticalAlign: "middle",
        cursor: "pointer",
        marginRight: 2,
      }}
    >
      <Icon size={12} color={t.textDim} />
    </span>
  );
}
