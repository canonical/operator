# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import os
from unittest.mock import patch

import pytest
from scenario import Context, State
from scenario.errors import UncaughtCharmError
from scenario.state import _Event, _next_action_id

from ops import CharmBase


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
    os.environ.pop('JUJU_MACHINE_ID', None)  # cleanup env to be sure
    with ctx(ctx.on.start(), State()):
        assert os.getenv('JUJU_MACHINE_ID') == machine_id


@pytest.mark.parametrize('availability_zone', ('zone1', None, 'us-east-1a'))
def test_availability_zone_envvar(availability_zone):
    ctx = Context(MyCharm, meta={'name': 'foo'}, availability_zone=availability_zone)
    os.environ.pop('JUJU_AVAILABILITY_ZONE', None)  # cleanup env to be sure
    with ctx(ctx.on.start(), State()):
        assert os.getenv('JUJU_AVAILABILITY_ZONE') == availability_zone


@pytest.mark.parametrize('principal_unit', ('main/0', None, 'app/42'))
def test_principal_unit_envvar(principal_unit):
    ctx = Context(MyCharm, meta={'name': 'foo'}, principal_unit=principal_unit)
    os.environ.pop('JUJU_PRINCIPAL_UNIT', None)  # cleanup env to be sure
    with ctx(ctx.on.start(), State()):
        assert os.getenv('JUJU_PRINCIPAL_UNIT') == principal_unit


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


@pytest.mark.parametrize('bare_charm_errors', ('1', '0'))
def test_context_manager_uncaught_error(bare_charm_errors: str, monkeypatch: pytest.Monkeypatch):
    class CrashyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)
            os.environ['TEST_ENV_VAR'] = '1'

        def _on_start(self, event):
            raise RuntimeError('Crash!')

    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', bare_charm_errors)
    ctx = Context(CrashyCharm, meta={'name': 'crashy'})
    with pytest.raises((UncaughtCharmError, RuntimeError)):
        with ctx(ctx.on.start(), State()) as mgr:
            assert os.getenv('TEST_ENV_VAR') == '1'
            mgr.run()
    assert 'TEST_ENV_VAR' not in os.environ


@pytest.mark.parametrize('bare_charm_errors', ('1', '0'))
def test_run_uncaught_error(bare_charm_errors: str, monkeypatch: pytest.Monkeypatch):
    class CrashyCharm(CharmBase):
        def __init__(self, framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)
            os.environ['TEST_ENV_VAR'] = '1'

        def _on_start(self, event):
            raise RuntimeError('Crash!')

    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', bare_charm_errors)
    ctx = Context(CrashyCharm, meta={'name': 'crashy'})
    with pytest.raises((UncaughtCharmError, RuntimeError)):
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


def test_charm_spec_is_deprecated():
    ctx = Context(CharmBase, meta={'name': 'some-name'})
    with pytest.warns(DeprecationWarning):
        _ = ctx.charm_spec  # type: ignore


def test_charmcraft_yaml_config_extraction():
    """Test that config is extracted from a full charmcraft.yaml dict."""
    charmcraft_yaml = {
        'name': 'my-charm',
        'summary': 'A test charm',
        'description': 'Test charm description',
        'config': {
            'options': {
                'param1': {
                    'type': 'string',
                    'default': 'value1',
                }
            }
        },
    }
    ctx = Context(MyCharm, meta=charmcraft_yaml)
    assert ctx._charm_spec.config == charmcraft_yaml['config']


def test_charmcraft_yaml_actions_extraction():
    """Test that actions are extracted from a full charmcraft.yaml dict."""
    charmcraft_yaml = {
        'name': 'my-charm',
        'summary': 'A test charm',
        'description': 'Test charm description',
        'actions': {
            'do-foo': {
                'description': 'Do foo',
            },
        },
    }
    ctx = Context(MyCharm, meta=charmcraft_yaml)
    assert ctx._charm_spec.actions == charmcraft_yaml['actions']


def test_charmcraft_yaml_both_config_and_actions_extraction():
    """Test that both config and actions are extracted from charmcraft.yaml."""
    charmcraft_yaml = {
        'name': 'my-charm',
        'summary': 'A test charm',
        'description': 'Test charm description',
        'config': {
            'options': {
                'param1': {
                    'type': 'string',
                }
            }
        },
        'actions': {
            'do-foo': {
                'description': 'Do foo',
            },
        },
    }
    ctx = Context(MyCharm, meta=charmcraft_yaml)
    assert ctx._charm_spec.config == charmcraft_yaml['config']
    assert ctx._charm_spec.actions == charmcraft_yaml['actions']


def test_metadata_yaml_without_config_or_actions():
    """Test backward compatibility with metadata.yaml that has no config/actions."""
    metadata_yaml = {
        'name': 'my-charm',
        'summary': 'A test charm',
        'description': 'Test charm description',
    }
    ctx = Context(MyCharm, meta=metadata_yaml)
    assert ctx._charm_spec.meta == metadata_yaml
    assert ctx._charm_spec.config is None
    assert ctx._charm_spec.actions is None


def test_explicit_config_overrides_extracted_config():
    """Test that explicitly provided config parameter overrides extracted config."""
    charmcraft_yaml = {
        'name': 'my-charm',
        'summary': 'A test charm',
        'description': 'Test charm description',
        'config': {
            'options': {
                'original': {'type': 'string'},
            }
        },
    }
    explicit_config = {
        'options': {
            'override': {'type': 'int'},
        }
    }
    ctx = Context(MyCharm, meta=charmcraft_yaml, config=explicit_config)
    assert ctx._charm_spec.config == explicit_config
    assert 'override' in ctx._charm_spec.config['options']


def test_explicit_actions_overrides_extracted_actions():
    """Test that explicitly provided actions parameter overrides extracted actions."""
    charmcraft_yaml = {
        'name': 'my-charm',
        'summary': 'A test charm',
        'description': 'Test charm description',
        'actions': {
            'original-action': {},
        },
    }
    explicit_actions = {
        'override-action': {},
    }
    ctx = Context(MyCharm, meta=charmcraft_yaml, actions=explicit_actions)
    assert ctx._charm_spec.actions == explicit_actions
    assert 'override-action' in ctx._charm_spec.actions
