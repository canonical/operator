# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Databag load helper that recursively coerces nested dataclasses and enums.

``ops.Relation.load``'s default decoder hands back raw dicts/strings for
nested fields; writes go through ``ops.Relation.save`` directly.
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
    """Construct a dataclass ``cls`` from ``data``, raising ``error_cls`` on missing fields."""
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
    """JSON-decode each known databag key and build ``cls``; unknown keys are ignored."""
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
