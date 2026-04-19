import { useState, useEffect, useRef } from "react";
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
      <div className="mb-2.5 flex items-start gap-2 rounded-md bg-warning/[0.08] px-2.5 py-2 text-[11px] leading-snug text-warning">
        <AlertTriangle size={14} className="mt-0.5 shrink-0" />
        <span>
          Uses OpenAI&apos;s Codex device-code OAuth flow. Intended for personal
          self-hosted use — OpenAI recommends API keys for programmatic access.
          ChatGPT plan rate limits apply; tokens grant Responses-API access only.
        </span>
      </div>

      {isNew && (
        <div className="rounded-md bg-surface-raised px-3 py-2.5 text-[12px] leading-relaxed text-text-muted">
          Enter a Provider ID + Display Name above and hit <strong>Save</strong>.
          The <em>Connect ChatGPT Account</em> button will appear here once the
          provider exists — the OAuth flow needs a provider row to bind tokens to.
        </div>
      )}

      {!isNew && connected && (
        <FormRow label="Signed in as">
          <div className="flex items-center gap-2.5">
            <Check size={14} className="text-success" />
            <span className="text-[13px] font-semibold text-text">
              {status?.email || "(unknown email)"}
            </span>
            {status?.plan && (
              <span className="rounded bg-surface-raised px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-text-muted">
                {status.plan}
              </span>
            )}
            {status?.expires_at && (
              <span className="text-[11px] text-text-dim">
                Token expires {new Date(status.expires_at).toLocaleString()}
              </span>
            )}
            <button
              onClick={handleDisconnect}
              disabled={disconnectMut.isPending}
              className="ml-auto rounded border border-danger/60 bg-transparent px-3 py-1 text-[12px] font-semibold text-danger hover:bg-danger/10 disabled:opacity-50"
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
          className="rounded-md bg-accent px-[18px] py-2 text-[13px] font-semibold text-white hover:bg-accent-hover disabled:opacity-50"
        >
          Connect ChatGPT Account
        </button>
      )}

      {!isNew && !connected && phase.kind === "starting" && (
        <div className="text-[12px] text-text-muted">Contacting OpenAI…</div>
      )}

      {phase.kind === "awaiting" && (
        <div className="rounded-lg border border-surface-border bg-surface-raised p-3">
          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            Step 1: open the verification page
          </div>
          <a
            href={phase.start.verification_uri_complete}
            target="_blank"
            rel="noreferrer noopener"
            className="mb-3 inline-flex items-center gap-1.5 text-[13px] font-semibold text-accent no-underline hover:text-accent-hover"
          >
            {phase.start.verification_uri}
            <ExternalLink size={12} />
          </a>

          <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-text-muted">
            Step 2: enter this code
          </div>
          <div className="mb-3 flex items-center gap-2">
            <code className="rounded-md border border-surface-border bg-surface px-3.5 py-1.5 font-mono text-[20px] font-bold tracking-[0.18em] text-text">
              {phase.start.user_code}
            </code>
            <button
              onClick={() => copyCode(phase.start.user_code)}
              className="flex items-center gap-1 rounded border border-surface-border bg-transparent px-2.5 py-1 text-[11px] text-text-muted hover:bg-surface"
            >
              <Copy size={11} />
              {phase.copied ? "Copied" : "Copy"}
            </button>
          </div>

          <div className="mb-2.5 text-[11px] text-text-dim">
            Waiting for approval… this page will update automatically.
            {pollMut.isPending && " Polling…"}
          </div>

          <button
            onClick={handleCancelFlow}
            className="inline-flex items-center gap-1 rounded border border-surface-border bg-transparent px-2.5 py-1 text-[11px] text-text-muted hover:bg-surface"
          >
            <X size={11} />
            Cancel
          </button>
        </div>
      )}

      {phase.kind === "error" && (
        <div className="flex items-center gap-2 rounded-md bg-danger/10 px-2.5 py-2 text-[12px] text-danger">
          <X size={14} />
          <span className="flex-1">{phase.message}</span>
          <button
            onClick={() => setPhase({ kind: "idle" })}
            className="rounded border border-danger bg-transparent px-2.5 py-0.5 text-[11px] font-semibold text-danger hover:bg-danger/10"
          >
            Dismiss
          </button>
        </div>
      )}

      <ConfirmDialogSlot />
    </Section>
  );
}
