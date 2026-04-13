# Voice Assistant (Wyoming)

Voice interaction with your bots via the [Wyoming protocol](https://github.com/rhasspy/wyoming). Bind a Wyoming satellite device to a Spindrel channel — speak to it, get a spoken response from the bound bot. Transcripts appear in the channel like any other message.

## How It Works

1. A satellite device (Raspberry Pi, desktop, etc.) runs `wyoming-satellite` with a wake word engine
2. The Spindrel integration connects to the satellite over TCP as a pipeline orchestrator
3. When you say the wake word, the satellite streams your audio to Spindrel
4. Spindrel transcribes via Whisper (STT) and posts the transcript to the bound channel
5. The bot responds in the channel
6. Spindrel synthesizes the response via Piper (TTS) and sends audio back to the satellite
7. The satellite plays the response through its speaker

Voice is just another integration binding — like Slack. Messages appear in the web UI, and if the channel is also mirrored to Slack, the transcript shows up there too.

## Quick Start

### 1. Enable the Integration

Toggle the integration on in the admin UI. Set `WYOMING_CONTAINERS` to `true` to auto-start the Whisper + Piper Docker containers.

### 2. Set Up a Satellite

#### Desktop (for testing)

```bash
# Terminal 1: start the wake word engine
docker run -d --name wyoming-openwakeword \
  -p 10400:10400 \
  rhasspy/wyoming-openwakeword \
  --uri tcp://0.0.0.0:10400 \
  --preload-model hey_jarvis

# Terminal 2: start the satellite
~/wyoming-client/bin/python -m wyoming_satellite \
  --name desktop \
  --uri tcp://0.0.0.0:10700 \
  --mic-command "arecord -r 16000 -c 1 -f S16_LE -t raw -q" \
  --snd-command "aplay -r 22050 -c 1 -f S16_LE -t raw -q" \
  --wake-uri tcp://127.0.0.1:10400 \
  --wake-word-name hey_jarvis \
  --vad
```

#### Raspberry Pi

```bash
# Install
sudo apt-get install python3-venv python3-dev
python3 -m venv ~/wyoming-satellite
source ~/wyoming-satellite/bin/activate
pip install wyoming-satellite

# Run (replace mic/speaker devices as needed)
python -m wyoming_satellite \
  --name living-room \
  --uri tcp://0.0.0.0:10700 \
  --mic-command "arecord -D plughw:CARD=seeed2micvoicec -r 16000 -c 1 -f S16_LE -t raw -q" \
  --snd-command "aplay -D plughw:CARD=seeed2micvoicec -r 22050 -c 1 -f S16_LE -t raw -q" \
  --wake-uri tcp://127.0.0.1:10400 \
  --wake-word-name hey_jarvis \
  --vad
```

Run openwakeword on the Pi too:
```bash
docker run -d --name wyoming-openwakeword \
  -p 10400:10400 \
  rhasspy/wyoming-openwakeword \
  --uri tcp://0.0.0.0:10400 \
  --preload-model hey_jarvis
```

### 3. Set Up an ESPHome Device (ATOM Echo)

The M5Stack ATOM Echo is a $13 ESP32 device with built-in mic and speaker. No separate wake word engine needed — push-to-talk via the built-in button.

#### Flash the firmware

```bash
cd integrations/wyoming
# Create secrets.yaml with your WiFi credentials
echo 'wifi_ssid: "YourSSID"' > secrets.yaml
echo 'wifi_password: "YourPassword"' >> secrets.yaml

# Build and flash (first time requires USB, subsequent via OTA)
esphome run atom-echo.yaml
```

The firmware includes a patched `voice_assistant` component (in `custom_components/`) that fixes a buffer deallocation bug in ESPHome 2026.3.3. This patch is required for audio playback to work.

#### Verify the device

- **Blue LED** = connected to Spindrel
- **Double-click button** = play a test tone (confirms speaker works)
- **Hold button** = push-to-talk (speak, release to process)

### 4. Bind a Channel

In the Spindrel admin UI:
1. Create or select a channel
2. Add a Wyoming binding with client ID (e.g. `wyoming:living-room` or `wyoming:atom-echo`)
3. Set **Protocol** to either "Wyoming (Pi satellite)" or "ESPHome (ATOM Echo / ESP32)"
4. Set **Device URI**:
   - Wyoming: `tcp://192.168.1.50:10700`
   - ESPHome: `tcp://10.10.20.129:6053` (device IP, port 6053)
5. For ESPHome: set **ESPHome Device Name** to the `name` from your YAML (e.g. `atom-echo`)
6. Optionally set **Piper Voice** to override the default voice for this device

### 5. Talk to It

- **Wyoming satellite**: Say the wake word → wait for beep → speak → hear response
- **ATOM Echo**: Hold button → speak → release → hear response

Transcripts and bot responses appear in the channel's web UI (and Slack if mirrored).

## Configuration

### Integration Settings (admin UI)

| Setting | Default | Description |
|---------|---------|-------------|
| WYOMING_WHISPER_URI | tcp://localhost:10300 | Whisper STT service |
| WYOMING_PIPER_URI | tcp://localhost:10200 | Piper TTS service |
| WYOMING_DEFAULT_VOICE | en_US-lessac-medium | Default Piper voice |
| WYOMING_CONTAINERS | true | Auto-start Whisper + Piper Docker containers |
| ESPHOME_API_PASSWORD | (empty) | ESPHome API password if devices use auth |

### Per-Device Binding Config

| Field | Required | Description |
|-------|----------|-------------|
| protocol | yes | `wyoming` or `esphome` |
| satellite_uri | yes | TCP address of the device |
| esphome_device_name | ESPHome only | Device name from YAML (for identification on connect) |
| voice | no | Override the default Piper TTS voice for this device |

### Changing the TTS Voice

Set the **Piper Voice** field in the channel binding config, or change `WYOMING_DEFAULT_VOICE` for all devices. Browse available voices at [rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/).

Common voices:
- `en_US-lessac-medium` (default, clear male)
- `en_US-amy-medium` (female)
- `en_US-danny-low` (casual male, lower quality but faster)
- `en_GB-alan-medium` (British male)

## Available Wake Words

Built-in `openwakeword` models (Wyoming satellites only — ESPHome uses push-to-talk):
- `hey_jarvis`
- `hey_mycroft`
- `ok_nabu`
- `alexa`

## ESPHome Firmware Notes

### Custom Component Patch

The `custom_components/voice_assistant/` directory contains a patched version of ESPHome's `voice_assistant` component. It fixes a bug in ESPHome 2026.3.3 where the IDLE state deallocates the speaker buffer, but STREAMING_RESPONSE still tries to read into it — causing a crash (StoreProhibited). The patch reallocates the buffer if needed when entering STREAMING_RESPONSE.

### Audio Mode

The integration uses **UDP audio mode** (not API/protobuf mode). The device streams mic audio via UDP to Spindrel, and Spindrel sends TTS audio back the same way. This avoids a separate ESPHome bug where API audio mode leaves the device's UDP socket null, preventing audio playback entirely.

### Wake Word Support

ESPHome devices can support on-device wake words via `micro_wake_word` (runs a TFLite model on the ESP32). This is not yet implemented in the integration but would replace push-to-talk:

```yaml
# Add to atom-echo.yaml for wake word support (future)
micro_wake_word:
  model: hey_jarvis
  on_wake_word_detected:
    - voice_assistant.start:
```

The integration would need to handle the wake word event instead of relying on button press/release.

## Hardware

| Device | Cost | Protocol | Notes |
|--------|------|----------|-------|
| M5Stack ATOM Echo | ~$13 | ESPHome | Push-to-talk, tiny, built-in mic+speaker |
| Raspberry Pi Zero 2W + ReSpeaker 2-Mic HAT | ~$25 | Wyoming | Best standalone satellite, wake word support |
| Raspberry Pi 3/4 + ReSpeaker | ~$45 | Wyoming | More headroom |
| Any Linux machine with mic + speakers | $0 | Wyoming | Great for testing |
