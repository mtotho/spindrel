export const CHAT_INLINE_IMAGE_MAX_BYTES = 8 * 1024 * 1024;
export const CHANNEL_DATA_UPLOAD_MAX_BYTES = 1024 * 1024 * 1024;

export type ComposerAttachmentRoute = "inline_image" | "channel_data" | "rejected";

export interface AttachmentRouteDecision {
  route: ComposerAttachmentRoute;
  reason: string;
}

export function formatFileSize(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return "0 B";
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let idx = 0;
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024;
    idx += 1;
  }
  const precision = value >= 10 || idx === 0 ? 1 : 2;
  return `${value.toFixed(precision).replace(/\.0+$/, "").replace(/(\.\d*[1-9])0+$/, "$1")} ${units[idx]}`;
}

export function decideAttachmentRoute(file: Pick<File, "type" | "size">): AttachmentRouteDecision {
  if (file.size > CHANNEL_DATA_UPLOAD_MAX_BYTES) {
    return {
      route: "rejected",
      reason: `File is larger than the ${formatFileSize(CHANNEL_DATA_UPLOAD_MAX_BYTES)} channel upload limit.`,
    };
  }

  if (file.type.startsWith("image/") && file.size <= CHAT_INLINE_IMAGE_MAX_BYTES) {
    return {
      route: "inline_image",
      reason: "Will be sent to the agent as an image.",
    };
  }

  if (file.type.startsWith("image/")) {
    return {
      route: "channel_data",
      reason: `Image is larger than ${formatFileSize(CHAT_INLINE_IMAGE_MAX_BYTES)} and will be uploaded to channel data.`,
    };
  }

  return {
    route: "channel_data",
    reason: "Will be uploaded to channel data.",
  };
}

export function routeLabel(route: ComposerAttachmentRoute): string {
  if (route === "inline_image") return "send to agent";
  if (route === "channel_data") return "channel data";
  return "not added";
}
