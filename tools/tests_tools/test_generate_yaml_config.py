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
import datetime
import logging

import pytest

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

import ops_tools

import ops

logger = logging.getLogger(__name__)


class MyConfig:
    basic_bool: bool
    basic_int: int
    basic_float: float
    basic_str: str

    my_bool: bool = False
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
    """A floating point value."""

    my_str: str = 'foo'
    """A string value."""

    my_secret: ops.Secret | None = None
    """A user secret."""

    my_date: datetime.date = datetime.date(2023, 9, 4)
    """A date value."""


@dataclasses.dataclass(frozen=True, kw_only=True)
class MyDataclassConfig:
    basic_bool: bool
    basic_int: int
    basic_float: float
    basic_str: str

    my_bool: bool = False
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
    """A floating point value."""

    my_str: str = 'foo'
    """A string value."""

    my_secret: ops.Secret | None = None
    """A user secret."""

    my_date: datetime.date = datetime.date(2023, 9, 4)
    """A date value."""


_test_config_classes: list[type[object]] = [MyConfig, MyDataclassConfig]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True, config={'arbitrary_types_allowed': True})
    class MyPydanticDataclassConfig:
        basic_bool: bool
        basic_int: int
        basic_float: float
        basic_str: str
        my_bool: bool = pydantic.Field(False, description='A Boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_str: str = pydantic.Field('foo', description='A string value.')
        my_secret: ops.Secret | None = pydantic.Field(None, description='A user secret.')
        my_date: datetime.date = pydantic.Field(
            datetime.date(2023, 9, 4), description='A date value.'
        )

    class MyPydanticBaseModelConfig(pydantic.BaseModel):
        basic_bool: bool
        basic_int: int
        basic_float: float
        basic_str: str
        my_bool: bool = pydantic.Field(False, description='A Boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_str: str = pydantic.Field('foo', description='A string value.')
        my_secret: ops.Secret | None = pydantic.Field(None, description='A user secret.')
        my_date: datetime.date = pydantic.Field(
            datetime.date(2023, 9, 4), description='A date value.'
        )

        class Config:
            arbitrary_types_allowed = True
            frozen = True

    _test_config_classes.extend((MyPydanticDataclassConfig, MyPydanticBaseModelConfig))


@pytest.mark.parametrize('config_class', _test_config_classes)
def test_config_yaml_schema(config_class: type[object]):
    generated_schema = ops_tools.config_to_juju_schema(config_class)
    expected_schema = {
        'options': {
            'basic-bool': {
                'type': 'boolean',
            },
            'basic-int': {
                'type': 'int',
            },
            'basic-float': {
                'type': 'float',
            },
            'basic-str': {
                'type': 'string',
            },
            'my-bool': {
                'type': 'boolean',
                'default': False,
                'description': 'A Boolean value.',
            },
            'my-float': {
                'type': 'float',
                'default': 3.14,
                'description': 'A floating point value.',
            },
            'my-int': {
                'type': 'int',
                'default': 42,
                'description': 'A positive integer value.',
            },
            'my-str': {
                'type': 'string',
                'default': 'foo',
                'description': 'A string value.',
            },
            'my-secret': {
                'type': 'secret',
                'description': 'A user secret.',
            },
            'my-date': {
                'default': '2023-09-04',
                'description': 'A date value.',
                'type': 'string',
            },
        },
    }
    assert generated_schema == expected_schema


@pytest.mark.parametrize('config_class', _test_config_classes)
def test_config_custom_type(config_class: type[object]):
    class Config(config_class):
        @classmethod
        def to_juju_schema(
            cls, schema: dict[str, ops_tools.OptionDict]
        ) -> dict[str, ops_tools.OptionDict]:
            # Override the custom type.
            assert schema['my-date'] == {
                'type': 'string',
                'default': '2023-09-04',
                'description': 'A date value.',
            }
            schema['my-date']['type'] = 'int'
            schema['my-date']['default'] = 20230904
            return schema

    generated_schema = ops_tools.config_to_juju_schema(Config)
    expected_schema = {
        'options': {
            'basic-bool': {
                'type': 'boolean',
            },
            'basic-int': {
                'type': 'int',
            },
            'basic-float': {
                'type': 'float',
            },
            'basic-str': {
                'type': 'string',
            },
            'my-bool': {
                'type': 'boolean',
                'default': False,
                'description': 'A Boolean value.',
            },
            'my-float': {
                'type': 'float',
                'default': 3.14,
                'description': 'A floating point value.',
            },
            'my-int': {
                'type': 'int',
                'default': 42,
                'description': 'A positive integer value.',
            },
            'my-str': {
                'type': 'string',
                'default': 'foo',
                'description': 'A string value.',
            },
            'my-secret': {
                'type': 'secret',
                'description': 'A user secret.',
            },
            'my-date': {
                'type': 'int',
                'default': 20230904,
                'description': 'A date value.',
            },
        },
    }
    assert generated_schema == expected_schema
