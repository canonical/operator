import inspect
from contextlib import contextmanager
from unittest.mock import Mock

import pytest
import yaml

import ops.model
from ops import testing
from ops.charm import SecretChangedEvent, CharmBase
from ops.framework import EventBase
from ops.model import Secret
from ops.testing import _TestingModelBackend, Harness

SECRET_METHODS = ("secret_set",
                  "secret_remove",
                  "secret_grant",
                  "secret_revoke",
                  "secret_add",
                  "secret_ids",
                  "secret_get",
                  "secret_meta")


@pytest.mark.parametrize('method', SECRET_METHODS, ids=SECRET_METHODS)
def test_testing_secrets_manager_api_completeness(method):
    # Assert that the signatures of the testing model backend's secret-methods match
    # the real backend ones.
    mmb_sig = inspect.signature(getattr(ops.model._ModelBackend, method))
    tsm_sig = inspect.signature(getattr(testing._TestingSecretManager, method))
    tmb_sig = inspect.signature(getattr(_TestingModelBackend, method))

    assert tsm_sig == mmb_sig, 'the _TestingSecretManager and ' \
                               '_ModelBackend signatures have diverged'
    assert tmb_sig == mmb_sig, 'the _TestingModelBackend and ' \
                               '_ModelBackend signatures have diverged'


class _TestingSecretManager(testing._TestingSecretManager):
    """Allows testing the secrets manager in isolation."""

    def __init__(self, this_unit: str, _god_mode: bool = False):
        super().__init__(this_unit, None)
        self._god_mode = _god_mode

    @property
    def _hook_is_running(self) -> bool:
        # used to switch the backend between
        #   'god mode' -> no permission checks and all
        #   'charm mode' -> permission checks enforced!
        #       the backend will behave as a 'real' backend would.
        return not self._god_mode

    @contextmanager
    def _god_mode_ctx(self, value: bool = True):
        """Do temporarily as if you have power, or not."""
        gm = self._god_mode
        self._god_mode = value
        yield
        self._god_mode = gm


@pytest.fixture
def backend():
    return _TestingSecretManager('myapp/0')


@pytest.fixture
def model(backend):
    return ops.model.Model(
        ops.charm.CharmMeta({'name': 'myapp'}),
        backend
    )


def test_secret_add_and_get(model, backend):
    secret = model.unit.add_secret('hey', {'foo': 'bar'})
    # I always have access to the secrets I created
    with backend._god_mode_ctx(value=False):
        secret_2 = model.get_secret(secret.id)
    assert secret == secret_2


def test_cannot_get_removed_secret(model):
    secret = model.unit.add_secret('hey', {'foo': 'bar'})
    secret.remove()

    # god mode or not, if a secret is gone, it's gone.
    with pytest.raises(Exception):  # todo: exceptions
        model.get_secret(secret.id)


def test_grant_secret(model, backend):
    secret = model.unit.add_secret('hey', {'foo': 'bar'})
    backend._relation_list_mock[1] = 'remote/0'
    secret.grant('remote/0',
                 ops.model.Relation('db', 1, is_peer=False,
                                    backend=backend, cache=model._cache,
                                    our_unit=model.unit))

    with backend._god_mode_ctx(True):
        with pytest.raises(RuntimeError):  # raised by Model, not Backend!
            secret.get()

        backend.secret_get(secret.id)  # this works in god mode

    with backend._god_mode_ctx(False):
        with pytest.raises(testing.OwnershipError):
            backend.secret_get(secret.id)


def test_cannot_get_revoked_secret(model, backend):
    secret = model.unit.add_secret('hey', {'foo': 'bar'})
    backend._relation_list_mock[1] = 'remote/0'
    secret.grant('remote/0',
                 ops.model.Relation('db', 1, is_peer=False,
                                    backend=backend, cache=model._cache,
                                    our_unit=model.unit))
    backend.secret_revoke(secret.id, 1)

    with pytest.raises(Exception):  # todo: exceptions
        secret.get()

