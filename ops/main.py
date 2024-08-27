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

import warnings
from typing import Optional, Type

import ops.charm

from . import _main


def main(charm_class: Type[ops.charm.CharmBase], use_juju_for_storage: Optional[bool] = None):
    """Legacy entrypoint to set up the charm and dispatch the observed event.

    The event name is based on the way this executable was called (argv[0]).

    .. jujuremoved:: 4.0
        The ``use_juju_for_storage`` argument is not available from Juju 4.0

    Args:
        charm_class: the charm class to instantiate and receive the event.
        use_juju_for_storage: whether to use controller-side storage. If not specified
            then Kubernetes charms that haven't previously used local storage and that
            are running on a new enough Juju default to controller-side storage,
            otherwise local storage is used.

    .. deprecated:: 2.16.0
        This entrypoint has been deprecated, use `ops.main()` instead.
    """
    warnings.warn(
        'Calling `ops.main.main()` is deprecated, call `ops.main()` instead',
        DeprecationWarning,
        stacklevel=2,
    )
    return _main.main(charm_class=charm_class, use_juju_for_storage=use_juju_for_storage)
