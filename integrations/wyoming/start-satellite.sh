#!/bin/bash
# ============================================================================
# Wyoming Voice Satellite — Client Setup Script
# ============================================================================
#
# Run this on any Linux machine with a mic and speakers to create a voice
# satellite that Spindrel connects to. The satellite handles:
#   - Wake word detection (via openwakeword in Docker)
#   - Microphone capture
#   - Speaker playback
#
# Spindrel handles everything else (STT, bot dispatch, TTS).
#
# PREREQUISITES:
#   - Python 3 with venv support
#   - Docker (for openwakeword)
#   - ALSA utils (arecord/aplay) — usually pre-installed on Linux
#   - A microphone and speakers
#
# FIRST-TIME SETUP:
#   1. Create a venv and install the satellite:
#        python3 -m venv ~/wyoming-satellite
#        ~/wyoming-satellite/bin/pip install wyoming-satellite
#
#   2. Run this script:
#        bash start-satellite.sh
#
#   3. In Spindrel admin UI, bind a channel to this satellite:
#        - Type: wyoming
#        - Pick your satellite from the auto-discovered dropdown
#          (or manually enter client ID and satellite URI)
#
#   4. Start the Wyoming integration process in Spindrel
#
#   5. Say the wake word ("hey jarvis") and speak!
#
# CONFIGURATION (via environment variables):
#   WAKE_WORD        — wake word model (default: hey_jarvis)
#                      Options: hey_jarvis, hey_mycroft, ok_nabu, alexa
#   SATELLITE_PORT   — port the satellite listens on (default: 10700)
#   SATELLITE_NAME   — device name for Zeroconf discovery (default: desktop)
#   WAKE_PORT        — port for openwakeword service (default: 10400)
#   VENV             — path to the Python venv (default: ~/wyoming-satellite)
#   MIC_COMMAND      — custom mic capture command (auto-detects PipeWire vs ALSA)
#   SND_COMMAND      — custom speaker playback command (auto-detects PipeWire vs ALSA)
#
# EXAMPLES:
#   # Default (hey jarvis, port 10700):
#   bash start-satellite.sh
#
#   # Different wake word:
#   WAKE_WORD=ok_nabu bash start-satellite.sh
#
#   # Pi in the kitchen:
#   SATELLITE_NAME=kitchen SATELLITE_PORT=10701 bash start-satellite.sh
#
# STOP: Ctrl+C (cleans up both processes automatically)
# ============================================================================

set -euo pipefail

WAKE_WORD="${WAKE_WORD:-hey_jarvis}"
SATELLITE_PORT="${SATELLITE_PORT:-10700}"
SATELLITE_NAME="${SATELLITE_NAME:-desktop}"
WAKE_PORT="${WAKE_PORT:-10400}"

# Auto-detect audio commands: PipeWire (parecord/paplay) if available, else ALSA (arecord/aplay)
if [ -z "${MIC_COMMAND:-}" ]; then
    if command -v parecord &>/dev/null; then
        MIC_COMMAND="parecord --rate=16000 --channels=1 --format=s16le --raw"
        echo "  Audio: PipeWire (parecord)"
    else
        MIC_COMMAND="arecord -r 16000 -c 1 -f S16_LE -t raw -q"
        echo "  Audio: ALSA (arecord)"
    fi
fi
if [ -z "${SND_COMMAND:-}" ]; then
    if command -v paplay &>/dev/null; then
        SND_COMMAND="paplay --rate=22050 --channels=1 --format=s16le --raw"
    else
        SND_COMMAND="aplay -r 22050 -c 1 -f S16_LE -t raw -q"
    fi
fi
# Auto-detect venv: prefer ~/wyoming-satellite, fall back to ~/wyoming-client
if [ -z "${VENV:-}" ]; then
    if [ -f "$HOME/wyoming-satellite/bin/python" ]; then
        VENV="$HOME/wyoming-satellite"
    elif [ -f "$HOME/wyoming-client/bin/python" ]; then
        VENV="$HOME/wyoming-client"
    else
        VENV="$HOME/wyoming-satellite"
    fi
fi

# Check prerequisites
if ! command -v docker &>/dev/null; then
    echo "ERROR: Docker is required for the wake word engine."
    echo "       Install Docker and try again."
    exit 1
fi

if [ ! -f "$VENV/bin/python" ]; then
    echo "ERROR: Python venv not found at $VENV"
    echo ""
    echo "  Create it with:"
    echo "    python3 -m venv $VENV"
    echo "    $VENV/bin/pip install wyoming-satellite"
    echo ""
    exit 1
fi

if ! "$VENV/bin/python" -c "import wyoming_satellite" 2>/dev/null; then
    echo "ERROR: wyoming-satellite not installed in $VENV"
    echo ""
    echo "  Install it with:"
    echo "    $VENV/bin/pip install wyoming-satellite"
    echo ""
    exit 1
fi

cleanup() {
    echo ""
    echo "Shutting down..."
    docker stop wyoming-openwakeword 2>/dev/null || true
    kill $SAT_PID 2>/dev/null || true
    echo "Done."
}
trap cleanup EXIT

echo "=== Wyoming Voice Satellite ==="
echo "  Name:      ${SATELLITE_NAME}"
echo "  Port:      ${SATELLITE_PORT}"
echo "  Wake word: ${WAKE_WORD}"
echo ""
echo "  Spindrel will connect to this satellite at tcp://<this-ip>:${SATELLITE_PORT}"
echo ""

# 1. Start openwakeword in Docker
echo "Starting wake word engine (${WAKE_WORD})..."
docker rm -f wyoming-openwakeword 2>/dev/null || true
docker run -d \
    --name wyoming-openwakeword \
    -p "${WAKE_PORT}:${WAKE_PORT}" \
    rhasspy/wyoming-openwakeword \
    --uri "tcp://0.0.0.0:${WAKE_PORT}" \
    --preload-model "${WAKE_WORD}" \
    > /dev/null
echo "  Wake word engine running on port ${WAKE_PORT}"

# Wait for openwakeword to initialize
sleep 2

# 2. Start the satellite
echo "Starting satellite on port ${SATELLITE_PORT}..."
echo ""
echo "  Say '${WAKE_WORD}' to activate, then speak your message."
echo "  Press Ctrl+C to stop."
echo ""

"$VENV/bin/python" -m wyoming_satellite \
    --name "${SATELLITE_NAME}" \
    --uri "tcp://0.0.0.0:${SATELLITE_PORT}" \
    --mic-command "${MIC_COMMAND}" \
    --snd-command "${SND_COMMAND}" \
    --wake-uri "tcp://127.0.0.1:${WAKE_PORT}" \
    --wake-word-name "${WAKE_WORD}" \
    --debug &
SAT_PID=$!

wait $SAT_PID
