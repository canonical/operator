# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import dataclasses

import ops_tools
import pytest
from scenario.context import Context
from scenario.state import State

import ops

from ..helpers import trigger


@pytest.fixture(scope='function')
def mycharm():
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                framework.observe(evt, self._on_event)

        def _on_event(self, event):
            pass

    return MyCharm


def test_config_get(mycharm):
    def check_cfg(charm: ops.CharmBase):
        assert charm.config['foo'] == 'bar'
        assert charm.config['baz'] == 1

    trigger(
        State(
            config={'foo': 'bar', 'baz': 1},
        ),
        'update_status',
        mycharm,
        meta={'name': 'foo'},
        config={'options': {'foo': {'type': 'string'}, 'baz': {'type': 'int'}}},
        post_event=check_cfg,
    )


def test_config_get_default_from_meta(mycharm):
    def check_cfg(charm: ops.CharmBase):
        assert charm.config['foo'] == 'bar'
        assert charm.config['baz'] == 2
        assert charm.config['qux'] is False

    trigger(
        State(
            config={'foo': 'bar'},
        ),
        'update_status',
        mycharm,
        meta={'name': 'foo'},
        config={
            'options': {
                'foo': {'type': 'string'},
                'baz': {'type': 'int', 'default': 2},
                'qux': {'type': 'boolean', 'default': False},
            },
        },
        post_event=check_cfg,
    )


@pytest.mark.parametrize(
    'cfg_in',
    (
        {'foo': 'bar'},
        {'baz': 4, 'foo': 'bar'},
        {'baz': 4, 'foo': 'bar', 'qux': True},
    ),
)
def test_config_in_not_mutated(mycharm, cfg_in):
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                framework.observe(evt, self._on_event)

        def _on_event(self, event):
            # access the config to trigger a config-get
            foo_cfg = self.config['foo']  # noqa: F841
            baz_cfg = self.config['baz']  # noqa: F841
            qux_cfg = self.config['qux']  # noqa: F841

    state_out = trigger(
        State(
            config=cfg_in,
        ),
        'update_status',
        MyCharm,
        meta={'name': 'foo'},
        config={
            'options': {
                'foo': {'type': 'string'},
                'baz': {'type': 'int', 'default': 2},
                'qux': {'type': 'boolean', 'default': False},
            },
        },
    )
    # check config was not mutated by scenario
    assert state_out.config == cfg_in


def test_config_using_generated_config():
    @dataclasses.dataclass
    class Config:
        a: int
        b: float
        c: str

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on.config_changed, self._on_config_changed)

        def _on_config_changed(self, event: ops.ConfigChangedEvent):
            self.typed_config = self.load_config(Config, 10, c='foo')

    schema = ops_tools.config_to_juju_schema(Config)
    ctx = Context(Charm, meta={'name': 'foo'}, config=schema)
    with ctx(ctx.on.config_changed(), State(config={'b': 3.14})) as mgr:
        mgr.run()
        assert mgr.charm.typed_config.a == 10
        assert mgr.charm.typed_config.b == 3.14
        assert mgr.charm.typed_config.c == 'foo'
