import { PageHeader } from "@/src/components/layout/PageHeader";

export function PlaceholderPage({ title, message = "Coming soon" }: { title: string; message?: string }) {
  return (
    <div className="flex-1 flex flex-col bg-surface overflow-hidden">
      <PageHeader variant="list" title={title} />
      <div className="p-6">
        <span className="text-text-muted text-sm">{message}</span>
      </div>
    </div>
  );
}
