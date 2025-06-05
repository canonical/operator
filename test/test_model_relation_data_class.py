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
import functools
import json
from typing import Any, Callable, Protocol, cast

import pytest

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

import ops
from ops import testing
from ops._main import _Abort


@dataclasses.dataclass
class Nested:
    sub: int = 28


class DatabagProtocol(Protocol):
    foo: str
    baz: list[str] | None
    bar: int
    quux: Nested | None


class MyDatabag:
    def __init__(
        self, foo: str, baz: list[str] | None = None, bar: int = 0, quux: Nested | None = None
    ):
        assert isinstance(foo, str)
        self.foo = foo
        if isinstance(baz, list):
            assert all(isinstance(i, str) for i in baz)
            self.baz = baz
        else:
            assert baz is None
            self.baz = []
        if not isinstance(bar, int) or bar < 0:
            raise ValueError('bar must be a zero or positive int')
        self.bar = bar
        if quux is None:
            self.quux = Nested()
        else:
            self.quux = quux

    def __setattr__(self, key: str, value: Any):
        if key == 'bar' and (not isinstance(value, int) or value < 0):
            raise ValueError('bar must be a zero or positive int')
        super().__setattr__(key, value)


class BaseTestCharm(ops.CharmBase):
    @property
    def databag_class(self) -> type[object]:
        raise NotImplementedError('databag_class must be set in the subclass')

    @property
    def encoder(self) -> Callable[..., Any] | None:
        return None

    @property
    def decoder(self) -> Callable[..., Any] | None:
        return None


class NestedEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Nested):
            return {'sub': obj.sub}
        return super().default(obj)


def json_nested_hook(dct: dict[str, Any]) -> Nested | dict[str, Any]:
    if 'sub' in dct:
        return Nested(dct['sub'])
    return dct


nested_encode = functools.partial(json.dumps, cls=NestedEncoder)
nested_decode = functools.partial(json.loads, object_hook=json_nested_hook)


class MyCharm(BaseTestCharm):
    @property
    def databag_class(self) -> type[object]:
        return MyDatabag

    @property
    def encoder(self) -> Callable[..., Any] | None:
        return nested_encode

    @property
    def decoder(self) -> Callable[..., Any] | None:
        return nested_decode


@dataclasses.dataclass
class MyDataclassDatabag:
    foo: str
    baz: list[str] = dataclasses.field(default_factory=list)  # type: ignore
    bar: int = dataclasses.field(default=0)
    quux: Nested = dataclasses.field(default_factory=Nested)

    def __post_init__(self):
        assert isinstance(self.foo, str)
        assert isinstance(self.baz, list)
        assert all(isinstance(i, str) for i in self.baz)
        assert isinstance(self.bar, int)
        if self.bar < 0:
            raise ValueError('bar must be a zero or positive int')

    def __setattr__(self, key: str, value: Any):
        if key == 'bar' and (not isinstance(value, int) or value < 0):
            raise ValueError('bar must be a zero or positive int')
        super().__setattr__(key, value)


class MyDataclassCharm(BaseTestCharm):
    @property
    def databag_class(self) -> type[object]:
        return MyDataclassDatabag


_test_classes: list[type[ops.CharmBase]] = [MyCharm, MyDataclassCharm]

