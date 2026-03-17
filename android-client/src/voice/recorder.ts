import { Audio } from "expo-av";
import * as FileSystem from "expo-file-system";

const RECORDING_OPTIONS: Audio.RecordingOptions = {
  android: {
    extension: ".wav",
    outputFormat: Audio.AndroidOutputFormat.DEFAULT,
    audioEncoder: Audio.AndroidAudioEncoder.DEFAULT,
    sampleRate: 16000,
    numberOfChannels: 1,
    bitRate: 256000,
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
    mimeType: "audio/wav",
    bitsPerSecond: 256000,
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

/**
 * Read a WAV file and extract the raw PCM samples as a Float32Array.
 * The server expects float32 at 16kHz mono.
 */
export async function wavFileToFloat32(uri: string): Promise<Float32Array> {
  const base64 = await FileSystem.readAsStringAsync(uri, {
    encoding: FileSystem.EncodingType.Base64,
  });

  const binaryStr = atob(base64);
  const bytes = new Uint8Array(binaryStr.length);
  for (let i = 0; i < binaryStr.length; i++) {
    bytes[i] = binaryStr.charCodeAt(i);
  }

  const view = new DataView(bytes.buffer);

  // Parse WAV header to find data chunk
  let offset = 12; // skip RIFF header
  while (offset < bytes.length - 8) {
    const chunkId = String.fromCharCode(
      bytes[offset], bytes[offset + 1], bytes[offset + 2], bytes[offset + 3]
    );
    const chunkSize = view.getUint32(offset + 4, true);

    if (chunkId === "data") {
      const dataStart = offset + 8;
      const dataEnd = Math.min(dataStart + chunkSize, bytes.length);
      const pcmBytes = bytes.slice(dataStart, dataEnd);

      // 16-bit PCM → float32
      const pcmView = new DataView(pcmBytes.buffer, pcmBytes.byteOffset, pcmBytes.byteLength);
      const numSamples = Math.floor(pcmBytes.length / 2);
      const float32 = new Float32Array(numSamples);
      for (let i = 0; i < numSamples; i++) {
        const sample = pcmView.getInt16(i * 2, true);
        float32[i] = sample / 32768.0;
      }
      return float32;
    }

    offset += 8 + chunkSize;
    if (chunkSize % 2 !== 0) offset++; // WAV chunks are word-aligned
  }

  throw new Error("No data chunk found in WAV file");
}
