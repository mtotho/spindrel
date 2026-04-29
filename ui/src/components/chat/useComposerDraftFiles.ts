import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { uploadChannelWorkspaceFile, type ChannelWorkspaceUploadResult } from "../../api/hooks/useChannels";
import { useDraftsStore } from "../../stores/drafts";
import { decideAttachmentRoute, type ComposerAttachmentRoute } from "./attachmentRouting";

export interface PendingFile {
  file: File;
  preview?: string;
  id: string;
  route: ComposerAttachmentRoute;
  status: "ready" | "uploading" | "uploaded" | "error" | "rejected";
  reason?: string;
  error?: string;
  base64?: string;
  upload?: ChannelWorkspaceUploadResult;
}

type PendingFilesUpdater = PendingFile[] | ((prev: PendingFile[]) => PendingFile[]);
interface ClearDraftOptions {
  preserveFilePreviews?: boolean;
}

function makeAttachmentId(): string {
  const cryptoObj = globalThis.crypto as Crypto | undefined;
  if (cryptoObj?.randomUUID) return `att-${cryptoObj.randomUUID()}`;
  return `att-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const idx = result.indexOf(",");
      resolve(idx >= 0 ? result.slice(idx + 1) : result);
    };
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function uploadTargetDir(): string {
  return `data/uploads/${new Date().toISOString().slice(0, 10)}`;
}

export function useComposerDraftFiles(channelId: string | undefined) {
  const draft = useDraftsStore((s) => channelId ? s.getDraft(channelId) : null);
  const setDraftText = useDraftsStore((s) => s.setDraftText);
  const clearDraft = useDraftsStore((s) => s.clearDraft);
  const queryClient = useQueryClient();

  const [localText, setLocalText] = useState("");
  const [localFiles, setLocalFiles] = useState<PendingFile[]>([]);
  const localFilesRef = useRef<PendingFile[]>([]);

  const text = draft?.text ?? localText;
  const setText = useCallback((nextText: string) => {
    if (channelId) setDraftText(channelId, nextText);
    else setLocalText(nextText);
  }, [channelId, setDraftText]);

  const pendingFiles = localFiles;

  useEffect(() => {
    localFilesRef.current = localFiles;
  }, [localFiles]);

  const setPendingFiles = useCallback((updater: PendingFilesUpdater) => {
    setLocalFiles((current) => {
      const next = typeof updater === "function" ? updater(current) : updater;
      const nextIds = new Set(next.map((pf) => pf.id));
      for (const pf of current) {
        if (pf.preview && !nextIds.has(pf.id)) URL.revokeObjectURL(pf.preview);
      }
      return next;
    });
  }, []);

  const clear = useCallback((options?: ClearDraftOptions) => {
    if (channelId) clearDraft(channelId);
    else {
      setLocalText("");
    }
    if (options?.preserveFilePreviews) setLocalFiles([]);
    else setPendingFiles([]);
  }, [channelId, clearDraft]);

  const handleFileSelect = useCallback(async (files: FileList | null) => {
    if (!files) return;
    const newFiles: PendingFile[] = [];
    for (const file of Array.from(files)) {
      const decision = decideAttachmentRoute(file);
      const preview = file.type.startsWith("image/")
        ? URL.createObjectURL(file)
        : undefined;
      const pending: PendingFile = {
        id: makeAttachmentId(),
        file,
        preview,
        route: decision.route,
        status: decision.route === "rejected" ? "rejected" : decision.route === "channel_data" ? "uploading" : "ready",
        reason: decision.reason,
      };
      if (decision.route === "inline_image") {
        pending.base64 = await fileToBase64(file);
      }
      if (decision.route === "channel_data" && !channelId) {
        pending.status = "error";
        pending.error = "Channel workspace unavailable.";
      }
      newFiles.push(pending);
    }
    setPendingFiles((prev) => [...prev, ...newFiles]);

    for (const pending of newFiles) {
      if (pending.route !== "channel_data" || pending.status === "error" || !channelId) continue;
      try {
        const upload = await uploadChannelWorkspaceFile(channelId, {
          file: pending.file,
          targetDir: uploadTargetDir(),
        });
        setPendingFiles((prev) => prev.map((pf) => (
          pf.id === pending.id
            ? { ...pf, status: "uploaded", upload }
            : pf
        )));
        queryClient.invalidateQueries({ queryKey: ["channel-workspace-files", channelId] });
      } catch (err) {
        setPendingFiles((prev) => prev.map((pf) => (
          pf.id === pending.id
            ? { ...pf, status: "error", error: err instanceof Error ? err.message : "Upload failed" }
            : pf
        )));
      }
    }
  }, [channelId, queryClient, setPendingFiles]);

  const removeFile = useCallback((idx: number) => {
    setPendingFiles((prev) => {
      const next = [...prev];
      next.splice(idx, 1);
      return next;
    });
  }, [setPendingFiles]);

  const handleImagePaste = useCallback(
    (files: File[]) => {
      const dt = new DataTransfer();
      files.forEach((f) => dt.items.add(f));
      handleFileSelect(dt.files);
    },
    [handleFileSelect],
  );

  useEffect(() => () => {
    for (const pf of localFilesRef.current) {
      if (pf.preview) URL.revokeObjectURL(pf.preview);
    }
  }, []);

  return {
    text,
    setText,
    pendingFiles,
    setPendingFiles,
    clear,
    handleFileSelect,
    removeFile,
    handleImagePaste,
  };
}
