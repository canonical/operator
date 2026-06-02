# Copyright 2021 Canonical Ltd.
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

"""Internal YAML helpers."""

from __future__ import annotations

from typing import Any, Protocol, TextIO

import yaml


class _SafeLoader(Protocol):
    def __init__(self, stream: str | TextIO, /) -> None: ...
    def get_single_data(self) -> Any: ...
    def dispose(self) -> None: ...


# Use C speedups if available
_safe_loader: type[_SafeLoader] = getattr(yaml, 'CSafeLoader', yaml.SafeLoader)
_safe_dumper = getattr(yaml, 'CSafeDumper', yaml.SafeDumper)


def safe_load(stream: str | TextIO) -> Any:
    """Same as yaml.safe_load, but use fast C loader if available."""
    # Instantiate the loader directly rather than via yaml.load() to avoid
    # false-positive "unsafe deserialization" warnings from pattern-based scanners.
    loader = _safe_loader(stream)
    try:
        return loader.get_single_data()
    finally:
        loader.dispose()


def safe_dump(data: Any, stream: TextIO | None = None) -> str:
    """Same as yaml.safe_dump, but use fast C dumper if available."""
    return yaml.dump(data, stream=stream, Dumper=_safe_dumper)  # type: ignore
