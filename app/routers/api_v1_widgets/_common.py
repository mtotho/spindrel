"""Shared helpers for ``/widgets`` sub-routers."""
from __future__ import annotations

import uuid

from app.dependencies import ApiKeyAuth


def auth_identity(auth) -> tuple[uuid.UUID | None, bool]:
    """Extract ``(user_id, is_admin)`` from a ``require_scopes`` return value.

    - ``ApiKeyAuth`` has no user identity (``user_id=None``). ``is_admin`` is
      true only when the key carries the ``admin`` scope — a non-admin
      scoped key with ``channels:write`` can still pass the route guard but
      must not be allowed to pin dashboards "for everyone".
    - ``User`` → ``(user.id, user.is_admin)``.
    """
    from app.db.models import User
    if isinstance(auth, ApiKeyAuth):
        return (None, "admin" in auth.scopes)
    if isinstance(auth, User):
        return (auth.id, bool(auth.is_admin))
    return (None, False)
