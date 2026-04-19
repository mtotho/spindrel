/**
 * Attachment rendering for chat messages -- images and file download links.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useState } from "react";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import type { AttachmentBrief } from "../../types/api";

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

export function AttachmentImages({ attachments }: { attachments: AttachmentBrief[] }) {
  const serverUrl = useAuthStore((s) => s.serverUrl);
  const token = getAuthToken();
  const images = attachments.filter(
    (a) => a.type === "image" && a.has_file_data
  );
  const files = attachments.filter(
    (a) => a.type !== "image" || !a.has_file_data
  );

  if (images.length === 0 && files.length === 0) return null;

  return (
    <div className="mt-2 flex flex-col gap-2">
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
          <a
            key={f.id}
            href={href}
            download={f.filename}
            target="_blank"
            rel="noopener noreferrer"
            className="flex flex-row items-center gap-2 text-[13px] text-accent no-underline cursor-pointer"
          >
            <span className="text-sm">📎</span>
            <span className="underline">{f.filename}</span>
            <span className="text-text-dim">
              ({(f.size_bytes / 1024).toFixed(1)} KB)
            </span>
          </a>
        );
      })}
    </div>
  );
}
