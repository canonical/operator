# Copyright 2019 Canonical Ltd.
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

import os
import pathlib
import shutil
import subprocess
import tempfile
import typing
import unittest

import pytest

import ops
from ops.jujucontext import _JujuContext
from ops.model import _ModelBackend
from ops.storage import SQLiteStorage


def fake_script(test_case: unittest.TestCase, name: str, content: str):
    if not hasattr(test_case, 'fake_script_path'):
        fake_script_path = tempfile.mkdtemp('-fake_script')
        old_path = os.environ['PATH']
        os.environ['PATH'] = os.pathsep.join([fake_script_path, os.environ['PATH']])

        def cleanup():
            shutil.rmtree(fake_script_path)
            os.environ['PATH'] = old_path

        test_case.addCleanup(cleanup)
        test_case.fake_script_path = pathlib.Path(fake_script_path)  # type: ignore

    template_args: typing.Dict[str, str] = {
        'name': name,
        'path': test_case.fake_script_path.as_posix(),  # type: ignore
        'content': content,
    }

    path: pathlib.Path = test_case.fake_script_path / name  # type: ignore
    with path.open('wt') as f:  # type: ignore
        # Before executing the provided script, dump the provided arguments in calls.txt.
        # ASCII 1E is RS 'record separator', and 1C is FS 'file separator', which seem appropriate.
        f.write(  # type: ignore
            """#!/bin/sh
{{ printf {name}; printf "\\036%s" "$@"; printf "\\034"; }} >> {path}/calls.txt
{content}""".format_map(template_args)
        )
    os.chmod(str(path), 0o755)  # type: ignore  # noqa: S103
    # TODO: this hardcodes the path to bash.exe, which works for now but might
    #       need to be set via environ or something like that.
    path.with_suffix('.bat').write_text(  # type: ignore
        f'@"C:\\Program Files\\git\\bin\\bash.exe" {path} %*\n'
    )


def fake_script_calls(
    test_case: unittest.TestCase, clear: bool = False
) -> typing.List[typing.List[str]]:
    calls_file: pathlib.Path = test_case.fake_script_path / 'calls.txt'  # type: ignore
    if not calls_file.exists():  # type: ignore
        return []

    # newline and encoding forced to linuxy defaults because on
    # windows they're written from git-bash
    with calls_file.open('r+t', newline='\n', encoding='utf8') as f:  # type: ignore
        calls = [line.split('\x1e') for line in f.read().split('\x1c')[:-1]]  # type: ignore
        if clear:
            f.truncate(0)  # type: ignore
    return calls  # type: ignore


def create_framework(
    request: pytest.FixtureRequest, *, meta: typing.Optional[ops.CharmMeta] = None
):
    env_backup = os.environ.copy()
    os.environ['PATH'] = os.pathsep.join([
        str(pathlib.Path(__file__).parent / 'bin'),
        os.environ['PATH'],
    ])
    os.environ['JUJU_UNIT_NAME'] = 'local/0'
    os.environ['JUJU_VERSION'] = '0.0.0'

    tmpdir = pathlib.Path(tempfile.mkdtemp())

    class CustomEvent(ops.EventBase):
        pass

    class TestCharmEvents(ops.CharmEvents):
        custom = ops.EventSource(CustomEvent)

    # Relations events are defined dynamically and modify the class attributes.
    # We use a subclass temporarily to prevent these side effects from leaking.
    ops.CharmBase.on = TestCharmEvents()  # type: ignore

    if meta is None:
        meta = ops.CharmMeta()
    model = ops.Model(meta, _ModelBackend('local/0'))
    # We can pass foo_event as event_name because we're not actually testing dispatch.
    framework = ops.Framework(
        SQLiteStorage(':memory:'),
        tmpdir,
        meta,
        model,
        juju_debug_at=_JujuContext.from_dict(os.environ).debug_at,
    )

    def finalizer():
        os.environ.clear()
        os.environ.update(env_backup)
        shutil.rmtree(tmpdir)
        ops.CharmBase.on = ops.CharmEvents()  # type: ignore
        framework.close()

    request.addfinalizer(finalizer)

    return framework


class FakeScript:
    def __init__(
        self,
        request: pytest.FixtureRequest,
        path: typing.Optional[pathlib.Path] = None,
    ):
        if path is None:
            fake_script_path = tempfile.mkdtemp('-fake_script')
            self.path = pathlib.Path(fake_script_path)
            old_path = os.environ['PATH']
            os.environ['PATH'] = os.pathsep.join([fake_script_path, os.environ['PATH']])

            def cleanup():
                shutil.rmtree(self.path)
                os.environ['PATH'] = old_path

            request.addfinalizer(cleanup)
        else:
            self.path = path

    def write(self, name: str, content: str):
        template_args: typing.Dict[str, str] = {
            'name': name,
            'path': self.path.as_posix(),
            'content': content,
        }

        path: pathlib.Path = self.path / name
        with path.open('wt') as f:
            # Before executing the provided script, dump the provided arguments in calls.txt.
            # RS 'record separator' (octal 036 in ASCII), FS 'file separator' (octal 034 in ASCII).
            f.write(
                """#!/bin/sh
{{ printf {name}; printf "\\036%s" "$@"; printf "\\034"; }} >> {path}/calls.txt

# Capture key and data from key#file=/some/path arguments
for word in "$@"; do
  echo "$word" | grep -q "#file=" || continue
  key=$(echo "$word" | cut -d'#' -f1)
  path=$(echo "$word" | cut -d'=' -f2)
  cp "$path" "{path}/$key.secret"
done

{content}""".format_map(template_args)
            )
        path.chmod(0o755)
        # TODO: this hardcodes the path to bash.exe, which works for now but might
        #       need to be set via environ or something like that.
        path.with_suffix('.bat').write_text(
            f'@"C:\\Program Files\\git\\bin\\bash.exe" {path} %*\n'
        )

    def calls(self, clear: bool = False) -> typing.List[typing.List[str]]:
        calls_file: pathlib.Path = self.path / 'calls.txt'
        if not calls_file.exists():
            return []

        # Newline and encoding forced to Linux-y defaults because on
        # windows they're written from git-bash.
        with calls_file.open('r+t', newline='\n', encoding='utf8') as f:
            calls = [line.split('\036') for line in f.read().split('\034')[:-1]]
            if clear:
                f.truncate(0)
        return calls

    def secrets(self) -> typing.Dict[str, str]:
        return {p.stem: p.read_text() for p in self.path.iterdir() if p.suffix == '.secret'}


class FakeScriptTest(unittest.TestCase):
    def test_fake_script_works(self):
        fake_script(self, 'foo', 'echo foo runs')
        fake_script(self, 'bar', 'echo bar runs')
        # subprocess.getoutput goes via the shell, so it needs to be
        # something both sh and CMD understand
        output = subprocess.getoutput('foo a "b c " && bar "d e" f')
        assert output == 'foo runs\nbar runs'
        assert fake_script_calls(self) == [
            ['foo', 'a', 'b c '],
            ['bar', 'd e', 'f'],
        ]

    def test_fake_script_clear(self):
        fake_script(self, 'foo', 'echo foo runs')

        output = subprocess.getoutput('foo a "b c"')
        assert output == 'foo runs'

        assert fake_script_calls(self, clear=True) == [['foo', 'a', 'b c']]

        fake_script(self, 'bar', 'echo bar runs')

        output = subprocess.getoutput('bar "d e" f')
        assert output == 'bar runs'

        assert fake_script_calls(self, clear=True) == [['bar', 'd e', 'f']]

        assert fake_script_calls(self, clear=True) == []
