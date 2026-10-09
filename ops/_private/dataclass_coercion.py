# Copyright 2026 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Coercion of decoded relation data into dataclass fields."""

from __future__ import annotations

import builtins
import collections.abc
import dataclasses
import enum
import logging
import sys
import types
import typing
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar, cast, get_type_hints

logger = logging.getLogger(__name__)

_T = TypeVar('_T')


# Builtin collections other than the mappings, which are built separately.
_BUILTIN_COLLECTION_TYPES = (list, tuple, set, frozenset)
# frozendict is new in Python 3.15.
_FROZENDICT: type | None = getattr(builtins, 'frozendict', None)
_BUILTIN_MAPPING_TYPES: tuple[type, ...] = (dict,) if _FROZENDICT is None else (dict, _FROZENDICT)

# Abstract collection annotations don't name a type to build, so each is
# built as a concrete type that satisfies it. The read-only sequence types
# would be better built as a tuple, but charms may rely on getting a list, so
# that change is left for the next major release.
_ABSTRACT_COLLECTION_TYPES: dict[Any, type] = {
    collections.abc.Iterable: list,
    collections.abc.Collection: list,
    collections.abc.Sequence: list,
    collections.abc.MutableSequence: list,
    collections.abc.Set: frozenset,
    collections.abc.MutableSet: set,
    collections.abc.Mapping: dict,
    collections.abc.MutableMapping: dict,
}
# A mapping is an Iterable or Collection of its keys, so a mapping value
# satisfies these annotations and they are built from its keys.
_MAPPING_KEY_TYPES = (collections.abc.Iterable, collections.abc.Collection)


def _is_pydantic_model(tp: Any) -> bool:
    """Report whether class ``tp`` is a Pydantic ``BaseModel``, without importing Pydantic."""
    # A Pydantic dataclass also has a validator, but no model_validate.
    return (
        isinstance(tp, type)
        and '__pydantic_validator__' in tp.__dict__
        and hasattr(tp, 'model_validate')
    )


def _type_alias_types() -> tuple[type, ...]:
    """Return the ``TypeAliasType`` classes that a charm may be using."""
    # Before Python 3.12, typing_extensions.TypeAliasType is the only one, and
    # it can only be in use if the charm has imported it.
    typing_extensions = sys.modules.get('typing_extensions')
    candidates = (
        getattr(typing, 'TypeAliasType', None),
        getattr(typing_extensions, 'TypeAliasType', None),
    )
    return tuple(c for c in candidates if isinstance(c, type))


def _resolve_alias(tp: Any) -> Any:
    """Resolve a ``type`` statement alias, such as ``type Pets = list[Pet]``, to its value.

    An alias that can't be evaluated, for example because it refers to a name
    that isn't defined, is returned unchanged, so its value is passed through.
    """
    alias_types = _type_alias_types()
    seen: set[int] = set()
    while True:
        origin = typing.get_origin(tp)
        alias = tp if isinstance(tp, alias_types) else origin
        if not isinstance(alias, alias_types) or id(alias) in seen:
            return tp
        seen.add(id(alias))
        try:
            value = alias.__value__
            # A generic alias only needs its arguments substituted if its
            # value uses the alias's type parameters.
            if alias is origin and getattr(value, '__parameters__', ()):
                value = value[typing.get_args(tp)]
        except (NameError, TypeError):
            return tp
        tp = value


_ANY_SHAPE = frozenset({'mapping', 'sequence', 'scalar'})


def _value_shape(value: Any) -> str:
    """Report whether a decoded ``value`` is a mapping, a sequence, or a scalar."""
    if isinstance(value, Mapping):
        return 'mapping'
    # A str or bytes is iterable, but isn't a collection of anything the
    # charm meant.
    if isinstance(value, (str, bytes)) or not isinstance(value, collections.abc.Iterable):
        return 'scalar'
    return 'sequence'


def _accepted_shapes(tp: Any) -> frozenset[str]:
    """Report which value shapes the annotation ``tp`` can be coerced from.

    Only the annotation is inspected; nothing is constructed, so the check has
    no side effects.
    """
    tp = _resolve_alias(tp)
    # A type alias that can't be resolved accepts a value of any shape, which is
    # then passed through.
    alias_types = _type_alias_types()
    if (
        tp is Any
        or tp is object
        or isinstance(tp, alias_types)
        or isinstance(typing.get_origin(tp), alias_types)
    ):
        return _ANY_SHAPE
    kind = typing.get_origin(tp) or tp
    if kind in _MAPPING_KEY_TYPES:
        return frozenset({'sequence', 'mapping'})
    kind = _ABSTRACT_COLLECTION_TYPES.get(kind, kind)
    if isinstance(kind, type) and issubclass(kind, _BUILTIN_COLLECTION_TYPES):
        return frozenset({'sequence'})
    if (
        (isinstance(kind, type) and issubclass(kind, Mapping))
        or dataclasses.is_dataclass(tp)
        or _is_pydantic_model(tp)
    ):
        return frozenset({'mapping'})
    return frozenset({'scalar'})


