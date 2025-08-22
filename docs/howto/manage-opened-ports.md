(manage-opened-ports)=
# How to manage opened ports
> See first: {external+juju:ref}`Juju | Hook Commands | open-port <hook-command-open-port>`

Juju manages the IP of each unit, so you need to instruct Juju
if you want the charm to have a stable address. Typically, charms manage this
by offering to integrate with an ingress charm, but you may also wish to have
the charm itself open a port.

## Implement the feature

Use [](ops.Unit.set_ports) to to declare which ports should be open. For
example, to set an open TCP port based on a configuration value, do the
following in your `config-changed` observer in `src/charm.py`:

```python
def _on_holistic_handler(self, _: ops.EventBase):
    port = cast(int, self.config['server-port'])
    self.unit.set_ports(port)
```

> See more: [](ops.Unit.set_ports)

> Examples: [mysql-k8s opens the MySQL ports](https://github.com/canonical/mysql-k8s-operator/blob/a68147d0fbf66386ab087f4cfcc19784fcc2be6e/src/charm.py#L648), [tempo-coordinator-k8s opens both server and receiver ports](https://github.com/canonical/tempo-coordinator-k8s-operator/blob/ece268eae1158760513807a02972c138fd39afcf/src/charm.py#L95)

`ops` also offers [](ops.Unit.open_port) and [](ops.Unit.close_port) methods,
but the declarative approach is typically simpler.

## Test the feature

You'll want to add unit and integration tests.

### Write unit tests

> See first: {ref}`write-unit-tests-for-a-charm`

In your unit tests, use the [](ops.testing.State.opened_ports) component of the
input `State` to specify which ports are already open when the event is
run. Ports that are not listed are assumed to be closed. After events that modify which
ports are open, assert that the output `State` has the correct set of ports. 

For example, in `tests/unit/test_charm.py`, this verifies that when the
`config-changed` event runs, the only opened port is 8000 (for TCP):

```python
def test_open_port():
    ctx = testing.Context(MyCharm)
    state_in = testing.State()
    state_out = ctx.run(ctx.on.config_changed(), state_in)
    assert state_out.opened_ports == {testing.TCPPort(8000)}
```

### Write integration tests

> See first: {ref}`write-unit-tests-for-a-charm`, {ref}`write-integration-tests-for-a-charm`

To verify that the correct ports are open in an integration test, deploy your
charm as usual, and then try to connect to the appropriate ports.

By adding the following test to your `tests/integration/test_charm.py` file, you can verify
that your charm opens a port specified in the configuration, but prohibits using port 22:

```python
def is_port_open(host: str, port: int) -> bool:
    """Check if a port is opened in a particular host."""
    try:
        with socket.create_connection((host, port), timeout=5):
            return True  # If connection succeeds, the port is open
    except (ConnectionRefusedError, TimeoutError):
        return False  # If connection fails, the port is closed


def test_open_ports(juju: jubilant.Juju):
    """Verify that setting the server-port in the charm's opens that port.

    Assert blocked status in case of port 22 and active status for others.
    """
    # Get the public address of the app:
    address = juju.status().apps["your-app"].units["your-app/0"].public_address
    # Validate that initial port is opened:
    assert is_port_open(address, 8000)

    # Set the port to 22 and validate the app goes to blocked status with the port not opened:
    juju.config("your-app", {"server-port": "22"})
    juju.wait(jubilant.all_blocked)
    assert not is_port_open(address, 22)

    # Set the port to 6789 and validate the app goes to active status with the port opened.
    juju.config("your-app", {"server-port": "6789"})
    juju.wait(jubuilant.all_active)
    assert is_port_open(address, 6789)
```
