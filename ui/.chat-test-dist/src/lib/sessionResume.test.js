import assert from "node:assert/strict";
import { SESSION_RESUME_IDLE_MS, getNewestVisibleMessageAt, sessionResumeDismissKey, shouldShowSessionResumeCard, } from "./sessionResume.js";
const old = "2026-04-24T12:00:00.000Z";
const recent = "2026-04-24T14:00:00.000Z";
assert.equal(getNewestVisibleMessageAt([
    { role: "assistant", created_at: old },
    { role: "user", created_at: recent },
    { role: "system", created_at: "2026-04-24T15:00:00.000Z" },
    { role: "assistant", created_at: "2026-04-24T16:00:00.000Z", metadata: { ui_only: true } },
]), recent);
assert.equal(sessionResumeDismissKey("s1", recent), `s1:${recent}`);
assert.equal(sessionResumeDismissKey("s1", null), null);
assert.equal(shouldShowSessionResumeCard({
    enabled: true,
    dismissed: false,
    isActive: false,
    nowMs: Date.parse(recent) + SESSION_RESUME_IDLE_MS,
    metadata: {
        sessionId: "s1",
        surfaceKind: "primary",
        lastVisibleMessageAt: recent,
        messageCount: 2,
    },
}), true);
assert.equal(shouldShowSessionResumeCard({
    enabled: true,
    dismissed: false,
    isActive: true,
    nowMs: Date.parse(recent) + SESSION_RESUME_IDLE_MS,
    metadata: {
        sessionId: "s1",
        surfaceKind: "primary",
        lastVisibleMessageAt: recent,
        messageCount: 2,
    },
}), false);
assert.equal(shouldShowSessionResumeCard({
    enabled: true,
    dismissed: false,
    isActive: false,
    nowMs: Date.parse(recent) + SESSION_RESUME_IDLE_MS,
    metadata: {
        sessionId: "s1",
        surfaceKind: "primary",
        lastVisibleMessageAt: recent,
        messageCount: 0,
    },
}), false);
