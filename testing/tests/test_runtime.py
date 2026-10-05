from __future__ import annotations

import dataclasses
import os
from tempfile import TemporaryDirectory

import pytest

import ops
from ops._main import _Abort

from scenario import Context, ActiveStatus
from scenario.state import Relation, State, _CharmSpec, _Event
from scenario._runtime import Runtime, UncaughtCharmError


def charm_type():
    class _CharmEvents(ops.CharmEvents):
        pass

    class MyCharm(ops.CharmBase):
        on = _CharmEvents()  # type: ignore
        _event = None

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._catchall)

        def _catchall(self, e: ops.EventBase):
            if self._event:
                return
            MyCharm._event = e

    return MyCharm


def test_event_emission():
    with TemporaryDirectory():
        meta = {
            'name': 'foo',
            'requires': {'ingress-per-unit': {'interface': 'ingress_per_unit'}},
        }

        my_charm_type = charm_type()

        class MyEvt(ops.EventBase):
            pass

        my_charm_type.on.define_event('bar', MyEvt)

        runtime = Runtime(
            _CharmSpec(
                my_charm_type,
                meta=meta,
            ),
        )

        with runtime.exec(
            state=State(),
            event=_Event('bar'),
            context=Context(my_charm_type, meta=meta),
        ) as manager:
            manager.run()

        assert my_charm_type._event
        assert isinstance(my_charm_type._event, MyEvt)


@pytest.mark.parametrize('app_name', ('foo', 'bar-baz', 'QuX2'))
@pytest.mark.parametrize('unit_id', (1, 2, 42))
def test_unit_name(app_name, unit_id):
    meta = {
        'name': app_name,
    }

    my_charm_type = charm_type()

    runtime = Runtime(
        _CharmSpec(
            my_charm_type,
            meta=meta,
        ),
        unit_id=unit_id,
        app_name=app_name,
    )

    with runtime.exec(
        state=State(),
        event=_Event('start'),
        context=Context(my_charm_type, meta=meta),
    ) as manager:
        assert manager.charm.unit.name == f'{app_name}/{unit_id}'


def test_env_clean_on_charm_error():
    meta = {'name': 'frank', 'requires': {'box': {'interface': 'triangle'}}}

    my_charm_type = charm_type()

    runtime = Runtime(
        _CharmSpec(
            my_charm_type,
            meta=meta,
        ),
    )

    remote_name = 'ava'
    rel = Relation('box', remote_app_name=remote_name)
    with pytest.raises(UncaughtCharmError) as exc:
        with runtime.exec(
            state=State(relations={rel}),
            event=_Event('box_relation_changed', relation=rel),
            context=Context(my_charm_type, meta=meta),
        ) as manager:
            assert manager._juju_context.remote_app_name == remote_name
            assert 'JUJU_REMOTE_APP' in os.environ
            _ = 1 / 0  # raise some error
    # Ensure that some other error didn't occur (like AssertionError!).
    assert 'ZeroDivisionError' in str(exc.value)

    # Ensure that the Juju environment didn't leak into the outside one.
    assert os.getenv('JUJU_REMOTE_APP', None) is None


def test_juju_version_is_set_in_environ():
    version = '2.9'

    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.StartEvent):
            assert ops.JujuVersion.from_environ() == version

    ctx = Context(MyCharm, meta={'name': 'foo'}, juju_version=version)
    ctx.run(ctx.on.start(), State())


@pytest.mark.parametrize('exit_code', (-1, 0, 1, 42))
def test_ops_raises_abort(exit_code: int):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.StartEvent):
            self.unit.status = ops.ActiveStatus()
            # Charms can't actually do this (_Abort is private), but this is
            # simpler than causing the framework to raise it.
            raise _Abort(exit_code)

    ctx = Context(MyCharm, meta={'name': 'foo'})
    if exit_code == 0:
        state_out = ctx.run(ctx.on.start(), State())
        assert {e.handle.kind for e in ctx.emitted_events} == {'start'}
        assert state_out.unit_status == ActiveStatus()
    else:
        with pytest.raises(_Abort) as exc:
            ctx.run(ctx.on.start(), State())
        assert exc.value.exit_code == exit_code


@dataclasses.dataclass
class PortConfig:
    port: int

    def __post_init__(self):
        if not 1 <= self.port <= 65535:
            raise ValueError('port out of range')


class LoadConfigBlockedCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.config_changed, self._on_config_changed)
        self.typed_config = self.load_config(PortConfig, errors='blocked')

    def _on_config_changed(self, _: ops.ConfigChangedEvent):
        self.unit.status = ops.ActiveStatus()


def test_load_config_blocked_in_init():
    ctx = Context(
        LoadConfigBlockedCharm,
        meta={'name': 'foo'},
        config={'options': {'port': {'type': 'int', 'default': 8080}}},
    )
    state_out = ctx.run(ctx.on.config_changed(), State(config={'port': 0}))
    # As in production, the event isn't emitted and nothing is committed.
    assert not ctx.emitted_events
    assert state_out.unit_status == ops.BlockedStatus('Invalid config: port out of range')


def test_load_config_blocked_in_init_manager():
    ctx = Context(
        LoadConfigBlockedCharm,
        meta={'name': 'foo'},
        config={'options': {'port': {'type': 'int', 'default': 8080}}},
    )
    with ctx(ctx.on.config_changed(), State(config={'port': 0})) as mgr:
        with pytest.raises(RuntimeError, match='exited early'):
            mgr.charm  # noqa: B018
        state_out = mgr.run()
    assert not ctx.emitted_events
    assert state_out.unit_status == ops.BlockedStatus('Invalid config: port out of range')


@pytest.mark.parametrize('exit_code', (-1, 1, 42))
def test_ops_raises_nonzero_abort_in_init(exit_code: int):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            # Charms can't actually do this (_Abort is private, and the public
            # APIs that raise it in __init__ use exit code 0), but this is
            # simpler than causing the framework to raise it.
            raise _Abort(exit_code)

    ctx = Context(MyCharm, meta={'name': 'foo'})
    with pytest.raises(_Abort) as exc:
        ctx.run(ctx.on.start(), State())
    assert exc.value.exit_code == exit_code


def test_leaked_operator_dispatch_raises(monkeypatch: pytest.MonkeyPatch):
    class MyCharm(ops.CharmBase):
        initialised = False

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            MyCharm.initialised = True

    # A leaked OPERATOR_DISPATCH makes the dispatcher raise _Abort(0) before the
    # framework exists. That must fail the test rather than silently pass.
    monkeypatch.setenv('OPERATOR_DISPATCH', '1')
    ctx = Context(MyCharm, meta={'name': 'foo'})
    with pytest.raises(_Abort) as exc:
        ctx.run(ctx.on.start(), State())
    assert exc.value.exit_code == 0
    assert not MyCharm.initialised
