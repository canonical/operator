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
from typing import Any, Optional, Union

import pytest

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

import ops
import ops._main
import ops._private.yaml
from ops import testing

logger = logging.getLogger(__name__)


class MyAction(ops.ActionBase):
    """An action description."""

    my_str: str
    """A string value."""

    my_bool: bool | None = None
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: Optional[float] = 3.14  # 'Optional' and not '| None' to exercise that path.
    """A floating point value."""

    my_list: list[str] = []  # noqa: RUF012
    """A list value."""

    def __init__(
        self,
        *,
        my_str: Any,
        my_bool: Any | None = None,
        my_int: Any = 42,
        my_float: Any | None = 3.14,
        my_list: Any = None,
    ):
        super().__init__()
        if my_bool is not None and not isinstance(my_bool, bool):
            raise ValueError('my_bool must be a boolean')
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
        if my_list is None:
            self.my_list = []
        else:
            self.my_list = my_list


class MyCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['my-action'].action, self._on_action)

    def _on_action(self, event: ops.ActionEvent):
        params = event.load_params(MyAction)
        # These should not have any type errors.
        assert params.my_float is not None
        new_float = params.my_float + 2006.8
        new_int = params.my_int + 1979
        new_str = params.my_str + 'bar'
        new_list = params.my_list[:]
        logger.info(f'{new_float=}, {new_int=}, {new_str=}, {new_list=}')
        event.set_results({'params': params})


# Note that we would really like to have kw_only=True here as well, but that's
# not available in Python 3.8.
@dataclasses.dataclass(frozen=True)
class MyDataclassAction(ops.ActionBase):
    """An action description."""

    my_str: str
    """A string value."""

    my_bool: bool | None = None
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: Optional[float] = 3.14  # 'Optional' and not '| None' to exercise that path.
    """A floating point value."""

    my_list: list[str] = dataclasses.field(default_factory=list)
    """A list value."""

    def __post_init__(self):
        if self.my_int < 0:
            raise ValueError('my_int must be zero or positive')


class MyDataclassCharm(ops.CharmBase):
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['my-dataclass-action'].action, self._on_action)

    def _on_action(self, event: ops.ActionEvent):
        params = event.load_params(MyDataclassAction)
        # These should not have any type errors.
        assert params.my_float is not None
        new_float = params.my_float + 2006.8
        new_int = params.my_int + 1979
        new_str = params.my_str + 'bar'
        new_list = params.my_list[:]
        logger.info(f'{new_float=}, {new_int=}, {new_str=}, {new_list=}')
        event.set_results({'params': params})


