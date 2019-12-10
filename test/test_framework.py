#!/usr/bin/python3

import unittest
import tempfile
import shutil
import gc

from pathlib import Path

from ops.framework import (
    Framework, Handle, Event, EventsBase, EventBase, Object, PreCommitEvent, CommitEvent,
    NoSnapshotError, StoredState, StoredList, BoundStoredState, StoredStateData
)


class TestFramework(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir)

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

    def test_bad_sig_observer(self):

        class MyEvent(EventBase):
            pass

        class MyNotifier(Object):
            foo = Event(MyEvent)
            bar = Event(MyEvent)
            baz = Event(MyEvent)
            qux = Event(MyEvent)

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

    def test_weak_observer(self):
        framework = self.create_framework()

        observed_events = []

        class MyEvent(EventBase):
            pass

        class MyEvents(EventsBase):
            foo = Event(MyEvent)

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
            foo = Event(MyEvent)

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


class TestStoredState(unittest.TestCase):

    def setUp(self):
        self.tmpdir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmpdir)

    def create_framework(self):
        framework = Framework(self.tmpdir / "framework.data", self.tmpdir, None, None)
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
            self.assertEqual(str(e), 'attribute \'foo\' cannot be set to CustomObject: must be int/dict/list/etc')
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

        # Validate correctness of modification operations.
        for get_a, b, expected_res, op, validate_op in test_operations:
            framework = self.create_framework()
            obj = SomeObject(framework, '1')

            obj.state.a = get_a()
            self.assertTrue(isinstance(obj.state, BoundStoredState))

            op(obj.state.a, b)
            validate_op(obj.state.a, expected_res)

            obj.state.a = get_a()
            framework.commit()

            obj_copy1 = SomeObject(framework, '1')
            self.assertEqual(obj_copy1.state.a, get_a())

            op(obj_copy1.state.a, b)
            validate_op(obj_copy1.state.a, expected_res)

            framework.commit()

            framework_copy = self.create_framework()

            obj_copy2 = SomeObject(framework_copy, '1')

            validate_op(obj_copy2.state.a, expected_res)

            # Validate the dirty state functionality.
            # obj_copy2 state is not dirty because it was not modified in any supported way since the last commit so
            # it still contains the old value at this point. State is overridden here via save_snapshot to validate that
            # the modification will not be saved when StoredStateData is not dirty. This check assumes that the artificially
            # created StoredStateData does not observe the on_commit event.
            framework_copy.save_snapshot(StoredStateData(obj_copy2, 'state'))
            framework_copy.commit()

            obj_copy3 = SomeObject(framework_copy, '1')

            # Now make sure that the modification was not saved as the state holding it was not dirty.
            with self.assertRaises(AttributeError):
                obj_copy3.state.a

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

        for a, b, op, op_ab, op_ba in test_operations:
            obj = SomeObject(framework, "1")
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
        for variable_operand, operation, ab_res, ba_res in test_operations:
            obj = SomeObject(framework, "2")
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


if __name__ == "__main__":
    unittest.main()
