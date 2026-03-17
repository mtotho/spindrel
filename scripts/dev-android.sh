#!/usr/bin/env bash
set -e

cd "$(dirname "$0")/.."

if [ ! -f .env ]; then
    echo "No .env file found. Copying from .env.example..."
    cp .env.example .env
    echo "Edit .env with your settings before continuing."
    exit 1
fi

cd android-client

echo "Generating build config from .env..."
node scripts/generate-env.js

echo "Installing dependencies..."
npm install --silent

# Clean native build if --clean flag passed
if [[ "$1" == "--clean" ]]; then
    echo "Cleaning native build..."
    cd android && ./gradlew clean -q && cd ..
fi

echo "Building and running on Android..."
npx expo run:android