_test_classes = [
    (MyCharm, 'my-action', MyAction),
    (MyDataclassCharm, 'my-dataclass-action', MyDataclassAction),
]
_test_class_types = Union[type[MyCharm], type[MyDataclassCharm]]
_test_action_classes = [(MyAction, 'my-action'), (MyDataclassAction, 'my-dataclass-action')]
_test_action_classes_types = Union[type[MyAction], type[MyDataclassAction]]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True, config={'arbitrary_types_allowed': True})
    class MyPydanticDataclassConfig(ops.ConfigBase):
        my_bool: bool | None = pydantic.Field(None, description='A boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_str: str = pydantic.Field('foo', description='A string value.')

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
            logger.info(f'{new_float=}, {new_int=}, {new_str=}')

    class MyPydanticBaseModelConfig(pydantic.BaseModel, ops.ConfigBase):
        my_bool: Optional[bool] = pydantic.Field(None, description='A boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_str: str = pydantic.Field('foo', description='A string value.')

        @pydantic.field_validator('my_int')
        @classmethod
        def validate_my_int(cls, my_int: int) -> int:
            if my_int < 0:
                raise ValueError('my_int must be zero or positive')
            return my_int

        class Config:
            frozen = True

    class MyPydanticBaseModelCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            self.typed_config = self.load_config(MyPydanticBaseModelConfig)
            # These should not have any type errors.
            new_float = self.typed_config.my_float + 2006.8
            new_int = self.typed_config.my_int + 1979
            new_str = self.typed_config.my_str + 'bar'
            logger.info(f'{new_float=}, {new_int=}, {new_str=}')

    _test_classes.extend((MyPydanticDataclassCharm, MyPydanticBaseModelCharm))
    _test_class_types = Union[
        _test_class_types, type[MyPydanticDataclassCharm], type[MyPydanticBaseModelCharm]
    ]
    _test_action_classes.extend((MyPydanticDataclassConfig, MyPydanticBaseModelConfig))
    _test_action_classes_types = Union[
        _test_action_classes_types,
        type[MyPydanticDataclassConfig],
        type[MyPydanticBaseModelConfig],
    ]


@pytest.mark.parametrize('charm_class,action_name,action_class', _test_classes)
def test_action_init(
    charm_class: _test_class_types,
    action_name: str,
    action_class: _test_action_classes,
    request: pytest.FixtureRequest,
):
    action_yaml = action_class.to_yaml_schema()
    actions = ops._private.yaml.safe_dump(action_yaml)
    harness = testing.Harness(charm_class, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params_out = harness.run_action(action_name, {'my-str': 'foo'}).results['params']
    assert params_out.my_bool is None
    assert params_out.my_float == 3.14
    assert isinstance(params_out.my_float, float)
    assert params_out.my_int == 42
    assert isinstance(params_out.my_int, int)
    assert params_out.my_str == 'foo'
    assert isinstance(params_out.my_str, str)
    assert params_out.my_list == []
    assert isinstance(params_out.my_list, list)


@pytest.mark.parametrize('charm_class,action_name,action_class', _test_classes)
def test_action_init_non_default(
    charm_class: _test_class_types,
    action_name: str,
    action_class: _test_action_classes,
    request: pytest.FixtureRequest,
):
    action_yaml = action_class.to_yaml_schema()
    actions = ops._private.yaml.safe_dump(action_yaml)
    harness = testing.Harness(charm_class, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params_in = {
        'my-bool': True,
        'my-float': 2.71,
        'my-int': 24,
        'my-str': 'bar',
        'my-list': ['a', 'b', 'c'],
    }
    params_out = harness.run_action(action_name, params_in).results['params']
    assert params_out.my_bool is True
    assert params_out.my_float == 2.71
    assert params_out.my_int == 24
    assert params_out.my_str == 'bar'
    assert params_out.my_list == ['a', 'b', 'c']


@pytest.mark.parametrize('charm_class,action_name,action_class', _test_classes)
def test_action_with_error(
    charm_class: _test_class_types,
    action_name: str,
    action_class: _test_action_classes,
    request: pytest.FixtureRequest,
):
    action_yaml = action_class.to_yaml_schema()
    actions = ops._private.yaml.safe_dump(action_yaml)
    harness = testing.Harness(charm_class, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    with pytest.raises(ops._main._Abort) as cm:
        harness.run_action(action_name, params={'my-str': 'foo', 'my-int': -1})
    assert cm.value.exit_code == 0
    assert 'my_int must be zero or positive' in harness._backend._running_action.failure_message


def test_action_custom_naming_pattern(request: pytest.FixtureRequest):
    @dataclasses.dataclass(frozen=True)
    class Act1(ops.ActionBase):
        foo_bar: int = 42
        other: str = 'baz'

        @staticmethod
        def attr_name_to_yaml_name(name: str):
            if name == 'foo_bar':
                return 'fooBar'
            return name.replace('_', '-')

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['act1'].action, self._on_action)

        def _on_action(self, event: ops.ActionEvent):
            params = event.load_params(Act1, convert_name=self.yaml_name_to_attr_name)
            event.set_results({'params': params})

        @staticmethod
        def yaml_name_to_attr_name(name: str):
            if name == 'fooBar':
                return 'foo_bar'
            return name.replace('-', '_')

    action_yaml = Act1.to_yaml_schema()
    assert 'fooBar' in action_yaml['act1']['params']
    actions = ops._private.yaml.safe_dump(action_yaml)
    harness = testing.Harness(Charm, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params_out = harness.run_action('act1', {}).results['params']
    assert params_out.foo_bar == 42
    assert params_out.other == 'baz'


def test_action_bad_attr_naming_pattern(request: pytest.FixtureRequest):
    @dataclasses.dataclass(frozen=True)
    class BadAction(ops.ActionBase):
        foo_bar: int = 42

    class BadCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['bad-action'].action, self._on_action)

        def _on_action(self, event: ops.ActionEvent):
            params = {}
            action_meta = self.meta.actions['bad-action']
            for name, meta in action_meta.parameters.items():
                if 'default' in meta:
                    params[name] = meta['default']
            event.load_params(BadAction, convert_name=lambda x: x.replace('_', '-'))
            assert True, 'The event handler should not continue'

    action_schema = BadAction.to_yaml_schema()
    assert 'foo-bar' in action_schema['bad-action']['params']
    actions = ops._private.yaml.safe_dump(action_schema)
    harness = testing.Harness(BadCharm, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    with pytest.raises(ops._main._Abort) as cm:
        harness.run_action('bad-action')
    assert cm.value.exit_code == 0
    assert 'foo-bar' in harness._backend._running_action.failure_message


@pytest.mark.parametrize('action_class,action_name', _test_action_classes)
def test_action_yaml_schema(action_class: _test_action_classes_types, action_name: str):
    generated_yaml = action_class.to_yaml_schema()
    expected_yaml = {
        action_name: {
            'description': 'An action description.',
            'params': {
                'my-bool': {
                    'type': 'boolean',
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
                    'description': 'A string value.',
                },
                'my-list': {
                    'type': 'array',
                    'default': [],
                    'description': 'A list value.',
                },
            },
            'required': ['my-str'],
            'additionalProperties': False,
        },
    }
    assert generated_yaml == expected_yaml


def test_action_yaml_additional_properties():
    class ActionTrue(ops.ActionBase):
        """An action."""

        _additional_properties = True
        x: int = 42

    generated_yaml = ActionTrue.to_yaml_schema()
    expected_yaml = {
        'action-true': {
            'description': 'An action.',
            'params': {'x': {'type': 'integer', 'default': 42}},
            'additionalProperties': True,
        },
    }
    assert generated_yaml == expected_yaml

    class ActionFalse(ops.ActionBase):
        """An action."""

        _additional_properties = False
        x: int = 42

    generated_yaml = ActionFalse.to_yaml_schema()
    expected_yaml = {
        'action-false': {
            'description': 'An action.',
            'params': {'x': {'type': 'integer', 'default': 42}},
            'additionalProperties': False,
        },
    }
    assert generated_yaml == expected_yaml


def test_action_subclass_modification():
    class ActionMinimum(ops.ActionBase):
        """An action."""

        x: int = 42

        @classmethod
        def to_yaml_schema(cls):
            yaml = super().to_yaml_schema()
            yaml['action-minimum']['params']['x']['minimum'] = 0
            return yaml

    generated_yaml = ActionMinimum.to_yaml_schema()
    expected_yaml = {
        'action-minimum': {
            'description': 'An action.',
            'additionalProperties': False,
            'params': {'x': {'type': 'integer', 'default': 42, 'minimum': 0}},
        },
    }
    assert generated_yaml == expected_yaml


# The code can only find this if it's at the module level.
class Mode(enum.Enum):
    FULL = 'full'
    ADD = 'add'
    REMOVE = 'remove'


# To find the docstring the class needs to be at the module level.
class Rebalance(ops.ActionBase):
    """Trigger a rebalance of cluster partitions based on configured goals"""

    mode: Mode
    """The operation to issue to the balancer."""


def test_action_enum():
    generated_yaml = Rebalance.to_yaml_schema()
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


class action(ops.ActionBase): ...  # noqa: N801


class Action(ops.ActionBase): ...


class AcTioN(ops.ActionBase): ...


class TheAction(ops.ActionBase): ...


class MYAction(ops.ActionBase): ...


class ABC(ops.ActionBase): ...


class myAction(ops.ActionBase): ...  # noqa: N801


class DoThisThing(ops.ActionBase): ...


@pytest.mark.parametrize(
    'cls,action_name',
    [
        (action, 'action'),
        (Action, 'action'),
        (AcTioN, 'ac-tio-n'),
        (TheAction, 'the-action'),
        (MYAction, 'm-y-action'),
        (ABC, 'a-b-c'),
        (myAction, 'my-action'),
        (DoThisThing, 'do-this-thing'),
    ],
)
def test_class_name_to_action_name(cls: ops.ActionBase, action_name: str):
    assert cls.class_name_to_action_name() == action_name


# TODO:
# Tests for passing in additional args/kwargs.
# Tests for custom types.
