"""Authorization helpers for widget action and refresh entrypoints."""
from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import ApiKeyAuth
from app.domain.errors import ForbiddenError, NotFoundError


def system_widget_action_auth(name: str = "internal-widget-action") -> ApiKeyAuth:
    """Return an explicit admin-equivalent principal for trusted internal tools."""
    return ApiKeyAuth(
        key_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        scopes=["admin"],
        name=name,
    )


def _is_admin(auth: object) -> bool:
    if isinstance(auth, ApiKeyAuth):
        return "admin" in (auth.scopes or [])
    return bool(getattr(auth, "is_admin", False))


def _has_scope(auth: object, scope: str) -> bool:
    if _is_admin(auth):
        return True
    from app.services.api_keys import has_scope

    if isinstance(auth, ApiKeyAuth):
        return has_scope(auth.scopes or [], scope)
    scopes = getattr(auth, "_resolved_scopes", None) or []
    return has_scope(scopes, scope)


def _is_widget_token(auth: object) -> bool:
    return isinstance(auth, ApiKeyAuth) and auth.pin_id is not None


def _channel_id_from_pin(pin) -> uuid.UUID | None:
    source_channel_id = getattr(pin, "source_channel_id", None)
    if source_channel_id is not None:
        return source_channel_id
    dashboard_key = str(getattr(pin, "dashboard_key", "") or "")
    if not dashboard_key.startswith("channel:"):
        return None
    try:
        return uuid.UUID(dashboard_key.removeprefix("channel:"))
    except ValueError:
        return None


async def _load_pin(db: AsyncSession, pin_id: uuid.UUID):
    from app.db.models import WidgetDashboardPin

    pin = await db.get(WidgetDashboardPin, pin_id)
    if pin is None:
        raise NotFoundError("Dashboard pin not found")
    return pin


async def _load_instance(db: AsyncSession, instance_id: uuid.UUID):
    from app.db.models import WidgetInstance

    instance = await db.get(WidgetInstance, instance_id)
    if instance is None:
        raise NotFoundError("Native widget instance not found")
    return instance


async def _authorize_user_for_channel(
    db: AsyncSession,
    auth: object,
    channel_id: uuid.UUID,
    *,
    write: bool,
) -> None:
    if isinstance(auth, ApiKeyAuth) or _is_admin(auth):
        return

    from app.db.models import Channel

    channel = await db.get(Channel, channel_id)
    if channel is None:
        raise NotFoundError("Channel not found")

    user_id = getattr(auth, "id", None)
    if channel.user_id is not None and user_id is not None and channel.user_id == user_id:
        return
    if not write and not bool(getattr(channel, "private", False)) and channel.user_id is None:
        return
    raise ForbiddenError("Channel owner or admin access required")


async def authorize_widget_channel_access(
    db: AsyncSession,
    auth: object,
    channel_id: uuid.UUID,
    *,
    required_scope: str = "channels:read",
) -> None:
    """Authorize access to a channel-scoped widget action surface."""
    if _is_widget_token(auth):
        pin = await _load_pin(db, auth.pin_id)  # type: ignore[arg-type]
        if _channel_id_from_pin(pin) == channel_id:
            return
        raise ForbiddenError("Widget token cannot access a different channel")

    if not _has_scope(auth, required_scope):
        raise ForbiddenError(f"Missing required scope: {required_scope}")
    await _authorize_user_for_channel(
        db,
        auth,
        channel_id,
        write=required_scope.endswith(":write"),
    )


async def authorize_widget_pin_access(
    db: AsyncSession,
    auth: object,
    pin_id: uuid.UUID,
    *,
    required_scope: str = "channels:write",
):
    """Authorize access to a dashboard pin and return the pin row."""
    pin = await _load_pin(db, pin_id)
    if _is_widget_token(auth):
        if auth.pin_id == pin.id:  # type: ignore[union-attr]
            return pin
        raise ForbiddenError("Widget token cannot access a different pin")

    if not _has_scope(auth, required_scope):
        raise ForbiddenError(f"Missing required scope: {required_scope}")

    channel_id = _channel_id_from_pin(pin)
    if channel_id is not None:
        await _authorize_user_for_channel(
            db,
            auth,
            channel_id,
            write=required_scope.endswith(":write"),
        )
    return pin


async def authorize_widget_instance_access(
    db: AsyncSession,
    auth: object,
    instance_id: uuid.UUID,
    *,
    required_scope: str = "channels:write",
):
    """Authorize access to a native widget instance and return the instance row."""
    instance = await _load_instance(db, instance_id)
    if _is_widget_token(auth):
        pin = await _load_pin(db, auth.pin_id)  # type: ignore[arg-type]
        if getattr(pin, "widget_instance_id", None) == instance.id:
            return instance
        raise ForbiddenError("Widget token cannot access a different widget instance")

    if not _has_scope(auth, required_scope):
        raise ForbiddenError(f"Missing required scope: {required_scope}")

    if instance.scope_kind == "channel":
        try:
            channel_id = uuid.UUID(str(instance.scope_ref))
        except (TypeError, ValueError):
            raise ForbiddenError("Native widget instance has invalid channel scope")
        await _authorize_user_for_channel(
            db,
            auth,
            channel_id,
            write=required_scope.endswith(":write"),
        )
    return instance


async def authorize_widget_action_request(
    db: AsyncSession,
    auth: object,
    req,
    *,
    required_scope: str = "channels:write",
) -> None:
    """Authorize a widget action request before dispatching side effects."""
    pin = None
    if getattr(req, "dashboard_pin_id", None) is not None:
        pin = await authorize_widget_pin_access(
            db,
            auth,
            req.dashboard_pin_id,
            required_scope=required_scope,
        )

    if getattr(req, "widget_instance_id", None) is not None:
        if pin is not None:
            pin_instance_id = getattr(pin, "widget_instance_id", None)
            if pin_instance_id != req.widget_instance_id:
                raise ForbiddenError("Dashboard pin does not reference this widget instance")
        else:
            await authorize_widget_instance_access(
                db,
                auth,
                req.widget_instance_id,
                required_scope=required_scope,
            )

    if (
        pin is None
        and getattr(req, "widget_instance_id", None) is None
        and getattr(req, "channel_id", None) is not None
    ):
        await authorize_widget_channel_access(
            db,
            auth,
            req.channel_id,
            required_scope=required_scope,
        )


async def authorize_widget_refresh_request(
    db: AsyncSession,
    auth: object,
    req,
) -> None:
    await authorize_widget_action_request(
        db,
        auth,
        req,
        required_scope="channels:write",
    )
