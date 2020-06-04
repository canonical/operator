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

import abc
import gc
import sys
import tempfile
from textwrap import dedent

from ops import (
    framework,
    storage,
)
from test.test_helpers import (
    BaseTestCase,
    fake_script,
    fake_script_calls,
)


class StoragePermutations(abc.ABC):

    @abc.abstractmethod
    def create_framework(self) -> framework.Framework:
        """Create a Framework that we can use to test the backend storage.
        """
        return NotImplemented

    def test_save_and_load_snapshot(self):
        f = self.create_framework()

        class Sample(framework.Object):

            def __init__(self, parent, key, content):
                super().__init__(parent, key)
                self.content = content

            def snapshot(self):
                return {'content': self.content}

            def restore(self, snapshot):
                self.__dict__.update(snapshot)

        f.register_type(Sample, None, Sample.handle_kind)
        content = {'test': 1}
        s = Sample(f, 'test', content)
        handle = s.handle
        f.save_snapshot(s)
        del s
        gc.collect()
        res = f.load_snapshot(handle)
        self.assertEqual(content, res.content)


class TestSQLiteStorage(StoragePermutations, BaseTestCase):

    def create_framework(self):
        return framework.Framework(':memory:', None, None, None)


class _MemoryStorageBackend:

    def __init__(self):
        self._values = {}
        self._calls = []

    def set(self, key, value):
        self._calls.append(('set', key, value))
        self._values[key] = value

    def get(self, key):
        self._calls.append(('get', key))
        return self._values[key]

    def delete(self, key):
        self._calls.append(('delete', key))
        self._calls.pop(key, None)


class TestJujuStorage(StoragePermutations, BaseTestCase):

    def create_framework(self):
        mem_backend = _MemoryStorageBackend()
        f = framework.Framework(':memory:', None, None, None)
        f._storage = storage.JujuStorage(mem_backend)
        return f


python_state_set = '''#!{executable}
import sys
import yaml

assert sys.argv[1:] == ['--file', '-']

with open({filename!r}, 'r+b') as saved:
    content = yaml.load(saved)
    if content is None:
        content = {{}}
    more = yaml.load(sys.stdin.buffer.read())
    content.update(more)
    out.seek(0)
    out.truncate()
    out.write(yaml.dump(existing)
'''

python_state_get = '''#!{executable}
import sys
import yaml

with open({filename!r}, 'rb') as saved:
    content = yaml.load(saved)
    if len(sys.argv) == 1:
        yaml.dump(content, sys.stdout)
    else:
        sys.stdout.write('{{}}'.format(content[sys.argv[1]]))
'''

python_state_delete = '''#!{executable}
import sys
import yaml

assert len(sys.argv) == 2
with open({filename!r}, 'r+b') as saved:
    content = yaml.load(saved)
    if len(sys.argv) == 1:
        yaml.dump(content, sys.stdout)
    else:
        sys.stdout.write('{{}}'.format(content[sys.argv[1]]))
'''


class TestJujuStateBackend(BaseTestCase):

    def setUpPythonStateScripts(self):
        t = tempfile.NamedTemporaryFile()
        template_args = {'executable': sys.executable, 'filename': t.name}
        fake_script(self, 'state-get', python_state_get.format(**template_args))
        fake_script(self, 'state-set', python_state_set.format(**template_args))
        fake_script(self, 'state-delete', python_state_delete.format(**template_args))

    def test_is_not_available(self):
        self.assertFalse(storage._JujuStorageBackend.is_available())

    def test_is_available(self):
        fake_script(self, 'state-get', 'echo ""')
        self.assertTrue(storage._JujuStorageBackend.is_available())
        self.assertEqual(fake_script_calls(self, clear=True), [])

    def test_set_encodes_args(self):
        t = tempfile.NamedTemporaryFile()
        fake_script(self, 'state-set', dedent("""
            #!/bin/sh
            cat >> {}
            """).format(t.name))
        backend = storage._JujuStorageBackend()
        backend.set('key', {'foo': 2})
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['state-set', '--file', '-'],
        ])
        t.seek(0)
        content = t.read()
        self.assertEqual(content.decode('utf-8'), dedent("""\
            {key: '{foo: 2}

                '}
            """))

    def test_get(self):
        fake_script(self, 'state-get', dedent("""
            #!/bin/sh
            echo 'foo: "bar"'
            """))
        backend = storage._JujuStorageBackend()
        value = backend.get('key')
        self.assertEqual(value, {'foo': 'bar'})
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['state-get', 'key'],
        ])

    def test_fake_backend(self):
        self.setUpPythonStateScripts()
        backend = storage._JujuStorageBackend()
        values = {'k': 'v', 2: 10, ('a', 'b'): {1, 2, 3}}
        backend.set('foo', values)
        res = backend.get('foo')
        self.assertEqual(res, values)
