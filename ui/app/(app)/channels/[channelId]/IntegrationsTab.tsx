import { ActivationsSection } from "./integrations/ActivationsSection";
import { BindingsSection } from "./integrations/BindingsSection";

export function IntegrationsTab({
  channelId,
  workspaceEnabled,
}: {
  channelId: string;
  workspaceEnabled: boolean;
}) {
  return (
    <>
      <ActivationsSection
        channelId={channelId}
        workspaceEnabled={workspaceEnabled}
      />
      <BindingsSection channelId={channelId} />
    </>
  );
}
