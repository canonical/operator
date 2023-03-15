import os

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource

from scenario import State
from scenario.runtime import InconsistentScenarioError


def test_custom_event_emitted():
    class FooEvent(EventBase):
        pass

    class MyCharmEvents(CharmEvents):
        foo = EventSource(FooEvent)

    class MyCharm(CharmBase):
        META = {"name": "mycharm"}
        on = MyCharmEvents()
        _foo_called = False

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.framework.observe(self.on.foo, self._on_foo)

        def _on_foo(self, e):
            MyCharm._foo_called = True

    State().trigger("foo", MyCharm, meta=MyCharm.META)
    assert MyCharm._foo_called


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
        State().trigger("foo-relation-changed", MyCharm, meta=MyCharm.META)

    assert not MyCharm._foo_called

    os.environ["SCENARIO_SKIP_CONSISTENCY_CHECKS"] = "1"
    State().trigger("foo-relation-changed", MyCharm, meta=MyCharm.META)
    assert MyCharm._foo_called
    os.unsetenv("SCENARIO_SKIP_CONSISTENCY_CHECKS")
