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

import collections.abc
import dataclasses
import enum
import functools
import ipaddress
import json
import sys
import typing
import urllib.parse
from collections.abc import Callable, Iterable
from typing import TYPE_CHECKING, Any, Protocol, cast

import pytest

if TYPE_CHECKING:
    # Used only by test_relation_load_falls_back_when_type_hints_unresolvable,
    # which needs an annotation naming a type that is never actually imported
    # at runtime.
    import decimal

try:
    import pydantic
    import pydantic.dataclasses
except ImportError:
    pydantic = None

try:
    from pydantic.experimental.missing_sentinel import MISSING
except ImportError:
    MISSING = None  # type: ignore

import ops
from ops import testing


@dataclasses.dataclass
class Nested:
    sub: int = 28


class _Colour(enum.Enum):
    RED = 'red'
    BLUE = 'blue'


class DatabagProtocol(Protocol):
    foo: str
    bar: int
    baz: list[str]
    quux: Nested

    def __init__(
        self,
        *,
        foo: str,
        bar: int = 0,
        baz: list[str] = [],  # ruff: ignore[mutable-argument-default]
        quux: Nested = Nested(),  # ruff: ignore[function-call-in-default-argument]
    ): ...


class MyDatabag:
    foo: str
    bar: int
    baz: list[str]
    quux: Nested

    def __init__(
        self, foo: str, bar: int = 0, baz: list[str] | None = None, quux: Nested | None = None
    ):
        assert isinstance(foo, str)
        self.foo = foo
        if not isinstance(bar, int) or bar < 0:
            raise ValueError('bar must be a zero or positive int')
        self.bar = bar
        if isinstance(baz, list):
            assert all(isinstance(i, str) for i in baz)
            self.baz = baz
        else:
            assert baz is None
            self.baz = []
        if quux is None:
            self.quux = Nested()
        else:
            self.quux = quux
        if self.foo in self.baz:
            raise ValueError('foo cannot be in baz')

    def __setattr__(self, key: str, value: Any):
        if key == 'bar' and (not isinstance(value, int) or value < 0):
            raise ValueError('bar must be a zero or positive int')
        super().__setattr__(key, value)


class BaseTestCharm(ops.CharmBase):
    encoder: Callable[[Any], str] | None = None
    decoder: Callable[[str], Any] | None = None

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

    def _on_relation_changed(self, _: ops.RelationChangedEvent) -> None:
        raise NotImplementedError('databag class must implement this')

    @property
    def databag_class(self) -> type[DatabagProtocol]:
        raise NotImplementedError('databag_class must be set in the subclass')


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
    encoder = staticmethod(nested_encode)
    decoder = staticmethod(nested_decode)

    @property
    def databag_class(self) -> type[DatabagProtocol]:
        return MyDatabag


@dataclasses.dataclass
class MyDataclassDatabag:
    foo: str
    bar: int = dataclasses.field(default=0)
    baz: list[str] = dataclasses.field(default_factory=list[str])
    quux: Nested = dataclasses.field(default_factory=Nested)

    def __post_init__(self):
        assert isinstance(self.foo, str)
        assert isinstance(self.bar, int)
        if self.bar < 0:
            raise ValueError('bar must be a zero or positive int')
        assert isinstance(self.baz, list)
        assert all(isinstance(i, str) for i in self.baz)
        if self.foo in self.baz:
            raise ValueError('foo cannot be in baz')

    def __setattr__(self, key: str, value: Any):
        if key == 'bar' and (not isinstance(value, int) or value < 0):
            raise ValueError('bar must be a zero or positive int')
        super().__setattr__(key, value)


class MyDataclassCharm(BaseTestCharm):
    @property
    def databag_class(self) -> type[DatabagProtocol]:
        return MyDataclassDatabag


_test_classes: list[type[ops.CharmBase]] = [MyCharm, MyDataclassCharm]

if pydantic:
    assert pydantic is not None

    @pydantic.dataclasses.dataclass
    class MyPydanticDataclassDatabag:
        foo: str
        bar: int = pydantic.Field(default=0, ge=0)
        baz: list[str] = pydantic.Field(default_factory=list)
        quux: Nested = pydantic.Field(default_factory=Nested)

        @pydantic.field_validator('baz')
        @classmethod
        def check_foo_not_in_baz(cls, baz: list[str], values: Any):
            data = cast('dict[str, Any]', values.data)
            foo = data.get('foo')
            if foo in baz:
                raise ValueError('foo cannot be in baz')
            return baz

        model_config = pydantic.ConfigDict(validate_assignment=True)

    class MyPydanticDataclassCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[DatabagProtocol]:
            return MyPydanticDataclassDatabag

    class MyPydanticDatabag(pydantic.BaseModel):
        foo: str
        bar: int = pydantic.Field(default=0, ge=0)
        baz: list[str] = pydantic.Field(default_factory=list)
        quux: Nested = pydantic.Field(default_factory=Nested)

        @pydantic.field_validator('baz')
        @classmethod
        def check_foo_not_in_baz(cls, baz: list[str], values: Any):
            data = cast('dict[str, Any]', values.data)
            foo = data.get('foo')
            if foo in baz:
                raise ValueError('foo cannot be in baz')
            return baz

        model_config = pydantic.ConfigDict(validate_assignment=True)

    class MyPydanticBaseModelCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[DatabagProtocol]:
            return MyPydanticDatabag

    _test_classes.extend((MyPydanticDataclassCharm, MyPydanticBaseModelCharm))


