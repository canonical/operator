# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""The tracing API for the charms."""

from __future__ import annotations

import json
import logging

import opentelemetry.trace
import ops

from ._buffer import Destination
from ._tracing_models import (
    CertificateTransferProviderAppData,
    CertificateTransferProviderUnitDataV0,
    CertificateTransferRequirerAppData,
    ReceiverProtocol,
    TracingProviderAppData,
    TracingRequirerAppData,
)

logger = logging.getLogger(__name__)
tracer = opentelemetry.trace.get_tracer('ops.tracing')


def _read_certificates(relation: ops.Relation) -> set[str] | None:
    """Parse the provider's certificates; ``None`` if neither v1 nor v0 parses.

    Reads the v1 app databag first (``certificates`` key). If the app databag
    has no certs and the relation has a remote unit, falls back to the v0 unit
    databag shape (``ca``/``certificate``/``chain``) a dual v0/v1 provider
    publishes when it hasn't seen ``version=1`` from us.
    """
    try:
        certificates = relation.load(CertificateTransferProviderAppData, relation.app).certificates
    except (json.JSONDecodeError, TypeError, ValueError):
        certificates = None

    if certificates:
        return certificates

    for unit in relation.units:
        try:
            v0 = relation.load(CertificateTransferProviderUnitDataV0, unit)
        except (json.JSONDecodeError, TypeError, ValueError):
            continue
        if v0.chain:
            return set(v0.chain)
        return {v0.ca, v0.certificate}

    return certificates


def _advertise_ca_version(charm: ops.CharmBase, ca_relation_name: str) -> None:
    """Write ``version=1`` to our own app databag on the ca relation (leader only).

    A dual v0/v1 ``certificate_transfer`` provider needs this to publish v1
    (app databag ``certificates``) rather than falling back to v0 (unit
    databag ``ca``/``certificate``/``chain``).
    """
    if not charm.unit.is_leader():
        return
    data = CertificateTransferRequirerAppData()
    try:
        for relation in charm.model.relations[ca_relation_name]:
            relation.save(data, charm.app)
    except ops.ModelError as e:
        msg = e.args[0] if e.args else b''
        if isinstance(msg, bytes) and msg.startswith(
            b'ERROR cannot read relation application settings: permission denied'
        ):
            logger.error('cannot advertise ca version on %s: %s', ca_relation_name, e)
            return
        raise


def _read_endpoint(relation: ops.Relation, protocol: ReceiverProtocol) -> str | None:
    """Return the URL the provider advertises for ``protocol`` on this relation."""
    try:
        data = relation.load(TracingProviderAppData, relation.app)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        logger.info('failed validating tracing provider databag for %s: %s', relation, e)
        return None
    for receiver in data.receivers:
        if receiver.protocol.name == protocol:
            return receiver.url
    return None


def _request_protocols(
    charm: ops.CharmBase, relation_name: str, protocols: list[ReceiverProtocol]
) -> None:
    """Publish ``protocols`` to every relation on ``relation_name`` (leader only)."""
    if not charm.unit.is_leader():
        return
    data = TracingRequirerAppData(receivers=protocols)
    try:
        for relation in charm.model.relations[relation_name]:
            relation.save(data, charm.app)
    except ops.ModelError as e:
        msg = e.args[0] if e.args else b''
        if isinstance(msg, bytes) and msg.startswith(
            b'ERROR cannot read relation application settings: permission denied'
        ):
            logger.error('cannot request tracing protocols on %s: %s', relation_name, e)
            return
        raise


