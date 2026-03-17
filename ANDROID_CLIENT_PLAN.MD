# Android Voice Assistant — Implementation Plan

## What This Is

A React Native app (Expo bare workflow) that runs as a background foreground service on Android/Fire OS. It listens for a wake word, captures speech, sends it to the agent server for transcription, sends the transcript to the chat endpoint, speaks the response via TTS, and displays a floating overlay on top of whatever app is foregrounded — including your Home Assistant dashboard.

---

## Expo vs React Native vs Java

**This is React Native with Expo bare workflow.** Almost everything is written in TypeScript. You only touch Java/Kotlin when writing or configuring native modules, which is minimal.

| Layer | Language |
|-------|----------|
| App UI and logic | TypeScript |
| Native foreground service | Java/Kotlin (small, mostly boilerplate or a library) |
| Overlay window | Java/Kotlin (small native module or library) |
| Build tooling | Gradle (Android) — you don't write this |

**Java/Android SDK is required on your machine to build locally.** Alternatively, EAS Build (Expo's cloud build service) handles all native compilation remotely — you push code, get an APK back, no local Android SDK needed. Free tier is available. This is the recommended path for getting started.

**Why bare workflow and not managed Expo?**
Managed Expo (Expo Go) sandboxes native access. Foreground services and `SYSTEM_ALERT_WINDOW` (overlay permission) require native Android APIs that managed Expo doesn't expose. Bare workflow gives you a full `android/` directory you can configure, while keeping the Expo toolchain and TypeScript DX.

---

## Architecture

```
Fire Tablet
─────────────────────────────────────────────
HA Dashboard (foreground, always visible)
      │
      │  (overlay drawn on top)
      ▼
┌─────────────────────────────┐
│   Floating Overlay (UI)     │  ← SYSTEM_ALERT_WINDOW
│   "Listening..." / response │
└─────────────────────────────┘

Background Foreground Service
─────────────────────────────
Porcupine wake word detection
      │ wake word detected
      ▼
Mic capture (expo-av)
      │ raw float32 audio
      ▼
POST /transcribe → Agent Server (Whisper)
      │ transcript text
      ▼
POST /chat/stream → Agent Server (SSE)
      │ response text + client_actions
      ▼
expo-speech TTS playback
+ overlay text update
```

---

## Permissions Required

| Permission | Purpose |
|------------|---------|
| `RECORD_AUDIO` | Mic access for wake word + recording |
| `FOREGROUND_SERVICE` | Keep process alive in background |
| `FOREGROUND_SERVICE_MICROPHONE` | Android 14+ mic in foreground service |
| `SYSTEM_ALERT_WINDOW` | Draw floating overlay on top of other apps |
| `INTERNET` | POST to agent server |
| `WAKE_LOCK` | Keep CPU alive while service runs |

---

## Key Libraries

| Library | Purpose | Notes |
|---------|---------|-------|
| `@picovoice/porcupine-react-native` | Wake word detection | Free tier, one built-in keyword |
| `expo-av` | Audio capture | Mic recording after wake word |
| `expo-speech` | TTS playback | Wraps Android native TTS engine |
| `expo-keep-awake` | Prevent screen sleep | Keep tablet awake |
| `fetch` / `XMLHttpRequest` | HTTP to agent server | SSE streaming via XHR onprogress |

**Not needed initially:**
- `@react-native-voice/voice` — future option for local on-device STT (configurable)
- `expo-task-manager` — evaluate if needed for foreground service vs custom native module
- `react-native-foreground-service` / `react-native-overlay-window` — evaluate library health before adopting

---

## STT Strategy

**Default: Server-side transcription** via `POST /transcribe`. The Android client records raw float32 audio at 16kHz, sends the buffer to the server, and gets back `{"text": "..."}`. The server runs Whisper (faster-whisper) — same model used by the Python CLI client.

**Future: Local on-device STT** as a configuration option. Android devices have built-in speech recognition (`@react-native-voice/voice`) that runs offline if the language pack is installed. This would be added as a setting: `sttMode: "server" | "local"`.

Benefits of server-side first:
- No extra native dependency on the client
- Same transcription quality as the Python client
- Works on all Android devices (no offline language pack needed)
- Simpler initial implementation

---

## Project Structure

```
android-client/
├── app/
│   ├── index.tsx              # Main chat screen, status bar, message bubbles
│   ├── settings.tsx           # Config screen (server URL, API key, bot, etc.)
│   └── _layout.tsx            # Navigation layout
│
├── src/
│   ├── agent.ts               # SSE streaming client, transcribe, session management
│   ├── config.ts              # Load/save config from AsyncStorage
│   ├── session.ts             # Session ID persistence
│   ├── voice/
│   │   ├── wakeword.ts        # Porcupine init + event handling (stub)
│   │   ├── stt.ts             # Server-side STT via POST /transcribe
│   │   └── tts.ts             # Text-to-speech via expo-speech
│   └── service/
│       └── VoiceService.ts    # Foreground service orchestration / state machine
│
├── android/                   # Native Android project (generated by expo prebuild)
│   └── app/
│       ├── build/outputs/apk/debug/app-debug.apk   # ← Debug APK output
│       └── src/main/
│           ├── AndroidManifest.xml
│           └── ...
│
├── app.json                   # Expo config with permissions
├── package.json
└── tsconfig.json
```

---

## Config

Stored in `AsyncStorage`, editable via in-app settings screen.

```
AGENT_URL=http://your-server:8000
API_KEY=your-bearer-key
BOT_ID=default
CLIENT_ID=tablet-living-room
WAKE_WORD=jarvis              # Porcupine keyword
TTS_ENABLED=true
OVERLAY_ENABLED=true
```

---

## Session Management

Identical contract to the Python CLI client:

- Session ID generated client-side as UUID on first run
- Persisted to `AsyncStorage`
- Sent with every `/chat/stream` request
- Server creates session on first sight, continues on resume
- New session triggered via settings screen or voice command handled server-side

---

## Foreground Service Design

The foreground service is the core of the app. It runs continuously, survives the app being backgrounded, and orchestrates the full voice pipeline.

**Persistent notification** (required by Android for foreground services) displays current state:
- `Listening for wake word...`
- `Hearing you...`
- `Thinking...`
- Last response snippet (truncated)

**State machine:**

```
IDLE (wake word listening)
      │ wake word detected
      ▼
LISTENING (mic recording + silence detection)
      │ silence detected
      ▼
PROCESSING (POST /transcribe → POST /chat/stream)
      │ response received
      ▼
RESPONDING (TTS playback + overlay display)
      │ playback complete
      ▼
IDLE
```

Each state transition updates both the persistent notification and the overlay.

---

## Overlay UI

A minimal floating view drawn via `SYSTEM_ALERT_WINDOW`. Appears on wake word detection, fades after response completes.

**States:**

| State | Overlay shows |
|-------|--------------|
| Wake word detected | Pulsing mic icon + "Listening..." |
| STT complete | Transcript text |
| Waiting for server | Spinner + transcript |
| Response received | Response text (scrollable if long) |
| TTS complete | Fades out after 3 seconds |

Design: dark semi-transparent pill anchored to bottom of screen. Unobtrusive over the HA dashboard. Tappable to dismiss early.

---

## Porcupine Wake Word

Free tier includes built-in keywords: `Jarvis`, `Hey Siri`, `Alexa`, `Picovoice`, `Porcupine`, `Bumblebee`, `Terminator`, `Grapefruit`, `Blueberry`, `Ok Google`.

Custom wake words (e.g. "Hey Home") require a Picovoice Console account — free account allows training custom keywords.

```typescript
// src/voice/wakeword.ts
import { Porcupine, BuiltInKeyword } from '@picovoice/porcupine-react-native';

const porcupine = await Porcupine.fromBuiltInKeywords(
  PICOVOICE_ACCESS_KEY,
  [BuiltInKeyword.JARVIS],
  ([keywordIndex]) => {
    onWakeWordDetected();
  }
);

await porcupine.start();
```

Access key is free from Picovoice Console — no credit card.

---

## TTS — expo-speech

Wraps Android's native TTS engine. Fully local, no internet.

Supports `[silent]...[/silent]` markers from the server — text inside markers is displayed but not spoken.

```typescript
// src/voice/tts.ts
import * as Speech from 'expo-speech';

export async function speak(text: string): Promise<void> {
  return new Promise((resolve) => {
    Speech.speak(text, {
      language: 'en-US',
      rate: 1.0,
      onDone: resolve,
    });
  });
}
```

---

## Agent Client

Uses **SSE streaming** via `POST /chat/stream` (matching the Python client), not plain `POST /chat`. This is critical for:

- Real-time tool status updates (`tool_start`, `tool_result`)
- Client-side tool execution (`tool_request` → execute → `POST /chat/tool_result`)
- `client_actions` handling (`new_session`, `switch_bot`, `switch_session`, `toggle_tts`)
- `[silent]...[/silent]` markers (text shown but not spoken via TTS)

SSE streaming uses `XMLHttpRequest.onprogress` in React Native (more reliable than `fetch` ReadableStream).

**Server-side transcription** via `POST /transcribe`:
- Accepts raw float32 audio at 16kHz as the request body
- Returns `{"text": "transcribed text"}`
- Content-Type: `application/octet-stream`

See `src/agent.ts` for the full implementation.

---

## Building

### Prerequisites

- **Android SDK** installed locally (Android Studio or standalone SDK)
- Set `ANDROID_HOME` environment variable, or create `android/local.properties` with `sdk.dir=/path/to/Android/Sdk`
- Java 17+
- Node.js 18+

### First-time setup

```bash
cd android-client
npm install
npx expo prebuild         # generates android/ directory from app.json
```

### Build & run (debug, to connected device/emulator)

```bash
ANDROID_HOME=/path/to/Android/Sdk npx expo run:android
```

### Build output

The debug APK is generated at:

```
android/app/build/outputs/apk/debug/app-debug.apk
```

### Release APK (for sideloading)

```bash
# Local release build
ANDROID_HOME=/path/to/Android/Sdk npx expo run:android --variant release
# → android/app/build/outputs/apk/release/app-release.apk

# OR cloud build via EAS (no local SDK needed)
npm install -g eas-cli
eas login
eas build:configure
eas build --platform android --profile preview
```

### Sideload to Fire Tablet

1. Enable developer mode on Fire tablet: Settings → Device Options → tap Serial Number 7 times
2. Enable ADB: Settings → Developer Options → Enable ADB
3. `adb connect <tablet-ip>:5555`
4. `adb install android/app/build/outputs/apk/debug/app-debug.apk`

---

## Build Phases

| Phase | What | Milestone |
|-------|------|-----------|
| 1 | Project scaffolding, bare workflow, permissions in manifest | App installs on tablet |
| 2 | Config screen + AsyncStorage (URL, key, bot, client ID) | Settings persist across restarts |
| 3 | Agent client (SSE streaming `/chat/stream`, session ID, client_actions) | Can send message, get streamed response |
| 4 | TTS — `expo-speech` with `[silent]` marker support | Response spoken aloud |
| 5 | Audio recording + server-side STT via `POST /transcribe` | Mic button: speak → transcript → response → TTS |
| 6 | Foreground service + persistent notification with state | App survives backgrounding |
| 7 | Porcupine wake word in foreground service | Hands-free trigger works |
| 8 | Floating overlay UI | Visual feedback over HA dashboard |
| 9 | Polish: error handling, reconnect logic, overlay animations | Production-ready |

Phases 1-5 can be built and tested as a normal foregrounded app. Phases 6-8 are the Android-specific native work.

---

## Fire OS Considerations

- Sideloading required — no Play Store
- Fire OS background killing is aggressive — foreground service with `WAKE_LOCK` is non-negotiable
- `SYSTEM_ALERT_WINDOW` must be manually granted by user in Settings → Apps → [App] → Display over other apps
- USB ADB works fine for development and sideloading
- Keep tablet plugged in and set to never sleep in display settings

---

## What You Don't Need

- Whisper on the client (server runs it via `POST /transcribe`)
- Piper (expo-speech uses Android's native TTS engine)
- Any server changes — uses existing `/transcribe`, `/chat/stream`, `/bots`, `/sessions` endpoints

## Future Enhancements

- **SSE streaming re-enablement**: Currently using `POST /chat` (non-streaming) because React Native's XHR drops SSE connections during server-side tool execution pauses, causing the server's `request.is_disconnected()` check to abort the loop. Fix options: (1) use `react-native-sse` library with proper keep-alive, (2) use `fetch` with `ReadableStream` + `TextDecoder` (requires RN 0.76+ / Hermes), or (3) add a server-side option to disable the `is_disconnected()` check for trusted clients. The `chatStream()` function in `agent.ts` is preserved and ready to swap back in. Streaming would enable real-time tool status in the overlay UI.
- **Local STT option**: Add `@react-native-voice/voice` as a configurable alternative to server-side transcription. Setting: `sttMode: "server" | "local"`. Local is faster (no network round-trip) but requires offline language packs.
- **Server-side TTS**: If the server adds a TTS endpoint, could stream audio back instead of using expo-speech.

## Implementation Status

| Phase | Status | Notes |
|-------|--------|-------|
| 1 | ✅ Done | Project scaffolded, permissions in app.json, structure created |
| 2 | ✅ Done | Config via AsyncStorage, settings screen with test connection |
| 3 | ✅ Done | Non-streaming `/chat` client (SSE broken in RN, see Future Enhancements), session management, client_actions |
| 4 | ✅ Done | TTS via expo-speech with [silent] marker support |
| 5 | ✅ Done | Audio recording (expo-av) + server-side STT + mic button with silence detection |
| 6 | Not started | Foreground service |
| 7 | Stub | Wake word interface defined, needs Porcupine |
| 8 | Not started | Floating overlay |
| 9 | Not started | Polish |
