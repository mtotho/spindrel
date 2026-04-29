import type { SessionPlan } from "@/app/(app)/channels/[channelId]/useSessionPlanMode";

function parseMaybeJson(raw: unknown): unknown {
  if (typeof raw !== "string") return raw;
  try {
    return JSON.parse(raw);
  } catch {
    return raw;
  }
}

function hasObjectShape(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function looksLikeSessionPlan(value: unknown): value is SessionPlan {
  if (!hasObjectShape(value)) return false;
  return (
    typeof value.title === "string"
    && typeof value.summary === "string"
    && typeof value.revision === "number"
    && typeof value.session_id === "string"
    && Array.isArray(value.steps)
  );
}

export function parsePlanPayload(raw: unknown, depth = 0): SessionPlan | null {
  if (raw == null || depth > 4) return null;
  const parsed = parseMaybeJson(raw);
  if (looksLikeSessionPlan(parsed)) return parsed;
  if (!hasObjectShape(parsed)) return null;

  const embeddedEnvelope = parsed._envelope;
  if (hasObjectShape(embeddedEnvelope) && "body" in embeddedEnvelope) {
    const fromEnvelope = parsePlanPayload(embeddedEnvelope.body, depth + 1);
    if (fromEnvelope) return fromEnvelope;
  }

  if ("plan" in parsed) {
    const fromPlanField = parsePlanPayload(parsed.plan, depth + 1);
    if (fromPlanField) return fromPlanField;
  }

  if ("body" in parsed) {
    return parsePlanPayload(parsed.body, depth + 1);
  }

  return null;
}
