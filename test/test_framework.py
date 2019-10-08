#!/usr/bin/python3

import unittest
import tempfile
import shutil

from pathlib import Path

from juju.framework import Framework, Handle, Event, EventsBase, EventBase, Object
from juju.framework import NoSnapshotError, StoredState


class TestFramework(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def create_framework(self):
        return Framework(self.tmpdir / "framework.data", model=None)

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

        framework2 = self.create_framework()
        framework2.register_type(Foo, None, handle.kind)
        event2 = framework2.load_snapshot(handle)
        self.assertEqual(event2.my_n, 2)

        framework2.save_snapshot(event2)
        event3 = framework2.load_snapshot(handle)
        self.assertEqual(event3.my_n, 3)

        framework2.drop_snapshot(event.handle)
        framework2.commit()

        framework3 = self.create_framework()
        framework3.register_type(Foo, None, handle.kind)

        self.assertRaises(NoSnapshotError, framework1.load_snapshot, handle)
        self.assertRaises(NoSnapshotError, framework2.load_snapshot, handle)
        self.assertRaises(NoSnapshotError, framework3.load_snapshot, handle)

    def test_simple_event_observer(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyNotifier(Object):
            foo = Event(MyEvent)
            bar = Event(MyEvent)
            baz = Event(MyEvent)

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

    def test_defer_and_reemit(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyNotifier1(Object):
            a = Event(MyEvent)
            b = Event(MyEvent)

        class MyNotifier2(Object):
            c = Event(MyEvent)

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
        ev_a = framework.load_snapshot(Handle(pub1, "a", "1"))
        ev_b = framework.load_snapshot(Handle(pub1, "b", "2"))
        ev_c = framework.load_snapshot(Handle(pub2, "c", "3"))

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
        self.assertRaises(NoSnapshotError, framework.load_snapshot, ev_a.handle)
        self.assertRaises(NoSnapshotError, framework.load_snapshot, ev_b.handle)
        self.assertRaises(NoSnapshotError, framework.load_snapshot, ev_c.handle)

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
            foo = Event(MyEvent)

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

    def test_events_base(self):
        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyEvents(EventsBase):
            foo = Event(MyEvent)

        class MyNotifier(Object):
            on = MyEvents()

        class MyObserver(Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(f"on_foo:{event.handle.kind}")
                event.defer()

        pub = MyNotifier(framework, "1")
        obs = MyObserver(framework, "1")

        framework.observe(pub.on.foo, obs)

        pub.on.foo.emit()

        self.assertEqual(obs.seen, ["on_foo:foo"])

    def test_conflicting_event_attributes(self):
        class MyEvent(EventBase):
            pass

        event = Event(MyEvent)

        class MyEvents(EventsBase):
            foo = event

        with self.assertRaises(RuntimeError) as cm:
            class OtherEvents(EventsBase):
                foo = event
        self.assertEqual(
            str(cm.exception.__cause__),
            "Event(MyEvent) reused as MyEvents.foo and OtherEvents.foo")

        with self.assertRaises(RuntimeError) as cm:
            class MyNotifier(Object):
                on = MyEvents()
                bar = event
        self.assertEqual(
            str(cm.exception.__cause__),
            "Event(MyEvent) reused as MyEvents.foo and MyNotifier.bar")

    def test_reemit_ignores_unknown_event_type(self):
        # The event type may have been gone for good, and nobody cares,
        # so this shouldn't be an error scenario.

        framework = self.create_framework()

        class MyEvent(EventBase):
            pass

        class MyNotifier(Object):
            foo = Event(MyEvent)

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
            foo = Event(MyFoo)

        class MyNotifier(Object):
            on = MyEvents()
            bar = Event(MyBar)

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
            pass

        class MyEventsB(EventsBase):
            pass

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


class TestStoredState(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def create_framework(self):
        return Framework(self.tmpdir / "framework.data", model=None)

    def test_basic_state_storage(self):
        framework = self.create_framework()

        class SomeObject(Object):
            state = StoredState()
            changes = 0

            def __init__(self, parent, key):
                super().__init__(parent, key)

                self.framework.observe(self.state.on.changed, self.on_state_changed)

            def on_state_changed(self, event):
                self.changes += 1
                event.defer()

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
        self.assertEqual(obj.changes, 3)

        framework.commit()

        # This won't be committed, and should not be seen.
        obj.state.foo = 43

        framework.close()

        # Since this has the same absolute object handle, it will get its state back.
        framework_copy = self.create_framework()
        obj_copy = SomeObject(framework_copy, "1")
        self.assertEqual(obj_copy.state.foo, 42)
        self.assertEqual(obj_copy.state.bar, "s")

        # But it has observed no changes since instantiation:
        self.assertEqual(obj_copy.changes, 0)

        # But if we ask for the events to be sent again, it will get them:
        framework_copy.reemit()
        self.assertEqual(obj_copy.changes, 3)

    def test_mutable_types(self):
        framework = self.create_framework()

        class SomeObject(Object):
            state = StoredState()
            changes = 0

            def __init__(self, framework, key):
                super().__init__(framework, key)
                framework.observe(self.state.on.changed, self.on_state_changed)

            def on_state_changed(self, event):
                self.changes += 1

        obj = SomeObject(framework, "1")

        try:
            class CustomObject:
                pass
            obj.state.foo = CustomObject()
        except AttributeError as e:
            self.assertEqual(str(e), "attribute 'foo' cannot be set to CustomObject: must be int/dict/list/etc")
        else:
            self.fail("AttributeError not raised")

        obj.state.dict = {}
        obj.state.dict["a"] = {}
        obj.state.dict["a"]["b"] = "c"
        obj.state.dict["a"]["d"] = "e"
        del obj.state.dict["a"]["d"]

        self.assertEqual(dict(obj.state.dict), {"a": {"b": "c"}})

        self.assertEqual(obj.changes, 5)

        obj.changes = 0

        obj.state.list = []
        obj.state.list.append("a")
        obj.state.list.append("c")
        obj.state.list.insert(1, "b")
        obj.state.list.insert(2, "d")
        del obj.state.list[2]

        self.assertEqual(list(obj.state.list), ["a", "b", "c"])
        self.assertEqual(obj.changes, 6)

        obj.changes = 0

        obj.state.set = set()
        obj.state.set.add("a")
        obj.state.set.add("b")
        obj.state.set.add("c")
        obj.state.set.discard("c")

        self.assertEqual(set(obj.state.set), {"a", "b"})
        self.assertEqual(obj.changes, 5)


if __name__ == "__main__":
    unittest.main()
