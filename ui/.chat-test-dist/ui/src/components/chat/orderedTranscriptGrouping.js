export function groupAdjacentTranscriptItems(items) {
    const grouped = [];
    let pending = null;
    const flush = () => {
        if (pending) {
            grouped.push(pending);
            pending = null;
        }
    };
    for (const item of items) {
        if (item.kind !== "transcript") {
            flush();
            grouped.push(item);
            continue;
        }
        if (!pending) {
            pending = item;
            continue;
        }
        pending = {
            kind: "transcript",
            key: `${pending.key}:group:${item.key}`,
            entries: [...pending.entries, ...item.entries],
        };
    }
    flush();
    return grouped;
}
