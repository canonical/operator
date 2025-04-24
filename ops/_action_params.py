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

"""Support for strongly typed action parameters."""

from __future__ import annotations

import dataclasses
import enum
import importlib
import pathlib
import re
import sys
from typing import Any, ClassVar, Generator

from ._private import attrdocs, yaml


class ActionBase:
    """Base class for strongly typed charm actions.

    Use :class:`ActionBase` as a base class for your actions, and define the
    attributes as you would in ``charmcraft.yaml``. For example::

        class Compression(enum.Enum):
            GZ = 'gzip'
            BZ = 'bzip2'

        @dataclasses.dataclass(frozen=True)
        class RunBackup(ops.ActionBase):
            '''Backup the database.'''

            filename: str
            '''The name of the backup file.'''

            compression: Compression = Compression.GZ
            '''The type of compression to use.'''

        @dataclasses.dataclass(frozen=True)
        class AddAdminUser(ops.ActionBase):
            '''Add a new admin user and return their credentials.'''

            username: str

    .. note::

        These are dataclasses, but can be any objects that inherit from
        ``ops.ActionBase``, and can be initialised with the raw Juju action
        params passed as keyword arguments. Any errors should be indicated by
        raising ``ValueError`` (or a ``ValueError`` subclass) in initialisation.

        Inheriting from ``ops.ActionBase`` is not strictly necessary, but it
        provides utility methods for translating the class to a YAML schema
        suitable for use with Juju.

    Use this in your charm class like so::

        class MyCharm(ops.CharmBase):
            def __init__(self, framework):
                super().__init__(framework)
                framework.observe(self.on['run-backup'].action, self._on_run_backup)
                framework.observe(self.on['add-admin-user'].action, self._on_add_admin_user)

            def _on_run_backup(self, event: ops.ActionEvent):
                params = event.load_params(RunBackup)
                ...

            def _on_add_admin_user(self, event: ops.ActionEvent):
                params = event.load_params(AddAdminUser)
                ...

    If the params provided by Juju are not valid, the action will fail and exit
    the hook when the class is initialised, using the ``str()`` of the exception
    raised as the failure message.
    """

    # We currently only handle the basic types that we expect to see in real
    # charms.
    _JSON_TYPES: ClassVar[dict[str, str]] = {
        'str': 'string',
        'bool': 'boolean',
        'int': 'integer',
        'float': 'number',
        'list': 'array',
        'list[str]': 'array',
        'list[bool]': 'array',
        'list[int]': 'array',
        'list[float]': 'array',
        "<class 'str'>": 'string',
        "<class 'bool'>": 'boolean',
        "<class 'int'>": 'integer',
        "<class 'float'>": 'number',
        "<class 'list'>": 'array',
    }

    @classmethod
    def _attr_to_json_type(cls, attr: str, default: Any = None) -> str:
        """Provide the appropriate type for the action JSONSchema for the given attribute.

        Raises:
            ValueError: if an appropriate type cannot be found.
        """
        types = cls.__annotations__.copy()
        for parent in cls.__mro__:
            if not hasattr(parent, '__annotations__'):
                continue
            for n, t in parent.__annotations__.items():
                if n not in types:
                    types[n] = t
        try:
            hint = str(types[attr])
        except (KeyError, ValueError):
            # If there's a default value, use that object's type.
            if default is not None and type(default).__name__ in cls._JSON_TYPES:
                return cls._JSON_TYPES[type(default).__name__]
            raise ValueError(f'{attr!r} type is unknown.') from None
        if hint not in cls._JSON_TYPES:
            raise ValueError(f'{attr!r} type ({hint!r}) is unknown.') from None
        return cls._JSON_TYPES[hint]

    @staticmethod
    def _attr_to_juju_name(attr: str):
        """Convert from the class attribute name to the name used in the schema.

        Python names are snake_case, but Juju config option names should be
        kebab-case.
        """
        return attr.replace('_', '-')

    @staticmethod
    def _juju_name_to_attr(attr: str):
        """Convert from the name used in the schema to the class attribute name.

        Python names are snake_case, but Juju config option names should be
        kebab-case.
        """
        return attr.replace('-', '_')

    @classmethod
    def _class_to_action_name(cls):
        """Convert the name of the class to the name of the action.

        The default behaviour is to add a ``-`` after each A-Z character of the
        class name, and then lower-case the resulting string.
        """
        return re.sub(r'(?<!^)([A-Z])', r'-\1', cls.__name__).lower()

    @classmethod
    def _param_names(cls) -> Generator[str, None, None]:
        """Iterates over all the param names to include in the action YAML.

        By default, this is ``dir(cls)``, any keys from ``cls.__annotations``,
        and any keys from ``cls.__dataclass_fields__``, excluding any callables
        and any names that start with an underscore, and the ``JSON_TYPES``
        name.
        """
        attrs = dir(cls)
        attrs.extend(cls.__annotations__)
        # TODO: this can probably be dataclasses.fields().
        if hasattr(cls, '__dataclass_fields__'):
            attrs.extend(cls.__dataclass_fields__)  # type: ignore
        for attr in set(attrs):
            if attr.startswith('_') or (hasattr(cls, attr) and callable(getattr(cls, attr))):
                continue
            # Perhaps we should ignore anything that's typing.ClassVar?
            if attr == 'JSON_TYPES':
                continue
            yield attr

    @classmethod
    def _to_json_schema(cls) -> tuple[dict[str, Any], list[str]]:
        """Translate the class to JSONSchema suitable for use in ``actions.yaml``.

        This only handles simple types (strings, Booleans, integers, floats,
        and lists).

        Returns a dictionary that can be dumped to YAML and a list of required
        params.
        """
        # As of March 2025, most charms use only simple parameter types, despite
        # being able to use anything that JSONSchema offers. The 'type'
        # breakdown among the charms analysed is:
        #   * 'string': 158
        #   * 'boolean': 16
        #   * 'array': 10
        #   * 'integer': 7
        #   * 'number': 2
        #   * 'object': 1
        # Only one charm has a `properties' field that further defines the
        # parameter. It seems reasonable to handle all of the simple cases and
        # require anyone using anything more complicated to subclass this method
        # and provide their own details (or to use a Pydantic class).

        # Pydantic classes provide this, so we can just get it directly.
        if hasattr(cls, 'schema'):
            schema = cls.schema()  # type: ignore
            return schema['properties'], schema['required']  # type: ignore

        attr_docs = attrdocs.get_attr_docstrings(cls)
        params: dict[str, Any] = {}
        required_params: list[str] = []
        for attr in cls._param_names():
            required = True
            param = {}
            try:
                default = getattr(cls, attr)
            except AttributeError:
                # TODO: probably this can use dataclasses.fields() instead.
                if hasattr(cls, '__dataclass_fields__'):
                    try:
                        field = cls.__dataclass_fields__[attr]  # type: ignore
                    except KeyError:
                        default = None
                    else:
                        if field.default != dataclasses.MISSING:  # type: ignore
                            default = field.default  # type: ignore
                            required = False
                        elif field.default_factory != dataclasses.MISSING:  # type: ignore
                            default = field.default_factory()  # type: ignore
                            required = False
                        else:
                            default = None
                else:
                    default = None
            else:
                required = False
            if hasattr(default, 'default_factory') and callable(default.default_factory):  # type: ignore
                default = default.default_factory()  # type: ignore
            if hasattr(default, 'is_required'):  # type: ignore
                required = default.is_required()  # type: ignore
            if type(default).__name__ in cls._JSON_TYPES:  # type: ignore
                param['default'] = default
            try:
                hint_obj = sys.modules[cls.__module__].__dict__[cls.__annotations__[attr]]
            except KeyError:
                param['type'] = cls._attr_to_json_type(attr, default)
            else:
                if issubclass(hint_obj, enum.Enum):
                    param['type'] = 'string'
                    param['enum'] = [m.value for m in hint_obj.__members__.values()]
            doc = attr_docs.get(attr)
            if doc:
                param['description'] = doc
            json_name = cls._attr_to_juju_name(attr)
            params[json_name] = param
            if required:
                required_params.append(json_name)

        return params, required_params

    @classmethod
    def to_juju_schema(cls) -> dict[str, Any]:
        """Translate the class to a dictionary suitable for actions.yaml.

        Using :attr:`ActionBase.to_juju_schema` will generate a YAML schema
        suitable for use in ``actions.yaml``. For example, with the class from
        the example above::

            print(yaml.safe_dump(RunBackup.to_juju_schema()))

        Will output::

            run-backup:
                description: Backup the database.
                params:
                    filename:
                        type: string
                        description: The name of the backup file.
                    compression:
                        type: string
                        description: The type of compression to use.
                        default: gzip
                        enum: [gzip, bzip2]
                required: [filename]
                additionalProperties: false

        To customise, override this method in the subclass. For example, to
        allow additional properties::

            @classmethod
            def to_juju_schema(cls) -> dict[str, Any]:
                action = super().to_juju_schema()
                action['additionalProperties'] = True
                return action
        """
        # As of March 2025, there are no known charms that are using
        # execution-group or parallel, so we don't support those here. If any
        # charms do need them, they can override this method in the subclass and
        # add support there.
        action = {}
        if cls.__doc__:
            action['description'] = cls.__doc__
        params, required_params = cls._to_json_schema()
        if params:
            action['params'] = params
        if required_params:
            action['required'] = required_params
        action['additionalProperties'] = False
        action_name = cls._class_to_action_name()
        return {action_name: action}


def generate_juju_schema():
    """Look for all ActionBase subclasses and generate their YAML schema.

    .. caution::

        This imports modules, so is not safe to run on untrusted code.
    """
    actions: dict[str, Any] = {}
    for name in pathlib.Path('src').glob('*.py'):
        module_name = name.stem
        module = importlib.import_module(f'src.{module_name}')
        for attr_name in dir(module):
            obj = getattr(module, attr_name)
            if hasattr(obj, '_to_json_schema'):
                actions.update(obj.to_juju_schema())
    print(yaml.safe_dump(actions))


if __name__ == '__main__':
    generate_juju_schema()

# TODO: if __future__ annotations is not used, check if everything works, or
# make that an explicit requirement.
