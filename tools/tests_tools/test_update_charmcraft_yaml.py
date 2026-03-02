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
import enum
import pathlib
import sys
import textwrap

import pytest
import yaml
from ops_tools._update_charmcraft_yaml import (
    _insert_into_charmcraft_yaml,
    get_class_from_module,
    main,
)

import ops

# -- _insert_into_charmcraft_yaml tests --


def test_insert_section_with_content_before_and_after():
    raw = textwrap.dedent("""\
        name: my-charm
        config:
          options:
            old-key:
              type: string
        actions:
          do-thing:
            description: old
    """)
    replacement = {'config': {'options': {'new-key': {'type': 'int'}}}}
    result = _insert_into_charmcraft_yaml(raw, 'config', replacement)
    assert 'new-key' in result
    assert 'old-key' not in result
    # Content after the section is preserved.
    assert 'actions:' in result
    assert 'do-thing' in result
    # Content before the section is preserved.
    assert 'name: my-charm' in result


def test_insert_section_at_start_of_file():
    raw = textwrap.dedent("""\
        config:
          options:
            old-key:
              type: string
        name: my-charm
    """)
    replacement = {'config': {'options': {'new-key': {'type': 'int'}}}}
    result = _insert_into_charmcraft_yaml(raw, 'config', replacement)
    assert 'new-key' in result
    assert 'old-key' not in result
    assert 'name: my-charm' in result


def test_insert_section_at_end_of_file():
    raw = textwrap.dedent("""\
        name: my-charm
        config:
          options:
            old-key:
              type: string
    """)
    replacement = {'config': {'options': {'new-key': {'type': 'int'}}}}
    result = _insert_into_charmcraft_yaml(raw, 'config', replacement)
    assert 'new-key' in result
    assert 'old-key' not in result
    assert 'name: my-charm' in result


def test_insert_section_not_present():
    raw = textwrap.dedent("""\
        name: my-charm
    """)
    replacement = {'config': {'options': {'new-key': {'type': 'int'}}}}
    result = _insert_into_charmcraft_yaml(raw, 'config', replacement)
    assert 'new-key' in result
    assert 'name: my-charm' in result


def test_insert_into_empty_file():
    replacement = {'config': {'options': {'new-key': {'type': 'int'}}}}
    result = _insert_into_charmcraft_yaml('', 'config', replacement)
    assert 'new-key' in result


def test_comments_before_replaced_section_preserved():
    raw = textwrap.dedent("""\
        # This is a comment about the charm.
        name: my-charm
        config:
          options:
            old-key:
              type: string
        actions:
          do-thing:
            description: old
    """)
    replacement = {'config': {'options': {'new-key': {'type': 'int'}}}}
    result = _insert_into_charmcraft_yaml(raw, 'config', replacement)
    assert '# This is a comment about the charm.' in result


# -- get_class_from_module tests --


def test_get_class_module_colon_syntax():
    classes = list(get_class_from_module('builtins:int'))
    assert int in classes


def test_get_class_default_module(monkeypatch: pytest.MonkeyPatch):
    """Without a colon, the module defaults to 'src.charm'."""
    import types

    fake_module = types.ModuleType('src.charm')

    class FakeConfig:
        pass

    fake_module.FakeConfig = FakeConfig  # type: ignore
    monkeypatch.setitem(sys.modules, 'src.charm', fake_module)
    classes = list(get_class_from_module('FakeConfig'))
    assert FakeConfig in classes


def test_get_class_regex_matching():
    classes = list(get_class_from_module('builtins:.*Error'))
    # There are multiple Error classes in builtins.
    assert len(classes) > 1
    assert all('Error' in cls.__name__ for cls in classes)


# -- main() tests --


