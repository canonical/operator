import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, EventSource

from scenario import State


class FooEvent(EventBase):
    pass


@pytest.fixture
def mycharm():
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

    return MyCharm


def test_custom_event_emitted(mycharm):
    State().trigger("foo", mycharm, meta=mycharm.META)
    assert mycharm._foo_called
