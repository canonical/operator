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

import importlib
import logging
import pathlib
from typing import Any, ClassVar, Generator

from ._private import attrdocs, yaml
from .model import Secret

logger = logging.getLogger(__name__)


class ConfigBase:
    """Base class for strongly typed charm config.

    Use :class:`ConfigBase` as a base class for your config class, and define
    the attributes as you would in ``charmcraft.yaml``. For example::

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

        This is a dataclass, but can be any object that inherits from
        ``ops.ConfigBase``, and can be initialised with the raw Juju config
        passed as keyword arguments. Any errors should be indicated by raising
        ``ValueError`` (or a ``ValueError`` subclass) in initialisation.

        Inheriting from ``ops.ConfigBase`` is not strictly necessary, but it
        provides utility methods for translating the class to a YAML schema suitable
        for use with Juju.

    Use this in your charm class like so::

        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.typed_config = self.load_config(MyConfig)

    If the config provided by Juju is not valid, the charm will exit after
    setting a blocked status with an error message based on the ``str()`` of the
    exception raised.
    """

    _JUJU_TYPES: ClassVar[dict[str, str]] = {
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
    }

    @staticmethod
    def __extract_optional_type(attr: str, hint: str):
        if 'Optional[' in hint:
            hint = hint.split('[')[1].split(']')[0]
        if '|' in hint:
            parts = [p.strip() for p in hint.split('|')]
            if 'None' in parts:
                parts.remove('None')
            if len(parts) != 1:
                raise ValueError(f'{attr!r} has multiple types.')
            hint = parts[0]
        return hint

    # TODO: now that we're not really exposing these methods, maybe they should
    # not raise? We could fall back to string maybe? We want someone to be able
    # to subclass and use to_juju_schema with super and then change things.

    @classmethod
    def _attr_to_juju_type(cls, name: str, default: Any = None) -> str:
        """Provide the appropriate type for the config YAML for the given attribute.

        Raises:
            ValueError: if an appropriate type cannot be found.
        """
        # TODO: This can probably use dataclasses.fields().
        types = cls.__annotations__
        try:
            hint = cls.__extract_optional_type(name, str(types[name]))
        except (KeyError, ValueError):
            # If there's a default value, use that object's type.
            if default is not None and type(default).__name__ in cls._JUJU_TYPES:
                return cls._JUJU_TYPES[type(default).__name__]
            raise ValueError(f'{name!r} type is unknown.') from None
        if hint not in cls._JUJU_TYPES:
            raise ValueError(f'{name!r} type is unknown.') from None
        return cls._JUJU_TYPES[hint]

    @staticmethod
    def _attr_to_juju_name(attr: str):
        """Convert from the class attribute name to the name used in the schema.

        Python names are snake_case, but Juju config option names should be
        kebab-case.
        """
        return attr.replace('_', '-')

    @staticmethod
    def _juju_name_to_attr(attr: str):
        """Convert from the schema name to the class attribute name.

        Python names are snake_case, but Juju config option names should be
        kebab-case.
        """
        return attr.replace('-', '_')

    @classmethod
    def _juju_names(cls) -> Generator[str, None, None]:
        """Iterates over all the option names to include in the config YAML.

        By default, this is ``dir(cls)``, any keys from ``cls.__annotations``,
        and any keys from ``cls.__dataclass_fields__``, excluding any callables
        and any names that start with an underscore, and the ``JUJU_TYPES``
        name.
        """
        attrs = dir(cls)
        attrs.extend(cls.__annotations__)
        # TODO: this can probably use dataclasses.fields().
        if hasattr(cls, '__dataclass_fields__'):
            attrs.extend(cls.__dataclass_fields__)  # type: ignore
        for attr in set(attrs):
            if attr.startswith('_') or (hasattr(cls, attr) and callable(getattr(cls, attr))):
                continue
            # Perhaps we should ignore anything that's typing.ClassVar?
            if attr == 'JUJU_TYPES':
                continue
            yield attr

    @classmethod
    def __juju_schema_from_basemodel(cls) -> dict[str, Any]:
        options = {}
        for name, field in cls.model_fields.items():  # type: ignore
            option = {}
            if field.default is not None:  # type: ignore
                option['default'] = field.default  # type: ignore
            if field.annotation in (bool, int, float, str, Secret):  # type: ignore
                hint = field.annotation.__name__  # type: ignore
            else:
                hint = str(field.annotation)  # type: ignore
                hint = cls.__extract_optional_type(name, hint)  # type: ignore
            option['type'] = cls._JUJU_TYPES[hint]
            if field.description:  # type: ignore
                option['description'] = field.description  # type: ignore
            options[cls._attr_to_juju_name(name)] = option  # type: ignore
        return {'options': options}

    @classmethod
    def to_juju_schema(cls) -> dict[str, Any]:
        """Translate the class to YAML suitable for config.yaml.

        Using :attr:`ConfigBase.to_juju_schema` will generate a YAML schema
        suitable for use in ``config.yaml``. For example, with the class from
        the example above::

            print(yaml.safe_dump(MyConfig.to_juju_schema()))

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

        To customise, override this method in your subclass. For example::

            @classmethod
            def to_juju_schema(cls) -> dict[str, Any]:
                schema = super().to_juju_schema()
                # Change the key names to upper-case.
                schema = {key.upper(): value for key, value in schema.items()}
                return schema
        """
        # Special-case pydantic BaseModel.
        if hasattr(cls, 'model_fields'):
            return cls.__juju_schema_from_basemodel()

        # Dataclasses, regular classes, etc.
        attr_docstrings = attrdocs.get_attr_docstrings(cls)
        options: dict[str, dict[str, bool | int | float | str]] = {}
        for attr in cls._juju_names():
            option = {}
            default = getattr(cls, attr, None)
            if type(default).__name__ in cls._JUJU_TYPES:
                option['default'] = default
            option['type'] = cls._attr_to_juju_type(attr, default)
            doc = attr_docstrings.get(attr)
            if doc:
                option['description'] = doc
            options[cls._attr_to_juju_name(attr)] = option
        return {'options': options}


def generate_juju_schema():
    """Look for all ConfigBase subclasses and generate their YAML schema.

    .. caution::

        This imports modules, so is not safe to run on untrusted code.
    """
    config: dict[str, Any] = {}
    for name in pathlib.Path('src').glob('*.py'):
        module_name = name.stem
        module = importlib.import_module(f'src.{module_name}')
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if hasattr(obj, 'to_yaml_schema'):
                config.update(obj.to_yaml_schema())
    print(yaml.safe_dump(config))


if __name__ == '__main__':
    generate_juju_schema()

# TODO: Verify that if future annotations is not used, everything still works
# as expected (or make this an explicit requirement).

# TODO: if no config is found, have Scenario try to generate it.

# TODO: test_main check to verify that the clean exit works correctly.
