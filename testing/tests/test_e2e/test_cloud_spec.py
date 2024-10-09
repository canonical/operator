import ops
import pytest

import scenario


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        for evt in self.on.events().values():
            self.framework.observe(evt, self._on_event)

    def _on_event(self, event):
        pass


def test_get_cloud_spec():
    scenario_cloud_spec = scenario.CloudSpec(
        type="lxd",
        name="localhost",
        endpoint="https://127.0.0.1:8443",
        credential=scenario.CloudCredential(
            auth_type="clientcertificate",
            attributes={
                "client-cert": "foo",
                "client-key": "bar",
                "server-cert": "baz",
            },
        ),
    )
    expected_cloud_spec = ops.CloudSpec(
        type="lxd",
        name="localhost",
        endpoint="https://127.0.0.1:8443",
        credential=ops.CloudCredential(
            auth_type="clientcertificate",
            attributes={
                "client-cert": "foo",
                "client-key": "bar",
                "server-cert": "baz",
            },
        ),
    )
    ctx = scenario.Context(MyCharm, meta={"name": "foo"}, app_trusted=True)
    state = scenario.State(
        model=scenario.Model(
            name="lxd-model", type="lxd", cloud_spec=scenario_cloud_spec
        ),
    )
    with ctx(ctx.on.start(), state=state) as mgr:
        assert mgr.charm.model.get_cloud_spec() == expected_cloud_spec


def test_get_cloud_spec_error():
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})
    state = scenario.State(model=scenario.Model(name="lxd-model", type="lxd"))
    with ctx(ctx.on.start(), state) as mgr:
        with pytest.raises(ops.ModelError):
            mgr.charm.model.get_cloud_spec()


def test_get_cloud_spec_untrusted():
    cloud_spec = ops.CloudSpec(type="lxd", name="localhost")
    ctx = scenario.Context(MyCharm, meta={"name": "foo"})
    state = scenario.State(
        model=scenario.Model(name="lxd-model", type="lxd", cloud_spec=cloud_spec),
    )
    with ctx(ctx.on.start(), state) as mgr:
        with pytest.raises(ops.ModelError):
            mgr.charm.model.get_cloud_spec()
