"""Shared request/response models for widget action endpoints and services."""
from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel


class WidgetActionRequest(BaseModel):
    dispatch: Literal[
        "tool",
        "api",
        "widget_config",
        "db_query",
        "db_exec",
        "widget_handler",
        "native_widget",
    ] = "tool"
    tool: str | None = None
    args: dict = {}
    handler: str | None = None
    endpoint: str | None = None
    method: str = "POST"
    body: dict | None = None
    dashboard_pin_id: uuid.UUID | None = None
    widget_instance_id: uuid.UUID | None = None
    config: dict | None = None
    sql: str | None = None
    params: list | None = None
    action: str | None = None
    channel_id: uuid.UUID | None = None
    bot_id: str | None = None
    source_record_id: uuid.UUID | None = None
    display_label: str | None = None
    widget_config: dict | None = None


class WidgetActionResponse(BaseModel):
    ok: bool
    envelope: dict | None = None
    error: str | None = None
    error_kind: str | None = None
    api_response: dict | None = None
    db_result: dict | None = None
    result: Any = None


class WidgetRefreshRequest(BaseModel):
    tool_name: str
    display_label: str = ""
    channel_id: uuid.UUID | None = None
    bot_id: str | None = None
    dashboard_pin_id: uuid.UUID | None = None
    widget_config: dict | None = None


class WidgetRefreshBatchItem(WidgetRefreshRequest):
    request_id: str


class WidgetRefreshBatchRequest(BaseModel):
    requests: list[WidgetRefreshBatchItem]


class WidgetRefreshBatchResult(BaseModel):
    request_id: str
    ok: bool
    envelope: dict | None = None
    error: str | None = None


class WidgetRefreshBatchResponse(BaseModel):
    ok: bool
    results: list[WidgetRefreshBatchResult]