class Tracing(ops.Object):
    """Initialise the tracing service.

    Usage:
        - Include ``ops[tracing]`` in your dependencies.
        - Declare the relations that the charm supports.
        - Initialise ``Tracing`` with the names of these relations.

    Example::

        # charmcraft.yaml
        requires:
            charm-tracing:
                interface: tracing
                limit: 1
                optional: true
            receive-ca-cert:
                interface: certificate_transfer
                limit: 1
                optional: true

        # src/charm.py
        import ops.tracing

        class SomeCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                ...
                self.tracing = ops.tracing.Tracing(
                    self,
                    tracing_relation_name="charm-tracing",
                    ca_relation_name="receive-ca-cert",
                )

    Args:
        charm: your charm instance
        tracing_relation_name: the name of the relation that provides the
            destination to send trace data to.
        ca_relation_name: the name of the relation that provides the CA
            list to validate the tracing destination against.
        ca_data: a fixed CA list (PEM bundle, a multi-line string).

    If the destination is resolved to an HTTPS URL, a CA list is required
    to establish a secure connection.

    The CA list can be provided over a relation via the ``ca_relation_name``
    argument, as a fixed string via the ``ca_data`` argument, or the system CA
    list will be used if the earlier two are both ``None``.
    """

    def __init__(
        self,
        charm: ops.CharmBase,
        tracing_relation_name: str,
        *,
        ca_relation_name: str | None = None,
        ca_data: str | None = None,
    ):
        """Initialise the tracing service."""
        with tracer.start_as_current_span('ops.tracing.Tracing'):
            super().__init__(charm, f'{tracing_relation_name}+{ca_relation_name}')
            self.charm = charm
            self.tracing_relation_name = tracing_relation_name
            self.ca_relation_name = ca_relation_name
            self.ca_data = ca_data

            if ca_relation_name is not None and ca_data is not None:
                raise ValueError('At most one of ca_relation_name, ca_data is allowed')

            # Validate the arguments manually to raise exceptions with helpful messages.
            relation = self.charm.meta.relations.get(tracing_relation_name)
            if not relation:
                raise ValueError(f'{tracing_relation_name=} is not declared in charm metadata')

            if relation.role is not ops.RelationRole.requires:
                raise ValueError(
                    f"{tracing_relation_name=} {relation.role=} when 'requires' is expected"
                )

            if relation.interface_name != 'tracing':
                raise ValueError(
                    f"{tracing_relation_name=} {relation.interface_name=} when 'tracing' is"
                    f' expected'
                )

            _request_protocols(self.charm, tracing_relation_name, ['otlp_http'])

            tracing_events = self.charm.on[tracing_relation_name]
            for event in (
                self.charm.on.start,
                self.charm.on.upgrade_charm,
                tracing_events.relation_changed,
                tracing_events.relation_broken,
            ):
                self.framework.observe(event, self._reconcile)

            if ca_relation_name:
                relation = self.charm.meta.relations.get(ca_relation_name)
                if not relation:
                    raise ValueError(f'{ca_relation_name=} is not declared in charm metadata')

                if relation.role is not ops.RelationRole.requires:
                    raise ValueError(
                        f"{ca_relation_name=} {relation.role=} when 'requires' is expected"
                    )
                if relation.interface_name != 'certificate_transfer':
                    raise ValueError(
                        f'{ca_relation_name=} {relation.interface_name=} when'
                        f" 'certificate_transfer' is expected"
                    )

                ca_events = self.charm.on[ca_relation_name]
                self.framework.observe(ca_events.relation_created, self._advertise_ca_version)
                for event in (ca_events.relation_changed, ca_events.relation_broken):
                    self.framework.observe(event, self._reconcile)

    def _reconcile(self, _event: ops.EventBase):
        dst = self._get_destination()
        ops.tracing.set_destination(url=dst.url, ca=dst.ca)

    def _advertise_ca_version(self, _event: ops.RelationCreatedEvent):
        # This handler is only registered when ca_relation_name is set.
        if not self.ca_relation_name:
            return
        _advertise_ca_version(self.charm, self.ca_relation_name)

    def _get_destination(self) -> Destination:
        try:
            relation = self.model.get_relation(self.tracing_relation_name)
        except ops.TooManyRelatedAppsError:
            # Shouldn't happen — the docs require limit=1 on the tracing relation.
            logger.exception('multiple tracing relations on %s', self.tracing_relation_name)
            return Destination(None, None)
        if not relation:
            return Destination(None, None)

        base_url = _read_endpoint(relation, 'otlp_http')
        if not base_url:
            return Destination(None, None)

        if not base_url.startswith(('http://', 'https://')):
            logger.warning('The base_url=%s must be an HTTP or an HTTPS URL', base_url)
            return Destination(None, None)

        url = f'{base_url.rstrip("/")}/v1/traces'

        if url.startswith('http://'):
            return Destination(url, None)

        if not self.ca_relation_name:
            return Destination(url, self.ca_data)

        ca = self._get_ca()
        if not ca:
            return Destination(None, None)

        return Destination(url, ca)

    def _get_ca(self) -> str | None:
        if not self.ca_relation_name:
            return None

        ca_rel = self.model.get_relation(self.ca_relation_name)
        if not ca_rel:
            return None

        ca_list = _read_certificates(ca_rel)
        if not ca_list:
            return None

        return '\n'.join(sorted(ca_list))
