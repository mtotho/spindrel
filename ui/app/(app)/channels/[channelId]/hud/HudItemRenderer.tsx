import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { useThemeTokens, type ThemeTokens } from "@/src/theme/tokens";
import { apiFetch } from "@/src/api/client";
import { resolveHudIcon, variantColor, variantBg } from "./hudIcons";
import { ConfirmDialog } from "@/src/components/shared/ConfirmDialog";
import type { HudItem, HudOnClick } from "@/src/types/api";
import { useState, useCallback } from "react";

function useOnClickHandler(onClick: HudOnClick | undefined, hudQueryKey?: string[]) {
  const navigate = useNavigate();
  const qc = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingConfirm, setPendingConfirm] = useState<string | null>(null);

  const executeAction = useCallback(async () => {
    if (!onClick || onClick.type !== "action" || !onClick.endpoint) return;
    setBusy(true);
    try {
      await apiFetch(onClick.endpoint, {
        method: onClick.method || "POST",
        ...(onClick.body ? { body: JSON.stringify(onClick.body) } : {}),
      });
      if (hudQueryKey) {
        await qc.invalidateQueries({ queryKey: hudQueryKey });
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Action failed";
      setError(msg);
      console.error("HUD action failed:", err);
    } finally {
      setBusy(false);
    }
  }, [onClick, hudQueryKey, qc]);

  if (!onClick) return { handler: undefined, busy, error, pendingConfirm, setPendingConfirm, executeAction };

  const handler = async () => {
    setError(null);
    if (onClick.type === "link" && onClick.href) {
      navigate(onClick.href);
    } else if (onClick.type === "action" && onClick.endpoint) {
      if (onClick.confirm) {
        setPendingConfirm(onClick.confirm);
        return;
      }
      await executeAction();
    } else if (onClick.type === "refresh") {
      if (hudQueryKey) {
        qc.invalidateQueries({ queryKey: hudQueryKey });
      }
    }
  };

  return { handler, busy, error, pendingConfirm, setPendingConfirm, executeAction };
}

export function HudBadge({ item, hudQueryKey }: { item: HudItem; hudQueryKey?: string[] }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  const bg = variantBg(item.variant, t);
  const Icon = resolveHudIcon(item.icon);
  const { handler } = useOnClickHandler(item.on_click, hudQueryKey);

  const content = (
    <div style={{
      display: "flex",
      flexDirection: "row",
      alignItems: "center",
      gap: 4,
      padding: "2px 8px",
      borderRadius: 10,
      backgroundColor: bg,
    }}>
      <Icon size={11} color={color} />
      {item.label && (
        <span style={{ fontSize: 11, color: t.textDim, fontWeight: "500" }}>
          {item.label}
        </span>
      )}
      {item.value && (
        <span style={{ fontSize: 11, color, fontWeight: "600", fontVariantNumeric: "tabular-nums" }}>
          {item.value}
        </span>
      )}
    </div>
  );

  if (handler) {
    return <button type="button" onClick={handler}>{content}</button>;
  }
  return content;
}

export function HudAction({ item, hudQueryKey }: { item: HudItem; hudQueryKey?: string[] }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  const bg = variantBg(item.variant, t);
  const Icon = resolveHudIcon(item.icon);
  const { handler, busy, error, pendingConfirm, setPendingConfirm, executeAction } =
    useOnClickHandler(item.on_click, hudQueryKey);

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
      <button type="button"
        onClick={handler}
        disabled={busy}
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "center",
          gap: 4,
          padding: "2px 8px",
          borderRadius: 10,
          backgroundColor: bg,
          border: `1px solid ${color}33`,
          opacity: busy ? 0.5 : 1,
          cursor: busy ? "wait" : "pointer",
        }}
      >
        <Icon size={11} color={color} />
        <span style={{ fontSize: 11, color, fontWeight: "600" }}>
          {busy ? "Working..." : item.label}
        </span>
      </button>
      {error && (
        <span style={{ fontSize: 10, color: t.danger }}>Failed</span>
      )}
      <ConfirmDialog
        open={pendingConfirm !== null}
        title="Confirm Action"
        message={pendingConfirm ?? ""}
        confirmLabel="Continue"
        variant="warning"
        onConfirm={() => {
          setPendingConfirm(null);
          executeAction();
        }}
        onCancel={() => setPendingConfirm(null)}
      />
    </div>
  );
}

export function HudDivider({ vertical }: { vertical?: boolean }) {
  const t = useThemeTokens();
  if (vertical) {
    return (
      <div style={{
        height: 1,
        backgroundColor: t.surfaceBorder,
        margin: "4px 0",
      }} />
    );
  }
  return (
    <div style={{
      width: 1,
      height: 14,
      backgroundColor: t.surfaceBorder,
      margin: "0 2px",
    }} />
  );
}

export function HudText({ item }: { item: HudItem }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  return (
    <span style={{ fontSize: 11, color }}>
      {item.value}
    </span>
  );
}

export function HudProgress({ item }: { item: HudItem }) {
  const t = useThemeTokens();
  const color = variantColor(item.variant, t);
  const current = Number(item.value) || 0;
  const max = Number(item.max) || 100;
  const pct = Math.min(100, Math.max(0, (current / max) * 100));

  return (
    <div style={{ display: "flex", flexDirection: "row", alignItems: "center", gap: 6 }}>
      {item.label && (
        <span style={{ fontSize: 11, color: t.textDim, fontWeight: "500" }}>
          {item.label}
        </span>
      )}
      <div style={{
        width: 60,
        height: 4,
        borderRadius: 2,
        backgroundColor: t.surfaceOverlay,
        overflow: "hidden",
      }}>
        <div style={{
          width: `${pct}%`,
          height: "100%",
          backgroundColor: color,
          borderRadius: 2,
        }} />
      </div>
      <span style={{ fontSize: 10, color: t.textDim, fontVariantNumeric: "tabular-nums" }}>
        {current}/{max}
      </span>
    </div>
  );
}

export function HudGroup({ item, hudQueryKey }: { item: HudItem; hudQueryKey?: string[] }) {
  const t = useThemeTokens();
  return (
    <div style={{ gap: 4 }}>
      {item.label && (
        <span style={{ fontSize: 11, fontWeight: "600", color: t.text, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {item.label}
        </span>
      )}
      {item.items && item.items.length > 0 && (
        <div style={{ display: "flex", flexDirection: "row", flexWrap: "wrap", gap: 4 }}>
          {item.items.map((child, i) => (
            <HudItemRenderer key={i} item={child} hudQueryKey={hudQueryKey} />
          ))}
        </div>
      )}
    </div>
  );
}

export function HudItemRenderer({ item, hudQueryKey, vertical }: { item: HudItem; hudQueryKey?: string[]; vertical?: boolean }) {
  switch (item.type) {
    case "badge":
      return <HudBadge item={item} hudQueryKey={hudQueryKey} />;
    case "action":
      return <HudAction item={item} hudQueryKey={hudQueryKey} />;
    case "divider":
      return <HudDivider vertical={vertical} />;
    case "text":
      return <HudText item={item} />;
    case "progress":
      return <HudProgress item={item} />;
    case "group":
      return <HudGroup item={item} hudQueryKey={hudQueryKey} />;
    default:
      return null;
  }
}
