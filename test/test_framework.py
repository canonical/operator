#!/usr/bin/python3
# Copyright 2019 Canonical Ltd.
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

import unittest
import tempfile
import shutil
import gc
import datetime

from pathlib import Path

from ops.framework import (
    Framework, Handle, EventSource, EventsBase, EventBase, Object, PreCommitEvent, CommitEvent,
    NoSnapshotError, StoredState, StoredList, BoundStoredState, StoredStateData, SQLiteStorage
)


class TestFramework(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir)
        default_timeout = SQLiteStorage.DB_LOCK_TIMEOUT

        def timeout_cleanup():
            SQLiteStorage.DB_LOCK_TIMEOUT = default_timeout
        SQLiteStorage.DB_LOCK_TIMEOUT = datetime.timedelta(0)
        self.addCleanup(timeout_cleanup)

    def create_framework(self):
        framework = Framework(self.tmpdir / "framework.data", self.tmpdir, None, None)
        self.addCleanup(framework.close)
        return framework

    def test_handle_path(self):
        cases = [
            (Handle(None, "root", None), "root"),
            (Handle(None, "root", "1"), "root[1]"),
            (Handle(Handle(None, "root", None), "child", None), "root/child"),
            (Handle(Handle(None, "root", "1"), "child", "2"), "root[1]/child[2]"),
        ]
        for handle, path in cases:
            self.assertEqual(str(handle), path)
            self.assertEqual(Handle.from_path(path), handle)

    def test_handle_attrs_readonly(self):
        handle = Handle(None, 'kind', 'key')
        with self.assertRaises(AttributeError):
            handle.parent = 'foo'
        with self.assertRaises(AttributeError):
            handle.kind = 'foo'
        with self.assertRaises(AttributeError):
            handle.key = 'foo'
        with self.assertRaises(AttributeError):
            handle.path = 'foo'

    def test_restore_unknown(self):
        framework = self.create_framework()

        class Foo(Object):
            pass

        handle = Handle(None, "a_foo", "some_key")

        framework.register_type(Foo, None, handle.kind)

        try:
            framework.load_snapshot(handle)
        except NoSnapshotError as e:
            self.assertEqual(e.handle_path, str(handle))
            self.assertEqual(str(e), "no snapshot data found for a_foo[some_key] object")
        else:
            self.fail("exception NoSnapshotError not raised")

    def test_snapshot_roundtrip(self):
        class Foo:
            def __init__(self, handle, n):
                self.handle = handle
                self.my_n = n

            def snapshot(self):
                return {"My N!": self.my_n}

            def restore(self, snapshot):
                self.my_n = snapshot["My N!"] + 1

        handle = Handle(None, "a_foo", "some_key")
        event = Foo(handle, 1)

        framework1 = self.create_framework()
        framework1.register_type(Foo, None, handle.kind)
        framework1.save_snapshot(event)
        framework1.commit()
        framework1.close()

        framework2 = self.create_framework()
        framework2.register_type(Foo, None, handle.kind)
        event2 = framework2.load_snapshot(handle)
        self.assertEqual(event2.my_n, 2)

        framework2.save_snapshot(event2)
        del event2
        gc.collect()
        event3 = framework2.load_snapshot(handle)
        self.assertEqual(event3.my_n, 3)

        framework2.drop_snapshot(event.handle)
        framework2.commit()
        framework2.close()

        framework3 = self.create_framework()
        framework3.register_type(Foo, None, handle.kind)

        self.assertRaises(NoSnapshotError, framework3.load_snapshot, handle)

    def test_simple_event_observer(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyNotifier(Object):
            foo = EventSource(MyEvent)
            bar = EventSource(MyEvent)
            baz = EventSource(MyEvent)

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_any(self, event):
                self.seen.append("on_any:" + event.handle.kind)

            def on_foo(self, event):
                self.seen.append("on_foo:" + event.handle.kind)

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs.on_any)
        framework.observe(pub.bar, obs.on_any)
        framework.observe(pub.foo, obs)  # Method name defaults to on_<event kind>.

        try:
            framework.observe(pub.baz, obs)
        except RuntimeError as e:
            self.assertEqual(str(e), 'Observer method not provided explicitly and MyObserver type has no "on_baz" method')
        else:
            self.fail("RuntimeError not raised")

        pub.foo.emit()
        pub.bar.emit()

        self.assertEqual(obs.seen, ["on_any:foo", "on_foo:foo", "on_any:bar"])

    def test_bad_sig_observer(self):

        class MyEvent(EventBase):
            pass

        class MyNotifier(Object):
            foo = EventSource(MyEvent)
            bar = EventSource(MyEvent)
            baz = EventSource(MyEvent)
            qux = EventSource(MyEvent)

        class MyObserver(Object):
            def on_foo(self):
                assert False, 'should not be reached'

            def on_bar(self, event, extra):
                assert False, 'should not be reached'

            def on_baz(self, event, extra=None, *, k):
                assert False, 'should not be reached'

            def on_qux(self, event, extra=None):
                assert False, 'should not be reached'

        framework = self.create_framework()
        pub = MyNotifier(framework, "pub")
        obs = MyObserver(framework, "obs")

        with self.assertRaises(TypeError):
            framework.observe(pub.foo, obs)
        with self.assertRaises(TypeError):
            framework.observe(pub.bar, obs)
        with self.assertRaises(TypeError):
            framework.observe(pub.baz, obs)
        framework.observe(pub.qux, obs)

    def test_on_pre_commit_emitted(self):
        framework = self.create_framework()

        class PreCommitObserver(Object):

            state = StoredState()

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []
                self.state.myinitdata = 40

            def on_pre_commit(self, event):
                self.state.myinitdata = 41
                self.state.mydata = 42
                self.seen.append(type(event))

            def on_commit(self, event):
                # Modifications made here will not be persisted.
                self.state.myinitdata = 42
                self.state.mydata = 43
                self.state.myotherdata = 43
                self.seen.append(type(event))

        obs = PreCommitObserver(framework, None)

        framework.observe(framework.on.pre_commit, obs.on_pre_commit)

        framework.commit()

        self.assertEqual(obs.state.myinitdata, 41)
        self.assertEqual(obs.state.mydata, 42)
        self.assertTrue(obs.seen, [PreCommitEvent, CommitEvent])
        framework.close()

        other_framework = self.create_framework()

        new_obs = PreCommitObserver(other_framework, None)

        self.assertEqual(obs.state.myinitdata, 41)
        self.assertEqual(new_obs.state.mydata, 42)

        with self.assertRaises(AttributeError):
            new_obs.state.myotherdata

    def test_defer_and_reemit(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyNotifier1(Object):
            a = EventSource(MyEvent)
            b = EventSource(MyEvent)

        class MyNotifier2(Object):
            c = EventSource(MyEvent)

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []
                self.done = {}

            def on_any(self, event):
                self.seen.append(event.handle.kind)
                if not self.done.get(event.handle.kind):
                    event.defer()

        pub1 = MyNotifier1(framework, "1")
        pub2 = MyNotifier2(framework, "1")
        obs1 = MyObserver(framework, "1")
        obs2 = MyObserver(framework, "2")

        framework.observe(pub1.a, obs1.on_any)
        framework.observe(pub1.b, obs1.on_any)
        framework.observe(pub1.a, obs2.on_any)
        framework.observe(pub1.b, obs2.on_any)
        framework.observe(pub2.c, obs2.on_any)

        pub1.a.emit()
        pub1.b.emit()
        pub2.c.emit()

        # Events remain stored because they were deferred.
        ev_a_handle = Handle(pub1, "a", "1")
        framework.load_snapshot(ev_a_handle)
        ev_b_handle = Handle(pub1, "b", "2")
        framework.load_snapshot(ev_b_handle)
        ev_c_handle = Handle(pub2, "c", "3")
        framework.load_snapshot(ev_c_handle)
        # make sure the objects are gone before we reemit them
        gc.collect()

        framework.reemit()
        obs1.done["a"] = True
        obs2.done["b"] = True
        framework.reemit()
        framework.reemit()
        obs1.done["b"] = True
        obs2.done["a"] = True
        framework.reemit()
        obs2.done["c"] = True
        framework.reemit()
        framework.reemit()
        framework.reemit()

        self.assertEqual(" ".join(obs1.seen), "a b a b a b b b")
        self.assertEqual(" ".join(obs2.seen), "a b c a b c a b c a c a c c")

        # Now the event objects must all be gone from storage.
        self.assertRaises(NoSnapshotError, framework.load_snapshot, ev_a_handle)
        self.assertRaises(NoSnapshotError, framework.load_snapshot, ev_b_handle)
        self.assertRaises(NoSnapshotError, framework.load_snapshot, ev_c_handle)

    def test_custom_event_data(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            def __init__(self, handle, n):
                super().__init__(handle)
                self.my_n = n

            def snapshot(self):
                return {"My N!": self.my_n}

            def restore(self, snapshot):
                super().restore(snapshot)
                self.my_n = snapshot["My N!"] + 1

        class MyNotifier(Object):
            foo = EventSource(MyEvent)

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(f"on_foo:{event.handle.kind}={event.my_n}")
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs)

        pub.foo.emit(1)

        framework.reemit()

        # Two things being checked here:
        #
        # 1. There's a restore roundtrip before the event is first observed.
        #    That means the data is safe before it's ever seen, and the
        #    roundtrip logic is tested under normal circumstances.
        #
        # 2. The renotification restores from the pristine event, not
        #    from the one modified during the first restore (otherwise
        #    we'd get a foo=3).
        #
        self.assertEqual(obs.seen, ["on_foo:foo=2", "on_foo:foo=2"])

    def test_weak_observer(self):
        framework = self.create_framework()

        observed_events = []

        class MyEvent(EventBase):
            pass

        class MyEvents(EventsBase):
            foo = EventSource(MyEvent)

        class MyNotifier(Object):
            on = MyEvents()

        class MyObserver(Object):
            def on_foo(self, event):
                observed_events.append("foo")

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "2")

        framework.observe(pub.on.foo, obs)
        pub.on.foo.emit()
        self.assertEqual(observed_events, ["foo"])
        # Now delete the observer, and note that when we emit the event, it
        # doesn't update the local slice again
        del obs
        gc.collect()
        pub.on.foo.emit()
        self.assertEqual(observed_events, ["foo"])

    def test_forget_and_multiple_objects(self):
        framework = self.create_framework()

        class MyObject(Object):
            pass

        o1 = MyObject(framework, "path")
        # Creating a second object at the same path should fail with RuntimeError
        with self.assertRaises(RuntimeError):
            o2 = MyObject(framework, "path")
        # Unless we _forget the object first
        framework._forget(o1)
        o2 = MyObject(framework, "path")
        self.assertEqual(o1.handle.path, o2.handle.path)
        # Deleting the tracked object should also work
        del o2
        gc.collect()
        o3 = MyObject(framework, "path")
        self.assertEqual(o1.handle.path, o3.handle.path)
        framework.close()
        # Or using a second framework
        framework_copy = self.create_framework()
        o_copy = MyObject(framework_copy, "path")
        self.assertEqual(o1.handle.path, o_copy.handle.path)

    def test_forget_and_multiple_objects_with_load_snapshot(self):
        framework = self.create_framework()

        class MyObject(Object):
            def __init__(self, parent, name):
                super().__init__(parent, name)
                self.value = name

            def snapshot(self):
                return self.value

            def restore(self, value):
                self.value = value

        framework.register_type(MyObject, None, MyObject.handle_kind)
        o1 = MyObject(framework, "path")
        framework.save_snapshot(o1)
        framework.commit()
        o_handle = o1.handle
        del o1
        gc.collect()
        o2 = framework.load_snapshot(o_handle)
        # Trying to load_snapshot a second object at the same path should fail with RuntimeError
        with self.assertRaises(RuntimeError):
            framework.load_snapshot(o_handle)
        # Unless we _forget the object first
        framework._forget(o2)
        o3 = framework.load_snapshot(o_handle)
        self.assertEqual(o2.value, o3.value)
        # A loaded object also prevents direct creation of an object
        with self.assertRaises(RuntimeError):
            MyObject(framework, "path")
        framework.close()
        # But we can create an object, or load a snapshot in a copy of the framework
        framework_copy1 = self.create_framework()
        o_copy1 = MyObject(framework_copy1, "path")
        self.assertEqual(o_copy1.value, "path")
        framework_copy1.close()
        framework_copy2 = self.create_framework()
        framework_copy2.register_type(MyObject, None, MyObject.handle_kind)
        o_copy2 = framework_copy2.load_snapshot(o_handle)
        self.assertEqual(o_copy2.value, "path")

    def test_events_base(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyEvents(EventsBase):
            foo = EventSource(MyEvent)
            bar = EventSource(MyEvent)

        class MyNotifier(Object):
            on = MyEvents()

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(f"on_foo:{event.handle.kind}")
                event.defer()

            def on_bar(self, event):
                self.seen.append(f"on_bar:{event.handle.kind}")

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        # Confirm that temporary persistence of BoundEvents doesn't cause errors,
        # and that events can be observed.
        for bound_event in [pub.on.foo, pub.on.bar]:
            framework.observe(bound_event, obs)

        # Confirm that events can be emitted and seen.
        pub.on.foo.emit()

        self.assertEqual(obs.seen, ["on_foo:foo"])

    def test_conflicting_event_attributes(self):
        class MyEvent(EventBase):
            pass

        event = EventSource(MyEvent)

        class MyEvents(EventsBase):
            foo = event

        with self.assertRaises(RuntimeError) as cm:
            class OtherEvents(EventsBase):
                foo = event
        self.assertEqual(
            str(cm.exception.__cause__),
            "EventSource(MyEvent) reused as MyEvents.foo and OtherEvents.foo")

        with self.assertRaises(RuntimeError) as cm:
            class MyNotifier(Object):
                on = MyEvents()
                bar = event
        self.assertEqual(
            str(cm.exception.__cause__),
            "EventSource(MyEvent) reused as MyEvents.foo and MyNotifier.bar")

    def test_reemit_ignores_unknown_event_type(self):
        # The event type may have been gone for good, and nobody cares,
        # so this shouldn't be an error scenario.

        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyNotifier(Object):
            foo = EventSource(MyEvent)

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(event.handle)
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs)
        pub.foo.emit()

        event_handle = obs.seen[0]
        self.assertEqual(event_handle.kind, "foo")

        framework.commit()
        framework.close()

        framework_copy = self.create_framework()

        # No errors on missing event types here.
        framework_copy.reemit()

        # Register the type and check that the event is gone from storage.
        framework_copy.register_type(MyEvent, event_handle.parent, event_handle.kind)
        self.assertRaises(NoSnapshotError, framework_copy.load_snapshot, event_handle)

    def test_auto_register_event_types(self):
        framework = self.create_framework()

        class MyFoo(EventBase):
            pass

        class MyBar(EventBase):
            pass

        class MyEvents(EventsBase):
            foo = EventSource(MyFoo)

        class MyNotifier(Object):
            on = MyEvents()
            bar = EventSource(MyBar)

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(f"on_foo:{type(event).__name__}:{event.handle.kind}")
                event.defer()

            def on_bar(self, event):
                self.seen.append(f"on_bar:{type(event).__name__}:{event.handle.kind}")
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        pub.on.foo.emit()
        pub.bar.emit()

        framework.observe(pub.on.foo, obs)
        framework.observe(pub.bar, obs)

        pub.on.foo.emit()
        pub.bar.emit()

        self.assertEqual(obs.seen, ["on_foo:MyFoo:foo", "on_bar:MyBar:bar"])

    def test_dynamic_event_types(self):
        framework = self.create_framework()

        class MyEventsA(EventsBase):
            handle_kind = 'on_a'

        class MyEventsB(EventsBase):
            handle_kind = 'on_b'

        class MyNotifier(Object):
            on_a = MyEventsA()
            on_b = MyEventsB()

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(f"on_foo:{type(event).__name__}:{event.handle.kind}")
                event.defer()

            def on_bar(self, event):
                self.seen.append(f"on_bar:{type(event).__name__}:{event.handle.kind}")
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        class MyFoo(EventBase):
            pass

        class MyBar(EventBase):
            pass

        class DeadBeefEvent(EventBase):
            pass

        class NoneEvent(EventBase):
            pass

        pub.on_a.define_event("foo", MyFoo)
        pub.on_b.define_event("bar", MyBar)

        framework.observe(pub.on_a.foo, obs)
        framework.observe(pub.on_b.bar, obs)

        pub.on_a.foo.emit()
        pub.on_b.bar.emit()

        self.assertEqual(obs.seen, ["on_foo:MyFoo:foo", "on_bar:MyBar:bar"])

        # Definitions remained local to the specific type.
        self.assertRaises(AttributeError, lambda: pub.on_a.bar)
        self.assertRaises(AttributeError, lambda: pub.on_b.foo)

        # Try to use an event name which is not a valid python identifier.
        with self.assertRaises(RuntimeError):
            pub.on_a.define_event("dead-beef", DeadBeefEvent)

        # Try to use a python keyword for an event name.
        with self.assertRaises(RuntimeError):
            pub.on_a.define_event("None", NoneEvent)

        # Try to override an existing attribute.
        with self.assertRaises(RuntimeError):
            pub.on_a.define_event("foo", MyFoo)

    def test_event_key_roundtrip(self):
        class MyEvent(EventBase):
            def __init__(self, handle, value):
                super().__init__(handle)
                self.value = value

            def snapshot(self):
                return self.value

            def restore(self, value):
                self.value = value

        class MyNotifier(Object):
            foo = EventSource(MyEvent)

        class MyObserver(Object):
            has_deferred = False

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_foo(self, event):
                self.seen.append((event.handle.key, event.value))
                # Only defer the first event and once.
                if not MyObserver.has_deferred:
                    event.defer()
                    MyObserver.has_deferred = True

        framework1 = self.create_framework()
        pub1 = MyNotifier(framework1, "pub")
        obs1 = MyObserver(framework1, "obs")
        framework1.observe(pub1.foo, obs1)
        pub1.foo.emit('first')
        self.assertEqual(obs1.seen, [('1', 'first')])

        framework1.commit()
        framework1.close()
        del framework1

        framework2 = self.create_framework()
        pub2 = MyNotifier(framework2, "pub")
        obs2 = MyObserver(framework2, "obs")
        framework2.observe(pub2.foo, obs2)
        pub2.foo.emit('second')
        framework2.reemit()

        # First observer didn't get updated, since framework it was bound to is gone.
        self.assertEqual(obs1.seen, [('1', 'first')])
        # Second observer saw the new event plus the reemit of the first event.
        # (The event key goes up by 2 due to the pre-commit and commit events.)
        self.assertEqual(obs2.seen, [('4', 'second'), ('1', 'first')])

    def test_helper_properties(self):
        framework = self.create_framework()
        framework.model = 'test-model'
        framework.meta = 'test-meta'

        my_obj = Object(framework, 'my_obj')
        self.assertEqual(my_obj.model, framework.model)
        self.assertEqual(my_obj.meta, framework.meta)
        self.assertEqual(my_obj.charm_dir, framework.charm_dir)

    def test_ban_concurrent_frameworks(self):
        f = self.create_framework()
        with self.assertRaises(Exception) as cm:
            self.create_framework()
        self.assertIn('database is locked', str(cm.exception))
        f.close()


