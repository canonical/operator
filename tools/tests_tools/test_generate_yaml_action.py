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

from __future__ import annotations

import dataclasses
import enum
import logging
from typing import Any

import pytest

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

import ops_tools

logger = logging.getLogger(__name__)


class MyAction:
    """An action description."""

    basic_bool: bool
    basic_int: int
    basic_float: float
    basic_str: str

    my_str: str = 'foo'
    """A string value."""

    my_bool: bool = False
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
    """A floating point value."""

    my_list: list[str] = []  # noqa: RUF012
    """A list value."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class MyDataclassAction:
    """An action description."""

    basic_bool: bool
    basic_int: int
    basic_float: float
    basic_str: str

    my_str: str = 'foo'
    """A string value."""

    my_bool: bool = False
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
    """A floating point value."""

    my_list: list[str] = dataclasses.field(default_factory=list)  # type: ignore
    """A list value."""


_test_action_classes: list[tuple[type[object], str]] = [
    (MyAction, 'my'),
    (MyDataclassAction, 'my-dataclass'),
]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True)
    class MyPydanticDataclassAction:
        """An action description."""

        basic_bool: bool
        basic_int: int
        basic_float: float
        basic_str: str

        my_str: str = pydantic.Field('foo', description='A string value.')
        my_bool: bool = pydantic.Field(False, description='A Boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_list: list[str] = pydantic.Field(default_factory=list, description='A list value.')

    class MyPydanticBaseModelAction(pydantic.BaseModel):
        """An action description."""

        basic_bool: bool
        basic_int: int
        basic_float: float
        basic_str: str

        my_str: str = pydantic.Field('foo', alias='my-str', description='A string value.')
        my_bool: bool = pydantic.Field(
            False,
            alias='my-bool',
            description='A Boolean value.',
        )
        my_int: int = pydantic.Field(42, alias='my-int', description='A positive integer value.')
        my_float: float = pydantic.Field(
            3.14,
            alias='my-float',
            description='A floating point value.',
        )
        my_list: list[str] = pydantic.Field(
            alias='my-list',
            default_factory=list,
            description='A list value.',
        )

        class Config:
            frozen = True

    _test_action_classes.extend((
        (MyPydanticDataclassAction, 'my-pydantic-dataclass'),
        (MyPydanticBaseModelAction, 'my-pydantic-base-model'),
    ))


@pytest.mark.parametrize('action_class,action_name', _test_action_classes)
def test_action_yaml_schema(action_class: type[object], action_name: str):
    generated_schema = ops_tools.action_to_juju_schema(action_class)
    if hasattr(action_class, 'schema'):
        # Remove the 'title' property that Pydantic adds to make the schema more
        # consistent with the others for simpler testing.
        for prop in generated_schema[action_name]['params'].values():
            prop.pop('title', None)
    expected_schema: dict[str, Any] = {
        action_name: {
            'description': 'An action description.',
            'params': {
                'basic-bool': {'type': 'boolean'},
                'basic-float': {'type': 'number'},
                'basic-int': {'type': 'integer'},
                'basic-str': {'type': 'string'},
                'my-bool': {
                    'type': 'boolean',
                    'default': False,
                    'description': 'A Boolean value.',
                },
                'my-float': {
                    'type': 'number',
                    'default': 3.14,
                    'description': 'A floating point value.',
                },
                'my-int': {
                    'type': 'integer',
                    'default': 42,
                    'description': 'A positive integer value.',
                },
                'my-str': {
                    'type': 'string',
                    'default': 'foo',
                    'description': 'A string value.',
                },
                'my-list': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'A list value.',
                },
            },
            'required': ['basic-bool', 'basic-float', 'basic-int', 'basic-str'],
            'additionalProperties': False,
        },
    }
    assert generated_schema == expected_schema


def test_action_yaml_additional_properties():
    class ActionTrue:
        """An action."""

        x: int = 42

        @classmethod
        def to_juju_schema(
            cls: type[object], schema: dict[str, ops_tools.ActionDict]
        ) -> dict[str, ops_tools.ActionDict]:
            schema['action-true']['additionalProperties'] = True
            return schema

    generated_schema = ops_tools.action_to_juju_schema(ActionTrue)
    expected_schema = {
        'action-true': {
            'description': 'An action.',
            'params': {'x': {'type': 'integer', 'default': 42}},
            'additionalProperties': True,
        },
    }
    assert generated_schema == expected_schema

    class ActionDefault:
        """An action."""

        x: int = 42

        @classmethod
        def to_juju_schema(
            cls: type[object], schema: dict[str, ops_tools.ActionDict]
        ) -> dict[str, ops_tools.ActionDict]:
            del schema['action-default']['additionalProperties']
            return schema

    generated_schema = ops_tools.action_to_juju_schema(ActionDefault)
    expected_schema = {
        'action-default': {
            'description': 'An action.',
            'params': {'x': {'type': 'integer', 'default': 42}},
        },
    }
    assert generated_schema == expected_schema


def test_action_class_modification():
    class ActionMinimum:
        """An action."""

        x: int = 42

        @classmethod
        def to_juju_schema(
            cls, schema: dict[str, ops_tools.ActionDict]
        ) -> dict[str, ops_tools.ActionDict]:
            assert 'params' in schema['action-minimum']
            schema['action-minimum']['params']['x']['minimum'] = 0
            return schema

    generated_schema = ops_tools.action_to_juju_schema(ActionMinimum)
    expected_schema = {
        'action-minimum': {
            'description': 'An action.',
            'additionalProperties': False,
            'params': {'x': {'type': 'integer', 'default': 42, 'minimum': 0}},
        },
    }
    assert generated_schema == expected_schema


class Mode(enum.Enum):
    FULL = 'full'
    ADD = 'add'
    REMOVE = 'remove'


class Rebalance:
    """Trigger a rebalance of cluster partitions based on configured goals"""

    mode: Mode
    """The operation to issue to the balancer."""


def test_action_enum():
    generated_yaml = ops_tools.action_to_juju_schema(Rebalance)
    expected_yaml = {
        'rebalance': {
            'description': 'Trigger a rebalance of cluster partitions based on configured goals',
            'additionalProperties': False,
            'required': ['mode'],
            'params': {
                'mode': {
                    'type': 'string',
                    'description': 'The operation to issue to the balancer.',
                    'enum': ['full', 'add', 'remove'],
                },
            },
        },
    }
    assert generated_yaml == expected_yaml


class oneaction: ...  # noqa: N801


class OneAction: ...


class oNeAcTioN: ...  # noqa: N801


class TheOneAction: ...


class MYOneAction: ...


class ABC: ...


class myOneAction: ...  # noqa: N801


class DoThisThing: ...


@pytest.mark.parametrize(
    'cls,action_name',
    [
        (oneaction, 'one'),
        (OneAction, 'one'),
        (oNeAcTioN, 'o-ne'),
        (TheOneAction, 'the-one'),
        (MYOneAction, 'm-y-one'),
        (ABC, 'a-b-c'),
        (myOneAction, 'my-one'),
        (DoThisThing, 'do-this-thing'),
    ],
)
def test_action_class_name_to_action_name(cls: type[object], action_name: str):
    assert list(ops_tools.action_to_juju_schema(cls).keys()) == [action_name]


class BaseAction:
    """Base action."""

    x: int = 42
    """X-ray."""


class ChildAction(BaseAction):
    """Derived action."""

    y: str = 'foo'
    """Yellow."""


class GrandchildAction(ChildAction):
    """Grandchild action."""

    x: int = 24
    """Xylophone."""
    z: float = 3.14
    """Zebra."""


def test_action_inherited_classes():
    generated_schema = ops_tools.action_to_juju_schema(GrandchildAction)
    expected_schema = {
        'grandchild': {
            'description': 'Grandchild action.',
            'params': {
                'x': {'type': 'integer', 'default': 24, 'description': 'Xylophone.'},
                'y': {'type': 'string', 'default': 'foo', 'description': 'Yellow.'},
                'z': {'type': 'number', 'default': 3.14, 'description': 'Zebra.'},
            },
            'additionalProperties': False,
        },
    }
    assert generated_schema == expected_schema
