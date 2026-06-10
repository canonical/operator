# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

# Forked from
# https://github.com/canonical/certificate-transfer-interface
# (lib charms.certificate_transfer_interface.v1.certificate_transfer, LIBAPI 1
# LIBPATCH 2). De-pydantic'd for ops_tracing's use: the pydantic ``BaseModel``
# databag models have been replaced with stdlib ``dataclasses`` plus manual
# validation, so that ops_tracing no longer pulls ``pydantic`` (and
# ``pydantic-core`` / ``annotated-types`` / ``typing-inspection``) into its
# dependency tree. The provider-side surface (``CertificateTransferProvides``)
# and the charmhub publish metadata (``LIBID`` / ``LIBAPI`` / ``LIBPATCH`` /
# ``PYDEPS``) have been dropped, since ops_tracing only acts as a requirer and
# never re-publishes this copy. Do NOT re-sync from upstream without
# re-applying this fork. See ``non-roadmap/depydantic-charm-libs`` in the
# canonical-work-queue repo for the audit of exactly what was dropped.

"""Library for the certificate_transfer relation (requirer side only).

This vendored copy contains just the ``CertificateTransferRequires`` class and
the data model it needs, for handling the requirer side of the
certificate-transfer interface.

### Requirer charm
The requirer charm is the charm requiring certificates from another charm that
provides them.

Example:
```python
import logging

from ops.charm import CharmBase
from ops.main import main

from lib.charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificatesAvailableEvent,
    CertificatesRemovedEvent,
    CertificateTransferRequires,
)


class DummyCertificateTransferRequirerCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.certificate_transfer = CertificateTransferRequires(self, "certificates")
        self.framework.observe(
            self.certificate_transfer.on.certificate_set_updated, self._on_certificates_available
        )
        self.framework.observe(
            self.certificate_transfer.on.certificates_removed, self._on_certificates_removed
        )

    def _on_certificates_available(self, event: CertificatesAvailableEvent):
        logging.info(event.certificates)
        logging.info(event.relation_id)

    def _on_certificates_removed(self, event: CertificatesRemovedEvent):
        logging.info(event.relation_id)


if __name__ == "__main__":
    main(DummyCertificateTransferRequirerCharm)
```
"""

import dataclasses
import enum
import json
import logging
import typing
from typing import Any, List, MutableMapping, Optional, Set

from ops import (
    CharmEvents,
    EventBase,
    EventSource,
    Handle,
    Relation,
    RelationBrokenEvent,
    RelationChangedEvent,
)
from ops.charm import CharmBase
from ops.framework import Object

logger = logging.getLogger(__name__)


class TLSCertificatesError(Exception):
    """Base class for custom errors raised by this library."""


class DataValidationError(TLSCertificatesError):
    """Raised when data validation fails."""


