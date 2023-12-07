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
import re
import shutil
import sys
import tempfile
import typing
from pathlib import Path
from test.test_helpers import BaseTestCase, fake_script
from unittest.mock import patch

import ops
from ops.framework import _BREAKPOINT_WELCOME_MESSAGE, _event_regex
from ops.storage import JujuStorage, NoSnapshotError, SQLiteStorage


class TestFramework(BaseTestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

        patcher = patch('ops.storage.SQLiteStorage.DB_LOCK_TIMEOUT', datetime.timedelta(0))
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_deprecated_init(self):
        # For 0.7, this still works, but it is deprecated.
        with self.assertLogs(level="WARNING") as cm:
            framework = ops.Framework(':memory:', None, None, None)  # type: ignore
        self.assertIn(
            "WARNING:ops.framework:deprecated: Framework now takes a Storage not a path",
            cm.output)
        self.assertIsInstance(framework._storage, SQLiteStorage)

    def test_handle_path(self):
        cases = [
            (ops.Handle(None, "root", None), "root"),
            (ops.Handle(None, "root", "1"), "root[1]"),
            (ops.Handle(ops.Handle(None, "root", None), "child", None), "root/child"),
            (ops.Handle(ops.Handle(None, "root", "1"), "child", "2"), "root[1]/child[2]"),
        ]
        for handle, path in cases:
            self.assertEqual(str(handle), path)
            self.assertEqual(ops.Handle.from_path(path), handle)

    def test_handle_attrs_readonly(self):
        handle = ops.Handle(None, 'kind', 'key')
        with self.assertRaises(AttributeError):
            handle.parent = 'foo'  # type: ignore
        with self.assertRaises(AttributeError):
            handle.kind = 'foo'  # type: ignore
        with self.assertRaises(AttributeError):
            handle.key = 'foo'  # type: ignore
        with self.assertRaises(AttributeError):
            handle.path = 'foo'  # type: ignore

    def test_restore_unknown(self):
        framework = self.create_framework()

        class Foo(ops.Object):
            pass

        handle = ops.Handle(None, "a_foo", "some_key")

        framework.register_type(Foo, None, handle.kind)  # type: ignore

        try:
            framework.load_snapshot(handle)
        except NoSnapshotError as e:
            self.assertEqual(e.handle_path, str(handle))
            self.assertEqual(str(e), "no snapshot data found for a_foo[some_key] object")
        else:
            self.fail("exception NoSnapshotError not raised")

    def test_snapshot_roundtrip(self):
        class Foo:
            handle_kind = 'foo'

            def __init__(self, handle: ops.Handle, n: int):
                self.handle = handle
                self.my_n = n

            def snapshot(self) -> typing.Dict[str, int]:
                return {"My N!": self.my_n}

            def restore(self, snapshot: typing.Dict[str, int]):
                self.my_n = snapshot["My N!"] + 1

        handle = ops.Handle(None, "a_foo", "some_key")
        event = Foo(handle, 1)

        framework1 = self.create_framework(tmpdir=self.tmpdir)
        framework1.register_type(Foo, None, handle.kind)
        framework1.save_snapshot(event)  # type: ignore
        framework1.commit()
        framework1.close()

        framework2 = self.create_framework(tmpdir=self.tmpdir)
        framework2.register_type(Foo, None, handle.kind)
        event2 = framework2.load_snapshot(handle)
        event2 = typing.cast(Foo, event2)
        self.assertEqual(event2.my_n, 2)

        framework2.save_snapshot(event2)  # type: ignore
        del event2
        gc.collect()
        event3 = framework2.load_snapshot(handle)
        event3 = typing.cast(Foo, event3)
        self.assertEqual(event3.my_n, 3)

        framework2.drop_snapshot(event.handle)
        framework2.commit()
        framework2.close()

        framework3 = self.create_framework(tmpdir=self.tmpdir)
        framework3.register_type(Foo, None, handle.kind)

        self.assertRaises(NoSnapshotError, framework3.load_snapshot, handle)

    def test_simple_event_observer(self):
        framework = self.create_framework()

        class MyEvent(ops.EventBase):
            pass

        class MyNotifier(ops.Object):
            foo = ops.EventSource(MyEvent)
            bar = ops.EventSource(MyEvent)
            baz = ops.EventSource(MyEvent)

        class MyObserver(ops.Object):
            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[str] = []
                self.reprs: typing.List[str] = []

            def on_any(self, event: ops.EventBase):
                self.seen.append(f"on_any:{event.handle.kind}")
                self.reprs.append(repr(event))

            def on_foo(self, event: ops.EventBase):
                self.seen.append(f"on_foo:{event.handle.kind}")
                self.reprs.append(repr(event))

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.foo, obs.on_any)
        framework.observe(pub.bar, obs.on_any)

        with self.assertRaisesRegex(RuntimeError, "^Framework.observe requires a method"):
            framework.observe(pub.baz, obs)  # type: ignore

        pub.foo.emit()
        pub.bar.emit()

        self.assertEqual(obs.seen, ["on_any:foo", "on_any:bar"])
        self.assertEqual(obs.reprs, [
            "<MyEvent via MyNotifier[1]/foo[1]>",
            "<MyEvent via MyNotifier[1]/bar[2]>",
        ])

    def test_bad_sig_observer(self):

        class MyEvent(ops.EventBase):
            pass

        class MyNotifier(ops.Object):
            foo = ops.EventSource(MyEvent)
            bar = ops.EventSource(MyEvent)
            baz = ops.EventSource(MyEvent)
            qux = ops.EventSource(MyEvent)

        class MyObserver(ops.Object):
            def _on_foo(self):
                assert False, 'should not be reached'

            def _on_bar(self, event: ops.EventBase, extra: typing.Any):
                assert False, 'should not be reached'

            def _on_baz(self,
                        event: ops.EventBase,
                        extra: typing.Optional[typing.Any] = None,
                        *,
                        k: typing.Any):
                assert False, 'should not be reached'

            def _on_qux(self, event: ops.EventBase, extra: typing.Optional[typing.Any] = None):
                assert False, 'should not be reached'

        framework = self.create_framework()
        pub = MyNotifier(framework, "pub")
        obs = MyObserver(framework, "obs")

        with self.assertRaisesRegex(TypeError, "must accept event parameter"):
            framework.observe(pub.foo, obs._on_foo)  # type: ignore
        with self.assertRaisesRegex(TypeError, "has extra required parameter"):
            framework.observe(pub.bar, obs._on_bar)  # type: ignore
        with self.assertRaisesRegex(TypeError, "has extra required parameter"):
            framework.observe(pub.baz, obs._on_baz)  # type: ignore
        framework.observe(pub.qux, obs._on_qux)

    def test_on_pre_commit_emitted(self):
        framework = self.create_framework(tmpdir=self.tmpdir)

        class PreCommitObserver(ops.Object):

            _stored = ops.StoredState()

            def __init__(self, parent: ops.Object, key: typing.Optional[str]):
                super().__init__(parent, key)
                self.seen: typing.List[typing.Any] = []
                self._stored.myinitdata = 40

            def on_pre_commit(self, event: ops.PreCommitEvent):
                self._stored.myinitdata = 41
                self._stored.mydata = 42
                self.seen.append(type(event))

            def on_commit(self, event: ops.CommitEvent):
                # Modifications made here will not be persisted.
                self._stored.myinitdata = 42
                self._stored.mydata = 43
                self._stored.myotherdata = 43
                self.seen.append(type(event))

        obs = PreCommitObserver(framework, None)

        framework.observe(framework.on.pre_commit, obs.on_pre_commit)

        framework.commit()

        self.assertEqual(obs._stored.myinitdata, 41)  # type: ignore
        self.assertEqual(obs._stored.mydata, 42)  # type: ignore
        self.assertTrue(obs.seen, [ops.PreCommitEvent, ops.CommitEvent])
        framework.close()

        other_framework = self.create_framework(tmpdir=self.tmpdir)

        new_obs = PreCommitObserver(other_framework, None)

        self.assertEqual(obs._stored.myinitdata, 41)  # type: ignore
        self.assertEqual(new_obs._stored.mydata, 42)  # type: ignore

        with self.assertRaises(AttributeError):
            new_obs._stored.myotherdata  # type: ignore

    def test_defer_and_reemit(self):
        framework = self.create_framework()

        class MyEvent(ops.EventBase):
            pass

        class MyNotifier1(ops.Object):
            a = ops.EventSource(MyEvent)
            b = ops.EventSource(MyEvent)

        class MyNotifier2(ops.Object):
            c = ops.EventSource(MyEvent)

        class MyObserver(ops.Object):
            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[str] = []
                self.done: typing.Dict[str, bool] = {}

            def on_any(self, event: ops.EventBase):
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
        ev_a_handle = ops.Handle(pub1, "a", "1")
        framework.load_snapshot(ev_a_handle)
        ev_b_handle = ops.Handle(pub1, "b", "2")
        framework.load_snapshot(ev_b_handle)
        ev_c_handle = ops.Handle(pub2, "c", "3")
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

        class MyEvent(ops.EventBase):
            def __init__(self, handle: ops.Handle, n: int):
                super().__init__(handle)
                self.my_n = n

            def snapshot(self):
                return {"My N!": self.my_n}

            def restore(self, snapshot: typing.Dict[str, typing.Any]):
                super().restore(snapshot)
                self.my_n = snapshot["My N!"] + 1

        class MyNotifier(ops.Object):
            foo = ops.EventSource(MyEvent)

        class MyObserver(ops.Object):
            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[str] = []

            def _on_foo(self, event: MyEvent):
                self.seen.append(f"on_foo:{event.handle.kind}={event.my_n}")
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

        observed_events: typing.List[str] = []

        class MyEvent(ops.EventBase):
            pass

        class MyEvents(ops.ObjectEvents):
            foo = ops.EventSource(MyEvent)

        class MyNotifier(ops.Object):
            on = MyEvents()  # type: ignore

        class MyObserver(ops.Object):
            def _on_foo(self, event: ops.EventBase):
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

        class MyObject(ops.Object):
            def snapshot(self) -> typing.Dict[str, typing.Any]:
                raise NotImplementedError()

            def restore(self, snapshot: typing.Dict[str, typing.Any]) -> None:
                raise NotImplementedError()

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

        class MyObject(ops.Object):
            def __init__(self, parent: ops.Object, name: str):
                super().__init__(parent, name)
                self.value = name

            def snapshot(self):
                return {"value": self.value}

            def restore(self, snapshot: typing.Dict[str, typing.Any]):
                self.value = snapshot["value"]

        framework.register_type(MyObject, None, MyObject.handle_kind)
        o1 = MyObject(framework, "path")
        framework.save_snapshot(o1)  # type: ignore
        framework.commit()
        o_handle = o1.handle
        del o1
        gc.collect()
        o2 = framework.load_snapshot(o_handle)
        o2 = typing.cast(MyObject, o2)
        # Trying to load_snapshot a second object at the same path should fail with RuntimeError
        with self.assertRaises(RuntimeError):
            framework.load_snapshot(o_handle)
        # Unless we _forget the object first
        framework._forget(o2)
        o3 = framework.load_snapshot(o_handle)
        o3 = typing.cast(MyObject, o3)
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
        o_copy2 = typing.cast(MyObject, o_copy2)
        self.assertEqual(o_copy2.value, "path")

    def test_events_base(self):
        framework = self.create_framework()

        class MyEvent(ops.EventBase):
            pass

        class MyEvents(ops.ObjectEvents):
            foo = ops.EventSource(MyEvent)
            bar = ops.EventSource(MyEvent)

        class MyNotifier(ops.Object):
            on = MyEvents()  # type: ignore

        class MyObserver(ops.Object):
            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[str] = []

            def _on_foo(self, event: ops.EventBase):
                self.seen.append(f"on_foo:{event.handle.kind}")
                event.defer()

            def _on_bar(self, event: ops.EventBase):
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
        class MyEvent(ops.EventBase):
            pass

        event = ops.EventSource(MyEvent)

        class MyEvents(ops.ObjectEvents):
            foo = event

        with self.assertRaises(RuntimeError) as cm:
            class OtherEvents(ops.ObjectEvents):  # type: ignore
                foo = event
        # Python 3.12+ raises the original exception with a note, but earlier
        # Python chains the exceptions.
        if hasattr(cm.exception, "__notes__"):
            cause = str(cm.exception)
        else:
            cause = str(cm.exception.__cause__)
        self.assertEqual(
            cause,
            "EventSource(MyEvent) reused as MyEvents.foo and OtherEvents.foo")

        with self.assertRaises(RuntimeError) as cm:
            class MyNotifier(ops.Object):  # type: ignore
                on = MyEvents()  # type: ignore
                bar = event
        if hasattr(cm.exception, "__notes__"):
            cause = str(cm.exception)
        else:
            cause = str(cm.exception.__cause__)
        self.assertEqual(
            cause,
            "EventSource(MyEvent) reused as MyEvents.foo and MyNotifier.bar")

    def test_reemit_ignores_unknown_event_type(self):
        # The event type may have been gone for good, and nobody cares,
        # so this shouldn't be an error scenario.

        framework = self.create_framework()

        class MyEvent(ops.EventBase):
            handle_kind = "test"

        class MyNotifier(ops.Object):
            foo = ops.EventSource(MyEvent)

        class MyObserver(ops.Object):
            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[typing.Any] = []

            def _on_foo(self, event: ops.EventBase):
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

        class MyFoo(ops.EventBase):
            pass

        class MyBar(ops.EventBase):
            pass

        class MyEvents(ops.ObjectEvents):
            foo = ops.EventSource(MyFoo)

        class MyNotifier(ops.Object):
            on = MyEvents()  # type: ignore
            bar = ops.EventSource(MyBar)

        class MyObserver(ops.Object):
            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[str] = []

            def _on_foo(self, event: ops.EventBase):
                self.seen.append(f"on_foo:{type(event).__name__}:{event.handle.kind}")
                event.defer()

            def _on_bar(self, event: ops.EventBase):
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

        class MyEventsA(ops.ObjectEvents):
            handle_kind = 'on_a'

        class MyEventsB(ops.ObjectEvents):
            handle_kind = 'on_b'

        class MyNotifier(ops.Object):
            on_a = MyEventsA()
            on_b = MyEventsB()

        class MyObserver(ops.Object):
            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[str] = []

            def _on_foo(self, event: ops.EventBase):
                self.seen.append(f"on_foo:{type(event).__name__}:{event.handle.kind}")
                event.defer()

            def _on_bar(self, event: ops.EventBase):
                self.seen.append(f"on_bar:{type(event).__name__}:{event.handle.kind}")
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        class MyFoo(ops.EventBase):
            pass

        class MyBar(ops.EventBase):
            pass

        class DeadBeefEvent(ops.EventBase):
            pass

        class NoneEvent(ops.EventBase):
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
        class MyEvent(ops.EventBase):
            def __init__(self, handle: ops.Handle, value: typing.Any):
                super().__init__(handle)
                self.value = value

            def snapshot(self):
                return self.value

            def restore(self, value: typing.Any):
                self.value = value

        class MyNotifier(ops.Object):
            foo = ops.EventSource(MyEvent)

        class MyObserver(ops.Object):
            has_deferred = False

            def __init__(self, parent: ops.Object, key: str):
                super().__init__(parent, key)
                self.seen: typing.List[typing.Any] = []

            def _on_foo(self, event: MyEvent):
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
        framework.model = 'test-model'  # type: ignore
        framework.meta = 'test-meta'  # type: ignore

        my_obj = ops.Object(framework, 'my_obj')
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

        class FooEvent(ops.EventBase):
            handle_kind = "test"

            def snapshot(self):
                return to_be_saved

        handle = ops.Handle(None, "a_foo", "some_key")
        event = FooEvent(handle)

        framework = self.create_framework()
        framework.register_type(FooEvent, None, handle.kind)
        with self.assertRaises(ValueError) as cm:
            framework.save_snapshot(event)
        expected = (
            "unable to save the data for FooEvent, it must contain only simple types: "
            "{'bar': <class 'test.test_framework.TestFramework'>}")
        self.assertEqual(str(cm.exception), expected)

    def test_unobserved_events_dont_leave_cruft(self):
        class FooEvent(ops.EventBase):
            def snapshot(self):
                return {'content': 1}

        class Events(ops.ObjectEvents):
            foo = ops.EventSource(FooEvent)

        class Emitter(ops.Object):
            on = Events()  # type: ignore

        framework = self.create_framework()
        e = Emitter(framework, 'key')
        e.on.foo.emit()
        ev_1_handle = ops.Handle(e.on, "foo", "1")
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

        class Evt(ops.EventBase):
            pass

        class Events(ops.ObjectEvents):
            event = ops.EventSource(Evt)

        class ObjectWithStorage(ops.Object):
            _stored = ops.StoredState()
            on = Events()  # type: ignore

            def __init__(self, framework: ops.Framework, key: str):
                super().__init__(framework, key)
                self._stored.set_default(foo=2)
                self.framework.observe(self.on.event, self._on_event)

            def _on_event(self, event: ops.EventBase):
                event.defer()

        # This is an event that 'happened in the past' that doesn't have an associated notice.
        o = ObjectWithStorage(framework, 'obj')
        handle = ops.Handle(o.on, 'event', '100')
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


