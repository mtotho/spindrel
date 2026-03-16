import shutil
import subprocess
import sys
from pathlib import Path

TTS_AVAILABLE = shutil.which("piper") is not None and shutil.which("aplay") is not None

try:
    import numpy as np
    import sounddevice as sd
    from faster_whisper import WhisperModel

    STT_AVAILABLE = True
except ImportError:
    STT_AVAILABLE = False

_whisper_model: "WhisperModel | None" = None


# --- TTS ---

def _ensure_model(model: str, model_dir: Path) -> Path:
    """Download the piper voice model if it doesn't exist. Returns the .onnx path."""
    onnx_path = model_dir / f"{model}.onnx"
    if onnx_path.exists():
        return onnx_path

    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"Downloading piper voice model '{model}' (~60MB)...")

    from piper.download_voices import download_voice
    download_voice(model, model_dir)

    if not onnx_path.exists():
        raise RuntimeError(f"Download completed but {onnx_path} not found")

    print("Download complete.")
    return onnx_path


def speak(text: str, model: str, model_dir: str) -> None:
    if not TTS_AVAILABLE:
        return

    resolved_dir = Path(model_dir).expanduser()

    try:
        onnx_path = _ensure_model(model, resolved_dir)

        piper_proc = subprocess.Popen(
            ["piper", "--model", str(onnx_path), "--output-raw"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        aplay_proc = subprocess.Popen(
            ["aplay", "-r", "22050", "-f", "S16_LE", "-t", "raw", "-q"],
            stdin=piper_proc.stdout,
            stderr=subprocess.PIPE,
        )
        piper_proc.stdout.close()
        piper_proc.stdin.write(text.encode())
        piper_proc.stdin.close()
        aplay_proc.wait()
        piper_proc.wait()

        if piper_proc.returncode != 0:
            err = piper_proc.stderr.read().decode().strip()
            print(f"[TTS] piper error: {err}", file=sys.stderr)
        if aplay_proc.returncode != 0:
            err = aplay_proc.stderr.read().decode().strip()
            print(f"[TTS] aplay error: {err}", file=sys.stderr)
    except Exception as e:
        print(f"[TTS] playback failed: {e}", file=sys.stderr)


def check_tts_ready(model: str, model_dir: str) -> str | None:
    """Returns an error message if TTS can't work, or None if ready."""
    if not shutil.which("piper"):
        return "piper not found in PATH. Install with: pip install piper-tts"
    if not shutil.which("aplay"):
        return "aplay not found in PATH. Install alsa-utils."

    resolved_dir = Path(model_dir).expanduser()

    try:
        onnx_path = _ensure_model(model, resolved_dir)
    except Exception as e:
        return f"Failed to get voice model: {e}"

    try:
        result = subprocess.run(
            ["piper", "--model", str(onnx_path), "--output-raw"],
            input=b"test",
            capture_output=True,
            timeout=30,
        )
        if result.returncode != 0:
            err = result.stderr.decode().strip()
            return f"piper failed: {err}"
    except subprocess.TimeoutExpired:
        return "piper timed out during test"
    except Exception as e:
        return f"piper check failed: {e}"

    return None


# --- STT ---

SAMPLE_RATE = 16000
CHANNELS = 1
SILENCE_THRESHOLD = 0.01
SILENCE_DURATION = 1.5
MAX_RECORD_SECONDS = 30
MAX_IDLE_SECONDS = 8
MIN_RECORD_SECONDS = 0.5


def _get_whisper(model_name: str) -> "WhisperModel":
    global _whisper_model
    if _whisper_model is None:
        print("Loading whisper model (first time may download ~150MB)...")
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print("Whisper ready.")
    return _whisper_model


def record_audio() -> "np.ndarray | None":
    """Record audio from mic until silence is detected. Returns numpy array or None."""
    if not STT_AVAILABLE:
        return None

    chunks: list = []
    silent_chunks = 0
    has_speech = False
    peak_rms = 0.0
    chunks_per_second = SAMPLE_RATE // 1024
    silence_chunks_needed = int(SILENCE_DURATION * chunks_per_second)

    print("Listening... (speak now, auto-stops on silence)")
    print(f"  threshold={SILENCE_THRESHOLD}  silence_after={SILENCE_DURATION}s  max={MAX_RECORD_SECONDS}s")

    try:
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                            dtype="float32", blocksize=1024) as stream:
            for i in range(int(MAX_RECORD_SECONDS * chunks_per_second)):
                data, _ = stream.read(1024)
                chunks.append(data.copy())

                rms = float(np.sqrt(np.mean(data ** 2)))
                peak_rms = max(peak_rms, rms)

                if rms > SILENCE_THRESHOLD:
                    if not has_speech:
                        print("  Speech detected!")
                    has_speech = True
                    silent_chunks = 0
                else:
                    silent_chunks += 1

                # Print level indicator every ~0.5s
                if i % (chunks_per_second // 2) == 0:
                    bar_len = min(int(rms * 500), 30)
                    bar = "#" * bar_len
                    elapsed = len(chunks) / chunks_per_second
                    state = "SPEECH" if rms > SILENCE_THRESHOLD else "quiet"
                    print(f"  [{elapsed:4.1f}s] {state:6s} |{bar:<30s}| rms={rms:.4f}", end="\r")

                total_seconds = len(chunks) / chunks_per_second
                if has_speech and silent_chunks >= silence_chunks_needed and total_seconds >= MIN_RECORD_SECONDS:
                    break

            print()  # newline after \r progress

    except KeyboardInterrupt:
        print("\nRecording cancelled.")
        return None
    except Exception as e:
        print(f"[STT] Recording error: {e}", file=sys.stderr)
        return None

    duration = len(chunks) / chunks_per_second
    print(f"  Recorded {duration:.1f}s, peak level={peak_rms:.4f}")

    if not has_speech:
        print("No speech detected. Try speaking louder or check your mic.")
        return None

    print("Recording complete.")
    return np.concatenate(chunks)


def transcribe(audio: "np.ndarray", model_name: str) -> str | None:
    """Transcribe audio array to text using faster-whisper."""
    if not STT_AVAILABLE:
        return None

    model = _get_whisper(model_name)

    print("Transcribing...")
    audio_flat = audio.flatten()
    segments, _ = model.transcribe(audio_flat, beam_size=1, language="en")
    text = " ".join(seg.text.strip() for seg in segments).strip()

    if not text:
        print("No speech recognized.")
        return None

    return text


def check_stt_ready() -> str | None:
    """Returns an error message if STT can't work, or None if ready."""
    if not STT_AVAILABLE:
        missing = []
        try:
            import sounddevice  # noqa: F401
        except ImportError:
            missing.append("sounddevice")
        try:
            import numpy  # noqa: F401
        except ImportError:
            missing.append("numpy")
        try:
            import faster_whisper  # noqa: F401
        except ImportError:
            missing.append("faster-whisper")
        return f"Missing packages: {', '.join(missing)}. Install with: pip install -e \"client/[voice]\""

    try:
        devices = sd.query_devices()
        default_in = sd.query_devices(kind="input")
        if default_in is None:
            return "No input audio device found."
    except Exception as e:
        return f"Audio device error: {e}"

    return None
