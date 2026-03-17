/**
 * Background-capable audio pipeline built on VoiceProcessor (Picovoice).
 *
 * VoiceProcessor is a singleton that captures raw 16-bit PCM audio at the
 * hardware level via Android's AudioRecord. Unlike expo-av, it does NOT
 * require the Activity to be foregrounded — it runs as long as the app
 * process is alive (kept alive by our foreground service).
 *
 * Architecture:
 *   VoiceProcessor delivers fixed-size frames (512 samples @ 16 kHz).
 *   A single frame listener dispatches frames to the active consumer:
 *     - Wake word mode: frames go to Porcupine.process() + ring buffer
 *     - Recording mode: frames accumulate in a recording buffer
 *   The ring buffer preserves ~1.5s of audio so speech overlapping the
 *   wake word isn't lost.
 */

import { VoiceProcessor } from "@picovoice/react-native-voice-processor";
import { Porcupine, BuiltInKeywords } from "@picovoice/porcupine-react-native";
import * as FileSystem from "expo-file-system";

// ─── Types ───────────────────────────────────────────────────────────

export type WakeWordDetectedCallback = () => void;
export type MeteringCallback = (rmsDb: number) => void;

export interface PipelineConfig {
  accessKey: string;
  keyword: BuiltInKeywords;
  /** Sensitivity in [0, 1]. Higher = more sensitive (easier to trigger, more false alarms). Default 0.75 */
  sensitivity?: number;
}

type PipelineMode = "idle" | "wakeword" | "recording";

// ─── Ring buffer ─────────────────────────────────────────────────────

const RING_BUFFER_SECONDS = 1.5;

class RingBuffer {
  private buffer: Int16Array;
  private writePos = 0;
  private filled = false;
  private readonly capacity: number;

  constructor(sampleRate: number, seconds: number) {
    this.capacity = Math.ceil(sampleRate * seconds);
    this.buffer = new Int16Array(this.capacity);
  }

  push(frame: number[]): void {
    for (let i = 0; i < frame.length; i++) {
      this.buffer[this.writePos] = frame[i];
      this.writePos++;
      if (this.writePos >= this.capacity) {
        this.writePos = 0;
        this.filled = true;
      }
    }
  }

  drain(): Int16Array {
    let result: Int16Array;
    if (this.filled) {
      result = new Int16Array(this.capacity);
      const firstLen = this.capacity - this.writePos;
      result.set(this.buffer.subarray(this.writePos, this.capacity), 0);
      result.set(this.buffer.subarray(0, this.writePos), firstLen);
    } else {
      result = new Int16Array(this.writePos);
      result.set(this.buffer.subarray(0, this.writePos));
    }
    this.writePos = 0;
    this.filled = false;
    return result;
  }

  clear(): void {
    this.writePos = 0;
    this.filled = false;
  }
}

// ─── WAV construction ────────────────────────────────────────────────

function buildWav(samples: Int16Array, sampleRate: number): Uint8Array {
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = sampleRate * numChannels * (bitsPerSample / 8);
  const blockAlign = numChannels * (bitsPerSample / 8);
  const dataSize = samples.length * (bitsPerSample / 8);
  const headerSize = 44;

  const wav = new Uint8Array(headerSize + dataSize);
  const view = new DataView(wav.buffer);

  // RIFF header
  writeString(wav, 0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeString(wav, 8, "WAVE");

  // fmt chunk
  writeString(wav, 12, "fmt ");
  view.setUint32(16, 16, true);          // chunk size
  view.setUint16(20, 1, true);           // PCM format
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);

  // data chunk
  writeString(wav, 36, "data");
  view.setUint32(40, dataSize, true);

  // PCM samples (little-endian 16-bit)
  const pcmView = new DataView(wav.buffer, headerSize);
  for (let i = 0; i < samples.length; i++) {
    pcmView.setInt16(i * 2, samples[i], true);
  }

  return wav;
}

function writeString(buf: Uint8Array, offset: number, str: string): void {
  for (let i = 0; i < str.length; i++) {
    buf[offset + i] = str.charCodeAt(i);
  }
}

// ─── RMS metering ────────────────────────────────────────────────────

