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
"""
Verify that `ops.main` can be invoked in every possible way.

Validate that main can be called at runtime and according to the static type checker.

Runtime tests:
- Ensure that `ops.main` and `ops.main.main` can be invoked with a charm class.
- Across 3 import styles: ops, main from ops, main from ops.main.
- Confirm that calling main without a charm class fails.

Typing tests:
- Ensure that `ops.main` and `ops.main.main` are callable with correct argument.
- Across same 3 import styles as above.
- Confirm that calling main without a charm class is caught by static analysis.
"""

import os
from pathlib import Path
from typing import Callable, Type
from unittest.mock import Mock

import pytest

import ops

Reset = Callable[[], None]


def type_test_dummy(_arg: Callable[[Type[ops.CharmBase], bool], None]):
    """Usage:
    from somewhere import main
    type_test_dummy(main)
    """


def type_test_negative(_arg: Callable[[], None]):
    """Usage:
    from somewhere import main
    type_test_negative(main)  # type: ignore

    The `reportUnnecessaryTypeIgnoreComment` setting is expected to kick up a fuss,
    should the passed argument match the expected argument type.
    """


@pytest.fixture
def reset(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr('sys.argv', ('hooks/install',))
    monkeypatch.setattr('ops._main._emit_charm_event', Mock())
    monkeypatch.setattr('ops._main._Manager._setup_root_logging', Mock())
    monkeypatch.setattr('ops.charm._evaluate_status', Mock())
    monkeypatch.setenv('JUJU_CHARM_DIR', str(tmp_path))
    monkeypatch.setenv('JUJU_UNIT_NAME', 'test_main/0')
    monkeypatch.setenv('JUJU_MODEL_NAME', 'mymodel')
    monkeypatch.setenv('JUJU_DISPATCH_PATH', 'hooks/install')
    monkeypatch.setenv('JUJU_VERSION', '3.5.0')
    (tmp_path / 'metadata.yaml').write_text('name: test', encoding='utf-8')
    (tmp_path / 'dispatch').absolute().touch(mode=0o755)

    yield (reset := lambda: os.environ.pop('OPERATOR_DISPATCH', None))

    reset()


class IdleCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)


def test_top_level_import(reset: Reset):
    import ops

    type_test_dummy(ops.main.__call__)  # pyright  is quirky
    type_test_dummy(ops.main.main)
    type_test_negative(ops.main.__call__)  # type: ignore
    type_test_negative(ops.main.main)  # type: ignore

    ops.main(IdleCharm)

    reset()
    ops.main.main(IdleCharm)

    with pytest.raises(TypeError):
        ops.main()  # type: ignore

    with pytest.raises(TypeError):
        ops.main.main()  # type: ignore


def test_submodule_import(reset: Reset):
    import ops.main

    type_test_dummy(ops.main.__call__)  # type: ignore FIXME
    type_test_dummy(ops.main.main)
    type_test_negative(ops.main.__call__)  # type: ignore
    type_test_negative(ops.main.main)  # type: ignore

    ops.main(IdleCharm)  # type: ignore FIXME

    reset()
    ops.main.main(IdleCharm)

    with pytest.raises(TypeError):
        ops.main()  # type: ignore

    with pytest.raises(TypeError):
        ops.main.main()  # type: ignore


def test_import_from_top_level_module(reset: Reset):
    from ops import main

    type_test_dummy(main.__call__)
    type_test_dummy(main.main)
    type_test_negative(main.__call__)  # type: ignore
    type_test_negative(main.main)  # type: ignore

    main(IdleCharm)

    reset()
    main.main(IdleCharm)

    with pytest.raises(TypeError):
        main()  # type: ignore

    with pytest.raises(TypeError):
        main.main()  # type: ignore


def test_import_from_submodule(reset: Reset):
    from ops.main import main

    type_test_dummy(main)
    type_test_negative(main)  # type: ignore

    main(IdleCharm)

    with pytest.raises(TypeError):
        main()  # type: ignore
