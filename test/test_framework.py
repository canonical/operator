#!/usr/bin/python3

import unittest
import tempfile
import shutil

from pathlib import Path

from juju.framework import Framework, Handle, Event, EventsBase, EventBase
from juju.framework import Object, NoSnapshotError, StoredState


class TestFramework(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def create_framework(self):
        return Framework(self.tmpdir / "framework.data")

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
            self.assertEqual(str(e), "no snapshot data found for a_foo.some_key object")
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

        class MyObserver(Object):
            def __init__(self, context):
                super().__init__(context)
                self.seen = []

            def on_any(self, event):
                self.seen.append("on_any:" + event.handle.kind)

            def on_foo(self, event):
                self.seen.append("on_foo:" + event.handle.kind)

        pub = MyNotifier(framework)
        obs = MyObserver(framework)

        framework.observe(pub.foo, obs.on_any)
        framework.observe(pub.bar, obs.on_any)
        framework.observe(pub.foo, obs) # Method name defaults to on_<event kind>.

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
            def __init__(self, context, key):
                super().__init__(context, key)
                self.seen = []
                self.done = {}

            def on_any(self, event):
                self.seen.append(event.handle.kind)
                if not self.done.get(event.handle.kind):
                    event.defer()

        pub1 = MyNotifier1(framework)
        pub2 = MyNotifier2(framework)
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
            def __init__(self, context):
                super().__init__(context)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(f"on_foo:{event.handle.kind}={event.my_n}")
                event.defer()

        pub = MyNotifier(framework)
        obs = MyObserver(framework)

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
            def __init__(self, context):
                super().__init__(context)
                self.seen = []

            def on_foo(self, event):
                self.seen.append(f"on_foo:{event.handle.kind}")
                event.defer()

        pub = MyNotifier(framework)
        obs = MyObserver(framework)

        framework.observe(pub.on.foo, obs)

        pub.on.foo.emit()

        self.assertEqual(obs.seen, ["on_foo:foo"])

    def test_conflicting_event_attributes(self):
        framework = self.create_framework()

        # The reuse of event attributes across different type hierarchies as done here
        # is strongly discouraged and might eventually be unsupported altogether, but
        # we handle it correctly since the bug might go unnoticed and create very
        # awkward behavior.

        class MyEvent(EventBase):
            pass

        event = Event(MyEvent)

        class MyEvents(EventsBase):
            foo = event

        class MyNotifier(Object):
            on = MyEvents()
            bar = event

        class MyObserver(Object):
            def __init__(self, context):
                super().__init__(context)
                self.seen = []

            def on_foo(self, event): self.seen.append(f"on_foo:{event.handle.kind}")
            def on_bar(self, event): self.seen.append(f"on_bar:{event.handle.kind}")

        pub = MyNotifier(framework)
        obs = MyObserver(framework)

        framework.observe(pub.on.foo, obs)
        framework.observe(pub.bar, obs)

        pub.on.foo.emit()
        pub.bar.emit()

        self.assertEqual(obs.seen, ["on_foo:foo", "on_bar:bar"])

        # The case where the same value is part of the same hierarchy is completely
        # unsupported, though, and is detected to prevent awkward bugs.

        class Ambiguous(EventsBase):
            one = event
        class SubAmbiguous(Ambiguous):
            two = event

        try:
            SubAmbiguous.two
        except RuntimeError as e:
            self.assertEqual(str(e), "Event(MyEvent) shared between SubAmbiguous.two and Ambiguous.one")
        else:
            self.fail("RuntimeError not raised")


class TestStoredState(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def create_framework(self):
        return Framework(self.tmpdir / "framework.data")

    def test_basic_state_storage(self):
        framework = self.create_framework()

        class SomeObject(Object):
            state = StoredState()
            changes = 0

            def __init__(self, framework):
                super().__init__(framework)

                framework.observe(self.state.on.changed, self.on_state_changed)

            def on_state_changed(self, event):
                self.changes += 1
                event.defer()

        obj = SomeObject(framework)

        try:
            obj.state.foo
        except AttributeError as e:
            self.assertEqual(str(e), "SomeObject.state has no 'foo' attribute stored")
        else:
            self.fail("AttributeError not raised")

        try:
            obj.state.on = "nonono"
        except AttributeError as e:
            self.assertEqual(str(e), "SomeObject.state attempting to set reserved 'on' attribute")
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
        obj_copy = SomeObject(framework_copy)
        self.assertEqual(obj_copy.state.foo, 42)
        self.assertEqual(obj_copy.state.bar, "s")

        # But it has observed no changes since instantiation:
        self.assertEqual(obj_copy.changes, 0)

        # But if we ask for the events to be sent again, it will get them:
        framework_copy.reemit()
        self.assertEqual(obj_copy.changes, 3)


if __name__ == "__main__":
    unittest.main()
