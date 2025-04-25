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
        receive-ca-cert:
            interface: certificate_transfer
            limit: 1
            optional: true

If you're migrating from the ``charm-tracing`` charm lib, you most likely already
have relations like these. If the names of the relations differ from this recipe, please
adjust the code on the rest of this page to your relation names.

.. hint::
    Make sure to include the Rust build packages in your ``charmcraft.yaml``, because
    this library depends on ``pydantic-core`` via ``pydantic``.

    .. code-block:: yaml

        parts:
            charm:
                plugin: charm
                source: .
                build-packages:
                    - cargo

    If you're migrating from the ``charm-tracing`` charm lib, this configuration is
    likely already in place.

In your charm, add and initialise the ``Tracing`` object.::

    import ops

    class SomeCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            ...
            self.tracing = ops.tracing.Tracing(
                self,
                tracing_relation_name='charm-tracing',
                ca_relation_name='receive-ca-cert',
            )

The tracing relation name is required, while the CA relation name is optional,
as it is possible to use a system certificate authority list, provide a custom
list (for example from the ``certify`` package) or export the trace data over
HTTP connections only. Declaring both relations is most common.

Note that you don't have to ``import ops.tracing``, that name is automatically
available when your Python project depends on ``ops[tracing]``.
"""

from ._api import Tracing
from ._backend import mark_observed as _mark_observed
from ._backend import set_destination
from ._backend import setup as _setup
from ._backend import shutdown as _shutdown

__all__ = [
    'Tracing',
    '_mark_observed',
    '_setup',
    '_shutdown',
    'set_destination',
]
