# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import os
from tempfile import TemporaryDirectory

import pytest
from scenario import ActiveStatus, Context
from scenario._runtime import Runtime, UncaughtCharmError
from scenario.state import Relation, State, _CharmSpec, _Event

import ops
from ops._main import _Abort


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
            'foo',
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
        app_name,
        _CharmSpec(
            my_charm_type,
            meta=meta,
        ),
        unit_id=unit_id,
    )

    with runtime.exec(
        state=State(),
        event=_Event('start'),
        context=Context(my_charm_type, meta=meta),
    ) as manager:
        assert manager.charm.unit.name == f'{app_name}/{unit_id}'


def test_env_clean_on_charm_error(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'false')
    meta = {'name': 'frank', 'requires': {'box': {'interface': 'triangle'}}}

    my_charm_type = charm_type()

    runtime = Runtime(
        'frank',
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
            with pytest.warns(DeprecationWarning):
                assert ops.JujuVersion.from_environ() == version

    ctx = Context(MyCharm, meta={'name': 'foo'}, juju_version=version)
    ctx.run(ctx.on.start(), State())


@pytest.mark.parametrize('exit_code', (-1, 0, 1, 42))
def test_ops_raises_abort(exit_code: int, monkeypatch: pytest.MonkeyPatch):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.StartEvent):
            self.unit.status = ops.ActiveStatus()
            # Charms can't actually do this (_Abort is private), but this is
            # simpler than causing the framework to raise it.
            raise _Abort(exit_code)

    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'false')
    ctx = Context(MyCharm, meta={'name': 'foo'})
    if exit_code == 0:
        state_out = ctx.run(ctx.on.start(), State())
        assert {e.handle.kind for e in ctx.emitted_events} == {'start'}
        assert state_out.unit_status == ActiveStatus()
    else:
        with pytest.raises(UncaughtCharmError) as exc:
            ctx.run(ctx.on.start(), State())
        assert isinstance(exc.value.__cause__, _Abort)
        assert exc.value.__cause__.exit_code == exit_code


class ValueErrorCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.update_status, self._on_update_status)

    def _on_update_status(self, event: ops.EventBase):
        raise ValueError()


@pytest.mark.parametrize(
    ('expected_error', 'bare_charm_errors'),
    (
        # any non-zero string that `isdigit`
        (ValueError, '1'),
        (ValueError, '007'),
        # 'true' (case-insensitive)
        (ValueError, 'true'),
        (ValueError, 'True'),
        (ValueError, 'tRuE'),
        # falsey digits
        (UncaughtCharmError, '0'),
        (UncaughtCharmError, '00'),
        # any other value
        (UncaughtCharmError, '-1'),
        (UncaughtCharmError, 'false'),
        (UncaughtCharmError, 'yes'),
        (UncaughtCharmError, '✩ anything ✨ else ✧'),
        # the actually unset case is tested separately
        # the empty string is treated as 'any other value'
        (UncaughtCharmError, ''),
    ),
)
def test_bare_charm_errors_set(
    monkeypatch: pytest.Monkeypatch, expected_error: type[Exception], bare_charm_errors: str | None
):
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', bare_charm_errors)
    ctx = Context(ValueErrorCharm, meta={'name': 'value-error'})
    with pytest.raises(expected_error):
        ctx.run(ctx.on.update_status(), State())


def test_bare_charm_errors_not_set(monkeypatch: pytest.Monkeypatch):
    monkeypatch.delenv('SCENARIO_BARE_CHARM_ERRORS', raising=False)
    ctx = Context(ValueErrorCharm, meta={'name': 'value-error'})
    with pytest.raises(UncaughtCharmError):
        ctx.run(ctx.on.update_status(), State())
