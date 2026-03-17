import { Audio } from "expo-av";
import * as FileSystem from "expo-file-system";

// Android MediaRecorder cannot produce WAV/PCM — use AAC in MP4 container
// which is universally supported. iOS can do real PCM/WAV.
const RECORDING_OPTIONS: Audio.RecordingOptions = {
  android: {
    extension: ".m4a",
    outputFormat: Audio.AndroidOutputFormat.MPEG_4,
    audioEncoder: Audio.AndroidAudioEncoder.AAC,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 64000,
  },
  ios: {
    extension: ".wav",
    outputFormat: Audio.IOSOutputFormat.LINEARPCM,
    audioQuality: Audio.IOSAudioQuality.HIGH,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 256000,
    linearPCMBitDepth: 16,
    linearPCMIsBigEndian: false,
    linearPCMIsFloat: false,
  },
  web: {
    mimeType: "audio/webm",
    bitsPerSecond: 64000,
  },
};

// Adaptive silence detection: calibrate noise floor from the first ~600ms,
// then detect speech/silence relative to it. Calibration readings are
// capped so that early speech doesn't inflate the noise floor.
const CALIBRATION_SAMPLES = 3;
const CALIBRATION_CEILING_DB = -30;
const SPEECH_MARGIN_DB = 8;
const SILENCE_MARGIN_DB = 5;
const SILENCE_DURATION_MS = 1000;
const MAX_DURATION_MS = 30000;
const MAX_AFTER_SPEECH_MS = 10000;
const METERING_INTERVAL_MS = 200;

let currentRecording: Audio.Recording | null = null;
let silenceTimer: ReturnType<typeof setTimeout> | null = null;
let maxTimer: ReturnType<typeof setTimeout> | null = null;
let speechTimer: ReturnType<typeof setTimeout> | null = null;
let meteringInterval: ReturnType<typeof setInterval> | null = null;
let cancelResolve: ((uri: string | null) => void) | null = null;

export type RecordingStatusCallback = (status: {
  isRecording: boolean;
  durationMs: number;
  metering?: number;
}) => void;

export async function requestMicPermission(): Promise<boolean> {
  const { granted } = await Audio.requestPermissionsAsync();
  return granted;
}

/**
 * Start recording audio. Returns a promise that resolves with the
 * file URI when recording stops (via silence detection, max duration,
 * or manual stop).
 */
export async function startRecording(
  onStatus?: RecordingStatusCallback
): Promise<string | null> {
  const granted = await requestMicPermission();
  if (!granted) {
    throw new Error("Microphone permission not granted");
  }

  await Audio.setAudioModeAsync({
    allowsRecordingIOS: true,
    playsInSilentModeIOS: true,
  });

  const recording = new Audio.Recording();
  await recording.prepareToRecordAsync({
    ...RECORDING_OPTIONS,
    isMeteringEnabled: true,
  });
  await recording.startAsync();
  currentRecording = recording;

  const calibrationReadings: number[] = [];
  let noiseFloor = -40;
  let speechThreshold = -32;
  let silenceThreshold = -36;
  let calibrated = false;
  let heardSpeech = false;

  return new Promise<string | null>((resolve) => {
    cancelResolve = resolve;

    const finish = async () => {
      cleanup();
      cancelResolve = null;
      if (!currentRecording) {
        resolve(null);
        return;
      }
      try {
        const status = await currentRecording.getStatusAsync();
        if (status.isRecording) {
          await currentRecording.stopAndUnloadAsync();
        }
        const uri = currentRecording.getURI();
        currentRecording = null;
        await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
        resolve(uri);
      } catch {
        currentRecording = null;
        resolve(null);
      }
    };

    maxTimer = setTimeout(finish, MAX_DURATION_MS);

    meteringInterval = setInterval(async () => {
      if (!currentRecording) return;
      try {
        const status = await currentRecording.getStatusAsync();
        if (!status.isRecording) return;

        const metering = (status as any).metering ?? -160;
        onStatus?.({
          isRecording: true,
          durationMs: status.durationMillis,
          metering,
        });

        // Calibration phase: sample the noise floor from the first readings.
        // Cap readings at CALIBRATION_CEILING_DB so that speech during
        // calibration doesn't inflate the noise floor and break detection.
        if (!calibrated) {
          calibrationReadings.push(Math.min(metering, CALIBRATION_CEILING_DB));
          if (metering > CALIBRATION_CEILING_DB + SPEECH_MARGIN_DB) {
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

        if (metering > speechThreshold) {
          heardSpeech = true;
          if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
          }
          // Cap total recording time after first speech detected
          if (!speechTimer) {
            speechTimer = setTimeout(finish, MAX_AFTER_SPEECH_MS);
          }
        } else if (heardSpeech && metering <= silenceThreshold && !silenceTimer) {
          silenceTimer = setTimeout(finish, SILENCE_DURATION_MS);
        }
      } catch {}
    }, METERING_INTERVAL_MS);
  });
}

export async function stopRecording(): Promise<void> {
  cleanup();
  const pendingResolve = cancelResolve;
  cancelResolve = null;
  if (currentRecording) {
    try {
      const status = await currentRecording.getStatusAsync();
      if (status.isRecording) {
        await currentRecording.stopAndUnloadAsync();
      }
    } catch {}
    currentRecording = null;
    await Audio.setAudioModeAsync({ allowsRecordingIOS: false });
  }
  // Resolve the pending startRecording promise so the pipeline doesn't hang
  pendingResolve?.(null);
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
  if (meteringInterval) {
    clearInterval(meteringInterval);
    meteringInterval = null;
  }
}

export interface AudioFile {
  data: ArrayBuffer;
  mimeType: string;
}

/**
 * Read a recorded audio file and return its raw bytes + MIME type.
 * The server handles decoding (ffmpeg) — no client-side format parsing needed.
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

  // Detect format from file header
  const mimeType = detectMimeType(bytes);
  return { data: bytes.buffer, mimeType };
}

/**
 * Read a recorded audio file and return its base64-encoded content + format
 * string (e.g. "m4a", "wav") suitable for native audio input to the model.
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
    default: return "m4a";
  }
}

function detectMimeType(bytes: Uint8Array): string {
  const header = String.fromCharCode(...bytes.slice(0, 12));
  if (header.startsWith("RIFF") && header.slice(8, 12) === "WAVE") return "audio/wav";
  if (header.slice(4, 8) === "ftyp") return "audio/mp4";
  if (bytes[0] === 0x1A && bytes[1] === 0x45 && bytes[2] === 0xDF && bytes[3] === 0xA3) return "audio/webm";
  if (bytes[0] === 0xFF && (bytes[1] & 0xE0) === 0xE0) return "audio/mpeg";
  if (header.startsWith("OggS")) return "audio/ogg";
  // Default for Android's various container formats
  return "audio/mp4";
}
