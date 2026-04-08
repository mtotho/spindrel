import { BindingsSection } from "./integrations/BindingsSection";

export function IntegrationsTab({
  channelId,
  workspaceEnabled,
}: {
  channelId: string;
  workspaceEnabled: boolean;
}) {
  return <BindingsSection channelId={channelId} />;
}
