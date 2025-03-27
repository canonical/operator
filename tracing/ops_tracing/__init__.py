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

"""The tracing facility for the Ops library.

Quick start
-----------

In your ``charmcraft.yaml``, declare the charm tracing relation with a ``tracing``
interface and optionally the TLS relation with a ``certificate_transfer`` interface.::

    requires:
        charm-tracing:
            interface: tracing
            limit: 1
            optional: true
        send-ca-cert:
            interface: certificate_transfer
            limit: 1
            optional: true

If you're migrating from the ``charm-tracing`` charm lib, you most likely already
have these relations, but do note their names.

Caveat: your ``charmcraft.yaml`` needs to include the Rust build packages, because
this library pulls in ``pydantic``.::

    parts:
        charm:
            plugin: charm
            source: .
            build-packages:
                - cargo

If you're migrating from the ``charm-tracing`` charm lib, that should already be the case.

In your charm, add the ``Tracing`` object.::

    import ops

    class SomeCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        ...
        self.tracing = ops.tracing.Tracing(
            self,
            tracing_relation_name='charm-tracing',
            ca_relation_name='send-ca-cert',
        )

Note that you don't have to ``import ops.tracing`` or ``import ops_tracing``.
When ``ops[tracing]`` has been added to your charm's dependencies, the Ops
library imports this library and re-exports it as ``ops.tracing``.
"""

from ._api import Tracing
from ._backend import mark_observed as _mark_observed
from ._backend import set_destination
from ._backend import setup as _setup

__all__ = [
    'Tracing',
    '_mark_observed',
    '_setup',
    'set_destination',
]
