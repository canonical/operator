from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from ops import CharmBase

from scenario import Context, State
from scenario.errors import UncaughtCharmError
from scenario.state import _Event, _next_action_id


class MyCharm(CharmBase):
    pass


def test_run():
    ctx = Context(MyCharm, meta={'name': 'foo'})
    state = State()

    with patch.object(ctx, '_run') as p:
        # This would normally be set within the _run call scope.
        ctx._output_state = 'foo'  # type: ignore
        output = ctx.run(ctx.on.start(), state)
        assert output == 'foo'

    assert p.called
    e = p.call_args.kwargs['event']
    s = p.call_args.kwargs['state']

    assert isinstance(e, _Event)
    assert e.name == 'start'
    assert s is state


def test_run_action():
    ctx = Context(MyCharm, meta={'name': 'foo'})
    state = State()
    expected_id = _next_action_id(update=False)

    with patch.object(ctx, '_run') as p:
        # This would normally be set within the _run call scope.
        ctx._output_state = 'foo'  # type: ignore
        output = ctx.run(ctx.on.action('do-foo'), state)
        assert output == 'foo'

    assert p.called
    e = p.call_args.kwargs['event']
    s = p.call_args.kwargs['state']

    assert isinstance(e, _Event)
    assert e.name == 'do_foo_action'
    assert s is state
    assert e.action.id == expected_id


@pytest.mark.parametrize('app_name', ('foo', 'bar', 'george'))
@pytest.mark.parametrize('unit_id', (1, 2, 42))
def test_app_name(app_name, unit_id):
    ctx = Context(MyCharm, meta={'name': 'foo'}, app_name=app_name, unit_id=unit_id)
    with ctx(ctx.on.start(), State()) as mgr:
        assert mgr.charm.app.name == app_name
        assert mgr.charm.unit.name == f'{app_name}/{unit_id}'


@pytest.mark.parametrize('machine_id', ('0', None, '42', '0/lxd/4'))
def test_machine_id_envvar(machine_id):
    ctx = Context(MyCharm, meta={'name': 'foo'}, machine_id=machine_id)
    os.unsetenv('JUJU_MACHINE_ID')  # cleanup env to be sure
    with ctx(ctx.on.start(), State()):
        assert os.getenv('JUJU_MACHINE_ID') == machine_id


def test_context_manager():
    ctx = Context(MyCharm, meta={'name': 'foo'}, actions={'act': {}})
    state = State()
    with ctx(ctx.on.start(), state) as mgr:
        mgr.run()
        assert mgr.charm.meta.name == 'foo'

    with ctx(ctx.on.action('act'), state) as mgr:
        mgr.run()
        assert mgr.charm.meta.name == 'foo'


def test_app_name_and_unit_id_default():
    ctx = Context(MyCharm, meta={'name': 'foo'})
    assert ctx.app_name == 'foo'
    assert ctx.unit_id == 0


def test_app_name_and_unit_id():
    ctx = Context(MyCharm, meta={'name': 'foo'}, app_name='notfoo', unit_id=42)
    assert ctx.app_name == 'notfoo'
    assert ctx.unit_id == 42


def test_context_manager_uncaught_error():
    class CrashyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)
            os.environ['TEST_ENV_VAR'] = '1'

        def _on_start(self, event):
            raise RuntimeError('Crash!')

    ctx = Context(CrashyCharm, meta={'name': 'crashy'})
    with pytest.raises(UncaughtCharmError):
        with ctx(ctx.on.start(), State()) as mgr:
            assert os.getenv('TEST_ENV_VAR') == '1'
            mgr.run()
    assert 'TEST_ENV_VAR' not in os.environ


def test_run_uncaught_error():
    class CrashyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)
            os.environ['TEST_ENV_VAR'] = '1'

        def _on_start(self, event):
            raise RuntimeError('Crash!')

    ctx = Context(CrashyCharm, meta={'name': 'crashy'})
    with pytest.raises(UncaughtCharmError):
        ctx.run(ctx.on.start(), State())
    assert 'TEST_ENV_VAR' not in os.environ


def test_context_manager_env_cleared():
    class GoodCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)
            os.environ['TEST_ENV_VAR'] = '1'

        def _on_start(self, event):
            os.environ['TEST_ENV_VAR'] = '2'

    ctx = Context(GoodCharm, meta={'name': 'crashy'})
    with ctx(ctx.on.start(), State()) as mgr:
        assert os.getenv('TEST_ENV_VAR') == '1'
        mgr.run()
    assert 'TEST_ENV_VAR' not in os.environ


def test_run_env_cleared():
    class GoodCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)

        def _on_start(self, event):
            os.environ['TEST_ENV_VAR'] = '1'

    ctx = Context(GoodCharm, meta={'name': 'crashy'})
    ctx.run(ctx.on.start(), State())
    assert 'TEST_ENV_VAR' not in os.environ
