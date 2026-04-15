import { PageHeader } from "@/src/components/layout/PageHeader";

export default function KnowledgeScreen() {
  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title="Knowledge" />
      <div className="p-6">
        <span className="text-text-muted text-sm">Coming soon</span>
      </div>
    </div>
  );
}
