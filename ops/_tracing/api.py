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
"""FIXME docstring."""

from __future__ import annotations

from typing import Any

import ops

from .vendor.charms.certificate_transfer_interface.v1.certificate_transfer import (
    CertificateTransferRequires,
)
from .vendor.charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer

# NOTE: the shape of certificate_transfer is `{"certificates": list[str]}`
# it is trivial to read the certificates out manually


class Tracing(ops.Object):
    """FIXME docstring."""

    _certificate_transfer: CertificateTransferRequires | None

    def __init__(
        self,
        charm: ops.CharmBase,
        tracing_relation_name: str,
        ca_relation_name: str | None = None,
        ca_data: str | None = None,
    ):
        """FIXME docstring.

        Include `ops[tracing]` in your dependencies.

        Declare the relations that the charm supports:

        ```yaml
        requires:
            charm-tracing:
                interface: tracing
                limit: 1
            send-ca-cert:
                interface: certificate_transfer
                limit: 1
        ```

        Initialise the tracing thing (FIXME) with the names of these relations.

        ```py
        import ops.tracing

        class SomeCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                ...
                self._tracing = ops.tracing.Tracing(
                    tracing_relation_name="charm-tracing",
                    ca_relation_name="send-ca-cart",
                )
        ```
        """
        super().__init__(charm, f'{tracing_relation_name}+{ca_relation_name}')
        self.charm = charm
        self.tracing_relation_name = tracing_relation_name
        self.ca_relation_name = ca_relation_name
        self.ca_data = ca_data

        # FIXME: Pietro recommends inspecting charm meta to validate the interface name
        assert self.charm.meta.relations[tracing_relation_name].interface_name == 'tracing'
        self._tracing = TracingEndpointRequirer(
            self.charm,
            tracing_relation_name,
            protocols=['otlp_http'],
        )

        # TODO: COS requirer

        for event in (
            # FIXME: validate this
            # - the start event may happen after relation-joined?
            # - the k8s container died and got restarted
            # - the vm [smth] crashed and got restarted
            self.charm.on.start,
            # In case the previous charm version has a relation but didn't save the URL
            self.charm.on.upgrade_charm,
            self._tracing.on.endpoint_changed,
            self._tracing.on.endpoint_removed,
        ):
            self.framework.observe(event, self._reconcile)

        self._certificate_transfer = None
        if ca_relation_name:
            self._certificate_transfer = CertificateTransferRequires(charm, ca_relation_name)
            assert (
                self.charm.meta.relations[ca_relation_name].interface_name
                == 'certificate_transfer'
            )
            for event in (
                self._certificate_transfer.on.certificate_set_updated,
                self._certificate_transfer.on.certificates_removed,
            ):
                self.framework.observe(event, self._reconcile)

    def _reconcile(self, _event: Any):
        url, ca = self._get_config()
        self.charm.set_tracing_destination(url=url, ca=ca)

    def _get_config(self) -> tuple[str | None, str | None]:
        if not self._tracing.is_ready():
            return None, None

        url = self._tracing.get_endpoint('otlp_http')

        if not url or not url.startswith(('http://', 'https://')):
            return None, None

        if url.startswith('http://'):
            return url, None

        if not self._certificate_transfer:
            return url, self.ca_data

        ca_rel = self.model.get_relation(self.ca_relation_name) if self.ca_relation_name else None
        ca_rel_id = ca_rel.id if ca_rel else None

        if ca_rel and self._certificate_transfer.is_ready(ca_rel):
            return url, '\n'.join(
                sorted(self._certificate_transfer.get_all_certificates(ca_rel_id))
            )
        else:
            return None, None