def test_secret_event_snapshot(backend):
    sec = Secret(backend, 'secret:1234567',
                 label='bar', revision=7, am_owner=True)
    e1 = SecretChangedEvent('', sec)
    e2 = SecretChangedEvent('', None)

    e2.framework = Mock(model=Mock(_backend=backend))
    e2.restore(e1.snapshot())
    assert e1.secret.__dict__ == e2.secret.__dict__



def charm_type():
    class InvokeEvent(EventBase):
        pass

    class SecretTesterCharm(CharmBase):
        def __init__(self, framework, key=None):
            super().__init__(framework, key)
            self._callback = None
            self.on.define_event('invoke', InvokeEvent)
            self.framework.observe(self.on.invoke, self._on_invoke)

        def run(self, fn):
            if self._callback:
                raise RuntimeError('already in a run scope')

            self._callback = fn
            self._invoke()
            self._callback = None

        def _invoke(self):
            self.on.invoke.emit()

        def _on_invoke(self, event):
            self._callback()

    return SecretTesterCharm


@pytest.fixture(scope='function')
def owner_harness():
    return Harness(charm_type(), meta=yaml.safe_dump({'name': 'owner'}))


@pytest.fixture(scope='function')
def owner(owner_harness):
    owner_harness.begin()
    return owner_harness.charm


@pytest.fixture(scope='function')
def holder_harness():
    return Harness(charm_type(), meta=yaml.safe_dump({'name': 'holder'}))


@pytest.fixture(scope='function')
def holder(holder_harness, owner_harness):
    holder_harness.begin()
    bind(owner_harness, holder_harness)
    return holder_harness.charm


def bind(owner_harness: Harness, holder_harness: Harness):
    # binds the two harnesses in such a way that the respective Secret
    # backends will work in sync
    owner_harness.model._backend._secrets._bind(holder_harness.model._backend._secrets)
    holder_harness.model._backend._secrets._bind(owner_harness.model._backend._secrets)


def grant(owner: CharmBase, secret_specifier: str, holder: CharmBase,
          relation_name='db',
          relation_id=1,
          is_peer=False):

    # simulate a relation
    owner.model._backend._secrets._relation_list_mock[1] = holder.unit.name
    holder.model._backend._secrets._relation_list_mock[1] = owner.unit.name

    owner.model.get_secret(secret_specifier).grant(
        holder.unit,
        relation=ops.model.Relation(relation_name, relation_id, is_peer=is_peer,
                                    backend=owner.model._backend,
                                    cache=owner.model._cache,
                                    our_unit=owner.model.unit))


def test_owner_create_secret(owner, holder):
    sec_id = ''

    @owner.run
    def create_secret():
        nonlocal sec_id
        secret = owner.app.add_secret('my_label', {'a': 'b'})
        sec_id = secret.id
        assert secret._am_owner

        # now we can also get it by:
        secret2 = owner.model.get_secret('my_label')
        assert secret == secret2

        # however we can't inspect the contents:
        with pytest.raises(ops.model.OwnershipError):
            secret.get()

    @holder.run
    def secret_get_without_access():
        nonlocal sec_id
        # labels are local: my_label is how OWNER knows this secret, not holder.
        with pytest.raises(ops.model.InvalidSecretIDError):
            assert holder.model.get_secret('my_label')

        with pytest.raises(ops.model.SecretNotGrantedError):
            holder.model.get_secret(sec_id, label='other_label')

    @owner.run
    def grant_access():
        # simulate a relation, grant the holder access.
        grant(owner, 'my_label', holder)

    @holder.run
    def secret_get_with_access():
        nonlocal sec_id
        # as a holder, we can secret-get
        secret = holder.model.get_secret(sec_id, label='other_label')

        assert not secret._am_owner
        # we give it our own label
        secret.get(label='other_label')
        # we can get it by label as well now!
        assert holder.model.get_secret('other_label') == secret

        assert secret.get('a') == 'b'
