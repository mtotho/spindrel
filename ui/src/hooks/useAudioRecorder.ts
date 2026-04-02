/**
 * Web-only hook for recording audio via MediaRecorder API.
 * Returns base64-encoded audio suitable for the ChatRequest audio_data field.
 */
import { useState, useRef, useCallback, useEffect } from "react";

interface RecordingResult {
  base64: string;
  format: string;
  durationMs: number;
}

interface UseAudioRecorderReturn {
  isRecording: boolean;
  durationMs: number;
  error: string | null;
  startRecording: () => Promise<void>;
  stopRecording: () => Promise<RecordingResult | null>;
  cancelRecording: () => void;
}

/** Preferred MIME types in order; first supported wins. */
const MIME_CANDIDATES = [
  "audio/webm;codecs=opus",
  "audio/webm",
  "audio/ogg;codecs=opus",
  "audio/mp4",
];

function pickMimeType(): string {
  if (typeof MediaRecorder === "undefined") return "";
  for (const mime of MIME_CANDIDATES) {
    if (MediaRecorder.isTypeSupported(mime)) return mime;
  }
  return "";
}

/** Extract a simple format string from a MIME type (e.g. "audio/webm;codecs=opus" → "webm"). */
function mimeToFormat(mime: string): string {
  const base = mime.split(";")[0]; // "audio/webm"
  return base.split("/")[1] || "webm";
}

export function useAudioRecorder(): UseAudioRecorderReturn {
  const [isRecording, setIsRecording] = useState(false);
  const [durationMs, setDurationMs] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef(0);
  const resolveRef = useRef<((result: RecordingResult | null) => void) | null>(null);
  const mimeRef = useRef("");

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== "inactive") {
        mediaRecorderRef.current.stop();
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((t) => t.stop());
      }
    };
  }, []);

  const releaseResources = useCallback(() => {
    if (timerRef.current) {
      clearInterval(timerRef.current);
      timerRef.current = null;
    }
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
    mediaRecorderRef.current = null;
    chunksRef.current = [];
    setIsRecording(false);
    setDurationMs(0);
  }, []);

  const startRecording = useCallback(async () => {
    setError(null);

    if (typeof MediaRecorder === "undefined") {
      setError("Audio recording is not supported in this browser");
      return;
    }

    const mime = pickMimeType();
    if (!mime) {
      setError("No supported audio format found");
      return;
    }
    mimeRef.current = mime;

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      streamRef.current = stream;

      const recorder = new MediaRecorder(stream, { mimeType: mime });
      mediaRecorderRef.current = recorder;
      chunksRef.current = [];

      recorder.ondataavailable = (e) => {
        if (e.data.size > 0) chunksRef.current.push(e.data);
      };

      recorder.start(100); // collect chunks every 100ms
      startTimeRef.current = Date.now();
      setIsRecording(true);

      timerRef.current = setInterval(() => {
        setDurationMs(Date.now() - startTimeRef.current);
      }, 100);
    } catch (err: any) {
      if (err.name === "NotAllowedError") {
        setError("Microphone permission denied");
      } else if (err.name === "NotFoundError") {
        setError("No microphone found");
      } else {
        setError("Could not access microphone");
      }
      releaseResources();
    }
  }, [releaseResources]);

  const stopRecording = useCallback((): Promise<RecordingResult | null> => {
    return new Promise((resolve) => {
      const recorder = mediaRecorderRef.current;
      if (!recorder || recorder.state === "inactive") {
        releaseResources();
        resolve(null);
        return;
      }

      resolveRef.current = resolve;

      recorder.onstop = async () => {
        const elapsed = Date.now() - startTimeRef.current;
        const blob = new Blob(chunksRef.current, { type: mimeRef.current });
        releaseResources();

        if (blob.size === 0) {
          resolveRef.current?.(null);
          resolveRef.current = null;
          return;
        }

        const buffer = await blob.arrayBuffer();
        const bytes = new Uint8Array(buffer);
        let binary = "";
        for (let i = 0; i < bytes.length; i++) {
          binary += String.fromCharCode(bytes[i]);
        }
        const base64 = btoa(binary);

        const result: RecordingResult = {
          base64,
          format: mimeToFormat(mimeRef.current),
          durationMs: elapsed,
        };
        resolveRef.current?.(result);
        resolveRef.current = null;
      };

      recorder.stop();
    });
  }, [releaseResources]);

  const cancelRecording = useCallback(() => {
    const recorder = mediaRecorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.onstop = null;
      recorder.stop();
    }
    releaseResources();
    if (resolveRef.current) {
      resolveRef.current(null);
      resolveRef.current = null;
    }
  }, [releaseResources]);

  return {
    isRecording,
    durationMs,
    error,
    startRecording,
    stopRecording,
    cancelRecording,
  };
}
