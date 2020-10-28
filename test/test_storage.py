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
import os
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

    def create_framework(self) -> framework.Framework:
        """Create a Framework that we can use to test the backend storage.
        """
        return framework.Framework(self.create_storage(), None, None, None)

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

    def test_emit_event(self):
        f = self.create_framework()

        class Evt(framework.EventBase):
            def __init__(self, handle, content):
                super().__init__(handle)
                self.content = content

            def snapshot(self):
                return self.content

            def restore(self, content):
                self.content = content

        class Events(framework.ObjectEvents):
            event = framework.EventSource(Evt)

        class Sample(framework.Object):

            on = Events()

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.observed_content = None
                self.framework.observe(self.on.event, self._on_event)

            def _on_event(self, event: Evt):
                self.observed_content = event.content

        s = Sample(f, 'key')
        f.register_type(Sample, None, Sample.handle_kind)
        s.on.event.emit('foo')
        self.assertEqual('foo', s.observed_content)
        s.on.event.emit(1)
        self.assertEqual(1, s.observed_content)
        s.on.event.emit(None)
        self.assertEqual(None, s.observed_content)

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

    def test_save_notice(self):
        store = self.create_storage()
        store.save_notice('event', 'observer', 'method')
        self.assertEqual(
            list(store.notices('event')),
            [('event', 'observer', 'method')])

    def test_all_notices(self):
        notices = [('e1', 'o1', 'm1'), ('e1', 'o2', 'm2'), ('e2', 'o3', 'm3')]
        store = self.create_storage()
        for notice in notices:
            store.save_notice(*notice)

        # passing in the arg, you get the ones that match
        self.assertEqual(list(store.notices('e1')), notices[:2])
        self.assertEqual(list(store.notices('e2')), notices[2:])
        # the match is exact
        self.assertEqual(list(store.notices('e%')), [])
        self.assertEqual(list(store.notices('e*')), [])
        self.assertEqual(list(store.notices('e.')), [])
        self.assertEqual(list(store.notices('e')), [])
        # no arg, or non-arg, means all
        self.assertEqual(list(store.notices()), notices)
        self.assertEqual(list(store.notices(None)), notices)
        self.assertEqual(list(store.notices('')), notices)

    def test_load_notices(self):
        store = self.create_storage()
        self.assertEqual(list(store.notices('path')), [])

    def test_save_one_load_another_notice(self):
        store = self.create_storage()
        store.save_notice('event', 'observer', 'method')
        self.assertEqual(list(store.notices('other')), [])

    def test_save_load_drop_load_notices(self):
        store = self.create_storage()
        store.save_notice('event', 'observer', 'method')
        store.save_notice('event', 'observer', 'method2')
        self.assertEqual(
            list(store.notices('event')),
            [('event', 'observer', 'method'),
             ('event', 'observer', 'method2'),
             ])


class TestSQLiteStorage(StoragePermutations, BaseTestCase):

    def create_storage(self):
        return storage.SQLiteStorage(':memory:')


def setup_juju_backend(test_case, state_file):
    """Create fake scripts for pretending to be state-set and state-get"""
    template_args = {
        'executable': str(pathlib.Path(sys.executable).as_posix()),
        'pthpth': repr(os.path.dirname(pathlib.__file__))[1:-1],
        'state_file': str(state_file.as_posix()),
    }

    fake_script(test_case, 'state-set', dedent('''\
        {executable} -c '
        import sys
        if "{pthpth}" not in sys.path:
            sys.path.append("{pthpth}")
        import sys, yaml, pathlib, pickle
        assert sys.argv[1:] == ["--file", "-"]
        request = yaml.load(sys.stdin, Loader=getattr(yaml, "CSafeLoader", yaml.SafeLoader))
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
        {executable} -Sc '
        import sys
        if "{pthpth}" not in sys.path:
            sys.path.append("{pthpth}")
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
        {executable} -Sc '
        import sys
        if "{pthpth}" not in sys.path:
            sys.path.append("{pthpth}")
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

    def create_storage(self):
        fd, fn = tempfile.mkstemp(prefix='tmp-ops-test-state-')
        os.close(fd)
        state_file = pathlib.Path(fn)
        self.addCleanup(state_file.unlink)
        setup_juju_backend(self, state_file)
        return storage.JujuStorage()


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

    def test_handles_tuples(self):
        raw = yaml.dump((1, 'tuple'), Dumper=storage._SimpleDumper)
        parsed = yaml.load(raw, Loader=storage._SimpleLoader)
        self.assertEqual(parsed, (1, 'tuple'))

    def assertRefused(self, obj):
        # We shouldn't allow them to be written
        with self.assertRaises(yaml.representer.RepresenterError):
            yaml.dump(obj, Dumper=storage._SimpleDumper)
        # If they did somehow end up written, we shouldn't be able to load them
        raw = yaml.dump(obj, Dumper=yaml.Dumper)
        with self.assertRaises(yaml.constructor.ConstructorError):
            yaml.load(raw, Loader=storage._SimpleLoader)

    def test_forbids_some_types(self):
        self.assertRefused(1 + 2j)
        self.assertRefused({'foo': 1 + 2j})
        self.assertRefused(frozenset(['foo', 'bar']))
        self.assertRefused(bytearray(b'foo'))
        self.assertRefused(object())

        class Foo:
            pass
        f = Foo()
        self.assertRefused(f)


class TestJujuStateBackend(BaseTestCase):

    def test_is_not_available(self):
        self.assertFalse(storage.juju_backend_available())

    def test_is_available(self):
        fake_script(self, 'state-get', 'echo ""')
        self.assertTrue(storage.juju_backend_available())
        self.assertEqual(fake_script_calls(self, clear=True), [])

    def test_set_encodes_args(self):
        t = tempfile.NamedTemporaryFile()
        fake_script(self, 'state-set', dedent("""
            cat >> {}
            """).format(pathlib.Path(t.name).as_posix()))
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
            """).format(pathlib.Path(t.name).as_posix()))
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
        outer = yaml.safe_load(content)
        key = 'Class[foo]/_stored'
        self.assertEqual(list(outer.keys()), [key])
        inner = yaml.load(outer[key], Loader=storage._SimpleLoader)
        self.assertEqual(complex_val, inner)
        if sys.version_info >= (3, 6):
            # In Python 3.5 dicts are not ordered by default, and PyYAML only
            # iterates the dict. So we read and assert the content is valid,
            # but we don't assert the serialized form.
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
