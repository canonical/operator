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

import logging

import ops

from ._buffer import Destination
from .vendor.charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferRequires,
)
from .vendor.charms.tempo_coordinator_k8s.v0.tracing import (
    AmbiguousRelationUsageError,
    ProtocolNotRequestedError,
    TracingEndpointRequirer,
)

logger = logging.getLogger(__name__)


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
                f"{tracing_relation_name=} {relation.interface_name=} when 'tracing' is expected"
            )

        self._tracing = TracingEndpointRequirer(
            self.charm,
            tracing_relation_name,
            protocols=['otlp_http'],
        )

        for event in (
            self.charm.on.start,
            self.charm.on.upgrade_charm,
            self._tracing.on.endpoint_changed,
            self._tracing.on.endpoint_removed,
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
                    f"{ca_relation_name=} {relation.interface_name=} when 'certificate_transfer' "
                    'is expected'
                )

            self._certificate_transfer = CertificateTransferRequires(charm, ca_relation_name)

            for event in (
                self._certificate_transfer.on.certificate_set_updated,
                self._certificate_transfer.on.certificates_removed,
            ):
                self.framework.observe(event, self._reconcile)
        else:
            self._certificate_transfer = None

    def _reconcile(self, _event: ops.EventBase):
        dst = self._get_destination()
        ops.tracing.set_destination(url=dst.url, ca=dst.ca)

    def _get_destination(self) -> Destination:
        try:
            if not self._tracing.is_ready():
                return Destination(None, None)

            base_url = self._tracing.get_endpoint('otlp_http')

            if not base_url:
                return Destination(None, None)

            if not base_url.startswith(('http://', 'https://')):
                logger.warning('The base_url=%s must be an HTTP or an HTTPS URL', base_url)
                return Destination(None, None)

            url = f'{base_url.rstrip("/")}/v1/traces'

            if url.startswith('http://'):
                return Destination(url, None)

            if not self._certificate_transfer:
                return Destination(url, self.ca_data)

            ca = self._get_ca()
            if not ca:
                return Destination(None, None)

            return Destination(url, ca)
        except (
            ops.TooManyRelatedAppsError,
            AmbiguousRelationUsageError,
            ProtocolNotRequestedError,
        ):
            # These should not really happen, as we've set up a single relation
            # and requested the protocol explicitly.
            logger.exception('Error getting the tracing destination')
            return Destination(None, None)

    def _get_ca(self) -> str | None:
        if not self.ca_relation_name:
            return None

        ca_rel = self.model.get_relation(self.ca_relation_name)
        if not ca_rel:
            return None

        if not self._certificate_transfer:
            return None

        if not self._certificate_transfer.is_ready(ca_rel):
            return None

        ca_list = self._certificate_transfer.get_all_certificates(ca_rel.id)
        if not ca_list:
            return None

        return '\n'.join(sorted(ca_list))
