# Copyright 2020-2021 Canonical Ltd.
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
import subprocess
import sys
import tempfile
import typing
import unittest


def get_python_filepaths(include_tests: bool = True):
    """Helper to retrieve paths of Python files."""
    python_paths: typing.List[str] = []
    roots = ['ops']
    if include_tests:
        roots.append('test')
    for root in roots:
        for dirpath, _, filenames in os.walk(root):
            for filename in filenames:
                if filename.endswith(".py"):
                    python_paths.append(os.path.join(dirpath, filename))
    return python_paths


class ImportersTestCase(unittest.TestCase):

    template = "from ops import {module_name}"

    def test_imports(self):
        mod_names = [
            'charm',
            'framework',
            'main',
            'model',
            'testing',
        ]

        for name in mod_names:
            with self.subTest(name=name):
                self.check(name)

    def check(self, name: str):
        """Helper function to run the test."""
        fd, testfile = tempfile.mkstemp()
        self.addCleanup(os.unlink, testfile)

        with open(fd, 'w', encoding='utf8') as fh:
            fh.write(self.template.format(module_name=name))

        environ = os.environ.copy()
        if 'PYTHONPATH' in environ:
            environ['PYTHONPATH'] = os.getcwd() + os.pathsep + environ['PYTHONPATH']
        else:
            environ['PYTHONPATH'] = os.getcwd()
        proc = subprocess.run([sys.executable, testfile], env=environ)
        self.assertEqual(proc.returncode, 0)
