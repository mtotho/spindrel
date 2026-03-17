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

# Argument parsing for --clean and --device (no device ID for --device)
CLEAN_FLAG=""
DEVICE_FLAG=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --clean)
            CLEAN_FLAG="yes"
            shift
            ;;
        --device)
            DEVICE_FLAG="yes"
            shift
            ;;
        *)
            # Ignore unknown argument or allow for extension
            shift
            ;;
    esac
done

# Clean native build if --clean flag passed
if [[ "$CLEAN_FLAG" == "yes" ]]; then
    echo "Cleaning native build..."
    cd android && ./gradlew clean -q && cd ..
fi

echo "Building and running on Android..."
if [[ "$DEVICE_FLAG" == "yes" ]]; then
    npx expo run:android --device
else
    npx expo run:android
fi
