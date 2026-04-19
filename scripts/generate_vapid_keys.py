#!/usr/bin/env python3
"""Generate a Web Push VAPID keypair and print `.env` lines.

Run once when setting up push notifications::

    python scripts/generate_vapid_keys.py

Copy the three lines it prints into `.env`, restart the server, and the
push router + `send_push_notification` tool will activate.

Uses the same P-256 EC curve pywebpush/browsers require. `VAPID_SUBJECT`
must be a mailto URL or https URL you control — browsers expose it in
push-service diagnostics and may rate-limit anonymous subjects.
"""
from __future__ import annotations

import base64
import sys

try:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PrivateFormat, PublicFormat,
    )
except ImportError:
    print("Missing cryptography. Install with: pip install cryptography", file=sys.stderr)
    sys.exit(1)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def main() -> None:
    priv = ec.generate_private_key(ec.SECP256R1())
    pub = priv.public_key()

    # VAPID wants raw 32-byte private scalar + uncompressed 65-byte public key,
    # both base64url-encoded without padding.
    priv_number = priv.private_numbers().private_value
    priv_bytes = priv_number.to_bytes(32, "big")
    pub_bytes = pub.public_bytes(
        Encoding.X962, PublicFormat.UncompressedPoint,
    )

    # Sanity check — PEM export so a human can reverse-verify if ever needed.
    _ = priv.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())

    print("# Paste these into .env (and restart the server):")
    print(f"VAPID_PUBLIC_KEY={_b64url(pub_bytes)}")
    print(f"VAPID_PRIVATE_KEY={_b64url(priv_bytes)}")
    print("VAPID_SUBJECT=mailto:you@example.com")


if __name__ == "__main__":
    main()
