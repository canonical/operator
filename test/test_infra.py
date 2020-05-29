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

import io
import itertools
import os
import re
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import autopep8
from flake8.api.legacy import get_style_guide

import ops


def get_python_filepaths():
    """Helper to retrieve paths of Python files."""
    python_paths = ['setup.py']
    for root in ['ops', 'test']:
        for dirpath, dirnames, filenames in os.walk(root):
            for filename in filenames:
                if filename.endswith(".py"):
                    python_paths.append(os.path.join(dirpath, filename))
    return python_paths


class InfrastructureTests(unittest.TestCase):

    def test_pep8(self):
        # verify all files are nicely styled
        python_filepaths = get_python_filepaths()
        style_guide = get_style_guide()
        fake_stdout = io.StringIO()
        with patch('sys.stdout', fake_stdout):
            report = style_guide.check_files(python_filepaths)

        # if flake8 didnt' report anything, we're done
        if report.total_errors == 0:
            return

        # grab on which files we have issues
        flake8_issues = fake_stdout.getvalue().split('\n')
        broken_filepaths = {item.split(':')[0] for item in flake8_issues if item}

        # give hints to the developer on how files' style could be improved
        options = autopep8.parse_args([''])
        options.aggressive = 1
        options.diff = True
        options.max_line_length = 99

        issues = []
        for filepath in broken_filepaths:
            diff = autopep8.fix_file(filepath, options=options)
            if diff:
                issues.append(diff)

        report = ["Please fix files as suggested by autopep8:"] + issues
        report += ["\n-- Original flake8 reports:"] + flake8_issues
        self.fail("\n".join(report))

    def test_quote_backslashes(self):
        # ensure we're not using unneeded backslash to escape strings
        issues = []
        for filepath in get_python_filepaths():
            with open(filepath, "rt", encoding="utf8") as fh:
                for idx, line in enumerate(fh, 1):
                    if (r'\"' in line or r"\'" in line) and "NOQA" not in line:
                        issues.append((filepath, idx, line.rstrip()))
        if issues:
            msgs = ["{}:{:d}:{}".format(*issue) for issue in issues]
            self.fail("Spurious backslashes found, please fix these quotings:\n" + "\n".join(msgs))

    def test_ensure_copyright(self):
        # all non-empty Python files must have a proper copyright somewhere in the first 5 lines
        issues = []
        regex = re.compile(r"# Copyright \d\d\d\d(-\d\d\d\d)? Canonical Ltd.\n")
        for filepath in get_python_filepaths():
            if os.stat(filepath).st_size == 0:
                continue

            with open(filepath, "rt", encoding="utf8") as fh:
                for line in itertools.islice(fh, 5):
                    if regex.match(line):
                        break
                else:
                    issues.append(filepath)
        if issues:
            self.fail("Please add copyright headers to the following files:\n" + "\n".join(issues))

    def _run_setup(self, *args):
        proc = subprocess.run(
            (sys.executable, 'setup.py') + args,
            stdout=subprocess.PIPE,
            check=True)
        return proc.stdout.strip().decode("utf8")

    def test_setup_version(self):
        setup_version = self._run_setup('--version')

        self.assertEqual(setup_version, ops.__version__)

    def test_setup_description(self):
        with open("README.md", "rt", encoding="utf8") as fh:
            disk_readme = fh.read().strip()

        setup_readme = self._run_setup('--long-description')

        self.assertEqual(setup_readme, disk_readme)

    def test_check(self):
        self._run_setup('check', '--strict')


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

    def check(self, name):
        """Helper function to run the test."""
        _, testfile = tempfile.mkstemp()
        self.addCleanup(os.unlink, testfile)

        with open(testfile, 'wt', encoding='utf8') as fh:
            fh.write(self.template.format(module_name=name))

        proc = subprocess.run([sys.executable, testfile], env={'PYTHONPATH': os.getcwd()})
        self.assertEqual(proc.returncode, 0)
