import { PageHeader } from "@/src/components/layout/PageHeader";
import { BloatStationContent } from "@/src/components/spatial-canvas/BloatSatellite";

export default function HubContextBloatPage() {
  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Hub"
        title="Context Bloat"
        subtitle="Unused tools, skills, and estimated prompt weight"
        backTo="/"
      />
      <main className="min-h-0 flex-1 overflow-auto p-3 md:p-4">
        <div className="mx-auto max-w-5xl rounded-md border border-surface-border bg-surface-raised/70 p-3">
          <BloatStationContent />
        </div>
      </main>
    </div>
  );
}

