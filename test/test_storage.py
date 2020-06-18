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
import io
import pathlib
import sys
import tempfile
from textwrap import dedent

import yaml

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

    @abc.abstractmethod
    def create_storage(self) -> storage.SQLiteStorage:
        """Create a Storage backend that we can interact with"""
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
        data = {
            'str': 'string',
            'bytes': b'bytes',
            'int': 1,
            'float': 3.0,
            'dict': {'a': 'b'},
            'set': {'a', 'b'},
            'list': [1, 2],
        }
        s = Sample(f, 'test', data)
        handle = s.handle
        f.save_snapshot(s)
        del s
        gc.collect()
        res = f.load_snapshot(handle)
        self.assertEqual(data, res.content)

    def test_save_and_overwrite_snapshot(self):
        store = self.create_storage()
        store.save_snapshot('foo', {1: 2})
        self.assertEqual({1: 2}, store.load_snapshot('foo'))
        store.save_snapshot('foo', {'three': 4})
        self.assertEqual({'three': 4}, store.load_snapshot('foo'))

    def test_drop_snapshot(self):
        store = self.create_storage()
        store.save_snapshot('foo', {1: 2})
        self.assertEqual({1: 2}, store.load_snapshot('foo'))
        store.drop_snapshot('foo')
        with self.assertRaises(storage.NoSnapshotError):
            store.load_snapshot('foo')

    def test_save_snapshot_empty_string(self):
        store = self.create_storage()
        with self.assertRaises(storage.NoSnapshotError):
            store.load_snapshot('foo')
        store.save_snapshot('foo', '')
        self.assertEqual('', store.load_snapshot('foo'))
        store.drop_snapshot('foo')
        with self.assertRaises(storage.NoSnapshotError):
            store.load_snapshot('foo')

    def test_save_snapshot_none(self):
        store = self.create_storage()
        with self.assertRaises(storage.NoSnapshotError):
            store.load_snapshot('bar')
        store.save_snapshot('bar', None)
        self.assertEqual(None, store.load_snapshot('bar'))
        store.drop_snapshot('bar')
        with self.assertRaises(storage.NoSnapshotError):
            store.load_snapshot('bar')

    def test_save_snapshot_zero(self):
        store = self.create_storage()
        with self.assertRaises(storage.NoSnapshotError):
            store.load_snapshot('zero')
        store.save_snapshot('zero', 0)
        self.assertEqual(0, store.load_snapshot('zero'))
        store.drop_snapshot('zero')
        with self.assertRaises(storage.NoSnapshotError):
            store.load_snapshot('zero')


class TestSQLiteStorage(StoragePermutations, BaseTestCase):

    def create_framework(self):
        return framework.Framework(':memory:', None, None, None)

    def create_storage(self):
        return storage.SQLiteStorage(':memory:')


def setup_juju_backend(test_case, state_file):
    """Create fake scripts for pretending to be state-set and state-get"""
    template_args = {
        'executable': sys.executable,
        'state_file': str(state_file),
    }
    fake_script(test_case, 'state-set', dedent('''\
        {executable} -c '
        import sys, yaml, pathlib, pickle
        assert sys.argv[1:] == ["--file", "-"]
        request = yaml.safe_load(sys.stdin)
        state_file = pathlib.Path("{state_file}")
        if state_file.exists() and state_file.stat().st_size > 0:
            with state_file.open("rb") as f:
                state = pickle.load(f)
        else:
            state = {{}}
        for k, v in request.items():
            state[k] = v
        with state_file.open("wb") as f:
            pickle.dump(state, f)
        ' "$@"
        ''').format(**template_args))

    fake_script(test_case, 'state-get', dedent('''\
        {executable} -c '
        import sys, pathlib, pickle
        assert len(sys.argv) == 2
        state_file = pathlib.Path("{state_file}")
        if state_file.exists() and state_file.stat().st_size > 0:
            with state_file.open("rb") as f:
                state = pickle.load(f)
        else:
            state = {{}}
        result = state.get(sys.argv[1], "\\n")
        sys.stdout.write(result)
        ' "$@"
        ''').format(**template_args))

    fake_script(test_case, 'state-delete', dedent('''\
        {executable} -c '
        import sys, pathlib, pickle
        assert len(sys.argv) == 2
        state_file = pathlib.Path("{state_file}")
        if state_file.exists() and state_file.stat().st_size > 0:
            with state_file.open("rb") as f:
                state = pickle.load(f)
        else:
            state = {{}}
        state.pop(sys.argv[1], None)
        with state_file.open("wb") as f:
            pickle.dump(state, f)
        ' "$@"
        ''').format(**template_args))


