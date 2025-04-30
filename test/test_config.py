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
from typing import Any, Optional, Protocol, Union, cast

import pytest

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

import ops
import ops._private.yaml
from ops import testing

logger = logging.getLogger(__name__)

JUJU_TYPES = Union[bool, int, float, str]


class _ConfigProtocol(Protocol):
    my_bool: bool | None
    my_int: int
    my_float: float
    my_str: str
    my_secret: Optional[ops.Secret]


class MyConfig(ops.ConfigBase):
    my_bool: bool | None = None
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
    """A floating point value."""

    my_str: str = 'foo'
    """A string value."""

    my_secret: Optional[ops.Secret] = None  # 'Optional' and not '| None' to exercise that path.
    """A user secret."""

    def __init__(
        self,
        *,
        my_bool: JUJU_TYPES | None = None,
        my_int: JUJU_TYPES = 42,
        my_float: JUJU_TYPES = 3.14,
        my_str: JUJU_TYPES = 'foo',
        my_secret: ops.Secret | None = None,
    ):
        super().__init__()
        if my_bool is not None and not isinstance(my_bool, bool):
            raise ValueError('my_bool must be a Boolean')
        self.my_bool = my_bool
        if not isinstance(my_float, float):
            raise ValueError('my_float must be a float')
        self.my_float = my_float
        if not isinstance(my_int, int):
            raise ValueError('my_int must be an integer')
        if my_int < 0:
            raise ValueError('my_int must be zero or positive')
        self.my_int = my_int
        if not isinstance(my_str, str):
            raise ValueError('my_str must be a string')
        self.my_str = my_str
        if my_secret is not None:
            if not isinstance(my_secret, ops.Secret):
                raise ValueError('my_secret must be a secret')
            self.my_secret = my_secret


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.typed_config = self.load_config(MyConfig)
        # These should not have any type errors.
        new_float = self.typed_config.my_float + 2006.8
        new_int = self.typed_config.my_int + 1979
        new_str = self.typed_config.my_str + 'bar'
        if self.typed_config.my_secret is not None:
            label = self.typed_config.my_secret.label
        else:
            label = 'no secret'
        logger.info(f'{new_float=}, {new_int=}, {new_str=}, {label=}')


# Note that we would really like to have kw_only=True here as well, but that's
# not available in Python 3.8.
@dataclasses.dataclass(frozen=True)
class MyDataclassConfig(ops.ConfigBase):
    my_bool: bool | None = None
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
    """A floating point value."""

    my_str: str = 'foo'
    """A string value."""

    my_secret: Optional[ops.Secret] = None  # 'Optional' and not '| None' to exercise that path.
    """A user secret."""

    def __post_init__(self):
        if self.my_int < 0:
            raise ValueError('my_int must be zero or positive')


class MyDataclassCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        self.typed_config = self.load_config(MyDataclassConfig)
        # These should not have any type errors.
        new_float = self.typed_config.my_float + 2006.8
        new_int = self.typed_config.my_int + 1979
        new_str = self.typed_config.my_str + 'bar'
        if self.typed_config.my_secret is not None:
            label = self.typed_config.my_secret.label
        else:
            label = 'no secret'
        logger.info(f'{new_float=}, {new_int=}, {new_str=}, {label=}')


