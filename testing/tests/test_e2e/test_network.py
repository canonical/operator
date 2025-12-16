# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pytest
from scenario import Context
from scenario.state import (
    Address,
    BindAddress,
    Network,
    Relation,
    State,
    SubordinateRelation,
)

import ops


@pytest.fixture(scope='function')
def mycharm() -> type[ops.CharmBase]:
    class MyCharm(ops.CharmBase):
        _call = None
        called = False

        def __init__(self, framework: ops.Framework):
            super().__init__(framework)

            for evt in self.on.events().values():
                framework.observe(evt, self._on_event)

        def _on_event(self, event: ops.EventBase):
            if MyCharm._call:
                MyCharm.called = True
                MyCharm._call(self, event)

    return MyCharm


def test_ip_get(mycharm: type[ops.CharmBase]):
    ctx: Context[ops.CharmBase] = Context(
        mycharm,
        meta={
            'name': 'foo',
            'requires': {
                'metrics-endpoint': {'interface': 'foo'},
                'deadnodead': {'interface': 'bar'},
            },
            'extra-bindings': {'foo': {}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(
            relations=[
                Relation(
                    interface='foo',
                    remote_app_name='remote',
                    endpoint='metrics-endpoint',
                    id=1,
                ),
            ],
            networks={Network('foo', [BindAddress([Address('4.4.4.4')])])},
        ),
    ) as mgr:
        # we have a network for the relation
        rel = mgr.charm.model.get_relation('metrics-endpoint')
        assert rel is not None
        binding = mgr.charm.model.get_binding(rel)
        assert binding is not None
        network = binding.network
        assert network is not None
        assert str(network.bind_address) == '192.0.2.0'

        # we have a network for a binding without relations on it
        binding = mgr.charm.model.get_binding('deadnodead')
        assert binding is not None
        network = binding.network
        assert network is not None
        assert str(network.bind_address) == '192.0.2.0'

        # and an extra binding
        binding = mgr.charm.model.get_binding('foo')
        assert binding is not None
        network = binding.network
        assert network is not None
        assert str(network.bind_address) == '4.4.4.4'


def test_no_sub_binding(mycharm: type[ops.CharmBase]):
    ctx: Context[ops.CharmBase] = Context(
        mycharm,
        meta={
            'name': 'foo',
            'requires': {'bar': {'interface': 'foo', 'scope': 'container'}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(
            relations=[
                SubordinateRelation('bar'),
            ]
        ),
    ) as mgr:
        with pytest.raises(ops.RelationNotFoundError):
            # sub relations have no network
            mgr.charm.model.get_binding('bar').network  # type: ignore # noqa: B018  # Used to trigger the error.


def test_no_relation_error(mycharm: type[ops.CharmBase]):
    """Attempting to call get_binding on a non-existing relation -> RelationNotFoundError"""

    ctx: Context[ops.CharmBase] = Context(
        mycharm,
        meta={
            'name': 'foo',
            'requires': {'metrics-endpoint': {'interface': 'foo'}},
            'extra-bindings': {'bar': {}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(
            relations=[
                Relation(
                    interface='foo',
                    remote_app_name='remote',
                    endpoint='metrics-endpoint',
                    id=1,
                ),
            ],
            networks={Network('bar')},
        ),
    ) as mgr:
        with pytest.raises(ops.RelationNotFoundError):
            mgr.charm.model.get_binding('foo').network  # type: ignore # noqa: B018  # Used to trigger the error.


def test_juju_info_network_default(mycharm: type[ops.CharmBase]):
    ctx: Context[ops.CharmBase] = Context(
        mycharm,
        meta={'name': 'foo'},
    )

    with ctx(
        ctx.on.update_status(),
        State(),
    ) as mgr:
        # we have a network for the relation
        binding = mgr.charm.model.get_binding('juju-info')
        assert binding is not None
        network = binding.network
        assert network is not None
        assert str(network.bind_address) == '192.0.2.0'


def test_explicit_juju_info_network_override(mycharm: type[ops.CharmBase]):
    ctx: Context[ops.CharmBase] = Context(
        mycharm,
        meta={
            'name': 'foo',
            # this charm for whatever reason explicitly defines a juju-info endpoint
            'requires': {'juju-info': {'interface': 'juju-info'}},
        },
    )

    with ctx(
        ctx.on.update_status(),
        State(),
    ) as mgr:
        binding = mgr.charm.model.get_binding('juju-info')
        assert binding is not None
        network = binding.network
        assert network is not None
        assert network.bind_address
