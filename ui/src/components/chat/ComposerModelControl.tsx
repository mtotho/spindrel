import { useCallback, useEffect, useRef, type RefObject } from "react";
import { X } from "lucide-react";
import { createPortal } from "react-dom";
import { useThemeTokens } from "../../theme/tokens";
import { LlmModelDropdownContent } from "../shared/LlmModelDropdown";

type ComposerControlPresentation = "default" | "terminal";

interface ComposerModelControlProps {
  presentation: ComposerControlPresentation;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  channelId?: string;
  isMobile: boolean;
  hideModelOverride: boolean;
  modelOverride?: string;
  modelProviderIdOverride?: string | null;
  onModelOverrideChange?: (m: string | undefined, providerId?: string | null) => void;
  defaultModel?: string;
  harnessRuntime?: string | null;
  harnessAvailableModels?: string[];
  harnessEffortValues?: string[];
  harnessCurrentModel?: string | null;
  harnessCurrentEffort?: string | null;
  harnessModelMutating?: boolean;
  onHarnessModelChange?: (model: string | null) => void;
  onHarnessEffortChange?: (effort: string | null) => void;
  terminalFontStack: string;
}

export function ComposerModelControl({
  presentation,
  open,
  onOpenChange,
  channelId,
  isMobile,
  hideModelOverride,
  modelOverride,
  modelProviderIdOverride,
  onModelOverrideChange,
  defaultModel,
  harnessRuntime,
  harnessAvailableModels,
  harnessEffortValues = [],
  harnessCurrentModel = null,
  harnessCurrentEffort = null,
  harnessModelMutating = false,
  onHarnessModelChange,
  onHarnessEffortChange,
  terminalFontStack,
}: ComposerModelControlProps) {
  const t = useThemeTokens();
  const pickerRef = useRef<HTMLDivElement>(null);
  const isTerminalMode = presentation === "terminal";
  const isHarness = !!harnessRuntime;
  const hasOverride = isHarness ? !!harnessCurrentModel : !!modelOverride;
  const effectiveName = isHarness
    ? harnessCurrentModel
    : (modelOverride
        ? modelOverride.split("/").pop()
        : defaultModel?.split("/").pop());
  const defaultVisible = isHarness ? true : !!(onModelOverrideChange && !hideModelOverride);
  const terminalVisible = isHarness || !!onModelOverrideChange;
  const visible = isTerminalMode ? terminalVisible : defaultVisible;

  useEffect(() => {
    if (!visible) return;
    const handler = (e: Event) => {
      const detail = (e as CustomEvent<{ channelId?: string }>).detail;
      if (!detail?.channelId || detail.channelId === channelId) {
        onOpenChange(true);
      }
    };
    window.addEventListener("spindrel:open-model-picker", handler);
    return () => window.removeEventListener("spindrel:open-model-picker", handler);
  }, [channelId, onOpenChange, visible]);

  const cycleHarnessEffort = useCallback(() => {
    if (!onHarnessEffortChange || harnessModelMutating) return;
    const cycle = [...harnessEffortValues, null];
    if (cycle.length === 1) return;
    const idx = harnessCurrentEffort ? harnessEffortValues.indexOf(harnessCurrentEffort) : harnessEffortValues.length;
    onHarnessEffortChange(cycle[(idx + 1) % cycle.length]);
  }, [harnessCurrentEffort, harnessEffortValues, harnessModelMutating, onHarnessEffortChange]);

  if (!visible) return null;

  if (isTerminalMode) {
    return (
      <div
        ref={pickerRef}
        style={{ minWidth: 0, display: "flex", alignItems: "center", flex: 1, gap: 12 }}
      >
        <button
          type="button"
          onClick={() => onOpenChange(true)}
          title={isHarness
            ? (hasOverride ? `Harness model: ${harnessCurrentModel}` : "Harness model: runtime default")
            : (hasOverride ? `Channel model override: ${modelOverride}` : `Model: ${defaultModel ?? effectiveName ?? "default"}`)}
          style={{
            background: "transparent",
            border: "none",
            padding: 0,
            margin: 0,
            color: hasOverride ? t.text : t.textDim,
            fontFamily: terminalFontStack,
            fontSize: 11.5,
            lineHeight: 1.2,
            cursor: "pointer",
            whiteSpace: "nowrap",
            maxWidth: "100%",
            overflow: "hidden",
            textOverflow: "ellipsis",
          }}
        >
          {effectiveName ?? (isHarness ? "default" : "select model")}
        </button>
        {isHarness && harnessEffortValues.length > 0 && (
          <button
            type="button"
            onClick={cycleHarnessEffort}
            disabled={harnessModelMutating}
            title={harnessCurrentEffort ? `Harness effort: ${harnessCurrentEffort}. Click to cycle.` : "Harness effort: default. Click to set."}
            style={{
              background: "transparent",
              border: "none",
              padding: 0,
              margin: 0,
              color: harnessCurrentEffort ? t.warningMuted : t.textDim,
              fontFamily: terminalFontStack,
              fontSize: 11.5,
              lineHeight: 1.2,
              cursor: harnessModelMutating ? "default" : "pointer",
              whiteSpace: "nowrap",
            }}
          >
            effort {harnessCurrentEffort ?? "default"}
          </button>
        )}
        {open && renderModelPickerPortal({
          t,
          pickerRef,
          isTerminalMode,
          isHarness,
          hasOverride,
          modelOverride,
          modelProviderIdOverride,
          onModelOverrideChange,
          defaultModel,
          harnessAvailableModels,
          harnessCurrentModel,
          harnessModelMutating,
          onHarnessModelChange,
          onOpenChange,
        })}
      </div>
    );
  }

  const pillLabel = effectiveName ?? (isHarness ? "default" : null);
  const canRenderPill = !!pillLabel;
  const pillTitle = isHarness
    ? (hasOverride
        ? `Harness model: ${harnessCurrentModel}`
        : "Harness model: runtime default")
    : (hasOverride
        ? `Channel model override: ${modelOverride}`
        : `Model: ${defaultModel ?? effectiveName}`);

  return (
    <div ref={pickerRef} style={{ position: "relative", display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
      {canRenderPill ? (
        <button
          type="button"
          onClick={() => onOpenChange(true)}
          title={pillTitle}
          style={{
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 4,
            background: hasOverride ? t.purpleSubtle : "transparent",
            border: `1px solid ${hasOverride ? t.purpleBorder : "transparent"}`,
            borderRadius: 8,
            padding: "4px 8px",
            fontSize: 11,
            color: hasOverride ? t.purple : t.textMuted,
            cursor: "pointer",
            whiteSpace: "nowrap",
            maxWidth: isMobile ? 120 : 200,
          }}
        >
          <span style={{ overflow: "hidden", textOverflow: "ellipsis" }}>
            {pillLabel}
          </span>
          {hasOverride && (
            <span
              onClick={(e) => {
                e.stopPropagation();
                if (isHarness) {
                  onHarnessModelChange?.(null);
                } else {
                  onModelOverrideChange?.(undefined, null);
                }
              }}
              style={{ marginLeft: 2, cursor: "pointer", fontSize: 12, lineHeight: 1 }}
            >
              <X size={12} color={hasOverride ? t.purple : t.textMuted} />
            </span>
          )}
        </button>
      ) : (
        <button
          className="input-action-btn"
          onClick={() => onOpenChange(true)}
          style={{ width: 32, height: 32, opacity: 0.6 }}
          title="Select channel model"
        >
          <span style={{ fontSize: 11, color: t.textDim }}>model</span>
        </button>
      )}
      {open && renderModelPickerPortal({
        t,
        pickerRef,
        isTerminalMode,
        isHarness,
        hasOverride,
        modelOverride,
        modelProviderIdOverride,
        onModelOverrideChange,
        defaultModel,
        harnessAvailableModels,
        harnessCurrentModel,
        harnessModelMutating,
        onHarnessModelChange,
        onOpenChange,
      })}
      {isHarness && harnessEffortValues.length > 0 && (
        <button
          type="button"
          onClick={cycleHarnessEffort}
          disabled={harnessModelMutating}
          title={harnessCurrentEffort ? `Harness effort: ${harnessCurrentEffort}. Click to cycle.` : "Harness effort: default. Click to set."}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 4,
            background: harnessCurrentEffort ? t.warningSubtle : "transparent",
            border: `1px solid ${harnessCurrentEffort ? t.warningBorder : "transparent"}`,
            borderRadius: 8,
            padding: "4px 8px",
            fontSize: 11,
            color: harnessCurrentEffort ? t.warningMuted : t.textMuted,
            cursor: harnessModelMutating ? "default" : "pointer",
            opacity: harnessModelMutating ? 0.6 : 1,
            whiteSpace: "nowrap",
          }}
        >
          effort {harnessCurrentEffort ?? "default"}
        </button>
      )}
    </div>
  );
}