function computeRmsDb(frame: number[]): number {
  let sum = 0;
  for (let i = 0; i < frame.length; i++) {
    const normalized = frame[i] / 32768;
    sum += normalized * normalized;
  }
  const rms = Math.sqrt(sum / frame.length);
  if (rms < 1e-10) return -160;
  return 20 * Math.log10(rms);
}

// ─── Pipeline singleton ──────────────────────────────────────────────

let porcupine: Porcupine | null = null;
let ringBuffer: RingBuffer | null = null;
let mode: PipelineMode = "idle";
let wakeWordCb: WakeWordDetectedCallback | null = null;

// Recording state
let recordingChunks: Int16Array[] = [];
let recordingLength = 0;
let recordingMeterCb: MeteringCallback | null = null;
let recordingResolve: ((uri: string | null) => void) | null = null;

// Frame processing state
let sampleRate = 16000;
let processingFrame = false;
let listenersRegistered = false;

const frameListener = (frame: number[]): void => {
  // Only skip during wake word Porcupine processing; recording frames are synchronous
  if (processingFrame && mode === "wakeword") return;

  if (mode === "wakeword") {
    ringBuffer?.push(frame);

    if (!porcupine) return;
    processingFrame = true;
    porcupine
      .process(frame)
      .then((keywordIndex) => {
        if (keywordIndex >= 0) {
          wakeWordCb?.();
        }
      })
      .catch((err) => {
        console.error("Porcupine process error:", err);
      })
      .finally(() => {
        processingFrame = false;
      });
  } else if (mode === "recording") {
    const chunk = new Int16Array(frame.length);
    for (let i = 0; i < frame.length; i++) {
      chunk[i] = frame[i];
    }
    recordingChunks.push(chunk);
    recordingLength += chunk.length;

    recordingMeterCb?.(computeRmsDb(frame));
  }
};

const errorListener = (error: { message: string }): void => {
  console.error("VoiceProcessor error:", error.message);
};

function ensureListeners(): void {
  if (listenersRegistered) return;
  const vp = VoiceProcessor.instance;
  vp.addFrameListener(frameListener);
  vp.addErrorListener(errorListener);
  listenersRegistered = true;
}

async function cleanupStandaloneVP(): Promise<void> {
  const vp = VoiceProcessor.instance;
  if (listenersRegistered) {
    vp.removeFrameListener(frameListener);
    vp.removeErrorListener(errorListener);
    listenersRegistered = false;
  }
  try {
    if (await vp.isRecording()) {
      await vp.stop();
    }
  } catch (e) {
    console.error("Error stopping standalone VoiceProcessor:", e);
  }
}

// ─── Public API ──────────────────────────────────────────────────────

/**
 * Initialize the audio pipeline and start wake word detection.
 * VoiceProcessor starts capturing audio immediately.
 */
export async function startPipeline(config: PipelineConfig, onWakeWord: WakeWordDetectedCallback): Promise<void> {
  if (porcupine) {
    await stopPipeline();
  }

  wakeWordCb = onWakeWord;

  const sensitivity = Math.max(0, Math.min(1, config.sensitivity ?? 0.75));
  porcupine = await Porcupine.fromBuiltInKeywords(
    config.accessKey,
    [config.keyword],
    undefined,
    undefined,
    [sensitivity],
  );

  sampleRate = porcupine.sampleRate;
  ringBuffer = new RingBuffer(sampleRate, RING_BUFFER_SECONDS);

  ensureListeners();

  const vp = VoiceProcessor.instance;
  if (!(await vp.hasRecordAudioPermission())) {
    throw new Error("Microphone permission not granted");
  }

  await vp.start(porcupine.frameLength, sampleRate);
  mode = "wakeword";
}

/**
 * Pause wake word detection. VoiceProcessor keeps running so we can
 * switch to recording mode without restarting the audio stream.
 */
export function pauseWakeWord(): void {
  mode = "idle";
}

/**
 * Resume wake word detection after recording completes.
 */
export function resumeWakeWord(): void {
  if (!porcupine) return;
  ringBuffer?.clear();
  mode = "wakeword";
}

/**
 * Switch to recording mode. Returns a promise that resolves with the
 * WAV file URI when recording is stopped (via stopRecordingPipeline).
 *
 * If preserveRingBuffer is true, the ring buffer contents (audio from
 * before the switch) are prepended to the recording — this captures
 * speech that overlapped with the wake word.
 */
