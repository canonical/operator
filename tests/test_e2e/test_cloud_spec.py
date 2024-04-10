import ops
import pytest

import scenario


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
    cloud_spec = scenario.state.CloudSpec(
        type="lxd",
        endpoint="https://127.0.0.1:8443",
        credential=scenario.state.CloudCredential(
            auth_type=scenario.state.CloudAuthType.client_certificate_auth_type,
            attributes={
                "client-cert": "foo",
                "client-key": "bar",
                "server-cert": "baz",
            },
        ),
    )
    ctx = scenario.Context(mycharm, meta={"name": "foo"})
    state = scenario.State(
        cloud_spec=cloud_spec, model=scenario.Model(name="lxd-model", type="lxd")
    )
    with ctx.manager("start", state=state) as mgr:
        assert mgr.charm.model.get_cloud_spec() == cloud_spec


def test_get_cloud_spec_error(mycharm):
    ctx = scenario.Context(mycharm, meta={"name": "foo"})
    state = scenario.State(model=scenario.Model(name="lxd-model", type="lxd"))
    with ctx.manager("start", state) as mgr:
        with pytest.raises(ops.ModelError):
            mgr.charm.model.get_cloud_spec()