if pydantic:

    @pydantic.dataclasses.dataclass
    class MyPydanticDataclassDatabag:
        foo: str
        baz: list[str] = pydantic.Field(default_factory=list)
        bar: int = pydantic.Field(default=0, ge=0)
        quux: Nested = pydantic.Field(default_factory=Nested)

        class Config:
            validate_assignment = True

    class MyPydanticDataclassCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[object]:
            return MyPydanticDataclassDatabag

    class MyPydanticDatabag(pydantic.BaseModel):
        foo: str
        baz: list[str] = pydantic.Field(default_factory=list)
        bar: int = pydantic.Field(default=0, ge=0)
        quux: Nested = pydantic.Field(default_factory=Nested)

        class Config:
            validate_assignment = True

    class MyPydanticBaseModelCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[object]:
            return MyPydanticDatabag

    _test_classes.extend((MyPydanticDataclassCharm, MyPydanticBaseModelCharm))


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_simple(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = event.relation.load(self.databag_class, event.app, decoder=self.decoder)
            data = cast('DatabagProtocol', data)
            self.newfoo = len(data.foo)
            assert data.baz is not None
            self.newbaz = [*data.baz, 'new']
            self.newbar = data.bar + 1
            assert data.quux is not None
            self.newquux = Nested(sub=data.quux.sub + 1)
            self.data = data

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel = testing.Relation('db', remote_app_data=data)
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        obj = mgr.charm.data
    assert obj.foo == 'value'
    assert obj.bar == 1
    assert obj.baz == ['a', 'b']
    assert obj.quux.sub == 28


@pytest.mark.parametrize(
    'errors,raised', [('raise', ValueError), ('blocked', _Abort), (None, ValueError)]
)
@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_fail(
    errors: str | None, raised: type[Exception], charm_class: type[BaseTestCharm]
):
    class Charm(charm_class):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            kwargs = {'decoder': self.decoder}
            if errors is not None:
                kwargs['errors'] = errors
            event.relation.load(self.databag_class, event.app, **kwargs)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    # 'bar' should be an int, not a string.
    data = {'foo': json.dumps('value'), 'bar': json.dumps('bar'), 'baz': json.dumps(['a', 'b'])}
    rel = testing.Relation('db', remote_app_data=data)
    state_in = testing.State(leader=True, relations={rel})
    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.relation_changed(rel), state_in)
    assert isinstance(exc_info.value.__cause__, raised)


class _Alias:  # noqa: B903
    def __init__(self, fooBar: int = 42, other: str = 'baz'):  # noqa: N803
        self.foo_bar = fooBar
        self.other = other


@dataclasses.dataclass()
class _DataclassesAlias:
    foo_bar: int = dataclasses.field(default=42, metadata={'alias': 'fooBar'})
    other: str = 'baz'


_alias_data_classes: list[type[object]] = [_Alias, _DataclassesAlias]

if pydantic is not None:

    @pydantic.dataclasses.dataclass(init=False)
    class _PydanticDataclassesAlias:
        foo_bar: int = dataclasses.field(default=42, metadata={'alias': 'fooBar'})
        other: str = pydantic.Field(default='baz')

    class _PydanticBaseModelAlias(pydantic.BaseModel):
        foo_bar: int = pydantic.Field(42, alias='fooBar')
        other: str = pydantic.Field('baz')

    _alias_data_classes.extend([_PydanticDataclassesAlias, _PydanticBaseModelAlias])


@pytest.mark.parametrize('relation_data', [{}, {'fooBar': '24'}])
@pytest.mark.parametrize('data_class', _alias_data_classes)
def test_relation_load_custom_naming_pattern(
    relation_data: dict[str, str], data_class: type[object]
):
    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(data_class, event.app)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data=relation_data)
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        obj = mgr.charm.data
    assert obj.foo_bar == json.loads(relation_data.get('fooBar', '42'))
    assert obj.other == 'baz'


def test_relation_load_extra_args():
    @dataclasses.dataclass
    class Data:
        a: int
        b: float
        c: str

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(Data, event.app, 10, c='foo')

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data={'b': '3.14'})
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        obj = mgr.charm.data
    assert isinstance(obj, Data)
    assert obj.a == 10
    assert obj.b == 3.14
    assert obj.c == 'foo'


