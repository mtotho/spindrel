# Plan: Tool Group Selection UI

## Problem
The bot editor's Tools tab shows tools organized by integration → pack, but there's no way to select/deselect an entire integration group at once. With many tools, configuring a bot requires clicking each pack's "all" button individually.

## Current State
- `ToolsSection` in `ui/app/(app)/admin/bots/[botId]/index.tsx` (lines 283-680)
- Tools are already organized into `ToolGroup` (integration level) → `ToolPack` (file level) → tools
- Pack-level "all/none" toggle exists (`togglePack` function, line 331)
- Group header shows integration name + total count but **no select-all control**

## Changes

### 1. Add `toggleGroup` function (next to `togglePack`, ~line 339)

```typescript
const toggleGroup = (group: ToolGroup) => {
  const allNames = group.packs.flatMap((p) => p.tools.map((t) => t.name));
  const allEnabled = allNames.every((n) => localTools.includes(n));
  if (allEnabled) {
    update({ local_tools: localTools.filter((t) => !allNames.includes(t)) });
  } else {
    const toAdd = allNames.filter((n) => !localTools.includes(n));
    update({ local_tools: [...localTools, ...toAdd] });
  }
};
```

### 2. Update group header (lines 382-398)

Add "all / none" button + selected count to the group header bar, next to the total count:

```
[ Core                          12/47  all | none ]
[ SLACK                          0/5   all | none ]
```

Specifically, in the `<div>` at line 383 (group header), add after the total count span:

```tsx
{/* Group-level select controls */}
{(() => {
  const allNames = group.packs.flatMap((p) => p.tools.map((t) => t.name));
  const selectedCount = allNames.filter((n) => localTools.includes(n)).length;
  const allEnabled = selectedCount === allNames.length;
  return (
    <>
      <span style={{ fontSize: 9, color: "#555" }}>
        {selectedCount}/{allNames.length}
      </span>
      <button
        onClick={(e) => { e.stopPropagation(); toggleGroup(group); }}
        style={{
          background: "none", border: "1px solid #333", borderRadius: 4,
          padding: "1px 6px", fontSize: 9, cursor: "pointer",
          color: allEnabled ? "#f87171" : "#86efac",
        }}
        title={allEnabled ? "Deselect all in group" : "Select all in group"}
      >
        {allEnabled ? "none" : "all"}
      </button>
    </>
  );
})()}
```

### 3. File changes

| File | Change |
|------|--------|
| `ui/app/(app)/admin/bots/[botId]/index.tsx` | Add `toggleGroup`, add group-header controls |

### Scope
- Frontend only, no API or backend changes needed
- ~20 lines of new code
- Follows existing pattern from `togglePack`

## Implementation Notes
- The existing `<span>` showing `{group.total}` at line 397 should be replaced by the new selected/total count + button
- Keep the `marginLeft: "auto"` on the first new element so controls stay right-aligned
- When search filter is active, group-level toggle should still operate on **all** tools in the group (not just filtered), matching how `togglePack` operates on `packNames` (unfiltered)
