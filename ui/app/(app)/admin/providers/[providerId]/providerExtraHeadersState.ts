export type HeaderRow = { key: string; value: string };

export function rowsFromMap(map: Record<string, string> | undefined | null): HeaderRow[] {
  if (!map) return [];
  return Object.entries(map).map(([key, value]) => ({ key, value: String(value) }));
}

export function mapFromRows(rows: HeaderRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const row of rows) {
    const key = row.key.trim();
    if (!key) continue;
    out[key] = row.value;
  }
  return out;
}

export function shouldSyncRows(
  currentRows: HeaderRow[],
  incomingMap: Record<string, string> | undefined | null
): boolean {
  const nextRows = rowsFromMap(incomingMap);
  if (currentRows.length !== nextRows.length) return true;
  return currentRows.some(
    (row, index) =>
      row.key !== nextRows[index]?.key || row.value !== nextRows[index]?.value
  );
}

export function shouldEmitMap(
  initialMap: Record<string, string> | undefined | null,
  nextMap: Record<string, string>
): boolean {
  const prev = initialMap ?? {};
  const prevKeys = Object.keys(prev);
  const nextKeys = Object.keys(nextMap);

  if (prevKeys.length !== nextKeys.length) return true;
  return prevKeys.some((key) => prev[key] !== nextMap[key]);
}
