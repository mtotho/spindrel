import { Section } from "@/src/components/shared/FormControls";
import { IndexingOverview } from "./IndexingOverview";
import { WriteProtection } from "./WriteProtection";

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------
export interface IndexingTabProps {
  workspaceId: string;
  writeProtectedPaths: string[];
  setWriteProtectedPaths: (v: string[]) => void;
}

// ---------------------------------------------------------------------------
// Indexing tab: overview + write protection
// ---------------------------------------------------------------------------
export function IndexingTab({ workspaceId, writeProtectedPaths, setWriteProtectedPaths }: IndexingTabProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Section
        title="Indexing Overview"
        description="Resolved indexing configuration for each bot. Overridden values are highlighted."
      >
        <IndexingOverview workspaceId={workspaceId} />
      </Section>

      <Section title="Write Protection" description="Prevent bots from writing to specific directories in the workspace.">
        <WriteProtection paths={writeProtectedPaths} onChange={setWriteProtectedPaths} />
      </Section>
    </div>
  );
}
