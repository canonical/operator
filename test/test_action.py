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

import ops
import ops._main
import ops._private.yaml
from ops import testing

logger = logging.getLogger(__name__)


class MyAction(ops.ActionBase):
    """An action description."""

    my_str: str
    """A string value."""

    my_bool: bool = False
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
    """A floating point value."""

    my_list: list[str] = []  # noqa: RUF012
    """A list value."""

    def __init__(
        self,
        *,
        my_str: Any,
        my_bool: Any = False,
        my_int: Any = 42,
        my_float: Any = 3.14,
        my_list: Any = None,
    ):
        super().__init__()
        if not isinstance(my_bool, bool):
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

    my_bool: bool = False
    """A Boolean value."""

    my_int: int = 42
    """A positive integer value."""

    my_float: float = 3.14
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


_test_classes: list[tuple[type[ops.CharmBase], str, type[ops.ActionBase]]] = [
    (MyCharm, 'my-action', MyAction),
    (MyDataclassCharm, 'my-dataclass-action', MyDataclassAction),
]
_test_action_classes: list[tuple[type[ops.ActionBase], str]] = [
    (MyAction, 'my-action'),
    (MyDataclassAction, 'my-dataclass-action'),
]

if pydantic:

    @pydantic.dataclasses.dataclass(frozen=True)
    class MyPydanticDataclassAction(ops.ActionBase):
        """An action description."""

        my_str: str = pydantic.Field(description='A string value.')
        my_bool: bool = pydantic.Field(False, description='A Boolean value.')
        my_int: int = pydantic.Field(42, description='A positive integer value.')
        my_float: float = pydantic.Field(3.14, description='A floating point value.')
        my_list: list[str] = pydantic.Field(default_factory=list, description='A list value.')

        @pydantic.field_validator('my_int')
        @classmethod
        def validate_my_int(cls, my_int: int) -> int:
            if my_int < 0:
                raise ValueError('my_int must be zero or positive')
            return my_int

    class MyPydanticDataclassCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['my-pydantic-dataclass-action'].action, self._on_action)

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

    class MyPydanticBaseModelAction(pydantic.BaseModel, ops.ActionBase):
        """An action description."""

        my_str: str = pydantic.Field(alias='my-str', description='A string value.')  # type: ignore
        my_bool: bool = pydantic.Field(
            False,
            alias='my-bool',  # type: ignore
            description='A Boolean value.',
        )
        my_int: int = pydantic.Field(42, alias='my-int', description='A positive integer value.')  # type: ignore
        my_float: float = pydantic.Field(
            3.14,
            alias='my-float',  # type: ignore
            description='A floating point value.',
        )
        my_list: list[str] = pydantic.Field(
            alias='my-list',  # type: ignore
            default_factory=list,
            description='A list value.',
        )

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
            framework.observe(self.on['my-pydantic-base-model-action'].action, self._on_action)

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

    _test_classes.extend((
        (MyPydanticDataclassCharm, 'my-pydantic-dataclass-action', MyPydanticDataclassAction),
        (MyPydanticBaseModelCharm, 'my-pydantic-base-model-action', MyPydanticBaseModelAction),
    ))
    _test_action_classes.extend((
        (MyPydanticDataclassAction, 'my-pydantic-dataclass-action'),
        (MyPydanticBaseModelAction, 'my-pydantic-base-model-action'),
    ))


