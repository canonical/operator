# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import collections
import datetime
from typing import Any, Literal, cast
from unittest.mock import ANY

import pytest
from scenario import Context
from scenario.state import Relation, Secret, State

import ops
from test.charms.test_secrets.src.charm import Result, SecretsCharm
from tests.helpers import trigger


@pytest.fixture(scope='function')
def mycharm() -> type[ops.CharmBase]:
    class MyCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            for evt in self.on.events().values():
                self.framework.observe(evt, self._on_event)

        def _on_event(self, event: ops.EventBase):
            pass

    return MyCharm


def test_get_secret_no_secret(mycharm: type[ops.CharmBase]):
    ctx = Context(mycharm, meta={'name': 'local'})
    with ctx(ctx.on.update_status(), State()) as mgr:
        with pytest.raises(ops.SecretNotFoundError):
            assert mgr.charm.model.get_secret(id='foo')
        with pytest.raises(ops.SecretNotFoundError):
            assert mgr.charm.model.get_secret(label='foo')


@pytest.mark.parametrize('owner', ('app', 'unit'))
def test_get_secret(mycharm: type[ops.CharmBase], owner: Literal['app', 'unit']):
    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret({'a': 'b'}, owner=owner)
    with ctx(
        state=State(secrets={secret}),
        event=ctx.on.update_status(),
    ) as mgr:
        assert mgr.charm.model.get_secret(id=secret.id).get_content()['a'] == 'b'


