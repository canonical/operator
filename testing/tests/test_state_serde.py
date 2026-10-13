# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import datetime
import enum
import json
import pathlib
from collections.abc import Callable
from typing import Any, cast

import pytest
from scenario import _state_serde

import ops
import ops.version
from ops import pebble, testing

FIRST = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)


def _secret_at_revision_2(*, track_latest: bool) -> testing.Secret:
    secret = testing.Secret({'password': 'hunter2'})
    secret._update_metadata(content={'password': 'hunter3'})
    if track_latest:
        secret._track_latest_revision()
    return secret


def _container(**kwargs: Any) -> testing.State:
    return testing.State(containers={testing.Container('app', **kwargs)})


def _stored(content: dict[str, Any]) -> testing.State:
    return testing.State(stored_states={testing.StoredState(content=content)})


NON_TRIVIAL = testing.State(
    config={'log_level': 'debug', 'port': 8080, 'enabled': True},
    relations={
        testing.Relation(
            'db',
            remote_app_name='postgresql',
            remote_units_data={0: {'host': '10.0.0.1'}, 1: {'host': '10.0.0.2'}},
            remote_app_data={'version': '14'},
        ),
        testing.PeerRelation('peers', peers_data={1: {'leader': 'true'}}),
    },
    containers={
        testing.Container(
            'myapp',
            can_connect=True,
            layers={'base': pebble.Layer({'services': {'app': {'command': '/bin/app'}}})},
            service_statuses={'app': pebble.ServiceStatus.ACTIVE},
            notices=[
                testing.Notice(
                    'example.com/event',
                    type=pebble.NoticeType.CUSTOM,
                    repeat_after=datetime.timedelta(minutes=30),
                    first_occurred=FIRST,
                    last_occurred=FIRST,
                    last_repeated=FIRST,
                )
            ],
            check_infos={
                testing.CheckInfo(
                    'http', level=pebble.CheckLevel.ALIVE, status=pebble.CheckStatus.UP
                )
            },
        )
    },
    secrets={
        testing.Secret(
            {'password': 'hunter2'},
            owner='app',
            expire=datetime.datetime(2030, 12, 31, tzinfo=datetime.timezone.utc),
            rotate=ops.SecretRotate.DAILY,
            remote_grants={0: {'related-app'}},
        )
    },
    resources={testing.Resource(name='oci-image', path=pathlib.Path('/srv/image.tar'))},
    stored_states={
        testing.StoredState(
            '_stored',
            owner_path='MyCharm',
            content={
                'count': 42,
                'raw': b'\xde\xad\xbe\xef',
                'coords': (1, 2, 3),
                'tags': {'alpha', 'beta'},
                'mapping': {'nested': True},
            },
        )
    },
    opened_ports={testing.TCPPort(8080)},
    leader=True,
    unit_status=testing.ActiveStatus('ready'),
    app_status=testing.BlockedStatus('needs database'),
    workload_version='1.2.3',
    planned_units=3,
    deferred=[
        testing.DeferredEvent(
            'MyCharm/on/config_changed[1]', owner='MyCharm', observer='_on_config_changed'
        )
    ],
)


@pytest.mark.parametrize(
    'state',
    [
        pytest.param(testing.State(), id='empty'),
        pytest.param(NON_TRIVIAL, id='non-trivial'),
        pytest.param(
            testing.State(
                secrets={testing.Secret({'k': 'v'}, expire=datetime.datetime(2030, 6, 15, 12))}
            ),
            id='naive-datetime',
        ),
        pytest.param(testing.State(secrets={testing.Secret({'k': 'v'})}), id='no-datetime'),
        pytest.param(
            _container(
                notices=[testing.Notice('example.com/n', expire_after=datetime.timedelta(days=7))]
            ),
            id='timedelta',
        ),
        pytest.param(
            testing.State(resources={testing.Resource(name='bin', path='/usr/bin/tool')}),
            id='str-path',
        ),
        pytest.param(
            _container(
                mounts={
                    'cfg': testing.Mount(
                        location=pathlib.PurePosixPath('/etc/config'),
                        source=pathlib.Path('/srv/cfg'),
                    )
                }
            ),
            id='pure-posix-path',
        ),
        pytest.param(
            _container(mounts={'cfg': testing.Mount(location='/etc/config', source='/srv/cfg')}),
            id='str-mount',
        ),
        pytest.param(
            _container(check_infos={testing.CheckInfo('ready', level=pebble.CheckLevel.READY)}),
            id='check-level',
        ),
        pytest.param(_container(layers={'l': pebble.Layer({})}), id='empty-layer'),
        pytest.param(
            testing.State(
                secrets={
                    testing.Secret({'k': 'v'}, owner='app', remote_grants={2: {'other-app/0'}})
                }
            ),
            id='int-keys',
        ),
        pytest.param(_stored({'b': b''}), id='empty-bytes'),
        pytest.param(_stored({'n': ((1, 2), (3, 4))}), id='nested-tuple'),
        pytest.param(_stored({'l': [1, 2, 3]}), id='list'),
        pytest.param(_stored({'l': ['__t__']}), id='list-of-the-tag'),
        pytest.param(
            testing.State(secrets={_secret_at_revision_2(track_latest=False)}),
            id='secret-revisions',
        ),
        pytest.param(
            testing.State(secrets={_secret_at_revision_2(track_latest=True)}),
            id='secret-tracking-latest',
        ),
        *(
            pytest.param(testing.State(unit_status=status, app_status=status), id=status.name)
            for status in (
                testing.ActiveStatus('ready'),
                testing.BlockedStatus('needs config'),
                testing.WaitingStatus('waiting for db'),
                testing.MaintenanceStatus('updating'),
                testing.ErrorStatus('hook failed: "start"'),
                testing.UnknownStatus(),
            )
        ),
    ],
)
def test_state_round_trips(state: testing.State):
    out = _state_serde.decode_state(_state_serde.encode_state(state))
    assert out == state
    # Equality doesn't see every type (an enum and its value, a Path and a str)
    # or the attributes that aren't fields, but the encoding does.
    assert _state_serde.encode_state(out) == _state_serde.encode_state(state)