@pytest.mark.parametrize('charm_class,action_name,action_class', _test_classes)
def test_action_init(
    charm_class: type[ops.CharmBase],
    action_name: str,
    action_class: type[ops.ActionBase],
    request: pytest.FixtureRequest,
):
    action_yaml = action_class.to_juju_schema()
    actions = ops._private.yaml.safe_dump(action_yaml)
    harness = testing.Harness(charm_class, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params_out = harness.run_action(action_name, {'my-str': 'foo'}).results['params']
    assert params_out.my_bool is False
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
    charm_class: type[ops.CharmBase],
    action_name: str,
    action_class: type[ops.ActionBase],
    request: pytest.FixtureRequest,
):
    action_yaml = action_class.to_juju_schema()
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
    charm_class: type[ops.CharmBase],
    action_name: str,
    action_class: type[ops.ActionBase],
    request: pytest.FixtureRequest,
):
    action_yaml = action_class.to_juju_schema()
    actions = ops._private.yaml.safe_dump(action_yaml)
    harness = testing.Harness(charm_class, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    with pytest.raises(ops.InvalidSchemaError):
        harness.run_action(action_name, params={'my-str': 'foo', 'my-int': -1})


def test_action_custom_naming_pattern(request: pytest.FixtureRequest):
    @dataclasses.dataclass(frozen=True)
    class Act1(ops.ActionBase):
        foo_bar: int = 42
        other: str = 'baz'

        @staticmethod
        def _attr_to_juju_name(attr: str):
            if attr == 'foo_bar':
                return 'fooBar'
            return attr.replace('_', '-')

        @staticmethod
        def _juju_name_to_attr(attr: str):
            if attr == 'fooBar':
                return 'foo_bar'
            return attr.replace('-', '_')

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['act1'].action, self._on_action)

        def _on_action(self, event: ops.ActionEvent):
            params = event.load_params(Act1)
            event.set_results({'params': params})

    action_yaml = Act1.to_juju_schema()
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

        @staticmethod
        def _juju_name_to_attr(attr: str):
            return attr.replace('_', '-')

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
            event.load_params(BadAction)
            assert True, 'The event handler should not continue'

    action_schema = BadAction.to_juju_schema()
    assert 'foo-bar' in action_schema['bad-action']['params']
    actions = ops._private.yaml.safe_dump(action_schema)
    harness = testing.Harness(BadCharm, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    with pytest.raises(ops.InvalidSchemaError):
        harness.run_action('bad-action')


@pytest.mark.parametrize('action_class,action_name', _test_action_classes)
def test_action_yaml_schema(action_class: type[ops.ActionBase], action_name: str):
    generated_yaml = action_class.to_juju_schema()
    if hasattr(action_class, 'schema'):
        # Remove the 'title' property that Pydantic adds to make the schema more
        # consistent with the others for simpler testing.
        for prop in generated_yaml[action_name]['params'].values():
            prop.pop('title', None)
        # Also adjust how `my-list` is specified.
        assert generated_yaml[action_name]['params']['my-list']['items'] == {'type': 'string'}
        del generated_yaml[action_name]['params']['my-list']['items']
        generated_yaml[action_name]['params']['my-list']['default'] = []
    expected_yaml: dict[str, Any] = {
        action_name: {
            'description': 'An action description.',
            'params': {
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

        x: int = 42

        @classmethod
        def to_juju_schema(cls):
            schema = super().to_juju_schema()
            schema['action-true']['additionalProperties'] = True
            return schema

    generated_yaml = ActionTrue.to_juju_schema()
    expected_yaml = {
        'action-true': {
            'description': 'An action.',
            'params': {'x': {'type': 'integer', 'default': 42}},
            'additionalProperties': True,
        },
    }
    assert generated_yaml == expected_yaml

    class ActionDefault(ops.ActionBase):
        """An action."""

        x: int = 42

        @classmethod
        def to_juju_schema(cls):
            schema = super().to_juju_schema()
            del schema['action-default']['additionalProperties']
            return schema

    generated_yaml = ActionDefault.to_juju_schema()
    expected_yaml = {
        'action-default': {
            'description': 'An action.',
            'params': {'x': {'type': 'integer', 'default': 42}},
        },
    }
    assert generated_yaml == expected_yaml


def test_action_subclass_modification():
    class ActionMinimum(ops.ActionBase):
        """An action."""

        x: int = 42

        @classmethod
        def to_juju_schema(cls):
            yaml = super().to_juju_schema()
            yaml['action-minimum']['params']['x']['minimum'] = 0
            return yaml

    generated_yaml = ActionMinimum.to_juju_schema()
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
    generated_yaml = Rebalance.to_juju_schema()
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
def test_action_class_name_to_action_name(cls: ops.ActionBase, action_name: str):
    assert cls._class_to_action_name() == action_name


def test_action_extra_args(request: pytest.FixtureRequest):
    @dataclasses.dataclass
    class Action(ops.ActionBase):
        a: int
        b: float
        c: str

        @classmethod
        def _param_names(cls):
            yield 'b'

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['action'].action, self._on_action)

        def _on_action(self, event: ops.ActionEvent):
            params = event.load_params(Action, 10, c='foo')
            event.set_results({'params': params})

    schema = Action.to_juju_schema()
    actions = ops._private.yaml.safe_dump(schema)
    harness = testing.Harness(Charm, actions=actions)
    request.addfinalizer(harness.cleanup)
    harness.begin()
    params = harness.run_action('action', {'b': 3.14}).results['params']
    assert params.a == 10
    assert params.b == 3.14
    assert params.c == 'foo'
