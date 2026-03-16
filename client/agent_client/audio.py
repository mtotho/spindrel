import collections
import queue
import shutil
import subprocess
import sys
import threading
import time
import warnings
from pathlib import Path

TTS_AVAILABLE = shutil.which("piper") is not None and shutil.which("aplay") is not None

try:
    import numpy as np
    import sounddevice as sd
    from faster_whisper import WhisperModel

    STT_AVAILABLE = True
except ImportError:
    STT_AVAILABLE = False

try:
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message=".*CUDAExecutionProvider.*")
        from openwakeword.model import Model as OwwModel

    WAKEWORD_AVAILABLE = True
except ImportError:
    WAKEWORD_AVAILABLE = False

_whisper_model: "WhisperModel | None" = None
_oww_model: "OwwModel | None" = None
_oww_keys: list[str] = []

_tts_lock = threading.Lock()
_tts_procs: list[subprocess.Popen] = []


# --- Shared Mic (callback-based) ---

SAMPLE_RATE = 16000
CHANNELS = 1
BLOCKSIZE = 1024
CHUNKS_PER_SECOND = SAMPLE_RATE // BLOCKSIZE

_audio_q: "queue.Queue[np.ndarray]" = queue.Queue()
_mic_stream: "sd.InputStream | None" = None


def _mic_callback(indata, frames, time_info, status):
    _audio_q.put(indata.copy())


def _open_mic() -> None:
    """Start the persistent callback-based mic stream."""
    global _mic_stream
    if _mic_stream is not None and _mic_stream.active:
        return
    if _mic_stream is not None:
        try:
            _mic_stream.close()
        except Exception:
            pass

    # Drain any stale data from previous session
    while not _audio_q.empty():
        try:
            _audio_q.get_nowait()
        except queue.Empty:
            break

    _mic_stream = sd.InputStream(
        samplerate=SAMPLE_RATE, channels=CHANNELS,
        dtype="float32", blocksize=BLOCKSIZE,
        callback=_mic_callback,
    )
    _mic_stream.start()


def close_mic() -> None:
    global _mic_stream
    if _mic_stream is not None:
        try:
            _mic_stream.stop()
            _mic_stream.close()
        except Exception:
            pass
        _mic_stream = None


def _read_chunk(timeout: float = 2.0) -> "np.ndarray":
    """Read one chunk from the callback queue."""
    return _audio_q.get(timeout=timeout)


def _drain_queue() -> None:
    """Discard any buffered audio to get fresh data."""
    while not _audio_q.empty():
        try:
            _audio_q.get_nowait()
        except queue.Empty:
            break


# --- TTS ---

def _ensure_piper_model(model: str, model_dir: Path) -> Path:
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
        onnx_path = _ensure_piper_model(model, resolved_dir)

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

        with _tts_lock:
            _tts_procs[:] = [piper_proc, aplay_proc]

        try:
            piper_proc.stdin.write(text.encode())
            piper_proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass

        aplay_proc.wait()
        piper_proc.wait()

        with _tts_lock:
            _tts_procs.clear()

        if piper_proc.returncode and piper_proc.returncode > 0:
            err = piper_proc.stderr.read().decode().strip()
            if err:
                print(f"[TTS] piper error: {err}", file=sys.stderr)
        if aplay_proc.returncode and aplay_proc.returncode > 0:
            err = aplay_proc.stderr.read().decode().strip()
            if err:
                print(f"[TTS] aplay error: {err}", file=sys.stderr)
    except Exception as e:
        with _tts_lock:
            _tts_procs.clear()
        print(f"[TTS] playback failed: {e}", file=sys.stderr)


def stop_speaking() -> None:
    """Kill any running TTS playback immediately."""
    with _tts_lock:
        for proc in _tts_procs:
            if proc.poll() is None:
                try:
                    proc.kill()
                except OSError:
                    pass
        _tts_procs.clear()


def check_tts_ready(model: str, model_dir: str) -> str | None:
    if not shutil.which("piper"):
        return "piper not found in PATH. Install with: pip install piper-tts"
    if not shutil.which("aplay"):
        return "aplay not found in PATH. Install alsa-utils."

    resolved_dir = Path(model_dir).expanduser()

    try:
        onnx_path = _ensure_piper_model(model, resolved_dir)
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

