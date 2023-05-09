import pytest
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import ActiveStatus, BlockedStatus, UnknownStatus, WaitingStatus

from scenario import trigger
from scenario.state import State, Status


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            pass

    return MyCharm


def test_initial_status(mycharm):
    def post_event(charm: CharmBase):
        assert charm.unit.status == UnknownStatus()

    out = trigger(
        State(leader=True),
        "update_status",
        mycharm,
        meta={"name": "local"},
        post_event=post_event,
    )

    assert out.status.unit == UnknownStatus()


def test_status_history(mycharm):
    def post_event(charm: CharmBase):
        for obj in [charm.unit, charm.app]:
            obj.status = ActiveStatus("1")
            obj.status = BlockedStatus("2")
            obj.status = WaitingStatus("3")

    out = trigger(
        State(leader=True),
        "update_status",
        mycharm,
        meta={"name": "local"},
        post_event=post_event,
    )

    assert out.status.unit == WaitingStatus("3")
    assert out.status.unit_history == [
        UnknownStatus(),
        ActiveStatus("1"),
        BlockedStatus("2"),
    ]

    assert out.status.app == WaitingStatus("3")
    assert out.status.app_history == [
        UnknownStatus(),
        ActiveStatus("1"),
        BlockedStatus("2"),
    ]


def test_status_history_preservation(mycharm):
    def post_event(charm: CharmBase):
        for obj in [charm.unit, charm.app]:
            obj.status = WaitingStatus("3")

    out = trigger(
        State(
            leader=True,
            status=Status(unit=ActiveStatus("foo"), app=ActiveStatus("bar")),
        ),
        "update_status",
        mycharm,
        meta={"name": "local"},
        post_event=post_event,
    )

    assert out.status.unit == WaitingStatus("3")
    assert out.status.unit_history == [ActiveStatus("foo")]

    assert out.status.app == WaitingStatus("3")
    assert out.status.app_history == [ActiveStatus("bar")]
