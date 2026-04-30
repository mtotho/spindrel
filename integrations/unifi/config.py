"""UniFi Network integration settings."""
from __future__ import annotations

from integrations.sdk import make_settings

_Base = make_settings("unifi", {
    "UNIFI_URL": "",
    "UNIFI_API_KEY": "",
    "UNIFI_SITE_ID": "",
    "UNIFI_VERIFY_SSL": "true",
    "UNIFI_API_BASE_PATH": "/proxy/network/integration/v1",
    "UNIFI_CONNECT_TIMEOUT_S": "10",
    "UNIFI_REQUEST_TIMEOUT_S": "30",
})


def parse_unifi_bool(value: object, *, default: bool = True) -> bool:
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


def parse_unifi_float(value: object, *, default: float, minimum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, parsed)


class _Settings(_Base):
    @property
    def UNIFI_VERIFY_SSL(self) -> bool:
        return parse_unifi_bool(self._get("UNIFI_VERIFY_SSL", "true"), default=True)

    @property
    def UNIFI_CONNECT_TIMEOUT_S(self) -> float:
        return parse_unifi_float(
            self._get("UNIFI_CONNECT_TIMEOUT_S", "10"),
            default=10.0,
            minimum=1.0,
        )

    @property
    def UNIFI_REQUEST_TIMEOUT_S(self) -> float:
        return parse_unifi_float(
            self._get("UNIFI_REQUEST_TIMEOUT_S", "30"),
            default=30.0,
            minimum=1.0,
        )


settings = _Settings()

