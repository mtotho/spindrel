"""TrueNAS integration settings."""
from __future__ import annotations

from integrations.sdk import make_settings

_Base = make_settings("truenas", {
    "TRUENAS_URL": "",
    "TRUENAS_API_KEY": "",
    "TRUENAS_VERIFY_SSL": "true",
    "TRUENAS_CONNECT_TIMEOUT_S": "10",
    "TRUENAS_REQUEST_TIMEOUT_S": "30",
})


def parse_truenas_bool(value: object, *, default: bool = True) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    return default


def parse_truenas_float(value: object, *, default: float, minimum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


class _Settings(_Base):
    @property
    def TRUENAS_VERIFY_SSL(self) -> bool:
        return parse_truenas_bool(self._get("TRUENAS_VERIFY_SSL", "true"), default=True)

    @property
    def TRUENAS_CONNECT_TIMEOUT_S(self) -> float:
        return parse_truenas_float(
            self._get("TRUENAS_CONNECT_TIMEOUT_S", "10"),
            default=10.0,
            minimum=1.0,
        )

    @property
    def TRUENAS_REQUEST_TIMEOUT_S(self) -> float:
        return parse_truenas_float(
            self._get("TRUENAS_REQUEST_TIMEOUT_S", "30"),
            default=30.0,
            minimum=1.0,
        )


settings = _Settings()