@pytest.mark.parametrize('owner', ('app', 'unit'))
def test_get_secret_get_refresh(mycharm: type[ops.CharmBase], owner: Literal['app', 'unit']):
    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret(
        tracked_content={'a': 'b'},
        latest_content={'a': 'c'},
        owner=owner,
    )
    with ctx(
        ctx.on.update_status(),
        State(secrets={secret}),
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(id=secret.id).get_content(refresh=True)['a'] == 'c'


@pytest.mark.parametrize('app', (True, False))
def test_get_secret_nonowner_peek_update(mycharm: type[ops.CharmBase], app: bool):
    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret(
        tracked_content={'a': 'b'},
        latest_content={'a': 'c'},
    )
    with ctx(
        ctx.on.update_status(),
        State(
            leader=app,
            secrets={secret},
        ),
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(id=secret.id).get_content()['a'] == 'b'
        assert charm.model.get_secret(id=secret.id).peek_content()['a'] == 'c'
        # Verify that the peek has not refreshed:
        assert charm.model.get_secret(id=secret.id).get_content()['a'] == 'b'

        assert charm.model.get_secret(id=secret.id).get_content(refresh=True)['a'] == 'c'
        assert charm.model.get_secret(id=secret.id).get_content()['a'] == 'c'


@pytest.mark.parametrize('owner', ('app', 'unit'))
def test_get_secret_owner_peek_update(mycharm: type[ops.CharmBase], owner: Literal['app', 'unit']):
    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret(
        tracked_content={'a': 'b'},
        latest_content={'a': 'c'},
        owner=owner,
    )
    with ctx(
        ctx.on.update_status(),
        State(
            secrets={secret},
        ),
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(id=secret.id).get_content()['a'] == 'b'
        assert charm.model.get_secret(id=secret.id).peek_content()['a'] == 'c'
        # Verify that the peek has not refreshed:
        assert charm.model.get_secret(id=secret.id).get_content()['a'] == 'b'
        assert charm.model.get_secret(id=secret.id).get_content(refresh=True)['a'] == 'c'


@pytest.mark.parametrize('owner', ('app', 'unit'))
def test_secret_changed_owner_evt_fails(
    mycharm: type[ops.CharmBase], owner: Literal['app', 'unit']
):
    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret(
        tracked_content={'a': 'b'},
        latest_content={'a': 'c'},
        owner=owner,
    )
    with pytest.raises(ValueError):
        _ = ctx.on.secret_changed(secret)


@pytest.mark.parametrize(
    'evt_suffix,revision',
    [
        ('rotate', None),
        ('expired', 1),
        ('remove', 1),
    ],
)
def test_consumer_events_failures(
    mycharm: type[ops.CharmBase], evt_suffix: str, revision: int | None
):
    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret(
        tracked_content={'a': 'b'},
        latest_content={'a': 'c'},
    )
    kwargs: dict[str, Any] = {'secret': secret}
    if revision is not None:
        kwargs['revision'] = revision
    with pytest.raises(ValueError):
        _ = getattr(ctx.on, f'secret_{evt_suffix}')(**kwargs)


@pytest.mark.parametrize('app', (True, False))
def test_add(mycharm: type[ops.CharmBase], app: bool):
    ctx = Context(mycharm, meta={'name': 'local'})
    with ctx(
        ctx.on.update_status(),
        State(leader=app),
    ) as mgr:
        charm = mgr.charm
        if app:
            charm.app.add_secret({'foo': 'bar'}, label='mylabel')
        else:
            charm.unit.add_secret({'foo': 'bar'}, label='mylabel')
        output = mgr.run()

    assert output.secrets
    secret = output.get_secret(label='mylabel')
    assert secret.latest_content == secret.tracked_content == {'foo': 'bar'}
    assert secret.label == 'mylabel'


def test_set_legacy_behaviour(mycharm: type[ops.CharmBase]):
    # in juju < 3.1.7, secret owners always used to track the latest revision.
    # ref: https://bugs.launchpad.net/juju/+bug/2037120
    ctx = Context(mycharm, meta={'name': 'local'}, juju_version='3.1.6')
    rev1, rev2 = {'foo': 'bar'}, {'foo': 'baz', 'qux': 'roz'}
    with ctx(
        ctx.on.update_status(),
        State(),
    ) as mgr:
        charm = mgr.charm
        secret: ops.Secret = charm.unit.add_secret(rev1, label='mylabel')
        assert (
            secret.get_content()
            == secret.peek_content()
            == secret.get_content(refresh=True)
            == rev1
        )

        secret.set_content(rev2)
        # We need to get the secret again, because ops caches the content in
        # the object.
        secret: ops.Secret = charm.model.get_secret(label='mylabel')
        assert (
            secret.get_content()
            == secret.peek_content()
            == secret.get_content(refresh=True)
            == rev2
        )

        state_out = mgr.run()

    assert (
        state_out.get_secret(label='mylabel').tracked_content
        == state_out.get_secret(label='mylabel').latest_content
        == rev2
    )


def test_set(mycharm: type[ops.CharmBase]):
    ctx = Context(mycharm, meta={'name': 'local'})
    rev1, rev2 = {'foo': 'bar'}, {'foo': 'baz', 'qux': 'roz'}
    with ctx(
        ctx.on.update_status(),
        State(),
    ) as mgr:
        charm = mgr.charm
        secret: ops.Secret = charm.unit.add_secret(rev1, label='mylabel')
        assert (
            secret.get_content()
            == secret.peek_content()
            == secret.get_content(refresh=True)
            == rev1
        )

        # TODO: if this is done in the same event hook, it's more complicated
        # than this. Figure out what we should do here.
        # Also the next test, for Juju 3.3
        secret.set_content(rev2)
        assert secret.get_content() == rev1
        assert secret.peek_content() == secret.get_content(refresh=True) == rev2

        state_out = mgr.run()

    assert (
        state_out.get_secret(label='mylabel').tracked_content
        == state_out.get_secret(label='mylabel').latest_content
        == rev2
    )


def test_set_juju33(mycharm: type[ops.CharmBase]):
    ctx = Context(mycharm, meta={'name': 'local'}, juju_version='3.3.1')
    rev1, rev2 = {'foo': 'bar'}, {'foo': 'baz', 'qux': 'roz'}
    with ctx(
        ctx.on.update_status(),
        State(),
    ) as mgr:
        charm = mgr.charm
        secret: ops.Secret = charm.unit.add_secret(rev1, label='mylabel')
        assert secret.get_content() == rev1

        secret.set_content(rev2)
        assert secret.get_content() == rev1
        assert secret.peek_content() == rev2
        assert secret.get_content(refresh=True) == rev2

        state_out = mgr.run()

    assert (
        state_out.get_secret(label='mylabel').tracked_content
        == state_out.get_secret(label='mylabel').latest_content
        == rev2
    )


@pytest.mark.parametrize('app', (True, False))
def test_meta(mycharm: type[ops.CharmBase], app: bool):
    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret(
        {'a': 'b'},
        owner='app' if app else 'unit',
        label='mylabel',
        description='foobarbaz',
        rotate=ops.SecretRotate.HOURLY,
    )
    with ctx(
        ctx.on.update_status(),
        State(
            leader=True,
            secrets={secret},
        ),
    ) as mgr:
        charm = mgr.charm
        assert charm.model.get_secret(label='mylabel')

        secret = charm.model.get_secret(id=secret.id)
        info = secret.get_info()

        assert secret.label is None
        assert info.description == 'foobarbaz'
        assert info.label == 'mylabel'
        assert info.rotation == ops.SecretRotate.HOURLY


@pytest.mark.parametrize('leader', (True, False))
@pytest.mark.parametrize('owner', ('app', 'unit', None))
def test_secret_permission_model(
    mycharm: type[ops.CharmBase], leader: bool, owner: Literal['app', 'unit'] | None
):
    expect_manage = bool(
        # if you're the leader and own this app secret
        (owner == 'app' and leader)
        # you own this secret
        or (owner == 'unit')
    )

    ctx = Context(mycharm, meta={'name': 'local'})
    scenario_secret = Secret(
        {'a': 'b'},
        label='mylabel',
        owner=owner,
        description='foobarbaz',
        rotate=ops.SecretRotate.HOURLY,
    )
    secret_id = scenario_secret.id
    with ctx(
        ctx.on.update_status(),
        State(
            leader=leader,
            secrets={scenario_secret},
        ),
    ) as mgr:
        # can always view
        secret: ops.Secret = mgr.charm.model.get_secret(id=secret_id)
        assert secret.get_content()['a'] == 'b'
        assert secret.peek_content()
        assert secret.get_content(refresh=True)

        if expect_manage:
            assert secret.get_content()
            assert secret.peek_content()
            assert secret.get_content(refresh=True)

            assert secret.get_info()
            secret.set_content({'foo': 'boo'})
            assert secret.get_content() == {'a': 'b'}  # rev1!
            assert secret.get_content(refresh=True) == {'foo': 'boo'}

            secret.remove_all_revisions()

        else:  # cannot manage
            # nothing else to do directly if you can't get a hold of the Secret instance
            # but we can try some raw backend calls
            with pytest.raises(ops.ModelError):
                secret.get_info()

            with pytest.raises(ops.ModelError):
                secret.set_content(content={'boo': 'foo'})


@pytest.mark.parametrize('app', (True, False))
def test_grant(mycharm: type[ops.CharmBase], app: bool):
    ctx = Context(mycharm, meta={'name': 'local', 'requires': {'foo': {'interface': 'bar'}}})
    secret = Secret(
        {'a': 'b'},
        owner='unit',
        label='mylabel',
        description='foobarbaz',
        rotate=ops.SecretRotate.HOURLY,
    )
    with ctx(
        ctx.on.update_status(),
        State(
            relations=[Relation('foo', 'remote')],
            secrets={secret},
        ),
    ) as mgr:
        charm = mgr.charm
        secret = charm.model.get_secret(label='mylabel')
        foo = charm.model.get_relation('foo')
        assert foo is not None
        if app:
            secret.grant(relation=foo)
        else:
            secret.grant(relation=foo, unit=foo.units.pop())
        output = mgr.run()
    vals = list(output.get_secret(label='mylabel').remote_grants.values())
    assert vals == [{'remote'}] if app else [{'remote/0'}]


def test_update_metadata(mycharm: type[ops.CharmBase]):
    exp = datetime.datetime(2050, 12, 12)

    ctx = Context(mycharm, meta={'name': 'local'})
    secret = Secret(
        {'a': 'b'},
        owner='unit',
        label='mylabel',
    )
    with ctx(
        ctx.on.update_status(),
        State(
            secrets={secret},
        ),
    ) as mgr:
        secret = mgr.charm.model.get_secret(label='mylabel')
        secret.set_info(
            label='babbuccia',
            description='blu',
            expire=exp,
            rotate=ops.SecretRotate.DAILY,
        )
        output = mgr.run()

    secret_out = output.get_secret(label='babbuccia')
    assert secret_out.label == 'babbuccia'
    assert secret_out.rotate == ops.SecretRotate.DAILY
    assert secret_out.description == 'blu'
    assert secret_out.expire == exp


@pytest.mark.parametrize('leader', (True, False))
def test_grant_after_add(leader: bool):
    class GrantingCharm(ops.CharmBase):
        def __init__(self, *args: Any):
            super().__init__(*args)
            self.framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.EventBase):
            if leader:
                secret = self.app.add_secret({'foo': 'bar'})
            else:
                secret = self.unit.add_secret({'foo': 'bar'})
            secret.grant(self.model.relations['bar'][0])

    state = State(leader=leader, relations={Relation('bar')})
    ctx = Context(GrantingCharm, meta={'name': 'foo', 'provides': {'bar': {'interface': 'bar'}}})
    ctx.run(ctx.on.start(), state)


def test_grant_nonowner(mycharm: type[ops.CharmBase]):
    secret = Secret(
        {'a': 'b'},
        label='mylabel',
        description='foobarbaz',
        rotate=ops.SecretRotate.HOURLY,
    )
    secret_id = secret.id

    def post_event(charm: ops.CharmBase):
        secret = charm.model.get_secret(id=secret_id)
        secret = charm.model.get_secret(label='mylabel')
        foo = charm.model.get_relation('foo')
        assert foo is not None

        with pytest.raises(ops.ModelError):
            secret.grant(relation=foo)

    trigger(
        State(
            relations={Relation('foo', 'remote')},
            secrets={secret},
        ),
        'update_status',
        mycharm,
        meta={'name': 'local', 'requires': {'foo': {'interface': 'bar'}}},
        post_event=post_event,
    )


def test_add_grant_revoke_remove():
    class GrantingCharm(ops.CharmBase):
        pass

    ctx = Context(GrantingCharm, meta={'name': 'foo', 'provides': {'bar': {'interface': 'bar'}}})
    relation_remote_app = 'remote_secret_desirerer'
    relation_id = 42

    state = State(
        leader=True,
        relations={Relation('bar', remote_app_name=relation_remote_app, id=relation_id)},
    )

    with ctx(ctx.on.start(), state) as mgr:
        charm = mgr.charm
        secret = charm.app.add_secret({'foo': 'bar'}, label='mylabel')
        bar_relation = charm.model.relations['bar'][0]

        secret.grant(bar_relation)
        output = mgr.run()

    assert output.secrets
    scenario_secret = output.get_secret(label='mylabel')
    assert relation_remote_app in scenario_secret.remote_grants[relation_id]

    with ctx(ctx.on.start(), output) as mgr:
        charm: GrantingCharm = mgr.charm
        secret = charm.model.get_secret(label='mylabel')
        secret.revoke(bar_relation)
        output = mgr.run()

    scenario_secret = output.get_secret(label='mylabel')
    assert scenario_secret.remote_grants == {}

    with ctx(ctx.on.start(), output) as mgr:
        charm: GrantingCharm = mgr.charm
        secret = charm.model.get_secret(label='mylabel')
        secret.remove_all_revisions()
        output = mgr.run()

    with pytest.raises(KeyError):
        output.get_secret(label='mylabel')


def test_secret_removed_event():
    class SecretCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.secret_remove, self._on_secret_remove)

        def _on_secret_remove(self, event: Any):
            event.secret.remove_revision(event.revision)

    ctx = Context(SecretCharm, meta={'name': 'foo'})
    secret = Secret({'a': 'b'}, owner='app')
    old_revision = 42
    state = ctx.run(
        ctx.on.secret_remove(secret, revision=old_revision),
        State(leader=True, secrets={secret}),
    )
    assert secret in state.secrets
    assert ctx.removed_secret_revisions == [old_revision]


def test_secret_expired_event():
    class SecretCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.secret_expired, self._on_secret_expired)

        def _on_secret_expired(self, event: Any):
            event.secret.set_content({'password': 'newpass'})
            event.secret.remove_revision(event.revision)

    ctx = Context(SecretCharm, meta={'name': 'foo'})
    secret = Secret({'password': 'oldpass'}, owner='app')
    old_revision = 42
    state = ctx.run(
        ctx.on.secret_expired(secret, revision=old_revision),
        State(leader=True, secrets={secret}),
    )
    assert state.get_secret(id=secret.id).latest_content == {'password': 'newpass'}
    assert ctx.removed_secret_revisions == [old_revision]


