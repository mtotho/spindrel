import { useSearchParams } from "react-router-dom";

import { WidgetLibraryTab } from "@/app/(app)/admin/tools/library/WidgetLibraryTab";

export function LibraryTab() {
  const [searchParams] = useSearchParams();
  const initialToolFilter = searchParams.get("tool") ?? "";
  return <WidgetLibraryTab initialToolFilter={initialToolFilter} />;
}
