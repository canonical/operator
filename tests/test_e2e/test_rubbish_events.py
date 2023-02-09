from dataclasses import asdict
from typing import Type

import pytest
from ops.charm import CharmBase, CharmEvents
from ops.framework import EventBase, Framework
from ops.model import ActiveStatus, UnknownStatus, WaitingStatus

from scenario.state import Container, Relation, State, sort_patch


# from tests.setup_tests import setup_tests
#
# setup_tests()  # noqa & keep this on top


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)

    return MyCharm


@pytest.mark.parametrize('evt_name', ('rubbish', 'foo', 'bar', 'kazoo_pebble_ready'))
def test_rubbish_event_raises(mycharm, evt_name):
    with pytest.raises(RuntimeError):
        State().trigger(evt_name, mycharm, meta={"name": "foo"})


@pytest.mark.parametrize('evt_name', ('rubbish', 'foo', 'bar', 'kazoo_pebble_ready'))
def test_rubbish_event_warns(mycharm, evt_name, caplog):
    State().trigger(evt_name, mycharm, meta={"name": "foo"},
                    on_no_event_handler='warn')
    assert caplog.messages[0].startswith(f"Charm has no registered observers for {evt_name!r}.")


@pytest.mark.parametrize('evt_name', ('rubbish', 'foo', 'bar', 'kazoo_pebble_ready'))
def test_rubbish_event_passes(mycharm, evt_name):
    State().trigger(evt_name, mycharm, meta={"name": "foo"},
                    on_no_event_handler='pass')