if pydantic and MISSING is not None:

    class MissingPydanticDatabag(pydantic.BaseModel):
        foo: str
        bar: int = pydantic.Field(default=0, ge=0)
        baz: list[str] = pydantic.Field(default_factory=list)
        quux: Nested = pydantic.Field(default_factory=Nested)
        miss: str | MISSING = MISSING  # type: ignore

        @pydantic.field_validator('baz')
        @classmethod
        def check_foo_not_in_baz(cls, baz: list[str], values: Any):
            data = cast('dict[str, Any]', values.data)
            foo = data.get('foo')
            if foo in baz:
                raise ValueError('foo cannot be in baz')
            return baz

        model_config = pydantic.ConfigDict(validate_assignment=True)

    class MissingPydanticBaseModelCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[DatabagProtocol]:
            return MissingPydanticDatabag

    _test_classes.append(MissingPydanticBaseModelCharm)


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_simple(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = event.relation.load(self.databag_class, event.app, decoder=self.decoder)
            self.newfoo = len(data.foo)
            self.newbar = data.bar + 1
            assert data.baz is not None
            self.newbaz = [*data.baz, 'new']
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
    assert obj.quux is not None and obj.quux.sub == 28


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_fail(charm_class: type[BaseTestCharm], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            event.relation.load(self.databag_class, event.app, decoder=self.decoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    # 'bar' should be an int, not a string.
    data = {'foo': json.dumps('value'), 'bar': json.dumps('bar'), 'baz': json.dumps(['a', 'b'])}
    rel = testing.Relation('db', remote_app_data=data)
    state_in = testing.State(leader=True, relations={rel})
    with pytest.raises(ValueError):
        ctx.run(ctx.on.relation_changed(rel), state_in)


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_fail_multi_field_validation(
    charm_class: type[BaseTestCharm], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            event.relation.load(self.databag_class, event.app, decoder=self.decoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    # The value of 'foo' cannot be in the 'baz' list.
    data = {
        'foo': json.dumps('value'),
        'bar': json.dumps('1979'),
        'baz': json.dumps(['value', 'b']),
    }
    rel = testing.Relation('db', remote_app_data=data)
    state_in = testing.State(leader=True, relations={rel})
    with pytest.raises(ValueError):
        ctx.run(ctx.on.relation_changed(rel), state_in)


class _AliasProtocol(Protocol):
    foo_bar: int
    other: str


class _Alias:  # ruff: ignore[class-as-data-structure]
    # This is pretty quirky, but we need `fooBar` to be in the type annotations
    # and we need it to return the value of `foo_bar` to correctly save back to
    # Juju. Other than being ugly to look at, this means that the class offers
    # `.fooBar` as well as `.foo_bar`. In practice, the expectation is that
    # charms that need aliases like this should use dataclasses or pydantic.
    # We have this here so that we can still have the standard set of four
    # classes being tested.
    fooBar: int = property(lambda self: self.foo_bar)  # type: ignore  # ruff: ignore[mixed-case-variable-in-class-scope]

    other: str

    def __init__(self, fooBar: int = 42, other: str = 'baz'):  # ruff: ignore[invalid-argument-name]
        self.foo_bar = fooBar
        self.other = other


@dataclasses.dataclass
class _DataclassesAlias:
    foo_bar: int = dataclasses.field(default=42, metadata={'alias': 'fooBar'})
    other: str = 'baz'


_alias_classes: list[type[object]] = [_Alias, _DataclassesAlias]

if pydantic is not None:

    @pydantic.dataclasses.dataclass
    class _PydanticDataclassesAlias:
        foo_bar: int = dataclasses.field(default=42, metadata={'alias': 'fooBar'})
        other: str = pydantic.Field(default='baz')

    class _PydanticBaseModelAlias(pydantic.BaseModel):
        foo_bar: int = pydantic.Field(42, alias='fooBar')
        other: str = pydantic.Field('baz')

    _alias_classes.extend([_PydanticDataclassesAlias, _PydanticBaseModelAlias])


@pytest.mark.parametrize('relation_data', [{}, {'fooBar': '24'}])
@pytest.mark.parametrize('relation_data_class', _alias_classes)
def test_relation_load_custom_naming_pattern(
    relation_data: dict[str, str], relation_data_class: type[_AliasProtocol]
):
    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(relation_data_class, event.app)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data=relation_data)
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        obj = mgr.charm.data
    assert obj.foo_bar == json.loads(relation_data.get('fooBar', '42'))
    assert obj.other == 'baz'


@pytest.mark.parametrize('relation_data_class', _alias_classes)
def test_relation_save_custom_naming_pattern(relation_data_class: type[_AliasProtocol]):
    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = event.relation.load(relation_data_class, event.app)
            data.foo_bar = 24
            data.other = 'foo'
            event.relation.save(data, self.app)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation(
        'db', remote_app_data={'fooBar': json.dumps('42'), 'other': json.dumps('baz')}
    )
    state_in = testing.State(leader=True, relations={rel})
    state_out = ctx.run(ctx.on.relation_changed(rel), state_in)
    data = state_out.get_relation(rel.id).local_app_data
    assert data == {
        'fooBar': json.dumps(24),
        'other': json.dumps('foo'),
    }


def test_juju_fields_pydantic_dataclass_without_is_pydantic_dataclass():
    """Pydantic dataclasses from before pydantic 2.11 still have their aliases kept.

    ``__is_pydantic_dataclass__`` only exists from pydantic 2.11, but every
    pydantic 2 dataclass has ``__pydantic_validator__`` in its ``__dict__``.
    Simulate the older shape on a plain dataclass, so that the test doesn't
    need multiple installed pydantic versions.
    """

    @dataclasses.dataclass
    class Data:
        foo_bar: int = dataclasses.field(default=42, metadata={'alias': 'fooBar'})

    Data.__pydantic_validator__ = object()  # pyright: ignore[reportAttributeAccessIssue]

    assert ops.charm._juju_fields(Data) == {'fooBar': 'fooBar'}


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


def _load_into(cls: type[Any], remote_app_data: dict[str, str]) -> Any:
    """Load ``remote_app_data`` into ``cls`` via ``Relation.load`` and return the result."""

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(cls, event.app)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data=remote_app_data)
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        return mgr.charm.data


def test_relation_load_optional_nested_dataclass():
    """Optional[X] (a Union with one concrete member) is coerced against X."""

    @dataclasses.dataclass
    class Data:
        inner: Nested | None = None

    obj = _load_into(Data, {'inner': json.dumps({'sub': 1})})
    assert isinstance(obj.inner, Nested)
    assert obj.inner.sub == 1

    obj = _load_into(Data, {})
    assert obj.inner is None


def test_relation_load_optional_explicit_null():
    """An Optional[X] field whose databag value is null stays None.

    The value is not coerced against X, which would reject None: building a
    nested dataclass, iterating a list, or calling an enum all fail on it.
    """

    @dataclasses.dataclass
    class Data:
        inner: Nested | None = None
        items: list[str] | None = None
        colour: _Colour | None = None

    obj = _load_into(
        Data,
        {'inner': json.dumps(None), 'items': json.dumps(None), 'colour': json.dumps(None)},
    )
    assert obj.inner is None
    assert obj.items is None
    assert obj.colour is None


def test_relation_load_dict_of_nested_dataclass():
    """dict[str, X] fields are coerced against X for each value."""

    @dataclasses.dataclass
    class Data:
        by_name: dict[str, Nested]

    obj = _load_into(Data, {'by_name': json.dumps({'a': {'sub': 1}, 'b': {'sub': 2}})})
    assert obj.by_name == {'a': Nested(sub=1), 'b': Nested(sub=2)}
    assert all(isinstance(v, Nested) for v in obj.by_name.values())


def test_relation_load_dict_with_enum_keys():
    """dict[K, V] fields coerce each key against K as well as each value against V."""

    @dataclasses.dataclass
    class Data:
        by_colour: dict[_Colour, Nested]

    obj = _load_into(Data, {'by_colour': json.dumps({'red': {'sub': 1}})})
    assert obj.by_colour == {_Colour.RED: Nested(sub=1)}


def test_relation_load_union_of_two_concrete_types_passes_through():
    """A Union with more than one concrete member is passed through as-is.

    There is no way to tell which member to coerce against, so this is a
    regression check that such fields keep working uncoerced rather than
    raising.
    """

    @dataclasses.dataclass
    class Data:
        value: int | str

    obj = _load_into(Data, {'value': json.dumps('x')})
    assert obj.value == 'x'


@pytest.mark.parametrize(
    'annotation,written,expected',
    [
        pytest.param(
            list[Nested] | dict[str, Nested],
            [{'sub': 1}],
            [Nested(sub=1)],
            id='list-or-dict-given-list',
        ),
        pytest.param(
            list[Nested] | dict[str, Nested],
            {'a': {'sub': 1}},
            {'a': Nested(sub=1)},
            id='list-or-dict-given-dict',
        ),
        pytest.param(Nested | str, {'sub': 1}, Nested(sub=1), id='dataclass-or-str-given-dict'),
        pytest.param(Nested | str, 'x', 'x', id='dataclass-or-str-given-str'),
        pytest.param(
            Nested | _Colour, {'sub': 1}, Nested(sub=1), id='dataclass-or-enum-given-dict'
        ),
        pytest.param(Nested | _Colour, 'red', _Colour.RED, id='dataclass-or-enum-given-str'),
        pytest.param(
            collections.abc.Sequence[Nested] | str,
            [{'sub': 1}],
            [Nested(sub=1)],
            id='sequence-or-str-given-list',
        ),
        pytest.param(
            collections.abc.Sequence[Nested] | str, 'x', 'x', id='sequence-or-str-given-str'
        ),
    ],
)
def test_relation_load_union_picks_member_by_shape(annotation: Any, written: Any, expected: Any):
    """A Union is coerced against the one member that matches the value's shape."""
    # This module uses postponed annotations, so a class body annotation would
    # be the unresolvable string 'annotation' rather than the type itself.
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps(written)})
    assert obj.value == expected
    assert type(obj.value) is type(expected)


def test_relation_load_union_ambiguous_scalar_passes_through():
    """A scalar that fits more than one member of a Union is passed through as-is."""

    @dataclasses.dataclass
    class Data:
        colour: _Colour | str

    obj = _load_into(Data, {'colour': json.dumps('red')})
    assert obj.colour == 'red'


@pytest.mark.parametrize(
    'wildcard', [pytest.param(Any, id='any'), pytest.param(object, id='object')]
)
def test_relation_load_union_with_any_or_object_member_passes_through(wildcard: Any):
    """Any and object accept a value of any shape, so the value is passed through as-is."""
    data_class = dataclasses.make_dataclass('Data', [('value', list[Nested] | wildcard)])

    obj = _load_into(data_class, {'value': json.dumps({'sub': 1})})
    assert obj.value == {'sub': 1}


@pytest.mark.parametrize('form', ['alias', 'alias-or-none', 'alias-or-int'])
def test_relation_load_type_statement_alias_passes_through(form: str):
    """A type alias from the type statement isn't resolved, so the value is passed through."""
    if sys.version_info < (3, 12):
        pytest.skip('the type statement needs Python 3.12')
    alias = typing.TypeAliasType('Pets', list[Nested])
    annotation = {'alias': alias, 'alias-or-none': alias | None, 'alias-or-int': alias | int}[form]
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps([{'sub': 1}])})
    assert obj.value == [{'sub': 1}]


