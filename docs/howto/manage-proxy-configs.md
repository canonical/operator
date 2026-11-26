(manage-proxy-configuration)=
# How to manage proxy configuration

Juju users can set the `juju-http-proxy`, `juju-https-proxy`, and `juju-no-proxy` {external+juju:ref}`model configuration keys <list-of-model-configuration-keys>` to control how a charm and its workload make HTTP requests. A {ref}`mature charm <charm-maturity>` should respect this proxy configuration.

## Read the proxy configuration

Use [](ops.Model.proxy_config) to get the model's proxy configuration. This returns an [](ops.ProxyConfig) instance:

```python
class MyCharm(ops.CharmBase):
    def _get_proxy_environ(self) -> dict[str, str]:
        proxy = self.model.proxy_config
        no_proxy = ','.join(sorted(proxy.no))
        return {
            'HTTP_PROXY': proxy.http or '',
            'HTTPS_PROXY': proxy.https or '',
            'NO_PROXY': no_proxy,
        }
```

[](ops.ProxyConfig) stores an empty `juju-http-proxy` or `juju-https-proxy` as `None`.

The `no` attribute of [](ops.ProxyConfig) contains the comma-separated entries of `juju-no-proxy` as a tuple of strings. An empty `juju-no-proxy` is an empty tuple. Entries in `no` can contain wildcards (`*.example.com`, or `*` for everything), domain suffixes (`.example.com`), or CIDRs (`10.0.0.0/8`).

Juju doesn't fire an event when the proxy configuration changes, so the charm can only observe the change the next time an event fires. Charms can read the proxy configuration using the {ref}`reconciler pattern <handling-events-holistically>`:

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.config_changed, self._reconcile)
        framework.observe(self.on.update_status, self._reconcile)

    def _reconcile(self, event: ops.EventBase) -> None:
        if not self.container.can_connect():
            return
        proxy_env = self._get_proxy_environ()
        # Pass proxy_env to the workload, as described in the next section.
```

```{admonition} Best practice
:class: hint
:name: best-practice-proxy-url-handling

Don't include the proxy URLs in log messages or in the status message, as they can contain credentials. Tools accept the proxy configuration in different formats, especially `no_proxy`. Validate the proxy configuration before passing it to the workload.

