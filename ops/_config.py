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

import ast
import importlib
import inspect
import logging
import pathlib
from typing import Any, ClassVar, cast

from ._private import yaml
from .model import Secret

logger = logging.getLogger(__name__)


# TODO: If we end up with this file, _action_params, and _relation_data, then we
# should factor out this class into a common helper module.
class _AttributeDocstringExtractor(ast.NodeVisitor):
    def __init__(self):
        self.attribute_docs: dict[str, str] = {}
        self._last_attr = None

    def visit_ClassDef(self, node: ast.ClassDef):  # noqa: N802
        # We iterate over the class definition, looking for attribute assignments.
        # We also track any standalone strings, and when we find one we use it
        # for the docstring of the most recent attribute assignments.
        # This isn't perfect - but it should cover the majority of cases.
        for child in node.body:
            if isinstance(child, (ast.Assign, ast.AnnAssign)):
                target = None  # Make the type checker happy.
                if isinstance(child, ast.Assign):
                    target = child.targets[0]
                elif isinstance(child, ast.AnnAssign):
                    target = child.target
                assert isinstance(target, ast.Name)
                self._last_attr = target.id
            elif (
                isinstance(child, ast.Expr)
                and isinstance(child.value, ast.Constant)
                and self._last_attr
            ):
                self.attribute_docs[self._last_attr] = child.value.value
                self._last_attr = None
        self.generic_visit(node)


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

    ```{note}
    This is a dataclass, but can be any object that inherits from
    ``ops.ConfigBase``, and can be initialised with the raw Juju config passed
    as keyword arguments. Any errors should be indicated by raising
    ``ValueError`` (or a ``ValueError`` subclass) in initialisation.

    Inheriting from ``ops.ConfigBase`` is not strictly necessary, but it
    provides utility methods for translating the class to a YAML schema suitable
    for use with Juju.
    ```

    Use this in your charm class like so::

        class MyCharm(ops.CharmBase):
            def __init__(self, framework):
                super().__init__(framework)
                self.typed_config = self.load_config(MyConfig)

    If the config provided by Juju is not valid, the charm will exit after
    setting a blocked status with an error message based on the ``str()`` of the
    exception raised.
    """

    JUJU_TYPES: ClassVar[dict[str, str]] = {
        'bool': 'boolean',
        'int': 'int',
        'float': 'float',
        'str': 'string',
        'ops.Secret': 'secret',
        'ops.model.Secret': 'secret',
    }

    @classmethod
    def _get_attr_docstrings(cls) -> dict[str, str]:
        docs: dict[str, str] = {}
        # pydantic stores descriptions in the field object.
        if hasattr(cls, '__dataclass_fields__'):
            fields = cast(dict[str, Any], cls.__dataclass_fields__)  # type: ignore
            for attr, field in fields.items():
                if (
                    hasattr(field, 'default')
                    and hasattr(field.default, 'description')
                    and field.default.description
                ):
                    docs[attr] = field.default.description

        try:
            source_code = inspect.getsource(cls)
        except OSError:
            logger.debug('No source code found for %s', cls.__name__)
        else:
            try:
                tree = ast.parse(source_code)
            except (SyntaxError, IndentationError):
                logger.debug('Failed to parse source code for %s', cls.__name__)
            else:
                extractor = _AttributeDocstringExtractor()
                extractor.visit(tree)
                docs.update(extractor.attribute_docs)

        return docs

    @staticmethod
    def _extract_optional_type(attr: str, hint: str):
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

    @classmethod
    def attr_to_yaml_type(cls, attr: str, default: Any = None) -> str:
        """Provide the appropriate type for the config YAML for the given attribute.

        Raises:
            ValueError: if an appropriate type cannot be found.
        """
        types = cls.__annotations__
        try:
            hint = cls._extract_optional_type(attr, str(types[attr]))
        except (KeyError, ValueError):
            # If there's a default value, use that object's type.
            if default is not None and type(default).__name__ in cls.JUJU_TYPES:
                return cls.JUJU_TYPES[type(default).__name__]
            raise ValueError(f'{attr!r} type is unknown.') from None
        if hint not in cls.JUJU_TYPES:
            raise ValueError(f'{attr!r} type is unknown.') from None
        return cls.JUJU_TYPES[hint]

    @staticmethod
    def attr_name_to_yaml_name(name: str):
        """Convert from the class attribute name to the name used in the schema.

        Python names are snake_case, but Juju config option names should be
        kebab-case. Override if your config names do not match this pattern, for
        backwards compatibility, for example.
        """
        return name.replace('_', '-')

    @classmethod
    def _yaml_schema_from_basemodel(cls) -> dict[str, Any]:
        options = {}
        for name, field in cls.model_fields.items():  # type: ignore
            option = {}
            if field.default is not None:  # type: ignore
                option['default'] = field.default  # type: ignore
            if field.annotation in (bool, int, float, str, Secret):  # type: ignore
                hint = field.annotation.__name__  # type: ignore
            else:
                hint = str(field.annotation)  # type: ignore
                hint = cls._extract_optional_type(name, hint)  # type: ignore
            option['type'] = cls.JUJU_TYPES[hint]
            if field.description:  # type: ignore
                option['description'] = field.description  # type: ignore
            options[cls.attr_name_to_yaml_name(name)] = option  # type: ignore
        return {'options': options}

    @classmethod
    def to_yaml_schema(cls) -> dict[str, Any]:
        """Translate the class to YAML suitable for config.yaml.

        Using :attr:`MyConfig.to_yaml_schema` will generate a YAML schema
        suitable for use in ``config.yaml``. For example, with the class from
        the example above::

            print(yaml.safe_dump(MyConfig.to_yaml_schema()))

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
        """
        # Special-case pydantic BaseModel.
        if hasattr(cls, 'model_fields'):
            return cls._yaml_schema_from_basemodel()

        # Dataclasses, regular classes, etc.
        options: dict[str, dict[str, bool | int | float | str]] = {}
        for attr in dir(cls):
            if attr.startswith('_') or callable(getattr(cls, attr)):
                continue
            # Perhaps we should ignore anything that's typing.ClassVar?
            if attr == 'JUJU_TYPES':
                continue
            option = {}
            default = getattr(cls, attr, None)
            if type(default).__name__ in cls.JUJU_TYPES:
                option['default'] = default
            option['type'] = cls.attr_to_yaml_type(attr, default)
            doc = cls._get_attr_docstrings().get(attr)
            if doc:
                option['description'] = doc
            options[cls.attr_name_to_yaml_name(attr)] = option
        return {'options': options}

    @classmethod
    def to_starlark_validator(cls) -> str:
        """Validation code, as a Starlark script."""
        raise NotImplementedError('To be added at a later point.')


def generate_yaml_schema():
    """Look for all ConfigBase subclasses and generate their YAML schema.

    ```{caution}
    This imports modules, so is not safe to run on untrusted code.
    ```
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
    generate_yaml_schema()
