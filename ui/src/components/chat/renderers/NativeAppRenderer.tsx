import { renderNativeWidget } from "./nativeApps/registry";
import type { NativeAppRendererProps } from "./nativeApps/shared";

export function NativeAppRenderer(props: NativeAppRendererProps) {
  return <>{renderNativeWidget(props)}</>;
}
