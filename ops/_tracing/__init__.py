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
"""The tracing facility of the Operator Framework.

TODO: quick start, usage example.
"""

from __future__ import annotations

import opentelemetry.trace

import ops.version

tracer = opentelemetry.trace.get_tracer('ops', ops.version.version)


try:
    from .export import (
        mark_observed,
        set_tracing_destination,
        setup_tracing,
        shutdown_tracing,
    )
except ImportError:

    def mark_observed() -> None: ...
    def set_tracing_destination(*, url: str | None, ca: str | None = None) -> None: ...
    def setup_tracing(charm_class_name: str) -> None: ...
    def shutdown_tracing() -> None: ...


__all__ = [
    'mark_observed',
    'set_tracing_destination',
    'setup_tracing',
    'shutdown_tracing',
]
