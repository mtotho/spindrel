import { useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { Shield, Sparkles } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

/**
 * One-line empty-state nudge for fresh Project-bound channels.
 *
 * Renders only when (a) the channel is attached to a Project and (b) the
 * conversation has zero user messages - i.e. the user is staring at an empty
 * channel with no idea what to ask for. Single line, low chrome, no CTA
 * button (the slash commands are the affordance). Dismisses automatically
 * once the user types anything.
 */
export function ProjectChannelEmptyHint({
  projectName,
  visible,
}: {
  projectName: string;
  visible: boolean;
}) {
  if (!visible) return null;
  return (
    <div className="mx-auto mt-2 mb-1 max-w-3xl px-3">
      <div className="flex items-center gap-2 rounded border border-border-subtle bg-surface-overlay/40 px-3 py-1.5 text-[12px] text-text-muted">
        <Sparkles size={12} className="shrink-0 text-accent" />
        <span className="truncate">
          <span className="text-text">{projectName}</span> is attached. Try:
          describe what to build · capture a bug · ask for status with{" "}
          <code className="rounded bg-surface-overlay px-1 py-0.5 text-[11px] text-text">/project-status</code>{" "}
          · reference a skill by name.
        </span>
      </div>
    </div>
  );
}

export function ErrorBanner({ error, onDismiss, onRetry }: { error: string; onDismiss: () => void; onRetry?: () => void }) {
  const t = useThemeTokens();

  useEffect(() => {
    const timer = setTimeout(onDismiss, onRetry ? 30000 : 8000);
    return () => clearTimeout(timer);
  }, [error, onDismiss, onRetry]);

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        gap: 8,
        padding: "8px 16px",
        backgroundColor: t.dangerSubtle,
        borderTop: `1px solid ${t.dangerBorder}`,
      }}
    >
      <span style={{ color: t.danger, fontSize: 13, flex: 1 }}>{error}</span>
      {onRetry && (
        <button
          className="banner-btn"
          onClick={onRetry}
          style={{
            padding: "8px 16px",
            backgroundColor: t.danger,
            borderRadius: 4,
            border: "none",
            color: "#fff",
            fontSize: 12,
            fontWeight: 600,
            cursor: "pointer",
          }}
        >
          Retry
        </button>
      )}
      <button
        className="banner-btn"
        onClick={onDismiss}
        style={{
          padding: "8px 12px",
          background: "none",
          border: "none",
          color: t.dangerMuted,
          fontSize: 12,
          cursor: "pointer",
          borderRadius: 4,
        }}
      >
        Dismiss
      </button>
    </div>
  );
}

export function SecretWarningBanner({ patterns, onDismiss }: { patterns: { type: string }[]; onDismiss: () => void }) {
  const navigate = useNavigate();
  const t = useThemeTokens();

  useEffect(() => {
    const timer = setTimeout(onDismiss, 15000);
    return () => clearTimeout(timer);
  }, [onDismiss]);

  const types = patterns.map((p) => p.type).join(", ");

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "row",
        alignItems: "center",
        justifyContent: "space-between",
        gap: 8,
        padding: "8px 16px",
        backgroundColor: "rgba(234, 179, 8, 0.1)",
        borderTop: "1px solid rgba(234, 179, 8, 0.2)",
      }}
    >
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 13, fontWeight: 600, color: "#facc15", display: "flex", flexDirection: "row", alignItems: "center", gap: 4 }}>
          <Shield size={12} />
          <span>Secret detected: {types}</span>
        </div>
        <div style={{ fontSize: 12, color: "rgba(250, 204, 21, 0.7)", marginTop: 2 }}>
          Consider using{" "}
          <a
            href="/admin/secret-values"
            onClick={(e) => { e.preventDefault(); navigate("/admin/secret-values"); }}
            style={{ color: "inherit", textDecoration: "underline", cursor: "pointer" }}
          >
            Secrets Manager
          </a>{" "}
          instead of pasting credentials in chat.
        </div>
      </div>
      <button
        className="banner-btn"
        onClick={onDismiss}
        style={{
          padding: "8px 12px",
          background: "none",
          border: "none",
          color: "rgba(250, 204, 21, 0.6)",
          fontSize: 12,
          cursor: "pointer",
          borderRadius: 4,
        }}
      >
        Dismiss
      </button>
    </div>
  );
}