def test_relation_load_union_with_none_member():
    """A null value for a Union with a None member stays None."""

    @dataclasses.dataclass
    class Data:
        inner: Nested | list[Nested] | None = None

    obj = _load_into(Data, {'inner': json.dumps(None)})
    assert obj.inner is None


def test_relation_load_union_no_member_fits():
    """A value that matches the shape of no member of a Union is rejected."""

    @dataclasses.dataclass
    class Data:
        inner: Nested | list[Nested]

    # The charm doesn't catch it, so ops.testing reports it as an uncaught error.
    with pytest.raises(
        testing.errors.UncaughtCharmError, match='expected a value matching one of'
    ):
        _load_into(Data, {'inner': json.dumps('oops')})


def test_relation_load_variable_length_tuple():
    """tuple[X, ...] is coerced element-wise against X and stays a tuple."""

    @dataclasses.dataclass
    class Data:
        items: tuple[Nested, ...]

    obj = _load_into(Data, {'items': json.dumps([{'sub': 1}, {'sub': 2}])})
    assert obj.items == (Nested(sub=1), Nested(sub=2))
    assert isinstance(obj.items, tuple)


def test_relation_load_heterogeneous_tuple():
    """A fixed-length tuple[X, Y] is coerced positionally against each type."""

    @dataclasses.dataclass
    class Data:
        pair: tuple[int, _Colour]

    obj = _load_into(Data, {'pair': json.dumps([1, 'red'])})
    assert obj.pair == (1, _Colour.RED)
    assert isinstance(obj.pair, tuple)


@pytest.mark.parametrize('written', [[1], [1, 'red', 'blue']])
def test_relation_load_fixed_length_tuple_rejects_a_length_mismatch(
    written: list[object], monkeypatch: pytest.MonkeyPatch
):
    """A fixed-length tuple needs exactly as many values as annotated positions."""
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    @dataclasses.dataclass
    class Data:
        pair: tuple[int, _Colour]

    with pytest.raises(ValueError, match='zip'):
        _load_into(Data, {'pair': json.dumps(written)})


@pytest.mark.parametrize('form', ['star', 'unpack'])
def test_relation_load_tuple_with_unpacked_member_builds_uncoerced_tuple(form: str):
    """A tuple with an unpacked member, such as *tuple[X, ...], is built without coercion."""
    if sys.version_info < (3, 11):
        pytest.skip('unpacked tuple members need Python 3.11')
    if form == 'star':
        annotation = tuple[(int, *tuple[Nested, ...])]
    else:
        annotation = tuple[int, typing.Unpack[tuple[Nested, ...]]]
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps([1, {'sub': 1}, {'sub': 2}])})
    assert obj.value == (1, {'sub': 1}, {'sub': 2})


@pytest.mark.parametrize(
    'annotation',
    [
        pytest.param(tuple[int, str, ...], id='ellipsis-after-two-types'),  # pyright: ignore[reportInvalidTypeForm]
        pytest.param(tuple[...], id='ellipsis-alone'),  # pyright: ignore[reportInvalidTypeForm]
    ],
)
def test_relation_load_tuple_with_misplaced_ellipsis_builds_uncoerced_tuple(annotation: Any):
    """A tuple with an Ellipsis anywhere other than tuple[X, ...] is built without coercion."""
    # This module uses postponed annotations, so a class body annotation would
    # be the unresolvable string 'annotation' rather than the type itself.
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps([1, 'a', 'b'])})
    assert obj.value == (1, 'a', 'b')


