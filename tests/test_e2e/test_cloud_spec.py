import ops
import pytest

import scenario
from scenario.state import CloudSpec


@pytest.fixture(scope="function")
def mycharm():
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event):
            pass

    return MyCharm


def test_get_cloud_spec(mycharm):
    cloud_spec = CloudSpec.from_dict(
        {
            "name": "localhost",
            "type": "lxd",
            "endpoint": "https://127.0.0.1:8443",
            "credential": {
                "auth-type": "certificate",
                "attrs": {
                    "client-cert": "foo",
                    "client-key": "bar",
                    "server-cert": "baz",
                },
            },
        }
    )

    ctx = scenario.Context(mycharm, meta={"name": "foo"})
    with ctx.manager("start", scenario.State(cloud_spec=cloud_spec)) as mgr:
        assert mgr.charm.model.get_cloud_spec() == cloud_spec


def test_get_cloud_spec(mycharm):
    ctx = scenario.Context(mycharm, meta={"name": "foo"})
    with ctx.manager("start", scenario.State()) as mgr:
        with pytest.raises(ops.ModelError):
            mgr.charm.model.get_cloud_spec()
