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

This private copy contains just the ``CertificateTransferRequires`` class and
the data model it needs, for handling the requirer side of the
certificate-transfer interface.

### Requirer charm
The requirer charm is the charm requiring certificates from another charm that
provides them.

Example:
```python
import logging

import ops

from lib.charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificatesAvailableEvent,
    CertificatesRemovedEvent,
    CertificateTransferRequires,
)


class DummyCertificateTransferRequirerCharm(ops.CharmBase):
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
    ops.main(DummyCertificateTransferRequirerCharm)
```
"""

import dataclasses
import logging
from typing import List, MutableMapping, Optional, Set

import ops

from . import _databag

logger = logging.getLogger(__name__)


class TLSCertificatesError(Exception):
    """Base class for custom errors raised by this library."""


class DataValidationError(TLSCertificatesError):
    """Raised when data validation fails."""


@dataclasses.dataclass(frozen=True)
class ProviderApplicationData:
    """App databag model for the certificate-transfer provider."""

    certificates: Set[str] = dataclasses.field(default_factory=set)

    @classmethod
    def load(cls, databag: MutableMapping[str, str]) -> 'ProviderApplicationData':
        """Load this model from a Juju databag."""
        return _databag.load(cls, databag, DataValidationError)


class CertificatesAvailableEvent(ops.EventBase):
    """Charm Event triggered when the set of provided certificates is updated."""

    def __init__(
        self,
        handle: ops.Handle,
        certificates: Set[str],
        relation_id: int,
    ):
        super().__init__(handle)
        self.certificates = certificates
        self.relation_id = relation_id

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {
            'certificates': self.certificates,
            'relation_id': self.relation_id,
        }

    def restore(self, snapshot: dict):
        """Restores snapshot."""
        self.certificates = snapshot['certificates']
        self.relation_id = snapshot['relation_id']


class CertificatesRemovedEvent(ops.EventBase):
    """Charm Event triggered when the set of provided certificates is removed."""

    def __init__(self, handle: ops.Handle, relation_id: int):
        super().__init__(handle)
        self.relation_id = relation_id

    def snapshot(self) -> dict:
        """Return snapshot."""
        return {'relation_id': self.relation_id}

    def restore(self, snapshot: dict):
        """Restores snapshot."""
        self.relation_id = snapshot['relation_id']


class CertificateTransferRequirerCharmEvents(ops.CharmEvents):
    """List of events that the Certificate Transfer requirer charm can leverage."""

    certificate_set_updated = ops.EventSource(CertificatesAvailableEvent)
    certificates_removed = ops.EventSource(CertificatesRemovedEvent)


class CertificateTransferRequires(ops.Object):
    """Certificate transfer requirer class to be instantiated by charms expecting certificates."""

    on = CertificateTransferRequirerCharmEvents()  # type: ignore

    def __init__(
        self,
        charm: ops.CharmBase,
        relationship_name: str,
    ):
        """Observe events related to the relation.

        Args:
            charm: Charm object
            relationship_name: Juju relation name
        """
        super().__init__(charm, f'internal: {relationship_name}_v1')
        self.relationship_name = relationship_name
        self.charm = charm
        self.framework.observe(
            charm.on[relationship_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            charm.on[relationship_name].relation_broken, self._on_relation_broken
        )

    def _on_relation_changed(self, event: ops.RelationChangedEvent) -> None:
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

    def _on_relation_broken(self, event: ops.RelationBrokenEvent) -> None:
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

    def is_ready(self, relation: ops.Relation) -> bool:
        """Check if the relation is ready by checking that it has valid relation data."""
        databag = relation.data[relation.app]
        try:
            ProviderApplicationData.load(databag)
            return True
        except DataValidationError:
            return False

    def _get_relation_data(self, relation: ops.Relation) -> Set[str]:
        """Get the given relation data."""
        databag = relation.data[relation.app]
        try:
            return ProviderApplicationData.load(databag).certificates
        except DataValidationError as e:
            logger.error(
                (
                    'Error parsing relation databag: %s. ',
                    'Make sure not to interact with the databags '
                    'except using the public methods in the provider library '
                    'and use version V1.',
                ),
                e.args,
            )
            return set()

    def _get_relevant_relations(self, relation_id: Optional[int] = None) -> List[ops.Relation]:
        """Get the relevant relation if relation_id is given, all relations otherwise."""
        if relation_id is not None and (
            relation := self.model.get_relation(
                relation_name=self.relationship_name, relation_id=relation_id
            )
        ):
            return [relation]
        return list(self.model.relations[self.relationship_name])