class TestJujuStorage(StoragePermutations, BaseTestCase):

    def create_framework(self):
        storage = self.create_storage()
        # TODO: jam 2020-06-17 Framework should take a Storage not a path
        f = framework.Framework(':memory:', None, None, None)
        f._storage = storage
        return f

    def create_storage(self):
        state_file = pathlib.Path(tempfile.mkstemp(prefix='tmp-ops-test-state-')[1])
        self.addCleanup(state_file.unlink)
        setup_juju_backend(self, state_file)
        return storage.JujuStorage(storage._JujuStorageBackend())


class TestSimpleLoader(BaseTestCase):

    def test_is_c_loader(self):
        loader = storage._SimpleLoader(io.StringIO(''))
        if getattr(yaml, 'CSafeLoader', None) is not None:
            self.assertIsInstance(loader, yaml.CSafeLoader)
        else:
            self.assertIsInstance(loader, yaml.SafeLoader)

    def test_is_c_dumper(self):
        dumper = storage._SimpleDumper(io.StringIO(''))
        if getattr(yaml, 'CSafeDumper', None) is not None:
            self.assertIsInstance(dumper, yaml.CSafeDumper)
        else:
            self.assertIsInstance(dumper, yaml.SafeDumper)


class TestJujuStateBackend(BaseTestCase):

    def test_is_not_available(self):
        self.assertFalse(storage._JujuStorageBackend.is_available())

    def test_is_available(self):
        fake_script(self, 'state-get', 'echo ""')
        self.assertTrue(storage._JujuStorageBackend.is_available())
        self.assertEqual(fake_script_calls(self, clear=True), [])

    def test_set_encodes_args(self):
        t = tempfile.NamedTemporaryFile()
        fake_script(self, 'state-set', dedent("""
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
            "key": |
              {foo: 2}
            """))

    def test_get(self):
        fake_script(self, 'state-get', dedent("""
            echo 'foo: "bar"'
            """))
        backend = storage._JujuStorageBackend()
        value = backend.get('key')
        self.assertEqual(value, {'foo': 'bar'})
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['state-get', 'key'],
        ])

    def test_set_and_get_complex_value(self):
        t = tempfile.NamedTemporaryFile()
        fake_script(self, 'state-set', dedent("""
            cat >> {}
            """).format(t.name))
        backend = storage._JujuStorageBackend()
        complex_val = {
            'foo': 2,
            3: [1, 2, '3'],
            'four': {2, 3},
            'five': {'a': 2, 'b': 3.0},
            'six': ('a', 'b'),
            'seven': b'1234',
        }
        backend.set('Class[foo]/_stored', complex_val)
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['state-set', '--file', '-'],
        ])
        t.seek(0)
        content = t.read()
        self.assertEqual(content.decode('utf-8'), dedent("""\
            "Class[foo]/_stored": |
              foo: 2
              3: [1, 2, '3']
              four: !!set {2: null, 3: null}
              five: {a: 2, b: 3.0}
              six: !!python/tuple [a, b]
              seven: !!binary |
                MTIzNA==
            """))
        # Note that the content is yaml in a string, embedded inside YAML to declare the Key:
        # Value of where to store the entry.
        fake_script(self, 'state-get', dedent("""
            echo "foo: 2
            3: [1, 2, '3']
            four: !!set {2: null, 3: null}
            five: {a: 2, b: 3.0}
            six: !!python/tuple [a, b]
            seven: !!binary |
              MTIzNA==
            "
        """))
        out = backend.get('Class[foo]/_stored')
        self.assertEqual(out, complex_val)

    # TODO: Add tests for things we don't want to support. eg, YAML that has custom types should
    #  be properly forbidden.
    # TODO: Tests for state-set/get/delete and how they handle if you ask to delete something
    #  that doesn't exist, or get something that doesn't exist, etc.