def test_remove_bad_revision():
    class SecretCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.secret_remove, self._on_secret_remove)

        def _on_secret_remove(self, event: Any):
            with pytest.raises(ValueError):
                event.secret.remove_revision(event.revision)

    ctx = Context(SecretCharm, meta={'name': 'foo'})
    secret = Secret({'a': 'b'}, owner='app')
    ctx.run(
        ctx.on.secret_remove(secret, revision=secret._latest_revision),
        State(leader=True, secrets={secret}),
    )
    ctx.run(
        ctx.on.secret_remove(secret, revision=secret._tracked_revision),
        State(leader=True, secrets={secret}),
    )


def test_set_label_on_get():
    class SecretCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.framework.observe(self.on.start, self._on_start)

        def _on_start(self, _: ops.EventBase):
            id = self.unit.add_secret({'foo': 'bar'}).id
            secret = self.model.get_secret(id=id, label='label1')
            assert secret.label == 'label1'
            secret = self.model.get_secret(id=id, label='label2')
            assert secret.label == 'label2'

    ctx = Context(SecretCharm, meta={'name': 'foo'})
    state = ctx.run(ctx.on.start(), State())
    assert state.get_secret(label='label2').tracked_content == {'foo': 'bar'}


def test_no_additional_positional_arguments():
    with pytest.raises(TypeError):
        Secret({}, {})  # type: ignore