def test_relation_load_set_and_frozenset():
    """set[X] and frozenset[X] coerce their elements and keep their own type."""

    @dataclasses.dataclass
    class Data:
        mutable: set[_Colour]
        immutable: frozenset[_Colour]

    obj = _load_into(
        Data, {'mutable': json.dumps(['red']), 'immutable': json.dumps(['red', 'blue'])}
    )
    assert obj.mutable == {_Colour.RED}
    assert type(obj.mutable) is set
    assert obj.immutable == frozenset({_Colour.RED, _Colour.BLUE})
    assert type(obj.immutable) is frozenset


@pytest.mark.parametrize(
    'annotation,expected',
    [
        pytest.param(collections.abc.Iterable[_Colour], [_Colour.RED], id='iterable'),
        pytest.param(collections.abc.Collection[_Colour], [_Colour.RED], id='collection'),
        pytest.param(collections.abc.Sequence[_Colour], [_Colour.RED], id='sequence'),
        pytest.param(
            collections.abc.MutableSequence[_Colour], [_Colour.RED], id='mutable-sequence'
        ),
        pytest.param(collections.abc.Set[_Colour], frozenset({_Colour.RED}), id='set'),
        pytest.param(collections.abc.MutableSet[_Colour], {_Colour.RED}, id='mutable-set'),
    ],
)
def test_relation_load_abstract_collection(annotation: Any, expected: Any):
    """An abstract collection field coerces its elements and is built as a concrete type."""
    # This module uses postponed annotations, so a class body annotation would
    # be the unresolvable string 'annotation' rather than the type itself.
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps(['red'])})
    assert obj.value == expected
    assert type(obj.value) is type(expected)


@pytest.mark.parametrize(
    'annotation',
    [
        pytest.param(collections.abc.Mapping[str, _Colour], id='mapping'),
        pytest.param(collections.abc.MutableMapping[str, _Colour], id='mutable-mapping'),
    ],
)
def test_relation_load_abstract_mapping(annotation: Any):
    """An abstract mapping field coerces its values and is built as a dict."""
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps({'a': 'red'})})
    assert obj.value == {'a': _Colour.RED}
    assert type(obj.value) is dict


@pytest.mark.parametrize(
    'annotation,expected',
    [
        pytest.param(set, {'red'}, id='set'),
        pytest.param(frozenset, frozenset({'red'}), id='frozenset'),
        pytest.param(tuple, ('red',), id='tuple'),
        pytest.param(list, ['red'], id='list'),
        pytest.param(collections.abc.Set, frozenset({'red'}), id='abc-set'),
        pytest.param(collections.abc.MutableSet, {'red'}, id='abc-mutable-set'),
        pytest.param(collections.abc.Sequence, ['red'], id='abc-sequence'),
        pytest.param(collections.abc.Iterable, ['red'], id='abc-iterable'),
        pytest.param(typing.Set, {'red'}, id='typing-set'),  # ruff: ignore[non-pep585-annotation]
        pytest.param(typing.Sequence, ['red'], id='typing-sequence'),
        pytest.param(typing.Tuple, ('red',), id='typing-tuple'),  # ruff: ignore[non-pep585-annotation]
    ],
)
def test_relation_load_bare_collection_builds_collection(annotation: Any, expected: Any):
    """A collection annotation without type arguments is built, but its items aren't coerced."""
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps(['red'])})
    assert obj.value == expected
    assert type(obj.value) is type(expected)


@pytest.mark.parametrize(
    'annotation',
    [
        pytest.param(dict, id='dict'),
        pytest.param(collections.abc.Mapping, id='abc-mapping'),
        pytest.param(typing.Dict, id='typing-dict'),  # ruff: ignore[non-pep585-annotation]
    ],
)
def test_relation_load_bare_mapping_builds_dict(annotation: Any):
    """A mapping annotation without type arguments is built as a dict, without coercion."""
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps({'a': 'red'})})
    assert obj.value == {'a': 'red'}
    assert type(obj.value) is dict


@pytest.mark.parametrize(
    'annotation',
    [
        pytest.param(collections.abc.Iterable[_Colour], id='iterable'),
        pytest.param(collections.abc.Collection[_Colour], id='collection'),
        pytest.param(collections.abc.Collection[_Colour] | int, id='collection-or-int'),
    ],
)
def test_relation_load_iterable_or_collection_given_mapping_uses_keys(annotation: Any):
    """A mapping is an Iterable or Collection of its keys, so its keys are coerced."""
    data_class = dataclasses.make_dataclass('Data', [('value', annotation)])

    obj = _load_into(data_class, {'value': json.dumps({'red': 1, 'blue': 2})})
    assert obj.value == [_Colour.RED, _Colour.BLUE]


def test_relation_load_other_mapping_type_passes_through():
    """A mapping type other than dict, Mapping or MutableMapping is passed through.

    There is no general way to build an arbitrary mapping type (a defaultdict
    needs a default factory, for example), so the field gets the decoded dict.
    """

    @dataclasses.dataclass
    class Data:
        by_name: collections.OrderedDict[str, Nested]

    obj = _load_into(Data, {'by_name': json.dumps({'a': {'sub': 1}})})
    assert obj.by_name == {'a': {'sub': 1}}


def test_relation_load_sequence_field_rejects_string_or_mapping(monkeypatch: pytest.MonkeyPatch):
    """A str, bytes or mapping value for a sequence field raises, rather than being iterated.

    All three are iterable, so coercing element-wise would silently produce a
    list of characters, or of the mapping's keys, instead of failing.
    """
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    @dataclasses.dataclass
    class Data:
        tags: list[str]

    with pytest.raises(TypeError, match='expected a sequence'):
        _load_into(Data, {'tags': json.dumps('hello')})

    with pytest.raises(TypeError, match='expected a sequence'):
        _load_into(Data, {'tags': json.dumps({'a': 1})})

    @dataclasses.dataclass
    class SetData:
        tags: set[str]

    with pytest.raises(TypeError, match='expected a sequence'):
        _load_into(SetData, {'tags': json.dumps('hello')})

    # A mapping isn't a Sequence, unlike an Iterable or Collection.
    sequence_data = dataclasses.make_dataclass(
        'SequenceData', [('tags', collections.abc.Sequence[str])]
    )
    with pytest.raises(TypeError, match='expected a sequence'):
        _load_into(sequence_data, {'tags': json.dumps({'a': 1})})

    # A tuple shape that is otherwise passed through as-is still rejects a string.
    unsupported_tuple_data = dataclasses.make_dataclass(
        'UnsupportedTupleData',
        [('tags', tuple[int, str, ...])],  # pyright: ignore[reportInvalidTypeForm]
    )
    with pytest.raises(TypeError, match='expected a sequence'):
        _load_into(unsupported_tuple_data, {'tags': json.dumps('hello')})

    # A genuine sequence is still coerced.
    obj = _load_into(Data, {'tags': json.dumps(['hello'])})
    assert obj.tags == ['hello']


