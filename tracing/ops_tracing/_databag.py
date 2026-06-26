# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared dataclass-based databag deserialisation helper.

Replaces what pydantic's ``DatabagModel.load`` did for the requirer-side
reads in ``_tracing_models`` and ``_cert_transfer_models``, recursively
coercing nested dataclasses, enums, and set/frozenset field types that
``ops.Relation.load``'s default ``json.loads`` decoder leaves as raw dicts
and lists. ``ops.Relation.save`` covers the writing side directly, so no
``dump`` helper lives here.
"""

from __future__ import annotations

import dataclasses
import enum
import json
import logging
import typing
from typing import Any, MutableMapping

logger = logging.getLogger(__name__)


def _coerce(tp: Any, value: Any, error_cls: type[Exception]) -> Any:
    """Coerce a JSON-decoded ``value`` into the dataclass field type ``tp``."""
    origin = typing.get_origin(tp)
    if origin is not None:
        args = typing.get_args(tp)
        if origin in (list, tuple):
            return [_coerce(args[0], v, error_cls) for v in value]
        if origin in (set, frozenset):
            return {_coerce(args[0], v, error_cls) for v in value}
        # Literal, Union, etc.: accept the value as-is.
        return value
    if isinstance(tp, type):
        if dataclasses.is_dataclass(tp):
            return _build(tp, value, error_cls)
        if issubclass(tp, enum.Enum):
            return tp(value)
    return value


def _build(cls: Any, data: MutableMapping[str, Any], error_cls: type[Exception]) -> Any:
    """Construct a dataclass ``cls`` from a plain ``data`` mapping.

    Required fields (those with no default) must be present; missing ones raise
    ``error_cls`` (mirroring pydantic's required-field behaviour).
    """
    hints = typing.get_type_hints(cls)
    kwargs: dict[str, Any] = {}
    for field in dataclasses.fields(cls):
        if field.name not in data:
            has_default = (
                field.default is not dataclasses.MISSING
                or field.default_factory is not dataclasses.MISSING
            )
            if has_default:
                continue
            raise error_cls(f'missing required field {field.name!r}')
        kwargs[field.name] = _coerce(hints[field.name], data[field.name], error_cls)
    return cls(**kwargs)


def load(cls: Any, databag: MutableMapping[str, str], error_cls: type[Exception]) -> Any:
    """``DatabagModel.load`` replacement: per-key ``json.loads`` then validate.

    Each databag key holds a JSON-encoded value (Juju's relation-databag
    convention). Unknown keys are ignored (matching pydantic's
    ``extra="ignore"``).
    """
    field_names = {f.name for f in dataclasses.fields(cls)}
    try:
        data = {k: json.loads(v) for k, v in databag.items() if k in field_names}
    except json.JSONDecodeError as e:
        msg = f'invalid databag contents: expecting json. {databag}'
        logger.error(msg)
        raise error_cls(msg) from e

    try:
        return _build(cls, data, error_cls)
    except (TypeError, ValueError, KeyError) as e:
        msg = f'failed to validate databag: {databag}'
        logger.debug(msg, exc_info=True)
        raise error_cls(msg) from e
