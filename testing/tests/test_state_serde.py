# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

from __future__ import annotations

import dataclasses
import datetime
import enum
import inspect
import json
import pathlib
import typing
import zoneinfo
from collections.abc import Callable
from typing import Any, cast

import pytest
from scenario import _state_serde, _version

import ops
from ops import pebble, testing

FIRST = datetime.datetime(2025, 1, 1, tzinfo=datetime.timezone.utc)
VERSION = _version.version


def _secret_at_revision_2(*, track_latest: bool) -> testing.Secret:
    secret = testing.Secret({'password': 'hunter2'})
    secret._update_metadata(content={'password': 'hunter3'})
    if track_latest:
        secret._track_latest_revision()
    return secret


def _container(**kwargs: Any) -> testing.State:
    return testing.State(containers={testing.Container('app', **kwargs)})


def _layer(**service: Any) -> pebble.Layer:
    # Layer passes these values through as given, though LayerDict doesn't describe them.
    raw = {'services': {'s': {'override': 'replace', 'command': '/bin/s', **service}}}
    return pebble.Layer(cast('pebble.LayerDict', raw))


def _stored(content: dict[str, Any]) -> testing.State:
    return testing.State(stored_states={testing.StoredState(content=content)})


# Sets every field to something other than its default, recursing into the
# nested types, so that a field added later with no encoding fails here.
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
        testing.SubordinateRelation(
            'logging',
            remote_app_name='fluentbit',
            remote_unit_id=2,
            remote_app_data={'format': 'json'},
            remote_unit_data={'ready': 'true'},
        ),
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
            execs={testing.Exec(['ls', '-l'], return_code=1, stdout='out', stderr='err')},
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
    networks={
        testing.Network(
            'db',
            bind_addresses=[
                testing.BindAddress(
                    [testing.Address('10.0.0.5', hostname='app-0', cidr='10.0.0.0/24')],
                    interface_name='eth0',
                    mac_address='00:16:3e:00:00:01',
                )
            ],
            ingress_addresses=['10.0.0.5'],
            egress_subnets=['10.0.0.0/24'],
        )
    },
    storages={testing.Storage('data', index=3)},
    model=testing.Model(
        'my-model',
        uuid='00000000-0000-4000-8000-000000000000',
        type='lxd',
        cloud_spec=testing.CloudSpec(
            'lxd',
            name='localhost',
            region='default',
            endpoint='https://10.0.0.1:8443',
            credential=testing.CloudCredential(
                auth_type='certificate',
                attributes={'client-cert': 'cert'},
                redacted=['client-key'],
            ),
            ca_certificates=['ca'],
            skip_tls_verify=True,
            is_controller_cloud=True,
        ),
    ),
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
            _container(
                notices=[
                    testing.Notice(
                        'example.com/n',
                        repeat_after=datetime.timedelta(days=400000, microseconds=1),
                    )
                ]
            ),
            id='large-timedelta',
        ),
        pytest.param(
            testing.State(
                secrets={
                    testing.Secret(
                        {'k': 'v'},
                        # The second 02:30 of the day the clocks go back.
                        expire=datetime.datetime(
                            2026, 4, 5, 2, 30, fold=1, tzinfo=zoneinfo.ZoneInfo('Pacific/Auckland')
                        ),
                    )
                }
            ),
            id='zoned-ambiguous-datetime',
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
            _container(layers={'l': _layer(startup=pebble.ServiceStartup.ENABLED)}),
            id='layer-service-startup',
        ),
        pytest.param(
            _container(layers={'l': _layer(environment={'CONFIG': pathlib.Path('/etc/s.conf')})}),
            id='layer-path-in-environment',
        ),
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
        pytest.param(_stored({'l': ['__tuple__', 1]}), id='list-starting-like-a-tuple'),
        pytest.param(_stored({'d': {'__t__': 'bytes', 'v': 'AAAA'}}), id='dict-with-the-tag'),
        pytest.param(_stored({'__t__': 'dc', 'cls': 'State', 'f': {}}), id='content-with-the-tag'),
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


@pytest.mark.parametrize('track_latest', [False, True])
def test_secret_revisions_round_trip(track_latest: bool):
    # Secret equality doesn't see the revisions, so check them directly.
    secret = _secret_at_revision_2(track_latest=track_latest)
    out = _state_serde.decode_state(_state_serde.encode_state(testing.State(secrets={secret})))
    decoded = next(iter(out.secrets))
    assert decoded._latest_revision == 2
    assert decoded._tracked_revision == (2 if track_latest else 1)


def test_a_zoned_datetime_keeps_its_zone_and_fold():
    expire = datetime.datetime(
        2026, 4, 5, 2, 30, fold=1, tzinfo=zoneinfo.ZoneInfo('Pacific/Auckland')
    )
    state = testing.State(secrets={testing.Secret({'k': 'v'}, expire=expire)})
    out = _state_serde.decode_state(_state_serde.encode_state(state))
    decoded = next(iter(out.secrets)).expire
    assert decoded is not None
    assert decoded.tzinfo == expire.tzinfo
    assert decoded.fold == 1
    assert decoded.utcoffset() == expire.utcoffset()


def test_a_change_id_keeps_its_type():
    state = _container(check_infos={testing.CheckInfo('http', change_id=pebble.ChangeID('42'))})
    out = _state_serde.decode_state(_state_serde.encode_state(state))
    change_id = next(iter(out.get_container('app').check_infos)).change_id
    assert isinstance(change_id, pebble.ChangeID)
    assert change_id == '42'


class _Charm(ops.CharmBase):
    pass


class _Events(ops.ObjectEvents):
    ready = ops.EventSource(ops.EventBase)


