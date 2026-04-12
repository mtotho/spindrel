#!/bin/bash
# Wyoming voice satellite — runs on the client device (desktop, Pi, etc.)
#
# This starts:
#   1. openwakeword (Docker) — listens for wake words
#   2. wyoming-satellite — captures mic, plays speaker, exposes Wyoming TCP server
#
# The Spindrel integration connects TO this satellite as a pipeline orchestrator.
#
# Usage:
#   ~/wyoming-client/start-satellite.sh                       # defaults
#   WAKE_WORD=ok_nabu ~/wyoming-client/start-satellite.sh     # different wake word
#   SATELLITE_PORT=10701 ~/wyoming-client/start-satellite.sh  # different port
#
# Stop: Ctrl+C (cleans up both processes)

set -euo pipefail

WAKE_WORD="${WAKE_WORD:-hey_jarvis}"
SATELLITE_PORT="${SATELLITE_PORT:-10700}"
WAKE_PORT="${WAKE_PORT:-10400}"
SATELLITE_NAME="${SATELLITE_NAME:-desktop}"

VENV=~/wyoming-client

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
echo "  Spindrel connects to this satellite at tcp://<your-ip>:${SATELLITE_PORT}"
echo "  Add this URI as 'satellite_uri' in the channel binding's activation config."
echo ""

# 1. Start openwakeword in Docker
echo "Starting wake word engine (${WAKE_WORD})..."
docker rm -f wyoming-openwakeword 2>/dev/null || true
docker run -d \
    --name wyoming-openwakeword \
    -p ${WAKE_PORT}:${WAKE_PORT} \
    rhasspy/wyoming-openwakeword \
    --uri "tcp://0.0.0.0:${WAKE_PORT}" \
    --preload-model "${WAKE_WORD}" \
    > /dev/null
echo "  Wake word engine running on port ${WAKE_PORT}"

# Wait for it to be ready
sleep 2

# 2. Start the satellite
echo "Starting satellite on port ${SATELLITE_PORT}..."
echo "  Say '${WAKE_WORD}' to activate, then speak your message."
echo "  Press Ctrl+C to stop."
echo ""

$VENV/bin/python -m wyoming_satellite \
    --name "${SATELLITE_NAME}" \
    --uri "tcp://0.0.0.0:${SATELLITE_PORT}" \
    --mic-command "arecord -r 16000 -c 1 -f S16_LE -t raw -q" \
    --snd-command "aplay -r 22050 -c 1 -f S16_LE -t raw -q" \
    --wake-uri "tcp://127.0.0.1:${WAKE_PORT}" \
    --wake-word-name "${WAKE_WORD}" \
    --debug &
SAT_PID=$!

wait $SAT_PID
