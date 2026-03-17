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

const SILENCE_THRESHOLD_DB = -35;
const SILENCE_DURATION_MS = 2000;
const MAX_DURATION_MS = 30000;
const METERING_INTERVAL_MS = 200;

let currentRecording: Audio.Recording | null = null;
let silenceTimer: ReturnType<typeof setTimeout> | null = null;
let maxTimer: ReturnType<typeof setTimeout> | null = null;
let meteringInterval: ReturnType<typeof setInterval> | null = null;

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

  let heardSpeech = false;

  return new Promise<string | null>((resolve) => {
    const finish = async () => {
      cleanup();
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

        if (metering > SILENCE_THRESHOLD_DB) {
          heardSpeech = true;
          if (silenceTimer) {
            clearTimeout(silenceTimer);
            silenceTimer = null;
          }
        } else if (heardSpeech && !silenceTimer) {
          silenceTimer = setTimeout(finish, SILENCE_DURATION_MS);
        }
      } catch {}
    }, METERING_INTERVAL_MS);
  });
}

export async function stopRecording(): Promise<void> {
  cleanup();
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
