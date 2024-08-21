# Copyright 2020 Canonical Ltd.
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
import sys

import pytest


@pytest.mark.parametrize(
    'mod_name',
    [
        'charm',
        'framework',
        'main',
        'model',
        'testing',
    ],
)
def test_import(mod_name: str, tmp_path: pathlib.Path):
    template = 'from ops import {module_name}'

    testfile = tmp_path / 'foo.py'
    with open(testfile, 'w', encoding='utf8') as fh:
        fh.write(template.format(module_name=mod_name))

    environ = os.environ.copy()
    if 'PYTHONPATH' in environ:
        environ['PYTHONPATH'] = os.getcwd() + os.pathsep + environ['PYTHONPATH']
    else:
        environ['PYTHONPATH'] = os.getcwd()

    proc = subprocess.run([sys.executable, testfile], env=environ)
    assert proc.returncode == 0
