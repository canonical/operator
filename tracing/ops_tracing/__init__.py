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
"""The tracing facility for the Ops framework.

FIXME: more docs here, incl examples.

Declare the charm tracing interface and optionally the TLS interface in your
``charmcraft.yaml``. If you're migrating from the ``charm-tracing`` charm lib,
you most likely already have these::

    requires:
        charm-tracing:
            interface: tracing
            limit: 1
            optional: true
        send-ca-cert:
            interface: certificate_transfer
            limit: 1
            optional: true


Caveat: presently pulls in ``pydantic``, which means that Rust build packages
must be specified in your ``charmcraft.yaml``. If you're migrating from the
``charm-tracing`` charm lib, you most likely already have these::

    parts:
        charm:
            plugin: charm
            source: .
            build-packages:
                - rustc
                - cargo


Then add the Tracing object in your charm::

    import ops

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        ...
        self.tracing = ops.tracing.Tracing(
            self,
            tracing_relation_name='charm-tracing',
            ca_relation_name='send-ca-cert',
        )

Note that you don't have to ``import ops.tracing``.
"""

from .api import Tracing
from .backend import mark_observed, set_destination, setup

__all__ = [
    'Tracing',
    'mark_observed',
    'set_destination',
    'setup',
]
