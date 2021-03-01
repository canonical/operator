# Copyright 2019-2020 Canonical Ltd.
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
import subprocess
import shutil
import tempfile
import unittest

from ops.framework import Framework
from ops.model import Model, _ModelBackend
from ops.charm import CharmMeta
from ops.storage import SQLiteStorage


def fake_script(test_case, name, content):
    if not hasattr(test_case, 'fake_script_path'):
        fake_script_path = tempfile.mkdtemp('-fake_script')
        old_path = os.environ["PATH"]
        os.environ['PATH'] = os.pathsep.join([fake_script_path, os.environ["PATH"]])

        def cleanup():
            shutil.rmtree(fake_script_path)
            os.environ['PATH'] = old_path

        test_case.addCleanup(cleanup)
        test_case.fake_script_path = pathlib.Path(fake_script_path)

    template_args = {
        'name': name,
        'path': test_case.fake_script_path.as_posix(),
        'content': content,
    }

    path = test_case.fake_script_path / name
    with path.open('wt') as f:
        # Before executing the provided script, dump the provided arguments in calls.txt.
        # ASCII 1E is RS 'record separator', and 1C is FS 'file separator', which seem appropriate.
        f.write('''#!/bin/sh
{{ printf {name}; printf "\\036%s" "$@"; printf "\\034"; }} >> {path}/calls.txt
{content}'''.format_map(template_args))
    os.chmod(str(path), 0o755)
    # TODO: this hardcodes the path to bash.exe, which works for now but might
    #       need to be set via environ or something like that.
    path.with_suffix(".bat").write_text(
        '@"C:\\Program Files\\git\\bin\\bash.exe" {} %*\n'.format(path))


def fake_script_calls(test_case, clear=False):
    calls_file = test_case.fake_script_path / 'calls.txt'
    if not calls_file.exists():
        return []

    # newline and encoding forced to linuxy defaults because on
    # windows they're written from git-bash
    with calls_file.open('r+t', newline='\n', encoding='utf8') as f:
        calls = [line.split('\x1e') for line in f.read().split('\x1c')[:-1]]
        if clear:
            f.truncate(0)
    return calls


class FakeScriptTest(unittest.TestCase):

    def test_fake_script_works(self):
        fake_script(self, 'foo', 'echo foo runs')
        fake_script(self, 'bar', 'echo bar runs')
        # subprocess.getoutput goes via the shell, so it needs to be
        # something both sh and CMD understand
        output = subprocess.getoutput('foo a "b c " && bar "d e" f')
        self.assertEqual(output, 'foo runs\nbar runs')
        self.assertEqual(fake_script_calls(self), [
            ['foo', 'a', 'b c '],
            ['bar', 'd e', 'f'],
        ])

    def test_fake_script_clear(self):
        fake_script(self, 'foo', 'echo foo runs')

        output = subprocess.getoutput('foo a "b c"')
        self.assertEqual(output, 'foo runs')

        self.assertEqual(fake_script_calls(self, clear=True), [['foo', 'a', 'b c']])

        fake_script(self, 'bar', 'echo bar runs')

        output = subprocess.getoutput('bar "d e" f')
        self.assertEqual(output, 'bar runs')

        self.assertEqual(fake_script_calls(self, clear=True), [['bar', 'd e', 'f']])

        self.assertEqual(fake_script_calls(self, clear=True), [])


class BaseTestCase(unittest.TestCase):

    def create_framework(self, *, model=None, tmpdir=None):
        """Create a Framework object.

        By default operate in-memory; pass a temporary directory via the 'tmpdir'
        parameter if you whish to instantiate several frameworks sharing the
        same dir (e.g. for storing state).
        """
        if tmpdir is None:
            data_fpath = ":memory:"
            charm_dir = 'non-existant'
        else:
            data_fpath = tmpdir / "framework.data"
            charm_dir = tmpdir

        framework = Framework(SQLiteStorage(data_fpath), charm_dir, meta=None, model=model)
        self.addCleanup(framework.close)
        return framework

    def create_model(self):
        """Create a Model object."""
        backend = _ModelBackend(unit_name='myapp/0')
        meta = CharmMeta()
        model = Model(meta, backend)
        return model
