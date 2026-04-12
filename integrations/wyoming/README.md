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

### 3. Bind a Channel

In the Spindrel admin UI:
1. Create or select a channel
2. Add a Wyoming binding with client ID `wyoming:desktop` (or `wyoming:living-room`, etc.)
3. Set the activation config:
   ```json
   {"satellite_uri": "tcp://192.168.1.50:10700"}
   ```
4. The integration will automatically connect to the satellite

### 4. Talk to It

Say "hey jarvis" → wait for the beep → speak your message → hear the response.

The transcript and bot response will appear in the channel's web UI (and Slack if mirrored).

## Configuration

| Setting | Default | Description |
|---------|---------|-------------|
| WYOMING_WHISPER_URI | tcp://localhost:10300 | Whisper STT service |
| WYOMING_PIPER_URI | tcp://localhost:10200 | Piper TTS service |
| WYOMING_DEFAULT_VOICE | en_US-lessac-medium | Default Piper voice |
| WYOMING_CONTAINERS | true | Auto-start Whisper + Piper Docker containers |

Per-device overrides go in the channel binding's `activation_config`:
- `satellite_uri` (required) — the satellite's TCP address
- `voice` — override the default Piper voice for this device
- `wake_words` — (Phase 2) map wake words to different channels

## Available Wake Words

Built-in `openwakeword` models (run on the satellite device):
- `hey_jarvis`
- `hey_mycroft`
- `ok_nabu`
- `alexa`

## Available Voices

Piper has dozens of voices. Browse at [rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/).

## Hardware

| Device | Cost | Notes |
|--------|------|-------|
| Raspberry Pi Zero 2W + ReSpeaker 2-Mic HAT | ~$25 | Best standalone satellite |
| Raspberry Pi 3/4 + ReSpeaker | ~$45 | More headroom |
| Any Linux machine with mic + speakers | $0 | Great for testing |
