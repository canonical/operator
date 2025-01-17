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
"""FIXME docstring.

If OTEL guts are installed, real implementation.
If OTEL deps are missing, ProxyTracer pointing to NoOpTracer, doing nothing.
"""

from __future__ import annotations

import logging

from ops.tracing._hacks import remove_stale_otel_sdk_packages

# FIXME must this hack be run before OTEL packages are imported?
remove_stale_otel_sdk_packages()


try:
    from . import _fixme as _fixme
except ImportError:
    logging.exception('FIXME deps')
    _fixme = None


def setup_tracing(charm_class_name: str) -> None:
    """Setup tracing for this "dispatch" of the charm code."""
    if not _fixme:
        return
    _fixme.setup_tracing(charm_class_name)


def shutdown_tracing() -> None:
    """Send out as much as possible, if possible."""
    if not _fixme:
        return
    try:
        _fixme.shutdown_tracing()
    except Exception:
        logging.exception('failed to flush tracing')


def reset_tracing():
    """FIXME: decide if this should be public, maybe it's oinly for testing?"""
    ...
