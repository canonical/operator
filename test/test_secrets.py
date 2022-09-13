import typing
from collections import defaultdict
from contextlib import contextmanager
from functools import wraps
from itertools import count
from typing import Optional, List, Dict, TypedDict, Union, Set, Literal, Callable
from unittest.mock import Mock

import pytest

import ops.model
from ops.charm import SecretChangedEvent
from ops.model import Secret

if typing.TYPE_CHECKING:
    pass

SecretMetadata = TypedDict('SecretMetadata', {
    'label': str,
    'description': str,
    'expire': str,
    'rotate': str,
    'owner': Literal['unit', 'application'],
    'content': Dict[str, str],
})

RetractedRevision = object()
ALL = object()


def _check_ownership(own):
    def decorator(fn):
        @wraps(fn)
        def wrapper(self, secret_id, *args, **kwargs):
            if self._god_mode:
                return fn(self, secret_id, *args, **kwargs)

            # assume that arg[0] is secret_id!
            owns = self._owners[secret_id] in {self.unit_name, self.app_name}

            if own and not owns:
                raise MockSecretsBackend.OwnershipError(
                    "You cannot call {} unless you own {}".format(fn, secret_id))
            elif not own and owns:
                raise MockSecretsBackend.OwnershipError(
                    "You cannot call {} as an owner of {}".format(fn, secret_id))

            return fn(self, secret_id, *args, **kwargs)
        return wrapper
    return decorator


class MockSecretsBackend:
    class OwnershipError(RuntimeError):
        pass

    def __init__(self, this_unit: str,
                 god_mode: bool = True):
        RelationID = int
        SecretID = str
        UnitName = str

        # used to switch the backend between
        #   'god mode' -> no permission checks and all
        #   'charm mode' -> permission checks enforced! the backend will behave as a 'real' backend would.
        self._god_mode = god_mode
        self.unit_name = this_unit
        self.app_name = this_unit.split('/')[0]

        self._ctr = count()
        self._secret_ids = set()  # type: Set[SecretID]
        self._scopes = defaultdict(lambda: defaultdict(
            list))  # type: Dict[SecretID, Dict[RelationID, Optional[List[UnitName]]]]  # noqa
        self._revisions = defaultdict(
            list)  # type: Dict[SecretID, List[Union[SecretMetadata, RetractedRevision]]]
        self._owners = {}  # type: Dict[SecretID, UnitName]

        # Which revision are we tracking, for every secret we know (but don't own)?
        self._tracking = {}  # type: Dict[SecretID, int]

        self._relation_list_mock = {}

    def relation_list(self, id: int):
        return self._relation_list_mock[id]

    @contextmanager
    def _god_mode_ctx(self, value: bool = True):
        """Do temporarily as if you have power, or not."""
        gm = self._god_mode
        self._god_mode = value
        yield
        self._god_mode = gm

    def _new_secret_id(self):
        return f"secret:{next(self._ctr)}"

    @_check_ownership(own=True)
    def secret_set(self, secret_id: str, **kwargs):
        self._revisions[secret_id].append(kwargs)

    @_check_ownership(own=True)
    def secret_remove(self, secret_id: str, revision: Optional[int] = None):
        if revision is None:
            self._secret_ids.remove(secret_id)
            del self._revisions[secret_id]
        else:
            self._revisions[secret_id][revision] = RetractedRevision

    @_check_ownership(own=True)
    def secret_grant(self, secret_id: str, relation_id: int, unit_id: Optional[str] = None):
        readers = self._scopes[secret_id][relation_id]
        if ALL in readers:
            raise RuntimeError(f'cannot grant further access to {secret_id}: {relation_id}; '
                               f'access is already ALL')
        readers.append(unit_id or ALL)

    @_check_ownership(own=True)
    def secret_revoke(self, secret_id: str, relation_id: int, unit_id: Optional[str] = None):
        if not unit_id:
            del self._scopes[secret_id][relation_id]
        else:
            self._scopes[secret_id][relation_id].remove(unit_id)

    # no checks: anyone can add a secret
    def secret_add(self, **kwargs) -> str:
        secret_id = self._new_secret_id()
        self._secret_ids.add(secret_id)
        self._owners[secret_id] = self.unit_name
        self._revisions[secret_id].append(kwargs)
        return secret_id

    def secret_ids(self) -> List[str]:
        return list(self._secret_ids)

    @_check_ownership(own=False)
    def secret_get(self, secret_id: str, key: Optional[str] = None,
                   label: Optional[str] = None,
                   update: bool = False,
                   peek: bool = False) -> Union[str, Dict[str, str]]:

        if label:
            self.secret_set(secret_id, label=label)

        latest_revision = len(self._revisions[secret_id]) - 1

        # implicitly update if we're not tracking any specific revision yet
        if not self._tracking.get(secret_id):
            # FIXME: check this logic;
            #  cfr. https://docs.google.com/document/d/1CQckRwyhbdK8cgiuy0oOw3Ic8DAuJ8dne8T44F2xzu0/edit?disco=AAAAd1WRfBE
            update = True

        if update:
            self._tracking[secret_id] = latest_revision

        revision = latest_revision if peek else self._tracking[secret_id]

        content = self._get_content(secret_id, revision)
        if key:
            return content[key]
        return content

    def _get_content(self, secret_id: str, revision: int):
        return self._revisions[secret_id][revision]['content']

    def secret_meta(self, secret_id: str) -> Dict[str, str]:
        revisions = self._revisions[secret_id]
        latest = revisions[-1]

        return {
            secret_id: {
                "label": latest['label'],
                "revision": len(revisions) - 1,
                "expires": latest['expire'],
                "rotation": latest['rotate'],
                "rotates": "2022-08-31T12:31:56Z"  # not implemented
            }
        }


@pytest.fixture
def backend():
    return MockSecretsBackend('myapp/0')


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
        with pytest.raises(Exception):  # todo: exceptions
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


@pytest.fixture
def framework():
    class TestFramework:
        def __init__(self):
            class TestModel:
                def __init__(self):
                    self._backend = MockSecretsBackend('myapp/0')

            self.model = TestModel()

    return TestFramework()


def test_secret_event_snapshots(framework):
    sec = Secret(framework.model._backend, 'secret:1234567',
                 label='bar', revision=7, am_owner=True)
    e1 = SecretChangedEvent('', sec)
    e2 = SecretChangedEvent('', None)
    e2.framework = framework
    e2.restore(e1.snapshot())
    assert e1.secret.__dict__ == e2.secret.__dict__
