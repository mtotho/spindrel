import { useState } from "react";
import { createPortal } from "react-dom";
import { X } from "lucide-react";
import { CronInput, parseCronShape } from "./CronInput";
import { ActionButton } from "./SettingsControls";

interface Props {
  title?: string;
  initial?: string | null;
  onClose: () => void;
  onSave: (expr: string | null) => Promise<void> | void;
}

/** Modal wrapping CronInput with Save / Clear schedule / Cancel. */
export function CronScheduleModal({ title = "Schedule", initial, onClose, onSave }: Props) {
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
        className="fixed inset-0 z-[10020] bg-surface/75"
      />
      <div
        className="fixed left-1/2 top-1/2 z-[10021] w-[440px] max-w-[92vw] -translate-x-1/2 -translate-y-1/2 rounded-md border border-surface-border bg-surface-raised p-5"
      >
        <div className="mb-3.5 flex items-center justify-between">
          <span className="text-[14px] font-semibold text-text">{title}</span>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center p-1 text-text-muted transition-colors hover:text-text"
          >
            <X size={16} />
          </button>
        </div>

        <CronInput value={value} onChange={setValue} />

        <div className="mt-5 flex flex-wrap justify-between gap-2">
          <ActionButton
            label="Clear schedule"
            onPress={() => save(null)}
            disabled={busy || !initial}
            variant="danger"
            size="small"
          />
          <div className="flex gap-2">
            <ActionButton label="Cancel" onPress={onClose} disabled={busy} variant="secondary" size="small" />
            <ActionButton
              label={busy ? "Saving..." : "Save"}
              onPress={() => save(value.trim())}
              disabled={!canSave}
              size="small"
            />
          </div>
        </div>
      </div>
    </>,
    document.body,
  );
}