def _shape_fits(tp: Any, value: Any) -> bool:
    """Report whether a decoded ``value`` has a shape that annotation ``tp`` accepts."""
    return _value_shape(value) in _accepted_shapes(tp)


def _check_shape(tp: Any, value: Any) -> None:
    """Raise ``TypeError`` if a decoded ``value`` has a shape that ``tp`` doesn't accept.

    A str, bytes or mapping is iterable, so coercing it element-wise would
    silently give a list of characters or keys, and a non-mapping for a
    dataclass would give an object built entirely from defaults: refuse
    rather than hand back the wrong answer.
    """
    if _shape_fits(tp, value):
        return
    expected = 'sequence' if 'sequence' in _accepted_shapes(tp) else 'mapping'
    name = tp.__name__ if isinstance(tp, type) else tp
    raise TypeError(f'expected a {expected} for {name}, got {type(value).__name__}: {value!r}')


def _coerce_field(tp: Any, value: Any) -> Any:
    """Coerce a decoded ``value`` into the dataclass field type ``tp``.

    Used by :meth:`ops.Relation.load` to recursively construct nested
    dataclasses and enum values from JSON-decoded relation data. An
    ``Optional``/``Union`` field is coerced against the one member that
    matches the shape of the value; ``dict``, ``Mapping`` and
    ``MutableMapping`` fields have their keys and values coerced; abstract
    sequence and set fields such as ``Sequence[X]`` are built as a ``list``,
    ``set`` or ``frozenset``; a variable-length ``tuple[X, ...]`` is coerced
    element-wise against ``X`` and a fixed-length ``tuple[X, Y]`` is
    coerced positionally.

    Raises ``TypeError`` if the value for a sequence field is a string, bytes
    or a mapping (other than a mapping for an ``Iterable`` or ``Collection``
    field, which is built from its keys), or if the value for a mapping field
    is not a mapping: those are all iterable, so coercing them element-wise
    would quietly produce a wrong answer rather than fail. Also raises
    ``TypeError`` if the value matches the shape of none of a ``Union``
    field's members.
    """
    tp = _resolve_alias(tp)
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if origin is None:
        # A bare collection annotation, such as `set` or `Sequence`, still names
        # the collection to build, although not the type of its items.
        if tp in _ABSTRACT_COLLECTION_TYPES or tp in (
            *_BUILTIN_COLLECTION_TYPES,
            *_BUILTIN_MAPPING_TYPES,
        ):
            origin = tp
        elif isinstance(tp, type):
            return _coerce_class(tp, value)  # pyright: ignore[reportUnknownVariableType]
        else:
            # Any, TypeVars, NewTypes and the like aren't classes, so there is
            # nothing to build.
            return value
    if origin is typing.Union or origin is types.UnionType:
        return _coerce_union(tp, args, value)
    if origin in _MAPPING_KEY_TYPES and isinstance(value, Mapping):
        value = list(cast('Mapping[Any, Any]', value))
    concrete = _ABSTRACT_COLLECTION_TYPES.get(origin, origin)
    if not args:
        if concrete is tuple:
            args = (Any, ...)
        elif concrete in _BUILTIN_MAPPING_TYPES:
            args = (Any, Any)
        else:
            args = (Any,)
    if concrete in _BUILTIN_COLLECTION_TYPES:
        return _coerce_sequence(tp, concrete, args, value)
    if concrete in _BUILTIN_MAPPING_TYPES and len(args) == 2:
        return _coerce_mapping(tp, concrete, args[0], args[1], value)
    # Literal and other constructed generics: accept the value as-is.
    return value


def _coerce_class(tp: type[_T], value: Any) -> _T:
    """Coerce ``value`` against a class ``tp`` with no type arguments.

    Builds a dataclass, enum, or Pydantic model; any other class is passed
    through as-is.
    """
    if issubclass(tp, enum.Enum):
        return tp(value)
    if '__pydantic_validator__' in tp.__dict__:
        # A Pydantic model or Pydantic dataclass does its own coercion and
        # validation, including aliases.
        return cast('Any', tp).__pydantic_validator__.validate_python(value)
    if dataclasses.is_dataclass(tp):
        if isinstance(value, tp):
            # Already the class we want, for example built by a custom
            # decoder, so there is nothing to coerce.
            return value
        # Without this, a remote app writing a string or a list where a nested
        # dataclass belongs gets a default-constructed object that corresponds
        # to nothing in the databag: `field.name not in 'oops'` is False for
        # every field, so every one is skipped.
        _check_shape(tp, value)
        return build_dataclass(tp, cast('Mapping[str, Any]', value))
    return value


