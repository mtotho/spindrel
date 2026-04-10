#!/usr/bin/env bash
# Spindrel — Interactive Setup
# Usage: curl -fsSL https://raw.githubusercontent.com/mtotho/spindrel/master/setup.sh | bash
#        or: bash setup.sh
set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
BOLD='\033[1m'
DIM='\033[2m'
RESET='\033[0m'

info()  { echo -e "${CYAN}$*${RESET}"; }
ok()    { echo -e "${GREEN}$*${RESET}"; }
err()   { echo -e "${RED}$*${RESET}" >&2; }
bold()  { echo -e "${BOLD}$*${RESET}"; }

# ── Banner ──────────────────────────────────────────────────────────────────

echo ""
bold "  ┌─────────────────────────────────┐"
bold "  │         s p i n d r e l          │"
bold "  │     self-hosted ai agent server  │"
bold "  └─────────────────────────────────┘"
echo -e "  ${DIM}your entire RAG loop, silk-wrapped.${RESET}"
echo ""

# ── Prerequisites ───────────────────────────────────────────────────────────

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        err "Required: $1 is not installed."
        return 1
    fi
}

info "Checking prerequisites..."
missing=0
check_cmd git       || missing=1
check_cmd docker    || missing=1
check_cmd python3   || missing=1

# Check docker compose (v2 plugin)
if ! docker compose version &>/dev/null 2>&1; then
    err "Required: docker compose (v2 plugin) is not available."
    missing=1
fi

# Check Python version
py_version=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "0.0")
py_major=${py_version%%.*}
py_minor=${py_version##*.}
if [ "$py_major" -lt 3 ] || { [ "$py_major" -eq 3 ] && [ "$py_minor" -lt 12 ]; }; then
    err "Required: Python 3.12+ (found $py_version)"
    missing=1
fi

# Check pip / ensurepip availability
if ! python3 -m pip --version &>/dev/null && ! python3 -c "import ensurepip" &>/dev/null; then
    err "Required: pip or ensurepip for Python. Install python3-pip (or python3-venv on Debian/Ubuntu)."
    missing=1
fi

if [ "$missing" -ne 0 ]; then
    echo ""
    err "Please install the missing prerequisites and try again."
    exit 1
fi
ok "All prerequisites met (Python $py_version, docker compose)"

# ── Clone repo if needed ────────────────────────────────────────────────────

if [ ! -f "app/main.py" ]; then
    if [ -d ".git" ]; then
        err "This doesn't look like the spindrel repo (no app/main.py)."
        err "Run this script from the repo root, or in an empty directory to clone."
        exit 1
    fi
    info "Cloning spindrel..."
    git clone https://github.com/mtotho/spindrel.git .
    ok "Cloned."
fi

# ── Create temp venv + install questionary ──────────────────────────────────

SETUP_VENV=".setup-venv"

cleanup_venv() {
    if [ -d "$SETUP_VENV" ]; then
        rm -rf "$SETUP_VENV"
    fi
}
trap cleanup_venv EXIT

if [ ! -d "$SETUP_VENV" ]; then
    info "Creating temporary setup environment..."
    python3 -m venv "$SETUP_VENV" 2>/dev/null || {
        # Some systems need --without-pip + ensurepip
        python3 -m venv "$SETUP_VENV" --without-pip
        "$SETUP_VENV/bin/python" -m ensurepip --upgrade -q
    }
    # questionary only needed for interactive mode
    if [ "${SPINDREL_HEADLESS:-}" != "1" ]; then
        "$SETUP_VENV/bin/python" -m pip install -q questionary pyyaml
    else
        "$SETUP_VENV/bin/python" -m pip install -q pyyaml
    fi
fi

# ── Run Python wizard ──────────────────────────────────────────────────────

"$SETUP_VENV/bin/python" scripts/setup.py
