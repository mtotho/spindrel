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

echo "Starting services (postgres)..."
docker compose up postgres -d

echo "Waiting for postgres..."
until docker compose exec postgres pg_isready -U agent -d agentdb -q 2>/dev/null; do
    sleep 1
done

# Integration processes are now managed by the server's process manager
# (app/services/integration_processes.py) — auto-started during lifespan.
# Control them via Admin UI > Integrations or the /api/v1/admin/integrations/{id}/process endpoints.

echo "Starting server with --reload..."
uvicorn app.main:app --host 0.0.0.0 --reload --reload-include '*.py' --reload-include '*.yaml' --reload-exclude '.venv'
