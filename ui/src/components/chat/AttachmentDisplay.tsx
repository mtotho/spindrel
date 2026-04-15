/**
 * Attachment rendering for chat messages -- images and file download links.
 *
 * Extracted from MessageBubble.tsx.
 */

import { useState } from "react";
import { useAuthStore, getAuthToken } from "../../stores/auth";
import type { ThemeTokens } from "../../theme/tokens";
import type { AttachmentBrief } from "../../types/api";

function AttachmentImage({ src, alt, t }: { src: string; alt: string; t: ThemeTokens }) {
  const [loaded, setLoaded] = useState(false);
  return (
    <a href={src} target="_blank" rel="noopener noreferrer">
      <div style={{
        minHeight: loaded ? undefined : 200,
        maxWidth: "100%",
        borderRadius: 8,
        overflow: "hidden",
        background: loaded ? "transparent" : t.surfaceRaised,
        transition: "min-height 0.15s ease-out",
      }}>
        <img
          src={src}
          alt={alt}
          onLoad={() => setLoaded(true)}
          style={{
            maxWidth: "100%",
            maxHeight: 360,
            borderRadius: 8,
            display: "block",
            opacity: loaded ? 1 : 0,
            transition: "opacity 0.15s ease-in",
          }}
        />
      </div>
    </a>
  );
}

export function AttachmentImages({ attachments, t }: { attachments: AttachmentBrief[]; t: ThemeTokens }) {
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
    <div style={{ marginTop: 8, display: "flex", flexDirection: "column", gap: 8 }}>
      {images.map((img) => {
        const url = `${serverUrl}/api/v1/attachments/${img.id}/file${token ? `?token=${token}` : ""}`;
        return (
          <AttachmentImage
            key={img.id}
            src={url}
            alt={img.description || img.filename}
            t={t}
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
            style={{
              display: "flex", flexDirection: "row",
              alignItems: "center",
              gap: 8,
              fontSize: 13,
              color: t.accent,
              textDecoration: "none",
              cursor: "pointer",
            }}
          >
            <span style={{ fontSize: 14 }}>📎</span>
            <span style={{ textDecoration: "underline" }}>{f.filename}</span>
            <span style={{ color: t.textDim }}>
              ({(f.size_bytes / 1024).toFixed(1)} KB)
            </span>
          </a>
        );
      })}
    </div>
  );
}
