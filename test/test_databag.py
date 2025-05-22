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
import ops.charm as _charm
from ops import testing


@dataclasses.dataclass
class Nested:
    sub: int = 28


class DatabagProtocol(Protocol):
    foo: str
    baz: list[str] | None
    bar: int
    quux: Nested | None


class MyDatabag(ops.RelationDataBase):
    # These need to be class attributes to be picked up and sent to Juju.
    foo: str
    baz: list[str] | None = None
    bar: int = 0
    quux: Nested | None = None

    def __init__(
        self, foo: str, baz: list[str] | None = None, bar: int = 0, quux: Nested | None = None
    ):
        if isinstance(foo, str):
            self.foo = foo
        else:
            raise ValueError('foo must be a string')
        if isinstance(baz, list):
            if not all(isinstance(i, str) for i in baz):
                raise ValueError('baz must be a list of strings')
            self.baz = baz
        elif baz is None:
            self.baz = []
        else:
            raise ValueError('baz must be a list')
        if not isinstance(bar, int) or bar < 0:
            raise ValueError('bar must be a zero or positive int')
        else:
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
    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on.install, self._on_install)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on.update_status, self._on_update_status)
        framework.observe(self.on['db'].relation_changed, self._on_relation_changed)
        framework.observe(self.on['db'].relation_joined, self._on_relation_joined)

    @property
    def databag_class(self) -> type[ops.RelationDataBase]:
        raise NotImplementedError('databag_class must be set in the subclass')

    @property
    def encoder(self) -> Callable[..., Any] | None:
        return None

    @property
    def decoder(self) -> Callable[..., Any] | None:
        return None

    def _on_install(self, _: ops.InstallEvent):
        rel = self.model.get_relation('db')
        assert rel is not None
        self.data1 = rel.load(
            self.databag_class, self.app, encoder=self.encoder, decoder=self.decoder
        )
        rel = self.model.get_relation('db')
        assert rel is not None
        self.data2 = rel.load(
            self.databag_class, self.app, encoder=self.encoder, decoder=self.decoder
        )

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        rel = self.model.get_relation('db')
        assert rel is not None
        classic = rel.data[self.app]
        modern = rel.load(self.databag_class, self.app, encoder=self.encoder, decoder=self.decoder)
        modern = cast('DatabagProtocol', modern)
        classic['foo'] = json.dumps('one')
        assert modern.foo == json.dumps('one')
        modern.foo = 'two'
        assert classic['foo'] == 'two'
        # Also check that if we get a fresh RelationDataContent it's still the
        # expected value.
        classic2 = rel.data[self.app]
        assert classic2['foo'] == 'two'

    def _on_update_status(self, event: ops.UpdateStatusEvent):
        rel = self.model.get_relation('db')
        assert rel is not None
        data = rel.load(self.databag_class, self.app, encoder=self.encoder, decoder=self.decoder)
        data = cast('DatabagProtocol', data)
        data.bar = -42

    def _on_relation_changed(self, event: ops.RelationChangedEvent):
        data = event.relation.load(
            self.databag_class, self.app, encoder=self.encoder, decoder=self.decoder
        )
        data = cast('DatabagProtocol', data)
        self.newfoo = len(data.foo)
        assert data.baz is not None
        self.newbaz = [*data.baz, 'new']
        self.newbar = data.bar + 1
        assert data.quux is not None
        self.newquux = Nested(sub=data.quux.sub + 1)
        self.data = data

    def _on_relation_joined(self, event: ops.RelationJoinedEvent):
        data = event.relation.load(
            self.databag_class, self.app, encoder=self.encoder, decoder=self.decoder
        )
        data = cast('DatabagProtocol', data)
        data.foo = 'newfoo'
        data.baz = ['new']
        data.bar = 42
        data.quux = Nested(sub=25)


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
    def databag_class(self) -> type[ops.RelationDataBase]:
        return MyDatabag

    @property
    def encoder(self) -> Callable[..., Any] | None:
        return nested_encode

    @property
    def decoder(self) -> Callable[..., Any] | None:
        return nested_decode


@dataclasses.dataclass
class MyDataclassDatabag(ops.RelationDataBase):
    foo: str
    baz: list[str] = dataclasses.field(default_factory=list)
    bar: int = dataclasses.field(default=0)
    quux: Nested = dataclasses.field(default_factory=Nested)

    def __post_init__(self):
        if not isinstance(self.foo, str):
            raise ValueError('foo must be a string')
        if not isinstance(self.baz, list):
            raise ValueError('baz must be a list')
        if not all(isinstance(i, str) for i in self.baz):
            raise ValueError('baz must be a list of strings')
        if not isinstance(self.bar, int) or self.bar < 0:
            raise ValueError('bar must be a zero or positive int')

    def __setattr__(self, key: str, value: Any):
        if key == 'bar' and (not isinstance(value, int) or value < 0):
            raise ValueError('bar must be a zero or positive int')
        super().__setattr__(key, value)


