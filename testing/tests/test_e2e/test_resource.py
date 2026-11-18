# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import pathlib

import pytest
from scenario import Context, Resource, State

import ops


class ResourceCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)


def test_get_resource():
    ctx = Context(
        ResourceCharm,
        meta={
            'name': 'resource-charm',
            'resources': {'foo': {'type': 'file'}, 'bar': {'type': 'file'}},
        },
    )
    resource1 = Resource(name='foo', path=pathlib.Path('/var/charm/foo'))
    resource2 = Resource(name='bar', path=pathlib.Path('~/bar'))
    with ctx(ctx.on.update_status(), state=State(resources={resource1, resource2})) as mgr:
        assert mgr.charm.model.resources.fetch('foo') == resource1.path
        assert mgr.charm.model.resources.fetch('bar') == resource2.path
        with pytest.raises(NameError):
            mgr.charm.model.resources.fetch('baz')


def test_get_missing_resource():
    ctx = Context(
        ResourceCharm,
        meta={'name': 'resource-charm', 'resources': {'foo': {'type': 'file'}}},
    )
    with ctx(ctx.on.update_status(), state=State()) as mgr:
        with pytest.raises(ops.ModelError) as exc_info:
            mgr.charm.model.resources.fetch('foo')
        uuid = mgr.charm.model.uuid
    assert str(exc_info.value) == (
        'ERROR could not download resource: HTTP request failed: '
        f'Get https://.../model/{uuid}/units/unit-resource-charm-0/resources/foo: '
        'resource#resource-charm/foo not found'
    )
