import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHeader } from "@/src/components/layout/PageHeader";
import { CommandCenter } from "@/src/components/command-center/CommandCenter";

export default function HubCommandCenterPage() {
  const [searchParams] = useSearchParams();
  const requestedItemId = searchParams.get("item");
  const [selectedId, setSelectedId] = useState<string | null>(requestedItemId);

  useEffect(() => {
    setSelectedId(requestedItemId);
  }, [requestedItemId]);

  return (
    <div className="flex h-full min-h-0 flex-col bg-surface">
      <PageHeader
        variant="detail"
        parentLabel="Hub"
        title="Mission Control"
        subtitle="Missions, bot lanes, progress, and traceable runs"
        backTo="/"
        chrome="flow"
        showMenuWithBack
      />
      <main className="min-h-0 flex-1 px-2 pb-2 md:px-4 md:pb-4">
        <div className="mx-auto flex h-full max-w-6xl flex-col overflow-hidden rounded-md bg-surface-raised/55">
          <CommandCenter initialItemId={selectedId} />
        </div>
      </main>
    </div>
  );
}