_test_classes: list[type[ops.CharmBase]] = [MyCharm, MyDataclassCharm]
_test_config_classes: list[type[ops.ConfigBase]] = [MyConfig, MyDataclassConfig]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True, config={'arbitrary_types_allowed': True})
    class MyPydanticDataclassConfig(ops.ConfigBase):
        my_bool: bool | None = pydantic.Field(None, description='A Boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_str: str = pydantic.Field('foo', description='A string value.')
        my_secret: Optional[ops.Secret] = pydantic.Field(None, description='A user secret.')

        @pydantic.field_validator('my_int')
        @classmethod
        def validate_my_int(cls, my_int: int) -> int:
            if my_int < 0:
                raise ValueError('my_int must be zero or positive')
            return my_int

    class MyPydanticDataclassCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(MyPydanticDataclassConfig)
            # These should not have any type errors.
            new_float = self.typed_config.my_float + 2006.8
            new_int = self.typed_config.my_int + 1979
            new_str = self.typed_config.my_str + 'bar'
            if self.typed_config.my_secret is not None:
                label = self.typed_config.my_secret.label
            else:
                label = 'no secret'
            logger.info(f'{new_float=}, {new_int=}, {new_str=}, {label=}')

    class MyPydanticBaseModelConfig(pydantic.BaseModel, ops.ConfigBase):
        my_bool: Optional[bool] = pydantic.Field(None, description='A Boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_str: str = pydantic.Field('foo', description='A string value.')
        my_secret: Optional[ops.Secret] = pydantic.Field(None, description='A user secret.')

        @pydantic.field_validator('my_int')
        @classmethod
        def validate_my_int(cls, my_int: int) -> int:
            if my_int < 0:
                raise ValueError('my_int must be zero or positive')
            return my_int

        class Config:
            arbitrary_types_allowed = True
            frozen = True

    class MyPydanticBaseModelCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(MyPydanticBaseModelConfig)
            # These should not have any type errors.
            new_float = self.typed_config.my_float + 2006.8
            new_int = self.typed_config.my_int + 1979
            new_str = self.typed_config.my_str + 'bar'
            if self.typed_config.my_secret is not None:
                label = self.typed_config.my_secret.label
            else:
                label = 'no secret'
            logger.info(f'{new_float=}, {new_int=}, {new_str=}, {label=}')

    _test_classes.extend((MyPydanticDataclassCharm, MyPydanticBaseModelCharm))
    _test_config_classes.extend((MyPydanticDataclassConfig, MyPydanticBaseModelConfig))


@pytest.mark.parametrize('charm_class', _test_classes)
def test_config_init(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    # We use the generated schema from the simple class for all variants,
    # because we expect it to be the same.
    config = MyConfig.to_juju_schema()
    harness = testing.Harness(charm_class, config=ops._private.yaml.safe_dump(config))
    request.addfinalizer(harness.cleanup)
    harness.begin()
    typed_config = harness.charm.typed_config  # type: ignore
    typed_config = cast(_ConfigProtocol, typed_config)
    assert typed_config.my_bool is None
    assert typed_config.my_float == 3.14
    assert isinstance(typed_config.my_float, float)
    assert typed_config.my_int == 42
    assert isinstance(typed_config.my_int, int)
    assert typed_config.my_str == 'foo'
    assert isinstance(typed_config.my_str, str)
    assert typed_config.my_secret is None


@pytest.mark.parametrize('charm_class', _test_classes)
def test_config_init_non_default(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    config = MyConfig.to_juju_schema()
    harness = testing.Harness(charm_class, config=ops._private.yaml.safe_dump(config))
    request.addfinalizer(harness.cleanup)
    harness.update_config({
        'my-bool': True,
        'my-float': 2.71,
        'my-int': 24,
        'my-str': 'bar',
    })
    harness.begin()
    typed_config = harness.charm.typed_config  # type: ignore
    typed_config = cast(_ConfigProtocol, typed_config)
    assert typed_config.my_bool is True
    assert typed_config.my_float == 2.71
    assert typed_config.my_int == 24
    assert typed_config.my_str == 'bar'
    assert typed_config.my_secret is None


@pytest.mark.parametrize('charm_class', _test_classes)
def test_config_with_error(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    config = MyConfig.to_juju_schema()
    harness = testing.Harness(charm_class, config=ops._private.yaml.safe_dump(config))
    request.addfinalizer(harness.cleanup)
    harness.update_config({
        'my-int': -1,
    })
    with pytest.raises(ops.InvalidSchemaError):
        harness.begin()
    # TODO: add a test_main check that makes sure that the status is set correctly.


@pytest.mark.parametrize('charm_class', _test_classes)
def test_config_with_secret(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    config = MyConfig.to_juju_schema()
    harness = testing.Harness(charm_class, config=ops._private.yaml.safe_dump(config))
    request.addfinalizer(harness.cleanup)
    content = {'password': 'admin'}
    secret_id = harness.add_user_secret(content)
    harness.grant_secret(secret_id, harness.model.app.name)
    harness.update_config({
        'my-secret': secret_id,
    })
    harness.begin()
    typed_config = harness.charm.typed_config  # type: ignore
    typed_config = cast(_ConfigProtocol, typed_config)
    secret = typed_config.my_secret
    assert secret is not None
    assert secret.id == secret_id
    assert secret.get_content() == content


def test_config_custom_naming_pattern(request: pytest.FixtureRequest):
    @dataclasses.dataclass(frozen=True)
    class Config(ops.ConfigBase):
        foo_bar: int = 42
        other: str = 'baz'

        @staticmethod
        def _attr_to_juju_name(name: str):
            if name == 'foo_bar':
                return 'fooBar'
            return name.replace('_', '-')

        @staticmethod
        def _juju_name_to_attr(name: str):
            if name == 'fooBar':
                return 'foo_bar'
            return name.replace('-', '_')

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(Config)

    config = Config.to_juju_schema()
    assert 'fooBar' in config['options']
    harness = testing.Harness(Charm, config=ops._private.yaml.safe_dump(config))
    request.addfinalizer(harness.cleanup)
    harness.begin()
    typed_config = harness.charm.typed_config
    assert typed_config.foo_bar == 42
    assert typed_config.other == 'baz'


def test_config_bad_attr_naming_pattern(request: pytest.FixtureRequest):
    @dataclasses.dataclass(frozen=True)
    class BadConfig(ops.ConfigBase):
        foo_bar: int = 42

        @staticmethod
        def _juju_name_to_attr(attr: str):
            return attr.replace('_', '-')

    class BadCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(BadConfig)

    config = BadConfig.to_juju_schema()
    assert 'foo-bar' in config['options']
    harness = testing.Harness(BadCharm, config=ops._private.yaml.safe_dump(config))
    request.addfinalizer(harness.cleanup)
    with pytest.raises(ops.InvalidSchemaError):
        harness.begin()


@pytest.mark.parametrize('config_class', _test_config_classes)
def test_config_yaml_schema(config_class: type[ops.ConfigBase]):
    generated_yaml = config_class.to_juju_schema()
    expected_yaml = {
        'options': {
            'my-bool': {
                'type': 'boolean',
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
        },
    }
    assert generated_yaml == expected_yaml


def test_config_extra_args(request: pytest.FixtureRequest):
    @dataclasses.dataclass
    class Config(ops.ConfigBase):
        a: int
        b: float
        c: str

        @classmethod
        def _juju_names(cls):
            yield 'b'

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(Config, 10, c='foo')

    schema = Config.to_juju_schema()
    options = ops._private.yaml.safe_dump(schema)
    harness = testing.Harness(Charm, config=options)
    request.addfinalizer(harness.cleanup)
    harness.update_config({'b': 3.14})
    harness.begin()
    typed_config = harness.charm.typed_config
    assert typed_config.a == 10
    assert typed_config.b == 3.14
    assert typed_config.c == 'foo'


def test_config_custom_type(request: pytest.FixtureRequest):
    class Config(ops.ConfigBase):
        x: int
        y: datetime.date

        def __init__(self, x: int, y: str):
            self.x = x
            year, month, day = y.split('-')
            self.y = datetime.date(int(year), int(month), int(day))

        @classmethod
        def _attr_to_juju_type(cls, attr: str, default: Any = None) -> str:
            if attr == 'y':
                return 'string'
            return super()._attr_to_juju_type(attr, default)

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(Config)

    schema = Config.to_juju_schema()
    options = ops._private.yaml.safe_dump(schema)
    harness = testing.Harness(Charm, config=options)
    request.addfinalizer(harness.cleanup)
    harness.update_config({'x': 42, 'y': '2008-08-28'})
    harness.begin()
    typed_config = harness.charm.typed_config
    assert typed_config.x == 42
    assert typed_config.y == datetime.date(2008, 8, 28)


def test_config_partial_init(request: pytest.FixtureRequest):
    @dataclasses.dataclass(frozen=True)
    class Config(ops.ConfigBase):
        x: int

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(Config)

    schema = Config.to_juju_schema()
    # Harness needs to know about *all* the options, even though the charm does
    # not.
    schema['options']['y'] = {
        'type': 'string',
        'description': 'An int not used in the class',
    }
    options = ops._private.yaml.safe_dump(schema)
    harness = testing.Harness(Charm, config=options)
    request.addfinalizer(harness.cleanup)
    # The raw config contains more fields than the class requires.
    harness.update_config({'x': 42, 'y': 'foo'})
    harness.begin()
    typed_config = harness.charm.typed_config
    assert typed_config.x == 42
