"""Env-driven config for the screenshot pipeline.

Reads ``scripts/screenshots/.env`` if present, else falls back to process
environment. No defaults for credentials — missing values raise at first use
instead of silently pointing at production.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

SCRIPTS_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPTS_ROOT.parent.parent

_ENV_PATH = SCRIPTS_ROOT / ".env"
if load_dotenv is not None and _ENV_PATH.exists():
    load_dotenv(_ENV_PATH)


def _require(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(
            f"Missing required env var {name!r}. "
            f"See {SCRIPTS_ROOT / '.env.example'}."
        )
    return val


def _optional(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip() or default


@dataclass(frozen=True)
class Config:
    api_url: str
    ui_url: str
    api_key: str
    login_email: str
    login_password: str
    ssh_alias: str
    ssh_container: str
    docs_images_dir: Path
    website_images_dir: Path


def load() -> Config:
    api_url = _require("SPINDREL_URL").rstrip("/")
    if "10.10.30.208" not in api_url and "localhost" not in api_url and "127.0.0.1" not in api_url:
        # Belt-and-suspenders: refuse to target production.
        raise RuntimeError(
            f"SPINDREL_URL {api_url!r} does not look like the e2e instance. "
            "Screenshots must come from the e2e server, not /opt/thoth-server/."
        )
    ui_url = _require("SPINDREL_UI_URL").rstrip("/")

    docs_dir = REPO_ROOT / _optional("DOCS_IMAGES_DIR", "docs/images")
    website_dir = REPO_ROOT / _optional("WEBSITE_IMAGES_DIR", "../spindrel-website/public/images/screenshots")

    return Config(
        api_url=api_url,
        ui_url=ui_url,
        api_key=_require("SPINDREL_API_KEY"),
        login_email=_optional("SPINDREL_LOGIN_EMAIL"),
        login_password=_optional("SPINDREL_LOGIN_PASSWORD"),
        ssh_alias=_optional("SSH_ALIAS", "spindrel-bot"),
        ssh_container=_optional("SSH_CONTAINER", "spindrel-local-e2e-spindrel-1"),
        docs_images_dir=docs_dir,
        website_images_dir=website_dir,
    )
