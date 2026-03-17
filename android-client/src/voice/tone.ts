/**
 * Play a short confirmation tone when the wake word is detected.
 * Presets match the Python client: chime (two-tone), beep (800Hz), ping (1200Hz).
 */

import { Audio, InterruptionModeAndroid, InterruptionModeIOS } from "expo-av";
import * as FileSystem from "expo-file-system";

let audioModeSet = false;

async function ensureAudioMode(): Promise<void> {
  if (audioModeSet) return;
  try {
    await Audio.setAudioModeAsync({
      allowsRecordingIOS: false,
      interruptionModeIOS: InterruptionModeIOS.MixWithOthers,
      playsInSilentModeIOS: true,
      staysActiveInBackground: false,
      interruptionModeAndroid: InterruptionModeAndroid.DuckOthers,
      shouldDuckAndroid: true,
      playThroughEarpieceAndroid: false,
    });
    audioModeSet = true;
  } catch (e) {
    console.warn("setAudioModeAsync failed:", e);
  }
}

const SAMPLE_RATE = 16000;
const VOLUME = 0.3;

export type ListenSoundPreset = "chime" | "beep" | "ping";

export const LISTEN_SOUND_PRESETS: ListenSoundPreset[] = ["chime", "beep", "ping"];

function generateToneSamples(preset: ListenSoundPreset): Int16Array {
  const sr = SAMPLE_RATE;
  const fadeLen = Math.floor(0.005 * sr);

  const applyFade = (samples: Float32Array) => {
    if (fadeLen > 0 && samples.length > 2 * fadeLen) {
      for (let i = 0; i < fadeLen; i++) {
        samples[i] *= i / fadeLen;
        samples[samples.length - 1 - i] *= i / fadeLen;
      }
    }
  };

  let samples: Float32Array;

  if (preset === "beep") {
    const duration = 0.15;
    const n = Math.floor(sr * duration);
    samples = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const t = i / sr;
      samples[i] = Math.sin(2 * Math.PI * 800 * t) * VOLUME;
    }
  } else if (preset === "ping") {
    const duration = 0.08;
    const n = Math.floor(sr * duration);
    samples = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const t = i / sr;
      samples[i] = Math.sin(2 * Math.PI * 1200 * t) * VOLUME;
    }
  } else {
    // chime — two-tone rising
    const duration = 0.1;
    const gapLen = Math.floor(sr * 0.03);
    const n = Math.floor(sr * duration);
    const tone1 = new Float32Array(n);
    const tone2 = new Float32Array(n);
    const gap = new Float32Array(gapLen);
    for (let i = 0; i < n; i++) {
      const t = i / sr;
      tone1[i] = Math.sin(2 * Math.PI * 660 * t) * VOLUME;
      tone2[i] = Math.sin(2 * Math.PI * 880 * t) * VOLUME;
    }
    samples = new Float32Array(n + gapLen + n);
    samples.set(tone1, 0);
    samples.set(gap, n);
    samples.set(tone2, n + gapLen);
  }

  applyFade(samples);

  const pcm = new Int16Array(samples.length);
  for (let i = 0; i < samples.length; i++) {
    const v = Math.round(samples[i] * 32767);
    pcm[i] = Math.max(-32768, Math.min(32767, v));
  }
  return pcm;
}

function buildWav(pcm: Int16Array, sampleRate: number): Uint8Array {
  const numChannels = 1;
  const bitsPerSample = 16;
  const byteRate = sampleRate * numChannels * (bitsPerSample / 8);
  const blockAlign = numChannels * (bitsPerSample / 8);
  const dataSize = pcm.length * (bitsPerSample / 8);
  const headerSize = 44;

  const wav = new Uint8Array(headerSize + dataSize);
  const view = new DataView(wav.buffer);

  const writeStr = (offset: number, str: string) => {
    for (let i = 0; i < str.length; i++) wav[offset + i] = str.charCodeAt(i);
  };

  writeStr(0, "RIFF");
  view.setUint32(4, 36 + dataSize, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, numChannels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, byteRate, true);
  view.setUint16(32, blockAlign, true);
  view.setUint16(34, bitsPerSample, true);
  writeStr(36, "data");
  view.setUint32(40, dataSize, true);

  const pcmView = new DataView(wav.buffer, headerSize);
  for (let i = 0; i < pcm.length; i++) {
    pcmView.setInt16(i * 2, pcm[i], true);
  }
  return wav;
}

function uint8ToBase64(bytes: Uint8Array): string {
  let binary = "";
  for (let i = 0; i < bytes.length; i++) {
    binary += String.fromCharCode(bytes[i]);
  }
  return btoa(binary);
}

/**
 * Play the listen confirmation tone (chime, beep, or ping).
 * Writes a short WAV to cache and plays it with expo-av.
 */
export async function playListenTone(preset: ListenSoundPreset = "chime"): Promise<void> {
  try {
    await ensureAudioMode();

    const pcm = generateToneSamples(preset);
    const wav = buildWav(pcm, SAMPLE_RATE);
    const base64 = uint8ToBase64(wav);
    const dir = FileSystem.cacheDirectory ?? "";
    const path = `${dir}listen_tone_${preset}.wav`;
    await FileSystem.writeAsStringAsync(path, base64, {
      encoding: FileSystem.EncodingType.Base64,
    });

    const uri = path.startsWith("file://") ? path : `file://${path}`;
    const { sound } = await Audio.Sound.createAsync(
      { uri },
      { shouldPlay: true }
    );

    const unload = () => {
      sound.unloadAsync().catch(() => {});
    };
    sound.setOnPlaybackStatusUpdate((status) => {
      if (status.isLoaded && (status as { didJustFinish?: boolean }).didJustFinish) {
        unload();
      }
    });
    setTimeout(unload, 600);
  } catch (e) {
    console.warn("Listen tone playback failed:", e);
  }
}
