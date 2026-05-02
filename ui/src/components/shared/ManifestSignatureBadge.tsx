import { StatusBadge } from "./SettingsControls";

type SignatureState = "signed" | "unsigned" | "tampered";

interface Props {
  state?: SignatureState | null;
  lastSignedAt?: string | null;
}

/**
 * Signed / Unsigned / Tampered badge for skills and widget packages.
 *
 * Backed by `signature_state` from `/api/v1/admin/{skills,widget-packages}` —
 * NULL signature → "unsigned" (Phase-1 backward compat),
 * present + verifies → "signed",
 * present + fails verification → "tampered" (run `POST
 * /api/v1/admin/manifest/trust-current-state` after review).
 *
 * Renders nothing for "unsigned" so existing rows pre-trust-current-state
 * don't drown the listing in muted pills; the absence of a badge implies
 * unsigned.
 */
export function ManifestSignatureBadge({ state, lastSignedAt }: Props) {
  const effective: SignatureState = state ?? "unsigned";
  if (effective === "unsigned") return null;

  if (effective === "tampered") {
    return (
      <span
        title="Signature does not match body. Review the row, then run POST /api/v1/admin/manifest/trust-current-state."
      >
        <StatusBadge label="tampered" variant="danger" />
      </span>
    );
  }

  const title = lastSignedAt
    ? `Signed (verified) — last updated ${new Date(lastSignedAt).toLocaleString()}`
    : "Signed (verified)";
  return (
    <span title={title}>
      <StatusBadge label="signed" variant="success" />
    </span>
  );
}