In a Canonical Kubernetes model, requests to the Kubernetes API and to other pods and services might need to bypass the proxy. Add those destinations to `juju-no-proxy`, as in the [Canonical Kubernetes proxy guide](https://documentation.ubuntu.com/canonical-kubernetes/latest/charm/howto/proxy/). For example, [`mysql-k8s`](https://github.com/canonical/mysql-operators/blob/main/kubernetes/src/utils.py) adds `.svc.cluster.local`.
```

## Manage proxy configuration for the workload

The workload typically reads the proxy configuration itself, so the charm needs to put the proxy configuration where the workload expects.

(manage-proxy-configuration-kubernetes)=
### Kubernetes charms

When the workload runs in a sidecar container, the charm can pass the proxy configuration with Pebble.

If the workload reads `*_proxy` or `*_PROXY` environment variables, put the variables in the Pebble layer for the workload service:

```python
class MyCharm(ops.CharmBase):
    def _get_pebble_layer(self, proxy_env: dict[str, str]) -> ops.pebble.Layer:
        return ops.pebble.Layer({
            'services': {
                'workload': {
                    'override': 'replace',
                    'command': 'workload --port=8000',
                    'startup': 'enabled',
                    'environment': proxy_env,
                },
            },
        })
```

This method defines a service with `override` set to `replace`, so that [](ops.Container.replan) restart the workload when the proxy configuration changes:

```python
class MyCharm(ops.CharmBase):
    def _reconcile(self, event: ops.EventBase) -> None:
        if not self.container.can_connect():
            return
        proxy_env = self._get_proxy_environ()
        self.container.add_layer(
            'workload', self._get_pebble_layer(proxy_env), combine=True
        )
        self.container.replan()
```

A workload may read proxy configuration from CLI options. The CLI options are part of the startup command for the service layer. The example below assumes that the `workload` command accepts the proxy configuration as CLI options:

```python
class MyCharm(ops.CharmBase):
    def _get_pebble_layer(self) -> ops.pebble.Layer:
        proxy = self.model.proxy_config
        args = ['workload', '--port=8000']
        if proxy.http:
            args.append(f'--http-proxy={proxy.http}')
        if proxy.https:
            args.append(f'--https-proxy={proxy.https}')
        if proxy.no:
            args.append(f'--no-proxy={",".join(sorted(proxy.no))}')
        return ops.pebble.Layer({
            'services': {
                'workload': {
                    'override': 'replace',
                    'startup': 'enabled',
                    'command': shlex.join(args),
                },
            },
        })

    def _reconcile(self, event: ops.EventBase) -> None:
        if not self.container.can_connect():
            return
        self.container.add_layer(
            'workload', self._get_pebble_layer(), combine=True
        )
        self.container.replan()
```

If the workload reads a configuration file, write the proxy configuration to {ref}`a file in the workload container <files-in-containers-write-a-file>`. A configuration file isn't part of the plan, so `replan()` can't detect changes to it. In the reconciler, only push the new file and restart the service with [](ops.Container.restart) when the config file changes.

For example, [`wordpress-k8s-operator`](https://github.com/canonical/wordpress-k8s-operator/blob/main/src/charm.py) renders the proxy configuration into `wp-config.php`. [`trino-k8s-operator`](https://github.com/canonical/trino-k8s-operator/blob/main/src/charm.py) renders the proxy configuration as JVM flags into its `jvm.config` file.

(manage-proxy-configuration-machine)=
### Machine charms

If the workload reads the proxy configuration from a file, write the file with {external+charmlibs:ref}`pathops <charmlibs-pathops>`. For example, the [`k8s`](https://github.com/canonical/k8s-operator/tree/main/charms/worker/k8s/src/charm.py) and [`vault`](https://github.com/canonical/vault-k8s-operator/tree/main/machine/src/charm.py) charms write a drop-in file for their snap services. The charm can reload systemd and restart the service with {external+charmlibs:ref}`charmlibs-systemd <charmlibs-systemd>`.

A machine workload can receive proxy configuration from its API or CLI options:
- A snap workload can be configured with {external+charmlibs:ref}`charmlibs-snap <charmlibs-snap>`.
- The workload's start-up command can include the proxy configuration.
- The charm can use the workload's API. For example, the [`lxd`](https://github.com/canonical/charm-lxd/tree/main/src/charm.py) charm uses the LXD API to set its `core.proxy_http`, `core.proxy_https`, and `core.proxy_ignore_hosts` options.

The reconciler is similar to a Kubernetes charm: convert [](ops.ProxyConfig) into the format that the workload expects, compare the result with what the workload has, and restart the workload only if they differ. For example, a systemd service:

```python
from charmlibs import pathops, systemd

SERVICE = 'workload.service'
PROXY_DROP_IN = pathops.LocalPath(f'/etc/systemd/system/{SERVICE}.d/proxy.conf')


class MyCharm(ops.CharmBase):
    def _reconcile(self, event: ops.EventBase) -> None:
        lines = ['[Service]']
        for name, value in self._get_proxy_environ().items():
            # systemd expands '%' specifiers in Environment=, and proxy URLs
            # can contain '%' in percent-encoded credentials.
            value = value.replace('%', '%%')
            lines.append(f'Environment="{name}={value}"')

        changed = pathops.ensure_contents(
            PROXY_DROP_IN, '\n'.join(lines) + '\n', mode=0o600
        )
        if changed:
            systemd.daemon_reload()
            if systemd.service_running(SERVICE):
                systemd.service_restart(SERVICE)
```

## Manage proxy configuration for the charm process

The charm process can make its own HTTP requests, for example to download a file or call an API.

Refer to the libraries' documentation such as {external+python:mod}`urllib.request` and [requests | Proxies](https://requests.readthedocs.io/en/latest/user/advanced/#proxies) for more information.

If the charm uses {external+python:func}`subprocess.run`, it can pass the proxy configuration with the `env` argument. For example:

```python
subprocess.run(
    [
        'backup-tool',
    ],
    env={
        **os.environ,
        'HTTP_PROXY': 'https://proxy.example.com:3128',
    },
)
```

## Test the feature

### Write unit tests

See first: {ref}`write-unit-tests-for-a-charm`

To set the proxy configuration in a unit test, pass a [](ops.testing.ProxyConfig) to [](ops.testing.Model). A default `ProxyConfig()` creates a model with `juju-http-proxy` and `juju-https-proxy` as empty strings, and `juju-no-proxy` is set to `127.0.0.1,localhost,::1`.

```{note}
If you don't pass a `proxy_config` to [](ops.testing.Model), the charm gets no proxy configuration, and `self.model.proxy_config.no` is an empty tuple. This exists for backward compatibility, and might change in a future major release of Ops.
```

We want to test that the proxy configuration reaches the workload.

#### Test a Kubernetes charm

These tests are for the {ref}`Kubernetes charm shown above <manage-proxy-configuration-kubernetes>`:

```python
def test_proxy_configuration_reaches_the_workload():
    proxy_url = 'http://proxy.example.com:3128'
    ctx = testing.Context(MyCharm)
    container = testing.Container('workload', can_connect=True)
    proxy_config = testing.ProxyConfig(
        https=proxy_url,
        no=('localhost', '10.0.0.0/8'),
    )
    state_in = testing.State(
        containers={container},
        model=testing.Model(proxy_config=proxy_config),
    )

    state_out = ctx.run(ctx.on.pebble_ready(container), state_in)

    plan = state_out.get_container('workload').plan
    environment = plan.services['workload'].environment
    assert environment['HTTPS_PROXY'] == proxy_url
    assert environment['HTTP_PROXY'] == ''
    assert environment['NO_PROXY'] == '10.0.0.0/8,localhost'
```

#### Test a machine charm

For a machine charm, check the file or API that the charm writes the proxy configuration to. Mock out those parts so that the unit tests do not modify the testing environment, and are deterministic.

These tests are for the {ref}`machine charm shown above <manage-proxy-configuration-machine>`:

```python
@pytest.fixture(autouse=True)
def service_restart(monkeypatch: pytest.MonkeyPatch) -> mock.Mock:
    restart = mock.Mock(return_value=True)
    monkeypatch.setattr(charm.systemd, 'daemon_reload', lambda: True)
    monkeypatch.setattr(charm.systemd, 'service_running', lambda service: True)
    monkeypatch.setattr(charm.systemd, 'service_restart', restart)
    return restart


def test_proxy_configuration_reaches_the_workload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
):
    proxy_url = 'http://proxy.example.com:3128'
    drop_in = tmp_path / 'proxy.conf'
    monkeypatch.setattr(charm, 'PROXY_DROP_IN', drop_in)
    ctx = testing.Context(charm.MyCharm)
    proxy_config = testing.ProxyConfig(
        https=proxy_url, no=('localhost', '10.0.0.0/8')
    )
    state_in = testing.State(model=testing.Model(proxy_config=proxy_config))

    ctx.run(ctx.on.config_changed(), state_in)

    content = drop_in.read_text()
    assert f'Environment="HTTPS_PROXY={proxy_url}"' in content
    assert 'Environment="NO_PROXY=10.0.0.0/8,localhost"' in content


