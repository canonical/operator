# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Typed JSON encoding of ``State`` and events, for the isolated worker.

Values JSON can't hold are wrapped in an envelope tagged with ``"__t__"``,
and a tuple is a list that starts with ``"__tuple__"``. The encoding is
internal: both ends run the same ``ops.testing``, which the payload records
and the decoder checks.
"""

from __future__ import annotations

import base64
import dataclasses
import datetime
import enum
import inspect
import json
import pathlib
from collections.abc import Callable, Iterable
from typing import Any, TypeAlias, Union, cast

import ops.version
from ops import SecretRotate, pebble

from . import state as _state


class _VersionMismatchError(RuntimeError):
    """A payload was encoded by a different ``ops.testing`` from this process's."""


#: Any value that survives a ``json.dumps``/``json.loads`` round trip.
_JSON: TypeAlias = Union[bool, int, float, str, 'list[_JSON]', 'dict[str, _JSON]', None]

_T = '__t__'
_TUPLE_SENTINEL = '__tuple__'

#: Attributes that aren't dataclass fields, so ``cls(**fields)`` can't
#: restore them. They're set with ``object.__setattr__`` after construction.
_NON_FIELD_ATTRS: dict[str, tuple[str, ...]] = {
    'Secret': ('_tracked_revision', '_latest_revision'),
}

_PEBBLE_ENUM_TYPES: dict[str, type[enum.Enum]] = {
    'CheckLevel': pebble.CheckLevel,
    'CheckStartup': pebble.CheckStartup,
    'CheckStatus': pebble.CheckStatus,
    'NoticeType': pebble.NoticeType,
    'SecretRotate': SecretRotate,
    'ServiceStartup': pebble.ServiceStartup,
    'ServiceStatus': pebble.ServiceStatus,
}

