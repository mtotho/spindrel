import type { ChatAttachment, ChatFileMetadata } from "@/src/types/api";
import type { PendingFile } from "./MessageInput";

export interface ChatAttachmentPayload {
  attachments?: ChatAttachment[];
  file_metadata?: ChatFileMetadata[];
  workspace_uploads?: Array<{
    filename: string;
    mime_type: string;
    size_bytes: number;
    path: string;
  }>;
}

export function buildChatAttachmentPayload(files?: PendingFile[]): ChatAttachmentPayload {
  if (!files?.length) return {};

  const attachments: ChatAttachment[] = [];
  const fileMetadata: ChatFileMetadata[] = [];
  const workspaceUploads: ChatAttachmentPayload["workspace_uploads"] = [];

  for (const pending of files) {
    const mimeType = pending.file.type || "application/octet-stream";
    if (pending.route === "inline_image" && mimeType.startsWith("image/") && pending.base64) {
      attachments.push({
        type: "image",
        content: pending.base64,
        mime_type: mimeType,
        name: pending.file.name,
      });
      fileMetadata.push({
        filename: pending.file.name,
        mime_type: mimeType,
        size_bytes: pending.file.size,
        file_data: pending.base64,
      });
      continue;
    }
    if (pending.route === "channel_data" && pending.upload?.path) {
      workspaceUploads.push({
        filename: pending.file.name,
        mime_type: mimeType,
        size_bytes: pending.file.size,
        path: pending.upload.path,
      });
    }
  }

  return {
    ...(attachments.length ? { attachments } : {}),
    ...(fileMetadata.length ? { file_metadata: fileMetadata } : {}),
    ...(workspaceUploads.length ? { workspace_uploads: workspaceUploads } : {}),
  };
}
