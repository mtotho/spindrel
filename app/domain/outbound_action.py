"""OutboundAction — typed replacement for the untyped `client_actions: list[dict]`.

Today, the agent loop emits a `client_actions` list along with `deliver()`,
and the dispatcher decides whether each entry is an image upload, a file
upload, etc. by looking at the `type` field of the dict. The new model
types these actions and lets renderers dispatch on the union variant.

Phase A introduces the types. Subsequent phases migrate `client_actions`
from `list[dict]` to `list[OutboundAction]`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


@dataclass(frozen=True)
class UploadImage:
    type: Literal["upload_image"] = "upload_image"
    image_data_b64: str = ""
    filename: str = "image.png"
    mime_type: str = "image/png"
    description: str | None = None


@dataclass(frozen=True)
class UploadFile:
    type: Literal["upload_file"] = "upload_file"
    file_data_b64: str = ""
    filename: str = "file.bin"
    mime_type: str = "application/octet-stream"
    description: str | None = None


@dataclass(frozen=True)
class DeleteMessage:
    type: Literal["delete_message"] = "delete_message"
    platform_message_id: str = ""


@dataclass(frozen=True)
class AddReaction:
    type: Literal["add_reaction"] = "add_reaction"
    platform_message_id: str = ""
    reaction: str = ""


@dataclass(frozen=True)
class RequestApproval:
    type: Literal["request_approval"] = "request_approval"
    approval_id: str = ""
    bot_id: str = ""
    tool_name: str = ""
    arguments: dict = field(default_factory=dict)
    reason: str | None = None


OutboundAction = UploadImage | UploadFile | DeleteMessage | AddReaction | RequestApproval
