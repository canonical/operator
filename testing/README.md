# ops-scenario, the unit testing framework for ops charms

`ops-scenario` is a Python library that provides state-transition testing for
[Ops](https://ops.readthedocs.io) charms. These tests are higher level than
typical unit tests, but run at similar speeds and are the recommended approach
for testing charms within requiring a full [Juju](https://juju.is) installation.

Test are written in the arrange/act/assert pattern, arranging an object
representing the current Juju state, acting by emulating an event from Juju, and
then asserting on the (simulated) output Juju state.

## Writing tests

Here's a test that verifies that a unit is active after the `start` event, with a very minimal initial state:

```python
from ops import testing

# 'src/charm.py' typically contains the charm class.
from charm import MyCharm

def test_start():
    ctx = testing.Context(MyCharm)
    state_in = testing.State()
    state_out = ctx.run(ctx.on.start(), state_in)
    assert state_out.unit_status == testing.ActiveStatus()
```

More comprehensive tests will include relations, containers, secrets, and other
components in the input state, and assertions against both the output state and
the context. The 'act' stage remains a simple single call, although additional
arguments may be required for the event, such as the relation or container that
triggered it. For example:

```python
import pytest
from ops import testing

from charm import MyCharm

@pytest.mark.parametrize(
    'leader',
    [pytest.param(True, id='leader'), pytest.param(False, id='non-leader')],
)
def test_(leader: bool):
    # Arrange:
    ctx = testing.Context(MyCharm)
    relation = testing.Relation('db', local_app_data={'hostname': 'example.com'})
    peer_relation = testing.PeerRelation('peer')
    container = testing.Container('workload', can_connect=True)
    relation_secret = testing.Secret({'certificate': 'xxxxxxxx'})
    user_secret = testing.Secret({'username': 'admin', 'password': 'xxxxxxxx'})
    config = {'port': 8443, 'admin-credentials': 'secret:1234'}
    state_in = testing.State(
        leader=leader,
        config=config,
        relations={relation, peer_relation},
        containers={container},
        secrets={relation_secret, user_secret},
        unit_status=testing.BlockedStatus(),
        workload_version='1.0.1',
    )

    # Act:
    state_out = ctx.run(ctx.on.relation_changed(relation), state_in)

    # Assert:
    assert testing.JujuLogLine(level='INFO', message='Distributing secret.') in ctx.juju_log
    peer_relation_out = state_out.get_relation(peer_relation.id)
    assert peer_relation_out.peers_data[0] == {'secret_id': relation_secret.id}
```

You don't have to use pytest for your charm tests, but it's what we recommend.
pytest's `assert`-based approach is a straightforward way to write tests, and
its fixtures are helpful for structuring setup and teardown.

## Installation

For charm tests, install the testing framework by adding the `testing` extra of
ops in your unit testing environment. For example, in `pyproject.toml`:

```toml
[dependency-groups]
test = ['ops[testing]<4.0']
```

Ops checks if `ops-scenario` is installed, and, if so, makes the classes
(such as `Context`, `State`, and `Relation`) available in the `ops.testing`
namespace. Use `from ops import testing` rather than importing the `scenario`
package.

`ops-scenario` supports the same platforms and Python versions as ops itself.

## Documentation

 * To get started, work through our ['Write your first Kubernetes charm' tutorial](https://ops.readthedocs.io/en/latest/tutorial/from-zero-to-hero-write-your-first-kubernetes-charm/create-a-minimal-kubernetes-charm.html#write-unit-tests-for-your-charm), following the instructions for adding
   unit tests at the end of each chapter.
 * When you need to write a test that involves specific ops functionality,
   refer to our [how-to guides](https://ops.readthedocs.io/en/latest/howto/index.html)
   which all conclude with examples of tests of the ops functionality.
 * Use our extensive [reference documentation](https://ops.readthedocs.io/en/latest/reference/ops-testing.html#ops-testing) when you need to know how each `testing` object works. These
   docs are also available via the standard Python `help()` functionality and in
   your IDE.

[**Read the full documentation**](https://ops.readthedocs.io/)

## Community

`ops-scenario` is a member of the Charming family. It's an open source project
that warmly welcomes community contributions, suggestions, fixes and
constructive feedback.

* Read our [code of conduct](https://ubuntu.com/community/ethos/code-of-conduct):
  As a community we adhere to the Ubuntu code of conduct.
* [Get support](https://discourse.charmhub.io/): Discourse is the go-to forum
  for all Ops-related discussions, including around testing.
* Join our [online chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com):
  Meet us in the #charmhub-charmdev channel on Matrix.
* [Report bugs](https://github.com/canonical/operator/issues): We want to know
  about the problems so we can fix them.
* [Contribute docs](https://github.com/canonical/operator/blob/main/HACKING.md#contributing-documentation):
  Get started on GitHub.

## Contributing and developing

Anyone can contribute to ops and `ops-scenario`. It's best to start by
[opening an issue](https://github.com/canonical/operator/issues) with a clear
description of the problem or feature request, but you can also
[open a pull request](https://github.com/canonical/operator/pulls) directly.

Read our [guide](./CONTRIBUTING.md) for more details on how to work on and
contribute to `ops-scenario`.

Currently, releases of `ops-scenario` are done in lockstep with releases of ops
itself, with matching minor and bugfix release numbers. The ops documentation
outlines how to create a new release.
