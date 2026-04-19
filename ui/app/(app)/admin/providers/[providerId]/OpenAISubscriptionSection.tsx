import { useState, useEffect, useRef } from "react";
import { useThemeTokens } from "@/src/theme/tokens";
import { Section, FormRow } from "@/src/components/shared/FormControls";
import {
  useOpenAIOAuthStatus,
  useStartOpenAIOAuth,
  usePollOpenAIOAuth,
  useDisconnectOpenAIOAuth,
  type OpenAIOAuthStart,
} from "@/src/api/hooks/useProviders";
import { useConfirm } from "@/src/components/shared/ConfirmDialog";
import { ExternalLink, Check, X, Copy, AlertTriangle } from "lucide-react";

interface Props {
  /** Undefined when the provider hasn't been created yet (new-provider form). */
  providerId?: string;
}

type Phase =
  | { kind: "idle" }
  | { kind: "starting" }
  | { kind: "awaiting"; start: OpenAIOAuthStart; copied: boolean }
  | { kind: "error"; message: string };

/**
 * Connect-ChatGPT panel shown on openai-subscription provider pages.
 *
 * Two states:
 *   • Connected — shows email, plan, expiry; Disconnect button.
 *   • Not connected — Connect button opens the device-code flow inline:
 *     fetch /start, show the user_code + verification URL, then poll
 *     /poll on the interval returned by /start until success or error.
 */
