/**
 * Attachment rendering for chat messages -- images and file download links.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useState } from "react";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import type { AttachmentBrief } from "../../types/api";

interface LocalAttachmentReceipt {
  id?: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  route?: string;
  preview_url?: string;
  path?: string;
}

interface WorkspaceUploadReceipt {
  filename: string;
  mime_type?: string;
  size_bytes: number;
  path: string;
}

function AttachmentImage({ src, alt }: { src: string; alt: string }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <a href={src} target="_blank" rel="noopener noreferrer" className="self-start">
      <div
        className="max-w-full overflow-hidden rounded-lg transition-[min-height] duration-150 ease-out"
        style={{
          minHeight: loaded ? undefined : 200,
          background: loaded ? "transparent" : "rgb(var(--color-surface-raised))",
        }}
      >
        <img
          src={src}
          alt={alt}
          loading="lazy"
          decoding="async"
          onLoad={() => setLoaded(true)}
          className="block max-w-full rounded-lg transition-opacity duration-150 ease-in"
          style={{
            maxHeight: 360,
            opacity: loaded ? 1 : 0,
          }}
        />
      </div>
    </a>
  );
}

function FileReceiptRow({
  filename,
  sizeBytes,
  href,
  detail,
}: {
  filename: string;
  sizeBytes: number;
  href?: string;
  detail?: string;
}) {
  const body = (
    <>
      <span className="rounded bg-surface-overlay px-1.5 py-0.5 text-[10px] uppercase tracking-[0.08em] text-text-dim">file</span>
      <span className="min-w-0 truncate underline">{filename}</span>
      <span className="shrink-0 text-text-dim">
        ({(sizeBytes / 1024).toFixed(1)} KB)
      </span>
      {detail && <span className="min-w-0 truncate text-text-dim">{detail}</span>}
    </>
  );

  if (href) {
    return (
      <a
        href={href}
        download={filename}
        target="_blank"
        rel="noopener noreferrer"
        className="flex max-w-full flex-row items-center gap-2 text-[13px] text-accent no-underline cursor-pointer"
      >
        {body}
      </a>
    );
  }

  return (
    <div className="flex max-w-full flex-row items-center gap-2 text-[13px] text-text-muted">
      {body}
    </div>
  );
}

export function AttachmentImages({
  attachments,
  localAttachments,
  workspaceUploads,
  channelId,
}: {
  attachments: AttachmentBrief[];
  localAttachments?: LocalAttachmentReceipt[];
  workspaceUploads?: WorkspaceUploadReceipt[];
  channelId?: string;
}) {
  const serverUrl = useAuthStore((s) => s.serverUrl);
  const token = getAuthToken();
  const images = attachments.filter(
    (a) => a.type === "image" && a.has_file_data
  );
  const files = attachments.filter(
    (a) => a.type !== "image" || !a.has_file_data
  );

  const optimistic = localAttachments ?? [];
  const uploaded = (workspaceUploads ?? []).filter((item) => (
    !optimistic.some((local) => local.path && local.path === item.path)
  ));

  if (images.length === 0 && files.length === 0 && optimistic.length === 0 && uploaded.length === 0) return null;

  return (
    <div className="mt-2 flex flex-col gap-2">
      {optimistic.map((item) => {
        if (item.preview_url && item.mime_type.startsWith("image/")) {
          return (
            <AttachmentImage
              key={item.id || item.preview_url}
              src={item.preview_url}
              alt={item.filename}
            />
          );
        }
        const href = item.path && channelId
          ? `${serverUrl}/api/v1/channels/${channelId}/workspace/files/raw?path=${encodeURIComponent(item.path)}${token ? `&token=${token}` : ""}`
          : undefined;
        return (
          <FileReceiptRow
            key={item.id || item.path || item.filename}
            filename={item.filename}
            sizeBytes={item.size_bytes}
            href={href}
            detail={item.path ? item.path : undefined}
          />
        );
      })}
      {images.map((img) => {
        const url = `${serverUrl}/api/v1/attachments/${img.id}/file${token ? `?token=${token}` : ""}`;
        return (
          <AttachmentImage
            key={img.id}
            src={url}
            alt={img.description || img.filename}
          />
        );
      })}
      {files.map((f) => {
        // Always generate a download link -- let the server return 404 if data was purged
        const href = `${serverUrl}/api/v1/attachments/${f.id}/file${token ? `?token=${token}` : ""}`;
        return (
          <FileReceiptRow
            key={f.id}
            filename={f.filename}
            sizeBytes={f.size_bytes}
            href={href}
          />
        );
      })}
      {uploaded.map((item) => {
        const href = channelId
          ? `${serverUrl}/api/v1/channels/${channelId}/workspace/files/raw?path=${encodeURIComponent(item.path)}${token ? `&token=${token}` : ""}`
          : undefined;
        return (
          <FileReceiptRow
            key={item.path}
            filename={item.filename}
            sizeBytes={item.size_bytes}
            href={href}
            detail={item.path}
          />
        );
      })}
    </div>
  );
}
