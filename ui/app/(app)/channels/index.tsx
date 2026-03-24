import { Redirect } from "expo-router";

// Channel list is the home screen — redirect there
export default function ChannelsIndex() {
  return <Redirect href="/(app)" />;
}
