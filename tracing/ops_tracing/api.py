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

from dataclasses import asdict

import ops

from .const import Config
from .vendor.charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferRequires,
)
from .vendor.charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

# Databag operations can be trivially re-coded in pure Python:
# - we'd get rid of pydantic dependency
# - we'd avoid init-time relation listing and databag update (tracing)
# - it's trivial to read the relation data bags, see below.
#
#
# certificate_transfer:
# - client doesn't write to the databag
# - client reads this from the databag:
# ```
# {"certificates": list[str]}
# ```
#
#
# tracing:
# - client leader sets own app data on every relation:
# ```
# {"receivers": ["otlp_http"]}
# ```
#
# - client reads this from remote_app_data:
# ```
# {"receivers": [
#     {
#         "protocol": {"name": "otlp_http", "type": "http"},
#         "url": "http//somewhere:4318/v1/traces",
#     },
#     ...,
# ]}
# ```


class Tracing(ops.Object):
    """Tracing service."""

    _certificate_transfer: CertificateTransferRequires | None

    def __init__(
        self,
        charm: ops.CharmBase,
        tracing_relation_name: str,
        ca_relation_name: str | None = None,
        ca_data: str | None = None,
    ):
        """Initialise the tracing service.

        Args:
            charm: your charm instange
            tracing_relation_name: the name of the relation that provides the
                destination to send tracing data to.
            ca_relation_name: the name of the relation that provides the CA
                list to validate the tracing destination against.
            ca_data: a fixed CA list (PEM bundle, a multi-line string).

        If the destination is resolved to an HTTPS URL, a CA list is required
        to establish a secure connection.

        The CA list can be provided over a relation via ``ca_relation_name=``
        argument, as a fixed string via ``ca_data`` argument, or the system CA
        list will be used if the earlier two are both ``None``.

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
                send-ca-cert:
                    interface: certificate_transfer
                    limit: 1
                    optional: true

            # src/charm.py
            import ops.tracing

            class SomeCharm(ops.CharmBase):
                def __init__(self, framework: ops.Framework):
                    ...
                    self.tracing = ops.tracing.Tracing(
                        tracing_relation_name="charm-tracing",
                        ca_relation_name="send-ca-cert",
                    )
        """
        super().__init__(charm, f'{tracing_relation_name}+{ca_relation_name}')
        self.charm = charm
        self.tracing_relation_name = tracing_relation_name
        self.ca_relation_name = ca_relation_name
        self.ca_data = ca_data

        # NOTE: Pietro recommends inspecting charm meta to validate the relation
        # that way a badly written charm crashes in early testing.
        if not (relation := self.charm.meta.relations.get(tracing_relation_name)):
            raise ValueError(f'{tracing_relation_name=} is not declared in charm metadata')
        if (relation_role := relation.role) is not ops.RelationRole.requires:
            raise ValueError(
                f"{tracing_relation_name=} {relation_role=} when 'requires' is expected"
            )
        if (interface_name := relation.interface_name) != 'tracing':
            raise ValueError(
                f"{tracing_relation_name=} {interface_name=} when 'tracing' is expected"
            )

        self._tracing = TracingEndpointRequirer(
            self.charm,
            tracing_relation_name,
            protocols=['otlp_http'],
        )
        # FIXME: handle the vendored charm lib init-time exceptions
        # convert the to ValueError() I think...
        # RelationNotFoundError,
        # RelationInterfaceMismatchError,
        # RelationRoleMismatchError,

        for event in (
            self.charm.on.start,
            self.charm.on.upgrade_charm,
            self._tracing.on.endpoint_changed,
            self._tracing.on.endpoint_removed,
        ):
            self.framework.observe(event, self._reconcile)

        self._certificate_transfer = None
        if ca_relation_name:
            if not (relation := self.charm.meta.relations.get(ca_relation_name)):
                raise ValueError(f'{ca_relation_name=} is not declared in charm metadata')
            if (relation_role := relation.role) is not ops.RelationRole.requires:
                raise ValueError(
                    f"{ca_relation_name=} {relation_role=} when 'requires' is expected"
                )
            if (interface_name := relation.interface_name) != 'certificate_transfer':
                raise ValueError(
                    f"{ca_relation_name=} {interface_name=} when 'certificate_transfer' "
                    'is expected'
                )

            self._certificate_transfer = CertificateTransferRequires(charm, ca_relation_name)

            for event in (
                self._certificate_transfer.on.certificate_set_updated,
                self._certificate_transfer.on.certificates_removed,
            ):
                self.framework.observe(event, self._reconcile)

    def _reconcile(self, _event: ops.EventBase):
        ops.tracing.set_destination(**asdict(self._get_config()))

    def _get_config(self) -> Config:
        if not self._tracing.is_ready():
            return Config(None, None)

        url = self._tracing.get_endpoint('otlp_http')

        if not url or not url.startswith(('http://', 'https://')):
            return Config(None, None)

        if url.startswith('http://'):
            return Config(url, None)

        if not self._certificate_transfer:
            return Config(url, self.ca_data)

        ca_rel = self.model.get_relation(self.ca_relation_name) if self.ca_relation_name else None
        ca_rel_id = ca_rel.id if ca_rel else None

        if ca_rel and self._certificate_transfer.is_ready(ca_rel):
            return Config(
                url, '\n'.join(sorted(self._certificate_transfer.get_all_certificates(ca_rel_id)))
            )
        else:
            return Config(None, None)
