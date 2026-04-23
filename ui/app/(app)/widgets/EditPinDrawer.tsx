/**
 * EditPinDrawer — per-pin display_label + widget_config editor.
 *
 * Opens as a right-side drawer from the dashboard page when the user clicks
 * the pencil icon on a pin (only visible in Edit layout mode). When a pin
 * ships a config_schema we render a simple form first and keep the raw JSON
 * editor as an escape hatch. Save replaces the config outright (merge:false)
 * and action-dispatched button flips stay on merge:true semantics.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Maximize2, Minimize2, Trash2, X } from "lucide-react";
import { apiFetch } from "@/src/api/client";
import { useDashboardPinsStore } from "@/src/stores/dashboardPins";
import { useBots } from "@/src/api/hooks/useBots";
import type { GridLayoutItem, WidgetConfigSchemaField } from "@/src/types/api";
import type { GridPreset } from "@/src/lib/dashboardGrid";
import {
  PinScopePicker,
  pinScopeFromBotId,
  pinScopeToBotId,
  type PinScope,
} from "./PinScopePicker";
import { WidgetContractCard } from "./WidgetContractCard";

const HTML_INTERACTIVE_CT = "application/vnd.spindrel.html+interactive";

interface Props {
  pinId: string | null;
  onClose: () => void;
  /** Active dashboard grid preset — drives size-preset chip values +
   *  full-width column count. Absent when opened from a context that has
   *  no dashboard (shouldn't happen in practice, but the size row is
   *  hidden when missing to stay safe). */
  preset?: GridPreset;
}

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function isRenderableSchemaField(field: WidgetConfigSchemaField): boolean {
  if (Array.isArray(field.enum) && field.enum.every((item) => ["string", "number", "boolean"].includes(typeof item))) {
    return true;
  }
  return field.type === "string"
    || field.type === "boolean"
    || field.type === "integer"
    || field.type === "number";
}

