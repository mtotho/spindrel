# Agent Client

A Python client that runs on a **separate machine** and connects to the Spindrel server over HTTP/SSE. It serves two purposes:

1. **Voice assistant** — wake word detection, speech-to-text, text-to-speech. Deploy on a Raspberry Pi, tablet, or any always-on device for a hands-free AI assistant.
2. **Local tool executor** — the server can request client-side actions (shell commands, file operations) that execute on the client's machine, not the server. This lets a remote bot help you on your local workstation.

The client communicates via streaming SSE (`/chat/stream`) and polls for client tool requests. It currently uses legacy (pre-v1) endpoints which still work — a future refresh will bring channel awareness and the v1 API.

## Quick Start

```bash
cd client && pip install -e .
agent --url http://your-server:8000 --key your-api-key
# or for local dev (pulls API_KEY from .env automatically):
./scripts/dev-client.sh
```

### Commands

| Command | What it does |
|---|---|
| `/help` | Show all commands |
| `/new` | Start a fresh conversation (new session) |
| `/bot <id>` | Switch to a different bot |
| `/bots` | List available bots |
| `/tts` | Toggle text-to-speech on/off |
| `/v` | Voice input — record, transcribe, send |
| `/vc` | Voice conversation — continuous back-and-forth |
| `/listen` | Wake word mode |
| `/session` | Show current session UUID |
| `/sessions` | List all sessions |
| `/history` | Print session message history |
| `/compact` | Force compaction now |
| `/quit` | Exit (Ctrl+C also works) |

### Voice Features

**Text-to-Speech** — Uses [Piper](https://github.com/rhasspy/piper), a fully local neural TTS engine. Enable with `--tts` flag or `/tts` command.

**Speech-to-Text** — Server-side transcription via [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The client sends audio to `POST /transcribe`. Falls back to local transcription if server is unreachable.

**Wake Word** — Uses [openwakeword](https://github.com/dscripka/openWakeWord). Type `/listen` or start with `--listen`. Configure wake words:

```bash
# ~/.config/agent-client/config.env
WAKE_WORDS=hey_jarvis,hey_computer
```

**Silent Responses** — Bots can use `[silent]...[/silent]` tags to show text without speaking it aloud.

### Voice Configuration

All optional, in `~/.config/agent-client/config.env`:

```
TTS_ENABLED=true
PIPER_MODEL=en_US-lessac-medium
TTS_SPEED=1.0
LISTEN_SOUND=chime                # chime | beep | ping
WHISPER_MODEL=base.en
WAKE_WORDS=hey_jarvis,hey_computer
```

### Server STT Config

```
STT_PROVIDER=local                  # "local" (faster-whisper)
WHISPER_MODEL=base.en
WHISPER_DEVICE=auto                 # auto | cpu | cuda
WHISPER_COMPUTE_TYPE=auto
WHISPER_BEAM_SIZE=1
WHISPER_LANGUAGE=en
```

### Settings Priority

1. `~/.config/agent-client/config.env` (persistent config)
2. Environment variables
3. CLI flags (`--url`, `--key`, `--bot`, `--tts`, `--listen`)

## Android Client

A React Native (Expo bare workflow) voice assistant app for Android tablets. Supports voice input, TTS, wake word detection (Picovoice Porcupine), and runs as a foreground service.

### Quick Start

```bash
cd android-client
npm install
npx expo prebuild
ANDROID_HOME=/path/to/sdk npx expo run:android
```

### Config from .env

The Android client reads your server's `.env` at build time:

```
ANDROID_AGENT_URL=http://192.168.1.100:8000
PICOVOICE_ACCESS_KEY=your-key-here     # free from console.picovoice.ai
```

### Transcription Modes

- **Server (Whisper)** — Audio sent to `POST /transcribe` (default)
- **Local (Cheetah)** — On-device via Picovoice Cheetah (no audio sent for STT)

### Sideloading to Fire Tablet

1. Enable developer mode: Settings > Device Options > tap Serial Number 7 times
2. Enable ADB: Settings > Developer Options > Enable ADB
3. `adb connect <tablet-ip>:5555`
4. `adb install android-client/android/app/build/outputs/apk/debug/app-debug.apk`
