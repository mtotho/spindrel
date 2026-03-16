# Android Voice Assistant — Implementation Plan

## What This Is

A React Native app (Expo bare workflow) that runs as a background foreground service on Android/Fire OS. It listens for a wake word, captures speech, sends it to the agent server, speaks the response via TTS, and displays a floating overlay on top of whatever app is foregrounded — including your Home Assistant dashboard.

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
      │
      ▼
Android on-device STT
      │ transcript
      ▼
POST /chat → Agent Server
      │ response text
      ▼
expo-speech TTS playback
+ overlay text update
```

---

## Permissions Required

| Permission | Purpose |
|------------|---------|
| `RECORD_AUDIO` | Mic access for wake word + STT |
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
| `@react-native-voice/voice` | Android on-device STT | No Whisper needed, instant, free |
| `expo-speech` | TTS playback | Wraps Android native TTS engine |
| `expo-task-manager` | Background task registration | Required for foreground service |
| `react-native-foreground-service` | Foreground service + notification | Keeps process alive |
| `react-native-overlay-window` | `SYSTEM_ALERT_WINDOW` overlay | Floating UI over HA dashboard |
| `expo-keep-awake` | Prevent screen sleep | Keep tablet awake |
| `axios` or `fetch` | HTTP to agent server | Simple REST calls |

---

## Project Structure

```
android-client/
├── app/
│   ├── index.tsx              # App entry, service bootstrap
│   ├── overlay.tsx            # Floating overlay UI component
│   ├── settings.tsx           # Config screen (server URL, API key, bot)
│   └── _layout.tsx
│
├── src/
│   ├── agent.ts               # POST /chat, session management
│   ├── config.ts              # Load/save config from AsyncStorage
│   ├── session.ts             # Session ID persistence
│   ├── voice/
│   │   ├── wakeword.ts        # Porcupine init + event handling
│   │   ├── stt.ts             # Speech-to-text wrapper
│   │   └── tts.ts             # Text-to-speech wrapper
│   └── service/
│       └── VoiceService.ts    # Foreground service orchestration
│
├── android/                   # Native Android project (bare workflow)
│   └── app/
│       └── src/main/
│           ├── AndroidManifest.xml   # Permissions declared here
│           └── ...
│
├── app.json
├── package.json
└── .env                       # AGENT_URL, API_KEY, BOT_ID
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
- Sent with every `/chat` request
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
LISTENING (mic recording + VAD)
      │ silence detected
      ▼
PROCESSING (STT → POST /chat)
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

## STT — Android On-Device

`@react-native-voice/voice` wraps Android's built-in speech recognition. Runs on-device (Pixel/Fire tablets have local models), no API call, instant response.

```typescript
// src/voice/stt.ts
import Voice from '@react-native-voice/voice';

Voice.onSpeechResults = (e) => {
  const transcript = e.value?.[0] ?? '';
  onTranscript(transcript);
};

await Voice.start('en-US');
```

Note: Android on-device STT requires the device to have the offline language pack installed. Fire tablets have this by default for English.

---

## TTS — expo-speech

Wraps Android's native TTS engine. Fully local, no internet.

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

See `src/agent.ts` for the full implementation.

---

## Build and Sideload to Fire Tablet

### Prerequisites

Either:
- **Local build**: Android Studio + SDK installed, Java 17+
- **Cloud build**: EAS account (free tier), no local SDK needed — recommended

### Steps

```bash
# Create project
npx create-expo-app android-client --template bare-minimum
cd android-client

# Install dependencies
npx expo install expo-av expo-speech expo-task-manager expo-keep-awake
npm install @picovoice/porcupine-react-native @react-native-voice/voice
npm install react-native-foreground-service react-native-overlay-window
npm install @react-native-async-storage/async-storage uuid

# Build APK (cloud)
npm install -g eas-cli
eas login
eas build:configure
eas build --platform android --profile preview
# → downloads APK when done

# OR build locally
npx expo run:android --variant release
```

### Sideload to Fire Tablet

1. Enable developer mode on Fire tablet: Settings → Device Options → tap Serial Number 7 times
2. Enable ADB: Settings → Developer Options → Enable ADB
3. `adb connect <tablet-ip>:5555`
4. `adb install app-release.apk`

---

## Build Phases

| Phase | What | Milestone |
|-------|------|-----------|
| 1 | Project scaffolding, bare workflow, permissions in manifest | App installs on tablet |
| 2 | Config screen + AsyncStorage (URL, key, bot, client ID) | Settings persist across restarts |
| 3 | Agent client (`/chat` POST, session ID) | Can send hardcoded message, get response |
| 4 | TTS — `expo-speech` | Response spoken aloud |
| 5 | STT — `@react-native-voice/voice` | Can speak, get transcript, send to server, hear response |
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

- Whisper (Android on-device STT is sufficient and faster)
- Piper (expo-speech uses Android's native TTS engine)
- Any server changes — the `/chat/stream` endpoint contract is identical to the Python CLI client

## Implementation Status

| Phase | Status | Notes |
|-------|--------|-------|
| 1 | ✅ Done | Project scaffolded, permissions in app.json, structure created |
| 2 | ✅ Done | Config via AsyncStorage, settings screen with test connection |
| 3 | ✅ Done | SSE streaming agent client, session management, client_actions |
| 4 | ✅ Done | TTS via expo-speech with [silent] marker support |
| 5 | Stub | STT interface defined, needs @react-native-voice/voice |
| 6 | Not started | Foreground service |
| 7 | Stub | Wake word interface defined, needs Porcupine |
| 8 | Not started | Floating overlay |
| 9 | Not started | Polish |