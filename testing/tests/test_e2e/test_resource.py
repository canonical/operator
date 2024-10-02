#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

import pathlib

import ops
import pytest

from scenario import Context, Resource, State


class ResourceCharm(ops.CharmBase):
    def __init__(self, framework):
        super().__init__(framework)


def test_get_resource():
    ctx = Context(
        ResourceCharm,
        meta={
            "name": "resource-charm",
            "resources": {"foo": {"type": "file"}, "bar": {"type": "file"}},
        },
    )
    resource1 = Resource(name="foo", path=pathlib.Path("/tmp/foo"))
    resource2 = Resource(name="bar", path=pathlib.Path("~/bar"))
    with ctx(
        ctx.on.update_status(), state=State(resources={resource1, resource2})
    ) as mgr:
        assert mgr.charm.model.resources.fetch("foo") == resource1.path
        assert mgr.charm.model.resources.fetch("bar") == resource2.path
        with pytest.raises(NameError):
            mgr.charm.model.resources.fetch("baz")