export function EditPinDrawer({ pinId, onClose, preset }: Props) {
  const pin = useDashboardPinsStore((s) =>
    pinId ? s.pins.find((p) => p.id === pinId) ?? null : null,
  );
  const renamePin = useDashboardPinsStore((s) => s.renamePin);
  const replaceConfig = useDashboardPinsStore((s) => s.replaceWidgetConfig);
  const promotePanel = useDashboardPinsStore((s) => s.promotePinToPanel);
  const demotePanel = useDashboardPinsStore((s) => s.demotePinFromPanel);
  const applyLayout = useDashboardPinsStore((s) => s.applyLayout);
  const setPinScope = useDashboardPinsStore((s) => s.setPinScope);
  const { data: allBots } = useBots();

  const [label, setLabel] = useState("");
  const [jsonText, setJsonText] = useState("{}");
  const [scope, setScope] = useState<PinScope>({ kind: "user" });
  const unpinWidget = useDashboardPinsStore((s) => s.unpinWidget);

  const [saving, setSaving] = useState(false);
  const [panelBusy, setPanelBusy] = useState(false);
  const [sizeBusy, setSizeBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedFlash, setSavedFlash] = useState(false);
  // Delete / unpin state
  const [deleteChecking, setDeleteChecking] = useState(false);
  const [deleteConfirmNeeded, setDeleteConfirmNeeded] = useState(false);
  const [deleteDeleting, setDeleteDeleting] = useState(false);

  useEffect(() => {
    if (!pin) return;
    setLabel(pin.display_label ?? "");
    setJsonText(prettyJson(pin.widget_config ?? {}));
    setScope(pinScopeFromBotId(pin.source_bot_id ?? null));
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
  const isHeaderZone = pin?.zone === "header";

  const currentLayout = (pin?.grid_layout as GridLayoutItem | undefined) ?? null;
  /** Match the current pin's {w,h} against a preset. Used to highlight the
   *  active chip. Falls back to null when the pin has a custom size. */
  const activeSizeId = useMemo(() => {
    if (!currentLayout || !preset) return null;
    const hit = preset.sizePresets.find(
      (p) => p.w === currentLayout.w && p.h === currentLayout.h,
    );
    return hit?.id ?? null;
  }, [currentLayout, preset]);

  const currentLabel = pin?.display_label ?? "";
  const currentConfig = prettyJson(pin?.widget_config ?? {});
  const currentScopeBotId = pin?.source_bot_id ?? null;
  const nextScopeBotId = pinScopeToBotId(scope);
  const scopeDirty = nextScopeBotId !== currentScopeBotId;
  const dirty =
    (label.trim() || null) !== (currentLabel.trim() || null) ||
    jsonText !== currentConfig ||
    scopeDirty;

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
      if (scopeDirty) {
        ops.push(setPinScope(pin.id, nextScopeBotId));
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

  const setConfigFieldValue = (fieldId: string, value: unknown) => {
    if (!parsedConfig) return;
    const nextConfig: Record<string, unknown> = { ...parsedConfig };
    if (value === undefined) delete nextConfig[fieldId];
    else nextConfig[fieldId] = value;
    setJsonText(prettyJson(nextConfig));
  };

  // Title-visibility override — read/write `show_title` on the parsed config.
  // Disabled when the JSON is unparseable so we don't stomp the user's edit.
  const currentTitleOverride: "inherit" | "show" | "hide" = (() => {
    const raw = parsedConfig?.show_title;
    if (raw === "show" || raw === "hide") return raw;
    return "inherit";
  })();
  const setTitleOverride = (next: "inherit" | "show" | "hide") => {
    if (!parsedConfig) return;
    const nextConfig: Record<string, unknown> = { ...parsedConfig };
    if (next === "inherit") delete nextConfig.show_title;
    else nextConfig.show_title = next;
    setJsonText(prettyJson(nextConfig));
  };
  const currentWrapperSurface: "inherit" | "surface" | "plain" = (() => {
    const raw = parsedConfig?.wrapper_surface;
    if (raw === "surface" || raw === "plain") return raw;
    return "inherit";
  })();
  const setWrapperSurface = (next: "inherit" | "surface" | "plain") => {
    if (!parsedConfig) return;
    const nextConfig: Record<string, unknown> = { ...parsedConfig };
    if (next === "inherit") delete nextConfig.wrapper_surface;
    else nextConfig.wrapper_surface = next;
    setJsonText(prettyJson(nextConfig));
  };

  const isHtmlWidget = pin?.envelope?.content_type === HTML_INTERACTIVE_CT;
  const isPanelPin = !!pin?.is_main_panel;
  const configSchemaProperties = useMemo(
    () => pin?.config_schema?.properties ?? {},
    [pin?.config_schema],
  );
  const requiredConfigFields = useMemo(
    () => new Set(pin?.config_schema?.required ?? []),
    [pin?.config_schema],
  );
  const schemaFields = useMemo(
    () => Object.entries(configSchemaProperties).filter(([, field]) => isRenderableSchemaField(field)),
    [configSchemaProperties],
  );
  const unsupportedSchemaFieldCount = useMemo(
    () => Object.keys(configSchemaProperties).length - schemaFields.length,
    [configSchemaProperties, schemaFields.length],
  );

  if (!isOpen) return null;

  const isFullWidth =
    !!currentLayout
    && !!preset
    && currentLayout.x === 0
    && currentLayout.w === preset.cols.lg;

  const applyTileSize = async (w: number, h: number, resetX: boolean) => {
    if (!pin || !currentLayout) return;
    setSizeBusy(true);
    setError(null);
    try {
      await applyLayout([
        {
          id: pin.id,
          x: resetX ? 0 : currentLayout.x,
          y: currentLayout.y,
          w,
          h,
        },
      ]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSizeBusy(false);
    }
  };

  const handleSizeChip = (w: number, h: number) => {
    // Full-width sizes (w === cols.lg) need x snapped to 0 so the tile can
    // actually fit without overflow. Smaller sizes preserve x/y — picking
    // "M" on a right-side tile shouldn't yank it to the left gutter.
    const resetX = !!preset && w === preset.cols.lg;
    void applyTileSize(w, h, resetX);
  };

  const handleFullWidthToggle = () => {
    if (!preset || !currentLayout) return;
    if (isFullWidth) {
      // Toggle off → fall back to the M preset at the current (x,y).
      const m = preset.sizePresets.find((p) => p.id === "M") ?? preset.sizePresets[0];
      void applyTileSize(m.w, m.h, false);
    } else {
      void applyTileSize(preset.cols.lg, currentLayout.h, true);
    }
  };

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

  const handleDeleteClick = async () => {
    if (!pin) return;
    if (deleteConfirmNeeded) {
      // Second click — confirmed, also wipe bundle data.
      setDeleteDeleting(true);
      setError(null);
      try {
        await apiFetch(
          `/api/v1/widgets/dashboard/pins/${pin.id}?delete_bundle_data=true`,
          { method: "DELETE" },
        );
        await unpinWidget(pin.id);
        onClose();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
        setDeleteDeleting(false);
      }
      return;
    }
    // First click — check if the bundle has DB data.
    setDeleteChecking(true);
    setError(null);
    try {
      const resp = await apiFetch(`/api/v1/widgets/dashboard/pins/${pin.id}/db-status`);
      const data = await (resp as Response).json();
      if (data?.has_content) {
        setDeleteConfirmNeeded(true);
        setDeleteChecking(false);
        return;
      }
    } catch {
      // Ignore status-check failure — proceed with plain delete.
    }
    // No DB data (or check failed) — delete immediately.
    setDeleteChecking(false);
    setDeleteDeleting(true);
    try {
      await apiFetch(`/api/v1/widgets/dashboard/pins/${pin.id}`, { method: "DELETE" });
      await unpinWidget(pin.id);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setDeleteDeleting(false);
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
              className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/40"
            />
            <span className="text-[11px] text-text-dim">
              Leave empty to fall back to the widget's own label.
            </span>
          </label>

          {isHtmlWidget && (
            <div className="flex flex-col gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                  Runs as
                </span>
                <span className="text-[10px] text-text-dim">
                  {scope.kind === "bot" ? "bot scope" : "user scope"}
                </span>
              </div>
              <PinScopePicker
                scope={scope}
                onChange={setScope}
                bots={allBots ?? null}
                bare
              />
              <p className="text-[11px] text-text-muted leading-snug">
                Changes who the widget authenticates as. Pin's saved data
                stays put; only the iframe's API credentials change.
              </p>
            </div>
          )}

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

          {preset && currentLayout && (
            <div className="flex flex-col gap-2 rounded-md border border-surface-border bg-surface px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                  Size
                </span>
                <span className="text-[10px] font-mono text-text-dim tabular-nums">
                  {currentLayout.w}×{currentLayout.h}
                </span>
              </div>
              <div className="flex flex-wrap gap-1.5">
                {preset.sizePresets.map((sp) => {
                  const active = activeSizeId === sp.id;
                  return (
                    <button
                      key={sp.id}
                      type="button"
                      onClick={() => handleSizeChip(sp.w, sp.h)}
                      disabled={sizeBusy}
                      className={
                        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium transition-colors "
                        + (active
                          ? "border-accent/60 bg-accent/10 text-accent"
                          : "border-surface-border text-text-muted hover:bg-surface-overlay")
                        + " disabled:opacity-50 disabled:cursor-not-allowed"
                      }
                      title={`${sp.label} — ${sp.w}×${sp.h}`}
                    >
                      {sp.label}
                      <span className="font-mono text-[10px] text-text-dim">
                        {sp.w}×{sp.h}
                      </span>
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                onClick={handleFullWidthToggle}
                disabled={sizeBusy}
                className={
                  "inline-flex w-fit items-center gap-1.5 rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors "
                  + (isFullWidth
                    ? "border-accent/60 bg-accent/10 text-accent"
                    : "border-surface-border text-text-muted hover:bg-surface-overlay")
                  + " disabled:opacity-50 disabled:cursor-not-allowed"
                }
                aria-pressed={isFullWidth}
              >
                {sizeBusy && <Loader2 size={11} className="animate-spin" />}
                <Maximize2 size={11} />
                {isFullWidth ? "Full width · on" : "Make full width"}
              </button>
            </div>
          )}

          {pin && (
            <WidgetContractCard
              contract={pin.widget_contract}
              title="Pin contract"
            />
          )}

          {pin?.config_schema && schemaFields.length > 0 && (
            <div className="flex flex-col gap-2 rounded-md border border-surface-border bg-surface px-3 py-2.5">
              <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                  Config fields
                </span>
                <span className="text-[10px] text-text-dim">
                  {schemaFields.length} field{schemaFields.length === 1 ? "" : "s"}
                </span>
              </div>
              {schemaFields.map(([fieldId, field]) => {
                const required = requiredConfigFields.has(fieldId);
                const title = field.title ?? fieldId;
                const description = field.description ?? null;
                const rawValue = parsedConfig?.[fieldId];
                const enumValues = Array.isArray(field.enum)
                  ? field.enum.filter((item) => ["string", "number", "boolean"].includes(typeof item))
                  : [];
                return (
                  <label key={fieldId} className="flex flex-col gap-1">
                    <span className="text-[11px] font-medium text-text">
                      {title}
                      {required ? <span className="ml-1 text-danger">*</span> : null}
                    </span>
                    {enumValues.length > 0 ? (
                      <select
                        value={rawValue === undefined ? "" : String(rawValue)}
                        onChange={(e) => {
                          const nextRaw = e.target.value;
                          const matched = enumValues.find((item) => String(item) === nextRaw);
                          setConfigFieldValue(fieldId, matched);
                        }}
                        className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/40"
                      >
                        {!required && <option value="">Unset</option>}
                        {enumValues.map((item) => (
                          <option key={String(item)} value={String(item)}>
                            {String(item)}
                          </option>
                        ))}
                      </select>
                    ) : field.type === "boolean" ? (
                      <select
                        value={rawValue === undefined ? "" : rawValue ? "true" : "false"}
                        onChange={(e) => {
                          if (e.target.value === "") setConfigFieldValue(fieldId, undefined);
                          else setConfigFieldValue(fieldId, e.target.value === "true");
                        }}
                        className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/40"
                      >
                        {!required && <option value="">Unset</option>}
                        <option value="true">True</option>
                        <option value="false">False</option>
                      </select>
                    ) : (
                      <input
                        value={rawValue === undefined ? "" : String(rawValue)}
                        type={field.type === "integer" || field.type === "number" ? "number" : "text"}
                        step={field.type === "integer" ? "1" : "any"}
                        onChange={(e) => {
                          const nextRaw = e.target.value;
                          if (nextRaw === "") {
                            setConfigFieldValue(fieldId, undefined);
                            return;
                          }
                          if (field.type === "integer") {
                            setConfigFieldValue(fieldId, Number.parseInt(nextRaw, 10));
                            return;
                          }
                          if (field.type === "number") {
                            setConfigFieldValue(fieldId, Number.parseFloat(nextRaw));
                            return;
                          }
                          setConfigFieldValue(fieldId, nextRaw);
                        }}
                        className="rounded-md border border-surface-border bg-input px-2.5 py-1.5 text-[13px] text-text outline-none focus:border-accent/40"
                      />
                    )}
                    {description && (
                      <span className="text-[11px] text-text-dim">
                        {description}
                      </span>
                    )}
                  </label>
                );
              })}
              {unsupportedSchemaFieldCount > 0 && (
                <p className="text-[11px] text-text-dim">
                  {unsupportedSchemaFieldCount} schema field{unsupportedSchemaFieldCount === 1 ? "" : "s"} still require raw JSON editing below.
                </p>
              )}
            </div>
          )}

          {isHeaderZone ? (
            <div className="rounded-md border border-surface-border bg-surface px-3 py-2.5">
              <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                Header zone host chrome
              </span>
              <p className="mt-1 text-[11px] leading-snug text-text-muted">
                Header-zone pins are always titleless at the host level. Wrapper shell treatment is controlled by the channel&apos;s <strong>Header strip shell</strong> setting, not per-pin overrides.
              </p>
            </div>
          ) : (
            <>
              <div className="flex flex-col gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-2.5">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                  Title bar
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {(["inherit", "show", "hide"] as const).map((opt) => {
                    const active = currentTitleOverride === opt;
                    return (
                      <button
                        key={opt}
                        type="button"
                        disabled={jsonError}
                        onClick={() => setTitleOverride(opt)}
                        className={
                          "inline-flex items-center rounded-md border px-2.5 py-1 text-[11px] font-medium capitalize transition-colors "
                          + (active
                            ? "border-accent/60 bg-accent/10 text-accent"
                            : "border-surface-border text-text-muted hover:bg-surface-overlay")
                          + " disabled:opacity-50 disabled:cursor-not-allowed"
                        }
                        aria-pressed={active}
                      >
                        {opt === "inherit" ? "Inherit dashboard" : opt}
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] text-text-muted leading-snug">
                  Override the dashboard&apos;s &quot;Hide widget titles&quot; setting for this one pin.
                </p>
              </div>

              <div className="flex flex-col gap-1.5 rounded-md border border-surface-border bg-surface px-3 py-2.5">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-text-dim">
                  Appearance
                </span>
                <div className="flex flex-wrap gap-1.5">
                  {([
                    ["inherit", "Inherit"],
                    ["surface", "Surface"],
                    ["plain", "Plain"],
                  ] as const).map(([opt, label]) => {
                    const active = currentWrapperSurface === opt;
                    return (
                      <button
                        key={opt}
                        type="button"
                        disabled={jsonError}
                        onClick={() => setWrapperSurface(opt)}
                        className={
                          "inline-flex items-center rounded-md border px-2.5 py-1 text-[11px] font-medium transition-colors "
                          + (active
                            ? "border-accent/60 bg-accent/10 text-accent"
                            : "border-surface-border text-text-muted hover:bg-surface-overlay")
                          + " disabled:opacity-50 disabled:cursor-not-allowed"
                        }
                        aria-pressed={active}
                      >
                        {label}
                      </button>
                    );
                  })}
                </div>
                <p className="text-[11px] text-text-muted leading-snug">
                  Control whether the host wrapper draws the outer widget surface. Plain leaves the wrapper transparent so the widget can provide its own interior treatment.
                </p>
              </div>
            </>
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
                "h-64 resize-none rounded-md border bg-input px-2.5 py-2 font-mono text-[12px] leading-relaxed text-text outline-none focus:border-accent/40 " +
                (jsonError ? "border-danger/60" : "border-surface-border")
              }
            />
            {jsonError ? (
              <span className="text-[11px] text-danger">
                Invalid JSON — config must be a JSON object.
              </span>
            ) : (
              <span className="text-[11px] text-text-dim">
                {pin?.config_schema
                  ? "Schema-aware controls update this JSON live. Save replaces the entire config object."
                  : "Save replaces the entire config object."}
              </span>
            )}
          </div>

          {error && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
              {error}
            </div>
          )}
        </div>

        <footer className="flex flex-col gap-2 border-t border-surface-border px-4 py-3">
          {deleteConfirmNeeded && (
            <div className="rounded-md border border-danger/40 bg-danger/10 px-3 py-2 text-[12px] text-danger">
              This widget has saved data. Click <strong>Unpin & delete data</strong> to permanently remove the widget and its SQLite database.
            </div>
          )}
          <div className="flex items-center justify-end gap-2">
            {savedFlash && (
              <span className="mr-auto text-[12px] text-success">
                Saved.
              </span>
            )}
            <button
              type="button"
              onClick={() => void handleDeleteClick()}
              disabled={deleteChecking || deleteDeleting}
              className={
                "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-[12px] font-medium transition-colors mr-auto " +
                (deleteConfirmNeeded
                  ? "border-danger/60 bg-danger/10 text-danger hover:bg-danger/20"
                  : "border-surface-border text-text-muted hover:bg-surface-overlay") +
                " disabled:opacity-50 disabled:cursor-not-allowed"
              }
              title={deleteConfirmNeeded ? "Confirm: unpin and delete saved data" : "Unpin this widget"}
            >
              {(deleteChecking || deleteDeleting) && <Loader2 size={12} className="animate-spin" />}
              {!(deleteChecking || deleteDeleting) && <Trash2 size={12} />}
              {deleteConfirmNeeded ? "Unpin & delete data" : "Unpin"}
            </button>
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
          </div>
        </footer>
      </div>
    </>
  );
}
