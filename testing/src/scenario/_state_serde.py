# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Typed JSON encoding of ``State`` and events, for the isolated worker.

Values JSON can't hold are wrapped in an envelope tagged with ``"__t__"``,
and so is a dict that has that key itself. The encoding is internal: both
ends run the same ``ops.testing``, which the payload records and the decoder
checks.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime
import enum
import inspect
import json
import pathlib
import zoneinfo
from collections.abc import Iterable
from typing import Any, TypeAlias, Union, cast

import ops
from ops import pebble

from . import _version
from . import state as _state


class _VersionMismatchError(RuntimeError):
    """A payload was encoded by a different ``ops.testing`` from this process's."""


#: Any value that survives a ``json.dumps``/``json.loads`` round trip.
_JSON: TypeAlias = Union[bool, int, float, str, 'list[_JSON]', 'dict[str, _JSON]', None]

_T = '__t__'

#: The ``ops-scenario`` version, from the source rather than the installed
#: metadata: what matters is whether the same code encoded the payload.
_VERSION = _version.version

#: Attributes that aren't dataclass fields, so ``cls(**fields)`` can't
#: restore them. They're set with ``object.__setattr__`` after construction.
_NON_FIELD_ATTRS: dict[type[Any], tuple[str, ...]] = {
    _state.Secret: ('_tracked_revision', '_latest_revision'),
}

_ENUM_TYPES: dict[str, type[enum.Enum]] = {
    cls.__name__: cls
    for cls in (
        pebble.CheckLevel,
        pebble.CheckStartup,
        pebble.CheckStatus,
        pebble.NoticeType,
        ops.SecretRotate,
        pebble.ServiceStartup,
        pebble.ServiceStatus,
    )
}

_DC_TYPES: dict[str, type[Any]] = {
    name: value
    for name, value in vars(_state).items()
    if inspect.isclass(value)
    and dataclasses.is_dataclass(value)
    and value.__module__ == _state.__name__
}


def encode_state(state: _state.State) -> str:
    """Encode a ``State`` as JSON.

    Raises:
        TypeError: if a value has no encoding, naming its path through the
            ``State``.
    """
    return _encode_payload(state, 'state')


def decode_state(payload: str) -> _state.State:
    """Decode a ``State`` encoded by :func:`encode_state`."""
    result = _decode_payload(payload, 'state')
    if not isinstance(result, _state.State):
        raise TypeError(f'The payload is not a State: got {type(result).__name__!r}.')
    return result


def encode_event(event: _state._Event) -> str:
    """Encode an event as JSON.

    Raises:
        TypeError: if the event is a custom event (``ctx.on.custom(...)``).
            A custom event is bound to an emitter in this process, which has
            no meaning in another one, and Juju never emits custom events,
            so they aren't encoded.
    """
    if event.custom_event is not None:
        raise TypeError(
            f'A custom event ({event.custom_event.event_kind!r}) has no JSON encoding: '
            'it is bound to an emitter in this process.'
        )
    return _encode_payload(event, 'event')


def decode_event(payload: str) -> _state._Event:
    """Decode an event encoded by :func:`encode_event`."""
    result = _decode_payload(payload, 'event')
    if not isinstance(result, _state._Event):
        raise TypeError(f'The payload is not an event: got {type(result).__name__!r}.')
    return result


def _encode_payload(obj: Any, kind: str) -> str:
    return json.dumps({'ops_testing_version': _VERSION, kind: _encode(obj, kind)})


def _decode_payload(payload: str, kind: str) -> Any:
    data = _as_dict(json.loads(payload), 'payload')
    version = data.get('ops_testing_version')
    if version != _VERSION:
        raise _VersionMismatchError(
            f'The {kind} was encoded by ops.testing (ops-scenario) {version!r}, but this '
            f'process has {_VERSION!r}. The environment is stale, or this is a bug.'
        )
    return _decode(_field(data, kind, 'payload'))


# Encoder


def _sorted_members(members: Iterable[Any], path: str) -> list[_JSON]:
    # Sorted so that equal sets encode the same, whatever the hash seed.
    encoded = [_encode(x, f'{path}[]') for x in members]
    return sorted(encoded, key=lambda x: json.dumps(x, sort_keys=True))