class TestStoredState(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir)

    def create_framework(self, cls=Framework):
        framework = cls(self.tmpdir / "framework.data", self.tmpdir, None, None)
        self.addCleanup(framework.close)
        return framework

    def test_basic_state_storage(self):
        framework = self.create_framework()

        class SomeObject(Object):
            state = StoredState()

        obj = SomeObject(framework, "1")

        try:
            obj.state.foo
        except AttributeError as e:
            self.assertEqual(str(e), "attribute 'foo' is not stored")
        else:
            self.fail("AttributeError not raised")

        try:
            obj.state.on = "nonono"
        except AttributeError as e:
            self.assertEqual(str(e), "attribute 'on' is reserved and cannot be set")
        else:
            self.fail("AttributeError not raised")

        obj.state.foo = 41
        obj.state.foo = 42
        obj.state.bar = "s"

        self.assertEqual(obj.state.foo, 42)

        framework.commit()

        # This won't be committed, and should not be seen.
        obj.state.foo = 43

        framework.close()

        # Since this has the same absolute object handle, it will get its state back.
        framework_copy = self.create_framework()
        obj_copy = SomeObject(framework_copy, "1")
        self.assertEqual(obj_copy.state.foo, 42)
        self.assertEqual(obj_copy.state.bar, "s")

    def test_mutable_types_invalid(self):
        framework = self.create_framework()

        class SomeObject(Object):
            state = StoredState()

        obj = SomeObject(framework, '1')
        try:
            class CustomObject:
                pass
            obj.state.foo = CustomObject()
        except AttributeError as e:
            self.assertEqual(str(e), "attribute 'foo' cannot be set to CustomObject: must be int/dict/list/etc")
        else:
            self.fail('AttributeError not raised')

        framework.commit()

    def test_mutable_types(self):
        # Test and validation functions in a list of 2-tuples.
        # Assignment and keywords like del are not supported in lambdas so functions are used instead.
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
            set(['a']),
            lambda a, b: a.add(b),
            lambda res, expected_res: self.assertEqual(res, expected_res)
        ), (
            lambda: set(['a']),
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
            state = StoredState()

        class WrappedFramework(Framework):
            def __init__(self, data_path, charm_dir, meta, model):
                super().__init__(data_path, charm_dir, meta, model)
                self.snapshots = []

            def save_snapshot(self, value):
                if value.handle.path == 'SomeObject[1]/StoredStateData[state]':
                    self.snapshots.append((type(value), value.snapshot()))
                return super().save_snapshot(value)

        # Validate correctness of modification operations.
        for get_a, b, expected_res, op, validate_op in test_operations:
            framework = self.create_framework(cls=WrappedFramework)
            obj = SomeObject(framework, '1')

            obj.state.a = get_a()
            self.assertTrue(isinstance(obj.state, BoundStoredState))

            op(obj.state.a, b)
            validate_op(obj.state.a, expected_res)

            obj.state.a = get_a()
            framework.commit()
            # We should see an update for initializing a
            self.assertEqual(framework.snapshots, [
                (StoredStateData, {'a': get_a()}),
            ])
            del obj
            gc.collect()
            obj_copy1 = SomeObject(framework, '1')
            self.assertEqual(obj_copy1.state.a, get_a())

            op(obj_copy1.state.a, b)
            validate_op(obj_copy1.state.a, expected_res)
            framework.commit()
            framework.close()

            framework_copy = self.create_framework(cls=WrappedFramework)

            obj_copy2 = SomeObject(framework_copy, '1')

            validate_op(obj_copy2.state.a, expected_res)

            # Commit saves the pre-commit and commit events, and the framework event counter, but shouldn't update the stored state of my object
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
            state = StoredState()

        framework = self.create_framework()

        for i, (a, b, op, op_ab, op_ba) in enumerate(test_operations):
            obj = SomeObject(framework, str(i))
            obj.state.a = a
            self.assertEqual(op(obj.state.a, b), op_ab)
            self.assertEqual(op(b, obj.state.a), op_ba)

    def test_set_operations(self):
        test_operations = [(
            {"1"},  # A set to test an operation against (other_set).
            lambda a, b: a | b,  # An operation to test.
            {"1", "a", "b"},  # The expected result of operation(obj.state.set, other_set).
            {"1", "a", "b"}  # The expected result of operation(other_set, obj.state.set).
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
            state = StoredState()

        framework = self.create_framework()

        # Validate that operations between StoredSet and built-in sets only result in built-in sets being returned.
        # Make sure that commutativity is preserved and that the original sets are not changed or used as a result.
        for i, (variable_operand, operation, ab_res, ba_res) in enumerate(test_operations):
            obj = SomeObject(framework, str(i))
            obj.state.set = {"a", "b"}

            for a, b, expected in [(obj.state.set, variable_operand, ab_res), (variable_operand, obj.state.set, ba_res)]:
                old_a = set(a)
                old_b = set(b)

                result = operation(a, b)
                self.assertEqual(result, expected)

                # Common sanity checks
                self.assertIsNot(obj.state.set._under, result)
                self.assertIsNot(result, a)
                self.assertIsNot(result, b)
                self.assertEqual(a, old_a)
                self.assertEqual(b, old_b)

    def test_set_default(self):
        framework = self.create_framework()

        class StatefulObject(Object):
            state = StoredState()
        parent = StatefulObject(framework, 'key')
        parent.state.set_default(foo=1)
        self.assertEqual(parent.state.foo, 1)
        parent.state.set_default(foo=2)
        # foo was already set, so it doesn't get replaced
        self.assertEqual(parent.state.foo, 1)
        parent.state.set_default(foo=3, bar=4)
        self.assertEqual(parent.state.foo, 1)
        self.assertEqual(parent.state.bar, 4)
        # reloading the state still leaves things at the default values
        framework.commit()
        del parent
        parent = StatefulObject(framework, 'key')
        parent.state.set_default(foo=5, bar=6)
        self.assertEqual(parent.state.foo, 1)
        self.assertEqual(parent.state.bar, 4)
        # TODO(jam) 2020-01-30: is there a clean way to tell that parent.state._data.dirty is False?


if __name__ == "__main__":
    unittest.main()
