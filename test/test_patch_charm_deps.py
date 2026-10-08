# Copyright 2026 Canonical Ltd.
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

"""Tests for .github/patch-charm-deps.py, which the published charms tests run."""

from __future__ import annotations

import configparser
import importlib.util
import pathlib
import shlex
import subprocess
from typing import Any

import pytest

# The script needs tomllib, which is new in Python 3.11.
pytest.importorskip('tomllib')

_SCRIPT = pathlib.Path(__file__).parent.parent / '.github' / 'patch-charm-deps.py'
_spec = importlib.util.spec_from_file_location('patch_charm_deps', _SCRIPT)
assert _spec is not None and _spec.loader is not None
patch_charm_deps: Any = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(patch_charm_deps)

OPS = '/wheels/ops-3.9.0-py3-none-any.whl'
SCENARIO = '/wheels/ops_scenario-8.9.0-py3-none-any.whl'
TRACING = '/wheels/ops_tracing-3.9.0-py3-none-any.whl'
INSTALL = [
    'uv',
    'pip',
    'install',
    '--reinstall-package',
    'ops',
    '--reinstall-package',
    'ops-scenario',
    OPS,
    SCENARIO,
]


class TestWheelInstallCommands:
    def test_without_tracing_wheel(self):
        assert patch_charm_deps._wheel_install_commands(OPS, SCENARIO, None) == [INSTALL]

    def test_with_tracing_wheel_only_installs_it_where_present(self):
        [command] = patch_charm_deps._wheel_install_commands(OPS, SCENARIO, TRACING)
        assert command[:2] == ['sh', '-c']
        with_tracing = [*INSTALL, '--reinstall-package', 'ops-tracing', TRACING]
        assert command[2] == (
            f'if uv pip show --quiet ops-tracing; then {shlex.join(with_tracing)}; '
            f'else {shlex.join(INSTALL)}; fi'
        )


class TestInsertAfterLockedInstallsIni:
    def test_after_each_locked_install(self):
        commands = '\n'.join([
            '',
            'poetry install --only main,unit',
            'pytest tests/unit',
            'uv sync --group static',
            'pyright',
        ])
        assert patch_charm_deps._insert_after_locked_installs_ini(commands, ['WHEELS']) == (
            '\n'.join([
                '',
                'poetry install --only main,unit',
                'WHEELS',
                'pytest tests/unit',
                'uv sync --group static',
                'WHEELS',
                'pyright',
            ])
        )

    def test_after_a_continued_command(self):
        commands = '\n'.join(['', 'poetry install \\', '    --only main,unit', 'pytest'])
        assert patch_charm_deps._insert_after_locked_installs_ini(commands, ['WHEELS']) == (
            '\n'.join(['', 'poetry install \\', '    --only main,unit', 'WHEELS', 'pytest'])
        )

    def test_no_locked_install(self):
        commands = '\npip install -r requirements.txt\npytest'
        assert patch_charm_deps._insert_after_locked_installs_ini(commands, ['WHEELS']) == (
            commands
        )


class TestInsertAfterLockedInstallsToml:
    def test_after_each_locked_install(self):
        commands = [
            ['poetry', 'install', '--only', 'main,unit'],
            ['pytest', 'tests/unit'],
            ['uv', 'sync', '--group', 'static'],
            ['pyright'],
        ]
        assert patch_charm_deps._insert_after_locked_installs_toml(commands, [['WHEELS']]) == [
            ['poetry', 'install', '--only', 'main,unit'],
            ['WHEELS'],
            ['pytest', 'tests/unit'],
            ['uv', 'sync', '--group', 'static'],
            ['WHEELS'],
            ['pyright'],
        ]

    def test_no_locked_install(self):
        commands = [['pytest', 'tests/unit']]
        assert patch_charm_deps._insert_after_locked_installs_toml(commands, [['WHEELS']]) == (
            commands
        )


class TestAddToxPipCommandsIni:
    def _patch(self, tmp_path: pathlib.Path, section: str, tracing: str | None):
        tox_ini = tmp_path / 'tox.ini'
        tox_ini.write_text(section)
        patch_charm_deps.add_tox_pip_commands_ini(tox_ini, 'testenv:unit', OPS, SCENARIO, tracing)
        config = configparser.ConfigParser()
        config.read(tox_ini)
        return config['testenv:unit']

    def test_without_tracing_wheel(self, tmp_path: pathlib.Path):
        section = self._patch(
            tmp_path,
            '[testenv:unit]\ncommands =\n    poetry install\n    pytest\n',
            None,
        )
        assert section['allowlist_externals'].split() == ['uv']
        assert [shlex.split(line) for line in section['commands_pre'].split('\n') if line] == [
            INSTALL
        ]
        assert [shlex.split(line) for line in section['commands'].split('\n') if line] == [
            ['poetry', 'install'],
            INSTALL,
            ['pytest'],
        ]

    def test_with_tracing_wheel(self, tmp_path: pathlib.Path):
        section = self._patch(
            tmp_path,
            '[testenv:unit]\nallowlist_externals =\n    poetry\ncommands =\n    pytest\n',
            TRACING,
        )
        assert section['allowlist_externals'].split() == ['poetry', 'sh']
        [command] = [shlex.split(line) for line in section['commands_pre'].split('\n') if line]
        # tox splits each command with shlex, so the script must come back whole.
        assert command == patch_charm_deps._wheel_install_commands(OPS, SCENARIO, TRACING)[0]

    def test_existing_allowlist_entry(self, tmp_path: pathlib.Path):
        section = self._patch(
            tmp_path, '[testenv:unit]\nallowlist_externals = uv\ncommands = pytest\n', None
        )
        assert section['allowlist_externals'].split() == ['uv']


