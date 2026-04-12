# Voice Assistant (Wyoming)

Voice interaction with your bots via the [Wyoming protocol](https://github.com/rhasspy/wyoming). Speak to a satellite device, get a spoken response from whichever bot/channel the device is bound to.

## How It Works

1. A satellite device (Raspberry Pi, ESP32, etc.) listens for a wake word
2. After wake word detection, it streams audio to this integration's TCP server
3. Audio is transcribed via Whisper (STT)
4. The transcript is dispatched to the bound Spindrel channel
5. The bot's response is synthesized via Piper (TTS)
6. Audio is streamed back to the satellite and played through its speaker

## Quick Start

### 1. Enable the Integration

Toggle the integration on in the admin UI. This starts the Whisper + Piper Docker containers automatically.

### 2. Configure Settings

- **Listen port**: TCP port for satellite connections (default: 10700)
- **Whisper URI**: STT service address (default: tcp://localhost:10300 — auto-started)
- **Piper URI**: TTS service address (default: tcp://localhost:10200 — auto-started)
- **Default voice**: Piper voice model (default: en_US-lessac-medium)

### 3. Bind a Channel

Create or select a channel in the admin UI and bind it to a Wyoming device:
- Set the client ID to `wyoming:<device-name>` (e.g., `wyoming:living-room`)
- Choose which bot handles this device

### 4. Connect a Satellite

#### Raspberry Pi (standalone, no Home Assistant needed)

Install `wyoming-satellite` on your Pi:

```bash
# Install dependencies
sudo apt-get install python3-venv python3-dev
python3 -m venv ~/wyoming-satellite
source ~/wyoming-satellite/bin/activate

# Install wyoming-satellite + wake word engine
pip install wyoming-satellite wyoming-openwakeword

# Run the satellite (replace YOUR_SERVER_IP)
wyoming-satellite \
  --name "living-room" \
  --uri "tcp://0.0.0.0:10700" \
  --mic-command "arecord -r 16000 -c 1 -f S16_LE -t raw" \
  --snd-command "aplay -r 22050 -c 1 -f S16_LE -t raw" \
  --wake-uri "tcp://127.0.0.1:10400" \
  --wake-word-name "hey_jarvis" \
  --awake-wav ~/sounds/awake.wav
```

Run openwakeword alongside it:

```bash
python3 -m wyoming_openwakeword \
  --uri "tcp://127.0.0.1:10400" \
  --preload-model "hey_jarvis"
```

The satellite will connect to your Spindrel server at `tcp://YOUR_SERVER_IP:10700`.

#### Testing from your Linux Desktop

Install the Wyoming CLI tools to test without hardware:

```bash
pip install wyoming

# Record a message and send it to your Wyoming server
python3 -c "
import asyncio
from wyoming.client import AsyncClient
from wyoming.audio import AudioStart, AudioChunk, AudioStop
import subprocess

async def test():
    client = AsyncClient('YOUR_SERVER_IP', 10700)
    await client.connect()

    # Record 3 seconds of audio
    proc = subprocess.run(
        ['arecord', '-d', '3', '-r', '16000', '-c', '1', '-f', 'S16_LE', '-t', 'raw'],
        capture_output=True
    )

    # Send audio
    await client.write_event(AudioStart(rate=16000, width=2, channels=1).event())
    await client.write_event(AudioChunk(rate=16000, width=2, channels=1, audio=proc.stdout).event())
    await client.write_event(AudioStop().event())

    # Read response audio events
    while True:
        event = await asyncio.wait_for(client.read_event(), timeout=30)
        if event is None:
            break
        print(f'Event: {event.type}')
        if event.type == 'audio-stop':
            break

asyncio.run(test())
"
```

#### M5Stack ATOM Echo (via Home Assistant)

The Echo uses ESPHome firmware which connects through Home Assistant:

1. Flash the Echo with ESPHome (see [ESPHome voice assistant docs](https://esphome.io/components/voice_assistant.html))
2. In HA, configure a Voice Pipeline with a custom conversation agent pointing to `tcp://YOUR_SERVER_IP:10700`
3. The Echo talks to HA, HA routes to your Spindrel Wyoming server

## Hardware Recommendations

| Device | Cost | Standalone? | Notes |
|--------|------|------------|-------|
| Raspberry Pi Zero 2W + ReSpeaker 2-Mic HAT | ~$25 | Yes | Best standalone option |
| Raspberry Pi 3/4 + ReSpeaker | ~$45 | Yes | More headroom |
| M5Stack ATOM Echo | ~$13 | Via HA | Cheapest, needs Home Assistant |

## Available Wake Words

Built-in models for `openwakeword` (run on-device):
- `hey_jarvis`
- `hey_mycroft`
- `ok_nabu`
- `alexa`

## Available Voices

Piper has dozens of voices. Browse at [rhasspy.github.io/piper-samples](https://rhasspy.github.io/piper-samples/). Change the voice in integration settings or per-device in the channel binding config.
