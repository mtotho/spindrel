# Voice Feature — CLI Client

Extends the existing text REPL with push-to-talk audio input and spoken responses. All processing is local — no API calls, no internet required.

---

## How It Works

1. Hold F9 (configurable) → records mic via `sounddevice`
2. Release → silence detected via `webrtcvad`, recording stops
3. Audio transcribed locally via `faster-whisper`
4. Transcript sent to `POST /chat` — identical path to typing a message
5. Response text spoken via **Piper** (local TTS)
6. Response also printed to terminal as normal

---

## New Dependencies (all optional)

| Package | Purpose |
|---------|---------|
| `sounddevice` | Mic capture |
| `webrtcvad` | Silence / voice activity detection |
| `faster-whisper` | Local speech-to-text |
| `piper-tts` | Local text-to-speech |
| `pynput` | Global hotkey listener |

If any of these are missing, the CLI falls back to text-only mode with a warning. It never crashes on missing audio deps.

---

## TTS — Piper

Piper is a fully local neural TTS engine. Runs offline, no API key, no data leaves the machine.

- Voice model downloaded once (~60MB), stored locally
- Runs as a subprocess, pipes raw audio to `aplay`
- Recommended voice: `en_US-lessac-medium`

```bash
# Install
pip install piper-tts

# Download voice model (one time)
piper --download-dir ~/.local/share/piper --model en_US-lessac-medium
```

---

## STT — faster-whisper

Local Whisper implementation. Runs on CPU, no GPU required for `base.en`.

```bash
pip install faster-whisper
```

Model is downloaded on first use and cached locally.

---

## New Config Options

Added to `~/.config/agent-client/config.env`:

```
HOTKEY=f9
WHISPER_MODEL=base.en
TTS_ENABLED=true
PIPER_MODEL=en_US-lessac-medium
PIPER_MODEL_DIR=~/.local/share/piper
```

---

## New Files

- `agent_client/audio.py` — recording, VAD, transcription, TTS playback
- Updates to `agent_client/cli.py` — hotkey listener wired into REPL loop

---

## Graceful Degradation

```python
try:
    import sounddevice as sd
    import faster_whisper
    import webrtcvad
    AUDIO_AVAILABLE = True
except ImportError:
    AUDIO_AVAILABLE = False
```

If `AUDIO_AVAILABLE` is False or `TTS_ENABLED=false`, voice features are silently skipped. The REPL works as normal.