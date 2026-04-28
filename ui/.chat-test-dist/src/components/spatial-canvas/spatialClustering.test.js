import test from "node:test";
import assert from "node:assert/strict";
import { buildChannelClusters, CHANNEL_CLUSTER_EXIT_SCALE, CHANNEL_CLUSTER_FOCUS_SCALE, clusterSuppressedChannelIds, clusterSuppressedNodeIds, } from "./spatialClustering.ts";
function channel(id, name, last) {
    return {
        id,
        name,
        bot_id: "bot",
        require_mention: false,
        passive_memory: false,
        private: false,
        created_at: "2026-04-01T00:00:00.000Z",
        updated_at: last,
        last_message_at: last,
    };
}
function node(id, channelId, x) {
    return {
        id,
        channel_id: channelId,
        widget_pin_id: null,
        bot_id: null,
        landmark_kind: null,
        world_x: x,
        world_y: 0,
        world_w: 280,
        world_h: 180,
        z_index: 0,
        seed_index: 0,
        pinned_at: null,
        updated_at: null,
    };
}
test("far zoom clusters nearby channels by screen proximity", () => {
    const channels = new Map([
        ["a", channel("a", "Alpha", "2026-04-01T00:00:00.000Z")],
        ["b", channel("b", "Beta", "2026-04-02T00:00:00.000Z")],
        ["c", channel("c", "Gamma", "2026-04-03T00:00:00.000Z")],
    ]);
    const clusters = buildChannelClusters({
        nodes: [node("na", "a", 0), node("nb", "b", 250), node("nc", "c", 2000)],
        channelsById: channels,
        activityByChannelId: new Map([["a", { tokens: 10, calls: 1 }], ["b", { tokens: 100, calls: 1 }]]),
        camera: { x: 0, y: 0, scale: 0.2 },
        enabled: true,
        radius: 92,
    });
    assert.equal(clusters.length, 1);
    assert.equal(clusters[0].winner.channel.name, "Beta");
    assert.deepEqual(clusterSuppressedNodeIds(clusters), new Set(["na", "nb"]));
    assert.deepEqual(clusterSuppressedChannelIds(clusters), new Set(["a", "b"]));
});
test("cluster winner falls back to recency when usage is absent", () => {
    const channels = new Map([
        ["a", channel("a", "Alpha", "2026-04-01T00:00:00.000Z")],
        ["b", channel("b", "Beta", "2026-04-03T00:00:00.000Z")],
    ]);
    const clusters = buildChannelClusters({
        nodes: [node("na", "a", 0), node("nb", "b", 250)],
        channelsById: channels,
        activityByChannelId: new Map(),
        camera: { x: 0, y: 0, scale: 0.2 },
        enabled: true,
        radius: 92,
    });
    assert.equal(clusters[0].winner.channel.name, "Beta");
});
test("cluster focus scale lands just past uncluster without entering preview zoom", () => {
    assert.ok(CHANNEL_CLUSTER_FOCUS_SCALE > CHANNEL_CLUSTER_EXIT_SCALE);
    assert.ok(CHANNEL_CLUSTER_FOCUS_SCALE < 0.4);
    assert.equal(CHANNEL_CLUSTER_FOCUS_SCALE, 0.31);
});
