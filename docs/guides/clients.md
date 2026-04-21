# Agent Client

!!! warning "Older, lightly maintained surface"
    This client still exists, but it has not been exercised recently enough to present as a current flagship path. The local tool-executor model is still useful; the voice-assistant path should be treated as lower-confidence until it gets fresh testing.

A Python client that runs on a **separate machine** and connects to the Spindrel server over HTTP/SSE. It serves two purposes:

1. **Voice assistant** — wake word detection, speech-to-text, text-to-speech. Deploy on a Raspberry Pi, tablet, or any always-on device for a hands-free AI assistant.
2. **Local tool executor** — the server can request client-side actions (shell commands, file operations) that execute on the client's machine, not the server. This lets a remote bot help you on your local workstation.

The client communicates via streaming SSE (`/chat/stream`) with full Rich terminal rendering — markdown, code highlighting, and real-time streaming display.

## Quick Start

```bash
cd client
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -e .

agent-chat --url http://your-server:8000 --key your-api-key
```

> **Why a venv?** Modern Linux distros (Arch, Fedora 38+, Debian 12+, Ubuntu 23.04+) block system-wide `pip install` via [PEP 668](https://peps.python.org/pep-0668/). A virtual environment keeps your system Python clean and avoids the `externally-managed-environment` error.

For local development (pulls `API_KEY` from `.env` automatically):

```bash
./scripts/dev-client.sh
```

### Rich Terminal Display

The client uses [Rich](https://github.com/Textualize/rich) for beautiful terminal output:

- **Real-time streaming** — markdown renders live as the response streams in
- **Code highlighting** — syntax-highlighted code blocks in responses
- **Tool status** — dim status lines showing tool execution, context assembly, and compaction
- **Rich tables** — session lists, bot lists, channel lists, and help all use formatted tables
- **Approval prompts** — interactive Y/N prompts for tool approval requests

### Commands

| Command | What it does |
|---|---|
| `/help` | Show all commands with descriptions |
| `/new` | Start a fresh conversation (new session) |
| `/session [id]` | Show or switch session (by number, UUID, or title) |
| `/sessions` | List all sessions in a formatted table |
| `/history` | Print session message history |
| `/compact` | Force context compaction |
| `/channels` | List channels for the current bot |
| `/channel [id]` | Show or switch channel (`/channel none` to clear) |
| `/model [name\|reset]` | Set or clear per-message model override |
| `/attach <path>` | Queue an image attachment for the next message |
| `/cancel` | Cancel an in-progress request |
| `/setup` | Generate a scoped API key for this client |
| `/bot [id]` | Show or switch bot |
| `/bots` | List available bots |
| `/tools` | List all server tools |
| `/tool <name> [json]` | Execute a tool directly |
| `/v` | Voice input — record, transcribe, send |
| `/vc` | Voice conversation — continuous back-and-forth |
| `/listen` | Wake word mode |
| `/tts` | Toggle text-to-speech on/off |
| `/tts_voice [model]` | Get or set TTS voice |
| `/tone [preset]` | Get or set listen tone (chime\|beep\|ping) |
| `/audio` | Toggle native audio mode |
| `/quit` | Exit (Ctrl+C also works) |

### Channel Awareness

The client supports channel-based conversations. Channels persist state on the server side (workspace files, heartbeats, integrations).

```bash
# Start with a specific channel
agent-chat --channel <channel-id>

# Or switch in the REPL
/channels          # list available channels
/channel 1         # switch by number
/channel abc123    # switch by ID prefix
/channel none      # clear channel (use raw session)
```

Channel selection persists across sessions in `~/.config/agent-client/state.json`.

### Model Override

Override the bot's default model per-message:

```
/model gemini/gemini-2.5-pro     # set override
/model reset                      # clear override
```

The override persists across sessions until cleared.

### Attachments

Queue image attachments for the next message:

```
/attach ~/screenshot.png          # queue an image
Hello, can you analyze this?      # sends message + attachment
```

Supported formats: PNG, JPEG, GIF, WebP. Attachments are cleared after sending.

### Scoped API Keys

The `/setup` command creates a scoped API key with the minimum permissions needed for the CLI client:

```
/setup
```

This generates a key with scopes: `chat`, `sessions:read`, `sessions:write`, `bots:read`, `tools:read`, `tools:execute`, `tasks:read`, `channels:read`, `approvals:write`.

### Approval Handling

When the server requests approval for a tool call (e.g., a destructive operation), the client pauses streaming and presents an interactive prompt:

```
  Approval required: delete_file
  {"path": "/important/file.txt"}
  Approve? [Y/n]
```

### Cancellation

- **Ctrl+C during streaming** — sends a cancel request to the server and stops the stream
- **`/cancel`** — cancels any in-progress request for the current session
- **Ctrl+C during task polling** — stops polling for a queued task

When the session is busy (another request in progress), the client automatically switches to polling mode and waits for the queued task to complete.

### Voice Features

**Text-to-Speech** — Uses [Piper](https://github.com/rhasspy/piper), a fully local neural TTS engine. Enable with `--tts` flag or `/tts` command.

**Speech-to-Text** — Server-side transcription via [faster-whisper](https://github.com/SYSTRAN/faster-whisper). The client sends audio to `POST /transcribe`. Falls back to local transcription if server is unreachable.

**Wake Word** — Uses [openwakeword](https://github.com/dscripka/openWakeWord). Type `/listen` or start with `--listen`. Configure wake words:

```bash
# ~/.config/agent-client/config.env
WAKE_WORDS=hey_jarvis,hey_computer
```

**Silent Responses** — Bots can use `[nospeech]...[/nospeech]` tags to show text without speaking it aloud.

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
3. CLI flags (`--url`, `--key`, `--bot`, `--tts`, `--listen`, `--channel`)

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
