/**
 * Reusable confirmation dialog — replaces window.confirm() with a proper modal.
 *
 * Two usage patterns:
 *
 * 1. **Declarative** — render <ConfirmDialog> and control via open/onConfirm/onCancel props
 * 2. **Imperative** — call useConfirm() hook to get a `confirm(msg)` async function
 *    that returns a boolean (mirrors window.confirm API but with proper UI).
 */

import { useState, useCallback, useRef } from "react";
import { View, Text, Pressable, ActivityIndicator, Platform } from "react-native";
import { AlertTriangle, X } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

interface ConfirmDialogProps {
  open: boolean;
  title?: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "warning" | "default";
  onConfirm: () => void;
  onCancel: () => void;
  loading?: boolean;
}

export function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  variant = "default",
  onConfirm,
  onCancel,
  loading,
}: ConfirmDialogProps) {
  const t = useThemeTokens();

  if (!open || typeof document === "undefined") return null;

  const confirmBg =
    variant === "danger" ? t.danger : variant === "warning" ? "#f59e0b" : t.accent;

  // eslint-disable-next-line @typescript-eslint/no-var-requires
  const ReactDOM = require("react-dom");
  return ReactDOM.createPortal(
    <>
      {/* Backdrop */}
      <div
        onClick={loading ? undefined : onCancel}
        style={{
          position: "fixed",
          inset: 0,
          background: "rgba(0,0,0,0.45)",
          zIndex: 10020,
        }}
      />
      {/* Dialog */}
      <div
        style={{
          position: "fixed",
          top: "50%",
          left: "50%",
          transform: "translate(-50%, -50%)",
          width: 380,
          maxWidth: "90vw",
          zIndex: 10021,
          background: t.surfaceRaised,
          border: `1px solid ${t.surfaceBorder}`,
          borderRadius: 12,
          boxShadow: "0 16px 48px rgba(0,0,0,0.3)",
          padding: 20,
        }}
      >
        {/* Header */}
        <View
          style={{
            flexDirection: "row",
            justifyContent: "space-between",
            alignItems: "center",
            marginBottom: 12,
          }}
        >
          <View style={{ flexDirection: "row", alignItems: "center", gap: 8 }}>
            {variant !== "default" && (
              <AlertTriangle
                size={15}
                color={variant === "danger" ? t.danger : "#f59e0b"}
              />
            )}
            <Text style={{ fontSize: 14, fontWeight: "700", color: t.text }}>
              {title ?? "Confirm"}
            </Text>
          </View>
          {!loading && (
            <Pressable onPress={onCancel} hitSlop={8}>
              <X size={16} color={t.textDim} />
            </Pressable>
          )}
        </View>

        {/* Message */}
        <Text
          style={{
            fontSize: 13,
            color: t.textMuted,
            lineHeight: 20,
            marginBottom: 20,
          }}
        >
          {message}
        </Text>

        {/* Actions */}
        <View style={{ flexDirection: "row", justifyContent: "flex-end", gap: 8 }}>
          <Pressable
            onPress={onCancel}
            disabled={loading}
            style={{
              paddingHorizontal: 12,
              paddingVertical: 6,
              borderRadius: 6,
              borderWidth: 1,
              borderColor: t.surfaceBorder,
            }}
          >
            <Text style={{ fontSize: 12, color: t.textDim }}>{cancelLabel}</Text>
          </Pressable>
          <Pressable
            onPress={onConfirm}
            disabled={loading}
            style={{
              paddingHorizontal: 12,
              paddingVertical: 6,
              borderRadius: 6,
              backgroundColor: confirmBg,
              opacity: loading ? 0.5 : 1,
            }}
          >
            {loading ? (
              <ActivityIndicator size="small" color="#fff" />
            ) : (
              <Text style={{ fontSize: 12, fontWeight: "600", color: "#fff" }}>
                {confirmLabel}
              </Text>
            )}
          </Pressable>
        </View>
      </div>
    </>,
    document.body,
  );
}

// ---------------------------------------------------------------------------
// useConfirm — imperative hook (drop-in replacement for window.confirm)
// ---------------------------------------------------------------------------

interface ConfirmState {
  message: string;
  title?: string;
  confirmLabel?: string;
  variant?: "danger" | "warning" | "default";
}

export interface ConfirmOptions {
  title?: string;
  confirmLabel?: string;
  variant?: "danger" | "warning" | "default";
}

/**
 * Returns `{ confirm, ConfirmDialogSlot }`.
 *
 * - `confirm(message, options?)` — returns a Promise<boolean> (like window.confirm).
 * - Render `<ConfirmDialogSlot />` once in your component tree.
 */
export function useConfirm() {
  const [state, setState] = useState<ConfirmState | null>(null);
  const resolveRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback(
    (message: string, options?: ConfirmOptions): Promise<boolean> => {
      // Fallback for non-web
      if (Platform.OS !== "web" || typeof document === "undefined") {
        return Promise.resolve(window.confirm(message));
      }
      return new Promise<boolean>((resolve) => {
        resolveRef.current = resolve;
        setState({
          message,
          title: options?.title,
          confirmLabel: options?.confirmLabel,
          variant: options?.variant,
        });
      });
    },
    [],
  );

  const handleConfirm = useCallback(() => {
    resolveRef.current?.(true);
    resolveRef.current = null;
    setState(null);
  }, []);

  const handleCancel = useCallback(() => {
    resolveRef.current?.(false);
    resolveRef.current = null;
    setState(null);
  }, []);

  const ConfirmDialogSlot = useCallback(
    () => (
      <ConfirmDialog
        open={state !== null}
        message={state?.message ?? ""}
        title={state?.title}
        confirmLabel={state?.confirmLabel}
        variant={state?.variant}
        onConfirm={handleConfirm}
        onCancel={handleCancel}
      />
    ),
    [state, handleConfirm, handleCancel],
  );

  return { confirm, ConfirmDialogSlot };
}