export async function startRecordingPipeline(
  onMeter: MeteringCallback | null,
  preserveRingBuffer: boolean,
): Promise<string | null> {
  recordingChunks = [];
  recordingLength = 0;
  recordingMeterCb = onMeter;
  processingFrame = false;

  if (preserveRingBuffer && ringBuffer) {
    const prefill = ringBuffer.drain();
    if (prefill.length > 0) {
      recordingChunks.push(prefill);
      recordingLength += prefill.length;
    }
  } else {
    ringBuffer?.clear();
  }

  // Ensure listeners are registered (needed when wake word was never enabled)
  ensureListeners();

  // Ensure VoiceProcessor is running (it may already be from wake word mode)
  const vp = VoiceProcessor.instance;
  const isRecording = await vp.isRecording();
  if (!isRecording) {
    const frameLength = porcupine?.frameLength ?? 512;
    await vp.start(frameLength, sampleRate);
  }

  mode = "recording";

  return new Promise<string | null>((resolve) => {
    recordingResolve = resolve;
  });
}

/**
 * Stop recording and write the accumulated PCM data as a WAV file.
 * Resolves the promise returned by startRecordingPipeline.
 */
export async function stopRecordingPipeline(): Promise<void> {
  if (mode !== "recording") {
    recordingResolve?.(null);
    recordingResolve = null;
    return;
  }

  mode = "idle";
  const resolve = recordingResolve;
  recordingResolve = null;
  recordingMeterCb = null;

  // If wake word isn't active, stop VoiceProcessor to release the mic
  if (!porcupine) {
    await cleanupStandaloneVP();
  }

  if (recordingLength === 0) {
    resolve?.(null);
    return;
  }

  // Merge chunks into a single Int16Array
  const merged = new Int16Array(recordingLength);
  let offset = 0;
  for (const chunk of recordingChunks) {
    merged.set(chunk, offset);
    offset += chunk.length;
  }
  recordingChunks = [];
  recordingLength = 0;

  try {
    const wav = buildWav(merged, sampleRate);
    const path = `${FileSystem.cacheDirectory}recording_${Date.now()}.wav`;
    const base64 = uint8ToBase64(wav);
    await FileSystem.writeAsStringAsync(path, base64, {
      encoding: FileSystem.EncodingType.Base64,
    });
    resolve?.(path);
  } catch (e) {
    console.error("Failed to write WAV file:", e);
    resolve?.(null);
  }
}

/**
 * Cancel an in-progress recording without saving.
 */
export function cancelRecording(): void {
  if (mode !== "recording") return;
  mode = "idle";
  recordingChunks = [];
  recordingLength = 0;
  recordingMeterCb = null;
  recordingResolve?.(null);
  recordingResolve = null;

  if (!porcupine) {
    cleanupStandaloneVP().catch(() => {});
  }
}

/**
 * Tear down the pipeline completely. Stops VoiceProcessor and deletes
 * the Porcupine instance.
 */
export async function stopPipeline(): Promise<void> {
  mode = "idle";
  cancelRecording();

  const vp = VoiceProcessor.instance;
  if (listenersRegistered) {
    vp.removeFrameListener(frameListener);
    vp.removeErrorListener(errorListener);
    listenersRegistered = false;
  }

  try {
    if (await vp.isRecording()) {
      await vp.stop();
    }
  } catch (e) {
    console.error("Error stopping VoiceProcessor:", e);
  }

  if (porcupine) {
    try {
      await porcupine.delete();
    } catch (e) {
      console.error("Error deleting Porcupine:", e);
    }
    porcupine = null;
  }

  ringBuffer = null;
  wakeWordCb = null;
}

export function isPipelineActive(): boolean {
  return porcupine !== null;
}

export function getPipelineMode(): PipelineMode {
  return mode;
}

export function getSampleRate(): number {
  return sampleRate;
}

// ─── Utilities ───────────────────────────────────────────────────────

function uint8ToBase64(bytes: Uint8Array): string {
  let binary = "";
  const len = bytes.byteLength;
  for (let i = 0; i < len; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}
