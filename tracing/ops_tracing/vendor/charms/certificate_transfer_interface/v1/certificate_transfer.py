# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

"""Library for the certificate_transfer relation.

This library contains the Requires and Provides classes for handling the
certificate-transfer interface. It supports both v0 and v1 of the interface.

For requirers, they will set version 1 in their application databag as a hint to
the provider. They will read the databag from the provider first as v1, and fallback
to v0 if the format does not match.

For providers, they will check the version in the requirer's application databag,
and send v1 if that version is set to 1, otherwise it will default to 0 for backwards
compatibility.

## Getting Started
From a charm directory, fetch the library using `charmcraft`:

```shell
charmcraft fetch-lib charms.certificate_transfer_interface.v1.certificate_transfer
```

### Provider charm
The provider charm is the charm providing public certificates to another charm that requires them.

Example:
```python
from ops.charm import CharmBase, RelationJoinedEvent
from ops.main import main

from lib.charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferProvides,
)

class DummyCertificateTransferProviderCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.certificate_transfer = CertificateTransferProvides(self, "certificates")
        self.framework.observe(
            self.on.certificates_relation_joined, self._on_certificates_relation_joined
        )

    def _on_certificates_relation_joined(self, event: RelationJoinedEvent):
        certificate = "my certificate"
        self.certificate_transfer.add_certificates(certificate)


if __name__ == "__main__":
    main(DummyCertificateTransferProviderCharm)
```

### Requirer charm
The requirer charm is the charm requiring certificates from another charm that provides them.

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

You can integrate both charms by running:

```bash
juju integrate <certificate_transfer provider charm> <certificate_transfer requirer charm>
```

"""

import json
import logging
from typing import Dict, List, MutableMapping, Optional, Set

import pydantic
from ops import (
    CharmEvents,
    EventBase,
    EventSource,
    Handle,
    Relation,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationCreatedEvent,
)
from ops.charm import CharmBase
from ops.framework import Object

# The unique Charmhub library identifier, never change it
LIBID = "3785165b24a743f2b0c60de52db25c8b"

# Increment this major API version when introducing breaking changes
LIBAPI = 1

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 15

logger = logging.getLogger(__name__)

PYDEPS = ["pydantic"]

IS_PYDANTIC_V1 = int(pydantic.version.VERSION.split(".")[0]) < 2


class TLSCertificatesError(Exception):
    """Base class for custom errors raised by this library."""


class DataValidationError(TLSCertificatesError):
    """Raised when data validation fails."""


class DatabagModel(pydantic.BaseModel):
    """Base databag model.

    Supports both pydantic v1 and v2.
    """

    if IS_PYDANTIC_V1:

        class Config:
            """Pydantic config."""

            # ignore any extra fields in the databag
            extra = "ignore"
            """Ignore any extra fields in the databag."""
            allow_population_by_field_name = True
            """Allow instantiating this class by field name (instead of forcing alias)."""

        _NEST_UNDER = None

    model_config = pydantic.ConfigDict(
        # tolerate additional keys in databag
        extra="ignore",
        # Allow instantiating this class by field name (instead of forcing alias).
        populate_by_name=True,
        # Custom config key: whether to nest the whole datastructure (as json)
        # under a field or spread it out at the toplevel.
        _NEST_UNDER=None,
    )  # type: ignore
    """Pydantic config."""

    @classmethod
    def load(cls, databag: MutableMapping):
        """Load this model from a Juju databag."""
        if IS_PYDANTIC_V1:
            return cls._load_v1(databag)
        nest_under = cls.model_config.get("_NEST_UNDER")
        if nest_under:
            return cls.model_validate(json.loads(databag[nest_under]))

        try:
            data = {
                k: json.loads(v)
                for k, v in databag.items()
                # Don't attempt to parse model-external values
                if k in {(f.alias or n) for n, f in cls.model_fields.items()}
            }
        except json.JSONDecodeError as e:
            msg = f"invalid databag contents: expecting json. {databag}"
            logger.error(msg)
            raise DataValidationError(msg) from e

        try:
            return cls.model_validate_json(json.dumps(data))
        except pydantic.ValidationError as e:
            msg = f"failed to validate databag: {databag}"
            logger.debug(msg, exc_info=True)
            raise DataValidationError(msg) from e

    @classmethod
    def _load_v1(cls, databag: MutableMapping):
        """Load implementation for pydantic v1."""
        if cls._NEST_UNDER:
            return cls.parse_obj(json.loads(databag[cls._NEST_UNDER]))

        try:
            data = {
                k: json.loads(v)
                for k, v in databag.items()
                # Don't attempt to parse model-external values
                if k in {f.alias for f in cls.__fields__.values()}
            }
        except json.JSONDecodeError as e:
            msg = f"invalid databag contents: expecting json. {databag}"
            logger.error(msg)
            raise DataValidationError(msg) from e

        try:
            return cls.parse_raw(json.dumps(data))  # type: ignore
        except pydantic.ValidationError as e:
            msg = f"failed to validate databag: {databag}"
            logger.debug(msg, exc_info=True)
            raise DataValidationError(msg) from e

    def dump(self, databag: Optional[MutableMapping] = None, clear: bool = True):
        """Write the contents of this model to Juju databag.

        Args:
            databag: The databag to write to.
            clear: Whether to clear the databag before writing.

        Returns:
            MutableMapping: The databag.
        """
        if IS_PYDANTIC_V1:
            return self._dump_v1(databag, clear)
        if clear and databag:
            databag.clear()

        if databag is None:
            databag = {}
        nest_under = self.model_config.get("_NEST_UNDER")
        if nest_under:
            databag[nest_under] = self.model_dump_json(
                by_alias=True,
                # skip keys whose values are default
                exclude_defaults=True,
            )
            return databag

        dct = self.model_dump(mode="json", by_alias=True, exclude_defaults=False)
        databag.update({k: json.dumps(v) for k, v in dct.items()})
        return databag

    def _dump_v1(self, databag: Optional[MutableMapping] = None, clear: bool = True):
        """Dump implementation for pydantic v1."""
        if clear and databag:
            databag.clear()

        if databag is None:
            databag = {}

        if self._NEST_UNDER:
            databag[self._NEST_UNDER] = self.json(by_alias=True, exclude_defaults=False)
            return databag

        dct = json.loads(self.json(by_alias=True, exclude_defaults=False))
        databag.update({k: json.dumps(v) for k, v in dct.items()})

        return databag


