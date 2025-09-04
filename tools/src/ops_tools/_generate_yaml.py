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

"""Generate charmcraft.yaml config and actions from Python classes."""

from __future__ import annotations

import dataclasses
import enum
import logging
import re
from typing import (
    Any,
    Final,
    Generator,
    Mapping,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

from typing_extensions import NotRequired

import ops

from . import _attrdocs

logger = logging.getLogger(__name__)


class OptionDict(TypedDict):
    type: str
    """The Juju option type."""

    description: NotRequired[str]
    default: NotRequired[bool | int | float | str]


class ActionDict(TypedDict, total=False):
    description: str
    params: dict[str, Any]
    """A dictionary of parameters for the action."""

    required: list[str]
    """A list of required parameters for the action."""

    additionalProperties: bool
    """Whether additional properties are allowed in the action parameters."""


JUJU_TYPES: Final[Mapping[type, str]] = {
    bool: 'boolean',
    int: 'int',
    float: 'float',
    str: 'string',
    ops.Secret: 'secret',
}

# We currently only handle the basic types that we expect to see in real charms.
# Arrays and objects (lists, tuples, and dicts) are handled without using this
# mapping.
JSON_TYPES: Final[Mapping[type, str]] = {
    bool: 'boolean',
    int: 'integer',
    float: 'number',
    str: 'string',
}


def attr_to_default(cls: type[object], name: str) -> object:
    """Get the default value for the attribute."""
    if not dataclasses.is_dataclass(cls):
        return getattr(cls, name, None)
    for field in dataclasses.fields(cls):
        if field.name == name:
            break
    else:
        return None

    # This might be a Pydantic dataclass using a Pydantic.Field object.
    field_default = (  # type: ignore
        field.default.default  # type: ignore
        if hasattr(field.default, 'default')
        else field.default
    )
    field_default_factory = (  # type: ignore
        field.default.default_factory  # type: ignore
        if hasattr(field.default, 'default_factory')
        else field.default_factory
    )
    # A hack to avoid importing Pydantic here.
    if (
        'PydanticUndefinedType' not in str(type(field_default))  # type: ignore
        and field_default is not dataclasses.MISSING
    ):
        return field_default  # type: ignore
    if field_default_factory is not dataclasses.MISSING:
        return field_default_factory()  # type: ignore
    return None


def _attr_to_yaml_type(cls: type[object], name: str, yaml_types: dict[type, str]) -> str:
    try:
        raw_hint = get_type_hints(cls)[name]
    except KeyError:
        pass
    else:
        # Collapse Optional[] and Union[] and so on to the simpler form.
        origin = get_origin(raw_hint)
        if origin in (list, tuple):
            return yaml_types[origin]
        elif origin:
            hints = {arg for arg in get_args(raw_hint) if arg in yaml_types}
        else:
            hints = {raw_hint}
        # If there are multiple types -- for example, the type annotation is
        # `int | str` -- then we can't determine the type, and we fall back to
        # "string", even if `str` is not in the type hint, because our
        # "we can't determine the type" choice is always "string".
        if len(hints) > 1:
            return 'string'
        elif hints:
            try:
                return yaml_types[hints.pop()]
            except KeyError:
                pass
    # If we can't figure it out, then use "string", which should be the most
    # compatible, and most likely to be used for arbitrary types. Charms can
    # override `to_juju_schema` to adjust this if required.
    return 'string'


def attr_to_juju_type(cls: type[object], name: str) -> str:
    """Provide the appropriate type for the config YAML for the given class attribute.

    If an appropriate type cannot be determined, fall back to "string".
    """
    return _attr_to_yaml_type(cls, name, JUJU_TYPES)


def attr_to_json_type(cls: type[object], name: str) -> str:
    """Provide the appropriate type for the action YAML for the given attribute.

    If an appropriate type cannot be determined, fall back to "string".
    """
    return _attr_to_yaml_type(cls, name, JSON_TYPES)


def juju_schema_from_model_fields(cls: type[object]) -> dict[str, OptionDict]:
    """Generate a Juju schema from the model fields of a Pydantic model."""
    # The many type: ignores are required because we don't want to import
    # pydantic in this code.
    options: dict[str, OptionDict] = {}
    for name, field in cls.model_fields.items():  # type: ignore
        option = {}
        if 'PydanticUndefinedType' not in str(type(field.default)) and field.default is not None:  # type: ignore
            default = field.default  # type: ignore
        elif field.default_factory is not None:  # type: ignore
            default = field.default_factory()  # type: ignore
        else:
            default = None
        if default is not None:
            if type(default) in JUJU_TYPES:  # type: ignore
                option['default'] = default
            else:
                option['default'] = str(default)  # type: ignore
        if field.annotation in (bool, int, float, str, ops.Secret):  # type: ignore
            hint = JUJU_TYPES[field.annotation]
        else:
            hint = field.annotation  # type: ignore
            if get_origin(hint):  # type: ignore
                hints = {arg for arg in get_args(hint) if arg in JUJU_TYPES}
                if len(hints) > 1:
                    hint = type(str)
                elif hints:
                    hint = hints.pop()
            hint = JUJU_TYPES.get(hint, 'string')  # type: ignore
        option['type'] = hint
        if field.description:  # type: ignore
            option['description'] = field.description  # type: ignore
        options[name.replace('_', '-')] = option  # type: ignore
    return options


def juju_names(cls: type[object]) -> Generator[str]:
    """Iterates over all the names to include in the config or action YAML."""
    if dataclasses.is_dataclass(cls):
        for field in dataclasses.fields(cls):
            yield field.name
        return
    if hasattr(cls, 'model_fields'):
        for field in cls.model_fields.values():  # type: ignore
            yield field.name  # type: ignore
        return
    # If this isn't a dataclass or a Pydantic model, then fall back to using
    # any class attribute with a type annotation.
    yield from get_type_hints(cls)


def to_json_schema(cls: type[object]) -> tuple[dict[str, Any], list[str]]:
    """Translate the class to JSONSchema suitable for use in ``charmcraft.yaml``.

    This only handles simple types (strings, Booleans, integers, floats, tuples,
    and lists).

    Returns a dictionary that can be dumped to YAML and a list of required
    params.
    """
    # As of March 2025, most charms use only simple parameter types, despite
    # being able to use anything that JSONSchema offers. The 'type' breakdown
    # among the charms analysed is:
    #   * 'string': 158
    #   * 'boolean': 16
    #   * 'array': 10
    #   * 'integer': 7
    #   * 'number': 2
    #   * 'object': 1
    # Only one charm has a `properties' field that further defines the
    # parameter. It seems reasonable to handle all of the simple cases and
    # require anyone using anything more complicated to provide a custom
    # to_juju_schema and provide their own details (or to use a Pydantic
    # class).

    attr_docs = _attrdocs.get_attr_docstrings(cls)
    params: dict[str, Any] = {}
    required_params: list[str] = []
    for attr in sorted(juju_names(cls)):
        param = {}

        hint_obj = get_type_hints(cls)[attr]
        origin = get_origin(hint_obj)
        args = get_args(hint_obj)
        if isinstance(hint_obj, type) and issubclass(hint_obj, enum.Enum):
            param['type'] = 'string'
            param['enum'] = [m.value for m in hint_obj.__members__.values()]
        elif isinstance(origin, type) and issubclass(origin, (list, tuple)):
            param['type'] = 'array'
            if issubclass(origin, list) and len(args) == 1:
                param['items'] = {'type': JSON_TYPES.get(args[0], 'string')}
        else:
            param['type'] = attr_to_json_type(cls, attr)

        default = attr_to_default(cls, attr)
        if default is None:
            required = True
        else:
            required = False
            if type(default) not in (bool, int, float, str, list, tuple):
                default = str(default)
            if not issubclass(type(default), (list, tuple)) or len(default) > 0:
                param['default'] = default

        doc = attr_docs.get(attr)
        if doc:
            param['description'] = doc
        json_name = attr.replace('_', '-')
        params[json_name] = param
        if required:
            required_params.append(json_name)

    required_params.sort()
    return params, required_params


def config_to_juju_schema(cls: type[object]) -> dict[str, dict[str, OptionDict]]:
    """Translate the class to YAML suitable for charmcraft.yaml.

    For example::

        >>> import pydantic
        >>> import yaml
        >>> class MyConfig(pydantic.BaseModel):
        ...     my_bool: bool = pydantic.Field(default=False, description='A boolean value.')
        ...     my_float: float = pydantic.Field(
        ...         default=3.14, description='A floating point value.'
        ...     )
        ...     my_int: int = pydantic.Field(default=42, description='An integer value.')
        ...     my_str: str = pydantic.Field(default="foo", description='A string value.')
        ...     my_secret: ops.Secret | None = pydantic.Field(
        ...         default=None, description='A user secret.'
        ...     )
        ...     class Config:
        ...         arbitrary_types_allowed = True
        >>> print(yaml.safe_dump(config_to_juju_schema(MyConfig)))
        options:
          my-bool:
            default: false
            description: A boolean value.
            type: boolean
          my-float:
            default: 3.14
            description: A floating point value.
            type: float
          my-int:
            default: 42
            description: An integer value.
            type: int
          my-secret:
            description: A user secret.
            type: secret
          my-str:
            default: foo
            description: A string value.
            type: string
        <BLANKLINE>

    Options with a default value of ``None`` will not have a ``default`` key
    in the output. If the type of the option cannot be determined, it will
    be set to ``string``. If there is a default value, but it is not one of the
    Juju option types, the ``str()`` representation of the value will be used.

    To customise, define a ``to_juju_schema`` method in your class. For example::

        @classmethod
        def to_juju_schema(cls, schema: dict[str, OptionDict]) -> dict[str, OptionDict]:
            # Change the key names to upper-case.
            schema = {key.upper(): value for key, value in schema.items()}
            return schema
    """
    if hasattr(cls, 'model_fields'):
        # Special-case pydantic BaseModel or anything else with a compatible
        # `model_fields`` attribute.
        options = juju_schema_from_model_fields(cls)
    else:
        # Dataclasses, regular classes, etc.
        attr_docstrings = _attrdocs.get_attr_docstrings(cls)
        options: dict[str, OptionDict] = {}
        for attr in sorted(juju_names(cls)):
            option: OptionDict = {'type': attr_to_juju_type(cls, attr)}
            default = attr_to_default(cls, attr)
            if default is not None:
                if type(default) in JUJU_TYPES:
                    option['default'] = default
                else:
                    option['default'] = str(default)
            doc = attr_docstrings.get(attr)
            if doc:
                option['description'] = doc
            options[attr.replace('_', '-')] = option

    if hasattr(cls, 'to_juju_schema'):
        # If the class has a custom `to_juju_schema` method, call it.
        # This allows the class to override the default schema generation.
        return {'options': cls.to_juju_schema(options)}  # type: ignore
    return {'options': options}


def action_to_juju_schema(cls: type[object]) -> dict[str, Any]:
    """Translate the class to a dictionary suitable for ``charmcraft.yaml``.

    For example::

        >>> import enum
        >>> import pydantic
        >>> import yaml
        >>> class RunBackup(pydantic.BaseModel):
        ...     '''Backup the database.'''
        ...     class Compression(enum.Enum):
        ...         GZ = 'gzip'
        ...         BZ = 'bzip2'
        ...
        ...     filename: str = pydantic.Field(description='The name of the backup file.')
        ...     compression: Compression = pydantic.Field(
        ...         Compression.GZ,
        ...         description='The type of compression to use.',
        ...     )
        >>> print(yaml.safe_dump(action_to_juju_schema(RunBackup)))
        run-backup:
          additionalProperties: false
          description: Backup the database.
          params:
            compression:
              type: string
              default: gzip
              description: The type of compression to use.
              enum: [gzip, bzip2]
            filename:
              description: The name of the backup file.
              title: Filename
              type: string
          required:
          - filename
        <BLANKLINE>
        >>>

    To adjust the YAML, provide a ``to_juju_schema`` method in the class. For
    example, to allow additional properties::

        def to_juju_schema(cls, schema: dict[str, ActionDict]) -> dict[str, ActionDict]:
            schema['run-backup']['additionalProperties'] = True
            return schema
    """
    # As of March 2025, there are no known charms that are using
    # execution-group or parallel, so we don't support those here. If any
    # charms do need them, they can change the output by defining a
    # `to_juju_schema` method.
    action = {}
    if cls.__doc__:
        action['description'] = cls.__doc__
    # Pydantic classes provide this, so we can just get it directly.
    # The type: ignores are to avoid importing pydantic.
    if hasattr(cls, 'schema'):
        schema = cls.schema()  # type: ignore
        params = {key.replace('_', '-'): value for key, value in schema['properties'].items()}  # type: ignore
        required_params = [key.replace('_', '-') for key in schema['required']]  # type: ignore
        required_params.sort()  # type: ignore
    else:
        params, required_params = to_json_schema(cls)
    if params:
        action['params'] = params
    if required_params:
        action['required'] = required_params
    action['additionalProperties'] = False
    # Add a ``-`` after each A-Z character of the class name, and then
    # lower-case the resulting string. Drop any 'action' suffix.
    action_name = cls.__name__
    if action_name.lower().endswith('action'):
        action_name = action_name[: -len('action')].rstrip('-')
    action_name = re.sub(r'(?<!^)([A-Z])', r'-\1', action_name).lower()
    if hasattr(cls, 'to_juju_schema'):
        # If the class has a custom `to_juju_schema` method, call it.
        # This allows the class to override the default schema generation.
        return cls.to_juju_schema({action_name: action})  # type: ignore
    return {action_name: action}
