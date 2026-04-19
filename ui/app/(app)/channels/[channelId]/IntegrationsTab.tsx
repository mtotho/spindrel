import { BindingsSection } from "./integrations/BindingsSection";

export function IntegrationsTab({ channelId }: { channelId: string }) {
  return <BindingsSection channelId={channelId} />;
}