def test_default_values():
    contents = {'foo': 'bar'}
    secret = Secret(contents)
    assert secret.latest_content == secret.tracked_content == contents
    assert secret.id.startswith('secret:')
    assert secret.label is None
    assert secret.description is None
    assert secret.owner is None
    assert secret.rotate is None
    assert secret.expire is None
    assert secret.remote_grants == {}


def test_add_secret(secrets_context: Context[SecretsCharm]):
    state = State(leader=True)
    state = secrets_context.run(secrets_context.on.action('add-secret'), state)

    result = cast('Result', secrets_context.action_results)
    assert result is not None
    assert result.get('secretid')

    scenario_secret = next(iter(state.secrets))

    common_assertions(scenario_secret, result)

    assert result == {
        'after': {
            'info': ANY,  # relying on scaffolding check
            'tracked': {'foo': 'bar'},
            'latest': {'foo': 'bar'},
        },
        'secretid': ANY,
    }

    assert scenario_secret._tracked_revision == scenario_secret._latest_revision


@pytest.mark.parametrize(
    'fields',
    [
        '',
        'label',
        'description',
        'expire',
        'rotate',
        'label,description',
        'description,expire,rotate',
        'label,description,expire,rotate',
    ],
)
def test_add_secret_with_metadata(secrets_context: Context[SecretsCharm], fields: str):
    state = State(leader=True)
    state = secrets_context.run(
        secrets_context.on.action('add-with-meta', params={'fields': fields}), state
    )
    scenario_secret = next(iter(state.secrets))
    result = cast('Result', secrets_context.action_results)
    assert 'after' in result
    assert result['after']
    info = result['after']['info']
    assert info

    common_assertions(scenario_secret, result)

    if 'label' in fields:
        assert scenario_secret.label == 'label1'
        assert info['label'] == 'label1'
    if 'description' in fields:
        assert scenario_secret.description == 'description1'
        assert info['description'] == 'description1'
    if 'expire' in fields:
        assert scenario_secret.expire == datetime.datetime(2020, 1, 1, 0, 0, 0)
        assert info['expires'] == datetime.datetime(2020, 1, 1, 0, 0, 0)
    if 'rotate' in fields:
        assert scenario_secret.rotate == ops.SecretRotate.DAILY
        assert info['rotation'] == ops.SecretRotate.DAILY
        # https://github.com/canonical/operator/issues/2104
        assert info['rotates'] is None

    assert scenario_secret._tracked_revision == scenario_secret._latest_revision