class _Lib(ops.Object):
    on = _Events()


def test_a_custom_event_has_no_encoding():
    ctx = testing.Context(_Charm, meta={'name': 'c'})
    with pytest.raises(TypeError, match="custom event \\('ready'\\)"):
        _state_serde.encode_event(ctx.on.custom(_Lib.on.ready))


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


class CheckLevel(enum.Enum):
    # The same name as pebble.CheckLevel, with a member it shares.
    ALIVE = 'alive'


@dataclasses.dataclass(frozen=True)
class Secret:
    # The same name as testing.Secret, without its non-field attributes.
    x: int = 1


@dataclasses.dataclass(frozen=True)
class Address:
    # The same name and fields as testing.Address.
    value: str = '10.0.0.1'
    hostname: str = ''
    cidr: str = ''


@dataclasses.dataclass(frozen=True)
class _Other:
    x: int = 1


@pytest.mark.parametrize(
    ('content', 'message'),
    [
        ({'bad': object()}, "No JSON encoding for type 'object' at path '.*content.bad'"),
        ({'e': _OtherEnum.VALUE}, 'Unrecognised enum type'),
        ({'e': _StrEnum.VALUE}, 'Unrecognised enum type'),
        ({'e': CheckLevel.ALIVE}, "Unrecognised enum type 'CheckLevel' at path '.*content.e'"),
        ({'d': Secret()}, "Unrecognised dataclass 'Secret' at path '.*content.d'"),
        ({'d': Address()}, "Unrecognised dataclass 'Address' at path '.*content.d'"),
        ({'d': _Other()}, "Unrecognised dataclass '_Other' at path '.*content.d'"),
        ({'p': pathlib.PureWindowsPath('C:/x')}, "No JSON encoding for type 'PureWindowsPath'"),
        ({(1, 2): 'x'}, 'keys must be all str or all int'),
        ({True: 1}, 'keys must be all str or all int'),
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
        ({'__t__': 'enum', 'cls': 'CheckLevel', 'name': 'OTHER'}, "Unknown member 'OTHER'"),
        ({'__t__': 'dc', 'cls': 'State', 'f': {}, 'x': {'anything': 1}}, 'Unexpected attribute'),
        ({'__t__': 'dc', 'cls': 'State'}, "Missing 'f'"),
        ({'__t__': 'idict'}, "Missing 'v'"),
        ({'__t__': 'idict', 'v': {'x': 1}}, 'Expected integer keys'),
        ({'__t__': 'datetime', 'v': 'nope'}, 'Invalid datetime'),
        ({'__t__': 'timedelta', 'v': 1.5}, 'Expected a list'),
        ({'__t__': 'timedelta', 'v': [1, 2]}, r'Expected \[days, seconds, microseconds\]'),
        ({'__t__': 'bytes', 'v': '!!'}, 'Invalid base64'),
        ({'__t__': 7}, 'Expected a string type tag'),
        ('not-a-state', 'not a State'),
    ],
)
def test_unknown_encodings_are_rejected(encoded: Any, message: str):
    payload = json.dumps({'ops_testing_version': VERSION, 'state': encoded})
    with pytest.raises(TypeError, match=message):
        _state_serde.decode_state(payload)


def test_a_payload_without_its_kind_is_rejected():
    payload = json.dumps({'ops_testing_version': VERSION})
    with pytest.raises(TypeError, match="Missing 'state'"):
        _state_serde.decode_state(payload)


def test_an_event_payload_must_hold_an_event():
    payload = json.dumps({'ops_testing_version': VERSION, 'event': 'install'})
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
    assert VERSION in str(caught.value)


def test_sets_encode_in_a_canonical_order():
    # Iteration order depends on the hash seed, so the members are sorted.
    names = [f'name{i}' for i in range(20)]
    state = testing.State(stored_states={testing.StoredState(n) for n in names})
    members = json.loads(_state_serde.encode_state(state))['state']['f']['stored_states']['v']
    assert members == sorted(members, key=lambda m: json.dumps(m, sort_keys=True))
    assert len(members) == len(names)


def test_the_payload_records_the_version():
    payload = json.loads(_state_serde.encode_state(testing.State()))
    assert payload['ops_testing_version'] == VERSION


def _enums_reachable_from_state() -> set[type[enum.Enum]]:
    found: set[type[enum.Enum]] = set()
    seen: set[type] = set()

    def walk(hint: Any):
        for arg in typing.get_args(hint):
            walk(arg)
        if not inspect.isclass(hint):
            return
        if issubclass(hint, enum.Enum):
            found.add(hint)
        elif dataclasses.is_dataclass(hint) and hint not in seen:
            seen.add(hint)
            # typing.get_type_hints rejects KW_ONLY annotations on Python 3.10,
            # so evaluate each class's own annotations and keep the real fields.
            names = {f.name for f in dataclasses.fields(hint)}
            for base in reversed(hint.__mro__):
                annotations = inspect.get_annotations(base, eval_str=True)
                for name, field_hint in annotations.items():
                    if name in names:
                        walk(field_hint)

    for cls in _state_serde._DC_TYPES.values():
        walk(cls)
    return found


def test_every_enum_in_a_state_has_an_encoding():
    # _ENUM_TYPES is written by hand, so a new enum-typed field would otherwise
    # only show up as an encoding error on a State that ops.testing accepts.
    known = set(_state_serde._ENUM_TYPES.values())
    reachable = _enums_reachable_from_state()
    assert reachable <= known
    # ServiceStartup is only reachable inside a Pebble layer, which the field
    # annotations don't see into.
    assert known - reachable == {pebble.ServiceStartup}
