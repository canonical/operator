#!/usr/bin/python3

import unittest
import tempfile
import shutil

from pathlib import Path

from juju.framework import Framework, Handle, Event, EventBase, Object, NoSnapshotError


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
            self.assertEqual(str(e), "no snapshot data found for a_foo:some_key object")
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


if __name__ == "__main__":
    unittest.main()
