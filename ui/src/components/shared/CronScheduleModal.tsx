import { useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { useThemeTokens } from "../../theme/tokens";
import { CronInput, parseCronShape } from "./CronInput";

interface Props {
  title?: string;
  initial?: string | null;
  onClose: () => void;
  onSave: (expr: string | null) => Promise<void> | void;
}

/** Modal wrapping CronInput with Save / Clear schedule / Cancel. */
export function CronScheduleModal({ title = "Schedule", initial, onClose, onSave }: Props) {
  const t = useThemeTokens();
  const [value, setValue] = useState<string>(initial ?? "");
  const [busy, setBusy] = useState(false);
  const shape = parseCronShape(value);
  const canSave = shape.valid && !busy;

  const save = async (expr: string | null) => {
    try {
      setBusy(true);
      await onSave(expr);
      onClose();
    } finally {
      setBusy(false);
    }
  };

  if (typeof document === "undefined") return null;

  return createPortal(
    <>
      <div
        onClick={onClose}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.5)",
          zIndex: 10020,
        }}
      />
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 440,
          maxWidth: "92vw",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          padding: 20,
        }}
      >
        <div
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            justifyContent: "space-between",
            marginBottom: 14,
          }}
        >
          <span style={{ fontSize: 14, fontWeight: 700, color: t.text }}>{title}</span>
          <button
            onClick={onClose}
            style={{
              background: "transparent",
              border: "none",
              cursor: "pointer",
              padding: 4,
              color: t.textMuted,
              display: "flex",
              alignItems: "center",
            }}
          >
            <X size={16} />
          </button>
        </div>

        <CronInput value={value} onChange={setValue} />

        <div
          style={{
            display: "flex",
            flexDirection: "row",
            justifyContent: "space-between",
            marginTop: 20,
            gap: 8,
          }}
        >
          <button
            type="button"
            onClick={() => save(null)}
            disabled={busy || !initial}
            style={{
              background: "transparent",
              border: `1px solid ${t.surfaceBorder}`,
              color: initial ? t.danger : t.textDim,
              borderRadius: 8,
              padding: "6px 12px",
              fontSize: 12,
              fontWeight: 500,
              cursor: initial && !busy ? "pointer" : "default",
            }}
          >
            Clear schedule
          </button>
          <div style={{ display: "flex", flexDirection: "row", gap: 8 }}>
            <button
              type="button"
              onClick={onClose}
              disabled={busy}
              style={{
                background: "transparent",
                border: `1px solid ${t.surfaceBorder}`,
                color: t.textMuted,
                borderRadius: 8,
                padding: "6px 12px",
                fontSize: 12,
                fontWeight: 500,
                cursor: busy ? "default" : "pointer",
              }}
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={() => save(value.trim())}
              disabled={!canSave}
              style={{
                background: canSave ? t.accent : t.surfaceBorder,
                border: "none",
                color: canSave ? "#fff" : t.textDim,
                borderRadius: 8,
                padding: "6px 14px",
                fontSize: 12,
                fontWeight: 600,
                cursor: canSave ? "pointer" : "default",
              }}
            >
              {busy ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}