export function OpenAISubscriptionSection({ providerId }: Props) {
  const t = useThemeTokens();
  const isNew = !providerId;
  const { data: status } = useOpenAIOAuthStatus(providerId);
  const startMut = useStartOpenAIOAuth();
  const pollMut = usePollOpenAIOAuth();
  const disconnectMut = useDisconnectOpenAIOAuth();
  const { confirm, ConfirmDialogSlot } = useConfirm();

  const [phase, setPhase] = useState<Phase>({ kind: "idle" });
  const pollTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (pollTimer.current) clearTimeout(pollTimer.current);
    };
  }, []);

  const pollLoop = (interval: number) => {
    if (!providerId) return;
    const attempt = async () => {
      try {
        const r = await pollMut.mutateAsync(providerId);
        if (r.status === "success") {
          setPhase({ kind: "idle" });
          return;
        }
        pollTimer.current = setTimeout(attempt, Math.max(1, interval) * 1000);
      } catch (e: any) {
        setPhase({
          kind: "error",
          message: e?.message || "Poll failed. Try again.",
        });
      }
    };
    pollTimer.current = setTimeout(attempt, Math.max(1, interval) * 1000);
  };

  const handleConnect = async () => {
    if (!providerId) return;
    setPhase({ kind: "starting" });
    try {
      const start = await startMut.mutateAsync(providerId);
      setPhase({ kind: "awaiting", start, copied: false });
      pollLoop(start.interval);
    } catch (e: any) {
      setPhase({
        kind: "error",
        message: e?.message || "Failed to start OAuth flow",
      });
    }
  };

  const handleCancelFlow = () => {
    if (pollTimer.current) {
      clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
    setPhase({ kind: "idle" });
  };

  const handleDisconnect = async () => {
    if (!providerId) return;
    const ok = await confirm(
      "Disconnect ChatGPT account? Bots using this provider will stop working until you reconnect.",
      { title: "Disconnect ChatGPT", confirmLabel: "Disconnect", variant: "danger" }
    );
    if (!ok) return;
    await disconnectMut.mutateAsync(providerId);
  };

  const copyCode = (code: string) => {
    navigator.clipboard?.writeText(code).then(() => {
      if (phase.kind === "awaiting") {
        setPhase({ ...phase, copied: true });
        setTimeout(() => {
          setPhase((p) =>
            p.kind === "awaiting" ? { ...p, copied: false } : p
          );
        }, 2000);
      }
    });
  };

  const connected = !!status?.connected;

  return (
    <Section
      title="ChatGPT Account"
      description="Sign in with your ChatGPT plan to use gpt-5 / gpt-5-codex models against your subscription."
    >
      {/* Gray-area disclaimer */}
      <div
        style={{
          display: "flex",
          flexDirection: "row",
          alignItems: "flex-start",
          gap: 8,
          padding: "8px 10px",
          marginBottom: 10,
          borderRadius: 6,
          background: t.warningSubtle,
          color: t.warning,
          fontSize: 11,
          lineHeight: 1.4,
        }}
      >
        <AlertTriangle size={14} style={{ flexShrink: 0, marginTop: 1 }} />
        <span>
          Uses OpenAI&apos;s Codex device-code OAuth flow. Intended for personal
          self-hosted use — OpenAI recommends API keys for programmatic access.
          ChatGPT plan rate limits apply; tokens grant Responses-API access only.
        </span>
      </div>

      {isNew && (
        <div
          style={{
            padding: "10px 12px",
            borderRadius: 6,
            background: t.surfaceRaised,
            color: t.textMuted,
            fontSize: 12,
            lineHeight: 1.5,
          }}
        >
          Enter a Provider ID + Display Name above and hit <strong>Save</strong>.
          The <em>Connect ChatGPT Account</em> button will appear here once the
          provider exists — the OAuth flow needs a provider row to bind tokens to.
        </div>
      )}

      {!isNew && connected && (
        <FormRow label="Signed in as">
          <div
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 10,
            }}
          >
            <Check size={14} style={{ color: t.success }} />
            <span style={{ color: t.text, fontSize: 13, fontWeight: 600 }}>
              {status?.email || "(unknown email)"}
            </span>
            {status?.plan && (
              <span
                style={{
                  padding: "2px 7px",
                  borderRadius: 4,
                  background: t.surfaceRaised,
                  color: t.textMuted,
                  fontSize: 10,
                  fontWeight: 600,
                  textTransform: "uppercase",
                  letterSpacing: "0.5px",
                }}
              >
                {status.plan}
              </span>
            )}
            {status?.expires_at && (
              <span style={{ color: t.textDim, fontSize: 11 }}>
                Token expires {new Date(status.expires_at).toLocaleString()}
              </span>
            )}
            <button
              onClick={handleDisconnect}
              disabled={disconnectMut.isPending}
              style={{
                marginLeft: "auto",
                padding: "5px 12px",
                fontSize: 12,
                fontWeight: 600,
                border: `1px solid ${t.dangerBorder}`,
                borderRadius: 5,
                background: "transparent",
                color: t.danger,
                cursor: "pointer",
              }}
            >
              {disconnectMut.isPending ? "Disconnecting..." : "Disconnect"}
            </button>
          </div>
        </FormRow>
      )}

      {!isNew && !connected && phase.kind === "idle" && (
        <button
          onClick={handleConnect}
          disabled={startMut.isPending}
          style={{
            padding: "8px 18px",
            fontSize: 13,
            fontWeight: 600,
            border: "none",
            borderRadius: 6,
            background: t.accent,
            color: "#fff",
            cursor: "pointer",
          }}
        >
          Connect ChatGPT Account
        </button>
      )}

      {!isNew && !connected && phase.kind === "starting" && (
        <div style={{ color: t.textMuted, fontSize: 12 }}>Contacting OpenAI…</div>
      )}

      {phase.kind === "awaiting" && (
        <div
          style={{
            padding: 12,
            borderRadius: 8,
            background: t.surfaceRaised,
            border: `1px solid ${t.surfaceBorder}`,
          }}
        >
          <div
            style={{
              fontSize: 11,
              color: t.textMuted,
              marginBottom: 6,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.5px",
            }}
          >
            Step 1: open the verification page
          </div>
          <a
            href={phase.start.verification_uri_complete}
            target="_blank"
            rel="noreferrer noopener"
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 6,
              color: t.accent,
              fontSize: 13,
              fontWeight: 600,
              textDecoration: "none",
              marginBottom: 12,
            }}
          >
            {phase.start.verification_uri}
            <ExternalLink size={12} />
          </a>

          <div
            style={{
              fontSize: 11,
              color: t.textMuted,
              marginBottom: 6,
              fontWeight: 600,
              textTransform: "uppercase",
              letterSpacing: "0.5px",
            }}
          >
            Step 2: enter this code
          </div>
          <div
            style={{
              display: "flex",
              flexDirection: "row",
              alignItems: "center",
              gap: 8,
              marginBottom: 12,
            }}
          >
            <code
              style={{
                fontSize: 20,
                fontWeight: 700,
                letterSpacing: "0.18em",
                padding: "6px 14px",
                background: t.surface,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 6,
                fontFamily: "monospace",
                color: t.text,
              }}
            >
              {phase.start.user_code}
            </code>
            <button
              onClick={() => copyCode(phase.start.user_code)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 4,
                padding: "5px 10px",
                fontSize: 11,
                border: `1px solid ${t.surfaceBorder}`,
                borderRadius: 5,
                background: "transparent",
                color: t.textMuted,
                cursor: "pointer",
              }}
            >
              <Copy size={11} />
              {phase.copied ? "Copied" : "Copy"}
            </button>
          </div>

          <div
            style={{
              fontSize: 11,
              color: t.textDim,
              marginBottom: 10,
            }}
          >
            Waiting for approval… this page will update automatically.
            {pollMut.isPending && " Polling…"}
          </div>

          <button
            onClick={handleCancelFlow}
            style={{
              display: "inline-flex",
              alignItems: "center",
              gap: 4,
              padding: "5px 10px",
              fontSize: 11,
              border: `1px solid ${t.surfaceBorder}`,
              borderRadius: 5,
              background: "transparent",
              color: t.textMuted,
              cursor: "pointer",
            }}
          >
            <X size={11} />
            Cancel
          </button>
        </div>
      )}

      {phase.kind === "error" && (
        <div
          style={{
            padding: 10,
            borderRadius: 6,
            background: t.dangerSubtle,
            color: t.danger,
            fontSize: 12,
            display: "flex",
            flexDirection: "row",
            alignItems: "center",
            gap: 8,
          }}
        >
          <X size={14} />
          <span style={{ flex: 1 }}>{phase.message}</span>
          <button
            onClick={() => setPhase({ kind: "idle" })}
            style={{
              padding: "3px 10px",
              fontSize: 11,
              fontWeight: 600,
              border: `1px solid ${t.danger}`,
              borderRadius: 5,
              background: "transparent",
              color: t.danger,
              cursor: "pointer",
            }}
          >
            Dismiss
          </button>
        </div>
      )}

      <ConfirmDialogSlot />
    </Section>
  );
}