class TestAddToxPipCommandsToml:
    def _patch(self, tmp_path: pathlib.Path, env: str, tracing: str | None) -> dict[str, Any]:
        tox_toml = tmp_path / 'tox.toml'
        tox_toml.write_text(env)
        patch_charm_deps.add_tox_pip_commands_toml(
            tox_toml, 'testenv:unit', OPS, SCENARIO, tracing
        )
        return patch_charm_deps.tomllib.loads(tox_toml.read_text())['env']['unit']

    def test_without_tracing_wheel(self, tmp_path: pathlib.Path):
        env = self._patch(tmp_path, '[env.unit]\ncommands = [["uv", "sync"], ["pytest"]]\n', None)
        assert env['allowlist_externals'] == ['uv']
        assert env['commands_pre'] == [INSTALL]
        assert env['commands'] == [['uv', 'sync'], INSTALL, ['pytest']]

    def test_with_tracing_wheel(self, tmp_path: pathlib.Path):
        env = self._patch(
            tmp_path,
            '[env.unit]\nallowlist_externals = ["poetry"]\ncommands = [["pytest"]]\n',
            TRACING,
        )
        assert env['allowlist_externals'] == ['poetry', 'sh']
        assert env['commands_pre'] == patch_charm_deps._wheel_install_commands(
            OPS, SCENARIO, TRACING
        )


class TestLockedOpsExtras:
    def test_collects_extras_from_every_requirement_on_ops(self):
        lock = {
            'package': [
                {'name': 'charm', 'dependencies': [{'name': 'ops', 'extra': ['testing']}]},
                {'name': 'charmlib', 'dependencies': [{'name': 'ops', 'extra': ['tracing']}]},
                {'name': 'other', 'dependencies': [{'name': 'other-lib', 'extra': ['x']}]},
            ]
        }
        assert patch_charm_deps._locked_ops_extras(lock) == {'testing', 'tracing'}

    def test_no_extras(self):
        lock = {'package': [{'name': 'charm', 'dependencies': [{'name': 'ops'}]}]}
        assert patch_charm_deps._locked_ops_extras(lock) == set()


class TestOverrideUvLock:
    def test_replaces_only_the_wheel_packages(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ):
        (tmp_path / 'pyproject.toml').write_text(
            '[project]\nname = "charm"\n\n'
            '[tool.uv]\noverride-dependencies = [\n'
            '    "ops[testing]==2.17",\n'
            '    "ops-scenario>=7",\n'
            '    "ops-tracing ; python_version >= \'3.10\'",\n'
            '    "opsish==1.0",\n'
            '    "pydantic<2",\n'
            ']\n'
        )
        (tmp_path / 'uv.lock').write_text(
            '[[package]]\nname = "charm"\ndependencies = [{ name = "ops", extra = ["tracing"] }]\n'
        )
        calls: list[list[str]] = []

        def fake_run(args: list[str], **kwargs: Any):
            calls.append(args)
            return subprocess.CompletedProcess(args, 0, '', '')

        monkeypatch.setattr(patch_charm_deps.subprocess, 'run', fake_run)
        wheels = {'ops': OPS, 'ops-scenario': SCENARIO, 'ops-tracing': TRACING}

        assert patch_charm_deps._override_uv_lock(tmp_path, wheels)

        data = patch_charm_deps.tomllib.loads((tmp_path / 'pyproject.toml').read_text())
        uri = {name: pathlib.Path(wheel).resolve().as_uri() for name, wheel in wheels.items()}
        assert data['tool']['uv']['override-dependencies'] == [
            'opsish==1.0',
            'pydantic<2',
            f'ops[tracing] @ {uri["ops"]}',
            f'ops-scenario @ {uri["ops-scenario"]}',
            f'ops-tracing @ {uri["ops-tracing"]}',
        ]
        assert calls == [['uv', 'lock', '--python-preference', 'system']]

    def test_no_pyproject(self, tmp_path: pathlib.Path):
        (tmp_path / 'uv.lock').write_text('')
        assert not patch_charm_deps._override_uv_lock(tmp_path, {'ops': OPS})
