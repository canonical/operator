# Copyright 2024 Canonical Ltd.
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
"""Validate the type signatures on ops.main().

This file doesn't contain any run-time tests, rather we rely on pyright to run over this code.
Assignment to a variable declared to follow a protocol is equivalent to backwards compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import ops


class CallableWithCharmClassOnly(Protocol):
    """Encapsulate main function type for simple charms.

    Supports:
    - ops.main(SomeCharm)
    - ops.main(charm_class=SomeCharm)
    """

    def __call__(self, charm_class: type[ops.charm.CharmBase]): ...


class CallableWithCharmClassAndStorageFlag(Protocol):
    """Encapsulate main function type for advanced charms.

    Supports permutations of:
    - ops.main(SomeCharm, False)
    - ops.main(charm_class=SomeCharm, use_juju_for_storage=False)
    """

    def __call__(
        self, charm_class: type[ops.charm.CharmBase], use_juju_for_storage: bool | None = None
    ): ...


class CallableWithoutArguments(Protocol):
    """Bad charm code should be caught by type checker.

    For example:
    - ops.main()  # type: ignore or pyright complains
    """

    def __call__(self): ...


@dataclass
class MainCalls:
    simple: CallableWithCharmClassOnly
    full: CallableWithCharmClassAndStorageFlag
    bad: CallableWithoutArguments


sink = MainCalls(None, None, None)  # type: ignore


def top_level_import() -> None:
    import ops

    sink.simple = ops.main
    sink.simple = ops.main.main
    sink.full = ops.main
    sink.full = ops.main.main
    sink.bad = ops.main  # type: ignore[assignment]
    sink.bad = ops.main.main  # type: ignore[assignment]


def submodule_import() -> None:
    import ops.main

    sink.simple = ops.main  # type: ignore # type checker limitation https://github.com/microsoft/pyright/issues/8830
    sink.simple = ops.main.main
    sink.full = ops.main  # type: ignore # type checker limitation https://github.com/microsoft/pyright/issues/8830
    sink.full = ops.main.main
    sink.bad = ops.main  # type: ignore[assignment]
    sink.bad = ops.main.main  # type: ignore[assignment]


def import_from_top_level_module() -> None:
    from ops import main

    sink.simple = main
    sink.simple = main.main
    sink.full = main
    sink.full = main.main
    sink.bad = main  # type: ignore[assignment]
    sink.bad = main.main  # type: ignore[assignment]


def import_from_submodule() -> None:
    from ops.main import main

    sink.simple = main
    sink.full = main
    sink.bad = main  # type: ignore[assignment]
