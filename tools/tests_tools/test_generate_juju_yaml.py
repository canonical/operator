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

from __future__ import annotations

import dataclasses
import sys
import textwrap
import types

import pytest
import yaml
from ops_tools._generate_juju_yaml import action_main, config_main


def _install_fake_charm_module(monkeypatch: pytest.MonkeyPatch, **attrs: type) -> None:
    module = types.ModuleType('src.charm')
    for name, value in attrs.items():
        setattr(module, name, value)
    monkeypatch.setitem(sys.modules, 'src.charm', module)


# -- Classes under test (defined at module scope so inspect.getsource works
# for attribute-docstring extraction). --


@dataclasses.dataclass(frozen=True, kw_only=True)
class OneStringConfig:
    my_str: str = 'foo'
    """A string value."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class ConfigA:
    a_str: str = 'a'


@dataclasses.dataclass(frozen=True, kw_only=True)
class ConfigB:
    b_int: int = 1


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunBackupAction:
    """Backup the database."""

    filename: str
    """The name of the backup file."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class ZebraAction:
    """Z."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class AlphaAction:
    """A."""


# -- generate-juju-config --


def test_config_main_single_class(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _install_fake_charm_module(monkeypatch, OneStringConfig=OneStringConfig)
    monkeypatch.setattr(sys, 'argv', ['generate-juju-config', 'OneStringConfig'])

    config_main()

    captured = capsys.readouterr()
    assert captured.out == textwrap.dedent("""\
        options:
          my-str:
            default: foo
            description: A string value.
            type: string
    """)


def test_config_main_merges_multiple_classes(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _install_fake_charm_module(monkeypatch, ConfigA=ConfigA, ConfigB=ConfigB)
    monkeypatch.setattr(sys, 'argv', ['generate-juju-config', 'ConfigA', 'ConfigB'])

    config_main()

    parsed = yaml.safe_load(capsys.readouterr().out)
    assert set(parsed['options']) == {'a-str', 'b-int'}


def test_config_main_with_explicit_module(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    module = types.ModuleType('my_pkg.config')
    module.ConfigA = ConfigA  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, 'my_pkg.config', module)
    monkeypatch.setattr(sys, 'argv', ['generate-juju-config', 'my_pkg.config:ConfigA'])

    config_main()

    parsed = yaml.safe_load(capsys.readouterr().out)
    assert 'a-str' in parsed['options']


def test_config_main_empty_without_classes_errors(monkeypatch: pytest.MonkeyPatch):
    # argparse enforces nargs='+', so zero classes is a usage error.
    monkeypatch.setattr(sys, 'argv', ['generate-juju-config'])
    with pytest.raises(SystemExit):
        config_main()


# -- generate-juju-actions --


def test_action_main_single_class(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _install_fake_charm_module(monkeypatch, RunBackupAction=RunBackupAction)
    monkeypatch.setattr(sys, 'argv', ['generate-juju-actions', 'RunBackupAction'])

    action_main()

    parsed = yaml.safe_load(capsys.readouterr().out)
    assert 'run-backup' in parsed
    assert parsed['run-backup']['description'] == 'Backup the database.'
    assert 'filename' in parsed['run-backup']['params']


def test_action_main_sorts_actions(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    _install_fake_charm_module(monkeypatch, ZebraAction=ZebraAction, AlphaAction=AlphaAction)
    monkeypatch.setattr(sys, 'argv', ['generate-juju-actions', 'ZebraAction', 'AlphaAction'])

    action_main()

    out = capsys.readouterr().out
    # alpha must appear before zebra in the output.
    assert out.index('alpha:') < out.index('zebra:')
