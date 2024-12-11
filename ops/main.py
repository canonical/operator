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

import inspect
import os
import warnings
from typing import Any, Optional, Type, Union

import ops.charm

from . import _main

# Re-export specific set of symbols that Scenario 6 imports from ops.main
from ._main import (  # noqa: F401
    CHARM_STATE_FILE,  # type: ignore[reportUnusedImport]
    _Dispatcher,  # type: ignore[reportUnusedImport]
    _get_event_args,  # type: ignore[reportUnusedImport]
    logger,  # type: ignore[reportUnusedImport]
)


def _top_frame():
    frame = inspect.currentframe()
    while frame:
        if frame.f_back is None:
            return frame
        frame = frame.f_back


def main(charm_class: Type[ops.charm.CharmBase], use_juju_for_storage: Optional[bool] = None):
    """Legacy entrypoint to set up the charm and dispatch the observed event.

    .. deprecated:: 2.16.0
        This entrypoint has been deprecated, use `ops.main()` instead.

    See `ops.main() <#ops-main-entry-point>`_ for details.
    """
    # Normally, we would do warnings.warn() with a DeprecationWarning, but at
    # this point in the charm execution, the framework has not been set up, so
    # we haven't had a chance to direct warnings where we want them to go. That
    # means that they'll end up going to stderr, and with actions that means
    # they'll end up being displayed to the user.
    # This means that we need to delay emitting the warning until the framework
    # has been set up, so we wrap the charm and do it on instantiation. However,
    # this means that a regular warning call won't provide the correct filename
    # and line number.
    # Note also that this will be logged with every event. Our assumption is
    # that this will be noticeable enough during integration testing that it
    # will get fixed before going into production.
    frame = _top_frame()
    assert frame is not None

    class DeprecatedMainCharmBase(charm_class):
        def __init__(self, *args: Any, **kwargs: Any):
            super().__init__(*args, **kwargs)

            _original_format = warnings.formatwarning

            def custom_warning_formatter(
                message: Union[str, Warning],
                category: Type[Warning],
                *args: Any,
                **kwargs: Any,
            ) -> str:
                """Like the default formatter, but patch in the filename and line number."""
                return (
                    f'{frame.f_code.co_filename}:{frame.f_lineno}: '
                    f'{category.__name__}: {message}'
                )

            try:
                warnings.formatwarning = custom_warning_formatter
                warnings.warn(
                    'Calling `ops.main()` is deprecated, call `ops.main()` instead',
                    DeprecationWarning,
                    stacklevel=2,
                )
            finally:
                warnings.formatwarning = _original_format

    return _main.main(
        charm_class=DeprecatedMainCharmBase, use_juju_for_storage=use_juju_for_storage
    )
