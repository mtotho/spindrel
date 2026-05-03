/**
 * Attachment rendering for chat messages -- images and file download links.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useEffect, useState } from "react";
import { FileText } from "lucide-react";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import { getApiBase } from "../../api/client";
import type { AttachmentBrief } from "../../types/api";

const TERMINAL_FONT_STACK = "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Monaco, Consolas, monospace";

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

function AttachmentImage({ src, alt, testId }: { src: string; alt: string; testId?: string }) {
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
          data-testid={testId}
          data-attachment-name={alt}
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

function formatAttachmentSize(sizeBytes: number): string {
  if (sizeBytes < 1024) return `${sizeBytes} B`;
  return `${(sizeBytes / 1024).toFixed(1)} KB`;
}

function AttachmentThumbReceipt({
  src,
  filename,
  sizeBytes,
  href,
  detail,
  testId = "chat-attachment-image-local",
  chatMode = "default",
}: {
  src: string;
  filename: string;
  sizeBytes: number;
  href?: string;
  detail?: string;
  testId?: string;
  chatMode?: "default" | "terminal";
}) {
  const isTerminal = chatMode === "terminal";
  useEffect(() => () => {
    if (src.startsWith("blob:")) URL.revokeObjectURL(src);
  }, [src]);
  const body = (
    <>
      <span
        className={[
          "flex shrink-0 items-center justify-center overflow-hidden",
          isTerminal ? "h-9 w-9 rounded-sm border border-border-subtle/30 bg-transparent" : "h-12 w-12 rounded-md bg-surface-overlay/25",
        ].join(" ")}
      >
        <img
          src={src}
          alt={filename}
          data-testid={testId}
          data-attachment-name={filename}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-cover"
        />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] text-text">{filename}</span>
        <span className="mt-0.5 flex min-w-0 flex-row items-center gap-1.5 text-[11px] text-text-dim">
          <span className="shrink-0 uppercase tracking-[0.08em]">{detail ? "data" : "image"}</span>
          <span className="shrink-0">{formatAttachmentSize(sizeBytes)}</span>
          {detail && <span className="min-w-0 truncate">{detail}</span>}
        </span>
      </span>
    </>
  );
  const className = [
    "flex w-full max-w-[520px] flex-row items-center gap-2 no-underline",
    isTerminal
      ? "px-0 py-0.5 text-text-muted"
      : "rounded-md bg-surface-overlay/15 p-1 text-text-muted",
  ].join(" ");
  const style = isTerminal ? { fontFamily: TERMINAL_FONT_STACK } : undefined;

  if (href) {
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" className={className} style={style}>
        {body}
      </a>
    );
  }

  return (
    <div className={className} style={style}>
      {body}
    </div>
  );
}

function FileReceiptRow({
  filename,
  sizeBytes,
  href,
  detail,
  testId = "chat-attachment-receipt",
  chatMode = "default",
}: {
  filename: string;
  sizeBytes: number;
  href?: string;
  detail?: string;
  testId?: string;
  chatMode?: "default" | "terminal";
}) {
  const isTerminal = chatMode === "terminal";
  const body = (
    <>
      <span
        className={[
          "flex shrink-0 items-center justify-center text-text-muted",
          isTerminal ? "h-9 w-9 rounded-sm border border-border-subtle/30" : "h-9 w-9 rounded-md bg-surface-overlay/25",
        ].join(" ")}
      >
        <FileText size={16} />
      </span>
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] text-text">{filename}</span>
        <span className="mt-0.5 flex min-w-0 flex-row items-center gap-1.5 text-[11px] text-text-dim">
          <span className="shrink-0 uppercase tracking-[0.08em]">file</span>
          <span className="shrink-0">{formatAttachmentSize(sizeBytes)}</span>
          {detail && <span className="min-w-0 truncate">{detail}</span>}
        </span>
      </span>
    </>
  );
  const className = [
    "flex w-full max-w-[520px] flex-row items-center gap-2 no-underline",
    isTerminal
      ? "px-0 py-0.5 text-text-muted"
      : "rounded-md bg-surface-overlay/15 px-1.5 py-1 text-text-muted",
  ].join(" ");
  const style = isTerminal ? { fontFamily: TERMINAL_FONT_STACK } : undefined;

  if (href) {
    return (
      <a
        href={href}
        download={filename}
        target="_blank"
        rel="noopener noreferrer"
        data-testid={testId}
        data-attachment-name={filename}
        data-attachment-detail={detail}
        className={className}
        style={style}
      >
        {body}
      </a>
    );
  }

  return (
    <div
      data-testid={testId}
      data-attachment-name={filename}
      data-attachment-detail={detail}
      className={className}
      style={style}
    >
      {body}
    </div>
  );
}

export function AttachmentImages({
  attachments,
  localAttachments,
  workspaceUploads,
  channelId,
  chatMode = "default",
}: {
  attachments: AttachmentBrief[];
  localAttachments?: LocalAttachmentReceipt[];
  workspaceUploads?: WorkspaceUploadReceipt[];
  channelId?: string;
  chatMode?: "default" | "terminal";
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
    <div className={chatMode === "terminal" ? "mt-2 flex max-w-full flex-col gap-1.5" : "mt-2 flex max-w-full flex-col gap-1.5"}>
      {optimistic.map((item) => {
        if (item.mime_type.startsWith("image/")) {
          const fileHref = item.path && channelId
            ? `${getApiBase()}/api/v1/channels/${channelId}/workspace/files/raw?path=${encodeURIComponent(item.path)}${token ? `&token=${token}` : ""}`
            : undefined;
          const previewSrc = item.preview_url ?? fileHref;
          if (!previewSrc) {
            return (
              <FileReceiptRow
                key={item.id || item.path || item.filename}
                filename={item.filename}
                sizeBytes={item.size_bytes}
                href={fileHref}
                detail={item.path ? item.path : undefined}
                testId="chat-attachment-receipt-local"
                chatMode={chatMode}
              />
            );
          }
          return (
            <AttachmentThumbReceipt
              key={item.id || item.path || previewSrc}
              src={previewSrc}
              filename={item.filename}
              sizeBytes={item.size_bytes}
              href={fileHref ?? item.preview_url}
              detail={item.path ? item.path : undefined}
              testId="chat-attachment-image-local"
              chatMode={chatMode}
            />
          );
        }
        const href = item.path && channelId
          ? `${getApiBase()}/api/v1/channels/${channelId}/workspace/files/raw?path=${encodeURIComponent(item.path)}${token ? `&token=${token}` : ""}`
          : undefined;
        return (
          <FileReceiptRow
            key={item.id || item.path || item.filename}
            filename={item.filename}
            sizeBytes={item.size_bytes}
            href={href}
            detail={item.path ? item.path : undefined}
            testId="chat-attachment-receipt-local"
            chatMode={chatMode}
          />
        );
      })}
      {images.map((img) => {
        const url = `${getApiBase()}/api/v1/attachments/${img.id}/file${token ? `?token=${token}` : ""}`;
        if (chatMode === "terminal") {
          return (
            <AttachmentThumbReceipt
              key={img.id}
              src={url}
              filename={img.description || img.filename}
              sizeBytes={img.size_bytes}
              href={url}
              testId="chat-attachment-image-file"
              chatMode={chatMode}
            />
          );
        }
        return (
          <AttachmentImage
            key={img.id}
            src={url}
            alt={img.description || img.filename}
            testId="chat-attachment-image-file"
          />
        );
      })}
      {files.map((f) => {
        // Always generate a download link -- let the server return 404 if data was purged
        const href = `${getApiBase()}/api/v1/attachments/${f.id}/file${token ? `?token=${token}` : ""}`;
        return (
          <FileReceiptRow
            key={f.id}
            filename={f.filename}
            sizeBytes={f.size_bytes}
            href={href}
            testId="chat-attachment-receipt-file"
            chatMode={chatMode}
          />
        );
      })}
      {uploaded.map((item) => {
        const href = channelId
          ? `${getApiBase()}/api/v1/channels/${channelId}/workspace/files/raw?path=${encodeURIComponent(item.path)}${token ? `&token=${token}` : ""}`
          : undefined;
        return (
          <FileReceiptRow
            key={item.path}
            filename={item.filename}
            sizeBytes={item.size_bytes}
            href={href}
            detail={item.path}
            testId="chat-attachment-receipt-workspace"
            chatMode={chatMode}
          />
        );
      })}
    </div>
  );
}