def test_relation_load_mapping_field_rejects_non_mapping(monkeypatch: pytest.MonkeyPatch):
    """A non-mapping value for a dict field raises a clear error."""
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    @dataclasses.dataclass
    class Data:
        by_name: dict[str, int]

    with pytest.raises(TypeError, match='expected a mapping'):
        _load_into(Data, {'by_name': json.dumps([1, 2])})

    obj = _load_into(Data, {'by_name': json.dumps({'a': 1})})
    assert obj.by_name == {'a': 1}


def test_relation_load_pydantic_dataclass_guard_without_is_pydantic_dataclass():
    """The pydantic guard must key off __pydantic_validator__, not __is_pydantic_dataclass__.

    __is_pydantic_dataclass__ only exists from pydantic 2.11; older pydantic
    dataclasses (as old as 2.0.3) have __pydantic_validator__ in their
    __dict__ instead. Simulate that older shape on a plain dataclass, without
    needing multiple installed pydantic versions, and confirm Relation.load
    still treats it as a pydantic target: ops's own recursive coercion must
    not run, so a nested-dataclass-typed field stays a plain decoded dict
    rather than being (mis-)coerced ahead of pydantic's own validation.
    """

    @dataclasses.dataclass
    class Data:
        nested: Nested

    # Simulate pydantic < 2.11's shape.
    Data.__pydantic_validator__ = object()  # pyright: ignore[reportAttributeAccessIssue]

    obj = _load_into(Data, {'nested': json.dumps({'sub': 1})})
    assert isinstance(obj.nested, dict)


@pytest.mark.skipif(
    pydantic is None,
    reason='pydantic is not available, so we cannot test pydantic-based classes.',
)
def test_relation_load_nested_pydantic_model():
    """A nested Pydantic model is built by Pydantic, which applies its aliases and validation."""
    assert pydantic is not None

    class Model(pydantic.BaseModel):
        secret_id: str = pydantic.Field(alias='secret-id')
        count: int = pydantic.Field(default=0, ge=0)

    data_class = dataclasses.make_dataclass(
        'Data',
        [('model', Model), ('models', list[Model]), ('maybe', Model | str | None, None)],
    )
    obj = _load_into(
        data_class,
        {
            'model': json.dumps({'secret-id': 'a', 'count': '2'}),
            'models': json.dumps([{'secret-id': 'b'}]),
            'maybe': json.dumps({'secret-id': 'c'}),
        },
    )
    assert isinstance(obj.model, Model)
    assert (obj.model.secret_id, obj.model.count) == ('a', 2)
    assert [m.secret_id for m in obj.models] == ['b']
    assert isinstance(obj.maybe, Model)
    assert obj.maybe.secret_id == 'c'

    # The charm doesn't catch it, so ops.testing reports it as an uncaught error.
    with pytest.raises(testing.errors.UncaughtCharmError, match='greater than or equal to 0'):
        _load_into(
            data_class, {'model': json.dumps({'secret-id': 'a', 'count': -1}), 'models': '[]'}
        )


@pytest.mark.parametrize(
    'written',
    [
        pytest.param(json.dumps('oops'), id='string'),
        pytest.param(json.dumps([1, 2]), id='list'),
        pytest.param(json.dumps(3), id='int'),
        # A string that happens to contain every field name: the membership
        # test that skips absent fields passes for the wrong reason.
        pytest.param(json.dumps('subscribe'), id='string-containing-field-name'),
    ],
)
def test_relation_load_rejects_a_non_mapping_for_a_nested_dataclass(written: str):
    """A remote app can write anything, and ops must not invent an object from it.

    `_build_dataclass` decides which fields to fill with `field.name not in
    data`, which is False for every field of a string or a list, so without
    this guard the charm is handed a confidently default-constructed object
    corresponding to nothing in the databag - or a TypeError from inside ops,
    depending on the value.
    """

    @dataclasses.dataclass
    class Data:
        nested: Nested | None = None

    # The charm doesn't catch it, so ops.testing reports it as an uncaught error.
    with pytest.raises(testing.errors.UncaughtCharmError, match='expected a mapping for Nested'):
        _load_into(Data, {'nested': written})


def test_relation_load_passes_through_an_already_built_keyword_argument():
    """`kwargs` are passed through to the data class as given."""

    @dataclasses.dataclass
    class Data:
        name: str = ''
        nested: Nested | None = None

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(Data, event.app, nested=Nested(sub=5))

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data={'name': json.dumps('x')})
    with ctx(ctx.on.relation_changed(rel), testing.State(relations={rel})) as mgr:
        mgr.run()
        data = mgr.charm.data

    assert data == Data(name='x', nested=Nested(sub=5))


def test_relation_load_does_not_coerce_keyword_arguments():
    """A keyword argument is passed through uncoerced, like a positional one."""

    @dataclasses.dataclass
    class Data:
        name: str = ''
        nested: Nested | None = None

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(Data, event.app, nested={'sub': 5})

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data={'name': json.dumps('x')})
    with ctx(ctx.on.relation_changed(rel), testing.State(relations={rel})) as mgr:
        mgr.run()
        data = mgr.charm.data

    assert data.nested == {'sub': 5}


@pytest.mark.parametrize('kind', ['dataclass', 'dataclass-fallback', 'pydantic', 'plain-class'])
def test_relation_load_relation_data_overrides_keyword_argument(kind: str):
    """A keyword argument with the same name as a field in the relation data is overridden."""
    if kind == 'dataclass':

        @dataclasses.dataclass
        class Data:  # pyright: ignore[reportRedeclaration]
            name: str = ''
            other: str = ''

    elif kind == 'dataclass-fallback':

        @dataclasses.dataclass
        class Data:  # pyright: ignore[reportRedeclaration]
            name: str = ''
            other: str = ''
            # Not a type, so get_type_hints raises and nothing is coerced.
            count: int | 1 = 0  # pyright: ignore[reportGeneralTypeIssues]

    elif kind == 'pydantic':
        if pydantic is None:
            pytest.skip('pydantic is not installed')

        class Data(pydantic.BaseModel):  # pyright: ignore[reportRedeclaration]
            name: str = ''
            other: str = ''

    else:
        # Deliberately not a dataclass, to exercise the path for any other class.
        class Data:  # ruff: ignore[class-as-data-structure]
            def __init__(self, name: str = '', other: str = ''):
                self.name = name
                self.other = other

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(Data, event.app, name='kwarg', other='kwarg')

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data={'name': json.dumps('relation')})
    with ctx(ctx.on.relation_changed(rel), testing.State(relations={rel})) as mgr:
        mgr.run()
        data = mgr.charm.data

    assert data.name == 'relation'
    assert data.other == 'kwarg'