class ProviderApplicationData(DatabagModel):
    """Provider App databag model."""

    if int(pydantic.version.VERSION.split(".")[0]) < 2:
        certificates: Set[str] = pydantic.Field(
            description="The set of certificates that will be transferred to a requirer",
            default_factory=set,
        )
    else:
        certificates: Set[str] = pydantic.Field(
            description="The set of certificates that will be transferred to a requirer",
            default=set(),
        )
    version: int = pydantic.Field(
        description="Version of the interface used in this databag",
        default=1,
    )


class ProviderUnitDataV0(DatabagModel):
    """Provider Unit databag v0 model."""

    ca: str
    certificate: str
    chain: Optional[List[str]] = None
    version: int = pydantic.Field(
        description="Version of the interface used in this databag",
        default=0,
    )


class RequirerApplicationData(DatabagModel):
    """Requirer App databag model."""

    version: int = pydantic.Field(
        description="Version of the interface supported by this requirer",
        default=1,
    )


class CertificateTransferProvides(Object):
    """Certificate Transfer provider class to be instantiated by charms sending certificates."""

    def __init__(self, charm: CharmBase, relationship_name: str):
        super().__init__(charm, relationship_name + "_v1")
        self.charm = charm
        self.relationship_name = relationship_name

    def add_certificates(self, certificates: Set[str], relation_id: Optional[int] = None) -> None:
        """Add certificates from a set to relation data.

        Adds certificate to all relations if relation_id is not provided.

        Args:
            certificates (Set[str]): A set of certificate strings in PEM format
            relation_id (int): Juju relation ID

        Returns:
            None
        """
        if not self.charm.unit.is_leader():
            logger.warning("Only the leader unit can add certificates to this relation")
            return
        relations = self._get_active_relations(relation_id)
        if not relations:
            if relation_id is not None:
                logger.debug(
                    "At least 1 matching relation ID not found with the relation name '%s'",
                    self.relationship_name,
                )
            else:
                logger.debug(
                    "No active relations found with the relation name '%s'",
                    self.relationship_name,
                )
            return

        for relation in relations:
            existing_data = self._get_relation_data(relation)
            existing_data.update(certificates)
            self._set_relation_data(relation, existing_data)

    def remove_all_certificates(self, relation_id: Optional[int] = None) -> None:
        """Remove all certificates from relation data.

        Removes all certificates from all relations if relation_id not given

        Args:
            relation_id (int): Relation ID

        Returns:
            None
        """
        if not self.charm.unit.is_leader():
            logger.warning("Only the leader unit can add certificates to this relation")
            return
        relations = self._get_active_relations(relation_id)
        if not relations:
            if relation_id is not None:
                logger.debug(
                    "At least 1 matching relation ID not found with the relation name '%s'",
                    self.relationship_name,
                )
            else:
                logger.debug(
                    "No active relations found with the relation name '%s'",
                    self.relationship_name,
                )
            return

        for relation in relations:
            self._set_relation_data(relation, set())

    def remove_certificate(
        self,
        certificate: str,
        relation_id: Optional[int] = None,
    ) -> None:
        """Remove a given certificate from relation data.

        Removes certificate from all relations if relation_id not given

        Args:
            certificate (str): Certificate in PEM format that's in the list
            relation_id (int): Relation ID

        Returns:
            None
        """
        if not self.charm.unit.is_leader():
            logger.warning("Only the leader unit can add certificates to this relation")
            return
        relations = self._get_active_relations(relation_id)
        if not relations:
            if relation_id is not None:
                logger.debug(
                    "At least 1 matching relation ID not found with the relation name '%s'",
                    self.relationship_name,
                )
            else:
                logger.debug(
                    "No active relations found with the relation name '%s'",
                    self.relationship_name,
                )
            return

        for relation in relations:
            existing_data = self._get_relation_data(relation)
            existing_data.discard(certificate)
            self._set_relation_data(relation, existing_data)

    def _get_active_relations(self, relation_id: Optional[int] = None) -> List[Relation]:
        """Get the relation if relation_id is given and the relation is active, all active relations otherwise."""
        if relation_id is not None:
            relation = self.model.get_relation(
                relation_name=self.relationship_name, relation_id=relation_id
            )
            if relation and relation.active:
                return [relation]
            return []

        return [
            relation
            for relation in self.model.relations[self.relationship_name]
            if relation.active
        ]

    def _set_relation_data(self, relation: Relation, data: Set[str]) -> None:
        """Set the given relation data."""
        if relation.data.get(relation.app, {}).get("version", "0") == "1":
            databag = relation.data[self.model.app]
            ProviderApplicationData(certificates=data).dump(databag, True)
        else:
            if "version" in relation.data.get(relation.app, {}):
                logger.warning(
                    (
                        "Requirer in relation %d is using version %s of the interface,",
                        "defaulting to version 0.",
                        "This is deprecated, please consider upgrading the requirer",
                        "to version 1 of the library.",
                    ),
                    relation.id,
                    relation.data[relation.app]["version"],
                )
            else:
                logger.warning(
                    (
                        "Requirer in relation %d did not provide version field,",
                        "defaulting to version 0.",
                        "This is deprecated, please consider upgrading the requirer",
                        "to version 1 of the library.",
                    ),
                    relation.id,
                )

            databag = relation.data[self.model.unit]
            if data:
                certificates = list(data)
                ProviderUnitDataV0(
                    ca=certificates[0], certificate=certificates[0], chain=certificates
                ).dump(databag, True)

    def _get_relation_data(self, relation: Relation) -> Set[str]:
        """Get the given relation data."""
        try:
            if relation.data.get(relation.app, {}).get("version", "0") == "1":
                databag = relation.data[self.model.app]
                return ProviderApplicationData().load(databag).certificates
            else:
                databag = relation.data[self.model.unit]
                certs = ProviderUnitDataV0.load(databag).chain
                if certs is None:
                    return set()
                return set(certs)
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
        super().__init__(charm, relationship_name + "_v1")
        self.relationship_name = relationship_name
        self.charm = charm
        self.framework.observe(
            charm.on[relationship_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            charm.on[relationship_name].relation_broken, self._on_relation_broken
        )
        self.framework.observe(
            charm.on[relationship_name].relation_created, self._on_relation_created
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

    def _on_relation_created(self, event: RelationCreatedEvent) -> None:
        """Handle relation created event.

        Args:
            event: Juju event

        Returns:
            None
        """
        if not self.model.unit.is_leader():
            logger.debug("Only leader unit sets the version number in the app databag")
            return
        databag = event.relation.data[self.model.app]
        RequirerApplicationData().dump(databag, False)

    def get_all_certificates(self, relation_id: Optional[int] = None) -> Set[str]:
        """Get transferred certificates.

        If no relation id is given, certificates from all relations will be
        provided in a concatenated list.

        Args:
            relation_id: The id of the relation to get the certificates from.
        """
        relations = self._get_active_relations(relation_id)
        result = set()
        for relation in relations:
            data = self._get_relation_data(relation)
            result = result.union(data)
        return result

    def get_all_certificates_by_relation(
        self, relation_id: Optional[int] = None
    ) -> Dict[int, List[str]]:
        """Get a deterministic list of certificates grouped by relation.

        - Grouped by relation_id.
        - The list order is sorted lexicographically by PEM content.

        Args:
            relation_id: If provided, only certificates for this relation are returned.

        Returns:
            Dict where keys are relation IDs and values are ordered lists of PEMs.
        """
        relations = self._get_active_relations(relation_id)
        result: Dict[int, List[str]] = {}
        for relation in relations:
            certificates = sorted(self._get_relation_data(relation))
            result[relation.id] = certificates
        return result

    def is_ready(self, relation: Relation) -> bool:
        """Check if the relation is ready by checking that it has valid relation data."""
        databag = relation.data[relation.app]
        try:
            ProviderApplicationData().load(databag)
            return True
        except DataValidationError:
            return False

    def _get_relation_data(self, relation: Relation) -> Set[str]:
        """Get the given relation data."""
        try:
            databag = relation.data[relation.app]
            certificates = ProviderApplicationData().load(databag).certificates
            if not certificates and relation.units:
                databag = relation.data.get(relation.units.pop(), {})
                certs = ProviderUnitDataV0.load(databag).chain
                if certs is None:
                    return set()
                return set(certs)
            return certificates
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

    def _get_active_relations(self, relation_id: Optional[int] = None) -> List[Relation]:
        """Get the active relation if relation_id is given, all active relations otherwise."""
        if relation_id is not None:
            if relation := self.model.get_relation(
                relation_name=self.relationship_name, relation_id=relation_id
            ):
                return [relation]
        return [
            relation
            for relation in self.model.relations[self.relationship_name]
            if relation.active
        ]
