# Building for iOS & Android

## Current Status

The app is built on Expo 55 / React Native 0.83.2 with expo-router — all of which
support iOS, Android, and web from the same codebase. The **chat screen, sidebar,
navigation, auth, and most admin pages** already use cross-platform React Native
components and will work on native.

### What works on native today
- Channel list, chat screen, message input, streaming
- Sidebar navigation, all Pressable/Link-based nav
- Auth flow (login, setup) — AsyncStorage for token persistence
- Safe area handling (SafeAreaProvider wired up)
- All Zustand stores, TanStack Query, SSE streaming

### What will crash on native (raw HTML, no Platform.OS guards)

| File | Issue | Used by |
|------|-------|---------|
| `src/components/shared/FormControls.tsx` | `<div>`, `<input>`, `<select>`, `<button>`, `<label>` | Channel settings, bot editor, all admin forms |
| `src/components/workspace/FileViewer.tsx` | `<div>`, `<textarea>`, `<pre>`, `<code>` | Workspace file browser |
| `src/components/workspace/SplitViewContainer.tsx` | `<div>`, `offsetWidth` DOM measurement | Workspace split pane |
| `src/components/workspace/ResizeHandle.tsx` | `document.addEventListener`, `body.style.cursor` | Workspace split pane |

**MessageBubble.tsx** uses HTML for markdown rendering but is already behind a
`Platform.OS === "web"` check — it falls back to plain `<Text>` on native.
Markdown rendering on native would need a library like `react-native-markdown-display`.

---

## Quick Start: Run on Device (Development)

### Prerequisites
- Node.js 18+
- Expo CLI: `npm install -g expo-cli` (or use `npx expo`)
- **iOS**: macOS with Xcode 15+ installed, iOS Simulator or physical device
- **Android**: Android Studio with an emulator, or physical device with USB debugging

### 1. Install dependencies
```bash
cd ui
npm install
```

### 2. Run on iOS Simulator
```bash
npx expo run:ios
```
This runs `expo prebuild` automatically (generates the `ios/` directory) then
builds and launches in the simulator.

### 3. Run on Android Emulator
```bash
npx expo run:android
```
Same — generates `android/`, builds, and launches.

### 4. Run on physical device (Expo Go)
```bash
npx expo start
```
Scan the QR code with Expo Go (iOS App Store / Google Play). Note: Expo Go has
limitations with some native modules — if something crashes, use a dev build instead.

### 5. Dev build on physical device (recommended)
```bash
npx expo prebuild --clean
npx expo run:ios --device    # picks your connected iPhone
npx expo run:android --device
```

---

## Production Builds with EAS

EAS (Expo Application Services) builds native binaries in the cloud — no need for
a Mac to build iOS.

### 1. Install EAS CLI
```bash
npm install -g eas-cli
eas login   # create account at expo.dev if needed
```

### 2. Configure the project

Add bundle identifiers to `app.json`:
```json
{
  "expo": {
    "ios": {
      "supportsTablet": true,
      "bundleIdentifier": "com.yourname.thoth"
    },
    "android": {
      "package": "com.yourname.thoth",
      "adaptiveIcon": { ... }
    }
  }
}
```

### 3. Create eas.json
```bash
eas build:configure
```

Or create `eas.json` manually:
```json
{
  "cli": { "version": ">= 3.0.0" },
  "build": {
    "development": {
      "developmentClient": true,
      "distribution": "internal"
    },
    "preview": {
      "distribution": "internal"
    },
    "production": {}
  },
  "submit": {
    "production": {}
  }
}
```

### 4. Build

```bash
# iOS (TestFlight / Ad Hoc)
eas build --platform ios --profile preview

# Android (APK for sideloading)
eas build --platform android --profile preview

# Both
eas build --platform all --profile preview
```

EAS builds in the cloud and gives you a download link. For iOS ad-hoc builds,
you'll need to register your device UDID first:
```bash
eas device:create
```

### 5. Submit to stores
```bash
eas submit --platform ios      # App Store Connect
eas submit --platform android  # Google Play Console
```

---

## iOS-Specific Setup

### Apple Developer Account
- Required for device testing and App Store ($99/year)
- Free account works for simulator only
- Sign up at https://developer.apple.com

### Signing & Provisioning
EAS handles this automatically. On first build it will:
1. Create a Distribution Certificate
2. Create a Provisioning Profile
3. Store them in your EAS account

For local builds (`expo run:ios`), Xcode handles signing with your Apple ID.

### TestFlight
After `eas build --profile production`, use `eas submit` to push to TestFlight.
Add testers via App Store Connect.

---

## Android-Specific Setup

### Signing Key
EAS auto-generates a keystore on first build. To manage manually:
```bash
eas credentials --platform android
```

### APK vs AAB
- `eas build` produces an AAB (Android App Bundle) for Play Store
- For direct install / sideloading, add to your build profile:
  ```json
  "preview": {
    "distribution": "internal",
    "android": { "buildType": "apk" }
  }
  ```

### Install APK on device
Download the APK from the EAS build URL and install:
```bash
adb install path/to/app.apk
```
Or open the download link directly on your Android device.

---

## Server Connection

The app stores the server URL at login time. For mobile:
- Your phone must be able to reach the agent-server (port 8000)
- For local dev: use your machine's LAN IP (e.g., `http://192.168.1.x:8000`)
- For production: use your public domain/IP with HTTPS

The login screen auto-detects `window.location` on web but on native you'll
type the server URL manually.

---

## Fixing Native Blockers (Roadmap)

To get full native support, these components need React Native alternatives:

### Priority 1: FormControls.tsx
Replace raw `<input>`, `<select>`, `<button>` with RN equivalents:
- `<input type="text">` → `<TextInput>`
- `<select>` → custom picker or `@react-native-picker/picker`
- `<button>` → `<Pressable>`
- `<div>` → `<View>`
- `<label>` → `<Text>`

This unblocks all admin forms (bot editor, channel settings, etc.).

### Priority 2: Markdown rendering on native
Install `react-native-markdown-display` and use it in the `Platform.OS !== "web"`
branch of MessageBubble.

### Priority 3: Workspace components
FileViewer, SplitViewContainer, and ResizeHandle are web-only. Options:
- Gate them behind `Platform.OS === "web"` and show a "not available on mobile" message
- Rewrite with `<TextInput multiline>` for editing, single-pane layout on native

### Priority 4: lucide-react icons
These may or may not render on native. Test first — if broken, swap to
`lucide-react-native` (same API, native SVG rendering).
