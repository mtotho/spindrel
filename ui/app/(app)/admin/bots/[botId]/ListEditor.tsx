import React from "react";

export function ListEditor({
  items,
  onUpdate,
  renderItem,
  renderAdd,
}: {
  items: any[];
  onUpdate: (items: any[]) => void;
  renderItem: (item: any, idx: number, remove: () => void) => React.ReactNode;
  renderAdd: (add: (item: any) => void) => React.ReactNode;
}) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {items.map((item, i) => (
        <div key={i}>{renderItem(item, i, () => onUpdate(items.filter((_, j) => j !== i)))}</div>
      ))}
      {renderAdd((item) => onUpdate([...items, item]))}
    </div>
  );
}