SILENCE_THRESHOLD = 0.01
SILENCE_DURATION = 2.5
MAX_RECORD_SECONDS = 30
MAX_IDLE_SECONDS = 8
MIN_RECORD_SECONDS = 0.5
PRE_BUFFER_SECONDS = 0.5


def _get_whisper(model_name: str) -> "WhisperModel":
    global _whisper_model
    if _whisper_model is None:
        print("Loading whisper model (first time may download ~150MB)...")
        _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
        print("Whisper ready.")
    return _whisper_model


def record_audio(idle_timeout: float | None = None) -> "np.ndarray | None":
    """Record from mic with pre-buffer. Auto-stops on 2.5s silence after speech,
    or after idle_timeout seconds if no speech detected at all."""
    if not STT_AVAILABLE:
        return None

    _open_mic()
    _drain_queue()

    idle_limit = idle_timeout or MAX_IDLE_SECONDS
    pre_buffer_size = int(PRE_BUFFER_SECONDS * CHUNKS_PER_SECOND)
    pre_buffer: collections.deque = collections.deque(maxlen=pre_buffer_size)

    chunks: list = []
    silent_chunks = 0
    has_speech = False
    peak_rms = 0.0
    silence_chunks_needed = int(SILENCE_DURATION * CHUNKS_PER_SECOND)
    idle_chunks_needed = int(idle_limit * CHUNKS_PER_SECOND)
    max_chunks = int(MAX_RECORD_SECONDS * CHUNKS_PER_SECOND)

    print("Listening... (speak now, auto-stops on silence)")

    try:
        for i in range(max_chunks):
            data = _read_chunk()
            rms = float(np.sqrt(np.mean(data ** 2)))
            peak_rms = max(peak_rms, rms)

            if not has_speech:
                pre_buffer.append(data.copy())
            else:
                chunks.append(data.copy())

            if rms > SILENCE_THRESHOLD:
                if not has_speech:
                    print("  Speech detected!")
                    chunks.extend(pre_buffer)
                    pre_buffer.clear()
                has_speech = True
                silent_chunks = 0
            else:
                silent_chunks += 1

            if i % (CHUNKS_PER_SECOND // 2) == 0:
                bar_len = min(int(rms * 500), 30)
                bar = "#" * bar_len
                elapsed = (len(chunks) + len(pre_buffer)) / CHUNKS_PER_SECOND
                state = "SPEECH" if rms > SILENCE_THRESHOLD else "quiet"
                print(f"  [{elapsed:4.1f}s] {state:6s} |{bar:<30s}| rms={rms:.4f}", end="\r")

            total_seconds = len(chunks) / CHUNKS_PER_SECOND
            if has_speech and silent_chunks >= silence_chunks_needed and total_seconds >= MIN_RECORD_SECONDS:
                break

            if not has_speech and i >= idle_chunks_needed:
                break

        print()

    except KeyboardInterrupt:
        print("\nRecording cancelled.")
        return None
    except Exception as e:
        print(f"[STT] Recording error: {e}", file=sys.stderr)
        return None

    if not has_speech:
        return None

    duration = len(chunks) / CHUNKS_PER_SECOND
    print(f"  Recorded {duration:.1f}s, peak level={peak_rms:.4f}")

    return np.concatenate(chunks)


def transcribe(audio: "np.ndarray", model_name: str) -> str | None:
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
        default_in = sd.query_devices(kind="input")
        if default_in is None:
            return "No input audio device found."
    except Exception as e:
        return f"Audio device error: {e}"

    return None


# --- Tone ---

def play_tone(volume: float = 0.3) -> None:
    """Play a short rising two-tone chime to confirm wake word detection."""
    if not STT_AVAILABLE:
        return
    try:
        duration = 0.1
        gap_duration = 0.03
        sr = SAMPLE_RATE

        t = np.linspace(0, duration, int(sr * duration), endpoint=False)
        tone1 = np.sin(2 * np.pi * 660 * t)
        tone2 = np.sin(2 * np.pi * 880 * t)
        gap = np.zeros(int(sr * gap_duration))

        chime = np.concatenate([tone1, gap, tone2]).astype(np.float32) * volume

        fade_len = int(0.005 * sr)
        if fade_len > 0:
            chime[:fade_len] *= np.linspace(0, 1, fade_len, dtype=np.float32)
            chime[-fade_len:] *= np.linspace(1, 0, fade_len, dtype=np.float32)

        sd.play(chime, samplerate=sr)
        sd.wait()
    except Exception:
        pass


# --- Wake Word ---

WAKEWORD_CHUNK = 1280  # 80ms at 16kHz, optimal for openwakeword
WAKEWORD_THRESHOLD = 0.5


def _get_oww_model() -> "OwwModel":
    global _oww_model, _oww_keys
    if _oww_model is None:
        print("Loading wake word models...")
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore", message=".*CUDAExecutionProvider.*")
            _oww_model = OwwModel()
        # Dummy predict to populate prediction_buffer keys
        dummy = np.zeros(WAKEWORD_CHUNK, dtype=np.int16)
        _oww_model.predict(dummy)
        _oww_keys = list(_oww_model.prediction_buffer.keys())
        print(f"Wake words available: {', '.join(_oww_keys)}")
        _oww_model.reset()
    return _oww_model


def listen_for_wakeword(
    wake_words: list[str] | None = None,
    stop_event: "threading.Event | None" = None,
) -> str | None:
    """Block until a wake word is detected. Returns the detected wake word name,
    or None on cancel or if stop_event is set."""
    if not WAKEWORD_AVAILABLE or not STT_AVAILABLE:
        return None

    _open_mic()
    _drain_queue()

    model = _get_oww_model()

    if wake_words:
        listen_keys = [k for k in _oww_keys if k in wake_words]
        skipped = [w for w in wake_words if w not in _oww_keys]
        if skipped:
            print(f"  Not available: {', '.join(skipped)}")
            print(f"  (valid options: {', '.join(_oww_keys)})")
        if not listen_keys:
            print("No matching wake words found — check WAKE_WORDS in config.")
            return None
    else:
        listen_keys = _oww_keys

    model.reset()
    if stop_event is not None:
        # Flush internal ONNX state (RNN hidden layers) by running
        # predictions on silence — model.reset() only clears the
        # prediction buffer, not the neural network hidden state,
        # so residual activation from a previous real detection can
        # cause an instant false trigger on the first chunk of audio.
        _flush = np.zeros(WAKEWORD_CHUNK, dtype=np.int16)
        for _ in range(20):
            model.predict(_flush)
        model.reset()

    print(f"Listening for: {', '.join(listen_keys)}")
    if stop_event is None:
        print("  (Ctrl+C to stop)")

    chunk_timeout = 0.2 if stop_event is not None else 2.0
    # During TTS playback the mic picks up speaker audio which can
    # cause brief false positives — require sustained detection.
    consecutive_needed = 3 if stop_event is not None else 1
    consecutive_count = 0
    chunk_count = 0
    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                model.reset()
                return None

            try:
                data = _read_chunk(timeout=chunk_timeout)
            except queue.Empty:
                continue

            audio_int16 = (data.flatten() * 32767).astype(np.int16)
            if len(audio_int16) < WAKEWORD_CHUNK:
                audio_int16 = np.pad(audio_int16, (0, WAKEWORD_CHUNK - len(audio_int16)))
            elif len(audio_int16) > WAKEWORD_CHUNK:
                audio_int16 = audio_int16[:WAKEWORD_CHUNK]

            prediction = model.predict(audio_int16)

            chunk_count += 1

            best_name = ""
            best_score = 0.0
            for name in listen_keys:
                score = float(prediction.get(name, 0))
                if score > best_score:
                    best_score = score
                    best_name = name

            if chunk_count % 25 == 0 and best_score > 0.01:
                print(f"  {best_name}: {best_score:.2f}", end="\r")

            if best_score > WAKEWORD_THRESHOLD:
                consecutive_count += 1
                if consecutive_count >= consecutive_needed:
                    print(f"  Wake word detected: {best_name} (score={best_score:.2f})")
                    model.reset()
                    return best_name
            else:
                consecutive_count = 0

    except KeyboardInterrupt:
        print("\nWake word listening stopped.")
        return None
    except Exception as e:
        print(f"[Wakeword] Error: {e}", file=sys.stderr)
        return None


def check_wakeword_ready() -> str | None:
    if not WAKEWORD_AVAILABLE:
        return "openwakeword not installed. Install with: pip install -e \"client/[wakeword]\""
    return None
