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
from typing import Callable, Type

import ops


def type_test_dummy(_arg: Callable[[Type[ops.CharmBase], bool], None]):
    """
    Helper to verify the function signature of ops.main and ops.main.main
    Usage:

    from somewhere import main

    type_test_dummy(main)
    """


def type_test_negative(_arg: Callable[[], None]):
    """
    Helper for negative tests of the function signatures of ops.main and ops.main.main
    Usage:

    from somewhere import main

    type_test_negative(main)  # type: ignore

    The `reportUnnecessaryTypeIgnoreComment` setting is expected to kick up a fuss,
    should the passed argument match the expected argument type.
    """


def top_level_import():
    import ops

    type_test_dummy(ops.main.__call__)  # pyright  is quirky
    type_test_dummy(ops.main.main)

    type_test_negative(ops.main.__call__)  # type: ignore
    type_test_negative(ops.main.main)  # type: ignore


def submodule_import():
    import ops.main

    type_test_dummy(ops.main.__call__)  # type: ignore # https://github.com/microsoft/pyright/issues/8830
    type_test_dummy(ops.main.main)

    type_test_negative(ops.main.__call__)  # type: ignore
    type_test_negative(ops.main.main)  # type: ignore


def import_from_top_level_module():
    from ops import main

    type_test_dummy(main.__call__)
    type_test_dummy(main.main)

    type_test_negative(main.__call__)  # type: ignore
    type_test_negative(main.main)  # type: ignore


def import_from_submodule():
    from ops.main import main

    type_test_dummy(main)

    type_test_negative(main)  # type: ignore
