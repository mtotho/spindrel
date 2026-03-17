/**
 * Audio recording module — captures audio via the shared audio-pipeline
 * (VoiceProcessor). Works in the background without foregrounding the app.
 *
 * Silence detection uses adaptive calibration: the noise floor is sampled
 * from the first ~600ms of audio, then speech/silence is detected relative
 * to it.
 */

import * as FileSystem from "expo-file-system";
import {
  startRecordingPipeline,
  stopRecordingPipeline,
  cancelRecording as cancelPipelineRecording,
  type RecordingResult,
} from "./audio-pipeline";

// ─── Silence detection tuning ────────────────────────────────────────

const CALIBRATION_SAMPLES = 3;
const CALIBRATION_CEILING_DB = -30;
const SPEECH_MARGIN_DB = 8;
const SILENCE_MARGIN_DB = 6;
const SILENCE_DURATION_MS = 900;
const MAX_DURATION_MS = 30000;
const MAX_AFTER_SPEECH_MS = 10000;
const METERING_INTERVAL_MS = 200;

let silenceTimer: ReturnType<typeof setTimeout> | null = null;
let maxTimer: ReturnType<typeof setTimeout> | null = null;
let speechTimer: ReturnType<typeof setTimeout> | null = null;
let isActive = false;

export type RecordingStatusCallback = (status: {
  isRecording: boolean;
  durationMs: number;
  metering?: number;
}) => void;

/**
 * Start recording. Resolves when recording stops (silence, max duration, or manual stop).
 * - When localStt is false: resolves with WAV file URI (string).
 * - When localStt is true: resolves with { transcript: string } from Cheetah (no WAV).
 *
 * @param onStatus Optional callback for metering updates
 * @param preserveRingBuffer If true, prepend ring buffer (or feed to Cheetah when localStt)
 * @param trimStartMs When preserveRingBuffer is true, trim this many ms from the start
 * @param localStt When true, stream frames to Cheetah and return transcript instead of URI
 */
export async function startRecording(
  onStatus?: RecordingStatusCallback,
  preserveRingBuffer = false,
  trimStartMs?: number,
  localStt = false,
): Promise<RecordingResult> {
  if (isActive) return null;
  isActive = true;

  const calibrationReadings: number[] = [];
  let noiseFloor = -40;
  let speechThreshold = -32;
  let silenceThreshold = -36;
  let calibrated = false;
  let heardSpeech = false;
  let startTime = Date.now();
  let lastMeterTime = 0;
  let finished = false;

  let resolveOuter: (result: RecordingResult) => void;
  const outerPromise = new Promise<RecordingResult>((resolve) => {
    resolveOuter = resolve;
  });

  const finish = async () => {
    if (finished) return;
    finished = true;
    cleanup();
    await stopRecordingPipeline();
  };

  maxTimer = setTimeout(finish, MAX_DURATION_MS);

  const meterCb = (rmsDb: number) => {
    if (finished) return;

    const now = Date.now();
    if (now - lastMeterTime < METERING_INTERVAL_MS) return;
    lastMeterTime = now;

    onStatus?.({
      isRecording: true,
      durationMs: now - startTime,
      metering: rmsDb,
    });

    // Calibration phase
    if (!calibrated) {
      calibrationReadings.push(Math.min(rmsDb, CALIBRATION_CEILING_DB));
      if (rmsDb > CALIBRATION_CEILING_DB + SPEECH_MARGIN_DB) {
        heardSpeech = true;
      }
      if (calibrationReadings.length >= CALIBRATION_SAMPLES) {
        calibrated = true;
        noiseFloor = calibrationReadings.reduce((a, b) => a + b, 0) / calibrationReadings.length;
        speechThreshold = noiseFloor + SPEECH_MARGIN_DB;
        silenceThreshold = noiseFloor + SILENCE_MARGIN_DB;
      }
      return;
    }

    if (rmsDb > speechThreshold) {
      heardSpeech = true;
      if (silenceTimer) {
        clearTimeout(silenceTimer);
        silenceTimer = null;
      }
      if (!speechTimer) {
        speechTimer = setTimeout(finish, MAX_AFTER_SPEECH_MS);
      }
    } else if (heardSpeech && rmsDb <= silenceThreshold && !silenceTimer) {
      silenceTimer = setTimeout(finish, SILENCE_DURATION_MS);
    }
  };

  startRecordingPipeline(meterCb, preserveRingBuffer, trimStartMs, localStt)
    .then((result) => {
      isActive = false;
      resolveOuter!(result);
    })
    .catch((err) => {
      isActive = false;
      console.error("Recording pipeline error:", err);
      resolveOuter!(null);
    });

  return outerPromise;
}

export async function stopRecording(): Promise<void> {
  if (!isActive) return;
  cleanup();
  cancelPipelineRecording();
  isActive = false;
}

function cleanup() {
  if (silenceTimer) {
    clearTimeout(silenceTimer);
    silenceTimer = null;
  }
  if (maxTimer) {
    clearTimeout(maxTimer);
    maxTimer = null;
  }
  if (speechTimer) {
    clearTimeout(speechTimer);
    speechTimer = null;
  }
}

// ─── File reading utilities (unchanged) ──────────────────────────────

export interface AudioFile {
  data: ArrayBuffer;
  mimeType: string;
}

/**
 * Read a recorded audio file and return its raw bytes + MIME type.
 */
export async function readAudioFile(uri: string): Promise<AudioFile> {
  const base64 = await FileSystem.readAsStringAsync(uri, {
    encoding: FileSystem.EncodingType.Base64,
  });

  const binaryStr = atob(base64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }

  if (bytes.length < 100) {
    throw new Error("Audio file is too small — recording may have failed");
  }

  const mimeType = detectMimeType(bytes);
  return { data: bytes.buffer, mimeType };
}

/**
 * Read a recorded audio file and return its base64-encoded content + format.
 */
export async function readAudioFileBase64(uri: string): Promise<{ base64: string; format: string }> {
  const base64 = await FileSystem.readAsStringAsync(uri, {
    encoding: FileSystem.EncodingType.Base64,
  });

  if (base64.length < 100) {
    throw new Error("Audio file is too small — recording may have failed");
  }

  const binaryStr = atob(base64);
  const bytes = new Uint8Array(Math.min(binaryStr.length, 12));
  for (let i = 0; i < bytes.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }

  const mime = detectMimeType(bytes);
  const format = mimeToFormat(mime);
  return { base64, format };
}

function mimeToFormat(mime: string): string {
  switch (mime) {
    case "audio/wav": return "wav";
    case "audio/mp4": return "m4a";
    case "audio/webm": return "webm";
    case "audio/mpeg": return "mp3";
    case "audio/ogg": return "ogg";
    default: return "wav";
  }
}

function detectMimeType(bytes: Uint8Array): string {
  const header = String.fromCharCode(...bytes.slice(0, 12));
  if (header.startsWith("RIFF") && header.slice(8, 12) === "WAVE") return "audio/wav";
  if (header.slice(4, 8) === "ftyp") return "audio/mp4";
  if (bytes[0] === 0x1A && bytes[1] === 0x45 && bytes[2] === 0xDF && bytes[3] === 0xA3) return "audio/webm";
  if (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0) return "audio/mpeg";
  if (header.startsWith("OggS")) return "audio/ogg";
  return "audio/wav";
}