def test_unchanged_proxy_configuration_doesnt_restart_the_workload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    service_restart: mock.Mock,
):
    proxy_url = 'http://proxy.example.com:3128'
    monkeypatch.setattr(charm, 'PROXY_DROP_IN', tmp_path / 'proxy.conf')
    ctx = testing.Context(charm.MyCharm)
    state_in = testing.State(
        model=testing.Model(proxy_config=testing.ProxyConfig(https=proxy_url)),
    )
    ctx.run(ctx.on.config_changed(), state_in)
    service_restart.reset_mock()

    ctx.run(ctx.on.update_status(), state_in)
    service_restart.assert_not_called()
```

(manage-proxy-configuration-integration-tests)=
### Write integration tests

See first: {ref}`write-integration-tests-for-a-charm`

In an integration test, change the proxy configuration with [](jubilant.Juju.model_config), then check that the workload has the new values.

#### Test a Kubernetes charm

These tests assume:

- The charm is already deployed as `my-charm`, for example by a `test_deploy` test that uses the `charm` fixture, as described in {ref}`write-integration-tests-for-a-charm`.
- The charm has a configuration option `proxy-update`. We only use it to trigger `config-changed` and make the charm apply the new proxy configuration.
- The charm has an action `show-proxy` that returns the proxy host and port from the workload. For example `proxy.example.com:3128`, or an empty string if no proxy configuration is set.

Let's add a handler for the `show-proxy` action:

```python
class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        ...
        framework.observe(self.on['show-proxy'].action, self._on_show_proxy)

    def _on_show_proxy(self, event: ops.ActionEvent) -> None:
        # workload.get_proxy() is a helper function to get the proxy configuration
        # from the workload.
        # The workload may not be ready immediately after replan(),
        # so try get_proxy() in a loop if needed.
        proxy = workload.get_proxy()
        event.set_results({'https-proxy': proxy})
```

In the test, change the proxy configuration, then change the `proxy-update` option to a new value, and probe the `show-proxy` action with [](jubilant.Juju.run) until it reports the expected proxy:

```python
def test_proxy_configuration(juju: jubilant.Juju):
    proxy_url = 'http://proxy.example.com:3128'
    juju.model_config({'juju-https-proxy': proxy_url})
    juju.config('my-charm', {'proxy-update': 'boo'})
    juju.wait(
        lambda _: (
            juju.run('my-charm/0', 'show-proxy').results['https-proxy']
            == 'proxy.example.com:3128'
        ),
        delay=2,
        timeout=120,
        successes=1,
    )

    juju.model_config(reset='juju-https-proxy')
    juju.config('my-charm', {'proxy-update': 'bar'})
    juju.wait(
        lambda _: (
            juju.run('my-charm/0', 'show-proxy').results['https-proxy'] == ''
        ),
        delay=2,
        timeout=120,
        successes=1,
    )
    # Use juju.model_config to restore model config if necessary.
```

#### Test a machine charm

For a machine charm, the integration test is similar to the Kubernetes charm example above. The difference is how the test reads the proxy configuration that the workload receives.

For example, if the workload runs as a systemd service, use `systemctl show`:

```python
def workload_environment(juju: jubilant.Juju) -> dict[str, str]:
    output = juju.ssh(
        'my-charm/0',
        'systemctl',
        'show',
        'workload.service',
        '--property=Environment',
        '--value',
    )
    # systemctl separates the entries with spaces, and quotes an entry that contains a space.
    # For example:
    #     HTTP_PROXY=http://proxy.example.com:8080 NO_PROXY=localhost,127.0.0.1,.example.com "OTHER= foo bar"
    return dict(entry.split('=', 1) for entry in shlex.split(output))
```
