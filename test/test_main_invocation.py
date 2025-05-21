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

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import Mock

import pytest

import ops


@pytest.fixture
def charm_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr('sys.argv', ('hooks/install',))
    monkeypatch.setattr('ops._main._Manager._emit_charm_event', Mock())
    monkeypatch.setattr('ops._main._Manager._setup_root_logging', Mock())
    monkeypatch.setattr('ops.charm._evaluate_status', Mock())
    monkeypatch.setenv('JUJU_CHARM_DIR', str(tmp_path))
    monkeypatch.setenv('JUJU_UNIT_NAME', 'test_main/0')
    monkeypatch.setenv('JUJU_MODEL_NAME', 'mymodel')
    monkeypatch.setenv('JUJU_DISPATCH_PATH', 'hooks/install')
    monkeypatch.setenv('JUJU_VERSION', '3.5.0')
    (tmp_path / 'metadata.yaml').write_text('name: test', encoding='utf-8')
    (tmp_path / 'dispatch').absolute().touch(mode=0o755)

    yield

    os.environ.pop('OPERATOR_DISPATCH', None)


def test_top_level_import(charm_env: None):
    import ops

    ops.main(ops.CharmBase)

    with pytest.raises(TypeError):
        ops.main()  # type: ignore


def test_top_level_import_legacy_call(charm_env: None):
    import ops

    ops.main.main(ops.CharmBase)

    with pytest.raises(TypeError):
        ops.main.main()  # type: ignore


def test_submodule_import(charm_env: None):
    import ops.main

    ops.main(ops.CharmBase)  # type: ignore # https://github.com/microsoft/pyright/issues/8830

    with pytest.raises(TypeError):
        ops.main()  # type: ignore


def test_submodule_import_legacy_call(charm_env: None):
    import ops.main

    ops.main.main(ops.CharmBase)

    with pytest.raises(TypeError):
        ops.main.main()  # type: ignore


def test_import_from_top_level_module(charm_env: None):
    from ops import main

    main(ops.CharmBase)

    with pytest.raises(TypeError):
        main()  # type: ignore


def test_import_from_top_level_module_legacy_call(charm_env: None):
    from ops import main

    main.main(ops.CharmBase)

    with pytest.raises(TypeError):
        main.main()  # type: ignore


def test_legacy_import_from_submodule(charm_env: None):
    from ops.main import main

    main(ops.CharmBase)

    with pytest.raises(TypeError):
        main()  # type: ignore
