"""Cluster 4B.4 — pin drift guard for ``_refresh_pin_contract_metadata``.

Per ``feedback_pin_drift_not_happy_path.md``, silent UPDATE helpers that
mutate multiple JSONB fields with ``flag_modified`` are exactly the seam
where pin drift hides. Before this test, the helper at
``app/services/dashboard_pins.py:_refresh_pin_contract_metadata`` had
zero direct unit coverage.

Invariants pinned here:

1. No-op when the pin's cached metadata already matches a fresh compute.
2. Each of the five fields (``widget_origin``, ``provenance_confidence``,
   ``widget_contract_snapshot``, ``config_schema_snapshot``,
   ``widget_presentation_snapshot``) becomes ``changed=True`` when it
   drifts, and the JSONB fields call ``flag_modified``.
3. Idempotency — a second call after a successful refresh returns
   ``False`` without additional writes.
4. Inferred origin when the pin's ``widget_origin`` is None.
5. ``source_stamp`` is refreshed through the same pin_contract Module.
"""
from __future__ import annotations

import uuid
from typing import Any
from unittest.mock import patch

from app.db.models import WidgetDashboardPin
from app.services.dashboard_pins import _refresh_pin_contract_metadata
from app.services.pin_contract import compute_expected_pin_contract


def _make_bare_pin(**overrides: Any) -> WidgetDashboardPin:
    """Build a detached ``WidgetDashboardPin`` with the fields the
    refresh helper reads. No DB session, no flush — the helper is pure
    Python and only touches ORM attributes.
    """
    base = {
        "id": uuid.uuid4(),
        "dashboard_key": "default",
        "position": 0,
        "source_kind": "channel",
        "source_channel_id": None,
        "source_bot_id": "test-bot",
        "tool_name": "get_weather",
        "tool_args": {},
        "widget_config": {},
        "envelope": {"display_label": "San Francisco"},
        "grid_layout": {},
        "widget_origin": None,
        "provenance_confidence": None,
        "widget_contract_snapshot": None,
        "config_schema_snapshot": None,
        "widget_presentation_snapshot": None,
        "source_stamp": None,
    }
    base.update(overrides)
    return WidgetDashboardPin(**base)


def _canonical_metadata(pin: WidgetDashboardPin) -> dict[str, Any]:
    expected = compute_expected_pin_contract(pin)
    return {
        "widget_origin": expected.view.widget_origin or None,
        "provenance_confidence": expected.view.provenance_confidence,
        "widget_contract_snapshot": expected.view.widget_contract,
        "config_schema_snapshot": expected.view.config_schema,
        "widget_presentation_snapshot": expected.view.widget_presentation,
        "source_stamp": expected.source_stamp,
    }


