import type { ChannelSettings } from "@/src/types/api";

import {
  ChannelTabSections,
  AgentTabSections,
  PresentationTabSections,
  AutomationTabSections,
} from "./ChannelSettingsSections";

export function GeneralTab({
  form,
  patch,
  bots,
  settings,
  workspaceId,
  channelId,
}: {
  form: Partial<ChannelSettings>;
  patch: <K extends keyof ChannelSettings>(key: K, value: ChannelSettings[K]) => void;
  bots: any[] | undefined;
  settings: ChannelSettings;
  workspaceId?: string | null;
  channelId: string;
}) {
  return (
    <>
      <ChannelTabSections form={form} patch={patch} channelId={channelId} settings={settings} />
      <AgentTabSections
        form={form}
        patch={patch}
        bots={bots}
        settings={settings}
        workspaceId={workspaceId}
        channelId={channelId}
      />
      <PresentationTabSections form={form} patch={patch} channelId={channelId} />
      <AutomationTabSections form={form} patch={patch} />
    </>
  );
}
