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
import functools
import ipaddress
import json
import urllib.parse
from collections.abc import Callable, Iterable
from typing import Any, Protocol, cast

import pytest

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
        baz: list[str] = [],  # noqa: B006
        quux: Nested = Nested(),  # noqa: B008
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

    class MyPydanticBaseModelCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[DatabagProtocol]:
            return MyPydanticDatabag

    _test_classes.extend((MyPydanticDataclassCharm, MyPydanticBaseModelCharm))


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
def test_relation_load_fail(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            event.relation.load(self.databag_class, event.app, decoder=self.decoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    # 'bar' should be an int, not a string.
    data = {'foo': json.dumps('value'), 'bar': json.dumps('bar'), 'baz': json.dumps(['a', 'b'])}
    rel = testing.Relation('db', remote_app_data=data)
    state_in = testing.State(leader=True, relations={rel})
    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.relation_changed(rel), state_in)
    assert isinstance(exc_info.value.__cause__, ValueError)


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_load_fail_multi_field_validation(charm_class: type[BaseTestCharm]):
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
    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.relation_changed(rel), state_in)
    assert isinstance(exc_info.value.__cause__, ValueError)


class _AliasProtocol(Protocol):
    foo_bar: int
    other: str


class _Alias:  # noqa: B903
    # This is pretty quirky, but we need `fooBar` to be in the type annotations
    # and we need it to return the value of `foo_bar` to correctly save back to
    # Juju. Other than being ugly to look at, this means that the class offers
    # `.fooBar` as well as `.foo_bar`. In practice, the expectation is that
    # charms that need aliases like this should use dataclasses or pydantic.
    # We have this here so that we can still have the standard set of four
    # classes being tested.
    fooBar: int = property(lambda self: self.foo_bar)  # type: ignore  # noqa: N815

    other: str

    def __init__(self, fooBar: int = 42, other: str = 'baz'):  # noqa: N803
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
def test_relation_save_no_access(charm_class: type[BaseTestCharm]):
    class Charm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = self.databag_class(foo='value', bar=1, baz=['a', 'b'])
            event.relation.save(data, event.app, encoder=self.encoder)

    ctx = testing.Context(Charm, meta={'name': 'foo', 'requires': {'db': {'interface': 'db-int'}}})
    rel_in = testing.Relation('db')
    state_in = testing.State(leader=True, relations={rel_in})
    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.relation_changed(rel_in), state_in)
    assert isinstance(exc_info.value.__cause__, ops.RelationDataAccessError)


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


@pytest.mark.parametrize('charm_class', _test_classes)
def test_relation_save_invalid(charm_class: type[BaseTestCharm]):
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
    with pytest.raises(testing.errors.UncaughtCharmError) as exc_info:
        ctx.run(ctx.on.relation_changed(rel_in), state_in)
    assert isinstance(exc_info.value.__cause__, ops.RelationDataTypeError)


class _OneStringProtocol(Protocol):
    foo: str

    def __init__(self, foo: str): ...


class _OneString:  # noqa: B903
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
        except ValueError:  # noqa: PERF203
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