def _json_safe(value: Any) -> Any:
    """Recursively convert a value into a JSON-serialisable form.

    Replaces what pydantic's ``model_dump(mode="json")`` did for the field
    types this library uses: nested dataclasses become dicts, enums become
    their value, and sets become *sorted* lists so the wire representation is
    stable across hook invocations.
    """
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _json_safe(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, (set, frozenset)):
        return sorted(_json_safe(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    return value


def _coerce(tp: Any, value: Any) -> Any:
    """Coerce a JSON-decoded ``value`` into the dataclass field type ``tp``."""
    origin = typing.get_origin(tp)
    if origin is not None:
        args = typing.get_args(tp)
        if origin in (list, tuple):
            return [_coerce(args[0], v) for v in value]
        if origin in (set, frozenset):
            return {_coerce(args[0], v) for v in value}
        # Literal, Union, etc.: accept the value as-is.
        return value
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return _build(tp, value)
        if issubclass(tp, enum.Enum):
            return tp(value)
    return value


def _build(cls: Any, data: MutableMapping[str, Any]) -> Any:
    """Construct a dataclass ``cls`` from a plain ``data`` mapping.

    Required fields (those with no default) must be present; missing ones raise
    ``DataValidationError`` (mirroring pydantic's required-field behaviour).
    """
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name not in data:
            has_default = (
                field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING
            )
            if has_default:
                continue
            raise DataValidationError(f"missing required field {field.name!r}")
        kwargs[field.name] = _coerce(hints[field.name], data[field.name])
    return cls(**kwargs)


def _is_default(field: 'dataclasses.Field[Any]', value: Any) -> bool:
    """Whether ``value`` equals the field's declared default."""
    if field.default is not dataclasses.MISSING:
        return value == field.default
    if field.default_factory is not dataclasses.MISSING:
        return value == field.default_factory()
    return False


def _databag_load(cls: Any, databag: MutableMapping[str, str]) -> Any:
    """``DatabagModel.load`` replacement: per-key ``json.loads`` then validate.

    Each databag key holds a JSON-encoded value (Juju's relation-databag
    convention). Unknown keys are ignored (matching pydantic's
    ``extra="ignore"``).
    """
    field_names = {f.name for f in dataclasses.fields(cls)}
    try:
        data = {k: json.loads(v) for k, v in databag.items() if k in field_names}
    except json.JSONDecodeError as e:
        msg = f"invalid databag contents: expecting json. {databag}"
        logger.error(msg)
        raise DataValidationError(msg) from e

    try:
        return _build(cls, data)
    except (TypeError, ValueError, KeyError) as e:
        msg = f"failed to validate databag: {databag}"
        logger.debug(msg, exc_info=True)
        raise DataValidationError(msg) from e


def _databag_dump(
    obj: Any,
    databag: Optional[MutableMapping[str, str]] = None,
    clear: bool = True,
) -> MutableMapping[str, str]:
    """``DatabagModel.dump`` replacement: JSON-encode each non-default field."""
    if clear and databag:
        databag.clear()
    if databag is None:
        databag = {}
    for field in dataclasses.fields(obj):
        value = getattr(obj, field.name)
        # Skip values equal to the field default (matches pydantic's
        # ``exclude_defaults=True``).
        if _is_default(field, value):
            continue
        databag[field.name] = json.dumps(_json_safe(value))
    return databag


@dataclasses.dataclass(frozen=True)
class ProviderApplicationData:
    """App databag model for the certificate-transfer provider."""

    certificates: Set[str] = dataclasses.field(default_factory=set)

    @classmethod
    def load(cls, databag: MutableMapping[str, str]) -> 'ProviderApplicationData':
        """Load this model from a Juju databag."""
        return _databag_load(cls, databag)

    def dump(
        self, databag: Optional[MutableMapping[str, str]] = None, clear: bool = True
    ) -> MutableMapping[str, str]:
        """Write the contents of this model to a Juju databag.

        Args:
            databag: The databag to write to.
            clear: Whether to clear the databag before writing.

        Returns:
            MutableMapping: The databag.
        """
        return _databag_dump(self, databag, clear)


class CertificatesAvailableEvent(EventBase):
    """Charm Event triggered when the set of provided certificates is updated."""

    def __init__(
        self,
        handle: Handle,
        certificates: Set[str],
        relation_id: int,
    ):
        super().__init__(handle)
        self.certificates = certificates
        self.relation_id = relation_id

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {
            "certificates": self.certificates,
            "relation_id": self.relation_id,
        }

    def restore(self, snapshot: dict):
        """Restores snapshot."""
        self.certificates = snapshot["certificates"]
        self.relation_id = snapshot["relation_id"]


class CertificatesRemovedEvent(EventBase):
    """Charm Event triggered when the set of provided certificates is removed."""

    def __init__(self, handle: Handle, relation_id: int):
        super().__init__(handle)
        self.relation_id = relation_id

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {"relation_id": self.relation_id}

    def restore(self, snapshot: dict):
        """Restores snapshot."""
        self.relation_id = snapshot["relation_id"]


class CertificateTransferRequirerCharmEvents(CharmEvents):
    """List of events that the Certificate Transfer requirer charm can leverage."""

    certificate_set_updated = EventSource(CertificatesAvailableEvent)
    certificates_removed = EventSource(CertificatesRemovedEvent)


class CertificateTransferRequires(Object):
    """Certificate transfer requirer class to be instantiated by charms expecting certificates."""

    on = CertificateTransferRequirerCharmEvents()  # type: ignore

    def __init__(
        self,
        charm: CharmBase,
        relationship_name: str,
    ):
        """Observe events related to the relation.

        Args:
            charm: Charm object
            relationship_name: Juju relation name
        """
        super().__init__(charm, f"internal: {relationship_name}_v1")
        self.relationship_name = relationship_name
        self.charm = charm
        self.framework.observe(
            charm.on[relationship_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            charm.on[relationship_name].relation_broken, self._on_relation_broken
        )

    def _on_relation_changed(self, event: RelationChangedEvent) -> None:
        """Emit certificate set updated event.

        Args:
            event: Juju event

        Returns:
            None
        """
        remote_unit_relation_data = self.get_all_certificates(event.relation.id)
        self.on.certificate_set_updated.emit(
            certificates=remote_unit_relation_data,
            relation_id=event.relation.id,
        )

    def _on_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Handle relation broken event.

        Args:
            event: Juju event

        Returns:
            None
        """
        self.on.certificates_removed.emit(relation_id=event.relation.id)

    def get_all_certificates(self, relation_id: Optional[int] = None) -> Set[str]:
        """Get transferred certificates.

        If no relation id is given, certificates from all relations will be
        provided in a concatenated list.

        Args:
            relation_id: The id of the relation to get the certificates from.
        """
        relations = self._get_relevant_relations(relation_id)
        result = set()
        for relation in relations:
            data = self._get_relation_data(relation)
            result = result.union(data)
        return result

    def is_ready(self, relation: Relation) -> bool:
        """Check if the relation is ready by checking that it has valid relation data."""
        databag = relation.data[relation.app]
        try:
            ProviderApplicationData.load(databag)
            return True
        except DataValidationError:
            return False

    def _get_relation_data(self, relation: Relation) -> Set[str]:
        """Get the given relation data."""
        databag = relation.data[relation.app]
        try:
            return ProviderApplicationData.load(databag).certificates
        except DataValidationError as e:
            logger.error(
                (
                    "Error parsing relation databag: %s. ",
                    "Make sure not to interact with the databags "
                    "except using the public methods in the provider library "
                    "and use version V1.",
                ),
                e.args,
            )
            return set()

    def _get_relevant_relations(self, relation_id: Optional[int] = None) -> List[Relation]:
        """Get the relevant relation if relation_id is given, all relations otherwise."""
        if relation_id is not None:
            if relation := self.model.get_relation(
                relation_name=self.relationship_name, relation_id=relation_id
            ):
                return [relation]
        return list(self.model.relations[self.relationship_name])
