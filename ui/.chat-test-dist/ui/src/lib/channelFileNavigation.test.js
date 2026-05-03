import test from "node:test";
import assert from "node:assert/strict";
import { buildChannelFileHref, defaultChannelBrowsePath, directoryForWorkspaceFile, readChannelFileIntent, resolveChannelLinkedFilePath, resolveChannelFileViewerScope, resolveMemoryFilePath, resolveToolTargetFilePath, } from "./channelFileNavigation.js";
test("buildChannelFileHref keeps channel routes on the main chat when no session is provided", () => {
    assert.equal(buildChannelFileHref({
        channelId: "channel-1",
        directoryPath: "/channels/channel-1/archive/",
        openFile: "/channels/channel-1/archive/notes.md",
    }), "/channels/channel-1?files_path=channels%2Fchannel-1%2Farchive&open_file=channels%2Fchannel-1%2Farchive%2Fnotes.md");
});
test("buildChannelFileHref preserves workspace root as an explicit files_path sentinel", () => {
    assert.equal(buildChannelFileHref({
        channelId: "channel-1",
        directoryPath: "/",
        openFile: "README.md",
    }), "/channels/channel-1?files_path=.&open_file=README.md");
});
test("buildChannelFileHref preserves scratch session routes when requested", () => {
    assert.equal(buildChannelFileHref({
        channelId: "channel-1",
        sessionId: "session-1",
        scratch: true,
        directoryPath: "channels/channel-1",
        openFile: "channels/channel-1/brief.md",
    }), "/channels/channel-1/session/session-1?scratch=true&files_path=channels%2Fchannel-1&open_file=channels%2Fchannel-1%2Fbrief.md");
});
test("directoryForWorkspaceFile returns the containing folder for workspace-relative files", () => {
    assert.equal(directoryForWorkspaceFile("channels/channel-1/data/brief.md"), "channels/channel-1/data");
    assert.equal(directoryForWorkspaceFile("README.md"), "");
});
test("readChannelFileIntent derives the target directory from open_file when files_path is omitted", () => {
    const searchParams = new URLSearchParams({
        open_file: "/channels/channel-1/data/brief.md",
    });
    assert.deepEqual(readChannelFileIntent(searchParams, "channel-1"), {
        directoryPath: "channels/channel-1/data",
        openFile: "channels/channel-1/data/brief.md",
    });
});
test("readChannelFileIntent prefers files_path and falls back to the channel root when only a folder intent is present", () => {
    const explicit = new URLSearchParams({
        files_path: "/bots/bot-1/memory",
        open_file: "/channels/channel-1/notes.md",
    });
    assert.deepEqual(readChannelFileIntent(explicit, "channel-1"), {
        directoryPath: "bots/bot-1/memory",
        openFile: "channels/channel-1/notes.md",
    });
    const folderOnly = new URLSearchParams({
        files_path: defaultChannelBrowsePath("channel-1"),
    });
    assert.deepEqual(readChannelFileIntent(folderOnly, "channel-1"), {
        directoryPath: "channels/channel-1",
        openFile: null,
    });
});
test("readChannelFileIntent round-trips the workspace root sentinel", () => {
    const root = new URLSearchParams({
        files_path: ".",
        open_file: "README.md",
    });
    assert.deepEqual(readChannelFileIntent(root, "channel-1"), {
        directoryPath: "",
        openFile: "README.md",
    });
});
test("resolveChannelFileViewerScope treats direct open_file paths as channel relative", () => {
    assert.deepEqual(resolveChannelFileViewerScope("channel-1", "notes/plan.md"), {
        kind: "channel",
        path: "notes/plan.md",
    });
    assert.deepEqual(resolveChannelFileViewerScope("channel-1", "channels/channel-1/notes/plan.md"), {
        kind: "channel",
        path: "notes/plan.md",
    });
});
test("resolveChannelFileViewerScope preserves shared workspace files outside this channel", () => {
    assert.deepEqual(resolveChannelFileViewerScope("channel-1", "channels/channel-2/notes/plan.md"), {
        kind: "workspace",
        path: "channels/channel-2/notes/plan.md",
    });
    assert.deepEqual(resolveChannelFileViewerScope("channel-1", "bots/bot-1/persona.md"), {
        kind: "workspace",
        path: "bots/bot-1/persona.md",
    });
});
test("resolveChannelLinkedFilePath accepts file-like relative links", () => {
    assert.equal(resolveChannelLinkedFilePath("AGENTS.md"), "AGENTS.md");
    assert.equal(resolveChannelLinkedFilePath("./get-latest.sh?raw=1"), "get-latest.sh");
    assert.equal(resolveChannelLinkedFilePath("common/projects/vault/README.md#top"), "common/projects/vault/README.md");
});
test("resolveChannelLinkedFilePath rejects external and app navigation links", () => {
    assert.equal(resolveChannelLinkedFilePath("https://example.com/AGENTS.md"), null);
    assert.equal(resolveChannelLinkedFilePath("/channels/channel-1?open_file=README.md"), null);
    assert.equal(resolveChannelLinkedFilePath("#local-heading"), null);
    assert.equal(resolveChannelLinkedFilePath("plain-word"), null);
});
test("resolveToolTargetFilePath accepts relative tool file targets only", () => {
    assert.equal(resolveToolTargetFilePath("docs/images/harness.png"), "docs/images/harness.png");
    assert.equal(resolveToolTargetFilePath("./AGENTS.md"), "AGENTS.md");
    assert.equal(resolveToolTargetFilePath(".spindrel-harness-parity/run.txt"), ".spindrel-harness-parity/run.txt");
    assert.equal(resolveToolTargetFilePath("/workspace-data/shared/project/AGENTS.md"), null);
    assert.equal(resolveToolTargetFilePath("~/project/AGENTS.md"), null);
    assert.equal(resolveToolTargetFilePath("C:\\Users\\me\\AGENTS.md"), null);
    assert.equal(resolveToolTargetFilePath("pytest -q tests/unit/test_uploads.py"), null);
});
test("resolveMemoryFilePath remaps bot-rooted memory paths to bots/<botId>/memory/...", () => {
    // Regression: chat memory updates emit ``memory/MEMORY.md``-style paths;
    // the channel files viewer resolves workspace-relative paths against the
    // Project cwd, so memory links used to open the wrong file. The remapped
    // form is recognized as workspace-scoped and routes to the bot's memory
    // root instead.
    assert.equal(resolveMemoryFilePath("memory/MEMORY.md", "bot-1"), "bots/bot-1/memory/MEMORY.md");
    assert.equal(resolveMemoryFilePath("memory/logs/2026-04-30.md", "bot-1"), "bots/bot-1/memory/logs/2026-04-30.md");
    // Plain rel path (no ``memory/`` prefix) is treated as memory-relative too,
    // matching how the memory tool sometimes reports paths.
    assert.equal(resolveMemoryFilePath("MEMORY.md", "bot-1"), "bots/bot-1/memory/MEMORY.md");
    // Already workspace-scoped under the same bot — pass through unchanged.
    assert.equal(resolveMemoryFilePath("bots/bot-1/memory/reference/project.md", "bot-1"), "bots/bot-1/memory/reference/project.md");
});
test("resolveMemoryFilePath rejects targets that escape the bot memory root", () => {
    assert.equal(resolveMemoryFilePath("../secrets.md", "bot-1"), null);
    assert.equal(resolveMemoryFilePath("memory/../etc/passwd", "bot-1"), null);
    assert.equal(resolveMemoryFilePath("/etc/passwd", "bot-1"), null);
    assert.equal(resolveMemoryFilePath("~/notes.md", "bot-1"), null);
    // Cross-bot memory references should not silently rewrite to the active bot.
    assert.equal(resolveMemoryFilePath("bots/other-bot/memory/MEMORY.md", "bot-1"), null);
    // Missing inputs.
    assert.equal(resolveMemoryFilePath("memory/MEMORY.md", null), null);
    assert.equal(resolveMemoryFilePath(null, "bot-1"), null);
    assert.equal(resolveMemoryFilePath("", "bot-1"), null);
});
test("buildChannelFileHref routes a remapped memory path to the bot memory root", () => {
    // End-to-end smoke test: a memory tool emits ``memory/MEMORY.md`` and the
    // channel files viewer needs to load ``bots/<bot_id>/memory/MEMORY.md`` —
    // not ``<projectPath>/memory/MEMORY.md``. The href below is what the link
    // builds after ``resolveMemoryFilePath`` does the remap.
    const filePath = resolveMemoryFilePath("memory/MEMORY.md", "bot-1");
    assert.equal(filePath, "bots/bot-1/memory/MEMORY.md");
    assert.equal(buildChannelFileHref({
        channelId: "channel-1",
        directoryPath: directoryForWorkspaceFile(filePath),
        openFile: filePath,
    }), "/channels/channel-1?files_path=bots%2Fbot-1%2Fmemory&open_file=bots%2Fbot-1%2Fmemory%2FMEMORY.md");
});
