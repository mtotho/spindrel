#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    echo "Creating virtualenv..."
    python -m venv .venv
fi

source .venv/bin/activate

if [ ! -f .env ]; then
    echo "No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "Edit .env with your settings before continuing."
    exit 1
fi

set -a
source .env
set +a

pip install -q -e ".[dev]"

echo "Starting services (postgres, searxng, playwright)..."
docker compose up postgres searxng playwright -d

echo "Waiting for postgres..."
until docker compose exec postgres pg_isready -U agent -d agentdb -q 2>/dev/null; do
    sleep 1
done

PIDS=()
cleanup() {
    for pid in "${PIDS[@]}"; do kill "$pid" 2>/dev/null || true; done
}
trap cleanup EXIT INT TERM

# Auto-discover and start integration background processes
while IFS= read -r line; do
    [[ "$line" == \#* ]] && { echo "$line"; continue; }
    [ -z "$line" ] && continue
    echo "Starting: $line"
    eval "$line" &
    PIDS+=($!)
done < <(python scripts/list_integration_processes.py 2>/dev/null)

echo "Starting server with --reload..."
uvicorn app.main:app --host 0.0.0.0 --reload --reload-include '*.py' --reload-include '*.yaml' --reload-exclude '.venv'
