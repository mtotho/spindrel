export type HashTabHistoryMode = "push" | "replace";

export interface HashTabHistoryWriter {
  pushState(data: unknown, unused: string, url?: string | URL | null): void;
  replaceState(data: unknown, unused: string, url?: string | URL | null): void;
}

export function buildHashTabUrl(pathname: string, search: string, nextTab: string): string {
  return `${pathname}${search}#${encodeURIComponent(nextTab)}`;
}

export function writeHashTabHistory(
  history: HashTabHistoryWriter,
  pathname: string,
  search: string,
  nextTab: string,
  mode: HashTabHistoryMode = "replace",
): string {
  const url = buildHashTabUrl(pathname, search, nextTab);
  if (mode === "push") {
    history.pushState(null, "", url);
  } else {
    history.replaceState(null, "", url);
  }
  return url;
}
