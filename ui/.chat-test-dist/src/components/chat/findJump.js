export async function loadUntilMessageVisible({ findNode, hasNextPage, isFetchingNextPage, loadMore, afterLoad, maxLoads = 20, }) {
    if (findNode())
        return "found";
    for (let i = 0; i < maxLoads; i += 1) {
        if (findNode())
            return "found";
        if (!hasNextPage())
            return "exhausted";
        if (isFetchingNextPage())
            return "busy";
        await loadMore();
        await afterLoad?.();
    }
    return findNode() ? "found" : "exhausted";
}
