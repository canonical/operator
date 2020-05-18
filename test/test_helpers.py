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
from unittest.mock import patch

from ops.framework import Framework
from ops.model import Model, _ModelBackend
from ops.charm import CharmMeta


def fake_script(test_case, name, content):
    if not hasattr(test_case, 'fake_script_path'):
        fake_script_path = tempfile.mkdtemp('-fake_script')
        os.environ['PATH'] = '{}:{}'.format(fake_script_path, os.environ["PATH"])

        def cleanup():
            shutil.rmtree(fake_script_path)
            os.environ['PATH'] = os.environ['PATH'].replace(fake_script_path + ':', '')

        test_case.addCleanup(cleanup)
        test_case.fake_script_path = pathlib.Path(fake_script_path)

    with (test_case.fake_script_path / name).open('wt') as f:
        # Before executing the provided script, dump the provided arguments in calls.txt.
        f.write('''#!/bin/bash
{ echo -n $(basename $0); printf ";%s" "$@"; echo; } >> $(dirname $0)/calls.txt
''' + content)
    os.chmod(str(test_case.fake_script_path / name), 0o755)


def fake_script_calls(test_case, clear=False):
    try:
        with (test_case.fake_script_path / 'calls.txt').open('r+t') as f:
            calls = [line.split(';') for line in f.read().splitlines()]
            if clear:
                f.truncate(0)
            return calls
    except FileNotFoundError:
        return []


class FakeScriptTest(unittest.TestCase):

    def test_fake_script_works(self):
        fake_script(self, 'foo', 'echo foo runs')
        fake_script(self, 'bar', 'echo bar runs')
        output = subprocess.getoutput('foo a "b c "; bar "d e" f')
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

        framework = Framework(data_fpath, charm_dir, meta=None, model=model)
        self.addCleanup(framework.close)
        return framework

    def create_model(self):
        """Create a Model object."""
        unit_name = 'myapp/0'
        patcher = patch.dict(os.environ, {'JUJU_UNIT_NAME': unit_name})
        patcher.start()
        self.addCleanup(patcher.stop)

        backend = _ModelBackend()
        meta = CharmMeta()
        model = Model('myapp/0', meta, backend)
        return model