class MyDataclassCharm(BaseTestCharm):
    @property
    def databag_class(self) -> type[ops.RelationDataBase]:
        return MyDataclassDatabag


_test_classes: list[type[ops.CharmBase]] = [MyCharm, MyDataclassCharm]

if pydantic:

    @pydantic.dataclasses.dataclass
    class MyPydanticDataclassDatabag(ops.RelationDataBase):
        foo: str
        baz: list[str] = pydantic.Field(default_factory=list)
        bar: int = pydantic.Field(default=0)
        quux: Nested = pydantic.Field(default_factory=Nested)

        def __post_init__(self):
            if not isinstance(self.foo, str):
                raise ValueError('foo must be a string')
            if not isinstance(self.baz, list):
                raise ValueError('baz must be a list')
            if not all(isinstance(i, str) for i in self.baz):
                raise ValueError('baz must be a list of strings')
            if not isinstance(self.bar, int) or self.bar < 0:
                raise ValueError('bar must be a zero or positive int')

        # TODO: This should be done pydantic-style.
        def __setattr__(self, key: str, value: Any):
            if key == 'bar' and (not isinstance(value, int) or value < 0):
                raise ValueError('bar must be a zero or positive int')
            super().__setattr__(key, value)

    class MyPydanticDataclassCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[ops.RelationDataBase]:
            return MyPydanticDataclassDatabag

    class MyPydanticDatabag(pydantic.BaseModel, ops.RelationDataBase):
        foo: str
        baz: list[str] = pydantic.Field(default_factory=list)
        bar: int = pydantic.Field(default=0, ge=0)
        quux: Nested = pydantic.Field(default_factory=Nested)

        class Config:
            validate_assignment = True

    class MyPydanticBaseModelCharm(BaseTestCharm):
        @property
        def databag_class(self) -> type[ops.RelationDataBase]:
            return MyPydanticDatabag

    _test_classes.extend((MyPydanticDataclassCharm, MyPydanticBaseModelCharm))


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_simple(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    harness = testing.Harness(
        charm_class, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel_id = harness.add_relation('db', 'db')
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    harness.charm.on['db'].relation_changed.emit(
        harness.model.get_relation('db'), harness.model.app
    )
    rel = harness.model.get_relation('db')
    assert rel is not None
    obj = rel._cache._databag_obj_cache[rel_id, harness.model.app][0]
    assert obj.foo == 'value'
    assert obj.bar == 1
    assert obj.baz == ['a', 'b']
    assert obj.quux.sub == 28


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_bad_init(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    harness = testing.Harness(
        charm_class, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': json.dumps('value'), 'bar': json.dumps('bar'), 'baz': json.dumps(['a', 'b'])}
    rel_id = harness.add_relation('db', 'db')
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    with pytest.raises(ops.InvalidSchemaError):
        harness.charm.on['db'].relation_changed.emit(
            harness.model.get_relation('db'), harness.model.app
        )
    assert isinstance(harness.model.unit.status, ops.WaitingStatus)


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_bad_set(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    harness = testing.Harness(
        charm_class, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel_id = harness.add_relation('db', 'db')
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    with pytest.raises(ValueError):
        harness.charm.on.update_status.emit()


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_good_set(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    harness = testing.Harness(
        charm_class, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel_id = harness.add_relation('db', 'db')
    rel = harness.model.get_relation('db', rel_id)
    assert rel is not None
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    harness.charm.on['db'].relation_joined.emit(rel, harness.model.app)
    # Check that it's in the databag object.
    obj = rel._cache._databag_obj_cache[rel_id, harness.model.app][0]
    assert obj.foo == 'newfoo'
    assert obj.bar == 42
    assert obj.baz == ['new']
    assert obj.quux.sub == 25
    # Check that it's going to Juju. We go directly to the raw data to avoid
    # hitting the bypass that would take us to the object instead. We also have
    # to manually trigger the send because Harness doesn't use _Manager.
    _charm._send_databag_to_juju(harness.charm)
    data = harness._backend._relation_data_raw[rel_id]['foo']
    assert data['foo'] == json.dumps('newfoo')
    assert data['bar'] == json.dumps(42)
    assert data['baz'] == json.dumps(['new'])
    assert data['quux'] == json.dumps({'sub': 25})


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_mix_modern_and_classic(
    charm_class: type[ops.CharmBase], request: pytest.FixtureRequest
):
    harness = testing.Harness(
        charm_class, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel_id = harness.add_relation('db', 'db')
    rel = harness.model.get_relation('db', rel_id)
    assert rel is not None
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    harness.charm.on.config_changed.emit()
    # We have to manually trigger the send because Harness doesn't use _Manager.
    _charm._send_databag_to_juju(harness.charm)
    data = harness._backend._relation_data_raw[rel_id]['foo']
    assert data['foo'] == json.dumps('two')


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_single_object(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    harness = testing.Harness(
        charm_class, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel_id = harness.add_relation('db', 'db')
    rel = harness.model.get_relation('db', rel_id)
    assert rel is not None
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    harness.charm.on.install.emit()
    assert harness.charm.data1 is harness.charm.data2  # type: ignore


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_single_object_different_databag(
    charm_class: type[ops.CharmBase], request: pytest.FixtureRequest
):
    @dataclasses.dataclass
    class OtherDatabag(ops.RelationDataBase):
        foo: str = 'foo'

    class BadCharmClass(charm_class):
        def _on_install(self, _: ops.InstallEvent):
            rel = self.model.get_relation('db')
            assert rel is not None
            self.data1 = rel.load(self.databag_class, self.app)  # type: ignore
            rel = self.model.get_relation('db')
            assert rel is not None
            self.data2 = rel.load(OtherDatabag, self.app)

    harness = testing.Harness(
        BadCharmClass, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': json.dumps('value'), 'bar': json.dumps(1), 'baz': json.dumps(['a', 'b'])}
    rel_id = harness.add_relation('db', 'db')
    rel = harness.model.get_relation('db', rel_id)
    assert rel is not None
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    with pytest.raises(TypeError):
        harness.charm.on.install.emit()


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_no_encode(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    class NoEncodeCharm(charm_class):
        def _on_relation_changed(self, event: ops.RelationChangedEvent):
            data = event.relation.load(  # type: ignore
                self.databag_class,  # type: ignore
                self.app,
                encoder=lambda x: x,
                decoder=lambda x: x,
            )
            data = cast('DatabagProtocol', data)
            data.foo = data.foo + '1'

    harness = testing.Harness(
        NoEncodeCharm, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': 'value'}
    rel_id = harness.add_relation('db', 'db')
    rel = harness.model.get_relation('db', rel_id)
    assert rel is not None
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    harness.charm.on['db'].relation_changed.emit(
        harness.model.get_relation('db'), harness.model.app
    )
    rel = harness.model.get_relation('db')
    assert rel is not None
    obj = rel._cache._databag_obj_cache[rel_id, harness.model.app][0]
    assert obj.foo == 'value1'


@pytest.mark.parametrize('charm_class', _test_classes)
def test_databag_custom_encode(charm_class: type[ops.CharmBase], request: pytest.FixtureRequest):
    class AlternateEncodeCharm(charm_class):
        @staticmethod
        def custom_encode(data: Any) -> Any:
            if hasattr(data, 'upper'):
                return data.upper()
            return data

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
            data = event.relation.load(  # type: ignore
                self.databag_class,  # type: ignore
                self.app,
                encoder=self.encoder,
                decoder=self.decoder,
            )
            data = cast('DatabagProtocol', data)
            data.foo = data.foo + '1'

    harness = testing.Harness(
        AlternateEncodeCharm, meta="""name: foo\nrequires:\n  db:\n    interface: db-int"""
    )
    request.addfinalizer(harness.cleanup)
    data = {'foo': 'value'}
    rel_id = harness.add_relation('db', 'db')
    rel = harness.model.get_relation('db', rel_id)
    assert rel is not None
    harness.set_leader(True)
    harness.begin()
    harness.update_relation_data(rel_id, 'foo', data)
    harness.charm.on['db'].relation_changed.emit(
        harness.model.get_relation('db'), harness.model.app
    )
    rel = harness.model.get_relation('db')
    assert rel is not None
    obj = rel._cache._databag_obj_cache[rel_id, harness.model.app][0]
    assert obj.foo == 'eulav1'
    # We have to manually trigger the send because Harness doesn't use _Manager.
    _charm._send_databag_to_juju(harness.charm)
    data = harness._backend._relation_data_raw[rel_id]['foo']
    assert data['foo'] == 'EULAV1'


# TODO: pydantic model with pydantic types that need to serialise down to a string
# TODO: Add back some Scenario tests.
# TODO: Add a test that verifies that the order of dictionary keys does not change
# on read then write (this would trigger relation-changed unnecessarily).
# TODO: add a test that has the common Pydantic types: AnyHttpUrl or HttpUrl,
# IPvAnyAddress (ipaddress.IPv4Address|ipaddress.IPv6Address) for non-Pydantic, IPvAnyNetwork.
# TODO: add a test that uses enums.
# TODO: add a test that validates a combination of fields.
# TODO: add in support for Scenario automatically JSON'ing the relation content.