def test_relation_load_falls_back_when_type_hints_unresolvable():
    """get_type_hints raises NameError on a TYPE_CHECKING-only annotation.

    ops's own ruff config disables TC001/2/3, so charms following ops's
    conventions are the ones most likely to hit this. Relation.load must
    fall back to the un-coerced constructor rather than raising.
    """

    @dataclasses.dataclass
    class Data:
        amount: decimal.Decimal | None = None
        name: str = ''

    obj = _load_into(Data, {'name': json.dumps('x')})
    assert obj.name == 'x'
    assert obj.amount is None


def test_relation_load_falls_back_when_type_hint_is_not_a_type():
    """get_type_hints raises TypeError on an annotation that isn't a type."""

    @dataclasses.dataclass
    class Data:
        count: int | 1 = 0  # pyright: ignore[reportGeneralTypeIssues]
        nested: Nested | None = None

    obj = _load_into(Data, {'nested': json.dumps({'sub': 1})})
    assert obj.nested == {'sub': 1}
    assert obj.count == 0


def test_relation_load_fallback_error_is_not_chained_to_type_hint_error():
    """An error from the data class in the fallback path is reported on its own.

    If it were raised while handling the get_type_hints error, the traceback
    would lead with that error, which isn't the charm's problem.
    """

    @dataclasses.dataclass
    class Data:
        amount: decimal.Decimal | None = None
        name: str = ''

        def __post_init__(self):
            raise ValueError('bad name')

    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        _load_into(Data, {'name': json.dumps('x')})
    error = exc_info.value.__cause__
    assert isinstance(error, ValueError)
    assert str(error) == 'bad name'
    assert error.__context__ is None


def test_relation_load_extra_args_still_coerces_remaining_fields():
    """A positional arg must not silently disable coercion for other fields.

    relation.load(cls, src, *args) matches args to cls's leading fields by
    position; any fields filled that way are left uncoerced (there's nothing
    to coerce them against without knowing which field each arg is for), but
    fields still supplied from the relation data should keep being coerced.
    """

    @dataclasses.dataclass
    class Data:
        a: int
        b: Nested

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(Data, event.app, 10)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation('db', remote_app_data={'b': json.dumps({'sub': 1})})
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        obj = mgr.charm.data
    assert obj.a == 10
    assert isinstance(obj.b, Nested)
    assert obj.b.sub == 1


