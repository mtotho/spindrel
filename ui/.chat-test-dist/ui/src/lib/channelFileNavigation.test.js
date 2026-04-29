import test from "node:test";
import assert from "node:assert/strict";
import { buildChannelFileHref, defaultChannelBrowsePath, directoryForWorkspaceFile, readChannelFileIntent, resolveChannelFileViewerScope, } from "./channelFileNavigation.js";
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
