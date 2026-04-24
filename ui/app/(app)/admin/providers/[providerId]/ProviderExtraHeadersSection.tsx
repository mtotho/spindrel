import { useEffect, useMemo, useState } from "react";
import { Plus, X } from "lucide-react";
import { Section } from "@/src/components/shared/FormControls";

type HeaderRow = { key: string; value: string };

function rowsFromMap(map: Record<string, string> | undefined | null): HeaderRow[] {
  if (!map) return [];
  return Object.entries(map).map(([key, value]) => ({ key, value: String(value) }));
}

function mapFromRows(rows: HeaderRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const k = r.key.trim();
    if (!k) continue;
    out[k] = r.value;
  }
  return out;
}

interface Props {
  initial: Record<string, string> | undefined | null;
  onChange: (next: Record<string, string>) => void;
}

export function ProviderExtraHeadersSection({ initial, onChange }: Props) {
  const [rows, setRows] = useState<HeaderRow[]>(rowsFromMap(initial));

  useEffect(() => {
    setRows(rowsFromMap(initial));
  }, [initial]);

  const computedMap = useMemo(() => mapFromRows(rows), [rows]);

  useEffect(() => {
    onChange(computedMap);
  }, [computedMap, onChange]);

  const updateRow = (idx: number, patch: Partial<HeaderRow>) => {
    setRows((prev) => prev.map((r, i) => (i === idx ? { ...r, ...patch } : r)));
  };
  const addRow = () => setRows((prev) => [...prev, { key: "", value: "" }]);
  const removeRow = (idx: number) => setRows((prev) => prev.filter((_, i) => i !== idx));

  return (
    <Section
      title="Custom Headers"
      description="Sent on every request to this provider. Useful for OpenRouter analytics (HTTP-Referer, X-Title), OpenAI org/project scoping (OpenAI-Organization), or Anthropic beta opt-ins (anthropic-beta)."
    >
      <div className="flex flex-col gap-2">
        {rows.length === 0 && (
          <div className="text-xs text-text-muted py-1">No custom headers</div>
        )}
        {rows.map((row, idx) => (
          <div key={idx} className="flex flex-row items-center gap-2">
            <input
              value={row.key}
              onChange={(e) => updateRow(idx, { key: e.target.value })}
              placeholder="Header-Name"
              className="flex-1 min-w-0 px-2 py-1.5 text-xs font-mono rounded bg-surface-raised border border-surface-border focus:outline-none focus:border-accent"
            />
            <input
              value={row.value}
              onChange={(e) => updateRow(idx, { value: e.target.value })}
              placeholder="value"
              className="flex-[2] min-w-0 px-2 py-1.5 text-xs font-mono rounded bg-surface-raised border border-surface-border focus:outline-none focus:border-accent"
            />
            <button
              onClick={() => removeRow(idx)}
              title="Remove header"
              className="p-1.5 text-text-dim hover:text-danger rounded"
            >
              <X size={14} />
            </button>
          </div>
        ))}
        <button
          onClick={addRow}
          className="self-start flex flex-row items-center gap-1.5 px-2.5 py-1.5 text-xs font-semibold text-text-muted hover:text-text rounded"
        >
          <Plus size={13} />
          Add header
        </button>
      </div>
    </Section>
  );
}