def _encode(obj: Any, path: str) -> _JSON:
    # Before the primitives, so that a str or int enum keeps its type.
    if isinstance(obj, enum.Enum):
        cls_name = type(obj).__name__
        if _ENUM_TYPES.get(cls_name) is not type(obj):
            raise TypeError(f'Unrecognised enum type {type(obj).__qualname__!r} at path {path!r}.')
        return {_T: 'enum', 'cls': cls_name, 'name': obj.name}

    # Before str, which it subclasses.
    if isinstance(obj, pebble.ChangeID):
        return {_T: 'ChangeID', 'v': str(obj)}

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, bytes):
        return {_T: 'bytes', 'v': base64.b64encode(obj).decode('ascii')}

    # Before the dataclasses, because the status __init__s take only a message.
    if isinstance(obj, _state._EntityStatus):
        return {_T: 'status', 'name': obj.name, 'msg': obj.message}

    if isinstance(obj, pebble.Layer):
        # Encoded rather than trusted: to_dict() passes values such as a
        # ServiceStartup or a Path through as given.
        return {_T: 'layer', 'v': _encode(obj.to_dict(), path)}

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        cls = type(obj)
        if _DC_TYPES.get(cls.__name__) is not cls:
            raise TypeError(f'Unrecognised dataclass {cls.__qualname__!r} at path {path!r}.')
        # init=False fields are derived in __post_init__, so they're left out.
        fields = {
            f.name: _encode(getattr(obj, f.name), f'{path}.{f.name}')
            for f in dataclasses.fields(obj)
            if f.init
        }
        encoded: dict[str, _JSON] = {_T: 'dc', 'cls': cls.__name__, 'f': fields}
        extra = {
            name: _encode(getattr(obj, name), f'{path}.{name}')
            for name in _NON_FIELD_ATTRS.get(cls, ())
        }
        if extra:
            encoded['x'] = extra
        return encoded

    if isinstance(obj, datetime.datetime):
        # isoformat() keeps the offset but not the zone or the fold, so an
        # ambiguous time in a zone would come back as a different instant.
        encoded = {_T: 'datetime', 'v': obj.isoformat()}
        if isinstance(obj.tzinfo, zoneinfo.ZoneInfo) and obj.tzinfo.key is not None:
            encoded['tz'] = obj.tzinfo.key
        if obj.fold:
            encoded['fold'] = 1
        return encoded

    if isinstance(obj, datetime.timedelta):
        # Not total_seconds(): a float loses the microseconds of a large value.
        return {_T: 'timedelta', 'v': [obj.days, obj.seconds, obj.microseconds]}

    # Path before PurePosixPath, which it subclasses on Linux.
    if isinstance(obj, pathlib.Path):
        return {_T: 'Path', 'v': str(obj)}

    if isinstance(obj, pathlib.PurePosixPath):
        return {_T: 'PurePosixPath', 'v': str(obj)}

    if isinstance(obj, frozenset):
        return {_T: 'frozenset', 'v': _sorted_members(cast('frozenset[Any]', obj), path)}

    if isinstance(obj, set):
        return {_T: 'set', 'v': _sorted_members(cast('set[Any]', obj), path)}

    if isinstance(obj, tuple):
        elements = cast('tuple[Any, ...]', obj)
        return {_T: 'tuple', 'v': [_encode(x, f'{path}[]') for x in elements]}

    if isinstance(obj, list):
        items = cast('list[Any]', obj)
        return [_encode(x, f'{path}[{i}]') for i, x in enumerate(items)]

    if isinstance(obj, dict):
        mapping = cast('dict[Any, Any]', obj)
        # type() rather than isinstance(), because int(str(True)) fails.
        if mapping and all(type(k) is int for k in mapping):
            return {
                _T: 'idict',
                'v': {str(k): _encode(v, f'{path}[{k}]') for k, v in mapping.items()},
            }
        for k in mapping:
            if not isinstance(k, str):
                raise TypeError(
                    f'No JSON encoding for dict key {k!r} of type {type(k).__qualname__!r} '
                    f'at path {path!r}: keys must be all str or all int.'
                )
        encoded_mapping = {k: _encode(v, f'{path}.{k}') for k, v in mapping.items()}
        if _T in encoded_mapping:
            return {_T: 'dict', 'v': encoded_mapping}
        return encoded_mapping

    raise TypeError(f'No JSON encoding for type {type(obj).__qualname__!r} at path {path!r}.')


# Decoder
#
# A malformed payload is always a TypeError, whatever went wrong, so a caller
# has one thing to catch.


def _field(obj: dict[str, _JSON], key: str, what: str) -> _JSON:
    if key not in obj:
        raise TypeError(f'Missing {key!r} for {what} in the payload.')
    return obj[key]


def _as_str(value: _JSON, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f'Expected a string for {field} in the payload, got {value!r}.')
    return value


def _as_int(value: _JSON, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f'Expected an integer for {field} in the payload, got {value!r}.')
    return value


def _as_list(value: _JSON, field: str) -> list[_JSON]:
    if not isinstance(value, list):
        raise TypeError(f'Expected a list for {field} in the payload, got {value!r}.')
    return value


def _as_dict(value: _JSON, field: str) -> dict[str, _JSON]:
    if not isinstance(value, dict):
        raise TypeError(f'Expected an object for {field} in the payload, got {value!r}.')
    return value


