import test from "node:test";
import assert from "node:assert/strict";

import { loadUntilMessageVisible } from "./findJump.js";

test("loads older pages until the target message is visible", async () => {
  let loads = 0;
  const result = await loadUntilMessageVisible({
    findNode: () => loads >= 2 ? ({} as HTMLElement) : null,
    hasNextPage: () => true,
    isFetchingNextPage: () => false,
    loadMore: async () => {
      loads += 1;
    },
  });

  assert.equal(result, "found");
  assert.equal(loads, 2);
});

test("reports exhausted when history ends before the target appears", async () => {
  let loads = 0;
  const result = await loadUntilMessageVisible({
    findNode: () => null,
    hasNextPage: () => loads < 1,
    isFetchingNextPage: () => false,
    loadMore: async () => {
      loads += 1;
    },
  });

  assert.equal(result, "exhausted");
  assert.equal(loads, 1);
});

test("does not issue overlapping loads while pagination is already fetching", async () => {
  let loads = 0;
  const result = await loadUntilMessageVisible({
    findNode: () => null,
    hasNextPage: () => true,
    isFetchingNextPage: () => true,
    loadMore: () => {
      loads += 1;
    },
  });

  assert.equal(result, "busy");
  assert.equal(loads, 0);
});