class TestStoredState(BaseTestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(self.tmpdir))

    def test_stored_dict_repr(self):
        self.assertEqual(repr(ops.StoredDict(None, {})),  # type: ignore
                         "ops.framework.StoredDict()")
        self.assertEqual(repr(ops.StoredDict(None, {"a": 1})),  # type: ignore
                         "ops.framework.StoredDict({'a': 1})")

    def test_stored_list_repr(self):
        self.assertEqual(repr(ops.StoredList(None, [])),  # type: ignore
                         "ops.framework.StoredList()")
        self.assertEqual(repr(ops.StoredList(None, [1, 2, 3])),  # type: ignore
                         'ops.framework.StoredList([1, 2, 3])')

    def test_stored_set_repr(self):
        self.assertEqual(repr(ops.StoredSet(None, set())),  # type: ignore
                         'ops.framework.StoredSet()')
        self.assertEqual(repr(ops.StoredSet(None, {1})),  # type: ignore
                         'ops.framework.StoredSet({1})')

    def test_basic_state_storage(self):
        class SomeObject(ops.Object):
            _stored = ops.StoredState()

        self._stored_state_tests(SomeObject)

    def test_straight_subclass(self):
        class SomeObject(ops.Object):
            _stored = ops.StoredState()

        class Sub(SomeObject):
            pass

        self._stored_state_tests(Sub)

    def test_straight_sub_subclass(self):
        class SomeObject(ops.Object):
            _stored = ops.StoredState()

        class Sub(SomeObject):
            pass

        class SubSub(Sub):
            pass

        self._stored_state_tests(SubSub)

    def test_two_subclasses(self):
        class SomeObject(ops.Object):
            _stored = ops.StoredState()

        class SubA(SomeObject):
            pass

        class SubB(SomeObject):
            pass

        self._stored_state_tests(SubA)
        self._stored_state_tests(SubB)

    def test_the_crazy_thing(self):
        class NoState(ops.Object):
            pass

        class StatedObject(NoState):
            _stored = ops.StoredState()

        class Sibling(NoState):
            pass

        class FinalChild(StatedObject, Sibling):
            pass

        self._stored_state_tests(FinalChild)

    def _stored_state_tests(self, cls: typing.Type[ops.Object]):
        @typing.runtime_checkable
        class _StoredProtocol(typing.Protocol):
            _stored: ops.StoredState

        framework = self.create_framework(tmpdir=self.tmpdir)
        obj = cls(framework, "1")
        assert isinstance(obj, _StoredProtocol)

        try:
            obj._stored.foo  # type: ignore
        except AttributeError as e:
            self.assertEqual(str(e), "attribute 'foo' is not stored")
        else:
            self.fail("AttributeError not raised")

        try:
            obj._stored.on = "nonono"  # type: ignore
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
        assert isinstance(obj_copy, _StoredProtocol)
        self.assertEqual(obj_copy._stored.foo, 42)
        self.assertEqual(obj_copy._stored.bar, "s")
        self.assertEqual(obj_copy._stored.baz, 4.2)
        self.assertEqual(obj_copy._stored.bing, True)

        framework_copy.close()

    def test_two_subclasses_no_conflicts(self):
        class Base(ops.Object):
            _stored = ops.StoredState()

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
        class Mine(ops.Object):
            _stored = ops.StoredState()
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
        class Base(ops.Object):
            pass

        class A(Base):
            _stored = ops.StoredState()

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

        class SomeObject(ops.Object):
            _stored = ops.StoredState()

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
        # Test and validation functions in a list of tuples.
        # Assignment and keywords like del are not supported in lambdas
        #  so functions are used instead.
        test_case = typing.Tuple[
            typing.Callable[[], typing.Any],                        # Called to get operand A.
            typing.Any,                                             # Operand B.
            typing.Any,                                             # Expected result.
            typing.Callable[[typing.Any, typing.Any], None],        # Operation to perform.
            typing.Callable[[typing.Any, typing.Any], typing.Any],  # Validation to perform.
        ]
        test_operations: typing.List[test_case] = [(
            lambda: {},
            None,
            {},
            lambda a, b: None,
            lambda res, expected_res: self.assertEqual(res, expected_res)
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
            lambda: {'s': set()},  # type: ignore
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
                self.assertIsInstance(res[1], ops.StoredList),
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
                self.assertIsInstance(res[1], ops.StoredList)
            ),
        ), (
            lambda: ['b', 'a', ['c']],
            ['d'],
            ['b', ['d'], ['c']],
            # a[1] = b
            lambda a, b: a.__setitem__(1, b),
            lambda res, expected_res: (
                self.assertEqual(res, expected_res),
                self.assertIsInstance(res[1], ops.StoredList)
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

        class SomeObject(ops.Object):
            _stored = ops.StoredState()

        class WrappedFramework(ops.Framework):
            def __init__(self,
                         store: typing.Union[SQLiteStorage, JujuStorage],
                         charm_dir: typing.Union[str, Path],
                         meta: ops.CharmMeta,
                         model: ops.Model,
                         event_name: str):
                super().__init__(store, charm_dir, meta, model, event_name)
                self.snapshots: typing.List[typing.Any] = []

            def save_snapshot(self, value: typing.Union[ops.StoredStateData, ops.EventBase]):
                if value.handle.path == 'SomeObject[1]/StoredStateData[_stored]':
                    self.snapshots.append((type(value), value.snapshot()))
                return super().save_snapshot(value)

        # Validate correctness of modification operations.
        for get_a, b, expected_res, op, validate_op in test_operations:
            storage = SQLiteStorage(self.tmpdir / "framework.data")
            framework = WrappedFramework(storage, self.tmpdir, None, None, "foo")  # type: ignore
            obj = SomeObject(framework, '1')

            obj._stored.a = get_a()
            self.assertTrue(isinstance(obj._stored, ops.BoundStoredState))

            op(obj._stored.a, b)
            validate_op(obj._stored.a, expected_res)

            obj._stored.a = get_a()
            framework.commit()
            # We should see an update for initializing a
            self.assertEqual(framework.snapshots, [
                (ops.StoredStateData, {'a': get_a()}),
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
            framework_copy = WrappedFramework(
                storage_copy, self.tmpdir, None, None, "foo")  # type: ignore

            obj_copy2 = SomeObject(framework_copy, '1')

            validate_op(obj_copy2._stored.a, expected_res)

            # Commit saves the pre-commit and commit events, and the framework
            # event counter, but shouldn't update the stored state of my object
            framework.snapshots.clear()
            framework_copy.commit()
            self.assertEqual(framework_copy.snapshots, [])
            framework_copy.close()

    def test_comparison_operations(self):
        test_case = typing.Tuple[
            typing.Any,                                       # Operand A.
            typing.Any,                                       # Operand B.
            typing.Callable[[typing.Any, typing.Any], bool],  # Operation to test.
            bool,                                             # Result of op(A, B).
            bool,                                             # Result of op(B, A).
        ]
        test_operations: typing.List[test_case] = [(
            {"1"},
            {"1", "2"},
            lambda a, b: a < b,
            True,
            False,
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

        class SomeObject(ops.Object):
            _stored = ops.StoredState()

        framework = self.create_framework()

        for i, (a, b, op, op_ab, op_ba) in enumerate(test_operations):
            obj = SomeObject(framework, str(i))
            obj._stored.a = a
            self.assertEqual(op(obj._stored.a, b), op_ab)
            self.assertEqual(op(b, obj._stored.a), op_ba)

    def test_set_operations(self):
        test_case = typing.Tuple[
            typing.Set[str],  # A set to test an operation against (other_set).
            # An operation to test.
            typing.Callable[[typing.Set[str], typing.Set[str]], typing.Set[str]],
            typing.Set[str],  # The expected result of operation(obj._stored.set, other_set).
            typing.Set[str],  # The expected result of operation(other_set, obj._stored.set).
        ]
        test_operations: typing.List[test_case] = [(
            {"1"},
            lambda a, b: a | b,
            {"1", "a", "b"},
            {"1", "a", "b"}
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

        class SomeObject(ops.Object):
            _stored = ops.StoredState()

        framework = self.create_framework()

        # Validate that operations between StoredSet and built-in sets
        # only result in built-in sets being returned.
        # Make sure that commutativity is preserved and that the
        # original sets are not changed or used as a result.
        for i, (variable_operand, operation, ab_res, ba_res) in enumerate(test_operations):
            obj = SomeObject(framework, str(i))
            obj._stored.set = {"a", "b"}
            assert isinstance(obj._stored.set, ops.StoredSet)

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

        class StatefulObject(ops.Object):
            _stored = ops.StoredState()
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


class GenericObserver(ops.Object):
    """Generic observer for the tests."""

    def __init__(self, parent: ops.Object, key: str):
        super().__init__(parent, key)
        self.called = False

    def callback_method(self, event: ops.EventBase):
        """Set the instance .called to True."""
        self.called = True


@patch('sys.stderr', new_callable=io.StringIO)
class BreakpointTests(BaseTestCase):

    def test_ignored(self, fake_stderr: io.StringIO):
        # It doesn't do anything really unless proper environment is there.
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            # We want to verify that there are *no* logs at warning level.
            # However, assertNoLogs is Python 3.10+.
            try:
                with self.assertLogs(level="WARNING"):
                    framework.breakpoint()
            except AssertionError:
                pass
            else:
                self.fail("No warning logs should be generated")
        self.assertEqual(mock.call_count, 0)
        self.assertEqual(fake_stderr.getvalue(), "")

    def test_pdb_properly_called(self, fake_stderr: io.StringIO):
        # The debugger needs to leave the user in the frame where the breakpoint is executed,
        # which for the test is the frame we're calling it here in the test :).
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            this_frame = inspect.currentframe()
            framework.breakpoint()

        self.assertEqual(mock.call_count, 1)
        self.assertEqual(mock.call_args, ((this_frame,), {}))

    def test_welcome_message(self, fake_stderr: io.StringIO):
        # Check that an initial message is shown to the user when code is interrupted.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace'):
            framework.breakpoint()
        self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_welcome_message_not_multiple(self, fake_stderr: io.StringIO):
        # Check that an initial message is NOT shown twice if the breakpoint is exercised
        # twice in the same run.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace'):
            framework.breakpoint()
            self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
            framework.breakpoint()
            self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_breakpoint_builtin_sanity(self, fake_stderr: io.StringIO):
        # this just checks that calling breakpoint() works as expected
        # nothing really framework-dependent
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            self.create_framework()

        with patch('pdb.Pdb.set_trace') as mock:
            this_frame = inspect.currentframe()
            breakpoint()

        self.assertEqual(mock.call_count, 1)
        self.assertEqual(mock.call_args, ((this_frame,), {}))

    def test_builtin_breakpoint_hooked(self, fake_stderr: io.StringIO):
        # Verify that the proper hook is set.
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'all'}):
            framework = self.create_framework()
        old_breakpointhook = framework.set_breakpointhook()
        self.addCleanup(setattr, sys, 'breakpointhook', old_breakpointhook)
        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()
        self.assertEqual(mock.call_count, 1)

    def test_breakpoint_builtin_unset(self, fake_stderr: io.StringIO):
        # if no JUJU_DEBUG_AT, no call to pdb is done
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()
        old_breakpointhook = framework.set_breakpointhook()
        self.addCleanup(setattr, sys, 'breakpointhook', old_breakpointhook)

        with patch('pdb.Pdb.set_trace') as mock:
            breakpoint()

        self.assertEqual(mock.call_count, 0)

    def test_breakpoint_names(self, fake_stderr: io.StringIO):
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
                    framework.breakpoint(name)  # type: ignore
                self.assertEqual(str(cm.exception), 'breakpoint names must be strings')

    def check_trace_set(
            self,
            envvar_value: str,
            breakpoint_name: typing.Optional[str],
            call_count: int):
        """Helper to check the diverse combinations of situations."""
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': envvar_value}):
            framework = self.create_framework()
        with patch('pdb.Pdb.set_trace') as mock:
            framework.breakpoint(breakpoint_name)
        self.assertEqual(mock.call_count, call_count)

    def test_unnamed_indicated_all(self, fake_stderr: io.StringIO):
        # If 'all' is indicated, unnamed breakpoints will always activate.
        self.check_trace_set('all', None, 1)

    def test_unnamed_indicated_hook(self, fake_stderr: io.StringIO):
        # Special value 'hook' was indicated, nothing to do with any call.
        self.check_trace_set('hook', None, 0)

    def test_named_indicated_specifically(self, fake_stderr: io.StringIO):
        # Some breakpoint was indicated, and the framework call used exactly that name.
        self.check_trace_set('mybreak', 'mybreak', 1)

    def test_named_indicated_unnamed(self, fake_stderr: io.StringIO):
        # Some breakpoint was indicated, but the framework call was unnamed
        with self.assertLogs(level="WARNING") as cm:
            self.check_trace_set('some-breakpoint', None, 0)
        self.assertEqual(cm.output, [
            "WARNING:ops.framework:Breakpoint None skipped "
            "(not found in the requested breakpoints: {'some-breakpoint'})"
        ])

    def test_named_indicated_somethingelse(self, fake_stderr: io.StringIO):
        # Some breakpoint was indicated, but the framework call was with a different name
        with self.assertLogs(level="WARNING") as cm:
            self.check_trace_set('some-breakpoint', 'other-name', 0)
        self.assertEqual(cm.output, [
            "WARNING:ops.framework:Breakpoint 'other-name' skipped "
            "(not found in the requested breakpoints: {'some-breakpoint'})"])

    def test_named_indicated_ingroup(self, fake_stderr: io.StringIO):
        # A multiple breakpoint was indicated, and the framework call used a name among those.
        self.check_trace_set('some,mybreak,foobar', 'mybreak', 1)

    def test_named_indicated_all(self, fake_stderr: io.StringIO):
        # The framework indicated 'all', which includes any named breakpoint set.
        self.check_trace_set('all', 'mybreak', 1)

    def test_named_indicated_hook(self, fake_stderr: io.StringIO):
        # The framework indicated the special value 'hook', nothing to do with any named call.
        self.check_trace_set('hook', 'mybreak', 0)


class DebugHookTests(BaseTestCase):

    def test_envvar_parsing_missing(self):
        with patch.dict(os.environ):
            os.environ.pop('JUJU_DEBUG_AT', None)
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, set())

    def test_envvar_parsing_empty(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': ''}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, set())

    def test_envvar_parsing_simple(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'hook'}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, {'hook'})

    def test_envvar_parsing_multiple(self):
        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'foo,bar,all'}):
            framework = self.create_framework()
        self.assertEqual(framework._juju_debug_at, {'foo', 'bar', 'all'})

    def test_basic_interruption_enabled(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = ops.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO) as fake_stderr:
            fake_stderr = typing.cast(io.StringIO, fake_stderr)
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        # Check that the pdb module was used correctly and that the callback method was NOT
        # called (as we intercepted the normal pdb behaviour! this is to check that the
        # framework didn't call the callback directly)
        self.assertEqual(mock.call_count, 1)
        expected_callback, expected_event = mock.call_args[0]
        self.assertEqual(expected_callback, observer.callback_method)
        self.assertIsInstance(expected_event, ops.EventBase)
        self.assertFalse(observer.called)

        # Verify proper message was given to the user.
        self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)

    def test_interruption_enabled_with_all(self):
        test_model = self.create_model()
        framework = self.create_framework(model=test_model)
        framework._juju_debug_at = {'all'}

        class CustomEvents(ops.ObjectEvents):
            foobar_action = ops.EventSource(ops.ActionEvent)

        publisher = CustomEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.foobar_action, observer.callback_method)
        fake_script(self, 'action-get', "echo {}")

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                publisher.foobar_action.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_actions_are_interrupted(self):
        test_model = self.create_model()
        framework = self.create_framework(model=test_model)
        framework._juju_debug_at = {'hook'}

        class CustomEvents(ops.ObjectEvents):
            foobar_action = ops.EventSource(ops.ActionEvent)

        publisher = CustomEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.foobar_action, observer.callback_method)
        fake_script(self, 'action-get', "echo {}")

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                publisher.foobar_action.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_internal_events_not_interrupted(self):
        class MyNotifier(ops.Object):
            """Generic notifier for the tests."""
            bar = ops.EventSource(ops.EventBase)

        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = MyNotifier(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.bar, observer.callback_method)

        with patch('pdb.runcall') as mock:
            publisher.bar.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_envvar_mixed(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'foo', 'hook', 'all', 'whatever'}

        publisher = ops.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO):
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        self.assertEqual(mock.call_count, 1)
        self.assertFalse(observer.called)

    def test_no_registered_method(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = ops.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")

        with patch('pdb.runcall') as mock:
            publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertFalse(observer.called)

    def test_envvar_nohook(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'something-else'}

        publisher = ops.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch.dict(os.environ, {'JUJU_DEBUG_AT': 'something-else'}):
            with patch('pdb.runcall') as mock:
                publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_envvar_missing(self):
        framework = self.create_framework()
        framework._juju_debug_at = set()

        publisher = ops.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('pdb.runcall') as mock:
            publisher.install.emit()

        self.assertEqual(mock.call_count, 0)
        self.assertTrue(observer.called)

    def test_welcome_message_not_multiple(self):
        framework = self.create_framework()
        framework._juju_debug_at = {'hook'}

        publisher = ops.CharmEvents(framework, "1")
        observer = GenericObserver(framework, "1")
        framework.observe(publisher.install, observer.callback_method)

        with patch('sys.stderr', new_callable=io.StringIO) as fake_stderr:
            fake_stderr = typing.cast(io.StringIO, fake_stderr)
            with patch('pdb.runcall') as mock:
                publisher.install.emit()
                self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
                publisher.install.emit()
                self.assertEqual(fake_stderr.getvalue(), _BREAKPOINT_WELCOME_MESSAGE)
        self.assertEqual(mock.call_count, 2)
