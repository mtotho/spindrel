"""Pin contract resolution — read/write split.

Public surface for widget dashboard pin contract metadata. The hot path
(``render_pin_metadata``) reads the pin row's snapshot columns with zero
registry / filesystem access. The cold path (``compute_pin_metadata`` +
``apply_to_pin``, or the convenience ``reconcile_pin_metadata``) walks the
``OriginResolver`` chain in ``resolvers/`` to materialize live fields, then
writes snapshot columns + a ``source_stamp`` so the next read can serve
from columns alone.

See ``docs/guides/widget-system.md`` for the four-layer model and
``~/.claude/plans/we-need-an-in-sparkling-sparrow.md`` for the design.
"""
from __future__ import annotations

from app.services.pin_contract.deps import ContractDeps, wire_pin_contract
from app.services.pin_contract.exceptions import (
    NativeSpecNotFound,
    PresetNotFound,
    TemplateNotFound,
)
from app.services.pin_contract.service import (
    ContractSnapshot,
    LiveFields,
    PinIdentity,
    PinMetadataView,
    apply_to_pin,
    compute_pin_metadata,
    reconcile_pin_metadata,
    render_pin_metadata,
)
from app.services.pin_contract.drift import (
    PinContractDrift,
    compute_expected_pin_contract,
    detect_pin_contract_drift,
    pin_contract_drift_worker,
    scan_pin_contract_drift,
)

__all__ = [
    "ContractDeps",
    "ContractSnapshot",
    "LiveFields",
    "NativeSpecNotFound",
    "PinIdentity",
    "PinMetadataView",
    "PresetNotFound",
    "TemplateNotFound",
    "apply_to_pin",
    "compute_pin_metadata",
    "compute_expected_pin_contract",
    "detect_pin_contract_drift",
    "PinContractDrift",
    "pin_contract_drift_worker",
    "reconcile_pin_metadata",
    "render_pin_metadata",
    "scan_pin_contract_drift",
    "wire_pin_contract",
]
