import { ShieldCheck, ShieldAlert, ShieldOff } from "lucide-react";

import { useThemeTokens } from "../../theme/tokens";

type SignatureState = "signed" | "unsigned" | "tampered";

interface Props {
  state?: SignatureState | null;
  lastSignedAt?: string | null;
  size?: "sm" | "md";
}

/**
 * Signed / Unsigned / Tampered badge for skills and widget packages.
 *
 * Backed by `signature_state` from `/api/v1/admin/{skills,widget-packages}`
 * — a NULL signature is "unsigned" (Phase-1 backward compat), a present
 * signature that verifies is "signed", and a present signature that fails
 * verification is "tampered" (run trust-current-state after review).
 */
export function ManifestSignatureBadge({ state, lastSignedAt, size = "sm" }: Props) {
  const t = useThemeTokens();
  const effective: SignatureState = state ?? "unsigned";
  const dim = size === "sm" ? 11 : 14;
  const fontSize = size === "sm" ? 10 : 12;

  let color: string;
  let bg: string;
  let label: string;
  let icon: React.ReactNode;
  let title: string;

  if (effective === "signed") {
    color = t.success;
    bg = t.successSubtle;
    label = "Signed";
    icon = <ShieldCheck size={dim} color={color} />;
    title = lastSignedAt
      ? `Signed (verified) — last updated ${new Date(lastSignedAt).toLocaleString()}`
      : "Signed (verified)";
  } else if (effective === "tampered") {
    color = t.danger;
    bg = t.dangerSubtle;
    label = "Tampered";
    icon = <ShieldAlert size={dim} color={color} />;
    title =
      "Signature does not match body. Review the row, then run POST /api/v1/admin/manifest/trust-current-state.";
  } else {
    color = t.textMuted;
    bg = "transparent";
    label = "Unsigned";
    icon = <ShieldOff size={dim} color={color} />;
    title =
      "No signature persisted (Phase-1 backward compat). Run trust-current-state to sign.";
  }

  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 6px",
        borderRadius: 999,
        background: bg,
        color,
        fontSize,
        fontWeight: 500,
        lineHeight: 1,
      }}
    >
      {icon}
      {label}
    </span>
  );
}