# UnknownStatus is handled in the decoder, because it takes no message.
_STATUS_TYPES: dict[str, Callable[[str], _state._EntityStatus]] = {
    'active': _state.ActiveStatus,
    'blocked': _state.BlockedStatus,
    'error': _state.ErrorStatus,
    'maintenance': _state.MaintenanceStatus,
    'waiting': _state.WaitingStatus,
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
    """Encode an event as JSON."""
    return _encode_payload(event, 'event')


def decode_event(payload: str) -> _state._Event:
    """Decode an event encoded by :func:`encode_event`."""
    result = _decode_payload(payload, 'event')
    if not isinstance(result, _state._Event):
        raise TypeError(f'The payload is not an event: got {type(result).__name__!r}.')
    return result


def _encode_payload(obj: Any, kind: str) -> str:
    return json.dumps({'ops_testing_version': ops.version.version, kind: _encode(obj, kind)})


def _decode_payload(payload: str, kind: str) -> Any:
    data = _as_dict(json.loads(payload), 'payload')
    version = data.get('ops_testing_version')
    if version != ops.version.version:
        raise _VersionMismatchError(
            f'The {kind} was encoded by ops.testing {version!r}, but this process has '
            f'{ops.version.version!r}. The environment is stale, or this is a bug.'
        )
    return _decode(data[kind])


# Encoder


def _sorted_members(members: Iterable[Any], path: str) -> list[_JSON]:
    # Sorted so that equal sets encode the same, whatever the hash seed.
    encoded = [_encode(x, f'{path}[]') for x in members]
    return sorted(encoded, key=lambda x: json.dumps(x, sort_keys=True))


def _encode(obj: Any, path: str) -> _JSON:
    # Before the primitives, so that a str or int enum keeps its type.
    if isinstance(obj, enum.Enum):
        cls_name = type(obj).__name__
        if cls_name not in _PEBBLE_ENUM_TYPES:
            raise TypeError(f'Unrecognised enum type {type(obj).__qualname__!r} at path {path!r}.')
        return {_T: 'enum', 'cls': cls_name, 'name': obj.name}

    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj

    if isinstance(obj, bytes):
        return {_T: 'bytes', 'v': base64.b64encode(obj).decode('ascii')}

    # Before the dataclasses, because the status classes take positional arguments.
    if isinstance(obj, _state._EntityStatus):
        return {_T: 'status', 'name': obj.name, 'msg': obj.message}

    if isinstance(obj, pebble.Layer):
        return {_T: 'layer', 'v': cast('dict[str, _JSON]', obj.to_dict())}

    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        # init=False fields are derived in __post_init__, so they're left out.
        fields = {
            f.name: _encode(getattr(obj, f.name), f'{path}.{f.name}')
            for f in dataclasses.fields(obj)
            if f.init
        }
        encoded: dict[str, _JSON] = {_T: 'dc', 'cls': type(obj).__name__, 'f': fields}
        extra = {
            name: _encode(getattr(obj, name), f'{path}.{name}')
            for name in _NON_FIELD_ATTRS.get(type(obj).__name__, ())
        }
        if extra:
            encoded['x'] = extra
        return encoded

    if isinstance(obj, datetime.datetime):
        return {_T: 'datetime', 'v': obj.isoformat()}

    if isinstance(obj, datetime.timedelta):
        return {_T: 'timedelta', 'v': obj.total_seconds()}

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
        return [_TUPLE_SENTINEL, *(_encode(x, f'{path}[]') for x in elements)]

    if isinstance(obj, list):
        items = cast('list[Any]', obj)
        if items and items[0] == _TUPLE_SENTINEL:
            raise TypeError(f'A list starting with {_TUPLE_SENTINEL!r} at path {path!r}.')
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
        if _T in mapping:
            raise TypeError(f'A dict with the key {_T!r} at path {path!r}.')
        return {k: _encode(v, f'{path}.{k}') for k, v in mapping.items()}

    raise TypeError(f'No JSON encoding for type {type(obj).__qualname__!r} at path {path!r}.')


# Decoder


def _as_str(value: _JSON, field: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f'Expected a string for {field} in the payload, got {value!r}.')
    return value


def _as_number(value: _JSON, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f'Expected a number for {field} in the payload, got {value!r}.')
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
        if obj and obj[0] == _TUPLE_SENTINEL:
            return tuple(_decode(x) for x in obj[1:])
        return [_decode(x) for x in obj]

    if not isinstance(obj, dict):
        return obj

    kind = obj.get(_T)

    if kind is None:
        return {k: _decode(v) for k, v in obj.items()}

    if kind == 'status':
        name = _as_str(obj['name'], 'status name')
        if name == 'unknown':
            return _state.UnknownStatus()
        cls = _STATUS_TYPES.get(name)
        if cls is None:
            raise TypeError(f'Unknown status name {name!r} in the payload.')
        return cls(_as_str(obj['msg'], 'status message'))

    if kind == 'layer':
        return pebble.Layer(cast('pebble.LayerDict', _as_dict(obj['v'], 'layer')))

    if kind == 'enum':
        cls_name = _as_str(obj['cls'], 'enum class')
        enum_cls = _PEBBLE_ENUM_TYPES.get(cls_name)
        if enum_cls is None:
            raise TypeError(f'Unknown enum class {cls_name!r} in the payload.')
        return enum_cls[_as_str(obj['name'], 'enum member')]

    if kind == 'dc':
        cls_name = _as_str(obj['cls'], 'dataclass name')
        dc_cls = _DC_TYPES.get(cls_name)
        if dc_cls is None:
            raise TypeError(f'Unknown dataclass {cls_name!r} in the payload.')
        fields = {k: _decode(v) for k, v in _as_dict(obj['f'], 'dataclass fields').items()}
        instance = dc_cls(**fields)
        for name, value in _as_dict(obj.get('x', {}), 'dataclass extras').items():
            object.__setattr__(instance, name, _decode(value))
        return instance

    if kind == 'datetime':
        return datetime.datetime.fromisoformat(_as_str(obj['v'], 'datetime'))

    if kind == 'timedelta':
        return datetime.timedelta(seconds=_as_number(obj['v'], 'timedelta'))

    if kind == 'Path':
        return pathlib.Path(_as_str(obj['v'], 'Path'))

    if kind == 'PurePosixPath':
        return pathlib.PurePosixPath(_as_str(obj['v'], 'PurePosixPath'))

    if kind == 'frozenset':
        return frozenset(_decode(x) for x in _as_list(obj['v'], 'frozenset'))

    if kind == 'set':
        return {_decode(x) for x in _as_list(obj['v'], 'set')}

    if kind == 'bytes':
        return base64.b64decode(_as_str(obj['v'], 'bytes'))

    if kind == 'idict':
        return {int(k): _decode(v) for k, v in _as_dict(obj['v'], 'idict').items()}

    raise TypeError(f'Unknown type tag {kind!r} in the payload.')