def test_relation_load_dash_to_underscore():
    @dataclasses.dataclass
    class Data:
        a_b: int

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(Data, event.app)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data={'a-b': '3.14'})
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        obj = mgr.charm.data
    assert isinstance(obj, Data)
    assert obj.a_b == 3.14


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_simple(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            event.relation.save(self.data, self.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db')
    state_in = testing.State(leader=True, relations={rel_in})
    with ctx(ctx.on.relation_changed(rel_in), state_in) as mgr:
        data_class = mgr.charm.databag_class
        mgr.charm.data = data_class(foo='other-value', bar=28, baz=['x', 'y'], quux=Nested(sub=8))
        state_out = mgr.run()
    rel_out = state_out.get_relation(rel_in.id)
    assert rel_out.local_app_data == {
        'foo': json.dumps('other-value'),
        'bar': json.dumps(28),
        'baz': json.dumps(['x', 'y']),
        'quux': json.dumps({'sub': 8}),
    }


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_no_access(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            event.relation.save(self.data, event.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db')
    state_in = testing.State(leader=True, relations={rel_in})
    with ctx(ctx.on.relation_changed(rel_in), state_in) as mgr:
        data_class = mgr.charm.databag_class
        mgr.charm.data = data_class(foo='value', bar=1, baz=['a', 'b'])
        with pytest.raises(ops.RelationDataAccessError):
            mgr.run()


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_then_save(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(self.databag_class, self.app)
            self.data = cast('DatabagProtocol', self.data)
            self.data.foo = self.data.foo + '1'
            self.data.bar = self.data.bar + 1
            self.data.baz.append('new')
            if self.data.quux is not None:
                self.data.quux.sub += 1
            event.relation.save(self.data, self.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel_in = testing.Relation('db', local_app_data=data)
    state_in = testing.State(leader=True, relations={rel_in})
    with ctx(ctx.on.relation_changed(rel_in), state_in) as mgr:
        data_class = mgr.charm.databag_class
        mgr.charm.data = data_class(foo='value', bar=1, baz=['a', 'b'])
        state_out = mgr.run()
    rel_out = state_out.get_relation(rel_in.id)
    assert rel_out.local_app_data == {
        'foo': json.dumps('value1'),
        'bar': json.dumps(2),
        'baz': json.dumps(['a', 'b', 'new']),
        'quux': json.dumps({'sub': 29}),
    }


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_invalid(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            def encoder(_: Any) -> int:
                # This is invalid: Juju only accepts strings.
                return 0

            data = self.databag_class(foo='value')
            event.relation.save(data, self.app, encoder=encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db')
    state_in = testing.State(leader=True, relations={rel_in})
    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.relation_changed(rel_in), state_in)
    assert isinstance(exc_info.value.__cause__, ops.RelationDataTypeError)


class _OneString:  # noqa: B903
    def __init__(self, foo: str):
        self.foo = foo


@dataclasses.dataclass()
class _DataclassesOneString:
    foo: str


_one_string_data_classes: list[type[object]] = [_OneString, _DataclassesOneString]

if pydantic is not None:

    @pydantic.dataclasses.dataclass()
    class _PydanticDataclassesOneString:
        foo: str

    class _PydanticBaseModelOneString(pydantic.BaseModel):
        foo: str = pydantic.Field()

    _one_string_data_classes.extend([_PydanticDataclassesOneString, _PydanticBaseModelOneString])


@pytest.mark.parametrize('data_class', _one_string_data_classes)
def test_relation_save_no_encode(data_class: type[BaseTestCharm]):
    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = event.relation.load(data_class, self.app, decoder=lambda x: x)
            data = cast('DatabagProtocol', data)
            data.foo = data.foo + '1'
            event.relation.save(data, self.app, encoder=lambda x: x)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db', local_app_data={'foo': 'value'})
    state_in = testing.State(leader=True, relations={rel_in})
    state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)
    rel_out = state_out.get_relation(rel_in.id)
    assert rel_out.local_app_data['foo'] == 'value1'


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_custom_encode(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        @staticmethod
        def custom_encode(data: Any) -> Any:
            if hasattr(data, 'upper'):
                return data.upper()
            return str(data)

        @staticmethod
        def custom_decode(data: Any) -> Any:
            if hasattr(data, '__getitem__'):
                return data[::-1]
            return data

        @property
        def encoder(self) -> Callable[..., Any] | None:
            return self.custom_encode

        @property
        def decoder(self) -> Callable[..., Any] | None:
            return self.custom_decode

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = event.relation.load(self.databag_class, self.app, decoder=self.decoder)
            data = cast('DatabagProtocol', data)
            data.foo = data.foo + '1'
            event.relation.save(data, self.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db', local_app_data={'foo': 'value'})
    state_in = testing.State(leader=True, relations={rel_in})
    state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)
    rel_out = state_out.get_relation(rel_in.id)
    assert rel_out.local_app_data['foo'] == 'EULAV1'


# TODO: pydantic model with pydantic types that need to serialise down to a string
# TODO: add a test that has the common Pydantic types: AnyHttpUrl or HttpUrl,
# IPvAnyAddress (ipaddress.IPv4Address|ipaddress.IPv6Address) for non-Pydantic, IPvAnyNetwork.
# TODO: add a test that uses enums.
# TODO: add a test that validates a combination of fields.
# TODO: add in support for Scenario automatically JSON'ing the relation content.
