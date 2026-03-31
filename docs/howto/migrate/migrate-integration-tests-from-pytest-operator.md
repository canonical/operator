(pytest-operator-migration)=
# How to migrate integration tests from pytest-operator

Many charm integration tests use [pytest-operator](https://github.com/charmed-kubernetes/pytest-operator) and [python-libjuju](https://github.com/juju/python-libjuju). This guide explains how to migrate your integration tests from those libraries to [pytest-jubilant](https://github.com/canonical/pytest-jubilant), which uses the Jubilant library.

```{tip}
Try bootstrapping your migration with an AI Agent (such as GitHub Copilot or Claude Code). Instruct the agent to clone the canonical/jubilant and canonical/pytest-jubilant repositories, study them, and then migrate the charm integration tests to Jubilant. You should end up with a great starting point to then continue as outlined in the rest of this guide.
```

To get help while you're migrating tests, please keep the {external+jubilant:doc}`Jubilant API Reference <reference/jubilant>` handy, and make use of your IDE's autocompletion -- Jubilant tries to provide good type annotations and docstrings.

Migrating your tests can be broken into three steps:

1. Update your dependencies
2. Add any extra fixtures to `conftest.py`
3. Update the tests themselves

Let's look at each of these in turn.


## Update your dependencies

The first thing you'll need to do is add `jubilant` and `pytest-jubilant` as dependencies to your `tox.ini` or `pyproject.toml`. Jubilant (1.x) wraps the Juju CLI, and `pytest-jubilant` (2.x) is a pytest plugin that provides fixtures and CLI options for managing Juju models during tests.

You can also remove the dependencies on `juju` (python-libjuju), `pytest-operator`, and `pytest-asyncio`.

If you're using `tox.ini`, the diff might look like:

```diff
 [testenv:integration]
 deps =
     boto3
     cosl
-    juju>=3.0
+    jubilant>=1,<2
+    pytest-jubilant>=2,<3
     pytest
-    pytest-operator
-    pytest-asyncio
     -r{toxinidir}/requirements.txt
```

If you're migrating a large number of tests, you may want to do it in stages. In that case, keep the old dependencies in place till the end, and migrate tests one at a time, so that both pytest-operator and Jubilant tests can run together.


## Add any extra fixtures to `conftest.py`

The `pytest-jubilant` plugin provides a module-scoped `juju` fixture that creates a temporary model, destroys it after the tests, and dumps debug logs on failure. It also provides CLI options such as `--no-juju-teardown` (to keep models) and `--juju-model` (to set a custom model name prefix). This replaces the need to write a `juju` fixture yourself.

If you have a hand-written `juju` fixture in your `conftest.py`, you can remove it.

(a_juju_model_fixture)=
### The `juju` model fixture

`pytest-jubilant` expects that a Juju controller has already been set up, either using [Concierge](https://github.com/jnsgruk/concierge) or a manual approach. The plugin automatically creates a temporary model per test module and tears it down afterward.

In your tests, use the fixture like this:

```python
# tests/integration/test_charm.py

def test_active(juju: jubilant.Juju):
    juju.deploy('mycharm')
    juju.wait(jubilant.all_active)

    # Or wait for just 'mycharm' to be active (ignoring other apps):
    juju.wait(lambda status: jubilant.all_active(status, 'mycharm'))
```

A few things to note about the fixture:

* To keep models around after running the tests (matching pytest-operator's `--keep-models`), pass `--no-juju-teardown`.
* The default wait timeout is Jubilant's default. To match python-libjuju's 10-minute `wait_for_idle` timeout, set `juju.wait_timeout = 10 * 60` in a wrapper fixture or at the start of your test.
* If any of the tests fail, the plugin automatically dumps the last 1000 lines of `juju debug-log` output.
* It is module-scoped, like pytest-operator's `ops_test` fixture. This means that a new model is created for every `test_*.py` file, but not for every test.

(how_to_migrate_an_application_fixture)=
### An application fixture

If you don't want to deploy your application in each test, you can add a module-scoped `app` fixture that deploys your charm and waits for it to go active.

The following fixture assumes that the charm has already been packed with `charmcraft pack` in a previous CI step (`pytest-jubilant` has no equivalent of `ops_test.build_charm`):

```python
# tests/integration/conftest.py

import pathlib

import jubilant
import pytest

@pytest.fixture(scope='module')
def app(juju: jubilant.Juju):
    juju.deploy(
        charm_path('mycharm'),
        'mycharm',
        resources={
            'mycharm-image': 'ghcr.io/canonical/...',
        },
        config={
            'base_url': '/api',
            'port': 80,
        },
        base='ubuntu@20.04',
    )
    # ... do any other application setup here ...
    juju.wait(jubilant.all_active)

    yield 'mycharm'  # run the test


def charm_path(name: str) -> pathlib.Path:
    """Return full absolute path to given test charm."""
    # We're in tests/integration/conftest.py, so parent*3 is repo top level.
    charm_dir = pathlib.Path(__file__).parent.parent.parent
    charms = [p.absolute() for p in charm_dir.glob(f'{name}_*.charm')]
    assert charms, f'{name}_*.charm not found'
    assert len(charms) == 1, 'more than one .charm file, unsure which to use'
    return charms[0]
```

In your tests, you'll need to specify that the test depends on both fixtures:

```python
# tests/integration/test_charm.py

def test_active(juju: jubilant.Juju, app: str):
    status = juju.status()
    assert status.apps[app].is_active
```


## Update the tests themselves

Many features of pytest-operator and python-libjuju map quite directly to Jubilant, except without using `async`. Here is a summary of what you need to change:

- Remove `async` and `await` keywords, and replace `pytest_asyncio.fixture` with `pytest.fixture`
- Replace introspection of python-libjuju's `Application` and `Unit` objects with [`juju.status`](jubilant.Juju.status)
- Replace `model.wait_for_idle` with [`juju.wait`](jubilant.Juju.wait) and an appropriate *ready* callable
- Replace `unit.run` with [`juju.exec`](jubilant.Juju.exec); note the different return type and error handling
- Replace `unit.run_action` with [`juju.run`](jubilant.Juju.run); note the different return type and error handling
- Replace other python-libjuju methods with equivalent [`Juju`](jubilant.Juju) methods, which are normally much closer to the Juju CLI commands

Let's look at some specifics in more detail.

### Deploying a charm

To migrate a charm deployment from pytest-operator, drop the `await`, change `series` to `base`, and replace `model.wait_for_idle` with [`juju.wait`](jubilant.Juju.wait):

```python
# pytest-operator
postgres_app = await model.deploy(
    'postgresql-k8s',
    channel='14/stable',
    series='jammy',
    revision=300,
    trust=True,
    config={'profile': 'testing'},
)
await model.wait_for_idle(apps=[postgres_app.name], status='active')

# jubilant
juju.deploy(
    'postgresql-k8s',
    channel='14/stable',
    base='ubuntu@22.04',
    revision=300,
    trust=True,
    config={'profile': 'testing'},
)
juju.wait(lambda status: jubilant.all_active(status, 'postgresql-k8s'))
```

### Fetching status

A python-libjuju model is updated in the background using websockets. In Jubilant you use ordinary Python function calls to fetch updates:

```python
# pytest-operator
async def test_active(app: Application):
    assert app.units[0].workload_status == ActiveStatus.name

# jubilant
def test_active(juju: jubilant.Juju, app: str):
    status = juju.status()
    assert status.apps[app].units[app + '/0'].is_active
```

### Waiting for a condition

However, instead of calling `status` directly, it's usually better to wait for a certain condition to be true. In python-libjuju you used `model.wait_for_idle`; in Jubilant you use [`juju.wait`](jubilant.Juju.wait), which has a simpler and more consistent API.

The `wait` method takes a *ready* callable, which takes a [`Status`](jubilant.Status) object. Internally, `wait` polls `juju status` every second and calls the *ready* callable, which must return `True` three times in a row (this is configurable).

You can optionally provide an *error* callable, which also takes a `Status` object. If the *error* callable returns `True`, `wait` raises a [`WaitError`](jubilant.WaitError) immediately.

Jubilant provides helper functions to use for the *ready* and *error* callables, such as [`jubilant.all_active`](jubilant.all_active) and [`jubilant.any_error`](jubilant.any_error). These check whether the workload status of all (or any) applications and their units are in a given state.

For example, here's a simple `wait` call that waits for all applications and units to go "active" and raises an error if any go into "error":

```python
# pytest-operator
async def test_active(model: Model):
    await model.deploy('mycharm')
    await model.wait_for_idle(status='active')  # implies raise_on_error=True

# jubilant
def test_active(juju: jubilant.Juju):
    juju.deploy('mycharm')
    juju.wait(jubilant.all_active, error=jubilant.any_error)
```

It's usually best to wait on workload status with the `all_*` and `any_*` helpers. However, if you want to wait specifically for unit agent status to be idle, you can use [`jubilant.all_agents_idle`](jubilant.all_agents_idle):

```python
# pytest-operator
async def test_idle(model: Model):
    await model.deploy('mycharm')
    await model.wait_for_idle()

# jubilant
def test_active(juju: jubilant.Juju):
    juju.deploy('mycharm')
    juju.wait(jubilant.all_agents_idle)
```

It's common to use a `lambda` function to customize the callable or compose multiple checks. For example, to wait specifically for `mysql` and `redis` to go active and `logger` to be blocked:

```python
juju.wait(
    lambda status: (
        jubilant.all_active(status, 'mysql', 'redis') and
        jubilant.all_blocked(status, 'logger'),
    ),
)
```

The `wait` method also has other options (see [`juju.wait`](jubilant.Juju.wait) for details):

```python
juju.deploy('mycharm')
juju.wait(
    ready=lambda status: jubilant.all_active(status, 'mycharm'),
    error=jubilant.any_error,
    delay=0.2,    # poll "juju status" every 200ms (default 1s)
    timeout=60,   # set overall timeout to 60s (default juju.wait_timeout)
    successes=7,  # require ready to return success 7x in a row (default 3)
)
```

For more examples, see {external+jubilant:ref}`Use a custom wait condition <use_a_custom_wait_condition>` in the Jubilant tutorial.


### Integrating two applications

To integrate two charms, remove the `async`-related code and replace `model.add_relation` with [`juju.integrate`](jubilant.Juju.integrate). For example, to integrate discourse-k8s with three other charms:

```python
# pytest-operator
await asyncio.gather(
    model.add_relation('discourse-k8s', 'postgresql-k8s:database'),
    model.add_relation('discourse-k8s', 'redis-k8s'),
    model.add_relation('discourse-k8s', 'nginx-ingress-integrator'),
)
await model.wait_for_idle(status='active')

# jubilant
juju.integrate('discourse-k8s', 'postgresql-k8s:database')
juju.integrate('discourse-k8s', 'redis-k8s')
juju.integrate('discourse-k8s', 'nginx-ingress-integrator')
juju.wait(jubilant.all_active)
```

### Executing a command

In `pytest-operator` tests, you used `unit.run` to execute a command. With Jubilant (as with Juju 3.x) you use [`juju.exec`](jubilant.Juju.exec). Jubilant's `exec` returns a [`jubilant.Task`](jubilant.Task), and it also checks errors for you:

```python
# pytest-operator
unit = model.applications['discourse-k8s'].units[0]
action = await unit.run('/bin/bash -c "..."')
await action.wait()
logger.info(action.results)
assert action.results['return-code'] == 0, 'Enable plugins failed'

# jubilant
task = juju.exec('/bin/bash -c "..."', unit='discourse-k8s/0')
logger.info(task.results)
```

### Running an action

In `pytest-operator` tests, you used `unit.run_action` to run an action. With Jubilant, you use [`juju.run`](jubilant.Juju.run). Similar to `exec`, Jubilant's `run` returns a [`jubilant.Task`](jubilant.Task) and checks errors for you:

```python
# pytest-operator
app = model.applications['postgresl-k8s']
action = await app.units[0].run_action('get-password', username='operator')
await action.wait()
password = action.results['password']

# jubilant
task = juju.run('postgresql-k8s/0', 'get-password', {'username': 'operator'})
password = task.results['password']
```

### The `cli` fallback

Similar to how you could call `ops_test.juju`, with Jubilant you can call [`juju.cli`](jubilant.Juju.cli) to execute an arbitrary Juju command. The `cli` method checks errors for you and raises a [`CLIError`](jubilant.CLIError) if the command's exit code is nonzero:

```python
# pytest-operator
return_code, _, scp_err = await ops_test.juju(
    'scp',
    '--container',
    'postgresql',
    './testing_database/testing_database.sql',
    f'{postgres_app.units[0].name}:.',
)
assert return_code == 0, scp_err

# jubilant
juju.cli(
    'scp',
    '--container',
    'postgresql',
    './testing_database/testing_database.sql',
    'postgresql-k8s/0:.',
)
```

### A `fast_forward` context manager

Pytest-operator has a `fast_forward` context manager which temporarily speeds up `update-status` hooks to fire every 10 seconds (instead of Juju's default of every 5 minutes). Jubilant doesn't provide this context manager, as we don't recommend it for new tests. If you need it for migrating existing tests, you can define it as:

```python
@contextlib.contextmanager
def fast_forward(juju: jubilant.Juju):
    """Context manager that temporarily speeds up update-status hooks to fire every 10s."""
    old = juju.model_config()['update-status-hook-interval']
    juju.model_config({'update-status-hook-interval': '10s'})
    try:
        yield
    finally:
        juju.model_config({'update-status-hook-interval': old})
```


## See more

- [](write-integration-tests-for-a-charm)
- {external+jubilant:doc}`Jubilant's API Reference <reference/jubilant>`
- [This discourse-k8s migration PR](https://github.com/canonical/discourse-k8s-operator/pull/326) shows how we migrated a real charm's integration tests
