/**
 * Mission Control — Express backend
 *
 * Serves the React SPA and provides:
 * 1. File reader API — reads workspace files from the mounted /workspaces volume
 * 2. API proxy — forwards authenticated requests to the agent server
 */
import express from "express";
import cors from "cors";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
const app = express();
const PORT = parseInt(process.env.PORT || "3000", 10);
const WORKSPACES_ROOT = process.env.WORKSPACES_ROOT || "/workspaces";
const AGENT_SERVER_URL = (process.env.AGENT_SERVER_URL || "http://host.docker.internal:8000").replace(/\/$/, "");
const API_KEY = process.env.AGENT_SERVER_API_KEY || "";
app.use(cors());
app.use(express.json());
// ---------------------------------------------------------------------------
// Health check
// ---------------------------------------------------------------------------
app.get("/api/health", (_req, res) => {
    res.json({ status: "ok", workspaces_root: WORKSPACES_ROOT });
});
// ---------------------------------------------------------------------------
// File reader — reads files from the mounted workspaces volume
// ---------------------------------------------------------------------------
/** Resolve a safe path within WORKSPACES_ROOT, preventing traversal. */
function safePath(segments) {
    const joined = path.join(WORKSPACES_ROOT, ...segments);
    const resolved = path.resolve(joined);
    if (!resolved.startsWith(path.resolve(WORKSPACES_ROOT) + path.sep) && resolved !== path.resolve(WORKSPACES_ROOT)) {
        return null;
    }
    return resolved;
}
/** List channels by scanning the workspaces directory structure. */
app.get("/api/files/channels", (_req, res) => {
    const channels = [];
    // Scan shared workspaces: shared/*/channels/*/
    const scanWorkspace = (wsPath, wsType) => {
        const channelsDir = path.join(wsPath, "channels");
        if (!fs.existsSync(channelsDir))
            return;
        for (const entry of fs.readdirSync(channelsDir, { withFileTypes: true })) {
            if (!entry.isDirectory())
                continue;
            const info = {
                id: entry.name,
                workspace_type: wsType,
            };
            // Read .channel_info for display name
            const infoPath = path.join(channelsDir, entry.name, ".channel_info");
            if (fs.existsSync(infoPath)) {
                const content = fs.readFileSync(infoPath, "utf-8");
                const match = content.match(/display_name:\s*(.+)/);
                if (match)
                    info.display_name = match[1].trim();
            }
            channels.push(info);
        }
    };
    try {
        // Scan shared/*/
        const sharedDir = path.join(WORKSPACES_ROOT, "shared");
        if (fs.existsSync(sharedDir)) {
            for (const ws of fs.readdirSync(sharedDir, { withFileTypes: true })) {
                if (ws.isDirectory()) {
                    scanWorkspace(path.join(sharedDir, ws.name), `shared/${ws.name}`);
                }
            }
        }
        // Scan bot workspaces: {bot_id}/ (non-shared)
        for (const entry of fs.readdirSync(WORKSPACES_ROOT, { withFileTypes: true })) {
            if (entry.isDirectory() && entry.name !== "shared") {
                scanWorkspace(path.join(WORKSPACES_ROOT, entry.name), entry.name);
            }
        }
    }
    catch (err) {
        console.error("Error scanning workspaces:", err);
    }
    res.json({ channels });
});
/** List files in a channel workspace. */
app.get("/api/files/channels/:channelId/files", (req, res) => {
    const { channelId } = req.params;
    const includeArchive = req.query.include_archive === "true";
    // Search for this channel across all workspace roots
    const channelDir = findChannelDir(channelId);
    if (!channelDir) {
        return res.json({ files: [] });
    }
    const files = [];
    // Active .md files
    try {
        for (const entry of fs.readdirSync(channelDir, { withFileTypes: true })) {
            if (entry.isFile() && entry.name.endsWith(".md")) {
                const stat = fs.statSync(path.join(channelDir, entry.name));
                files.push({
                    name: entry.name,
                    path: entry.name,
                    size: stat.size,
                    modified_at: stat.mtimeMs / 1000,
                    section: "active",
                });
            }
        }
    }
    catch { /* empty dir */ }
    // Archive files
    if (includeArchive) {
        const archiveDir = path.join(channelDir, "archive");
        try {
            for (const entry of fs.readdirSync(archiveDir, { withFileTypes: true })) {
                if (entry.isFile() && entry.name.endsWith(".md")) {
                    const stat = fs.statSync(path.join(archiveDir, entry.name));
                    files.push({
                        name: entry.name,
                        path: `archive/${entry.name}`,
                        size: stat.size,
                        modified_at: stat.mtimeMs / 1000,
                        section: "archive",
                    });
                }
            }
        }
        catch { /* no archive */ }
    }
    res.json({ files });
});
/** Read a specific file from a channel workspace. */
app.get("/api/files/channels/:channelId/content", (req, res) => {
    const { channelId } = req.params;
    const filePath = req.query.path;
    if (!filePath)
        return res.status(400).json({ error: "path query param required" });
    const channelDir = findChannelDir(channelId);
    if (!channelDir)
        return res.status(404).json({ error: "Channel not found" });
    const resolved = path.resolve(path.join(channelDir, filePath));
    if (!resolved.startsWith(path.resolve(channelDir))) {
        return res.status(400).json({ error: "Path traversal not allowed" });
    }
    if (!fs.existsSync(resolved)) {
        return res.status(404).json({ error: "File not found" });
    }
    const content = fs.readFileSync(resolved, "utf-8");
    res.json({ path: filePath, content });
});
/** Read daily logs for a channel's bot. */
app.get("/api/files/channels/:channelId/logs", (req, res) => {
    const { channelId } = req.params;
    const limit = parseInt(req.query.limit || "7", 10);
    // Find the bot workspace that contains this channel, then look for memory/logs/
    const channelDir = findChannelDir(channelId);
    if (!channelDir)
        return res.json({ logs: [] });
    // Walk up to find memory/logs/ relative to the workspace root
    // channelDir is like: /workspaces/shared/{ws}/channels/{id}
    // logs are at:        /workspaces/{bot_id}/memory/logs/
    // We'll scan all top-level bot dirs for memory/logs/
    const logs = [];
    try {
        for (const entry of fs.readdirSync(WORKSPACES_ROOT, { withFileTypes: true })) {
            if (!entry.isDirectory())
                continue;
            const logsDir = path.join(WORKSPACES_ROOT, entry.name, "memory", "logs");
            if (!fs.existsSync(logsDir))
                continue;
            const logFiles = fs.readdirSync(logsDir)
                .filter((f) => f.endsWith(".md"))
                .sort()
                .reverse()
                .slice(0, limit);
            for (const logFile of logFiles) {
                const content = fs.readFileSync(path.join(logsDir, logFile), "utf-8");
                logs.push({ date: logFile.replace(".md", ""), content });
            }
        }
    }
    catch { /* no logs */ }
    // Deduplicate by date (if multiple bots have logs)
    const seen = new Set();
    const unique = logs
        .sort((a, b) => b.date.localeCompare(a.date))
        .filter((l) => {
        if (seen.has(l.date))
            return false;
        seen.add(l.date);
        return true;
    })
        .slice(0, limit);
    res.json({ logs: unique });
});
/** Find a channel directory across all workspace roots. */
function findChannelDir(channelId) {
    // Security check
    if (channelId.includes("..") || channelId.includes("/"))
        return null;
    const searchDirs = [];
    // shared/*/channels/
    const sharedDir = path.join(WORKSPACES_ROOT, "shared");
    if (fs.existsSync(sharedDir)) {
        for (const ws of fs.readdirSync(sharedDir, { withFileTypes: true })) {
            if (ws.isDirectory()) {
                searchDirs.push(path.join(sharedDir, ws.name, "channels"));
            }
        }
    }
    // {bot_id}/channels/
    for (const entry of fs.readdirSync(WORKSPACES_ROOT, { withFileTypes: true })) {
        if (entry.isDirectory() && entry.name !== "shared") {
            searchDirs.push(path.join(WORKSPACES_ROOT, entry.name, "channels"));
        }
    }
    for (const dir of searchDirs) {
        const candidate = path.join(dir, channelId);
        if (fs.existsSync(candidate) && fs.statSync(candidate).isDirectory()) {
            return candidate;
        }
    }
    return null;
}
// ---------------------------------------------------------------------------
// API proxy — forwards requests to the agent server with auth
// ---------------------------------------------------------------------------
app.all("/api/proxy/*", async (req, res) => {
    const targetPath = req.params[0];
    const url = `${AGENT_SERVER_URL}/${targetPath}`;
    const headers = {
        "Content-Type": "application/json",
    };
    if (API_KEY) {
        headers["Authorization"] = `Bearer ${API_KEY}`;
    }
    try {
        const fetchOpts = {
            method: req.method,
            headers,
        };
        if (req.method !== "GET" && req.method !== "HEAD") {
            fetchOpts.body = JSON.stringify(req.body);
        }
        // Forward query params
        const queryStr = new URLSearchParams(req.query).toString();
        const fullUrl = queryStr ? `${url}?${queryStr}` : url;
        const response = await fetch(fullUrl, fetchOpts);
        const data = await response.json();
        res.status(response.status).json(data);
    }
    catch (err) {
        console.error(`Proxy error: ${req.method} ${url}`, err);
        res.status(502).json({ error: "Failed to reach agent server" });
    }
});
// ---------------------------------------------------------------------------
// Serve React SPA (production)
// ---------------------------------------------------------------------------
const __server_dir = path.dirname(fileURLToPath(import.meta.url));
const distPath = path.join(__server_dir, "dist");
if (fs.existsSync(distPath)) {
    app.use(express.static(distPath));
    app.get("*", (_req, res) => {
        res.sendFile(path.join(distPath, "index.html"));
    });
}
app.listen(PORT, "0.0.0.0", () => {
    console.log(`[mission-control] Server listening on port ${PORT}`);
    console.log(`[mission-control] Workspaces root: ${WORKSPACES_ROOT}`);
    console.log(`[mission-control] Agent server: ${AGENT_SERVER_URL}`);
});