def _coerce_union(tp: Any, args: tuple[Any, ...], value: Any) -> Any:
    """Coerce ``value`` against the member of union ``tp`` that its shape matches."""
    # A null can only be for the None member, so there is nothing to coerce.
    # Without a None member, it is passed through as-is.
    if value is None:
        return None
    # Nested unions are flattened when defined, but not through a type alias,
    # so expand those here.
    members: list[Any] = []
    pending = list(args)
    seen: set[int] = set()
    while pending:
        member = _resolve_alias(pending.pop(0))
        if id(member) in seen:
            continue
        seen.add(id(member))
        if typing.get_origin(member) in (typing.Union, types.UnionType):
            pending[:0] = typing.get_args(member)
        elif member is not type(None):
            members.append(member)
    # Pick the member by the shape of the decoded value alone, checking
    # every member so that the result doesn't depend on the order they are
    # declared in. Where more than one member fits (an enum and a str both
    # take a string, for example), there's no principled way to choose, so
    # accept the value as-is.
    if len(members) > 1:
        fits = [m for m in members if _shape_fits(m, value)]
        if not fits:
            raise TypeError(
                f'expected a value matching one of {tp}, got {type(value).__name__}: {value!r}'
            )
        members = fits
    if len(members) == 1:
        return _coerce_field(members[0], value)
    return value


def _is_unpacked(arg: Any) -> bool:
    """Report whether type argument ``arg`` is unpacked, such as ``*tuple[str, ...]``."""
    if getattr(arg, '__unpacked__', False):
        return True
    origin = typing.get_origin(arg)
    if origin is None:
        return False
    # Before Python 3.12, typing_extensions.Unpack is a separate object from
    # typing.Unpack, and it can only be in use if the charm has imported it.
    typing_extensions = sys.modules.get('typing_extensions')
    return origin is getattr(typing, 'Unpack', None) or origin is getattr(
        typing_extensions, 'Unpack', None
    )


def _coerce_sequence(tp: Any, origin: type, args: tuple[Any, ...], value: Any) -> Any:
    """Coerce the elements of ``value`` against sequence type ``tp``."""
    # Iterable and Collection fields have already had a mapping turned into
    # its keys by the caller.
    _check_shape(tp, value)
    if origin is tuple:
        if len(args) == 2 and args[1] is Ellipsis:
            return tuple(_coerce_field(args[0], v) for v in value)
        # An unpacked member such as *tuple[str, ...] makes the number of
        # positions variable, which isn't supported, and an Ellipsis anywhere
        # other than tuple[X, ...] isn't a valid annotation, so build a tuple
        # without coercing its elements.
        if Ellipsis in args or any(_is_unpacked(a) for a in args):
            return tuple(value)
        return tuple(_coerce_field(t, v) for t, v in zip(args, value, strict=True))
    if origin is set:
        return {_coerce_field(args[0], v) for v in value}
    if origin is frozenset:
        return frozenset(_coerce_field(args[0], v) for v in value)
    return [_coerce_field(args[0], v) for v in value]


def _coerce_mapping(tp: Any, origin: type, key_type: Any, value_type: Any, value: Any) -> Any:
    """Coerce the keys and values of ``value`` against the key and value types of ``tp``."""
    _check_shape(tp, value)
    mapping = cast('Mapping[Any, Any]', value)
    coerced = {
        _coerce_field(key_type, k): _coerce_field(value_type, v) for k, v in mapping.items()
    }
    return coerced if origin is dict else origin(coerced)


def build_dataclass(
    cls: Any,
    data: Mapping[str, Any],
    args: Sequence[Any] = (),
    extra_kwargs: Mapping[str, Any] | None = None,
) -> Any:
    """Construct dataclass ``cls`` from ``data``, ``args``, and ``extra_kwargs``.

    Recursively coerces nested dataclass / enum / list / set / tuple / dict
    fields supplied via ``data``. The caller's ``args`` and ``extra_kwargs``
    are passed through as given rather than coerced; a name in both
    ``extra_kwargs`` and ``data`` is taken from ``data``.

    Falls back to the un-coerced ``cls(*args, **{**extra_kwargs, **data})`` if
    ``get_type_hints`` raises, which happens even if a single field's
    annotation is unresolvable, because ``get_type_hints`` resolves every
    field at once. This is most likely to happen with a
    ``TYPE_CHECKING``-only import that has no runtime name.

    Raises ``TypeError`` (via the dataclass ``__init__``) if a required field is
    missing or an item in ``args`` fills a field that is also in ``data``, and
    ``ValueError``/``TypeError`` from coercion of malformed values.
    """
    extra_kwargs = extra_kwargs or {}
    kwargs: Mapping[str, Any]
    try:
        hints = get_type_hints(cls)
    except (NameError, TypeError) as e:
        msg = 'Unable to resolve type hints for %s, not coercing relation data: %s'
        logger.debug(msg, cls.__name__, e)
        kwargs = data
    else:
        kwargs = {}
        for field in dataclasses.fields(cls):
            if field.name not in data:
                continue
            kwargs[field.name] = _coerce_field(hints[field.name], data[field.name])
    # Relation data wins over a keyword argument of the same name.
    return cls(*args, **{**extra_kwargs, **kwargs})