class TestRefreshPinContractMetadata:
    def test_initial_call_populates_all_inferred_fields(self) -> None:
        pin = _make_bare_pin()
        assert pin.widget_origin is None
        assert pin.provenance_confidence is None

        changed = _refresh_pin_contract_metadata(pin)

        assert changed is True
        # Resolver-chain origin inference runs because pin.widget_origin was None.
        assert isinstance(pin.widget_origin, dict)
        assert pin.provenance_confidence == "inferred"
        # widget_presentation_snapshot should get the default-merged shape.
        assert isinstance(pin.widget_presentation_snapshot, dict)
        assert pin.widget_presentation_snapshot.get("presentation_family") == "card"

    def test_idempotent_second_call_returns_false(self) -> None:
        pin = _make_bare_pin()
        first = _refresh_pin_contract_metadata(pin)
        assert first is True
        second = _refresh_pin_contract_metadata(pin)
        assert second is False, (
            "second call must be a no-op; pin already reflects canonical "
            "metadata"
        )

    def test_no_op_when_pin_already_matches_canonical(self) -> None:
        pin = _make_bare_pin()
        canonical = _canonical_metadata(pin)
        pin.widget_origin = canonical["widget_origin"]
        pin.provenance_confidence = canonical["provenance_confidence"]
        pin.widget_contract_snapshot = canonical["widget_contract_snapshot"]
        pin.config_schema_snapshot = canonical["config_schema_snapshot"]
        pin.widget_presentation_snapshot = canonical["widget_presentation_snapshot"]
        pin.source_stamp = canonical["source_stamp"]

        assert _refresh_pin_contract_metadata(pin) is False

    def test_widget_origin_inferred_when_none_flags_modified(self) -> None:
        """When pin has no cached ``widget_origin``, the helper infers
        one from tool_name/envelope/source_bot_id. It's a dict column —
        the helper must call ``flag_modified`` so the UPDATE is emitted.

        Semantic note: the helper trusts an already-set ``widget_origin``
        (doesn't recompute); drift is only possible through the None →
        inferred transition here, or by a caller explicitly clearing the
        field.
        """
        pin = _make_bare_pin()
        canonical = _canonical_metadata(pin)
        # Pre-align snapshots so only widget_origin drifts.
        pin.widget_contract_snapshot = canonical["widget_contract_snapshot"]
        pin.config_schema_snapshot = canonical["config_schema_snapshot"]
        pin.widget_presentation_snapshot = canonical["widget_presentation_snapshot"]
        pin.source_stamp = canonical["source_stamp"]
        pin.widget_origin = None
        pin.provenance_confidence = canonical["provenance_confidence"]

        with patch(
            "app.services.pin_contract.service.flag_modified"
        ) as flag_modified_spy:
            changed = _refresh_pin_contract_metadata(pin)

        assert changed is True
        assert isinstance(pin.widget_origin, dict)
        flagged_attrs = {call.args[1] for call in flag_modified_spy.call_args_list}
        assert "widget_origin" in flagged_attrs, (
            "widget_origin is a JSONB field — SQLAlchemy won't UPDATE "
            "it unless flag_modified is called explicitly"
        )

    def test_provenance_confidence_populated_from_none_without_flag_modified(
        self,
    ) -> None:
        """``provenance_confidence`` is a scalar column. When the helper
        flips it from None to "inferred"/"authoritative", no
        ``flag_modified`` is needed — SQLAlchemy tracks scalar writes."""
        pin = _make_bare_pin()
        canonical = _canonical_metadata(pin)
        # Align every field except provenance_confidence.
        pin.widget_origin = canonical["widget_origin"]
        pin.widget_contract_snapshot = canonical["widget_contract_snapshot"]
        pin.config_schema_snapshot = canonical["config_schema_snapshot"]
        pin.widget_presentation_snapshot = canonical["widget_presentation_snapshot"]
        pin.source_stamp = canonical["source_stamp"]
        pin.provenance_confidence = None

        with patch(
            "app.services.pin_contract.service.flag_modified"
        ) as flag_modified_spy:
            changed = _refresh_pin_contract_metadata(pin)

        assert changed is True
        # None → "authoritative" (because widget_origin is already a dict)
        # or "inferred" (when widget_origin is None). Both are legal.
        assert pin.provenance_confidence in {"inferred", "authoritative"}
        flagged_attrs = {call.args[1] for call in flag_modified_spy.call_args_list}
        assert "provenance_confidence" not in flagged_attrs

    def test_jsonb_snapshot_drift_all_flag_modified(self) -> None:
        """Each of the three snapshot fields is JSONB — all three must
        call ``flag_modified`` when they drift. Catches "forgot to
        flag one of them" regressions."""
        pin = _make_bare_pin()
        canonical = _canonical_metadata(pin)
        pin.widget_origin = canonical["widget_origin"]
        pin.provenance_confidence = canonical["provenance_confidence"]
        pin.source_stamp = canonical["source_stamp"]
        # Set all three snapshot fields to stale placeholders.
        pin.widget_contract_snapshot = {"stale": "contract"}
        pin.config_schema_snapshot = {"stale": "config"}
        pin.widget_presentation_snapshot = {"stale": "presentation"}

        with patch(
            "app.services.pin_contract.service.flag_modified"
        ) as flag_modified_spy:
            changed = _refresh_pin_contract_metadata(pin)

        assert changed is True
        flagged_attrs = {call.args[1] for call in flag_modified_spy.call_args_list}
        for attr in (
            "widget_contract_snapshot",
            "config_schema_snapshot",
            "widget_presentation_snapshot",
        ):
            assert attr in flagged_attrs, (
                f"{attr} drifted but flag_modified was not called — "
                "SQLAlchemy will silently skip the UPDATE for this JSONB field"
            )

    def test_source_stamp_drift_refreshes_without_flag_modified(self) -> None:
        pin = _make_bare_pin(
            tool_name="native",
            envelope={
                "content_type": "application/vnd.spindrel.native-app+json",
                "body": {"widget_ref": "core/notes_native"},
            },
        )
        canonical = _canonical_metadata(pin)
        pin.widget_origin = canonical["widget_origin"]
        pin.provenance_confidence = canonical["provenance_confidence"]
        pin.widget_contract_snapshot = canonical["widget_contract_snapshot"]
        pin.config_schema_snapshot = canonical["config_schema_snapshot"]
        pin.widget_presentation_snapshot = canonical["widget_presentation_snapshot"]
        pin.source_stamp = "stale"

        with patch(
            "app.services.pin_contract.service.flag_modified"
        ) as flag_modified_spy:
            changed = _refresh_pin_contract_metadata(pin)

        assert changed is True
        assert pin.source_stamp == canonical["source_stamp"]
        flagged_attrs = {call.args[1] for call in flag_modified_spy.call_args_list}
        assert "source_stamp" not in flagged_attrs

    def test_no_writes_when_metadata_matches_partial_fields(self) -> None:
        """Regression guard: fields that already match must NOT trigger
        flag_modified (no spurious JSONB rewrites)."""
        pin = _make_bare_pin()
        canonical = _canonical_metadata(pin)
        # Fully aligned.
        pin.widget_origin = canonical["widget_origin"]
        pin.provenance_confidence = canonical["provenance_confidence"]
        pin.widget_contract_snapshot = canonical["widget_contract_snapshot"]
        pin.config_schema_snapshot = canonical["config_schema_snapshot"]
        pin.widget_presentation_snapshot = canonical["widget_presentation_snapshot"]
        pin.source_stamp = canonical["source_stamp"]

        with patch(
            "app.services.pin_contract.service.flag_modified"
        ) as flag_modified_spy:
            changed = _refresh_pin_contract_metadata(pin)

        assert changed is False
        assert flag_modified_spy.call_count == 0, (
            "no drift → no UPDATE writes → flag_modified must not fire "
            "(checked because a buggy `!=` comparison on dict equality "
            "could regress this quietly)"
        )
