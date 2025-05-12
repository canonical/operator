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
import re
from typing import Any, ClassVar, Generator, get_args, get_origin, get_type_hints

from ._private import attrdocs


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
    """

    # We currently only handle the basic types that we expect to see in real
    # charms.
    _JSON_TYPES: ClassVar[dict[str, str]] = {
        'str': 'string',
        'bool': 'boolean',
        'int': 'integer',
        'float': 'number',
        "<class 'str'>": 'string',
        "<class 'bool'>": 'boolean',
        "<class 'int'>": 'integer',
        "<class 'float'>": 'number',
        "<class 'list'>": 'array',
        "<class 'tuple'>": 'array',
        'list[bool]': 'array',
        'list[int]': 'array',
        'list[float]': 'array',
        'list[str]': 'array',
    }

    @classmethod
    def __python_38_attr_to_json_type(cls, name: str) -> str | None:
        """Like _attr_to_json_type, but for Python 3.8.

        In Python 3.8, get_type_hints() fails with new-style type annotations,
        even with __future__ annotations is used. This provides a reasonable
        effort fallback.
        """
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
        return hint

    @classmethod
    def _attr_to_json_type(cls, name: str, default: Any = None) -> str:
        """Provide the appropriate type for the config YAML for the given attribute.

        If an appropriate type cannot be determined, fall back to "string".
        """
        try:
            raw_hint = get_type_hints(cls)[name]
        except KeyError:
            pass
        except TypeError:
            hint = cls.__python_38_attr_to_json_type(name)
            if hint:
                return cls._JSON_TYPES[str(hint)]
        else:
            # Collapse Optional[] and Union[] and so on to the simpler form.
            origin = get_origin(raw_hint)
            if origin in (list, tuple):
                return cls._JSON_TYPES[str(origin)]
            elif origin:
                hints = {arg for arg in get_args(raw_hint) if str(arg) in cls._JSON_TYPES}
            else:
                hints = {raw_hint}
            # If there are multiple types -- for example, the type annotation is
            # `int | str` -- then we can't determine the type, and we fall back
            # to "string", even if `str` is not in the type hint, because our
            # "we can't determine the type" choice is always "string".
            if len(hints) > 1:
                return 'string'
            elif hints:
                return cls._JSON_TYPES[str(hints.pop())]
        # If there's a default value, use that object's type.
        if default is not None:
            return cls._JSON_TYPES.get(type(default).__name__, 'string')
        # If we can't figure it out, then use "string", which should be the most
        # compatible, and most likely to be used for arbitrary types. Charms can
        # override `to_juju_schema` to adjust this if required.
        return 'string'

    @staticmethod
    def _attr_to_juju_name(attr: str):
        """Convert from the class attribute name to the name used in the schema.

        Python names are snake_case, but Juju action parameter names should be
        kebab-case.
        """
        return attr.replace('_', '-')

    @staticmethod
    def _juju_name_to_attr(attr: str):
        """Convert from the name used in the schema to the class attribute name.

        Python names are snake_case, but Juju action parameter names should be
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
    def _param_names(cls) -> Generator[str]:
        """Iterates over all the param names to include in the action YAML."""
        try:
            yield from (field.name for field in dataclasses.fields(cls))  # type: ignore
        except TypeError:
            pass
        else:
            return
        if hasattr(cls, 'model_fields'):
            yield from iter(cls.model_fields)  # type: ignore
            return
        # Fall back to using dir() and __annotations__.
        attrs = dir(cls)
        attrs.extend((a for a, t in cls.__annotations__.items() if get_origin(t) is not ClassVar))
        for attr in set(attrs):
            if attr.startswith('_') or (hasattr(cls, attr) and callable(getattr(cls, attr))):
                continue
            yield attr

    @classmethod
    def _attr_to_default(cls, name: str) -> tuple[Any, bool]:
        """Get the default value for the attribute.

        Return an appropriate default value for the attribute, and whether it is
        required.
        """
        required = True
        try:
            default = getattr(cls, name)
        except AttributeError:
            try:
                fields = {field.name: field for field in dataclasses.fields(cls)}  # type: ignore
            except TypeError:
                default = None
            else:
                field = fields[name]
                if field.default != dataclasses.MISSING:
                    default = field.default
                    required = False
                elif field.default_factory != dataclasses.MISSING:
                    default = field.default_factory()
                    required = False
                else:
                    default = None
        else:
            if default is not None:
                required = False
        if hasattr(default, 'default_factory') and callable(default.default_factory):  # type: ignore
            default = default.default_factory()  # type: ignore
        if hasattr(default, 'is_required'):
            required = default.is_required()  # type: ignore
            assert isinstance(required, bool)
        if str(type(default)) not in cls._JSON_TYPES:  # type: ignore
            default = None
            required = True
        return default, required

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
        # require anyone using anything more complicated to subclass
        # to_juju_schema and provide their own details (or to use a Pydantic
        # class).

        # Pydantic classes provide this, so we can just get it directly.
        if hasattr(cls, 'schema'):
            schema = cls.schema()  # type: ignore
            return schema['properties'], schema['required']  # type: ignore

        attr_docs = attrdocs.get_attr_docstrings(cls)
        params: dict[str, Any] = {}
        required_params: list[str] = []
        for attr in cls._param_names():
            param = {}
            default, required = cls._attr_to_default(attr)
            if default is not None:
                param['default'] = default

            try:
                hint_obj = get_type_hints(cls)[attr]
            except TypeError:
                # We can't handle enums in Python 3.8.
                hint_obj = None
            if isinstance(hint_obj, type) and issubclass(hint_obj, enum.Enum):
                param['type'] = 'string'
                param['enum'] = [m.value for m in hint_obj.__members__.values()]
            else:
                param['type'] = cls._attr_to_json_type(attr, default)

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