class _Charm(ops.CharmBase):
    pass


@pytest.mark.parametrize(
    ('name', 'kwargs'),
    [
        ('install', {}),
        ('relation_changed', {'relation': testing.Relation('db', remote_app_name='pg')}),
    ],
)
def test_event_round_trips(name: str, kwargs: dict[str, Any]):
    ctx = testing.Context(_Charm, meta={'name': 'c', 'requires': {'db': {'interface': 'db'}}})
    event = getattr(ctx.on, name)(**kwargs)
    assert _state_serde.decode_event(_state_serde.encode_event(event)) == event


class _OtherEnum(enum.Enum):
    VALUE = 'value'


class _StrEnum(str, enum.Enum):
    VALUE = 'value'


@pytest.mark.parametrize(
    ('content', 'message'),
    [
        ({'bad': object()}, "No JSON encoding for type 'object' at path '.*content.bad'"),
        ({'e': _OtherEnum.VALUE}, 'Unrecognised enum type'),
        ({'e': _StrEnum.VALUE}, 'Unrecognised enum type'),
        ({'p': pathlib.PureWindowsPath('C:/x')}, "No JSON encoding for type 'PureWindowsPath'"),
        ({(1, 2): 'x'}, 'keys must be all str or all int'),
        ({True: 1}, 'keys must be all str or all int'),
        ({'d': {'__t__': 'bytes', 'v': 'AAAA'}}, "key '__t__' at path '.*content.d'"),
        ({'l': ['__tuple__', 1]}, "starting with '__tuple__' at path '.*content.l'"),
    ],
)
def test_values_without_an_encoding_are_rejected(content: dict[Any, Any], message: str):
    state = _stored(cast('dict[str, Any]', content))
    with pytest.raises(TypeError, match=message):
        _state_serde.encode_state(state)


@pytest.mark.parametrize(
    ('encoded', 'message'),
    [
        ({'__t__': '__no_such_type__', 'v': None}, 'Unknown type tag'),
        ({'__t__': 'dc', 'cls': 'NoSuchClass', 'f': {}}, 'Unknown dataclass'),
        ({'__t__': 'enum', 'cls': 'NoSuchEnum', 'name': 'FOO'}, 'Unknown enum class'),
        ({'__t__': 'status', 'name': 'no-such-status', 'msg': ''}, 'Unknown status name'),
        ('not-a-state', 'not a State'),
    ],
)
def test_unknown_encodings_are_rejected(encoded: Any, message: str):
    payload = json.dumps({'ops_testing_version': ops.version.version, 'state': encoded})
    with pytest.raises(TypeError, match=message):
        _state_serde.decode_state(payload)


def test_an_event_payload_must_hold_an_event():
    payload = json.dumps({'ops_testing_version': ops.version.version, 'event': 'install'})
    with pytest.raises(TypeError, match='not an event'):
        _state_serde.decode_event(payload)


@pytest.mark.parametrize(
    ('kind', 'decode'),
    [('state', _state_serde.decode_state), ('event', _state_serde.decode_event)],
)
@pytest.mark.parametrize('version', ['0.0.0-does-not-exist', None])
def test_a_payload_from_another_version_is_rejected(
    kind: str, decode: Callable[[str], object], version: str | None
):
    payload = json.dumps({'ops_testing_version': version, kind: {}})
    with pytest.raises(_state_serde._VersionMismatchError) as caught:
        decode(payload)
    assert str(version) in str(caught.value)
    assert ops.version.version in str(caught.value)


def test_sets_encode_the_same_whatever_order_they_were_built_in():
    names = [f'name{i}' for i in range(20)]
    model = testing.Model('m', uuid='00000000-0000-4000-8000-000000000000')
    forwards = testing.State(model=model, stored_states={testing.StoredState(n) for n in names})
    backwards = testing.State(
        model=model, stored_states={testing.StoredState(n) for n in reversed(names)}
    )
    assert _state_serde.encode_state(forwards) == _state_serde.encode_state(backwards)


def test_the_payload_records_the_version():
    payload = json.loads(_state_serde.encode_state(testing.State()))
    assert payload['ops_testing_version'] == ops.version.version
