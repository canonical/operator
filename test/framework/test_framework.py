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

import datetime
import gc
import re
import shutil
import tempfile
from pathlib import Path
from test.test_helpers import BaseTestCase
from unittest.mock import patch

import logassert

from ops.framework import (
    CommitEvent,
    EventBase,
    EventSource,
    Framework,
    Handle,
    Object,
    ObjectEvents,
    PreCommitEvent,
    StoredState,
    _event_regex,
)
from ops.storage import NoSnapshotError, SQLiteStorage


class TestFramework(BaseTestCase):
    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

        patcher = patch('ops.storage.SQLiteStorage.DB_LOCK_TIMEOUT', datetime.timedelta(0))
        patcher.start()
        self.addCleanup(patcher.stop)
        logassert.setup(self, 'ops')

    def test_deprecated_init(self):
        # For 0.7, this still works, but it is deprecated.
        framework = Framework(':memory:', None, None, None)
        self.assertLoggedWarning(
            "deprecated: Framework now takes a Storage not a path")
        self.assertIsInstance(framework._storage, SQLiteStorage)

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
                self.reprs = []

            def on_any(self, event):
                self.seen.append(f"on_any:{event.handle.kind}")
                self.reprs.append(repr(event))

            def on_foo(self, event):
                self.seen.append(f"on_foo:{event.handle.kind}")
                self.reprs.append(repr(event))

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs.on_any)
        framework.observe(pub.bar, obs.on_any)

        with self.assertRaisesRegex(RuntimeError, "^Framework.observe requires a method"):
            framework.observe(pub.baz, obs)

        pub.foo.emit()
        pub.bar.emit()

        self.assertEqual(obs.seen, ["on_any:foo", "on_any:bar"])
        self.assertEqual(obs.reprs, [
            "<MyEvent via MyNotifier[1]/foo[1]>",
            "<MyEvent via MyNotifier[1]/bar[2]>",
        ])

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
                self.seen.append(f"on_foo:{event.handle.kind}={event.my_n}")
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs._on_foo)

        self.assertNotLogged("Deferring")
        pub.foo.emit(1)
        self.assertLogged("Deferring <MyEvent via MyNotifier[1]/foo[1]>.")
        self.assertNotLogged("Re-emitting")

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
        self.assertLoggedDebug("Re-emitting deferred event <MyEvent via MyNotifier[1]/foo[1]>.")

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
                self.seen.append(f"on_foo:{event.handle.kind}")
                event.defer()

            def _on_bar(self, event):
                self.seen.append(f"on_bar:{event.handle.kind}")

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        # Confirm that temporary persistence of BoundEvents doesn't cause errors,
        # and that events can be observed.
        for bound_event, handler in [(pub.on.foo, obs._on_foo), (pub.on.bar, obs._on_bar)]:
            framework.observe(bound_event, handler)

        # Confirm that events can be emitted and seen.
        pub.on.foo.emit()

        self.assertEqual(obs.seen, ["on_foo:foo"])
        fqn = f"{pub.on.__class__.__module__}.{pub.on.__class__.__qualname__}"
        self.assertEqual(repr(pub.on), f"<{fqn}: bar, foo>")

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
                self.seen.append(f"on_foo:{type(event).__name__}:{event.handle.kind}")
                event.defer()

            def _on_bar(self, event):
                self.seen.append(f"on_bar:{type(event).__name__}:{event.handle.kind}")
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
                self.seen.append(f"on_foo:{type(event).__name__}:{event.handle.kind}")
                event.defer()

            def _on_bar(self, event):
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
            "{'bar': <class 'test.framework.test_framework.TestFramework'>}")
        self.assertEqual(str(cm.exception), expected)

    def test_unobserved_events_dont_leave_cruft(self):
        class FooEvent(EventBase):
            def snapshot(self):
                return {'content': 1}

        class Events(ObjectEvents):
            foo = EventSource(FooEvent)

        class Emitter(Object):
            on = Events()

        framework = self.create_framework()
        e = Emitter(framework, 'key')
        e.on.foo.emit()
        ev_1_handle = Handle(e.on, "foo", "1")
        with self.assertRaises(NoSnapshotError):
            framework.load_snapshot(ev_1_handle)
        # Committing will save the framework's state, but no other snapshots should be saved
        framework.commit()
        events = framework._storage.list_snapshots()
        self.assertEqual(list(events), [framework._stored.handle.path])

    def test_event_regex(self):
        examples = [
            'Ubuntu/on/config_changed[7]',
            'on/commit[9]',
            'on/pre_commit[8]',
        ]
        non_examples = [
            'StoredStateData[_stored]',
            'ObjectWithSTorage[obj]StoredStateData[_stored]',
        ]
        regex = re.compile(_event_regex)
        for e in examples:
            self.assertIsNotNone(regex.match(e))
        for e in non_examples:
            self.assertIsNone(regex.match(e))

    def test_remove_unreferenced_events(self):
        framework = self.create_framework()

        class Evt(EventBase):
            pass

        class Events(ObjectEvents):
            event = EventSource(Evt)

        class ObjectWithStorage(Object):
            _stored = StoredState()
            on = Events()

            def __init__(self, framework, key):
                super().__init__(framework, key)
                self._stored.set_default(foo=2)
                self.framework.observe(self.on.event, self._on_event)

            def _on_event(self, event):
                event.defer()

        # This is an event that 'happened in the past' that doesn't have an associated notice.
        o = ObjectWithStorage(framework, 'obj')
        handle = Handle(o.on, 'event', '100')
        event = Evt(handle)
        framework.save_snapshot(event)
        self.assertEqual(list(framework._storage.list_snapshots()), [handle.path])
        o.on.event.emit()
        self.assertEqual(
            list(framework._storage.notices('')),
            [('ObjectWithStorage[obj]/on/event[1]', 'ObjectWithStorage[obj]', '_on_event')])
        framework.commit()
        self.assertEqual(
            sorted(framework._storage.list_snapshots()),
            sorted(['ObjectWithStorage[obj]/on/event[100]',
                    'StoredStateData[_stored]',
                    'ObjectWithStorage[obj]/StoredStateData[_stored]',
                    'ObjectWithStorage[obj]/on/event[1]']))
        framework.remove_unreferenced_events()
        self.assertEqual(
            sorted(framework._storage.list_snapshots()),
            sorted([
                'StoredStateData[_stored]',
                'ObjectWithStorage[obj]/StoredStateData[_stored]',
                'ObjectWithStorage[obj]/on/event[1]']))
