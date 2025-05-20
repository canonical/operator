# Copyright 2025 Canonical Ltd.
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

"""Support for strongly typed charm config."""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, ClassVar, Final, Generator, Mapping, get_args, get_origin, get_type_hints

from ._private import attrdocs
from .model import Secret

logger = logging.getLogger(__name__)


_JUJU_TYPES: Final[Mapping[str, str]] = {
    'bool': 'boolean',
    'int': 'int',
    'float': 'float',
    'str': 'string',
    "<class 'bool'>": 'boolean',
    "<class 'int'>": 'int',
    "<class 'float'>": 'float',
    "<class 'str'>": 'string',
    'ops.Secret': 'secret',
    'ops.model.Secret': 'secret',
    "<class 'ops.Secret'>": 'secret',
    "<class 'ops.model.Secret'>": 'secret',
}


def _attr_to_juju_type(cls: type[object], name: str, default: Any = None) -> str:
    """Provide the appropriate type for the config YAML for the given class attribute.

    If possible, use the type hint from the class attribute, ignoring
    optionality. Fall back to the type of the default value if it is not None.

    If an appropriate type cannot be determined, fall back to "string".
    """
    try:
        raw_hint = get_type_hints(cls)[name]
    except KeyError:
        pass
    except TypeError:
        # In Python 3.8, this fails even though __future__ annotations is
        # used. Provide a reasonable effort fallback.
        hint = cls.__annotations__.get(name)
        if hint and '|' in hint:
            hints = {h.strip() for h in hint.split('|')}
            try:
                hints.remove('None')
            except ValueError:
                pass
            if len(hints) > 1:
                return 'string'
            hint = hints.pop()
        if hint and hint.startswith('Optional['):
            hint = hint[9:-1]
        if hint:
            return _JUJU_TYPES[str(hint)]
    else:
        # Collapse Optional[] and Union[] and so on to the simpler form.
        if get_origin(raw_hint):
            hints = {arg for arg in get_args(raw_hint) if str(arg) in _JUJU_TYPES}
        else:
            hints = {raw_hint}
        # If there are multiple types -- for example, the type annotation is
        # `int | str` -- then we can't determine the type, and we fall back
        # to "string", even if `str` is not in the type hint, because our
        # "we can't determine the type" choice is always "string".
        if len(hints) > 1:
            return 'string'
        elif hints:
            try:
                return _JUJU_TYPES[str(hints.pop())]
            except KeyError:
                pass
    # If there's a default value, use that object's type.
    if default is not None:
        return _JUJU_TYPES.get(type(default).__name__, 'string')
    # If we can't figure it out, then use "string", which should be the most
    # compatible, and most likely to be used for arbitrary types. Charms can
    # override `to_juju_schema` to adjust this if required.
    return 'string'


def _juju_schema_from_model_fields(cls: type[object]) -> dict[str, Any]:
    options = {}
    for name, field in cls.model_fields.items():  # type: ignore
        option = {}
        if field.default is not None:  # type: ignore
            option['default'] = field.default  # type: ignore
        if field.annotation in (bool, int, float, str, Secret):  # type: ignore
            hint = _JUJU_TYPES[field.annotation.__name__]  # type: ignore
        else:
            hint = field.annotation  # type: ignore
            if get_origin(hint):
                hints = {arg for arg in get_args(hint) if str(arg) in _JUJU_TYPES}
                if len(hints) > 1:
                    hint = type(str)
                elif hints:
                    hint = hints.pop()
            hint = _JUJU_TYPES.get(str(hint), 'string')  # type: ignore
        option['type'] = hint
        if field.description:  # type: ignore
            option['description'] = field.description  # type: ignore
        options[name.replace('_', '-')] = option  # type: ignore
    return {'options': options}


def _juju_names(cls: type[object]) -> Generator[str]:
    """Iterates over all the option names to include in the config YAML."""
    try:
        yield from (field.name for field in sorted(dataclasses.fields(cls)))  # type: ignore
    except TypeError:
        pass
    else:
        return
    if hasattr(cls, 'model_fields'):
        yield from sorted(cls.model_fields)  # type: ignore
        return
    # Fall back to using dir() and __annotations__.
    attrs = dir(cls)
    attrs.extend((a for a, t in cls.__annotations__.items() if get_origin(t) is not ClassVar))
    for attr in sorted(set(attrs)):
        if attr.startswith('_') or (hasattr(cls, attr) and callable(getattr(cls, attr))):
            continue
        yield attr


class ConfigBase:
    """Base class for strongly typed charm config.

    Use ``ConfigBase`` as a base class for your config class, and define the
    attributes as you would in ``charmcraft.yaml``. For example::

        @dataclasses.dataclass(frozen=True)
        class MyConfig(ops.ConfigBase):
            my_bool: bool | None = None
            '''A boolean value.'''
            my_float: float = 3.14
            '''A floating point value.'''
            my_int: int = 42
            '''An integer value.'''
            my_str: str = "foo"
            '''A string value.'''
            my_secret: ops.Secret | None = None
            '''A user secret.'''

    .. note::

        This example is a dataclass, but the class can be any that inherits from
        ``ops.ConfigBase``, and that can be initialised with the raw Juju config
        passed as keyword arguments. Any errors should be indicated by raising
        ``ValueError`` (or a ``ValueError`` subclass) in initialisation.

        Inheriting from ``ops.ConfigBase`` is not strictly necessary, but it
        provides a utility method for translating the class to a YAML schema
        suitable for use with Juju.

    Use this in your charm class like so::

        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.typed_config = self.load_config(MyConfig)
    """

    @classmethod
    def to_juju_schema(cls) -> dict[str, Any]:
        """Translate the class to YAML suitable for config.yaml.

        Using :attr:`ConfigBase.to_juju_schema` will generate a YAML schema
        suitable for use in ``config.yaml``. For example, with the class from
        the example above::

            print(yaml.dump(MyConfig.to_juju_schema()))

        Will output::

            options:
                my-bool:
                    type: boolean
                    description: A boolean value.
                my-float:
                    type: float
                    default: 3.14
                    description: A floating point value.
                my-int:
                    type: int
                    default: 42
                    description: An integer value.
                my-str:
                    type: string
                    default: foo
                    description: A string value.
                my-secret:
                    type: secret
                    description: A user secret.

        Options with a default value of ``None`` will not have a ``default`` key
        in the output. If the type of the option cannot be determined, it will
        be set to ``string``.

        To customise, override this method in your subclass. For example::

            @classmethod
            def to_juju_schema(cls) -> dict[str, Any]:
                schema = super().to_juju_schema()
                # Change the key names to upper-case.
                schema = {key.upper(): value for key, value in schema.items()}
                return schema
        """
        # Special-case pydantic BaseModel or anything else with a compatible
        # `model_fields`` attribute.
        if hasattr(cls, 'model_fields'):
            return _juju_schema_from_model_fields(cls)

        # Dataclasses, regular classes, etc.
        attr_docstrings = attrdocs.get_attr_docstrings(cls)
        options: dict[str, dict[str, bool | int | float | str]] = {}
        for attr in _juju_names(cls):
            option = {}
            default = getattr(cls, attr, None)
            if default is not None and type(default).__name__ in _JUJU_TYPES:
                option['default'] = default
            option['type'] = _attr_to_juju_type(cls, attr, default)
            doc = attr_docstrings.get(attr)
            if doc:
                option['description'] = doc
            options[attr.replace('_', '-')] = option
        return {'options': options}
