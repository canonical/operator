import os
from unittest.mock import MagicMock

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource, Object

from scenario import State
from scenario.ops_main_mock import NoObserverError
from scenario.runtime import InconsistentScenarioError
from tests.helpers import trigger


def test_custom_event_emitted():
    class FooEvent(EventBase):
        pass

    class MyCharmEvents(CharmEvents):
        foo = EventSource(FooEvent)

    class MyCharm(CharmBase):
        META = {"name": "mycharm"}
        on = MyCharmEvents()
        _foo_called = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.framework.observe(self.on.foo, self._on_foo)
            self.framework.observe(self.on.start, self._on_start)

        def _on_foo(self, e):
            MyCharm._foo_called += 1

        def _on_start(self, e):
            self.on.foo.emit()

    trigger(State(), "foo", MyCharm, meta=MyCharm.META)
    assert MyCharm._foo_called == 1

    trigger(State(), "start", MyCharm, meta=MyCharm.META)
    assert MyCharm._foo_called == 2


def test_funky_named_event_emitted():
    class FooRelationChangedEvent(EventBase):
        pass

    class MyCharmEvents(CharmEvents):
        foo_relation_changed = EventSource(FooRelationChangedEvent)

    class MyCharm(CharmBase):
        META = {"name": "mycharm"}
        on = MyCharmEvents()
        _foo_called = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.framework.observe(self.on.foo_relation_changed, self._on_foo)

        def _on_foo(self, e):
            MyCharm._foo_called = True

    # we called our custom event like a builtin one. Trouble!
    with pytest.raises(InconsistentScenarioError):
        trigger(State(), "foo-relation-changed", MyCharm, meta=MyCharm.META)

    assert not MyCharm._foo_called

    os.environ["SCENARIO_SKIP_CONSISTENCY_CHECKS"] = "1"
    trigger(State(), "foo-relation-changed", MyCharm, meta=MyCharm.META)
    assert MyCharm._foo_called
    os.unsetenv("SCENARIO_SKIP_CONSISTENCY_CHECKS")


def test_child_object_event_emitted_no_path_raises():
    class FooEvent(EventBase):
        pass

    class MyObjEvents(CharmEvents):
        foo = EventSource(FooEvent)

    class MyObject(Object):
        my_on = MyObjEvents()

    class MyCharm(CharmBase):
        META = {"name": "mycharm"}
        _foo_called = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.obj = MyObject(self, "child")
            self.framework.observe(self.obj.my_on.foo, self._on_foo)

        def _on_foo(self, e):
            MyCharm._foo_called = True

    with pytest.raises(NoObserverError):
        # this will fail because "foo" isn't registered on MyCharm but on MyCharm.foo
        trigger(State(), "foo", MyCharm, meta=MyCharm.META)
        assert MyCharm._foo_called

    # workaround: we can use pre_event to have Scenario set up the simulation for us and run our
    # test code before it eventually fails. pre_event gets called with the set-up charm instance.
    def pre_event(charm: MyCharm):
        event_mock = MagicMock()
        charm._on_foo(event_mock)
        assert charm.unit.name == "mycharm/0"

    # make sure you only filter out NoObserverError, else if pre_event raises,
    # they will also be caught while you want them to bubble up.
    with pytest.raises(NoObserverError):
        trigger(
            State(),
            "rubbish",  # you can literally put anything here
            MyCharm,
            pre_event=pre_event,
            meta=MyCharm.META,
        )
    assert MyCharm._foo_called


def test_child_object_event():
    class FooEvent(EventBase):
        pass

    class MyObjEvents(CharmEvents):
        foo = EventSource(FooEvent)

    class MyObject(Object):
        my_on = MyObjEvents()

    class MyCharm(CharmBase):
        META = {"name": "mycharm"}
        _foo_called = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.obj = MyObject(self, "child")
            self.framework.observe(self.obj.my_on.foo, self._on_foo)

        def _on_foo(self, e):
            MyCharm._foo_called = True

    trigger(State(), "obj.my_on.foo", MyCharm, meta=MyCharm.META)

    assert MyCharm._foo_called
