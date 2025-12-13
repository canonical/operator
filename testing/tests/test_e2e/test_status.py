from __future__ import annotations

import ops
import pytest
from ops.charm import CharmBase
from ops.framework import EventBase, Framework

from scenario import Context
from scenario.state import (
    ActiveStatus,
    BlockedStatus,
    ErrorStatus,
    MaintenanceStatus,
    State,
    UnknownStatus,
    WaitingStatus,
)
from scenario.errors import UncaughtCharmError
from ..helpers import trigger


@pytest.fixture(scope='function')
def mycharm() -> type[CharmBase]:
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event: EventBase) -> None:
            pass

    return MyCharm


def test_initial_status(mycharm: type[CharmBase]) -> None:
    def post_event(charm: CharmBase) -> None:
        assert charm.unit.status == UnknownStatus()

    out = trigger(
        State(leader=True),
        'update_status',
        mycharm,
        meta={'name': 'local'},
        post_event=post_event,
    )

    assert out.unit_status == UnknownStatus()


def test_status_history(mycharm: type[CharmBase]) -> None:
    class StatusCharm(mycharm):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._on_update_status)

        def _on_update_status(self, _: EventBase) -> None:
            for obj in (self.unit, self.app):
                obj.status = ops.ActiveStatus('1')
                obj.status = ops.BlockedStatus('2')
                obj.status = ops.WaitingStatus('3')

    ctx = Context(
        StatusCharm,
        meta={'name': 'local'},
    )

    out = ctx.run(ctx.on.update_status(), State(leader=True))

    assert out.unit_status == WaitingStatus('3')
    assert ctx.unit_status_history == [
        UnknownStatus(),
        ActiveStatus('1'),
        BlockedStatus('2'),
    ]

    assert out.app_status == ops.WaitingStatus('3')
    assert ctx.app_status_history == [
        UnknownStatus(),
        ActiveStatus('1'),
        BlockedStatus('2'),
    ]


def test_status_history_preservation(mycharm: type[CharmBase]) -> None:
    class StatusCharm(mycharm):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._on_update_status)

        def _on_update_status(self, _: EventBase) -> None:
            for obj in (self.unit, self.app):
                obj.status = WaitingStatus('3')

    ctx = Context(
        StatusCharm,
        meta={'name': 'local'},
    )

    out = ctx.run(
        ctx.on.update_status(),
        State(
            leader=True,
            unit_status=ActiveStatus('foo'),
            app_status=ActiveStatus('bar'),
        ),
    )

    assert out.unit_status == WaitingStatus('3')
    assert ctx.unit_status_history == [ActiveStatus('foo')]

    assert out.app_status == WaitingStatus('3')
    assert ctx.app_status_history == [ActiveStatus('bar')]


def test_workload_history(mycharm: type[CharmBase]) -> None:
    class WorkloadCharm(mycharm):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.install, self._on_install)
            framework.observe(self.on.start, self._on_start)
            framework.observe(self.on.update_status, self._on_update_status)

        def _on_install(self, _: EventBase) -> None:
            self.unit.set_workload_version('1')

        def _on_start(self, _: EventBase) -> None:
            self.unit.set_workload_version('1.1')

        def _on_update_status(self, _: EventBase) -> None:
            self.unit.set_workload_version('1.2')

    ctx = Context(
        WorkloadCharm,
        meta={'name': 'local'},
    )

    out = ctx.run(ctx.on.install(), State(leader=True))
    out = ctx.run(ctx.on.start(), out)
    out = ctx.run(ctx.on.update_status(), out)

    assert ctx.workload_version_history == ['1', '1.1']
    assert out.workload_version == '1.2'


@pytest.mark.parametrize(
    'status',
    (
        ActiveStatus('foo'),
        WaitingStatus('bar'),
        BlockedStatus('baz'),
        MaintenanceStatus('qux'),
        ErrorStatus('fiz'),
        UnknownStatus(),
    ),
)
def test_status_comparison(status: ops.StatusBase) -> None:
    if isinstance(status, UnknownStatus):
        ops_status = ops.UnknownStatus()
    else:
        ops_status = getattr(ops, status.__class__.__name__)(status.message)
    # A status can be compared to itself.
    assert status == status
    # A status can be compared to another instance of the scenario class.
    if isinstance(status, UnknownStatus):
        assert status == status.__class__()
    else:
        assert status == status.__class__(status.message)
    # A status can be compared to an instance of the ops class.
    assert status == ops_status
    # isinstance also works for comparing to the ops classes.
    assert isinstance(status, type(ops_status))
    # The repr of the scenario and ops classes should be identical.
    assert repr(status) == repr(ops_status)


@pytest.mark.parametrize(
    'status',
    (
        ActiveStatus('foo'),
        WaitingStatus('bar'),
        BlockedStatus('baz'),
        MaintenanceStatus('qux'),
    ),
)
def test_status_success(status: ops.StatusBase) -> None:
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._on_update_status)

        def _on_update_status(self, _: EventBase) -> None:
            self.unit.status = status

    ctx = Context(MyCharm, meta={'name': 'foo'})
    ctx.run(ctx.on.update_status(), State())


@pytest.mark.parametrize(
    'status',
    (
        ErrorStatus('fiz'),
        UnknownStatus(),
    ),
)
def test_status_error(status: ops.StatusBase, monkeypatch: pytest.MonkeyPatch) -> None:
    class MyCharm(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            framework.observe(self.on.update_status, self._on_update_status)

        def _on_update_status(self, _: EventBase) -> None:
            self.unit.status = status

    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'false')
    ctx = Context(MyCharm, meta={'name': 'foo'})
    with pytest.raises(UncaughtCharmError) as excinfo:
        ctx.run(ctx.on.update_status(), State())
    assert isinstance(excinfo.value.__cause__, ops.ModelError)
    assert f'invalid status "{status.name}"' in str(excinfo.value.__cause__)
