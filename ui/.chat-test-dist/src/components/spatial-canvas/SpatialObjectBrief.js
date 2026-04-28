function asString(value) {
    return typeof value === "string" && value.trim() ? value.trim() : null;
}
function asNumber(value) {
    return typeof value === "number" && Number.isFinite(value) ? value : null;
}
function titleForSignal(signal) {
    if (!signal)
        return null;
    return signal.title || signal.kind || null;
}
function signalKey(signal) {
    return [
        signal.id,
        signal.kind,
        signal.title,
        signal.task_id,
        signal.bot_id,
        signal.channel_id,
        signal.created_at,
        signal.last_seen_at,
        signal.error,
    ].filter(Boolean).join("|");
}
function dedupeSignals(signals) {
    const seen = new Set();
    const out = [];
    for (const signal of signals) {
        const key = signalKey(signal);
        if (seen.has(key))
            continue;
        seen.add(key);
        out.push(signal);
    }
    return out;
}
function relativeTime(value, now = Date.now()) {
    if (!value)
        return null;
    const ts = Date.parse(value);
    if (!Number.isFinite(ts))
        return null;
    const diff = ts - now;
    const abs = Math.abs(diff);
    const minute = 60_000;
    const hour = 60 * minute;
    const day = 24 * hour;
    const suffix = diff >= 0 ? "from now" : "ago";
    if (abs < minute)
        return diff >= 0 ? "now" : "just now";
    if (abs < hour)
        return `${Math.round(abs / minute)}m ${suffix}`;
    if (abs < day)
        return `${Math.round(abs / hour)}h ${suffix}`;
    return `${Math.round(abs / day)}d ${suffix}`;
}
function sourceLinesFor(state) {
    const source = state.source || {};
    const attached = state.attached || {};
    const lines = [];
    if (state.kind === "channel") {
        const bot = asString(source.primary_bot_name) || asString(source.primary_bot_id);
        if (bot)
            lines.push(`Primary bot: ${bot}`);
        if (state.counts.bots > 1)
            lines.push(`${state.counts.bots} bots attached`);
        if (state.counts.integrations > 0)
            lines.push(`${state.counts.integrations} integrations`);
        const heartbeat = attached.heartbeat;
        if (heartbeat) {
            const enabled = heartbeat.enabled === true ? "enabled" : "paused";
            const interval = asNumber(heartbeat.interval_minutes);
            lines.push(interval ? `Heartbeat ${enabled}, every ${interval}m` : `Heartbeat ${enabled}`);
        }
    }
    else if (state.kind === "bot") {
        const model = asString(source.model);
        const runtime = asString(source.harness_runtime);
        if (model)
            lines.push(`Model: ${model}`);
        if (runtime)
            lines.push(`Runtime: ${runtime}`);
        const channelIds = Array.isArray(attached.channel_ids) ? attached.channel_ids.length : 0;
        if (channelIds)
            lines.push(`${channelIds} rooms`);
    }
    else if (state.kind === "widget") {
        const tool = asString(source.tool_name);
        const sourceChannel = asString(source.source_channel_name);
        if (tool)
            lines.push(`Tool: ${tool}`);
        if (sourceChannel)
            lines.push(`Source: #${sourceChannel}`);
        const cronCount = asNumber(attached.cron_count) ?? 0;
        const eventCount = asNumber(attached.event_count) ?? 0;
        if (cronCount || eventCount)
            lines.push(`${cronCount} cron · ${eventCount} event`);
    }
    else if (state.kind === "landmark") {
        lines.push("Workspace landmark");
    }
    return lines;
}
export function buildSpatialObjectBrief(state, now = Date.now()) {
    if (!state)
        return null;
    const warnings = dedupeSignals(state.warnings ?? []).slice(0, 4);
    const warningKeys = new Set(warnings.map(signalKey));
    const recent = dedupeSignals(state.recent ?? []).filter((signal) => !warningKeys.has(signalKey(signal))).slice(0, 4);
    const next = state.next ?? null;
    const nextTitle = titleForSignal(next);
    const recentTitle = titleForSignal(recent[0]);
    const warningTitle = titleForSignal(warnings[0]);
    const tone = state.status === "error" || state.severity === "critical" || state.severity === "error"
        ? "danger"
        : state.status === "warning" || state.severity === "warning"
            ? "warning"
            : state.status === "running" || state.status === "scheduled" || state.status === "active"
                ? "active"
                : "muted";
    let headline = "Quiet";
    if (state.status === "error")
        headline = warningTitle || state.primary_signal || "Needs attention";
    else if (state.status === "warning")
        headline = warningTitle || state.primary_signal || "Warning";
    else if (state.status === "running")
        headline = state.primary_signal || "Running";
    else if (state.status === "scheduled")
        headline = nextTitle || state.primary_signal || "Scheduled";
    else if (state.status === "recent")
        headline = recentTitle || state.primary_signal || "Recently active";
    const parts = [];
    if (nextTitle) {
        const when = relativeTime(next?.scheduled_at || next?.created_at || null, now);
        parts.push(when ? `Next: ${nextTitle} (${when})` : `Next: ${nextTitle}`);
    }
    if (recentTitle) {
        const when = relativeTime(recent[0]?.completed_at || recent[0]?.created_at || recent[0]?.last_seen_at || null, now);
        parts.push(when ? `Recent: ${recentTitle} (${when})` : `Recent: ${recentTitle}`);
    }
    if (warnings.length)
        parts.push(`${warnings.length} warning${warnings.length === 1 ? "" : "s"}`);
    const summary = parts.join(" · ") || "No scheduled work or recent warnings on this object.";
    return {
        headline,
        summary,
        tone,
        sourceLines: sourceLinesFor(state).slice(0, 5),
        next,
        recent,
        warnings,
    };
}
export function formatSignalTime(signal) {
    return relativeTime(signal.scheduled_at || signal.completed_at || signal.created_at || signal.last_seen_at || null);
}