def test_relation_load_positional_arg_colliding_with_relation_data_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    """A positional arg for a field that is also in the relation data raises TypeError."""
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    @dataclasses.dataclass
    class Data:
        a: int
        b: Nested

    class Charm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            event.relation.load(Data, event.app, 10)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation(
        'db', remote_app_data={'a': json.dumps(20), 'b': json.dumps({'sub': 1})}
    )
    state_in = testing.State(leader=True, relations={rel})
    with pytest.raises(TypeError, match='multiple values'):
        ctx.run(ctx.on.relation_changed(rel), state_in)


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_simple(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = self.databag_class(
                foo='other-value', bar=28, baz=['x', 'y'], quux=Nested(sub=8)
            )
            event.relation.save(data, self.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db')
    state_in = testing.State(leader=True, relations={rel_in})
    state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)
    rel_out = state_out.get_relation(rel_in.id)
    assert rel_out.local_app_data == {
        'foo': json.dumps('other-value'),
        'bar': json.dumps(28),
        'baz': json.dumps(['x', 'y']),
        'quux': json.dumps({'sub': 8}),
    }


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_no_access(
    charm_class: type[BaseTestCharm], monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = self.databag_class(foo='value', bar=1, baz=['a', 'b'])
            event.relation.save(data, event.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db')
    state_in = testing.State(leader=True, relations={rel_in})
    with pytest.raises(ops.RelationDataAccessError):
        ctx.run(ctx.on.relation_changed(rel_in), state_in)


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_then_save(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            self.data = event.relation.load(self.databag_class, self.app)
            self.data.foo = self.data.foo + '1'
            self.data.bar = self.data.bar + 1
            assert self.data.baz is not None
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


@pytest.mark.parametrize('charm_class', [c for c in _test_classes if c is not MyCharm])
def test_relation_load_unit_data_ignores_juju_keys(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            saved = self.databag_class(foo='value', bar=1, baz=['a', 'b'])
            event.relation.save(saved, self.unit, encoder=self.encoder)
            assert 'ingress-address' in event.relation.data[self.unit]
            assert 'private-address' in event.relation.data[self.unit]
            self.data = event.relation.load(self.databag_class, self.unit, decoder=self.decoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel = testing.Relation(
        'db',
        local_unit_data={
            'egress-subnets': '192.0.2.0',
            'ingress-address': '192.0.2.0',
            'private-address': '192.0.2.0',
        },
    )
    state_in = testing.State(leader=True, relations={rel})
    with ctx(ctx.on.relation_changed(rel), state_in) as mgr:
        mgr.run()
        obj = mgr.charm.data
    assert obj.foo == 'value'
    assert obj.bar == 1
    assert obj.baz == ['a', 'b']


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_invalid(charm_class: type[BaseTestCharm], monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv('SCENARIO_BARE_CHARM_ERRORS', 'true')

    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            def encoder(_: Any) -> int:
                # This is invalid: Juju only accepts strings.
                return 0

            data = self.databag_class(foo='value')
            event.relation.save(data, self.app, encoder=encoder)  # type: ignore

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db')
    state_in = testing.State(leader=True, relations={rel_in})
    with pytest.raises(ops.RelationDataTypeError):
        ctx.run(ctx.on.relation_changed(rel_in), state_in)


class _OneStringProtocol(Protocol):
    foo: str

    def __init__(self, foo: str): ...


class _OneString:  # ruff: ignore[class-as-data-structure]
    foo: str

    def __init__(self, foo: str):
        self.foo = foo


@dataclasses.dataclass
class _DataclassesOneString:
    foo: str


_one_string_classes: list[type[object]] = [_OneString, _DataclassesOneString]

if pydantic is not None:

    @pydantic.dataclasses.dataclass()
    class _PydanticDataclassesOneString:
        foo: str

    class _PydanticBaseModelOneString(pydantic.BaseModel):
        foo: str = pydantic.Field()

    _one_string_classes.extend([_PydanticDataclassesOneString, _PydanticBaseModelOneString])


@pytest.mark.parametrize('data_class', _one_string_classes)
def test_relation_save_no_encode(data_class: type[_OneStringProtocol]):
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
    def custom_encode(data: Any) -> str:
        if hasattr(data, 'upper'):
            return data.upper()
        return str(data)

    def custom_decode(data: str) -> Any:
        if hasattr(data, '__getitem__'):
            return data[::-1]
        return data

    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = event.relation.load(self.databag_class, self.app, decoder=custom_decode)
            assert data.foo == 'eulav'
            data.foo = data.foo + '1'
            event.relation.save(data, self.app, encoder=custom_encode)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db', local_app_data={'foo': 'value'})
    state_in = testing.State(leader=True, relations={rel_in})
    state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)
    rel_out = state_out.get_relation(rel_in.id)
    assert rel_out.local_app_data['foo'] == 'EULAV1'


class Country(enum.Enum):
    NZ = 'New Zealand'
    JP = 'Japan'
    CN = 'China'


class CommonTypesProtocol(Protocol):
    url: str
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    network: ipaddress.IPv4Network | ipaddress.IPv6Network
    origin: Country

    def __init__(
        self,
        *,
        url: str,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | str,
        network: ipaddress.IPv4Network | ipaddress.IPv6Network | str,
        origin: Country | str,
    ): ...


class BaseTestCharmCommonTypes(ops.CharmBase):
    encoder: Callable[[Any], str] | None = None
    decoder: Callable[[Any], str] | None = None

    @property
    def databag_class(self) -> type[CommonTypesProtocol]:
        raise NotImplementedError('databag_class must be set in the subclass')


class _CommonTypesData:
    url: str
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    network: ipaddress.IPv4Network | ipaddress.IPv6Network
    origin: Country | str

    def __init__(
        self,
        *,
        url: str,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | str,
        network: ipaddress.IPv4Network | ipaddress.IPv6Network | str,
        origin: Country | str,
    ):
        if not self._validate_url(url):
            raise ValueError(f'Invalid URL: {url}')
        self.url = url
        if isinstance(ip, str):
            self.ip = ipaddress.ip_address(ip)
        else:
            self.ip = ip
        if isinstance(network, str):
            self.network = ipaddress.ip_network(network)
        else:
            self.network = network
        if isinstance(origin, str):
            self.origin = Country(origin)
        else:
            self.origin = origin

    @staticmethod
    def _validate_url(url: str):
        parsed_url = urllib.parse.urlparse(url)
        return bool(parsed_url.scheme and parsed_url.netloc)

    def __setattr__(self, key: str, value: Any):
        if key == 'url' and not self._validate_url(value):
            raise ValueError(f'Invalid URL: {value}')
        if key == 'ip' and not isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            raise ValueError(f'Invalid IP address: {value}')
        if key == 'network' and not isinstance(
            value, (ipaddress.IPv4Network, ipaddress.IPv6Network)
        ):
            raise ValueError(f'Invalid network: {value}')
        if key == 'origin' and isinstance(value, str):
            value = Country(value)
        super().__setattr__(key, value)


class CommonTypes(BaseTestCharmCommonTypes):
    @property
    def databag_class(self):
        return _CommonTypesData

    @staticmethod
    def encoder(x: Any) -> str:
        if isinstance(x, Country):
            return json.dumps(x.value)
        return json.dumps(str(x))


class _IPJSONEncoder(json.JSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(
            obj,
            (
                ipaddress.IPv4Address,
                ipaddress.IPv6Address,
                ipaddress.IPv4Network,
                ipaddress.IPv6Network,
            ),
        ):
            return str(obj)
        return super().default(obj)


class _CountryAndIPJSONEncoder(_IPJSONEncoder):
    def default(self, obj: Any) -> Any:
        if isinstance(obj, Country):
            return obj.value
        return super().default(obj)


@staticmethod
def json_ip_hook(dct: dict[str, Any]) -> dict[str, Any]:
    for key, value in dct.items():
        try:
            if '/' in value:
                dct[key] = ipaddress.ip_network(value, strict=False)
            else:
                dct[key] = ipaddress.ip_address(value)
        except ValueError:  # ruff: ignore[try-except-in-loop]
            pass
    return dct


json_ip_and_country_encode = functools.partial(json.dumps, cls=_CountryAndIPJSONEncoder)
json_ip_decode = functools.partial(json.loads, object_hook=json_ip_hook)


@dataclasses.dataclass
class _CommonTypesDataclass:
    url: str
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address
    network: ipaddress.IPv4Network | ipaddress.IPv6Network
    origin: Country | str

    def __init__(
        self,
        *,
        url: str,
        ip: ipaddress.IPv4Address | ipaddress.IPv6Address | str,
        network: ipaddress.IPv4Network | ipaddress.IPv6Network | str,
        origin: Country | str,
    ):
        if not self._validate_url(url):
            raise ValueError(f'Invalid URL: {url}')
        self.url = url
        if isinstance(ip, str):
            self.ip = ipaddress.ip_address(ip)
        else:
            self.ip = ip
        if isinstance(network, str):
            self.network = ipaddress.ip_network(network)
        else:
            self.network = network
        if isinstance(origin, str):
            self.origin = Country(origin)
        else:
            self.origin = origin

    @staticmethod
    def _validate_url(url: str):
        parsed_url = urllib.parse.urlparse(url)
        return bool(parsed_url.scheme and parsed_url.netloc)

    def __setattr__(self, key: str, value: Any):
        if key == 'url' and not self._validate_url(value):
            raise ValueError(f'Invalid URL: {value}')
        if key == 'ip' and not isinstance(value, (ipaddress.IPv4Address, ipaddress.IPv6Address)):
            raise ValueError(f'Invalid IP address: {value}')
        if key == 'network' and not isinstance(
            value, (ipaddress.IPv4Network, ipaddress.IPv6Network)
        ):
            raise ValueError(f'Invalid network: {value}')
        if key == 'origin' and isinstance(value, str):
            value = Country(value)
        super().__setattr__(key, value)


class CommonTypesDataclasses(BaseTestCharmCommonTypes):
    encoder = staticmethod(json_ip_and_country_encode)
    decoder = staticmethod(json_ip_decode)

    @property
    def databag_class(self):
        return _CommonTypesDataclass


_common_types_classes: list[type[ops.CharmBase]] = [CommonTypes, CommonTypesDataclasses]

if pydantic:

    @pydantic.dataclasses.dataclass
    class _DataPydanticDataclass:
        url: pydantic.AnyHttpUrl  # type: ignore
        ip: pydantic.IPvAnyAddress  # type: ignore
        network: pydantic.IPvAnyNetwork  # type: ignore
        origin: Country

    class CommonTypesPydanticDataclass(BaseTestCharmCommonTypes):
        encoder = staticmethod(json_ip_and_country_encode)

        @property
        def databag_class(self):
            return _DataPydanticDataclass

    class _DataBaseModel(pydantic.BaseModel):
        url: pydantic.AnyHttpUrl  # type: ignore
        ip: pydantic.IPvAnyAddress  # type: ignore
        network: pydantic.IPvAnyNetwork  # type: ignore
        origin: Country

        model_config = pydantic.ConfigDict(validate_assignment=True)

    class CommonTypesPydantic(BaseTestCharmCommonTypes):
        @property
        def databag_class(self):
            return _DataBaseModel

    _common_types_classes.extend([CommonTypesPydanticDataclass, CommonTypesPydantic])


@pytest.mark.parametrize('charm_class', _common_types_classes)
def test_relation_common_types(charm_class: type[BaseTestCharmCommonTypes]):
    class Charm(charm_class):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['db'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data: CommonTypesProtocol = event.relation.load(
                self.databag_class, event.app, decoder=self.decoder
            )
            # In the Pydantic classes .url is an AnyHttpUrl, and in the others it is
            # a regular string. For the purposes of this test, we're ok with it just
            # being a string.
            assert str(data.url) == 'https://example.com/'
            assert data.ip == ipaddress.ip_address('127.0.0.2')
            assert data.network == ipaddress.ip_network('127.0.1.0/24')
            assert data.origin == Country.NZ
            data.url = 'https://new.example.com/'
            data.ip = ipaddress.ip_address('127.0.0.3')
            data.network = ipaddress.ip_network('127.0.2.0/24')
            data.origin = Country.JP
            event.relation.save(data, self.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    data_in = {
        'url': json.dumps('https://example.com/'),
        'ip': json.dumps('127.0.0.2'),
        'network': json.dumps('127.0.1.0/24'),
        'origin': json.dumps('New Zealand'),
    }
    rel_in = testing.Relation('db', remote_app_data=data_in)
    state_in = testing.State(leader=True, relations={rel_in})
    state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)
    rel_out = state_out.get_relation(rel_in.id)
    assert rel_out.local_app_data['url'] == json.dumps('https://new.example.com/')
    assert rel_out.local_app_data['ip'] == json.dumps('127.0.0.3')
    assert rel_out.local_app_data['network'] == json.dumps('127.0.2.0/24')
    assert rel_out.local_app_data['origin'] == json.dumps('Japan')


# This test is based on the example in the manage-libraries how-to guide, which
# is in turn based on the tracing (v2) interface.
# The description and examples are kept in place from the doc, even though they
# are not necessarily used in the test itself, to keep the two copies roughly in
# sync.
@pytest.mark.skipif(
    pydantic is None,
    reason='pydantic is not available, so we cannot test pydantic-based classes.',
)
def test_relation_tracing_provider():
    assert pydantic is not None

    class TransportProtocolType(enum.Enum):
        HTTP = 'http'
        GRPC = 'grpc'

    class ProtocolType(pydantic.BaseModel):
        name: str = pydantic.Field(
            description='Receiver protocol name. What protocols are supported '
            '(and what they are called) may differ per provider.',
            examples=['otlp_grpc', 'otlp_http', 'tempo_http', 'jaeger_thrift_compact'],
        )
        type: TransportProtocolType = pydantic.Field(
            description='The transport protocol used by this receiver.',
            examples=['http', 'grpc'],
        )

    class Receiver(pydantic.BaseModel):
        protocol: ProtocolType = pydantic.Field(description='Receiver protocol name and type.')
        url: str = pydantic.Field(
            description="""URL at which the receiver is reachable. If there's an
            ingress, it would be the external URL.
            Otherwise, it would be the service's fqdn or internal IP.
            If the protocol type is grpc, the url will not contain a scheme.""",
            examples=[
                'http://traefik_address:2331',
                'https://traefik_address:2331',
                'http://tempo_public_ip:2331',
                'https://tempo_public_ip:2331',
                'tempo_public_ip:2331',
            ],
        )

    class TracingProviderAppData(pydantic.BaseModel):
        receivers: list[Receiver] = pydantic.Field(
            description='A list of enabled receivers in the form of the '
            'protocol they use and their resolvable server url.',
        )

    receiver_protocol_to_transport_protocol: dict[str, TransportProtocolType] = {
        'zipkin': TransportProtocolType.HTTP,
        'otlp_grpc': TransportProtocolType.GRPC,
        'otlp_http': TransportProtocolType.HTTP,
        'jaeger_thrift_http': TransportProtocolType.HTTP,
        'jaeger_grpc': TransportProtocolType.GRPC,
    }

    # This would typically be a charmlib, but a charm is simpler to use for this test.
    class TracingProviderCharm(ops.CharmBase):
        def __init__(self, framework: ops.Framework):
            super().__init__(framework)
            framework.observe(self.on['tracing'].relation_changed, self._on_relation_changed)

        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            urls = Receiver.model_json_schema()['properties']['url']['examples']
            urls = cast('list[str]', urls)
            receiver_prototcols = list(receiver_protocol_to_transport_protocol)
            # Cycle through the protocols so that the test uses each of them.
            receivers = [
                (receiver_prototcols[i % len(receiver_prototcols)], url)
                for i, url in enumerate(urls)
            ]
            self._publish_provider(event.relation, receivers)

        def _publish_provider(self, relation: ops.Relation, receivers: Iterable[tuple[str, str]]):
            data = TracingProviderAppData(
                receivers=[
                    Receiver(
                        url=url,
                        protocol=ProtocolType(
                            name=protocol,
                            type=receiver_protocol_to_transport_protocol[protocol],
                        ),
                    )
                    for protocol, url in receivers
                ],
            )
            relation.save(data, self.app)

    ctx = testing.Context(
        TracingProviderCharm,
        meta={'name': 'tracer', 'provides': {'tracing': {'interface': 'tracing'}}},
    )
    rel_in = testing.Relation('tracing')
    state_in = testing.State(leader=True, relations={rel_in})
    state_out = ctx.run(ctx.on.relation_changed(rel_in), state_in)
    rel_out = state_out.get_relation(rel_in.id)
    receivers = json.loads(rel_out.local_app_data['receivers'])
    assert len(receivers) == 5
    assert {
        'protocol': {'name': 'zipkin', 'type': 'http'},
        'url': 'http://traefik_address:2331',
    } in receivers
    assert {
        'protocol': {'name': 'otlp_grpc', 'type': 'grpc'},
        'url': 'https://traefik_address:2331',
    } in receivers
    assert {
        'protocol': {'name': 'otlp_http', 'type': 'http'},
        'url': 'http://tempo_public_ip:2331',
    } in receivers
    assert {
        'protocol': {'name': 'jaeger_thrift_http', 'type': 'http'},
        'url': 'https://tempo_public_ip:2331',
    } in receivers
    assert {
        'protocol': {'name': 'jaeger_grpc', 'type': 'grpc'},
        'url': 'tempo_public_ip:2331',
    } in receivers
