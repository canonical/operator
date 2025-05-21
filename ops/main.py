# Copyright 2020 Canonical Ltd.
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

"""Support legacy ops.main.main() import."""

from __future__ import annotations

from . import _main
from . import charm as _charm

# Re-export specific set of symbols that Scenario 6 imports from ops.main
from ._main import (  # noqa: F401
    CHARM_STATE_FILE,  # type: ignore[reportUnusedImport]
    _Dispatcher,  # type: ignore[reportUnusedImport]
    _get_event_args,  # type: ignore[reportUnusedImport]
    logger,  # type: ignore[reportUnusedImport]
)


def main(charm_class: type[_charm.CharmBase], use_juju_for_storage: bool | None = None):
    """Legacy entrypoint to set up the charm and dispatch the observed event.

    .. deprecated:: 2.16.0
        This entrypoint has been deprecated, use `ops.main()` instead.

    See `ops.main() <#ops-main-entry-point>`_ for details.
    """
    return _main.main(charm_class=charm_class, use_juju_for_storage=use_juju_for_storage)
