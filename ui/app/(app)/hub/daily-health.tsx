import { PageHeader } from "@/src/components/layout/PageHeader";
import SummaryPanel from "@/src/components/system-health/SummaryPanel";

export default function HubDailyHealthPage() {
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Hub"
        title="Daily Health"
        subtitle="Deterministic 24h server-error rollup"
        backTo="/"
      />
      <main className="min-h-0 flex-1 p-3 md:p-4">
        <div className="mx-auto flex h-full max-w-5xl flex-col overflow-hidden rounded-md border border-surface-border bg-surface-raised/70">
          <SummaryPanel embedded />
        </div>
      </main>
    </div>
  );
}

