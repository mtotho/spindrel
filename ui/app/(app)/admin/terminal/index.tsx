import { Suspense, lazy } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { Spinner } from "@/src/components/shared/Spinner";

const TerminalPanel = lazy(() =>
  import("@/src/components/terminal/TerminalPanel").then((m) => ({ default: m.TerminalPanel })),
);

export default function AdminTerminalScreen() {
  const [params] = useSearchParams();
  const cwd = params.get("cwd") || undefined;
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-surface">
      <PageHeader
        variant="list"
        title="Terminal"
        subtitle="Shell into the Spindrel container as the spindrel user — admin-only"
      />
      <div className="relative flex min-h-0 flex-1 flex-col">
        <Suspense
          fallback={
            <div className="flex flex-1 items-center justify-center bg-[#0a0d12]">
              <Spinner />
            </div>
          }
        >
          <TerminalPanel cwd={cwd} />
        </Suspense>
      </div>
    </div>
  );
}
