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
        chrome="flow"
        showMenuWithBack
      />
      <main className="min-h-0 flex-1 overflow-auto px-2 pb-2 md:px-4 md:pb-4">
        <div className="mx-auto max-w-5xl rounded-md bg-surface-raised/55 p-3">
          <BloatStationContent />
        </div>
      </main>
    </div>
  );
}
