import pytest
from ops.charm import CharmBase
from ops.framework import Framework
from ops.framework import StoredState as ops_storedstate

from scenario.state import State, StoredState
from tests.helpers import trigger


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        META = {"name": "mycharm"}

        _read = {}
        _stored = ops_storedstate()
        _stored2 = ops_storedstate()

        def __init__(self, framework: Framework):
            super().__init__(framework)
            self._stored.set_default(foo="bar", baz={12: 142})
            self._stored2.set_default(foo="bar", baz={12: 142})
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            self._read["foo"] = self._stored.foo
            self._read["baz"] = self._stored.baz

    return MyCharm


def test_stored_state_default(mycharm):
    out = trigger(State(), "start", mycharm, meta=mycharm.META)
    assert out.stored_state[0].content == {"foo": "bar", "baz": {12: 142}}


def test_stored_state_initialized(mycharm):
    out = trigger(
        State(
            stored_state=[
                StoredState(
                    owner_path="MyCharm", name="_stored", content={"foo": "FOOX"}
                ),
            ]
        ),
        "start",
        mycharm,
        meta=mycharm.META,
    )
    # todo: ordering is messy?
    assert out.stored_state[1].content == {"foo": "FOOX", "baz": {12: 142}}
    assert out.stored_state[0].content == {"foo": "bar", "baz": {12: 142}}


def test_positional_arguments():
    with pytest.raises(TypeError):
        StoredState("_stored", "")


def test_default_arguments():
    s = StoredState()
    assert s.name == "_stored"
    assert s.owner_path == None
    assert s.content == {}
    assert s._data_type_name == "StoredStateData"
