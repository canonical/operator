# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import os

import pytest
import scenario

import ops


class ProxyStatusCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.start, self._on_start)

    def _on_start(self, event: ops.StartEvent):
        proxy = self.model.proxy_config
        if proxy.https:
            self.unit.status = ops.ActiveStatus(f'using proxy {proxy.https}')
        else:
            self.unit.status = ops.ActiveStatus('no proxy')


@pytest.fixture
def ctx() -> scenario.Context[ProxyStatusCharm]:
    return scenario.Context(ProxyStatusCharm, meta={'name': 'foo'})


@pytest.mark.parametrize(
    'proxy_config',
    [
        scenario.ProxyConfig(
            http='http-proxy-url',
            https='https-proxy-url',
            no='127.0.0.1,localhost,::1',
        ),
        scenario.ProxyConfig(
            http='',
            https='https-proxy-url',
            no='127.0.0.1,localhost,::1',
        ),
        scenario.ProxyConfig(
            http='',
            https='',
            no='127.0.0.1,localhost,::1',
        ),
        # Empty strings create empty env vars, like Juju does when the model
        # configs aren't set. Ops reads them as None.
        scenario.ProxyConfig(
            http='',
            https='',
            no='',
        ),
        scenario.ProxyConfig(
            https='',
        ),
        scenario.ProxyConfig(),
    ],
)
def test_proxy_config_round_trip(
    ctx: scenario.Context[ProxyStatusCharm], proxy_config: scenario.ProxyConfig
):
    model = scenario.Model(proxy_config=proxy_config)
    state_in = scenario.State(model=model)
    with ctx(ctx.on.start(), state_in) as mgr:
        assert mgr.charm.model.proxy_config == proxy_config._to_ops()


def test_model_no_proxy_config(ctx: scenario.Context[ProxyStatusCharm]):
    model = scenario.Model()
    assert model.proxy_config is None
    with ctx(ctx.on.start(), scenario.State(model=model)) as mgr:
        assert mgr.charm.model.proxy_config == ops.ProxyConfig()


def test_model_proxy_config_defaults(ctx: scenario.Context[ProxyStatusCharm]):
    model = scenario.Model(proxy_config=scenario.ProxyConfig())
    with ctx(ctx.on.start(), scenario.State(model=model)) as mgr:
        # Juju's default for juju-http-proxy and juju-https-proxy is an empty
        # string, which ops reads as None.
        assert mgr.charm.model.proxy_config == ops.ProxyConfig(
            http=None, https=None, no='127.0.0.1,localhost,::1'
        )


def test_not_leaking_into_os_environ(
    ctx: scenario.Context[ProxyStatusCharm], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('JUJU_CHARM_HTTP_PROXY', 'environ-http-proxy-url')
    model = scenario.Model(proxy_config=scenario.ProxyConfig(http='https-proxy-url'))
    state_in = scenario.State(
        model=model,
    )
    with ctx(ctx.on.start(), state_in) as mgr:
        assert mgr.charm.model.proxy_config.http == 'https-proxy-url'

    assert os.environ['JUJU_CHARM_HTTP_PROXY'] == 'environ-http-proxy-url'


def test_proxy_config_drives_charm_status(ctx: scenario.Context[ProxyStatusCharm]):
    proxy_config = scenario.ProxyConfig(https='https-proxy-url')
    state_in = scenario.State(model=scenario.Model(proxy_config=proxy_config))

    state_out = ctx.run(
        ctx.on.start(),
        state_in,
    )
    assert state_out.unit_status == ops.ActiveStatus('using proxy https-proxy-url')


def test_proxy_config_default_charm_status(ctx: scenario.Context[ProxyStatusCharm]):
    state_out = ctx.run(ctx.on.start(), scenario.State())
    assert state_out.unit_status == ops.ActiveStatus('no proxy')