@pytest.mark.parametrize('lookup_by', ['id', 'label'])
@pytest.mark.parametrize(
    'flow',
    [
        'content,label,description,expire,rotate',
        'content,description,content,description',
        'rotate,content,rotate,content,rotate',
        'label,content,label,content',
    ],
)
def test_set_secret(
    secrets_context: Context[SecretsCharm], flow: str, lookup_by: Literal['id', 'label']
):
    secret = Secret({'some': 'content'}, owner='app', id='theid', label='thelabel')
    state = State(leader=True, secrets={secret})
    params = {'flow': flow, f'secret{lookup_by}': f'the{lookup_by}'}
    state = secrets_context.run(secrets_context.on.action('set-secret-flow', params=params), state)
    scenario_secret = state.get_secret(id='theid')
    result = cast('Result', secrets_context.action_results)
    assert 'after' in result
    assert result['after']
    info = result['after']['info']
    assert info

    common_assertions(scenario_secret, result)

    counts = collections.Counter(flow.split(','))
    if counts['content']:
        assert result['after']['latest'] == {'val': str(counts['content'])}
    if counts['label']:
        assert info['label'] == f'label{counts["label"]}'
    if counts['description']:
        assert info['description'] == f'description{counts["description"]}'
    if counts['expire']:
        assert info['expires'] == datetime.datetime(2010 + counts['expire'], 1, 1, 0, 0)
    if counts['rotate']:
        rotation_values = ['sentinel', *ops.SecretRotate.__members__.values()]
        assert info['rotation'] == rotation_values[counts['rotate']]


def common_assertions(scenario_secret: Secret | None, result: Result):
    if scenario_secret:
        assert scenario_secret.owner == 'app'
        assert not scenario_secret.remote_grants

        after = result.get('after')
        assert after is not None
        info = after['info']
        assert info is not None
        # Verify that the unit and the scaffolding see the same data
        #
        # Scenario presents a secret with a full secret URI to the charm
        # however, the id on the scenario Secret object is a plain id
        assert scenario_secret.id.split('/')[-1] == info['id'].split('/')[-1]
        assert scenario_secret.label == info['label']
        assert scenario_secret._latest_revision == info['revision']
        assert scenario_secret.expire == info['expires']
        assert scenario_secret.rotate == info['rotation']
        assert scenario_secret.description == info['description']
        # https://github.com/canonical/operator/issues/2104
        assert info['rotates'] is None

        assert scenario_secret.tracked_content == after['tracked']
        assert scenario_secret.latest_content == after['latest']