function renderModelPickerPortal({
  t,
  pickerRef,
  isTerminalMode,
  isHarness,
  hasOverride,
  modelOverride,
  modelProviderIdOverride,
  onModelOverrideChange,
  defaultModel,
  harnessAvailableModels,
  harnessCurrentModel,
  harnessModelMutating,
  onHarnessModelChange,
  onOpenChange,
}: {
  t: ReturnType<typeof useThemeTokens>;
  pickerRef: RefObject<HTMLDivElement | null>;
  isTerminalMode: boolean;
  isHarness: boolean;
  hasOverride: boolean;
  modelOverride?: string;
  modelProviderIdOverride?: string | null;
  onModelOverrideChange?: (m: string | undefined, providerId?: string | null) => void;
  defaultModel?: string;
  harnessAvailableModels?: string[];
  harnessCurrentModel?: string | null;
  harnessModelMutating: boolean;
  onHarnessModelChange?: (model: string | null) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const rect = pickerRef.current?.getBoundingClientRect();
  const dropdownWidth = isTerminalMode ? Math.min(320, Math.max(220, window.innerWidth - 24)) : 320;
  const dropdownBottom = rect ? window.innerHeight - rect.top + 8 : 80;
  const position = isTerminalMode
    ? {
        left: Math.max(12, Math.min(rect?.left ?? 16, window.innerWidth - dropdownWidth - 12)),
        width: dropdownWidth,
      }
    : {
        right: rect ? window.innerWidth - rect.right : 16,
        width: dropdownWidth,
      };

  return createPortal(
    <>
      <div
        onClick={() => onOpenChange(false)}
        style={{ position: "fixed", inset: 0, zIndex: 50000 }}
      />
      <div style={{ position: "fixed", bottom: dropdownBottom, zIndex: 50001, ...position }}>
        {isHarness ? (
          <HarnessModelPickerContent
            t={t}
            models={harnessAvailableModels ?? []}
            current={harnessCurrentModel ?? null}
            disabled={harnessModelMutating}
            onSelect={(m) => {
              onHarnessModelChange?.(m);
              onOpenChange(false);
            }}
          />
        ) : (
          <>
            <LlmModelDropdownContent
              value={modelOverride ?? ""}
              selectedProviderId={modelProviderIdOverride}
              onSelect={(m, pid) => {
                onModelOverrideChange?.(m || undefined, pid);
                onOpenChange(false);
              }}
            />
            {hasOverride && (
              <button
                type="button"
                onClick={() => {
                  onModelOverrideChange?.(undefined, null);
                  onOpenChange(false);
                }}
                style={{
                  marginTop: 6,
                  width: "100%",
                  background: t.surfaceRaised,
                  border: `1px solid ${t.surfaceBorder}`,
                  borderRadius: 8,
                  padding: "8px 12px",
                  color: t.textMuted,
                  fontSize: 12,
                  cursor: "pointer",
                  textAlign: "left",
                }}
              >
                Clear override - inherit {defaultModel ?? "default"}
              </button>
            )}
          </>
        )}
      </div>
    </>,
    document.body
  );
}

/** Harness model picker - same popover shell as the LLM picker, but the
 *  list comes from the runtime adapter and selection writes to harness
 *  settings rather than channel model overrides. */
function HarnessModelPickerContent({
  t,
  models,
  current,
  disabled,
  onSelect,
}: {
  t: ReturnType<typeof useThemeTokens>;
  models: string[];
  current: string | null;
  disabled: boolean;
  onSelect: (model: string | null) => void;
}) {
  return (
    <div
      style={{
        background: t.surfaceRaised,
        border: `1px solid ${t.surfaceBorder}`,
        borderRadius: 8,
        padding: 6,
        maxHeight: 360,
        overflowY: "auto",
        boxShadow: "0 8px 24px rgba(0,0,0,0.18)",
      }}
    >
      <div
        style={{
          fontSize: 10,
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: t.textDim,
          padding: "6px 8px 4px",
        }}
      >
        Harness model
      </div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => onSelect(null)}
        style={{
          display: "block",
          width: "100%",
          textAlign: "left",
          background: current === null ? t.surfaceOverlay : "transparent",
          color: t.textMuted,
          border: "none",
          borderRadius: 6,
          padding: "8px 10px",
          fontSize: 12,
          cursor: disabled ? "default" : "pointer",
          opacity: disabled ? 0.6 : 1,
        }}
      >
        Default - runtime picks
      </button>
      {models.map((m) => {
        const selected = m === current;
        return (
          <button
            key={m}
            type="button"
            disabled={disabled}
            onClick={() => onSelect(m)}
            style={{
              display: "block",
              width: "100%",
              textAlign: "left",
              background: selected ? t.purpleSubtle : "transparent",
              color: selected ? t.purple : t.text,
              border: "none",
              borderRadius: 6,
              padding: "8px 10px",
              fontSize: 12,
              fontFamily: "'Menlo', monospace",
              cursor: disabled ? "default" : "pointer",
              opacity: disabled ? 0.6 : 1,
            }}
          >
            {m}
          </button>
        );
      })}
      {models.length === 0 && (
        <div style={{ padding: "8px 10px", fontSize: 11, color: t.textDim }}>
          No model list reported by the runtime adapter.
        </div>
      )}
    </div>
  );
}
