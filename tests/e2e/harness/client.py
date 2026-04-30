"""E2E HTTP client for interacting with Spindrel."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from .streaming import StreamEvent, StreamResult

if TYPE_CHECKING:
    from .config import E2EConfig


MAX_REPLAY_LAPSED_RETRIES = 8


@dataclass
class ChatResponse:
    """Response from the non-streaming /chat endpoint."""

    session_id: str
    response: str
    client_actions: list[dict] = field(default_factory=list)
    raw: dict = field(default_factory=dict)


def replay_lapsed_resume_cursor(payload: dict[str, Any]) -> str | None:
    """Return a safe SSE cursor to resume after a replay_lapsed event."""
    value = payload.get("oldest_available")
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value) if value >= 0 else None
    if isinstance(value, str):
        value = value.strip()
        return value if value.isdigit() else None
    return None


def replay_lapsed_retry_cursor(
    payload: dict[str, Any],
    *,
    attempts: int,
    max_attempts: int = MAX_REPLAY_LAPSED_RETRIES,
) -> str | None:
    """Return the next safe SSE cursor while the replay-lapsed retry budget remains."""
    if attempts >= max_attempts:
        return None
    return replay_lapsed_resume_cursor(payload)


def _response_detail(resp: httpx.Response) -> str:
    try:
        detail = resp.json().get("detail")
    except Exception:
        detail = resp.text
    return str(detail)


def _runtime_surface_error(action: str, resp: httpx.Response) -> RuntimeError:
    detail = _response_detail(resp).strip() or resp.reason_phrase
    return RuntimeError(
        f"deployed server returned {resp.status_code} while {action}; "
        f"response detail: {detail!r}. This usually means the running server "
        "image and database schema are out of sync; redeploy/restart the "
        "current image and verify migrations before running harness parity."
    )


class E2EClient:
    """Async HTTP client for E2E testing against a running Spindrel server."""

    def __init__(self, config: E2EConfig) -> None:
        self.config = config
        self.default_bot_id = config.bot_id
        self._client = httpx.AsyncClient(
            base_url=config.base_url,
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=httpx.Timeout(config.request_timeout),
        )

    async def close(self) -> None:
        await self._client.aclose()

    # -- Chat endpoints --

    async def chat(
        self,
        message: str,
        bot_id: str | None = None,
        channel_id: str | None = None,
        client_id: str | None = None,
        **kwargs: Any,
    ) -> ChatResponse:
        """Send a message to /chat (POST → 202) and consume the bus until TURN_ENDED.

        Phase E of the Integration Delivery refactor flipped /chat from a
        synchronous endpoint that returned ``{response: ...}`` to a
        202-Accepted handle ``{session_id, channel_id, turn_id}``. The
        actual agent run happens on a background turn worker that
        publishes typed events to the channel-events bus. This helper
        re-creates the old "wait for the answer" behavior by tailing the
        SSE bus until the matching ``turn_ended`` event arrives.
        """
        result = await self._post_and_consume_turn(
            message,
            bot_id=bot_id,
            channel_id=channel_id,
            client_id=client_id,
            **kwargs,
        )
        return ChatResponse(
            session_id=result["session_id"],
            response=result["response_text"],
            client_actions=result["client_actions"],
            raw=result["raw"],
        )

    async def chat_stream(
        self,
        message: str,
        bot_id: str | None = None,
        channel_id: str | None = None,
        client_id: str | None = None,
        **kwargs: Any,
    ) -> StreamResult:
        """Send a message and consume the channel-events bus as a StreamResult.

        After Phase E the legacy SSE long-poll on ``/chat/stream`` is gone
        — both ``/chat`` and ``/chat/stream`` return ``202`` immediately
        with ``{session_id, channel_id, turn_id}``. The harness now POSTs
        to ``/chat`` and tails ``GET /api/v1/channels/{channel_id}/events``
        until the matching turn finishes, mapping the typed bus events
        back into the legacy ``StreamEvent`` shape so existing scenarios
        keep working without per-test changes.
        """
        consumed = await self._post_and_consume_turn(
            message,
            bot_id=bot_id,
            channel_id=channel_id,
            client_id=client_id,
            **kwargs,
        )

        result = StreamResult()
        result.session_id = consumed["session_id"]
        result.response_text = consumed["response_text"]
        result.tools_used = list(consumed["tools_used"])
        result.raw_lines = list(consumed["raw_lines"])
        for ev_type, ev_data in consumed["legacy_events"]:
            result.events.append(StreamEvent(type=ev_type, data=ev_data))
        return result

    async def chat_session_stream(
        self,
        message: str,
        *,
        session_id: str,
        channel_id: str,
        bot_id: str | None = None,
        timeout: float | None = None,
        harness_question_answer: dict[str, Any] | None = None,
        approval_decision: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> StreamResult:
        """Send a chat turn to a detached session and consume its channel bus.

        ``/chat`` accepts ``session_id`` for scratch/detached sessions, but
        turn events are still published on the parent channel bus. Existing
        helpers infer the bus channel from the response body; this helper lets
        live harness smoke tests target a fresh detached session while still
        tailing the known parent channel.
        """
        kwargs.setdefault("external_delivery", "none")
        consumed = await self._post_and_consume_turn(
            message,
            bot_id=bot_id,
            channel_id=channel_id,
            client_id=None,
            timeout=timeout,
            event_channel_id=channel_id,
            session_id=session_id,
            harness_question_answer=harness_question_answer,
            approval_decision=approval_decision,
            **kwargs,
        )

        result = StreamResult()
        result.session_id = consumed["session_id"]
        result.response_text = consumed["response_text"]
        result.tools_used = list(consumed["tools_used"])
        result.raw_lines = list(consumed["raw_lines"])
        for ev_type, ev_data in consumed["legacy_events"]:
            result.events.append(StreamEvent(type=ev_type, data=ev_data))
        return result

    async def _post_and_consume_turn(
        self,
        message: str,
        *,
        bot_id: str | None,
        channel_id: str | None,
        client_id: str | None,
        timeout: float | None = None,
        event_channel_id: str | None = None,
        harness_question_answer: dict[str, Any] | None = None,
        approval_decision: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """POST /chat, then tail the channel-events bus until TURN_ENDED.

        Returns a dict with the canonical fields the two public methods
        synthesize their results from. Handles the queued / passive /
        throttled fast paths (no turn_id in the 202 body) by returning
        immediately with empty event lists.
        """
        import asyncio
        import json
        import time

        payload: dict[str, Any] = {
            "message": message,
            "bot_id": bot_id or self.default_bot_id,
            "msg_metadata": {"sender_type": "human", "source": "e2e-test"},
            **kwargs,
        }
        if channel_id:
            payload["channel_id"] = channel_id
        if client_id:
            payload["client_id"] = client_id

        post_resp = await self._client.post("/chat", json=payload)
        post_resp.raise_for_status()
        body = post_resp.json()

        session_id = body.get("session_id", "")
        chan_id = body.get("channel_id") or channel_id or event_channel_id or ""
        turn_id = body.get("turn_id")

        # Fast paths that have no turn_id: passive store, throttled,
        # queued (busy session or system pause). Return what we have.
        if not turn_id:
            return {
                "session_id": session_id,
                "response_text": "",
                "tools_used": [],
                "raw_lines": [],
                "legacy_events": [],
                "client_actions": body.get("client_actions") or [],
                "raw": body,
            }

        if not chan_id:
            # Shouldn't happen — POST /chat always returns channel_id when
            # turn_id is present. Bail out with what we have.
            return {
                "session_id": session_id,
                "response_text": "",
                "tools_used": [],
                "raw_lines": [],
                "legacy_events": [],
                "client_actions": body.get("client_actions") or [],
                "raw": body,
            }

        deadline = time.monotonic() + (timeout or self.config.request_timeout)
        accumulated_text: list[str] = []
        tools_used: list[str] = []
        legacy_events: list[tuple[str, dict]] = []
        raw_lines: list[str] = []
        final_response_text = ""
        final_error: str | None = None
        final_client_actions: list[dict] = []
        final_raw: dict = body
        answered_harness_questions: set[str] = set()
        decided_approvals: set[str] = set()

        sse_url = f"/api/v1/channels/{chan_id}/events"
        sse_params = {"since": "0"}
        replay_lapsed_retries = 0

        while time.monotonic() <= deadline:
            reconnect_since: str | None = None
            try:
                async with self._client.stream(
                    "GET", sse_url, params=sse_params,
                    timeout=httpx.Timeout(timeout or self.config.request_timeout),
                ) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        raw_lines.append(line)
                        if time.monotonic() > deadline:
                            legacy_events.append(("error", {"reason": "harness_timeout"}))
                            final_error = "harness_timeout"
                            break
                        stripped = line.strip()
                        if not stripped or stripped.startswith(":"):
                            continue
                        if stripped.startswith("data: "):
                            stripped = stripped[6:]
                        try:
                            evt = json.loads(stripped)
                        except json.JSONDecodeError:
                            continue

                        kind = evt.get("kind", "")
                        epayload = evt.get("payload") or {}
                        ep_turn_id = epayload.get("turn_id")
                        is_my_turn = ep_turn_id == turn_id

                        # Map typed bus events into legacy StreamEvent shape so
                        # scenarios that introspect ``result.events`` /
                        # ``result.event_types`` keep matching.
                        if kind == "turn_started" and is_my_turn:
                            legacy_events.append(("start", {"bot_id": epayload.get("bot_id")}))
                        elif kind == "turn_stream_token" and is_my_turn:
                            # ``TurnStreamTokenPayload.delta`` is the canonical
                            # field name on the wire (see app/domain/payloads.py).
                            text_chunk = epayload.get("delta") or epayload.get("text", "")
                            if text_chunk:
                                accumulated_text.append(text_chunk)
                            legacy_events.append((
                                "text_delta",
                                {"text": text_chunk, "delta": text_chunk},
                            ))
                        elif kind == "turn_stream_tool_start" and is_my_turn:
                            tname = epayload.get("tool_name") or epayload.get("tool", "")
                            if tname and tname not in tools_used:
                                tools_used.append(tname)
                            legacy_events.append(("tool_start", {
                                "tool": tname,
                                "name": tname,
                                **epayload,
                            }))
                        elif kind == "turn_stream_tool_result" and is_my_turn:
                            tname = epayload.get("tool_name") or epayload.get("tool", "")
                            if tname and tname not in tools_used:
                                tools_used.append(tname)
                            legacy_events.append(("tool_result", {
                                "tool": tname,
                                "name": tname,
                                **epayload,
                            }))
                        elif kind == "approval_requested":
                            legacy_events.append(("approval_request", dict(epayload)))
                            await self._maybe_decide_approval(
                                epayload,
                                session_id=session_id,
                                decision=approval_decision,
                                decided=decided_approvals,
                            )
                        elif kind == "approval_resolved":
                            legacy_events.append(("approval_resolved", dict(epayload)))
                        elif kind == "context_budget":
                            # Metadata snapshot bridged by `turn_event_emit.py` —
                            # surfaces the budget bar in the UI and lets
                            # `test_stream_reports_context_injection` read it.
                            legacy_events.append(("context_budget", dict(epayload)))
                        elif kind == "memory_scheme_bootstrap":
                            legacy_events.append(("memory_scheme_bootstrap", dict(epayload)))
                        elif kind == "session_plan_updated":
                            legacy_events.append(("session_plan_updated", dict(epayload)))
                        elif kind == "delivery_failed":
                            legacy_events.append(("error", dict(epayload)))
                        elif kind == "new_message":
                            # Pass through new_message events for tests that
                            # introspect message ordering.
                            legacy_events.append(("message", dict(epayload)))
                            await self._maybe_answer_harness_question(
                                epayload,
                                session_id=session_id,
                                answer=harness_question_answer,
                                answered=answered_harness_questions,
                            )
                        elif kind == "turn_ended" and is_my_turn:
                            result_text = epayload.get("result")
                            if result_text:
                                final_response_text = result_text
                            elif accumulated_text:
                                final_response_text = "".join(accumulated_text)
                            final_error = epayload.get("error")
                            final_client_actions = list(epayload.get("client_actions") or [])
                            legacy_events.append(("response", {
                                "text": final_response_text,
                                "session_id": session_id,
                                "turn_id": turn_id,
                                "error": final_error,
                                "client_actions": final_client_actions,
                            }))
                            if final_error:
                                legacy_events.append(("error", {
                                    "message": final_error,
                                }))
                            break
                        elif kind == "replay_lapsed":
                            resume_cursor = replay_lapsed_retry_cursor(
                                dict(epayload),
                                attempts=replay_lapsed_retries,
                            )
                            if resume_cursor is not None:
                                reconnect_since = resume_cursor
                                replay_lapsed_retries += 1
                                break
                            legacy_events.append(("error", {
                                "reason": "replay_lapsed",
                                **dict(epayload),
                            }))
                            final_error = "replay_lapsed"
                            break
            except httpx.HTTPError as exc:
                legacy_events.append(("error", {"message": str(exc)}))
                final_error = str(exc)
                break
            except asyncio.TimeoutError:
                legacy_events.append(("error", {"reason": "sse_timeout"}))
                final_error = "sse_timeout"
                break

            if reconnect_since is None:
                break
            sse_params["since"] = reconnect_since

        if not final_response_text and accumulated_text:
            final_response_text = "".join(accumulated_text)

        return {
            "session_id": session_id,
            "response_text": final_response_text,
            "tools_used": tools_used,
            "raw_lines": raw_lines,
            "legacy_events": legacy_events,
            "client_actions": final_client_actions,
            "raw": {**final_raw, "error": final_error} if final_error else final_raw,
        }

    async def _maybe_answer_harness_question(
        self,
        event_payload: dict[str, Any],
        *,
        session_id: str,
        answer: dict[str, Any] | None,
        answered: set[str],
    ) -> None:
        if not answer:
            return
        message = event_payload.get("message")
        if not isinstance(message, dict):
            return
        if str(message.get("session_id") or "") != str(session_id):
            return
        metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
        if metadata.get("kind") != "harness_question":
            return
        interaction_id = str(message.get("id") or "").strip()
        if not interaction_id or interaction_id in answered:
            return
        state = metadata.get("harness_interaction") if isinstance(metadata, dict) else None
        if not isinstance(state, dict) or state.get("status") not in (None, "pending"):
            return
        questions = state.get("questions")
        if not isinstance(questions, list) or not questions:
            return

        answers: list[dict[str, Any]] = []
        default_answer = str(answer.get("answer") or "").strip()
        selected_options = answer.get("selected_options")
        default_selected = list(selected_options) if isinstance(selected_options, list) else []
        for question in questions:
            if not isinstance(question, dict):
                continue
            qid = str(question.get("id") or question.get("question_id") or "").strip()
            if not qid:
                continue
            options = question.get("options")
            selected = list(default_selected)
            if not selected and isinstance(options, list) and options:
                first = options[0]
                if isinstance(first, dict) and first.get("label"):
                    selected = [str(first["label"])]
            answers.append({
                "question_id": qid,
                "answer": default_answer,
                "selected_options": selected,
            })
        if not answers:
            return
        payload = {"answers": answers, "notes": answer.get("notes")}
        resp = await self._client.post(
            f"/api/v1/sessions/{session_id}/harness-interactions/{interaction_id}/answer",
            json=payload,
        )
        resp.raise_for_status()
        answered.add(interaction_id)

    async def _maybe_decide_approval(
        self,
        event_payload: dict[str, Any],
        *,
        session_id: str,
        decision: dict[str, Any] | None,
        decided: set[str],
    ) -> None:
        if not decision:
            return
        if str(event_payload.get("session_id") or "") != str(session_id):
            return
        approval_id = str(event_payload.get("approval_id") or "").strip()
        if not approval_id or approval_id in decided:
            return
        payload = {
            "approved": bool(decision.get("approved", True)),
            "decided_by": str(decision.get("decided_by") or "e2e_harness_parity"),
            "bypass_rest_of_turn": bool(decision.get("bypass_rest_of_turn", False)),
        }
        resp = await self._client.post(
            f"/api/v1/approvals/{approval_id}/decide",
            json=payload,
        )
        resp.raise_for_status()
        decided.add(approval_id)

    # -- Admin/utility endpoints --

    async def health(self) -> dict:
        """GET /health or /api/v1/admin/health (tries admin first for richer data)."""
        resp = await self._client.get("/api/v1/admin/health")
        if resp.status_code == 200:
            return resp.json()
        resp = await self._client.get("/health")
        resp.raise_for_status()
        return resp.json()

    async def list_bots(self) -> list[dict]:
        """GET /bots."""
        resp = await self._client.get("/bots")
        resp.raise_for_status()
        data = resp.json()
        return data["bots"] if isinstance(data, dict) and "bots" in data else data

    async def list_channels(self) -> list[dict]:
        """GET /api/v1/admin/channels."""
        resp = await self._client.get("/api/v1/admin/channels")
        if resp.status_code >= 500:
            raise _runtime_surface_error("listing admin channels", resp)
        resp.raise_for_status()
        data = resp.json()
        return data["channels"] if isinstance(data, dict) and "channels" in data else data

    async def create_channel_session(self, channel_id: str) -> str:
        """POST /api/v1/channels/{channel_id}/sessions and return the new session id."""
        resp = await self._client.post(f"/api/v1/channels/{channel_id}/sessions")
        if resp.status_code == 404 and _response_detail(resp).lower() == "not found":
            reset_resp = await self._client.post(f"/api/v1/channels/{channel_id}/reset")
            if reset_resp.status_code >= 500:
                raise _runtime_surface_error(
                    f"creating a harness session for channel {channel_id!r} via reset fallback",
                    reset_resp,
                )
            if reset_resp.status_code != 404:
                reset_resp.raise_for_status()
                return str(reset_resp.json()["new_session_id"])
            reset_detail = _response_detail(reset_resp)
            if reset_detail.lower() == "channel not found":
                raise RuntimeError(
                    f"harness parity channel {channel_id!r} was not found on the "
                    "target server; update HARNESS_PARITY_*_CHANNEL_ID or the "
                    "runner defaults before running harness parity"
                )
            raise RuntimeError(
                "deployed server is missing both /api/v1/channels/{channel_id}/sessions "
                "and /api/v1/channels/{channel_id}/reset; redeploy the build that includes "
                "channel-session APIs before running harness parity"
            )
        if resp.status_code == 404:
            detail = _response_detail(resp)
            if str(detail).lower() == "channel not found":
                raise RuntimeError(
                    f"harness parity channel {channel_id!r} was not found on the "
                    "target server; update HARNESS_PARITY_*_CHANNEL_ID or the "
                    "runner defaults before running harness parity"
                )
            raise RuntimeError(
                "deployed server is missing /api/v1/channels/{channel_id}/sessions; "
                "redeploy the build that includes channel-session APIs before running "
                "harness parity"
            )
        if resp.status_code >= 500:
            raise _runtime_surface_error(
                f"creating a harness session for channel {channel_id!r}",
                resp,
            )
        resp.raise_for_status()
        return str(resp.json()["new_session_id"])

    async def switch_channel_session(self, channel_id: str, session_id: str) -> dict:
        """POST /api/v1/channels/{channel_id}/switch-session."""
        resp = await self._client.post(
            f"/api/v1/channels/{channel_id}/switch-session",
            json={"session_id": session_id},
        )
        resp.raise_for_status()
        return resp.json()

    async def get_session_messages(self, session_id: str, limit: int = 50) -> list[dict]:
        """GET /api/v1/sessions/{session_id}/messages, normalized to the messages list."""
        resp = await self._client.get(
            f"/api/v1/sessions/{session_id}/messages",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            messages = data.get("messages", [])
        else:
            messages = data
        return list(messages or [])

    async def execute_slash_command(
        self,
        command_id: str,
        *,
        channel_id: str | None = None,
        session_id: str | None = None,
        current_session_id: str | None = None,
        args: list[str] | None = None,
        surface: str = "session",
    ) -> dict:
        """POST /api/v1/slash-commands/execute."""
        payload: dict[str, Any] = {
            "command_id": command_id,
            "args": list(args or []),
            "surface": surface,
        }
        if channel_id:
            payload["channel_id"] = channel_id
        if session_id:
            payload["session_id"] = session_id
        if current_session_id:
            payload["current_session_id"] = current_session_id
        resp = await self._client.post("/api/v1/slash-commands/execute", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_admin_logs(
        self,
        *,
        session_id: str | None = None,
        event_type: str | None = None,
        page_size: int = 50,
    ) -> dict:
        params: dict[str, Any] = {"page_size": page_size}
        if session_id:
            params["session_id"] = session_id
        if event_type:
            params["event_type"] = event_type
        resp = await self._client.get("/api/v1/admin/logs", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_trace_detail(self, correlation_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/admin/traces/{correlation_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_runtime_capabilities(self, runtime: str) -> dict:
        resp = await self._client.get(f"/api/v1/runtimes/{runtime}/capabilities")
        resp.raise_for_status()
        return resp.json()

    async def get_context_budget(self, channel_id: str, *, session_id: str | None = None) -> dict:
        params = {"session_id": session_id} if session_id else None
        resp = await self._client.get(
            f"/api/v1/channels/{channel_id}/context-budget",
            params=params,
        )
        resp.raise_for_status()
        return resp.json()

    async def get_agent_capabilities(
        self,
        *,
        bot_id: str | None = None,
        channel_id: str | None = None,
        session_id: str | None = None,
        include_endpoints: bool = False,
        include_schemas: bool = False,
    ) -> dict:
        params: dict[str, Any] = {
            "include_endpoints": include_endpoints,
            "include_schemas": include_schemas,
        }
        if bot_id:
            params["bot_id"] = bot_id
        if channel_id:
            params["channel_id"] = channel_id
        if session_id:
            params["session_id"] = session_id
        resp = await self._client.get("/api/v1/agent-capabilities", params=params)
        resp.raise_for_status()
        return resp.json()

    async def get_usage_logs(self, **params: Any) -> dict:
        clean_params = {key: value for key, value in params.items() if value is not None}
        resp = await self._client.get("/api/v1/admin/usage/logs", params=clean_params)
        resp.raise_for_status()
        return resp.json()

    async def get_usage_breakdown(self, **params: Any) -> dict:
        clean_params = {key: value for key, value in params.items() if value is not None}
        resp = await self._client.get("/api/v1/admin/usage/breakdown", params=clean_params)
        resp.raise_for_status()
        return resp.json()

    async def list_docker_stacks(self) -> list[dict]:
        resp = await self._client.get("/api/v1/admin/docker-stacks")
        if resp.status_code == 404:
            raise RuntimeError(
                "deployed server is missing /api/v1/admin/docker-stacks; "
                "redeploy the build that includes app/routers/api_v1_admin/docker_stacks.py "
                "before running browser-runtime harness parity"
            )
        resp.raise_for_status()
        return list(resp.json() or [])

    async def get_docker_stack_status(self, stack_id: str) -> list[dict]:
        resp = await self._client.get(f"/api/v1/admin/docker-stacks/{stack_id}/status")
        if resp.status_code == 404:
            raise RuntimeError(
                "deployed server is missing docker-stack status diagnostics; "
                "redeploy the build that includes app/routers/api_v1_admin/docker_stacks.py "
                "before running browser-runtime harness parity"
            )
        resp.raise_for_status()
        return list(resp.json() or [])

    async def list_admin_tools(self) -> list[dict]:
        resp = await self._client.get("/api/v1/admin/tools")
        resp.raise_for_status()
        return list(resp.json() or [])

    async def get_channel_config(self, channel_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/channels/{channel_id}/config")
        resp.raise_for_status()
        return resp.json()

    async def patch_channel_config(self, channel_id: str, patch: dict[str, Any]) -> dict:
        resp = await self._client.patch(f"/api/v1/channels/{channel_id}/config", json=patch)
        resp.raise_for_status()
        return resp.json()

    async def get_channel_settings(self, channel_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/admin/channels/{channel_id}/settings")
        resp.raise_for_status()
        return resp.json()

    async def patch_channel_settings(self, channel_id: str, patch: dict[str, Any]) -> dict:
        resp = await self._client.patch(f"/api/v1/admin/channels/{channel_id}/settings", json=patch)
        resp.raise_for_status()
        return resp.json()

    async def read_workspace_file(self, workspace_id: str, path: str) -> dict:
        resp = await self._client.get(
            f"/api/v1/workspaces/{workspace_id}/files/content",
            params={"path": path},
        )
        resp.raise_for_status()
        return resp.json()

    async def read_channel_workspace_file(self, channel_id: str, path: str) -> dict:
        resp = await self._client.get(
            f"/api/v1/channels/{channel_id}/workspace/files/content",
            params={"path": path},
        )
        resp.raise_for_status()
        return resp.json()

    async def write_workspace_file(self, workspace_id: str, path: str, content: str) -> dict:
        resp = await self._client.put(
            f"/api/v1/workspaces/{workspace_id}/files/content",
            params={"path": path},
            json={"content": content},
        )
        resp.raise_for_status()
        return resp.json()

    async def mkdir_workspace_path(self, workspace_id: str, path: str) -> dict:
        resp = await self._client.post(
            f"/api/v1/workspaces/{workspace_id}/files/mkdir",
            params={"path": path},
        )
        if resp.status_code == 400 and "exist" in resp.text.lower():
            return {}
        resp.raise_for_status()
        return resp.json()

    async def delete_workspace_path(self, workspace_id: str, path: str) -> None:
        resp = await self._client.delete(
            f"/api/v1/workspaces/{workspace_id}/files",
            params={"path": path},
        )
        if resp.status_code in (200, 204, 404):
            return
        if resp.status_code == 400 and "not" in resp.text.lower():
            return
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    async def delete_channel_workspace_path(self, channel_id: str, path: str) -> None:
        resp = await self._client.delete(
            f"/api/v1/channels/{channel_id}/workspace/files",
            params={"path": path},
        )
        if resp.status_code in (200, 204, 404):
            return
        if resp.status_code == 400 and "not" in resp.text.lower():
            return
        resp.raise_for_status()

    async def exit_session_plan_mode(self, session_id: str) -> dict:
        resp = await self._client.post(f"/sessions/{session_id}/plan/exit", json={})
        resp.raise_for_status()
        return resp.json()

    async def resume_session_plan_mode(self, session_id: str) -> dict:
        resp = await self._client.post(f"/sessions/{session_id}/plan/resume", json={})
        resp.raise_for_status()
        return resp.json()

    async def get_session_plan_state(self, session_id: str) -> dict:
        resp = await self._client.get(f"/sessions/{session_id}/plan-state")
        resp.raise_for_status()
        return resp.json()

    async def get_session_plan(self, session_id: str) -> dict:
        resp = await self._client.get(f"/sessions/{session_id}/plan")
        resp.raise_for_status()
        return resp.json()

    async def start_session_plan_mode(self, session_id: str) -> dict:
        resp = await self._client.post(f"/sessions/{session_id}/plan/start", json={})
        resp.raise_for_status()
        return resp.json()

    async def submit_plan_question_answers(
        self,
        session_id: str,
        *,
        title: str,
        answers: list[dict[str, Any]],
        source_message_id: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "title": title,
            "answers": list(answers),
        }
        if source_message_id:
            payload["source_message_id"] = source_message_id
        resp = await self._client.post(
            f"/sessions/{session_id}/plan/question-answers",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def create_session_plan(self, session_id: str, payload: dict[str, Any]) -> dict:
        resp = await self._client.post(f"/sessions/{session_id}/plans", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def update_session_plan(self, session_id: str, payload: dict[str, Any]) -> dict:
        resp = await self._client.patch(f"/sessions/{session_id}/plan", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def approve_session_plan(self, session_id: str, revision: int | None = None) -> dict:
        payload = {"revision": revision} if revision is not None else {}
        resp = await self._client.post(f"/sessions/{session_id}/plan/approve", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def create_native_plan_unsupported_fixture(
        self,
        *,
        session_id: str,
        channel_id: str,
        bot_id: str,
        variant: str = "unsupported",
        marker: str | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "session_id": session_id,
            "channel_id": channel_id,
            "bot_id": bot_id,
            "variant": variant,
        }
        if marker:
            payload["marker"] = marker
        resp = await self._client.post(
            "/api/v1/admin/diagnostics/native-plan-fixtures/unsupported-adherence",
            json=payload,
        )
        resp.raise_for_status()
        return resp.json()

    async def request_session_replan(
        self,
        session_id: str,
        *,
        reason: str,
        affected_step_ids: list[str] | None = None,
        evidence: str | None = None,
        revision: int | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "reason": reason,
            "affected_step_ids": affected_step_ids or [],
        }
        if evidence is not None:
            payload["evidence"] = evidence
        if revision is not None:
            payload["revision"] = revision
        resp = await self._client.post(f"/sessions/{session_id}/plan/replan", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def get_channel_heartbeat(self, channel_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/admin/channels/{channel_id}/heartbeat")
        resp.raise_for_status()
        return resp.json()

    async def patch_channel_heartbeat(self, channel_id: str, patch: dict[str, Any]) -> dict:
        resp = await self._client.patch(
            f"/api/v1/admin/channels/{channel_id}/heartbeat",
            json=patch,
        )
        resp.raise_for_status()
        return resp.json()

    async def fire_channel_heartbeat(self, channel_id: str) -> dict:
        resp = await self._client.post(f"/api/v1/admin/channels/{channel_id}/heartbeat/fire")
        resp.raise_for_status()
        return resp.json()

    async def get_run_preset(self, preset_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/admin/run-presets/{preset_id}")
        resp.raise_for_status()
        return resp.json()

    async def create_task(self, payload: dict[str, Any]) -> dict:
        resp = await self._client.post("/api/v1/admin/tasks", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def run_task_now(self, task_id: str, payload: dict[str, Any] | None = None) -> dict:
        resp = await self._client.post(f"/api/v1/admin/tasks/{task_id}/run", json=payload or {})
        resp.raise_for_status()
        return resp.json()

    async def get_task(self, task_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/admin/tasks/{task_id}")
        resp.raise_for_status()
        return resp.json()

    async def wait_task_terminal(self, task_id: str, *, timeout: float) -> dict:
        import asyncio
        import time

        deadline = time.monotonic() + timeout
        terminal = {"complete", "failed", "cancelled"}
        latest: dict | None = None
        while time.monotonic() < deadline:
            latest = await self.get_task(task_id)
            if str(latest.get("status")) in terminal:
                return latest
            await asyncio.sleep(2)
        raise AssertionError(f"task {task_id} did not finish within {timeout}s; latest={latest}")

    async def delete_task(self, task_id: str) -> None:
        resp = await self._client.delete(f"/api/v1/admin/tasks/{task_id}")
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    async def get_channel_widget_usefulness(self, channel_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/admin/channels/{channel_id}/widget-usefulness")
        resp.raise_for_status()
        return resp.json()

    async def list_widget_agency_receipts(self, channel_id: str, *, limit: int = 20) -> list[dict]:
        resp = await self._client.get(
            f"/api/v1/admin/channels/{channel_id}/widget-agency/receipts",
            params={"limit": limit},
        )
        resp.raise_for_status()
        data = resp.json()
        return list((data or {}).get("receipts") or [])

    async def list_dashboard_pins(self, dashboard_key: str) -> list[dict]:
        resp = await self._client.get(
            "/api/v1/widgets/dashboard",
            params={"slug": dashboard_key},
        )
        resp.raise_for_status()
        data = resp.json()
        return list((data or {}).get("pins") or [])

    async def create_dashboard_pin(self, payload: dict[str, Any]) -> dict:
        resp = await self._client.post("/api/v1/widgets/dashboard/pins", json=payload)
        resp.raise_for_status()
        return resp.json()

    async def delete_dashboard_pin(self, pin_id: str) -> None:
        resp = await self._client.delete(f"/api/v1/widgets/dashboard/pins/{pin_id}")
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    async def get_session_harness_settings(self, session_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/sessions/{session_id}/harness-settings")
        resp.raise_for_status()
        return resp.json()

    async def get_session_harness_status(self, session_id: str) -> dict:
        resp = await self._client.get(f"/api/v1/sessions/{session_id}/harness-status")
        resp.raise_for_status()
        return resp.json()

    async def set_session_approval_mode(self, session_id: str, mode: str) -> dict:
        resp = await self._client.post(
            f"/api/v1/sessions/{session_id}/approval-mode",
            json={"mode": mode},
        )
        resp.raise_for_status()
        return resp.json()

    # -- Bot admin endpoints --

    async def create_bot(self, bot_data: dict[str, Any]) -> dict:
        """POST /api/v1/admin/bots — create a bot, return BotOut."""
        resp = await self._client.post("/api/v1/admin/bots", json=bot_data)
        resp.raise_for_status()
        return resp.json()

    async def get_bot(self, bot_id: str) -> dict:
        """GET /api/v1/admin/bots/{bot_id} — return BotOut."""
        resp = await self._client.get(f"/api/v1/admin/bots/{bot_id}")
        resp.raise_for_status()
        return resp.json()

    async def update_bot(self, bot_id: str, updates: dict[str, Any]) -> dict:
        """PATCH /api/v1/admin/bots/{bot_id} — return updated BotOut."""
        resp = await self._client.patch(f"/api/v1/admin/bots/{bot_id}", json=updates)
        resp.raise_for_status()
        return resp.json()

    async def delete_bot(self, bot_id: str, force: bool = True) -> None:
        """DELETE /api/v1/admin/bots/{bot_id}."""
        resp = await self._client.delete(
            f"/api/v1/admin/bots/{bot_id}", params={"force": str(force).lower()}
        )
        resp.raise_for_status()

    # -- Channel admin endpoints --

    async def get_channel(self, channel_id: str) -> dict:
        """GET /api/v1/admin/channels/{channel_id} — return ChannelDetailOut."""
        resp = await self._client.get(f"/api/v1/admin/channels/{channel_id}")
        resp.raise_for_status()
        return resp.json()

    async def get_channel_settings(self, channel_id: str) -> dict:
        """GET /api/v1/admin/channels/{channel_id}/settings."""
        resp = await self._client.get(f"/api/v1/admin/channels/{channel_id}/settings")
        resp.raise_for_status()
        return resp.json()

    async def update_channel_settings(
        self, channel_id: str, updates: dict[str, Any]
    ) -> dict:
        """PATCH /api/v1/admin/channels/{channel_id}/settings."""
        resp = await self._client.patch(
            f"/api/v1/admin/channels/{channel_id}/settings", json=updates
        )
        resp.raise_for_status()
        return resp.json()

    async def delete_channel(self, channel_id: str) -> None:
        """DELETE /api/v1/channels/{channel_id}."""
        resp = await self._client.delete(f"/api/v1/channels/{channel_id}")
        # 204 = deleted, 404 = already gone — both are fine
        if resp.status_code not in (200, 204, 404):
            resp.raise_for_status()

    # -- Generic HTTP methods --

    async def get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(path, **kwargs)

    async def post(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.post(path, **kwargs)

    async def put(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.put(path, **kwargs)

    async def patch(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.patch(path, **kwargs)

    async def delete(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.delete(path, **kwargs)

    # -- Bot member endpoints (multi-bot channels) --

    async def create_channel(self, channel_data: dict[str, Any]) -> dict:
        """POST /api/v1/channels — create a channel, return ChannelOut."""
        resp = await self._client.post("/api/v1/channels", json=channel_data)
        resp.raise_for_status()
        return resp.json()

    async def list_bot_members(self, channel_id: str) -> list[dict]:
        """GET /api/v1/channels/{channel_id}/bot-members."""
        resp = await self._client.get(f"/api/v1/channels/{channel_id}/bot-members")
        resp.raise_for_status()
        return resp.json()

    async def add_bot_member(self, channel_id: str, bot_id: str) -> dict:
        """POST /api/v1/channels/{channel_id}/bot-members."""
        resp = await self._client.post(
            f"/api/v1/channels/{channel_id}/bot-members",
            json={"bot_id": bot_id},
        )
        resp.raise_for_status()
        return resp.json()

    async def remove_bot_member(self, channel_id: str, bot_id: str) -> None:
        """DELETE /api/v1/channels/{channel_id}/bot-members/{bot_id}."""
        resp = await self._client.delete(
            f"/api/v1/channels/{channel_id}/bot-members/{bot_id}"
        )
        resp.raise_for_status()

    async def update_bot_member_config(
        self, channel_id: str, bot_id: str, config: dict[str, Any]
    ) -> dict:
        """PATCH /api/v1/channels/{channel_id}/bot-members/{bot_id}/config."""
        resp = await self._client.patch(
            f"/api/v1/channels/{channel_id}/bot-members/{bot_id}/config",
            json=config,
        )
        resp.raise_for_status()
        return resp.json()

    # -- Helpers --

    async def create_temp_bot(
        self,
        model: str,
        provider_id: str | None = None,
        tools: list[str] | None = None,
        system_prompt: str = "You are a test bot. Follow instructions exactly.",
    ) -> str:
        """Create a temporary bot for testing. Returns bot_id. Caller must delete."""
        bot_id = f"e2e-tmp-{uuid.uuid4().hex[:8]}"
        bot_data: dict[str, Any] = {
            "id": bot_id,
            "name": f"E2E Temp ({model})",
            "model": model,
            "system_prompt": system_prompt,
            "local_tools": tools or ["get_current_time"],
            "tool_retrieval": False,
            "tool_discovery": False,
            "persona": False,
        }
        if provider_id:
            bot_data["model_provider_id"] = provider_id
        await self.create_bot(bot_data)
        return bot_id

    @staticmethod
    def new_channel_id() -> str:
        """Generate a unique channel ID for test isolation."""
        return str(uuid.uuid4())

    @staticmethod
    def new_client_id(prefix: str = "e2e-test") -> str:
        """Generate a unique client_id for channel creation."""
        return f"{prefix}:{uuid.uuid4().hex[:12]}"

    @staticmethod
    def derive_channel_id(client_id: str) -> str:
        """Derive the channel UUID that the server will create for a client_id.

        Mirrors app/services/channels.py:derive_channel_id().
        """
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"channel:{client_id}"))
