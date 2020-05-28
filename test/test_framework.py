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

import datetime
import gc
import inspect
import io
import os
import shutil
import sys
import tempfile
from unittest.mock import patch
from pathlib import Path

from ops import charm
from ops.framework import (
    _BREAKPOINT_WELCOME_MESSAGE,
    BoundStoredState,
    CommitEvent,
    EventBase,
    ObjectEvents,
    EventSource,
    Framework,
    Handle,
    NoSnapshotError,
    Object,
    PreCommitEvent,
    StoredList,
    StoredState,
    StoredStateData,
)
from test.test_helpers import fake_script, BaseTestCase


class TestFramework(BaseTestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

        patcher = patch('ops.framework.SQLiteStorage.DB_LOCK_TIMEOUT', datetime.timedelta(0))
        patcher.start()
        self.addCleanup(patcher.stop)

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

        framework1 = self.create_framework(tmpdir=self.tmpdir)
        framework1.register_type(Foo, None, handle.kind)
        framework1.save_snapshot(event)
        framework1.commit()
        framework1.close()

        framework2 = self.create_framework(tmpdir=self.tmpdir)
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

        framework3 = self.create_framework(tmpdir=self.tmpdir)
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

        with self.assertRaisesRegex(RuntimeError, "^Framework.observe requires a method"):
            framework.observe(pub.baz, obs)

        pub.foo.emit()
        pub.bar.emit()

        self.assertEqual(obs.seen, ["on_any:foo", "on_any:bar"])

    def test_bad_sig_observer(self):

        class MyEvent(EventBase):
            pass

        class MyNotifier(Object):
            foo = EventSource(MyEvent)
            bar = EventSource(MyEvent)
            baz = EventSource(MyEvent)
            qux = EventSource(MyEvent)

        class MyObserver(Object):
            def _on_foo(self):
                assert False, 'should not be reached'

            def _on_bar(self, event, extra):
                assert False, 'should not be reached'

            def _on_baz(self, event, extra=None, *, k):
                assert False, 'should not be reached'

            def _on_qux(self, event, extra=None):
                assert False, 'should not be reached'

        framework = self.create_framework()
        pub = MyNotifier(framework, "pub")
        obs = MyObserver(framework, "obs")

        with self.assertRaisesRegex(TypeError, "must accept event parameter"):
            framework.observe(pub.foo, obs._on_foo)
        with self.assertRaisesRegex(TypeError, "has extra required parameter"):
            framework.observe(pub.bar, obs._on_bar)
        with self.assertRaisesRegex(TypeError, "has extra required parameter"):
            framework.observe(pub.baz, obs._on_baz)
        framework.observe(pub.qux, obs._on_qux)

    def test_on_pre_commit_emitted(self):
        framework = self.create_framework(tmpdir=self.tmpdir)

        class PreCommitObserver(Object):

            _stored = StoredState()

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []
                self._stored.myinitdata = 40

            def on_pre_commit(self, event):
                self._stored.myinitdata = 41
                self._stored.mydata = 42
                self.seen.append(type(event))

            def on_commit(self, event):
                # Modifications made here will not be persisted.
                self._stored.myinitdata = 42
                self._stored.mydata = 43
                self._stored.myotherdata = 43
                self.seen.append(type(event))

        obs = PreCommitObserver(framework, None)

        framework.observe(framework.on.pre_commit, obs.on_pre_commit)

        framework.commit()

        self.assertEqual(obs._stored.myinitdata, 41)
        self.assertEqual(obs._stored.mydata, 42)
        self.assertTrue(obs.seen, [PreCommitEvent, CommitEvent])
        framework.close()

        other_framework = self.create_framework(tmpdir=self.tmpdir)

        new_obs = PreCommitObserver(other_framework, None)

        self.assertEqual(obs._stored.myinitdata, 41)
        self.assertEqual(new_obs._stored.mydata, 42)

        with self.assertRaises(AttributeError):
            new_obs._stored.myotherdata

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

            def _on_foo(self, event):
                self.seen.append("on_foo:{}={}".format(event.handle.kind, event.my_n))
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs._on_foo)

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

        class MyEvents(ObjectEvents):
            foo = EventSource(MyEvent)

        class MyNotifier(Object):
            on = MyEvents()

        class MyObserver(Object):
            def _on_foo(self, event):
                observed_events.append("foo")

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "2")

        framework.observe(pub.on.foo, obs._on_foo)
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
        framework = self.create_framework(tmpdir=self.tmpdir)

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
        framework_copy1 = self.create_framework(tmpdir=self.tmpdir)
        o_copy1 = MyObject(framework_copy1, "path")
        self.assertEqual(o_copy1.value, "path")
        framework_copy1.close()
        framework_copy2 = self.create_framework(tmpdir=self.tmpdir)
        framework_copy2.register_type(MyObject, None, MyObject.handle_kind)
        o_copy2 = framework_copy2.load_snapshot(o_handle)
        self.assertEqual(o_copy2.value, "path")

    def test_events_base(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyEvents(ObjectEvents):
            foo = EventSource(MyEvent)
            bar = EventSource(MyEvent)

        class MyNotifier(Object):
            on = MyEvents()

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def _on_foo(self, event):
                self.seen.append("on_foo:{}".format(event.handle.kind))
                event.defer()

            def _on_bar(self, event):
                self.seen.append("on_bar:{}".format(event.handle.kind))

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        # Confirm that temporary persistence of BoundEvents doesn't cause errors,
        # and that events can be observed.
        for bound_event, handler in [(pub.on.foo, obs._on_foo), (pub.on.bar, obs._on_bar)]:
            framework.observe(bound_event, handler)

        # Confirm that events can be emitted and seen.
        pub.on.foo.emit()

        self.assertEqual(obs.seen, ["on_foo:foo"])

    def test_conflicting_event_attributes(self):
        class MyEvent(EventBase):
            pass

        event = EventSource(MyEvent)

        class MyEvents(ObjectEvents):
            foo = event

        with self.assertRaises(RuntimeError) as cm:
            class OtherEvents(ObjectEvents):
                foo = event
        self.assertEqual(
            str(cm.exception),
            "EventSource(MyEvent) reused as MyEvents.foo and OtherEvents.foo")

        with self.assertRaises(RuntimeError) as cm:
            class MyNotifier(Object):
                on = MyEvents()
                bar = event
        self.assertEqual(
            str(cm.exception),
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

            def _on_foo(self, event):
                self.seen.append(event.handle)
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs._on_foo)
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

        class MyEvents(ObjectEvents):
            foo = EventSource(MyFoo)

        class MyNotifier(Object):
            on = MyEvents()
            bar = EventSource(MyBar)

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def _on_foo(self, event):
                self.seen.append("on_foo:{}:{}".format(type(event).__name__, event.handle.kind))
                event.defer()

            def _on_bar(self, event):
                self.seen.append("on_bar:{}:{}".format(type(event).__name__, event.handle.kind))
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        pub.on.foo.emit()
        pub.bar.emit()

        framework.observe(pub.on.foo, obs._on_foo)
        framework.observe(pub.bar, obs._on_bar)

        pub.on.foo.emit()
        pub.bar.emit()

        self.assertEqual(obs.seen, ["on_foo:MyFoo:foo", "on_bar:MyBar:bar"])

    def test_dynamic_event_types(self):
        framework = self.create_framework()

        class MyEventsA(ObjectEvents):
            handle_kind = 'on_a'

        class MyEventsB(ObjectEvents):
            handle_kind = 'on_b'

        class MyNotifier(Object):
            on_a = MyEventsA()
            on_b = MyEventsB()

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def _on_foo(self, event):
                self.seen.append("on_foo:{}:{}".format(type(event).__name__, event.handle.kind))
                event.defer()

            def _on_bar(self, event):
                self.seen.append("on_bar:{}:{}".format(type(event).__name__, event.handle.kind))
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

        framework.observe(pub.on_a.foo, obs._on_foo)
        framework.observe(pub.on_b.bar, obs._on_bar)

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

            def _on_foo(self, event):
                self.seen.append((event.handle.key, event.value))
                # Only defer the first event and once.
                if not MyObserver.has_deferred:
                    event.defer()
                    MyObserver.has_deferred = True

        framework1 = self.create_framework(tmpdir=self.tmpdir)
        pub1 = MyNotifier(framework1, "pub")
        obs1 = MyObserver(framework1, "obs")
        framework1.observe(pub1.foo, obs1._on_foo)
        pub1.foo.emit('first')
        self.assertEqual(obs1.seen, [('1', 'first')])

        framework1.commit()
        framework1.close()
        del framework1

        framework2 = self.create_framework(tmpdir=self.tmpdir)
        pub2 = MyNotifier(framework2, "pub")
        obs2 = MyObserver(framework2, "obs")
        framework2.observe(pub2.foo, obs2._on_foo)
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

    def test_ban_concurrent_frameworks(self):
        f = self.create_framework(tmpdir=self.tmpdir)
        with self.assertRaises(Exception) as cm:
            self.create_framework(tmpdir=self.tmpdir)
        self.assertIn('database is locked', str(cm.exception))
        f.close()

    def test_snapshot_saving_restricted_to_simple_types(self):
        # this can not be saved, as it has not simple types!
        to_be_saved = {"bar": TestFramework}

        class FooEvent(EventBase):
            def snapshot(self):
                return to_be_saved

        handle = Handle(None, "a_foo", "some_key")
        event = FooEvent(handle)

        framework = self.create_framework()
        framework.register_type(FooEvent, None, handle.kind)
        with self.assertRaises(ValueError) as cm:
            framework.save_snapshot(event)
        expected = (
            "unable to save the data for FooEvent, it must contain only simple types: "
            "{'bar': <class 'test.test_framework.TestFramework'>}")
        self.assertEqual(str(cm.exception), expected)


class TestStoredState(BaseTestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

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

        class SubSub(SomeObject):
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
            _stored = StoredState()

        class WrappedFramework(Framework):
            def __init__(self, data_path, charm_dir, meta, model):
                super().__init__(data_path, charm_dir, meta, model)
                self.snapshots = []

            def save_snapshot(self, value):
                if value.handle.path == 'SomeObject[1]/StoredStateData[_stored]':
                    self.snapshots.append((type(value), value.snapshot()))
                return super().save_snapshot(value)

        # Validate correctness of modification operations.
        for get_a, b, expected_res, op, validate_op in test_operations:
            framework = WrappedFramework(self.tmpdir / "framework.data", self.tmpdir, None, None)
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

            framework_copy = WrappedFramework(
                self.tmpdir / "framework.data", self.tmpdir, None, None)

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


class GenericObserver(Object):
    """Generic observer for the tests."""

    def __init__(self, parent, key):
        super().__init__(parent, key)
        self.called = False

    def callback_method(self, event):
        """Set the instance .called to True."""
        self.called = True


@patch('sys.stderr', new_callable=io.StringIO)
class BreakpointTests(BaseTestCase):

    def test_ignored(self, fake_stderr):
        # It doesn't do anything really unless proper environment is there.
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            framework.breakpoint()
        self.assertEqual(mock.call_count, 0)
        self.assertEqual(fake_stderr.getvalue(), "")

    def test_pdb_properly_called(self, fake_stderr):
        # The debugger needs to leave the user in the frame where the breakpoint is executed,
        # which for the test is the frame we're calling it here in the test :).
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            this_frame = inspect.currentframe()
            framework.breakpoint()

        self.assertEqual(mock.call_count, 1)
        self.assertEqual(mock.call_args, ((this_frame,), {}))

    def test_welcome_message(self, fake_stderr):
        # Check that an initial message is shown to the user when code is interrupted.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace'):
            framework.breakpoint()
        self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_welcome_message_not_multiple(self, fake_stderr):
        # Check that an initial message is NOT shown twice if the breakpoint is exercised
        # twice in the same run.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace'):
            framework.breakpoint()
            self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
            framework.breakpoint()
            self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_builtin_breakpoint_hooked(self, fake_stderr):
        # Verify that the proper hook is set.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            self.create_framework()  # creating the framework setups the hook
        with patch('pdb.Pdb.set_trace') as mock:
            # Calling through sys, not breakpoint() directly, so we can run the
            # tests with Py < 3.7.
            sys.breakpointhook()
        self.assertEqual(mock.call_count, 1)

    def test_breakpoint_names(self, fake_stderr):
        framework = self.create_framework()

        # Name rules:
        # - must start and end with lowercase alphanumeric characters
        # - only contain lowercase alphanumeric characters, or the hyphen "-"
        good_names = [
            'foobar',
            'foo-bar-baz',
            'foo-------bar',
            'foo123',
            '778',
            '77-xx',
            'a-b',
            'ab',
            'x',
        ]
        for name in good_names:
            with self.subTest(name=name):
                framework.breakpoint(name)

        bad_names = [
            '',
            '.',
            '-',
            '...foo',
            'foo.bar',
            'bar--'
            'FOO',
            'FooBar',
            'foo bar',
            'foo_bar',
            '/foobar',
            'break-here-☚',
        ]
        msg = 'breakpoint names must look like "foo" or "foo-bar"'
        for name in bad_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as cm:
                    framework.breakpoint(name)
                self.assertEqual(str(cm.exception), msg)

        reserved_names = [
            'all',
            'hook',
        ]
        msg = 'breakpoint names "all" and "hook" are reserved'
        for name in reserved_names:
            with self.subTest(name=name):
                with self.assertRaises(ValueError) as cm:
                    framework.breakpoint(name)
                self.assertEqual(str(cm.exception), msg)

        not_really_names = [
            123,
            1.1,
            False,
        ]
        for name in not_really_names:
            with self.subTest(name=name):
                with self.assertRaises(TypeError) as cm:
                    framework.breakpoint(name)
                self.assertEqual(str(cm.exception), 'breakpoint names must be strings')

    def check_trace_set(self, envvar_value, breakpoint_name, call_count):
        """Helper to check the diverse combinations of situations."""
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': envvar_value}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace') as mock:
            framework.breakpoint(breakpoint_name)
        self.assertEqual(mock.call_count, call_count)

    def test_unnamed_indicated_all(self, fake_stderr):
        # If 'all' is indicated, unnamed breakpoints will always activate.
        self.check_trace_set('all', None, 1)

    def test_unnamed_indicated_hook(self, fake_stderr):
        # Special value 'hook' was indicated, nothing to do with any call.
        self.check_trace_set('hook', None, 0)

    def test_named_indicated_specifically(self, fake_stderr):
        # Some breakpoint was indicated, and the framework call used exactly that name.
        self.check_trace_set('mybreak', 'mybreak', 1)

    def test_named_indicated_somethingelse(self, fake_stderr):
        # Some breakpoint was indicated, but the framework call was not with that name.
        self.check_trace_set('some-breakpoint', None, 0)

    def test_named_indicated_ingroup(self, fake_stderr):
        # A multiple breakpoint was indicated, and the framework call used a name among those.
        self.check_trace_set('some,mybreak,foobar', 'mybreak', 1)

    def test_named_indicated_all(self, fake_stderr):
        # The framework indicated 'all', which includes any named breakpoint set.
        self.check_trace_set('all', 'mybreak', 1)

    def test_named_indicated_hook(self, fake_stderr):
        # The framework indicated the special value 'hook', nothing to do with any named call.
        self.check_trace_set('hook', 'mybreak', 0)


class DebugHookTests(BaseTestCase):

    def test_envvar_parsing_missing(self):
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, ())

    def test_envvar_parsing_empty(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': ''}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, ())

    def test_envvar_parsing_simple(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'hook'}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, ['hook'])

    def test_envvar_parsing_multiple(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'foo,bar,all'}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, ['foo', 'bar', 'all'])

    def test_basic_interruption_enabled(self):
        framework = self.create_framework()
        framework._juju_debug_at = ['hook']

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO) as fake_stderr:
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        # Check that the pdb module was used correctly and that the callback method was NOT
        # called (as we intercepted the normal pdb behaviour! this is to check that the
        # framework didn't call the callback directly)
        self.assertEqual(mock.call_count, 1)
        expected_callback, expected_event = mock.call_args[0]
        self.assertEqual(expected_callback, observer.callback_method)
        self.assertIsInstance(expected_event, EventBase)
        self.assertFalse(observer.called)

        # Verify proper message was given to the user.
        self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_actions_are_interrupted(self):
        test_model = self.create_model()
        framework = self.create_framework(model=test_model)
        framework._juju_debug_at = ['hook']

        class CustomEvents(ObjectEvents):
            foobar_action = EventSource(charm.ActionEvent)

        publisher = CustomEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.foobar_action, observer.callback_method)
        fake_script(self, 'action-get', "echo {}")

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                with patch.dict(os.environ, {'JUJU_ACTION_NAME': 'foobar'}):
                    publisher.foobar_action.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_internal_events_not_interrupted(self):
        class MyNotifier(Object):
            """Generic notifier for the tests."""
            bar = EventSource(EventBase)

        framework = self.create_framework()
        framework._juju_debug_at = ['hook']

        publisher = MyNotifier(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.bar, observer.callback_method)

        with patch('pdb.runcall') as mock:
            publisher.bar.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_envvar_mixed(self):
        framework = self.create_framework()
        framework._juju_debug_at = ['foo', 'hook', 'all', 'whatever']

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_no_registered_method(self):
        framework = self.create_framework()
        framework._juju_debug_at = ['hook']

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")

        with patch('pdb.runcall') as mock:
            publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertFalse(observer.called)

    def test_envvar_nohook(self):
        framework = self.create_framework()
        framework._juju_debug_at = ['something-else']

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'something-else'}):
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_envvar_missing(self):
        framework = self.create_framework()
        framework._juju_debug_at = ()

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('pdb.runcall') as mock:
            publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_welcome_message_not_multiple(self):
        framework = self.create_framework()
        framework._juju_debug_at = ['hook']

        publisher = charm.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO) as fake_stderr:
            with patch('pdb.runcall') as mock:
                publisher.install.emit()
                self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
                publisher.install.emit()
                self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
        self.assertEqual(mock.call_count, 2)
