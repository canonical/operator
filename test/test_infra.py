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
import typing

import pytest

import ops.testing


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


@pytest.mark.skipif(
    not hasattr(ops.testing, 'Context'), reason='requires optional ops[testing] install'
)
def test_ops_testing_doc():
    """Ensure that ops.testing's documentation includes all the expected names."""
    prefix = '.. autoclass:: ops.testing.'
    # We don't document the type aliases.
    expected_names = set(
        name
        for name in ops.testing.__all__
        if name != 'errors'
        and name not in ops.testing._compatibility_names
        and getattr(ops.testing, name).__class__.__module__ != 'typing'
    )
    expected_names.update(
        f'errors.{name}' for name in dir(ops.testing.errors) if not name.startswith('_')
    )
    # ops.testing.UnitID is `int` - we don't document it, but it's hard to fit
    # into the above logic, so we just exclude it here.
    expected_names.discard('UnitID')
    # ops.testing.Container is a documented class when Scenario is installed,
    # but exported for compatibility when not, so we do want to have it present
    # even though the above compatibility_names logic would exclude it.
    expected_names.add('Container')

    found_names: typing.Set[str] = set()
    for test_doc in (
        'docs/reference/ops-testing-harness.rst',
        'docs/reference/ops-testing.rst',
    ):
        with open(test_doc) as testing_doc:
            found_names.update({
                line.split(prefix, 1)[1].strip()
                for line in testing_doc
                if line.strip().startswith(prefix)
            })

    assert expected_names == found_names
