# Copyright 2025 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not use this
# file except in compliance with the License. You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF
# ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.
"""Constants and helper types for the ops-tracing extension."""

from __future__ import annotations

from dataclasses import dataclass

EXPORT_TIMEOUT: int | float = 1  # seconds
"""How much to give OTLP span exporter has to push traces to the backend."""

SENDOUT_FACTOR: int = 2
"""How many buffered chunks to send out for each incoming chunk."""

BUFFER_FILE: str = '.tracing-data.db'
"""Name of the file whither data is buffered, located next to .unit-state.db."""


@dataclass
class Config:
    """Tracing destination configuration.

    NOTE: that empty string values may be coerced to None.
    """

    url: str | None
    """The URL to send tracing data to."""
    ca: str | None
    """CA list, a PEM bundle."""