def _decode(obj: _JSON) -> Any:
    if isinstance(obj, list):
        return [_decode(x) for x in obj]

    if not isinstance(obj, dict):
        return obj

    kind = obj.get(_T)

    if kind is None:
        return {k: _decode(v) for k, v in obj.items()}

    if not isinstance(kind, str):
        raise TypeError(f'Expected a string type tag in the payload, got {kind!r}.')

    if kind == 'dict':
        return {k: _decode(v) for k, v in _as_dict(_field(obj, 'v', kind), kind).items()}

    if kind == 'tuple':
        return tuple(_decode(x) for x in _as_list(_field(obj, 'v', kind), kind))

    if kind == 'status':
        name = _as_str(_field(obj, 'name', 'status'), 'status name')
        if name not in _state._EntityStatus._entity_statuses:
            raise TypeError(f'Unknown status name {name!r} in the payload.')
        message = _as_str(_field(obj, 'msg', 'status'), 'status message')
        # UnknownStatus has no message; from_status_name warns if given one.
        return _state._EntityStatus.from_status_name(
            cast('_state._RawStatusLiteral', name), message if name != 'unknown' else ''
        )

    if kind == 'layer':
        layer = _decode(_field(obj, 'v', kind))
        if not isinstance(layer, dict):
            raise TypeError(f'Expected an object for layer in the payload, got {layer!r}.')
        return pebble.Layer(cast('pebble.LayerDict', layer))

    if kind == 'enum':
        cls_name = _as_str(_field(obj, 'cls', 'enum'), 'enum class')
        enum_cls = _ENUM_TYPES.get(cls_name)
        if enum_cls is None:
            raise TypeError(f'Unknown enum class {cls_name!r} in the payload.')
        member_name = _as_str(_field(obj, 'name', 'enum'), 'enum member')
        member = enum_cls.__members__.get(member_name)
        if member is None:
            raise TypeError(f'Unknown member {member_name!r} of {cls_name} in the payload.')
        return member

    if kind == 'dc':
        cls_name = _as_str(_field(obj, 'cls', 'dataclass'), 'dataclass name')
        dc_cls = _DC_TYPES.get(cls_name)
        if dc_cls is None:
            raise TypeError(f'Unknown dataclass {cls_name!r} in the payload.')
        fields = {
            k: _decode(v)
            for k, v in _as_dict(_field(obj, 'f', cls_name), 'dataclass fields').items()
        }
        instance = dc_cls(**fields)
        allowed = _NON_FIELD_ATTRS.get(dc_cls, ())
        for name, value in _as_dict(obj.get('x', {}), 'dataclass extras').items():
            if name not in allowed:
                raise TypeError(f'Unexpected attribute {name!r} for {cls_name} in the payload.')
            object.__setattr__(instance, name, _decode(value))
        return instance

    if kind == 'datetime':
        text = _as_str(_field(obj, 'v', kind), kind)
        try:
            value = datetime.datetime.fromisoformat(text)
        except ValueError as e:
            raise TypeError(f'Invalid datetime {text!r} in the payload: {e}') from None
        if 'tz' in obj:
            key = _as_str(obj['tz'], 'time zone')
            try:
                value = value.replace(tzinfo=zoneinfo.ZoneInfo(key))
            except zoneinfo.ZoneInfoNotFoundError:
                raise TypeError(f'Unknown time zone {key!r} in the payload.') from None
        if obj.get('fold'):
            value = value.replace(fold=1)
        return value

    if kind == 'timedelta':
        parts = _as_list(_field(obj, 'v', kind), kind)
        if len(parts) != 3:
            raise TypeError(
                f'Expected [days, seconds, microseconds] for timedelta, got {parts!r}.'
            )
        days, seconds, microseconds = (_as_int(p, 'timedelta part') for p in parts)
        return datetime.timedelta(days=days, seconds=seconds, microseconds=microseconds)

    if kind == 'Path':
        return pathlib.Path(_as_str(_field(obj, 'v', kind), kind))

    if kind == 'PurePosixPath':
        return pathlib.PurePosixPath(_as_str(_field(obj, 'v', kind), kind))

    if kind == 'ChangeID':
        return pebble.ChangeID(_as_str(_field(obj, 'v', kind), kind))

    if kind == 'frozenset':
        return frozenset(_decode(x) for x in _as_list(_field(obj, 'v', kind), kind))

    if kind == 'set':
        return {_decode(x) for x in _as_list(_field(obj, 'v', kind), kind)}

    if kind == 'bytes':
        text = _as_str(_field(obj, 'v', kind), kind)
        try:
            return base64.b64decode(text, validate=True)
        except ValueError as e:
            raise TypeError(f'Invalid base64 in the payload: {e}') from None

    if kind == 'idict':
        mapping = _as_dict(_field(obj, 'v', kind), kind)
        try:
            return {int(k): _decode(v) for k, v in mapping.items()}
        except ValueError:
            raise TypeError(
                f'Expected integer keys for idict in the payload, got {list(mapping)!r}.'
            ) from None

    raise TypeError(f'Unknown type tag {kind!r} in the payload.')
