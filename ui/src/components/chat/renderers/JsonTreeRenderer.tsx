/**
 * JSON tree renderer with collapsible objects/arrays.
 *
 * Used for any envelope whose content_type is `application/json`. Falls
 * back to a plain pretty-printed view if the body fails to parse.
 */
import { useState } from "react";
import { ChevronRight, ChevronDown } from "lucide-react";
import type { ThemeTokens } from "../../../theme/tokens";
import type { RichRendererChromeMode, RichRendererVariant } from "./genericRendererChrome";
import { resolveCodeShell } from "./genericRendererChrome";

interface Props {
  body: string;
  rendererVariant?: RichRendererVariant;
  chromeMode?: RichRendererChromeMode;
  t: ThemeTokens;
}

/** Count total nodes in a JSON value (objects, arrays, and primitives). */
function countNodes(value: unknown, cap = 100): number {
  if (value === null || typeof value !== "object") return 1;
  let n = 1;
  const entries = Array.isArray(value) ? value : Object.values(value as Record<string, unknown>);
  for (const v of entries) {
    n += countNodes(v, cap);
    if (n >= cap) return cap;
  }
  return n;
}

/** When the tree is small, expand everything. Otherwise depth-limit. */
const SMALL_TREE_THRESHOLD = 60;

export function JsonTreeRenderer({
  body,
  rendererVariant = "default-chat",
  chromeMode = "standalone",
  t,
}: Props) {
  let parsed: unknown;
  try {
    parsed = JSON.parse(body);
  } catch {
    return (
      <pre
        style={{
          ...resolveCodeShell({ t, rendererVariant, chromeMode }),
          whiteSpace: "pre-wrap",
        }}
      >
        {body}
      </pre>
    );
  }

  const nodeCount = countNodes(parsed);
  // Small trees expand fully; larger ones use depth-based collapsing.
  const expandDepth = nodeCount < SMALL_TREE_THRESHOLD ? 20 : 2;

  return (
    <div
      style={{
        ...resolveCodeShell({ t, rendererVariant, chromeMode }),
        lineHeight: rendererVariant === "terminal-chat" ? 1.45 : 1.55,
      }}
    >
      <JsonNode value={parsed} t={t} keyPath="$" depth={0} expandDepth={expandDepth} />
    </div>
  );
}

function JsonNode({
  value,
  t,
  keyPath,
  depth,
  expandDepth = 2,
}: {
  value: unknown;
  t: ThemeTokens;
  keyPath: string;
  depth: number;
  expandDepth?: number;
}) {
  const [open, setOpen] = useState(depth < expandDepth);

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
                <JsonNode value={item} t={t} keyPath={`${keyPath}.${i}`} depth={depth + 1} expandDepth={expandDepth} />
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
                <JsonNode value={v} t={t} keyPath={`${keyPath}.${k}`} depth={depth + 1} expandDepth={expandDepth} />
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
