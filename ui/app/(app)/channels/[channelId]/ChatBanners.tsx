import { useEffect } from "react";
import { useRouter } from "expo-router";
import { Shield } from "lucide-react";
import { useThemeTokens } from "@/src/theme/tokens";

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
  const router = useRouter();
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
        <div style={{ fontSize: 13, fontWeight: 600, color: "#facc15", display: "flex", alignItems: "center", gap: 4 }}>
          <Shield size={12} />
          <span>Secret detected: {types}</span>
        </div>
        <div style={{ fontSize: 12, color: "rgba(250, 204, 21, 0.7)", marginTop: 2 }}>
          Consider using{" "}
          <a
            href="/admin/secret-values"
            onClick={(e) => { e.preventDefault(); router.push("/admin/secret-values" as any); }}
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
