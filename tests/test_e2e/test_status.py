import pytest
from ops.charm import CharmBase
from ops.framework import Framework
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    ErrorStatus,
    MaintenanceStatus,
    UnknownStatus,
    WaitingStatus,
)

from scenario import Context
from scenario.state import State, _status_to_entitystatus
from tests.helpers import trigger


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

    assert out.unit_status == UnknownStatus()


def test_status_history(mycharm):
    def post_event(charm: CharmBase):
        for obj in [charm.unit, charm.app]:
            obj.status = ActiveStatus("1")
            obj.status = BlockedStatus("2")
            obj.status = WaitingStatus("3")

    ctx = Context(
        mycharm,
        meta={"name": "local"},
    )

    out = ctx.run(
        "update_status",
        State(leader=True),
        post_event=post_event,
    )

    assert out.unit_status == WaitingStatus("3")
    assert ctx.unit_status_history == [
        UnknownStatus(),
        ActiveStatus("1"),
        BlockedStatus("2"),
    ]

    assert out.app_status == WaitingStatus("3")
    assert ctx.app_status_history == [
        UnknownStatus(),
        ActiveStatus("1"),
        BlockedStatus("2"),
    ]


def test_status_history_preservation(mycharm):
    def post_event(charm: CharmBase):
        for obj in [charm.unit, charm.app]:
            obj.status = WaitingStatus("3")

    ctx = Context(
        mycharm,
        meta={"name": "local"},
    )

    out = ctx.run(
        "update_status",
        State(
            leader=True,
            unit_status=ActiveStatus("foo"),
            app_status=ActiveStatus("bar"),
        ),
        post_event=post_event,
    )

    assert out.unit_status == WaitingStatus("3")
    assert ctx.unit_status_history == [ActiveStatus("foo")]

    assert out.app_status == WaitingStatus("3")
    assert ctx.app_status_history == [ActiveStatus("bar")]


def test_workload_history(mycharm):
    def post_event(charm: CharmBase):
        charm.unit.set_workload_version("1")
        charm.unit.set_workload_version("1.1")
        charm.unit.set_workload_version("1.2")

    ctx = Context(
        mycharm,
        meta={"name": "local"},
    )

    out = ctx.run(
        "update_status",
        State(
            leader=True,
        ),
        post_event=post_event,
    )

    assert ctx.workload_version_history == ["1", "1.1"]
    assert out.workload_version == "1.2"


@pytest.mark.parametrize(
    "status",
    (
        ActiveStatus("foo"),
        WaitingStatus("bar"),
        BlockedStatus("baz"),
        MaintenanceStatus("qux"),
        ErrorStatus("fiz"),
        UnknownStatus(),
    ),
)
def test_status_comparison(status):
    entitystatus = _status_to_entitystatus(status)
    assert entitystatus == entitystatus == status
    assert isinstance(entitystatus, type(status))
    assert repr(entitystatus) == repr(status)
