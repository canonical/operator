# Copyright 2023 Canonical Ltd.
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

import gc
import shutil
import tempfile
from pathlib import Path
from test.test_helpers import BaseTestCase

from ops.framework import (
    BoundStoredState,
    Framework,
    Object,
    StoredDict,
    StoredList,
    StoredSet,
    StoredState,
    StoredStateData,
)
from ops.storage import SQLiteStorage


class TestStoredState(BaseTestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

    def test_stored_dict_repr(self):
        self.assertEqual(repr(StoredDict(None, {})), "ops.framework.StoredDict()")
        self.assertEqual(repr(StoredDict(None, {"a": 1})), "ops.framework.StoredDict({'a': 1})")

    def test_stored_list_repr(self):
        self.assertEqual(repr(StoredList(None, [])), "ops.framework.StoredList()")
        self.assertEqual(repr(StoredList(None, [1, 2, 3])), 'ops.framework.StoredList([1, 2, 3])')

    def test_stored_set_repr(self):
        self.assertEqual(repr(StoredSet(None, set())), 'ops.framework.StoredSet()')
        self.assertEqual(repr(StoredSet(None, {1})), 'ops.framework.StoredSet({1})')

    def test_basic_state_storage(self):
        class SomeObject(Object):
            _stored = StoredState()

        self._stored_state_tests(SomeObject)

    def test_straight_subclass(self):
        class SomeObject(Object):
            _stored = StoredState()

        class Sub(SomeObject):
            pass

        self._stored_state_tests(Sub)

    def test_straight_sub_subclass(self):
        class SomeObject(Object):
            _stored = StoredState()

        class Sub(SomeObject):
            pass

        class SubSub(Sub):
            pass

        self._stored_state_tests(SubSub)

    def test_two_subclasses(self):
        class SomeObject(Object):
            _stored = StoredState()

        class SubA(SomeObject):
            pass

        class SubB(SomeObject):
            pass

        self._stored_state_tests(SubA)
        self._stored_state_tests(SubB)

    def test_the_crazy_thing(self):
        class NoState(Object):
            pass

        class StatedObject(NoState):
            _stored = StoredState()

        class Sibling(NoState):
            pass

        class FinalChild(StatedObject, Sibling):
            pass

        self._stored_state_tests(FinalChild)

    def _stored_state_tests(self, cls):
        framework = self.create_framework(tmpdir=self.tmpdir)
        obj = cls(framework, "1")

        try:
            obj._stored.foo
        except AttributeError as e:
            self.assertEqual(str(e), "attribute 'foo' is not stored")
        else:
            self.fail("AttributeError not raised")

        try:
            obj._stored.on = "nonono"
        except AttributeError as e:
            self.assertEqual(str(e), "attribute 'on' is reserved and cannot be set")
        else:
            self.fail("AttributeError not raised")

        obj._stored.foo = 41
        obj._stored.foo = 42
        obj._stored.bar = "s"
        obj._stored.baz = 4.2
        obj._stored.bing = True

        self.assertEqual(obj._stored.foo, 42)

        framework.commit()

        # This won't be committed, and should not be seen.
        obj._stored.foo = 43

        framework.close()

        # Since this has the same absolute object handle, it will get its state back.
        framework_copy = self.create_framework(tmpdir=self.tmpdir)
        obj_copy = cls(framework_copy, "1")
        self.assertEqual(obj_copy._stored.foo, 42)
        self.assertEqual(obj_copy._stored.bar, "s")
        self.assertEqual(obj_copy._stored.baz, 4.2)
        self.assertEqual(obj_copy._stored.bing, True)

        framework_copy.close()

    def test_two_subclasses_no_conflicts(self):
        class Base(Object):
            _stored = StoredState()

        class SubA(Base):
            pass

        class SubB(Base):
            pass

        framework = self.create_framework(tmpdir=self.tmpdir)
        a = SubA(framework, None)
        b = SubB(framework, None)
        z = Base(framework, None)

        a._stored.foo = 42
        b._stored.foo = "hello"
        z._stored.foo = {1}

        framework.commit()
        framework.close()

        framework2 = self.create_framework(tmpdir=self.tmpdir)
        a2 = SubA(framework2, None)
        b2 = SubB(framework2, None)
        z2 = Base(framework2, None)

        self.assertEqual(a2._stored.foo, 42)
        self.assertEqual(b2._stored.foo, "hello")
        self.assertEqual(z2._stored.foo, {1})

    def test_two_names_one_state(self):
        class Mine(Object):
            _stored = StoredState()
            _stored2 = _stored

        framework = self.create_framework()
        obj = Mine(framework, None)

        with self.assertRaises(RuntimeError):
            obj._stored.foo = 42

        with self.assertRaises(RuntimeError):
            obj._stored2.foo = 42

        framework.close()

        # make sure we're not changing the object on failure
        self.assertNotIn("_stored", obj.__dict__)
        self.assertNotIn("_stored2", obj.__dict__)

    def test_same_name_two_classes(self):
        class Base(Object):
            pass

        class A(Base):
            _stored = StoredState()

        class B(Base):
            _stored = A._stored

        framework = self.create_framework()
        a = A(framework, None)
        b = B(framework, None)

        # NOTE it's the second one that actually triggers the
        # exception, but that's an implementation detail
        a._stored.foo = 42

        with self.assertRaises(RuntimeError):
            b._stored.foo = "xyzzy"

        framework.close()

        # make sure we're not changing the object on failure
        self.assertNotIn("_stored", b.__dict__)

    def test_mutable_types_invalid(self):
        framework = self.create_framework()

        class SomeObject(Object):
            _stored = StoredState()

        obj = SomeObject(framework, '1')
        try:
            class CustomObject:
                pass
            obj._stored.foo = CustomObject()
        except AttributeError as e:
            self.assertEqual(
                str(e),
                "attribute 'foo' cannot be a CustomObject: must be int/float/dict/list/etc")
        else:
            self.fail('AttributeError not raised')

        framework.commit()

    def test_mutable_types(self):
        # Test and validation functions in a list of 2-tuples.
        # Assignment and keywords like del are not supported in lambdas
        #  so functions are used instead.
        test_operations = [(
            lambda: {},         # Operand A.
            None,               # Operand B.
            {},                 # Expected result.
            lambda a, b: None,  # Operation to perform.
            lambda res, expected_res: self.assertEqual(res, expected_res)  # Validation to perform.
        ), (
            lambda: {},
            {'a': {}},
            {'a': {}},
            lambda a, b: a.update(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: {'a': {}},
            {'b': 'c'},
            {'a': {'b': 'c'}},
            lambda a, b: a['a'].update(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: {'a': {'b': 'c'}},
            {'d': 'e'},
            {'a': {'b': 'c', 'd': 'e'}},
            lambda a, b: a['a'].update(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: {'a': {'b': 'c', 'd': 'e'}},
            'd',
            {'a': {'b': 'c'}},
            lambda a, b: a['a'].pop(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: {'s': set()},
            'a',
            {'s': {'a'}},
            lambda a, b: a['s'].add(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: {'s': {'a'}},
            'a',
            {'s': set()},
            lambda a, b: a['s'].discard(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: [],
            None,
            [],
            lambda a, b: None,
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: [],
            'a',
            ['a'],
            lambda a, b: a.append(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: ['a'],
            ['c'],
            ['a', ['c']],
            lambda a, b: a.append(b),
            lambda res, expected_res: (
                self.assertEqual(res, expected_res),
                self.assertIsInstance(res[1], StoredList),
            )
        ), (
            lambda: ['a', ['c']],
            'b',
            ['b', 'a', ['c']],
            lambda a, b: a.insert(0, b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: ['b', 'a', ['c']],
            ['d'],
            ['b', ['d'], 'a', ['c']],
            lambda a, b: a.insert(1, b),
            lambda res, expected_res: (
                self.assertEqual(res, expected_res),
                self.assertIsInstance(res[1], StoredList)
            ),
        ), (
            lambda: ['b', 'a', ['c']],
            ['d'],
            ['b', ['d'], ['c']],
            # a[1] = b
            lambda a, b: a.__setitem__(1, b),
            lambda res, expected_res: (
                self.assertEqual(res, expected_res),
                self.assertIsInstance(res[1], StoredList)
            ),
        ), (
            lambda: ['b', ['d'], 'a', ['c']],
            0,
            [['d'], 'a', ['c']],
            lambda a, b: a.pop(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: [['d'], 'a', ['c']],
            ['d'],
            ['a', ['c']],
            lambda a, b: a.remove(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: ['a', ['c']],
            'd',
            ['a', ['c', 'd']],
            lambda a, b: a[1].append(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: ['a', ['c', 'd']],
            1,
            ['a', ['c']],
            lambda a, b: a[1].pop(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: ['a', ['c']],
            'd',
            ['a', ['c', 'd']],
            lambda a, b: a[1].insert(1, b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: ['a', ['c', 'd']],
            'd',
            ['a', ['c']],
            lambda a, b: a[1].remove(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: set(),
            None,
            set(),
            lambda a, b: None,
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: set(),
            'a',
            {'a'},
            lambda a, b: a.add(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: {'a'},
            'a',
            set(),
            lambda a, b: a.discard(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: set(),
            {'a'},
            set(),
            # Nested sets are not allowed as sets themselves are not hashable.
            lambda a, b: self.assertRaises(TypeError, a.add, b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        )]

        class SomeObject(Object):
            _stored = StoredState()

        class WrappedFramework(Framework):
            def __init__(self, store, charm_dir, meta, model, event_name):
                super().__init__(store, charm_dir, meta, model, event_name)
                self.snapshots = []

            def save_snapshot(self, value):
                if value.handle.path == 'SomeObject[1]/StoredStateData[_stored]':
                    self.snapshots.append((type(value), value.snapshot()))
                return super().save_snapshot(value)

        # Validate correctness of modification operations.
        for get_a, b, expected_res, op, validate_op in test_operations:
            storage = SQLiteStorage(self.tmpdir / "framework.data")
            framework = WrappedFramework(storage, self.tmpdir, None, None, "foo")
            obj = SomeObject(framework, '1')

            obj._stored.a = get_a()
            self.assertTrue(isinstance(obj._stored, BoundStoredState))

            op(obj._stored.a, b)
            validate_op(obj._stored.a, expected_res)

            obj._stored.a = get_a()
            framework.commit()
            # We should see an update for initializing a
            self.assertEqual(framework.snapshots, [
                (StoredStateData, {'a': get_a()}),
            ])
            del obj
            gc.collect()
            obj_copy1 = SomeObject(framework, '1')
            self.assertEqual(obj_copy1._stored.a, get_a())

            op(obj_copy1._stored.a, b)
            validate_op(obj_copy1._stored.a, expected_res)
            framework.commit()
            framework.close()

            storage_copy = SQLiteStorage(self.tmpdir / "framework.data")
            framework_copy = WrappedFramework(storage_copy, self.tmpdir, None, None, "foo")

            obj_copy2 = SomeObject(framework_copy, '1')

            validate_op(obj_copy2._stored.a, expected_res)

            # Commit saves the pre-commit and commit events, and the framework
            # event counter, but shouldn't update the stored state of my object
            framework.snapshots.clear()
            framework_copy.commit()
            self.assertEqual(framework_copy.snapshots, [])
            framework_copy.close()

    def test_comparison_operations(self):
        test_operations = [(
            {"1"},               # Operand A.
            {"1", "2"},          # Operand B.
            lambda a, b: a < b,  # Operation to test.
            True,                # Result of op(A, B).
            False,               # Result of op(B, A).
        ), (
            {"1"},
            {"1", "2"},
            lambda a, b: a > b,
            False,
            True
        ), (
            # Empty set comparison.
            set(),
            set(),
            lambda a, b: a == b,
            True,
            True
        ), (
            {"a", "c"},
            {"c", "a"},
            lambda a, b: a == b,
            True,
            True
        ), (
            dict(),
            dict(),
            lambda a, b: a == b,
            True,
            True
        ), (
            {"1": "2"},
            {"1": "2"},
            lambda a, b: a == b,
            True,
            True
        ), (
            {"1": "2"},
            {"1": "3"},
            lambda a, b: a == b,
            False,
            False
        ), (
            [],
            [],
            lambda a, b: a == b,
            True,
            True
        ), (
            [1, 2],
            [1, 2],
            lambda a, b: a == b,
            True,
            True
        ), (
            [1, 2, 5, 6],
            [1, 2, 5, 8, 10],
            lambda a, b: a <= b,
            True,
            False
        ), (
            [1, 2, 5, 6],
            [1, 2, 5, 8, 10],
            lambda a, b: a < b,
            True,
            False
        ), (
            [1, 2, 5, 8],
            [1, 2, 5, 6, 10],
            lambda a, b: a > b,
            True,
            False
        ), (
            [1, 2, 5, 8],
            [1, 2, 5, 6, 10],
            lambda a, b: a >= b,
            True,
            False
        )]

        class SomeObject(Object):
            _stored = StoredState()

        framework = self.create_framework()

        for i, (a, b, op, op_ab, op_ba) in enumerate(test_operations):
            obj = SomeObject(framework, str(i))
            obj._stored.a = a
            self.assertEqual(op(obj._stored.a, b), op_ab)
            self.assertEqual(op(b, obj._stored.a), op_ba)

    def test_set_operations(self):
        test_operations = [(
            {"1"},  # A set to test an operation against (other_set).
            lambda a, b: a | b,  # An operation to test.
            {"1", "a", "b"},  # The expected result of operation(obj._stored.set, other_set).
            {"1", "a", "b"}  # The expected result of operation(other_set, obj._stored.set).
        ), (
            {"a", "c"},
            lambda a, b: a - b,
            {"b"},
            {"c"}
        ), (
            {"a", "c"},
            lambda a, b: a & b,
            {"a"},
            {"a"}
        ), (
            {"a", "c", "d"},
            lambda a, b: a ^ b,
            {"b", "c", "d"},
            {"b", "c", "d"}
        ), (
            set(),
            lambda a, b: set(a),
            {"a", "b"},
            set()
        )]

        class SomeObject(Object):
            _stored = StoredState()

        framework = self.create_framework()

        # Validate that operations between StoredSet and built-in sets
        # only result in built-in sets being returned.
        # Make sure that commutativity is preserved and that the
        # original sets are not changed or used as a result.
        for i, (variable_operand, operation, ab_res, ba_res) in enumerate(test_operations):
            obj = SomeObject(framework, str(i))
            obj._stored.set = {"a", "b"}

            for a, b, expected in [
                (obj._stored.set, variable_operand, ab_res),
                    (variable_operand, obj._stored.set, ba_res)]:
                old_a = set(a)
                old_b = set(b)

                result = operation(a, b)
                self.assertEqual(result, expected)

                # Common sanity checks
                self.assertIsNot(obj._stored.set._under, result)
                self.assertIsNot(result, a)
                self.assertIsNot(result, b)
                self.assertEqual(a, old_a)
                self.assertEqual(b, old_b)

    def test_set_default(self):
        framework = self.create_framework()

        class StatefulObject(Object):
            _stored = StoredState()
        parent = StatefulObject(framework, 'key')
        parent._stored.set_default(foo=1)
        self.assertEqual(parent._stored.foo, 1)
        parent._stored.set_default(foo=2)
        # foo was already set, so it doesn't get replaced
        self.assertEqual(parent._stored.foo, 1)
        parent._stored.set_default(foo=3, bar=4)
        self.assertEqual(parent._stored.foo, 1)
        self.assertEqual(parent._stored.bar, 4)
        # reloading the state still leaves things at the default values
        framework.commit()
        del parent
        parent = StatefulObject(framework, 'key')
        parent._stored.set_default(foo=5, bar=6)
        self.assertEqual(parent._stored.foo, 1)
        self.assertEqual(parent._stored.bar, 4)
        # TODO: jam 2020-01-30 is there a clean way to tell that
        #       parent._stored._data.dirty is False?
