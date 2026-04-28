import { useCallback, useMemo, useState } from "react";
import { useDraftsStore, type DraftFile } from "../../stores/drafts";

export interface PendingFile {
  file: File;
  preview?: string;
  base64: string;
}

type PendingFilesUpdater = PendingFile[] | ((prev: PendingFile[]) => PendingFile[]);

/** Rebuild PendingFile objects from serialized DraftFiles (restores File + preview). */
function draftFilesToPending(draftFiles: DraftFile[]): PendingFile[] {
  return draftFiles.map((df) => {
    const byteString = atob(df.base64);
    const bytes = new Uint8Array(byteString.length);
    for (let i = 0; i < byteString.length; i++) bytes[i] = byteString.charCodeAt(i);
    const file = new File([bytes], df.name, { type: df.type });
    const preview = df.type.startsWith("image/") ? `data:${df.type};base64,${df.base64}` : undefined;
    return { file, base64: df.base64, preview };
  });
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

export function useComposerDraftFiles(channelId: string | undefined) {
  const draft = useDraftsStore((s) => channelId ? s.getDraft(channelId) : null);
  const setDraftText = useDraftsStore((s) => s.setDraftText);
  const setDraftFiles = useDraftsStore((s) => s.setDraftFiles);
  const clearDraft = useDraftsStore((s) => s.clearDraft);

  const [localText, setLocalText] = useState("");
  const [localFiles, setLocalFiles] = useState<PendingFile[]>([]);

  const text = draft?.text ?? localText;
  const setText = useCallback((nextText: string) => {
    if (channelId) setDraftText(channelId, nextText);
    else setLocalText(nextText);
  }, [channelId, setDraftText]);

  const pendingFiles = useMemo(
    () => draft?.files.length ? draftFilesToPending(draft.files) : localFiles,
    [draft?.files, localFiles],
  );

  const setPendingFiles = useCallback((updater: PendingFilesUpdater) => {
    const newFiles = typeof updater === "function" ? updater(pendingFiles) : updater;
    if (channelId) {
      setDraftFiles(channelId, newFiles.map((pf) => ({
        name: pf.file.name,
        type: pf.file.type,
        size: pf.file.size,
        base64: pf.base64,
      })));
    } else {
      setLocalFiles(newFiles);
    }
  }, [channelId, pendingFiles, setDraftFiles]);

  const clear = useCallback(() => {
    if (channelId) clearDraft(channelId);
    else {
      setLocalText("");
      setLocalFiles([]);
    }
  }, [channelId, clearDraft]);

  const handleFileSelect = useCallback(async (files: FileList | null) => {
    if (!files) return;
    const newFiles: PendingFile[] = [];
    for (const file of Array.from(files)) {
      const base64 = await fileToBase64(file);
      const preview = file.type.startsWith("image/")
        ? URL.createObjectURL(file)
        : undefined;
      newFiles.push({ file, preview, base64 });
    }
    setPendingFiles((prev) => [...prev, ...newFiles]);
  }, [setPendingFiles]);

  const removeFile = useCallback((idx: number) => {
    setPendingFiles((prev) => {
      const next = [...prev];
      if (next[idx]?.preview) URL.revokeObjectURL(next[idx].preview);
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
