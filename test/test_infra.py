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

import pytest


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


class TestImporters:
    template = "from ops import {module_name}"

    @pytest.mark.parametrize("mod_name", [
        'charm',
        'framework',
        'main',
        'model',
        'testing',
    ])
    def test_import(self, mod_name: str):
        fd, testfile = tempfile.mkstemp()

        with open(fd, 'w', encoding='utf8') as fh:
            fh.write(self.template.format(module_name=mod_name))

        environ = os.environ.copy()
        if 'PYTHONPATH' in environ:
            environ['PYTHONPATH'] = os.getcwd() + os.pathsep + environ['PYTHONPATH']
        else:
            environ['PYTHONPATH'] = os.getcwd()
        proc = subprocess.run([sys.executable, testfile], env=environ)
        assert proc.returncode == 0
        os.unlink(testfile)
