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

import opentelemetry.trace

from ops.tracing import _hacks

# FIXME must this hack be run before OTEL packages are imported?
_hacks.remove_stale_otel_sdk_packages()
tracer = opentelemetry.trace.get_tracer(__name__)


try:
    from . import _export
except ImportError:
    logging.exception('FIXME deps')
    _export = None


def setup_tracing(charm_class_name: str) -> None:
    """Setup tracing for this "dispatch" of the charm code."""
    if not _export:
        return
    _export.setup_tracing(charm_class_name)


@tracer.start_as_current_span('ops.configure_tracing_buffer')  # type: ignore
def configure_tracing_buffer(buffer_path: str) -> None:
    """FIXME docstring for public method."""
    if not _export:
        return
    _export.configure_tracing_buffer(buffer_path)


# FIXME make this cheap to call with very same arguments
# FIXME add CA cert arguments
@tracer.start_as_current_span('ops.configure_tracing_destination')  # type: ignore
def configure_tracing_destination(url: str) -> None:
    """FIXME docstring for public method."""
    if not _export:
        return
    _export.configure_tracing_destination(url)


def shutdown_tracing() -> None:
    """Send out as much as possible, if possible."""
    if not _export:
        return
    try:
        _export.shutdown_tracing()
    except Exception:
        logging.exception('failed to flush tracing')


def reset_tracing():
    """FIXME: decide if this should be public, maybe it's oinly for testing?"""
    ...
