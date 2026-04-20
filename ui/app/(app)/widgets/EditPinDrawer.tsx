/**
 * EditPinDrawer — per-pin display_label + widget_config editor.
 *
 * Opens as a right-side drawer from the dashboard page when the user clicks
 * the pencil icon on a pin (only visible in Edit layout mode). widget_config
 * has no canonical schema today, so the editor is a JSON textarea with
 * parse-time validation. Save replaces the config outright (merge:false) —
 * action-dispatched button flips stay on merge:true semantics.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Maximize2, Minimize2, X } from "lucide-react";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";

const HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive";

interface Props {
  pinId: string | null;
  onClose: () => void;
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

export function EditPinDrawer({ pinId, onClose }: Props) {
  const pin = useDashboardPinsStore((s) =>
    pinId ? s.pins.find((p) => p.id === pinId) ?? null : null,
  );
  const renamePin = useDashboardPinsStore((s) => s.renamePin);
  const replaceConfig = useDashboardPinsStore((s) => s.replaceWidgetConfig);
  const promotePanel = useDashboardPinsStore((s) => s.promotePinToPanel);
  const demotePanel = useDashboardPinsStore((s) => s.demotePinFromPanel);

  const [label, setLabel] = useState("");
  const [jsonText, setJsonText] = useState("{}");
  const [saving, setSaving] = useState(false);
  const [panelBusy, setPanelBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);

  useEffect(() => {
    if (!pin) return;
    setLabel(pin.display_label ?? "");
    setJsonText(prettyJson(pin.widget_config ?? {}));
    setError(null);
    setSavedFlash(false);
  }, [pin?.id]);

  // Close on Escape — standard modal UX.
  useEffect(() => {
    if (!pinId) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [pinId, onClose]);

  // Cmd/Ctrl + Enter saves while the drawer is open.
  const kbdSaveRef = useRef<() => void>(() => {});
  useEffect(() => {
    if (!pinId) return;
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        kbdSaveRef.current();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [pinId]);

  const parsedConfig = useMemo<Record<string, unknown> | null>(() => {
    const trimmed = jsonText.trim();
    if (trimmed === "") return {};
    try {
      const v = JSON.parse(trimmed);
      if (v && typeof v === "object" && !Array.isArray(v)) {
        return v as Record<string, unknown>;
      }
      return null;
    } catch {
      return null;
    }
  }, [jsonText]);

  const jsonError = parsedConfig === null;
  const isOpen = !!pinId;

  if (!isOpen) return null;

  const currentLabel = pin?.display_label ?? "";
  const currentConfig = prettyJson(pin?.widget_config ?? {});
  const dirty =
    (label.trim() || null) !== (currentLabel.trim() || null) ||
    jsonText !== currentConfig;

  const canSave = !!pin && dirty && !saving && !jsonError;

  const handleSave = async () => {
    if (!pin || !parsedConfig) return;
    setSaving(true);
    setError(null);
    try {
      const ops: Promise<unknown>[] = [];
      const newLabel = label.trim() || null;
      if (newLabel !== (pin.display_label ?? null)) {
        ops.push(renamePin(pin.id, newLabel));
      }
      if (jsonText !== currentConfig) {
        ops.push(replaceConfig(pin.id, parsedConfig));
      }
      await Promise.all(ops);
      setSavedFlash(true);
      window.setTimeout(() => setSavedFlash(false), 1800);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  const handleReset = () => {
    setJsonText("{}");
  };

  const isHtmlWidget = pin?.envelope?.content_type === HTML_INTERACTIVE_CT;
  const isPanelPin = !!pin?.is_main_panel;

  const handlePanelToggle = async () => {
    if (!pin) return;
    setPanelBusy(true);
    setError(null);
    try {
      if (isPanelPin) {
        await demotePanel(pin.id);
      } else {
        await promotePanel(pin.id);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setPanelBusy(false);
    }
  };

  // Bind the keyboard shortcut to the latest save handler (closure capture
  // would otherwise freeze the disabled/parsed-json state from first paint).
  kbdSaveRef.current = () => {
    if (canSave) void handleSave();
  };

  return (
    <>
      {/* Backdrop */}
      <div
        className="fixed inset-0 z-40 bg-black/60 backdrop-blur-[2px]"
        onClick={onClose}
        role="presentation"
      />
      {/* Drawer */}
      <div
        className="fixed right-0 top-0 bottom-0 z-50 w-full sm:w-[440px] flex flex-col border-l border-surface-border bg-surface-raised shadow-2xl"
        role="dialog"
        aria-label="Edit pin"
      >
        <header className="flex items-center justify-between border-b border-surface-border px-4 py-3">
          <div className="flex flex-col">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
              Edit pin
            </span>
            <span className="text-[13px] font-mono text-text truncate max-w-[320px]">
              {pin?.tool_name ?? "—"}
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-md text-text-muted hover:bg-surface-overlay hover:text-text transition-colors"
            title="Close"
            aria-label="Close"
          >
            <X size={16} />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-4">
          <label className="flex flex-col gap-1">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
              Display label
            </span>
            <input
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              placeholder={pin?.envelope?.display_label ?? pin?.tool_name ?? ""}
              className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent"
            />
            <span className="text-[11px] text-text-dim">
              Leave empty to fall back to the widget's own label.
            </span>
          </label>

          {isHtmlWidget && (
            <div className="flex flex-col gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                  Dashboard panel
                </span>
                {isPanelPin && (
                  <span className="text-[10px] font-medium text-accent">
                    Active
                  </span>
                )}
              </div>
              <p className="text-[11px] text-text-muted leading-snug">
                {isPanelPin
                  ? "This pin owns the dashboard's main area. Other pins surface in the rail strip alongside it."
                  : "Promote to give this widget the dashboard's main area; existing tiles move to the rail strip."}
              </p>
              <button
                type="button"
                onClick={handlePanelToggle}
                disabled={panelBusy}
                className={
                  "inline-flex w-fit items-center gap-1.5 rounded-md border px-2.5 py-1 text-[12px] font-medium transition-colors " +
                  (isPanelPin
                    ? "border-surface-border text-text-muted hover:bg-surface-overlay"
                    : "border-accent/60 bg-accent/10 text-accent hover:bg-accent/20") +
                  " disabled:opacity-50 disabled:cursor-not-allowed"
                }
              >
                {panelBusy && <Loader2 size={12} className="animate-spin" />}
                {isPanelPin ? <Minimize2 size={12} /> : <Maximize2 size={12} />}
                {isPanelPin ? "Demote from panel" : "Promote to dashboard panel"}
              </button>
            </div>
          )}

          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                Widget config (JSON)
              </span>
              <button
                type="button"
                onClick={handleReset}
                className="text-[11px] text-text-muted hover:text-text underline"
              >
                Reset to {"{}"}
              </button>
            </div>
            <textarea
              value={jsonText}
              onChange={(e) => setJsonText(e.target.value)}
              spellCheck={false}
              className={
                "h-64 resize-none rounded-md border bg-input px-2.5 py-2 font-mono text-[12px] leading-relaxed text-text outline-none focus:border-accent " +
                (jsonError ? "border-danger/60" : "border-surface-border")
              }
            />
            {jsonError ? (
              <span className="text-[11px] text-danger">
                Invalid JSON — config must be a JSON object.
              </span>
            ) : (
              <span className="text-[11px] text-text-dim">
                Save replaces the entire config object.
              </span>
            )}
          </div>

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}
        </div>

        <footer className="flex items-center justify-end gap-2 border-t border-surface-border px-4 py-3">
          {savedFlash && (
            <span className="mr-auto text-[12px] text-success">
              Saved.
            </span>
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-surface-border px-3 py-1.5 text-[12px] text-text-muted hover:bg-surface-overlay"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            disabled={!canSave}
            className="inline-flex items-center gap-1.5 rounded-md bg-accent px-3 py-1.5 text-[12px] font-medium text-white hover:opacity-90 disabled:opacity-50 disabled:cursor-not-allowed transition-opacity"
          >
            {saving && <Loader2 size={12} className="animate-spin" />}
            Save changes
          </button>
        </footer>
      </div>
    </>
  );
}
