#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

source .venv/bin/activate

# Install with voice extras if --tts or --voice is in the args
if [[ " $* " == *" --tts "* ]] || [[ " $* " == *" --voice "* ]]; then
    pip install -q -e "client/[voice]"
else
    pip install -q -e client/
fi

# Pull API_KEY from .env if not already set
if [ -z "$API_KEY" ] && [ -f .env ]; then
    export $(grep -E '^API_KEY=' .env | xargs)
fi

agent-chat --key "${API_KEY:-dev}" --url "${AGENT_URL:-http://localhost:8000}" "$@"