def test_main_stdout_default(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    """By default, main() prints to stdout and does not modify the file."""
    charmcraft = tmp_path / 'charmcraft.yaml'
    charmcraft.write_text(
        textwrap.dedent("""\
        name: my-charm
        config:
          options:
            old-key:
              type: string
    """)
    )
    original_content = charmcraft.read_text()

    # We need a module with a config class for main() to use.
    import types

    fake_module = types.ModuleType('src.charm')

    class MyConfig:
        my_str: str = 'foo'

    fake_module.MyConfig = MyConfig  # type: ignore
    monkeypatch.setitem(sys.modules, 'src.charm', fake_module)
    monkeypatch.setattr(sys, 'argv', ['prog', '--path', str(charmcraft), '--config', 'MyConfig'])

    main()

    captured = capsys.readouterr()
    assert 'my-str' in captured.out
    # File should be unchanged.
    assert charmcraft.read_text() == original_content


def test_main_update_flag_writes_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, capsys: pytest.CaptureFixture[str]
):
    """With --update, main() writes to the file."""
    charmcraft = tmp_path / 'charmcraft.yaml'
    charmcraft.write_text(
        textwrap.dedent("""\
        name: my-charm
        config:
          options:
            old-key:
              type: string
    """)
    )

    import types

    fake_module = types.ModuleType('src.charm')

    class MyConfig:
        my_str: str = 'foo'

    fake_module.MyConfig = MyConfig  # type: ignore
    monkeypatch.setitem(sys.modules, 'src.charm', fake_module)
    monkeypatch.setattr(
        sys, 'argv', ['prog', '--path', str(charmcraft), '--config', 'MyConfig', '--update']
    )

    main()

    updated = charmcraft.read_text()
    assert 'my-str' in updated
    assert 'old-key' not in updated
    # Nothing should be printed to stdout.
    captured = capsys.readouterr()
    assert captured.out == ''


# -- YAML output stability (verbatim comparison) --


@dataclasses.dataclass(frozen=True, kw_only=True)
class VerbatimConfig:
    my_str: str = 'foo'
    """A string value."""
    my_secret: ops.Secret | None = None
    """A user secret."""


def test_yaml_output_verbatim_config():
    """Ensure YAML output is stable as a string, not just as a dict."""
    import ops_tools

    schema = ops_tools.config_to_juju_schema(VerbatimConfig)
    output = yaml.safe_dump(schema, indent=2)
    # Note: ops.Secret | None currently resolves to 'string' because
    # _attr_to_yaml_type doesn't filter NoneType from union types.
    expected = textwrap.dedent("""\
        options:
          my-secret:
            description: A user secret.
            type: string
          my-str:
            default: foo
            description: A string value.
            type: string
    """)
    assert output == expected


# -- README example test --


def test_readme_config_example():
    """Match the exact config example from the README."""
    import ops_tools

    schema = ops_tools.config_to_juju_schema(VerbatimConfig)
    full = {'config': schema}
    output = yaml.safe_dump(full, indent=4)
    expected = textwrap.dedent("""\
        config:
            options:
                my-secret:
                    description: A user secret.
                    type: string
                my-str:
                    default: foo
                    description: A string value.
                    type: string
    """)
    assert output == expected


class Compression(enum.Enum):
    GZ = 'gzip'
    BZ = 'bzip2'


@dataclasses.dataclass(frozen=True, kw_only=True)
class RunBackupAction:
    """Backup the database."""

    filename: str
    """The name of the backup file."""
    compression: Compression = Compression.GZ
    """The type of compression to use."""


def test_readme_action_example():
    """Match the exact action example from the README."""
    import ops_tools

    schema = ops_tools.action_to_juju_schema(RunBackupAction)
    full = {'actions': schema}
    output = yaml.safe_dump(full, indent=4)
    # Note: for dataclass-based actions, str(Compression.GZ) produces
    # 'Compression.GZ' rather than 'gzip'.
    expected = textwrap.dedent("""\
        actions:
            run-backup:
                additionalProperties: false
                description: Backup the database.
                params:
                    compression:
                        default: Compression.GZ
                        description: The type of compression to use.
                        enum:
                        - gzip
                        - bzip2
                        type: string
                    filename:
                        description: The name of the backup file.
                        type: string
                required:
                - filename
    """)
    assert output == expected
