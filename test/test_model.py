# Copyright 2019 Canonical Ltd.
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

import datetime
import io
import ipaddress
import json
import os
import pathlib
import re
import tempfile
import typing
import unittest
from collections import OrderedDict
from textwrap import dedent
from unittest.mock import ANY, MagicMock, patch

import pytest

import ops
import ops.testing
from ops import pebble
from ops._private import yaml
from ops.jujucontext import _JujuContext
from ops.jujuversion import JujuVersion
from ops.model import _ModelBackend
from test.test_helpers import FakeScript


@pytest.fixture
def fake_script(request: pytest.FixtureRequest) -> FakeScript:
    return FakeScript(request)


class TestModel:
    @pytest.fixture
    def harness(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: myapp
            provides:
              db0:
                interface: db0
            requires:
              db1:
                interface: db1
            peers:
              db2:
                interface: db2
            resources:
              foo: {type: file, filename: foo.txt}
              bar: {type: file, filename: bar.txt}
        """,
            config="""
        options:
            foo:
                type: string
            bar:
                type: int
            qux:
                type: boolean
            baz:
                type: float
            secretfoo:
                type: secret
        """,
        )
        yield harness
        harness.cleanup()

    def ensure_relation(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        name: str = 'db1',
        relation_id: typing.Optional[int] = None,
    ) -> ops.Relation:
        """Wrapper around harness.model.get_relation that enforces that None is not returned."""
        rel_db1 = harness.model.get_relation(name, relation_id)
        assert rel_db1 is not None
        assert rel_db1 is not None  # Type checkers understand this, but not the previous line.
        return rel_db1

    def test_model_attributes(self, harness: ops.testing.Harness[ops.CharmBase]):
        assert harness.model.app is harness.model.unit.app
        assert harness.model.name is None

    def test_unit_immutable(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(AttributeError):
            harness.model.unit = object()  # type: ignore

    def test_app_immutable(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(AttributeError):
            harness.model.app = object()  # type: ignore

    def test_model_name_from_backend(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.set_model_name('default')
        m = ops.Model(ops.CharmMeta(), harness._backend)
        assert m.name == 'default'
        with pytest.raises(AttributeError):
            m.name = 'changes-disallowed'  # type: ignore

    def test_relations_keys(self, harness: ops.testing.Harness[ops.CharmBase]):
        rel_app1 = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(rel_app1, 'remoteapp1/0')
        harness.add_relation_unit(rel_app1, 'remoteapp1/1')
        rel_app2 = harness.add_relation('db1', 'remoteapp2')
        harness.add_relation_unit(rel_app2, 'remoteapp2/0')

        # We invalidate db1 so that it causes us to reload it
        harness.model.relations._invalidate('db1')
        self.resetBackendCalls(harness)
        for relation in harness.model.relations['db1']:
            assert harness.model.unit in relation.data
            unit_from_rel = next(filter(lambda u: u.name == 'myapp/0', relation.data.keys()))
            assert harness.model.unit is unit_from_rel

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', rel_app1),
                ('relation_list', rel_app2),
            ],
        )

    def test_relations_immutable(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(AttributeError):
            harness.model.relations = {}  # type: ignore

    def test_get_relation(self, harness: ops.testing.Harness[ops.CharmBase]):
        # one relation on db1
        # two relations on db0
        # no relations on db2
        relation_id_db0 = harness.add_relation('db0', 'db')
        harness._get_backend_calls(reset=True)

        relation_id_db1 = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(relation_id_db1, 'remoteapp1/0')
        relation_id_db0_b = harness.add_relation('db0', 'another')
        self.resetBackendCalls(harness)

        with pytest.raises(ops.ModelError):
            # You have to specify it by just the integer ID
            harness.model.get_relation('db1', f'db1:{relation_id_db1}')  # type: ignore
        rel_db1 = harness.model.get_relation('db1', relation_id_db1)
        assert isinstance(rel_db1, ops.Relation)
        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id_db1),
            ],
        )
        dead_rel = self.ensure_relation(harness, 'db1', 7)
        assert isinstance(dead_rel, ops.Relation)
        assert set(dead_rel.data.keys()) == {harness.model.unit, harness.model.unit.app}
        assert dead_rel.data[harness.model.unit] == {}
        self.assertBackendCalls(
            harness,
            [
                ('relation_list', 7),
                ('relation_remote_app_name', 7),
                ('relation_get', 7, 'myapp/0', False),
            ],
        )

        assert harness.model.get_relation('db2') is None
        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db2'),
            ],
        )
        assert harness.model.get_relation('db1') is rel_db1
        with pytest.raises(ops.TooManyRelatedAppsError):
            harness.model.get_relation('db0')

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db0'),
                ('relation_list', relation_id_db0),
                ('relation_remote_app_name', 0),
                ('relation_list', relation_id_db0_b),
                ('relation_remote_app_name', 2),
            ],
        )

    def test_peer_relation_app(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_relation('db2', 'myapp')
        rel_dbpeer = self.ensure_relation(harness, 'db2')
        assert rel_dbpeer.app is harness.model.app

    def test_remote_units_is_our(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.add_relation_unit(relation_id, 'remoteapp1/1')
        self.resetBackendCalls(harness)

        for u in self.ensure_relation(harness, 'db1').units:
            assert not u._is_our_unit
            assert not u.app._is_our_app

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
            ],
        )

    def test_our_unit_is_our(self, harness: ops.testing.Harness[ops.CharmBase]):
        assert harness.model.unit._is_our_unit
        assert harness.model.unit.app._is_our_app

    def test_invalid_type_relation_data(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(relation_id, 'remoteapp1/0')

        with pytest.raises(ops.RelationDataError):
            with harness._event_context('foo_event'):
                harness.update_relation_data(relation_id, 'remoteapp1/0', {42: 'remoteapp1-0'})  # type: ignore

        with pytest.raises(ops.RelationDataError):
            with harness._event_context('foo_event'):
                harness.update_relation_data(relation_id, 'remoteapp1/0', {'foo': 42})  # type: ignore

    def test_get_app_relation_data(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.begin()
        relation_id = harness.add_relation('db1', 'remote')
        harness.add_relation_unit(relation_id, 'remote/0')
        local_app = harness.model.app.name
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, local_app, {'foo': 'bar'})
            assert (
                harness.get_relation_data(relation_id, harness.model.app)
                == harness.get_relation_data(relation_id, local_app)
                == {'foo': 'bar'}
            )

    @pytest.mark.parametrize(
        'args,kwargs', [(({'foo': 'baz'},), {}), (([('foo', 'baz')],), {}), ((), {'foo': 'baz'})]
    )
    def test_update_app_relation_data(
        self,
        args: typing.Tuple[typing.Any, ...],
        kwargs: typing.Dict[str, str],
        harness: ops.testing.Harness[ops.CharmBase],
    ):
        harness.set_leader(True)
        harness.begin()
        relation_id = harness.add_relation('db1', 'remote')
        harness.add_relation_unit(relation_id, 'remote/0')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, harness.model.app.name, {'foo': 'bar'})
            rel = harness.model.get_relation('db1', relation_id)
            assert rel is not None
            rel.data[harness.model.app].update(*args, **kwargs)
            assert harness.get_relation_data(relation_id, harness.model.app) == {'foo': 'baz'}

    def test_unit_relation_data(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, 'remoteapp1/0', {'host': 'remoteapp1-0'})
        harness.model.relations._invalidate('db1')
        self.resetBackendCalls(harness)

        random_unit = harness.model.get_unit('randomunit/0')
        with pytest.raises(KeyError):
            self.ensure_relation(harness, 'db1').data[random_unit]
        remoteapp1_0 = next(
            filter(lambda u: u.name == 'remoteapp1/0', self.ensure_relation(harness, 'db1').units)
        )
        assert self.ensure_relation(harness, 'db1').data[remoteapp1_0] == {'host': 'remoteapp1-0'}

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('relation_get', relation_id, 'remoteapp1/0', False),
            ],
        )

    def test_remote_app_relation_data(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, 'remoteapp1', {'secret': 'cafedeadbeef'})
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.add_relation_unit(relation_id, 'remoteapp1/1')
        self.resetBackendCalls(harness)

        rel_db1 = self.ensure_relation(harness, 'db1')
        # Try to get relation data for an invalid remote application.
        random_app = harness.model._cache.get(ops.Application, 'randomapp')
        with pytest.raises(KeyError):
            rel_db1.data[random_app]

        remoteapp1 = rel_db1.app
        assert remoteapp1 is not None
        assert remoteapp1.name == 'remoteapp1'
        assert rel_db1.data[remoteapp1] == {'secret': 'cafedeadbeef'}

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('relation_get', relation_id, 'remoteapp1', True),
            ],
        )

    def test_relation_data_modify_remote(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, 'remoteapp1', {'secret': 'cafedeadbeef'})
            harness.add_relation_unit(relation_id, 'remoteapp1/0')
            harness.update_relation_data(relation_id, 'remoteapp1/0', {'host': 'remoteapp1/0'})
        harness.model.relations._invalidate('db1')
        self.resetBackendCalls(harness)

        rel_db1 = self.ensure_relation(harness, 'db1')
        remoteapp1_0 = next(
            filter(lambda u: u.name == 'remoteapp1/0', self.ensure_relation(harness, 'db1').units)
        )
        # Force memory cache to be loaded.
        assert 'host' in rel_db1.data[remoteapp1_0]
        assert repr(rel_db1.data[remoteapp1_0]) == "{'host': 'remoteapp1/0'}"

        with harness._event_context('foo_event'):
            with pytest.raises(ops.RelationDataError):
                rel_db1.data[remoteapp1_0]['foo'] = 'bar'
        assert 'foo' not in rel_db1.data[remoteapp1_0]

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('relation_get', relation_id, 'remoteapp1/0', False),
            ],
        )

        # this will fire more backend calls
        with harness._event_context('foo_event'):
            data_repr = repr(rel_db1.data)
        assert data_repr == (
            '{<ops.model.Unit myapp/0>: {}, '
            '<ops.model.Application myapp>: <n/a>, '
            "<ops.model.Unit remoteapp1/0>: {'host': 'remoteapp1/0'}, "
            "<ops.model.Application remoteapp1>: {'secret': 'cafedeadbeef'}}"
        )

    def test_relation_data_modify_our(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')

        harness.update_relation_data(relation_id, 'myapp/0', {'host': 'nothing'})
        self.resetBackendCalls(harness)
        with harness._event_context('foo_event'):
            rel_db1 = self.ensure_relation(harness, 'db1')
            # update_relation_data will also trigger relation-get, so we
            # invalidate the cache to ensure it will be reloaded
            rel_db1.data[harness.model.unit]._invalidate()
            # Force memory cache to be loaded.
            assert 'host' in rel_db1.data[harness.model.unit]
            rel_db1.data[harness.model.unit]['host'] = 'bar'
            assert rel_db1.data[harness.model.unit]['host'] == 'bar'

        self.assertBackendCalls(
            harness,
            [
                ('relation_get', relation_id, 'myapp/0', False),
                ('update_relation_data', relation_id, harness.model.unit, 'host', 'bar'),
            ],
        )

    def test_app_relation_data_modify_local_as_leader(
        self, harness: ops.testing.Harness[ops.CharmBase]
    ):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.update_relation_data(relation_id, 'myapp', {'password': 'deadbeefcafe'})
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.set_leader(True)
        self.resetBackendCalls(harness)

        local_app = harness.model.unit.app

        rel_db1 = self.ensure_relation(harness, 'db1')
        assert rel_db1.data[local_app] == {'password': 'deadbeefcafe'}

        rel_db1.data[local_app]['password'] = 'foo'

        assert rel_db1.data[local_app]['password'] == 'foo'

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', 0),
                ('relation_get', 0, 'myapp', True),
                ('update_relation_data', 0, harness.model.app, 'password', 'foo'),
            ],
        )

    def test_app_relation_data_modify_local_as_minion(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
    ):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.update_relation_data(relation_id, 'myapp', {'password': 'deadbeefcafe'})
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.set_leader(False)
        self.resetBackendCalls(harness)

        local_app = harness.model.unit.app

        rel_db1 = self.ensure_relation(harness, 'db1')
        assert rel_db1.data[local_app] == {'password': 'deadbeefcafe'}

        with harness._event_context('foo_event'):
            # if we were inside an event context, we'd get:
            with pytest.raises(ops.RelationDataError):
                rel_db1.data[local_app]['password'] = 'foobar'

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', 0),
                ('relation_get', 0, 'myapp', True),
                ('is_leader',),
            ],
        )

    def test_relation_data_access_peer_leader(self, harness: ops.testing.Harness[ops.CharmBase]):
        r_id = harness.add_relation('db2', 'myapp')
        harness.add_relation_unit(r_id, 'myapp/1')  # peer!
        harness.update_relation_data(r_id, 'myapp', {'foo': 'bar'})
        with harness._event_context('foo_event'):
            # leaders can read
            harness.set_leader(True)
            relation = harness.model.get_relation('db2')
            assert relation is not None and relation.app is not None
            assert relation.data[relation.app]['foo'] == 'bar'

    def test_relation_data_access_peer_minion(self, harness: ops.testing.Harness[ops.CharmBase]):
        r_id = harness.add_relation('db2', 'myapp')
        harness.add_relation_unit(r_id, 'myapp/1')  # peer!
        harness.update_relation_data(r_id, 'myapp', {'foo': 'bar'})
        with harness._event_context('foo_event'):
            # nonleaders can read
            harness.set_leader(False)
            relation = harness.model.get_relation('db2')
            assert relation is not None and relation.app is not None
            assert relation.data[relation.app]['foo'] == 'bar'

    def test_relation_data_del_key(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, 'myapp/0', {'host': 'bar'})
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls(harness)

        rel_db1 = self.ensure_relation(harness, 'db1')
        # Force memory cache to be loaded.
        assert 'host' in rel_db1.data[harness.model.unit]
        del rel_db1.data[harness.model.unit]['host']
        assert 'host' not in rel_db1.data[harness.model.unit]
        assert harness.get_relation_data(relation_id, 'myapp/0') == {}

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('relation_get', relation_id, 'myapp/0', False),
                ('update_relation_data', relation_id, harness.model.unit, 'host', ''),
            ],
        )

    def test_relation_data_del_missing_key(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, 'myapp/0', {'host': 'bar'})
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls(harness)

        rel_db1 = self.ensure_relation(harness, 'db1')
        # Force memory cache to be loaded.
        assert 'host' in rel_db1.data[harness.model.unit]
        with harness._event_context('foo_event'):
            rel_db1.data[harness.model.unit]['port'] = ''  # Same as a delete, should not fail.
        assert 'port' not in rel_db1.data[harness.model.unit]
        with harness._event_context('foo_event'):
            assert harness.get_relation_data(relation_id, 'myapp/0') == {'host': 'bar'}

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('relation_get', relation_id, 'myapp/0', False),
                ('update_relation_data', relation_id, harness.model.unit, 'port', ''),
            ],
        )

    def test_relation_set_fail(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, 'myapp/0', {'host': 'myapp-0'})
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls(harness)

        backend = harness._backend
        # TODO: jam 2020-03-06 This is way too much information about relation_set
        #       The original test forced 'relation-set' to return exit code 2,
        #       but there was nothing illegal about the data that was being set,
        #       for us to properly test the side effects of relation-set failing.

        def broken_update_relation_data(
            relation_id: int,
            entity: typing.Union[ops.Unit, ops.Application],
            key: str,
            value: str,
        ):
            backend._calls.append(('update_relation_data', relation_id, entity, key, value))
            raise ops.ModelError()

        backend.update_relation_data = broken_update_relation_data

        rel_db1 = self.ensure_relation(harness, 'db1')
        # Force memory cache to be loaded.
        assert 'host' in rel_db1.data[harness.model.unit]

        with harness._event_context('foo_event'):
            with pytest.raises(ops.ModelError):
                rel_db1.data[harness.model.unit]['host'] = 'bar'
            assert rel_db1.data[harness.model.unit]['host'] == 'myapp-0'
            with pytest.raises(ops.ModelError):
                del rel_db1.data[harness.model.unit]['host']
            assert 'host' in rel_db1.data[harness.model.unit]

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('relation_get', relation_id, 'myapp/0', False),
                ('update_relation_data', relation_id, harness.model.unit, 'host', 'bar'),
                ('update_relation_data', relation_id, harness.model.unit, 'host', ''),
            ],
        )

    def test_relation_data_type_check(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.update_relation_data(relation_id, 'myapp/0', {'host': 'myapp-0'})
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls(harness)

        rel_db1 = self.ensure_relation(harness, 'db1')
        for key, value in (
            ('foo', 1),
            ('foo', None),
            ('foo', {'foo': 'bar'}),
            (1, 'foo'),
            (None, 'foo'),
            (('foo', 'bar'), 'foo'),
            (1, 1),
            (None, None),
        ):
            with pytest.raises(ops.RelationDataError):
                with harness.framework._event_context('foo_event'):
                    rel_db1.data[harness.model.unit][key] = value  # type: ignore

        # No data has actually been changed
        assert dict(rel_db1.data[harness.model.unit]) == {'host': 'myapp-0'}

        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('relation_get', relation_id, 'myapp/0', False),
            ],
        )

    def test_relation_local_app_data_readability_leader(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
    ):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.update_relation_data(relation_id, 'remoteapp1', {'secret': 'cafedeadbeef'})
        harness.update_relation_data(relation_id, 'myapp', {'local': 'data'})

        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.update_relation_data(relation_id, 'remoteapp1/0', {'host': 'remoteapp1/0'})
        harness.model.relations._invalidate('db1')
        self.resetBackendCalls(harness)

        rel_db1 = self.ensure_relation(harness, 'db1')
        harness.begin()
        harness.set_leader(True)
        self.resetBackendCalls(harness)

        local_app = harness.charm.app
        self.resetBackendCalls(harness)

        # addressing the object is OK
        rel_db1.data[local_app]

        self.assertBackendCalls(harness, [])

        with harness._event_context('foo_event'):
            self.resetBackendCalls(harness)

            assert rel_db1.data[local_app]['local'] == 'data'

            self.assertBackendCalls(
                harness,
                [
                    ('is_leader',),
                    ('relation_get', 0, 'myapp', True),
                ],
            )

            self.resetBackendCalls(harness)

            assert repr(rel_db1.data[local_app]) == repr({'local': 'data'})

            # we don't get the data, because we're lazy
            self.assertBackendCalls(harness, [('is_leader',)])

            # as well as relation data repr() in general:
            assert isinstance(repr(rel_db1.data), str)

    def test_relation_local_app_data_readability_follower(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
    ):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        with harness._event_context('foo_event'):
            harness.update_relation_data(relation_id, 'remoteapp1', {'secret': 'cafedeadbeef'})
            harness.update_relation_data(relation_id, 'myapp', {'local': 'data'})

            harness.add_relation_unit(relation_id, 'remoteapp1/0')
            harness.update_relation_data(relation_id, 'remoteapp1/0', {'host': 'remoteapp1/0'})
        harness.model.relations._invalidate('db1')
        self.resetBackendCalls(harness)

        rel_db1 = self.ensure_relation(harness, 'db1')
        harness.begin()
        harness.set_leader(False)

        local_app = harness.charm.app
        # addressing the object is OK
        rel_db1.data[local_app]
        # nonleader units cannot read their local app databag
        # attempting to read it is not
        with harness._event_context('foo_event'):
            self.resetBackendCalls(harness)

            with pytest.raises(ops.RelationDataError):
                # 'local' is there, but still:
                rel_db1.data[local_app]['local']

            # we didn't even get to relation-get
            self.assertBackendCalls(harness, [('is_leader',)])

            # we can't see it but repr() works
            assert repr(rel_db1.data[local_app]) == '<n/a>'
            self.assertBackendCalls(harness, [('is_leader',)])

            # as well as relation data repr() in general:
            assert isinstance(repr(rel_db1.data), str)

            expected_backend_calls = [
                ('relation_get', 0, 'myapp/0', False),
                ('is_leader',),
                ('relation_get', 0, 'remoteapp1/0', False),
                ('is_leader',),
                ('relation_get', 0, 'remoteapp1', True),
            ]
            self.assertBackendCalls(harness, expected_backend_calls)

    def test_relation_no_units(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.add_relation('db1', 'remoteapp1')
        rel = self.ensure_relation(harness, 'db1')
        assert rel.units == set()
        assert rel.app is harness.model.get_app('remoteapp1')
        self.assertBackendCalls(
            harness,
            [
                ('relation_ids', 'db1'),
                ('relation_list', 0),
                ('relation_remote_app_name', 0),
            ],
        )

    def test_config(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness._get_backend_calls(reset=True)
        harness.update_config({
            'foo': 'foo',
            'bar': 1,
            'qux': True,
            'baz': 3.1,
            'secretfoo': 'secret:1234',
        })
        assert harness.model.config == {
            'foo': 'foo',
            'bar': 1,
            'qux': True,
            'baz': 3.1,
            'secretfoo': 'secret:1234',
        }
        with pytest.raises(TypeError):
            # Confirm that we cannot modify config values.
            harness.model.config['foo'] = 'bar'  # type: ignore

        self.assertBackendCalls(harness, [('config_get',)])

    def test_config_immutable(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(AttributeError):
            harness.model.config = {}  # type: ignore

    def test_is_leader(self, harness: ops.testing.Harness[ops.CharmBase]):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.set_leader(True)
        self.resetBackendCalls(harness)

        def check_remote_units():
            # Cannot determine leadership for remote units.
            for u in self.ensure_relation(harness, 'db1').units:
                with pytest.raises(RuntimeError):
                    u.is_leader()

        assert harness.model.unit.is_leader()

        check_remote_units()

        # Create a new model and backend to drop a cached is-leader output.
        harness.set_leader(False)
        assert not harness.model.unit.is_leader()

        check_remote_units()

        self.assertBackendCalls(
            harness,
            [
                ('is_leader',),
                ('relation_ids', 'db1'),
                ('relation_list', relation_id),
                ('is_leader',),
            ],
        )

    def test_workload_version(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.model.unit.set_workload_version('1.2.3')
        self.assertBackendCalls(
            harness,
            [
                ('application_version_set', '1.2.3'),
            ],
        )

    def test_workload_version_invalid(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(TypeError) as excinfo:
            harness.model.unit.set_workload_version(5)  # type: ignore
        assert str(excinfo.value) == 'workload version must be a str, not int: 5'
        self.assertBackendCalls(harness, [])

    def test_resources(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(ops.ModelError):
            harness.model.resources.fetch('foo')

        harness.add_resource('foo', 'foo contents\n')
        harness.add_resource('bar', '')

        with pytest.raises(NameError):
            harness.model.resources.fetch('qux')

        assert harness.model.resources.fetch('foo').name == 'foo.txt'
        assert harness.model.resources.fetch('bar').name == 'bar.txt'

    def test_resources_immutable(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(AttributeError):
            harness.model.resources = object()  # type: ignore

    def test_pod_spec(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.set_leader(True)
        harness.model.pod.set_spec({'foo': 'bar'})
        assert harness.get_pod_spec() == ({'foo': 'bar'}, None)

        harness.model.pod.set_spec({'bar': 'foo'}, {'qux': 'baz'})
        assert harness.get_pod_spec() == ({'bar': 'foo'}, {'qux': 'baz'})

        # no leader -> no set pod spec
        harness.set_leader(False)
        with pytest.raises(ops.ModelError):
            harness.model.pod.set_spec({'foo': 'bar'})

    def test_pod_immutable(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(AttributeError):
            harness.model.pod = object()  # type: ignore

    def test_base_status_instance_raises(self):
        with pytest.raises(TypeError):
            ops.StatusBase('test')

        class NoNameStatus(ops.StatusBase):
            pass

        with pytest.raises(AttributeError):
            ops.StatusBase.register_status(NoNameStatus)  # type: ignore

    def test_status_repr(self):
        test_cases = {
            "ActiveStatus('Seashell')": ops.ActiveStatus('Seashell'),
            "MaintenanceStatus('Red')": ops.MaintenanceStatus('Red'),
            "BlockedStatus('Magenta')": ops.BlockedStatus('Magenta'),
            "WaitingStatus('Thistle')": ops.WaitingStatus('Thistle'),
            'UnknownStatus()': ops.UnknownStatus(),
        }
        for expected, status in test_cases.items():
            assert repr(status) == expected

    def test_status_eq(self):
        status_types = [
            ops.ActiveStatus,
            ops.MaintenanceStatus,
            ops.BlockedStatus,
            ops.WaitingStatus,
        ]

        assert ops.UnknownStatus() == ops.UnknownStatus()
        for i, t1 in enumerate(status_types):
            assert t1('') != ops.UnknownStatus()
            for j, t2 in enumerate(status_types):
                assert t1('one') != t2('two')
                if i == j:
                    assert t1('one') == t2('one')
                else:
                    assert t1('one') != t2('one')

    def test_active_message_default(self):
        assert ops.ActiveStatus().message == ''

    @pytest.mark.parametrize(
        'target_status,backend_call',
        [
            (
                ops.ActiveStatus('Green'),
                ('status_set', 'active', 'Green', {'is_app': False}),
            ),
            (
                ops.MaintenanceStatus('Yellow'),
                ('status_set', 'maintenance', 'Yellow', {'is_app': False}),
            ),
            (
                ops.BlockedStatus('Red'),
                ('status_set', 'blocked', 'Red', {'is_app': False}),
            ),
            (
                ops.WaitingStatus('White'),
                ('status_set', 'waiting', 'White', {'is_app': False}),
            ),
        ],
    )
    def test_local_set_valid_unit_status(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        target_status: ops.StatusBase,
        backend_call: typing.Tuple[str, str, str, typing.Dict[str, bool]],
    ):
        harness._get_backend_calls(reset=True)
        harness.model.unit.status = target_status
        assert harness.model.unit.status == target_status
        harness.model.unit._invalidate()
        assert harness.model.unit.status == target_status
        self.assertBackendCalls(harness, [backend_call, ('status_get', {'is_app': False})])

    @pytest.mark.parametrize(
        'target_status,backend_call',
        [
            (
                ops.ActiveStatus('Green'),
                ('status_set', 'active', 'Green', {'is_app': True}),
            ),
            (
                ops.MaintenanceStatus('Yellow'),
                ('status_set', 'maintenance', 'Yellow', {'is_app': True}),
            ),
            (
                ops.BlockedStatus('Red'),
                ('status_set', 'blocked', 'Red', {'is_app': True}),
            ),
            (
                ops.WaitingStatus('White'),
                ('status_set', 'waiting', 'White', {'is_app': True}),
            ),
        ],
    )
    def test_local_set_valid_app_status(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        target_status: ops.StatusBase,
        backend_call: typing.Tuple[str, str, str, typing.Dict[str, bool]],
    ):
        harness.set_leader(True)

        harness.model.app.status = target_status
        assert harness.model.app.status == target_status
        harness.model.app._invalidate()
        assert harness.model.app.status == target_status
        # There is a backend call to check if we can set the value,
        # and then another check each time we assert the status above
        expected_calls = [
            ('is_leader',),
            backend_call,
            ('is_leader',),
            ('is_leader',),
            ('status_get', {'is_app': True}),
        ]
        self.assertBackendCalls(harness, expected_calls)

    def test_set_app_status_non_leader_raises(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
    ):
        harness.set_leader(False)
        with pytest.raises(RuntimeError):
            harness.model.app.status

        with pytest.raises(RuntimeError):
            harness.model.app.status = ops.ActiveStatus()

    def test_set_unit_status_invalid(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(ops.InvalidStatusError):
            harness.model.unit.status = 'blocked'  # type: ignore

    def test_set_app_status_invalid(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(ops.InvalidStatusError):
            harness.model.app.status = 'blocked'  # type: ignore

    @pytest.mark.parametrize(
        'target_status',
        [
            ops.UnknownStatus(),
            ops.ActiveStatus('Green'),
            ops.MaintenanceStatus('Yellow'),
            ops.BlockedStatus('Red'),
            ops.WaitingStatus('White'),
        ],
    )
    def test_remote_unit_status(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        target_status: ops.StatusBase,
    ):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.add_relation_unit(relation_id, 'remoteapp1/1')
        remote_unit = next(
            filter(lambda u: u.name == 'remoteapp1/0', self.ensure_relation(harness, 'db1').units)
        )
        self.resetBackendCalls(harness)

        # Remote unit status is always unknown.
        assert remote_unit.status == ops.UnknownStatus()

        with pytest.raises(RuntimeError):
            remote_unit.status = target_status

        self.assertBackendCalls(harness, [])

    @pytest.mark.parametrize(
        'target_status',
        [
            ops.UnknownStatus(),
            ops.ActiveStatus(),
            ops.MaintenanceStatus('Upgrading software'),
            ops.BlockedStatus('Awaiting manual resolution'),
            ops.WaitingStatus('Awaiting related app updates'),
        ],
    )
    def test_remote_app_status(
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        target_status: ops.StatusBase,
    ):
        relation_id = harness.add_relation('db1', 'remoteapp1')
        harness.add_relation_unit(relation_id, 'remoteapp1/0')
        harness.add_relation_unit(relation_id, 'remoteapp1/1')
        remoteapp1 = self.ensure_relation(harness, 'db1').app
        self.resetBackendCalls(harness)

        # Remote application status is always unknown.
        assert remoteapp1 is not None
        assert isinstance(remoteapp1.status, ops.UnknownStatus)

        with pytest.raises(RuntimeError):
            remoteapp1.status = target_status

        self.assertBackendCalls(harness, [])

    def test_storage(self, fake_script: FakeScript):
        meta = ops.CharmMeta()
        raw: ops.charm._StorageMetaDict = {
            'type': 'test',
        }
        meta.storages = {
            'disks': ops.StorageMeta('test', raw),
            'data': ops.StorageMeta('test', raw),
        }
        model = ops.Model(meta, _ModelBackend('myapp/0'))

        fake_script.write(
            'storage-list',
            """
            if [ "$1" = disks ]; then
                echo '["disks/0", "disks/1"]'
            else
                echo '[]'
            fi
        """,
        )
        fake_script.write(
            'storage-get',
            """
            if [ "$2" = disks/0 ]; then
                echo '"/var/srv/disks/0"'
            elif [ "$2" = disks/1 ]; then
                echo '"/var/srv/disks/1"'
            else
                exit 2
            fi
        """,
        )
        fake_script.write('storage-add', '')

        assert len(model.storages) == 2
        assert model.storages.keys() == meta.storages.keys()
        assert 'disks' in model.storages

        with pytest.raises(KeyError, match='Did you mean'):
            model.storages['does-not-exist']

        test_cases = {
            0: {'name': 'disks', 'location': pathlib.Path('/var/srv/disks/0')},
            1: {'name': 'disks', 'location': pathlib.Path('/var/srv/disks/1')},
        }
        for storage in model.storages['disks']:
            assert storage.name == 'disks'
            assert storage.id in test_cases
            assert storage.name == test_cases[storage.id]['name']
            assert storage.location == test_cases[storage.id]['location']

        assert fake_script.calls(clear=True) == [
            ['storage-list', 'disks', '--format=json'],
            ['storage-get', '-s', 'disks/0', 'location', '--format=json'],
            ['storage-get', '-s', 'disks/1', 'location', '--format=json'],
        ]

        assert model.storages['data'] == []
        model.storages.request('data', count=3)
        assert fake_script.calls() == [
            ['storage-list', 'data', '--format=json'],
            ['storage-add', 'data=3'],
        ]

        # Try to add storage not present in charm metadata.
        with pytest.raises(ops.ModelError):
            model.storages.request('deadbeef')

        # Invalid count parameter types.
        for count_v in [None, False, 2.0, 'a', b'beef', object]:
            with pytest.raises(TypeError):
                model.storages.request('data', count_v)  # type: ignore

    def test_storages_immutable(self, harness: ops.testing.Harness[ops.CharmBase]):
        with pytest.raises(AttributeError):
            harness.model.storages = {}  # type: ignore

    def resetBackendCalls(self, harness: ops.testing.Harness[ops.CharmBase]):  # noqa: N802
        harness._get_backend_calls(reset=True)

    def assertBackendCalls(  # noqa: N802
        self,
        harness: ops.testing.Harness[ops.CharmBase],
        expected: typing.List[typing.Tuple[typing.Any, ...]],
        *,
        reset: bool = True,
    ):
        assert expected == harness._get_backend_calls(reset=reset)

    def test_run_error(self, fake_script: FakeScript):
        model = ops.Model(ops.CharmMeta(), _ModelBackend('myapp/0'))
        fake_script.write('status-get', """echo 'ERROR cannot get status' >&2; exit 1""")
        with pytest.raises(ops.ModelError) as excinfo:
            _ = model.unit.status.message
        assert str(excinfo.value) == 'ERROR cannot get status\n'
        assert excinfo.value.args[0] == 'ERROR cannot get status\n'

    @patch('grp.getgrgid')
    @patch('pwd.getpwuid')
    def test_push_path_unnamed(self, getpwuid: MagicMock, getgrgid: MagicMock):
        getpwuid.side_effect = KeyError
        getgrgid.side_effect = KeyError
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: test-app
            containers:
              foo:
                resource: foo-image
            """,
        )
        harness.begin()
        harness.set_can_connect('foo', True)
        container = harness.model.unit.containers['foo']

        with tempfile.TemporaryDirectory() as push_src:
            push_path = pathlib.Path(push_src) / 'src.txt'
            push_path.write_text('hello')
            container.push_path(push_path, '/')
        assert container.exists('/src.txt'), 'push_path failed: file "src.txt" missing'


class PushPullCase:
    """Test case for table-driven tests."""

    def __init__(
        self,
        *,
        name: str,
        path: typing.Union[str, typing.List[str]],
        files: typing.List[str],
        want: typing.Optional[typing.Set[str]] = None,
        dst: typing.Optional[str] = None,
        errors: typing.Optional[typing.Set[str]] = None,
        dirs: typing.Optional[typing.Set[str]] = None,
        want_dirs: typing.Optional[typing.Set[str]] = None,
    ):
        self.pattern = None
        self.dst = dst
        self.errors = errors or set()
        self.name = name
        self.path = path
        self.files = files
        self.dirs = dirs or set()
        self.want = want or set()
        self.want_dirs = want_dirs or set()


recursive_list_cases = [
    PushPullCase(
        name='basic recursive list',
        path='/',
        files=['/foo/bar.txt', '/baz.txt'],
        want={'/foo', '/foo/bar.txt', '/baz.txt'},
    ),
    PushPullCase(
        name='basic recursive list reverse',
        path='/',
        files=['/baz.txt', '/foo/bar.txt'],
        want={'/foo', '/foo/bar.txt', '/baz.txt'},
    ),
    PushPullCase(
        name='directly list a (non-directory) file',
        path='/baz.txt',
        files=['/baz.txt'],
        want={'/baz.txt'},
    ),
]


class ConstFileInfoArgs(typing.TypedDict):
    last_modified: datetime.datetime
    permissions: int
    size: int
    user_id: int
    user: str
    group_id: int
    group: str


@pytest.mark.parametrize('case', recursive_list_cases)
def test_recursive_list(case: PushPullCase):
    def list_func_gen(file_list: typing.List[str]):
        args: ConstFileInfoArgs = {
            'last_modified': datetime.datetime.now(),
            'permissions': 0o777,
            'size': 42,
            'user_id': 0,
            'user': 'foo',
            'group_id': 1024,
            'group': 'bar',
        }
        file_infos: typing.List[pebble.FileInfo] = []
        dirs: typing.Set[str] = set()
        for f in file_list:
            file_infos.append(
                pebble.FileInfo(
                    path=f, name=os.path.basename(f), type=pebble.FileType.FILE, **args
                )
            )

            # collect all the directories for the test case's files
            dirpath = os.path.dirname(f)
            if dirpath != '' and dirpath not in dirs:
                dirs.update(dirpath)
                file_infos.append(
                    pebble.FileInfo(
                        path=dirpath,
                        name=os.path.basename(dirpath),
                        type=pebble.FileType.DIRECTORY,
                        **args,
                    )
                )

        def inner(path: pathlib.Path):
            path_str = str(path)
            matches: typing.List[pebble.FileInfo] = []
            for info in file_infos:
                # exclude file infos for separate trees and also
                # for the directory we are listing itself - we only want its contents.
                if not info.path.startswith(path_str) or (
                    info.type == pebble.FileType.DIRECTORY and path_str == info.path
                ):
                    continue
                # exclude file infos for files that are in subdirectories of path.
                # we only want files that are directly in path.
                if info.path[len(path_str) :].find('/') > 0:
                    continue
                matches.append(info)
            return matches

        return inner

    # test raw business logic for recursion and dest path construction
    files: typing.Set[typing.Union[str, pathlib.Path]] = set()
    assert isinstance(case.path, str)
    case.path = os.path.normpath(case.path)
    case.files = [os.path.normpath(f) for f in case.files]
    case.want = {os.path.normpath(f) for f in case.want}
    for f in ops.Container._list_recursive(list_func_gen(case.files), pathlib.Path(case.path)):
        path = f.path
        if case.dst is not None:
            # test destination path construction
            _, path = f.path, ops.Container._build_destpath(f.path, case.path, case.dst)
        files.add(path)
    assert case.want == files, f'case {case.name!r} has wrong files: want {case.want}, got {files}'


recursive_push_pull_cases = [
    PushPullCase(
        name='basic push/pull',
        path='/foo',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/foo/bar.txt'},
    ),
    PushPullCase(
        name='push/pull - trailing slash',
        path='/foo/',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/foo/bar.txt'},
    ),
    PushPullCase(
        name='basic push/pull - root',
        path='/',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/foo/bar.txt'},
    ),
    PushPullCase(
        name='basic push/pull - multicomponent path',
        path='/foo/bar',
        dst='/baz',
        files=['/foo/bar/baz.txt'],
        want={'/baz/bar/baz.txt'},
    ),
    PushPullCase(
        name='push/pull contents',
        path='/foo/*',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/bar.txt'},
    ),
    PushPullCase(
        name='directly push/pull a specific file',
        path='/foo/bar.txt',
        dst='/baz',
        files=['/foo/bar.txt'],
        want={'/baz/bar.txt'},
    ),
    PushPullCase(
        name='error on push/pull non-existing file',
        path='/foo/bar.txt',
        dst='/baz',
        files=[],
        errors={'/foo/bar.txt'},
    ),
    PushPullCase(
        name='push/pull multiple non-existing files',
        path=['/foo/bar.txt', '/boo/far.txt'],
        dst='/baz',
        files=[],
        errors={'/foo/bar.txt', '/boo/far.txt'},
    ),
    PushPullCase(
        name='push/pull file and dir combo',
        path=['/foo/foobar.txt', '/foo/bar'],
        dst='/baz',
        files=['/foo/bar/baz.txt', '/foo/foobar.txt', '/quux.txt'],
        want={'/baz/foobar.txt', '/baz/bar/baz.txt'},
    ),
    PushPullCase(
        name='push/pull an empty directory',
        path='/foo',
        dst='/foobar',
        files=[],
        dirs={'/foo/baz'},
        want_dirs={'/foobar/foo/baz'},
    ),
]


@pytest.mark.parametrize('case', recursive_push_pull_cases)
def test_recursive_push_and_pull(case: PushPullCase):
    # full "integration" test of push+pull
    harness = ops.testing.Harness(
        ops.CharmBase,
        meta="""
        name: test-app
        containers:
          foo:
            resource: foo-image
        """,
    )
    harness.begin()
    harness.set_can_connect('foo', True)
    c = harness.model.unit.containers['foo']

    # create push test case filesystem structure
    push_src = tempfile.TemporaryDirectory()
    for file in case.files:
        fpath = os.path.join(push_src.name, file[1:])
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, 'w') as f:
            f.write('hello')
    if case.dirs:
        for directory in case.dirs:
            fpath = os.path.join(push_src.name, directory[1:])
            os.makedirs(fpath, exist_ok=True)

    # test push
    if isinstance(case.path, list):
        # swap slash for dummy dir on root dir so Path.parent doesn't return tmpdir path component
        # otherwise remove leading slash so we can do the path join properly.
        push_path = [
            os.path.join(push_src.name, p[1:] if len(p) > 1 else 'foo') for p in case.path
        ]
    else:
        # swap slash for dummy dir on root dir so Path.parent doesn't return tmpdir path component
        # otherwise remove leading slash so we can do the path join properly.
        push_path = os.path.join(push_src.name, case.path[1:] if len(case.path) > 1 else 'foo')

    errors: typing.Set[str] = set()
    assert case.dst is not None
    try:
        c.push_path(push_path, case.dst)
    except ops.MultiPushPullError as err:
        if not case.errors:
            raise
        errors = {src[len(push_src.name) :] for src, _ in err.errors}

    assert (
        case.errors == errors
    ), f'push_path gave wrong expected errors: want {case.errors}, got {errors}'
    for fpath in case.want:
        assert c.exists(fpath), f'push_path failed: file {fpath} missing at destination'
    for fdir in case.want_dirs:
        assert c.isdir(fdir), f'push_path failed: dir {fdir} missing at destination'

    # create pull test case filesystem structure
    pull_dst = tempfile.TemporaryDirectory()
    for fpath in case.files:
        c.push(fpath, 'hello', make_dirs=True)
    if case.dirs:
        for directory in case.dirs:
            c.make_dir(directory, make_parents=True)

    # test pull
    errors: typing.Set[str] = set()
    try:
        c.pull_path(case.path, os.path.join(pull_dst.name, case.dst[1:]))
    except ops.MultiPushPullError as err:
        if not case.errors:
            raise
        errors = {src for src, _ in err.errors}

    assert (
        case.errors == errors
    ), f'pull_path gave wrong expected errors: want {case.errors}, got {errors}'
    for fpath in case.want:
        assert c.exists(fpath), f'pull_path failed: file {fpath} missing at destination'
    for fdir in case.want_dirs:
        assert c.isdir(fdir), f'pull_path failed: dir {fdir} missing at destination'


@pytest.mark.parametrize(
    'case',
    [
        PushPullCase(
            name='push directory without trailing slash',
            path='foo',
            dst='/baz',
            files=['foo/bar/baz.txt', 'foo/foobar.txt'],
            want={'/baz/foo/foobar.txt', '/baz/foo/bar/baz.txt'},
        ),
        PushPullCase(
            name='push directory with trailing slash',
            path='foo/',
            dst='/baz',
            files=['foo/bar/baz.txt', 'foo/foobar.txt'],
            want={'/baz/foo/foobar.txt', '/baz/foo/bar/baz.txt'},
        ),
        PushPullCase(
            name='push directory relative pathing',
            path='./foo',
            dst='/baz',
            files=['foo/bar/baz.txt', 'foo/foobar.txt'],
            want={'/baz/foo/foobar.txt', '/baz/foo/bar/baz.txt'},
        ),
    ],
)
def test_push_path_relative(case: PushPullCase):
    harness = ops.testing.Harness(
        ops.CharmBase,
        meta="""
        name: test-app
        containers:
          foo:
            resource: foo-image
        """,
    )
    harness.begin()
    harness.set_can_connect('foo', True)
    container = harness.model.unit.containers['foo']

    with tempfile.TemporaryDirectory() as tmpdir:
        cwd = os.getcwd()
        # change working directory to enable relative pathing for testing
        os.chdir(tmpdir)
        try:
            # create test files under temporary test directory
            tmp = pathlib.Path(tmpdir)
            for testfile in case.files:
                testfile_path = pathlib.Path(tmp / testfile)
                testfile_path.parent.mkdir(parents=True, exist_ok=True)
                testfile_path.touch(exist_ok=True)
                testfile_path.write_text('test', encoding='utf-8')

            # push path under test to container
            assert case.dst is not None
            container.push_path(case.path, case.dst)

            # test
            for want_path in case.want:
                content = container.pull(want_path).read()
                assert content == 'test'
        finally:
            os.chdir(cwd)


class TestApplication:
    @pytest.fixture
    def harness(self):
        harness = ops.testing.Harness(
            ops.CharmBase,
            meta="""
            name: myapp
            provides:
              db0:
                interface: db0
            requires:
              db1:
                interface: db1
            peers:
              db2:
                interface: db2
            resources:
              foo: {type: file, filename: foo.txt}
              bar: {type: file, filename: bar.txt}
            containers:
              bar:
                k: v
        """,
        )
        yield harness
        harness.cleanup()

    # Tests fix for https://github.com/canonical/operator/issues/694.
    def test_mocked_get_services(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.begin()
        harness.set_can_connect('bar', True)
        c = harness.charm.unit.get_container('bar')
        c.add_layer(
            'layer1',
            {
                'summary': 'layer',
                'services': {
                    'baz': {'override': 'replace', 'summary': 'echo', 'command': 'echo 1'}
                },
            },
        )

        s = c.get_service('baz')  # So far, so good
        assert s
        assert 'baz' in c.get_services()

    def test_planned_units(self, harness: ops.testing.Harness[ops.CharmBase]):
        app = harness.model.app
        peer_rel_id = harness.add_relation('db2', 'db2')

        # Test that we always count ourself.
        assert app.planned_units() == 1

        # Add some units, and verify count.
        harness.add_relation_unit(peer_rel_id, 'myapp/1')
        harness.add_relation_unit(peer_rel_id, 'myapp/2')

        assert app.planned_units() == 3

        harness.add_relation_unit(peer_rel_id, 'myapp/3')
        assert app.planned_units() == 4

        # And remove a unit
        harness.remove_relation_unit(peer_rel_id, 'myapp/2')

        assert app.planned_units() == 3

    def test_planned_units_user_set(self, harness: ops.testing.Harness[ops.CharmBase]):
        harness.set_planned_units(1)
        app = harness.model.app
        assert app.planned_units() == 1

        harness.set_planned_units(2)
        assert app.planned_units() == 2

        harness.set_planned_units(100)
        assert app.planned_units() == 100

    def test_planned_units_garbage_values(self, harness: ops.testing.Harness[ops.CharmBase]):
        # Planned units should be a positive integer, or zero.
        with pytest.raises(TypeError):
            harness.set_planned_units(-1)
        # Verify that we didn't set our value before raising the error.
        assert harness._backend._planned_units is None
        # Verify that we still get the default value back from .planned_units.
        app = harness.model.app
        assert app.planned_units() == 1

        with pytest.raises(TypeError):
            harness.set_planned_units('foo')  # type: ignore

        with pytest.raises(TypeError):
            harness.set_planned_units(-3423000102312321090)

    def test_planned_units_override(self, harness: ops.testing.Harness[ops.CharmBase]):
        """Verify that we override the calculated value of planned_units when we set it manually.

        When a charm author writes a test that explicitly calls set_planned_units, we assume that
        their intent is to override the calculated return value. Often, this will be because the
        charm author is composing a charm without peer relations, and the harness's count of
        planned units, which is based on the number of peer relations, will not be accurate.
        """
        peer_rel_id = harness.add_relation('db2', 'db2')

        harness.set_planned_units(10)
        harness.add_relation_unit(peer_rel_id, 'myapp/1')
        harness.add_relation_unit(peer_rel_id, 'myapp/2')
        harness.add_relation_unit(peer_rel_id, 'myapp/3')

        app = harness.model.app
        assert app.planned_units() == 10

        # Verify that we can clear the override.
        harness.reset_planned_units()
        assert app.planned_units() == 4  # self + 3 peers


class TestContainers:
    @pytest.fixture
    def model(self):
        meta = ops.CharmMeta.from_yaml("""
name: k8s-charm
containers:
  c1:
    k: v
  c2:
    k: v
""")
        backend = _ModelBackend('myapp/0')
        return ops.Model(meta, backend)

    def test_unit_containers(self, model: ops.Model):
        containers = model.unit.containers
        assert sorted(containers) == ['c1', 'c2']
        assert len(containers) == 2
        assert 'c1' in containers
        assert 'c2' in containers
        assert 'c3' not in containers
        for name in ['c1', 'c2']:
            container = containers[name]
            assert isinstance(container, ops.Container)
            assert container.name == name
            assert isinstance(container.pebble, pebble.Client)
        with pytest.raises(KeyError):
            containers['c3']

        with pytest.raises(RuntimeError):
            other_unit = model.get_unit('other')
            other_unit.containers

    def test_unit_get_container(self, model: ops.Model):
        unit = model.unit
        for name in ['c1', 'c2']:
            container = unit.get_container(name)
            assert isinstance(container, ops.Container)
            assert container.name == name
            assert isinstance(container.pebble, pebble.Client)
        with pytest.raises(ops.ModelError):
            unit.get_container('c3')

        with pytest.raises(RuntimeError):
            other_unit = model.get_unit('other')
            other_unit.get_container('foo')


class TestContainerPebble:
    @pytest.fixture
    def container(self):
        meta = ops.CharmMeta.from_yaml("""
name: k8s-charm
containers:
  c1:
    k: v
""")
        backend = MockPebbleBackend('myapp/0')
        return ops.Model(meta, backend).unit.containers['c1']

    def test_socket_path(self, container: ops.Container):
        assert container.pebble.socket_path == '/charm/containers/c1/pebble.socket'

    def test_autostart(self, container: ops.Container):
        container.autostart()
        assert container.pebble.requests == [('autostart',)]  # type: ignore

    def test_replan(self, container: ops.Container):
        container.replan()
        assert container.pebble.requests == [('replan',)]  # type: ignore

    def test_can_connect(self, container: ops.Container):
        container.pebble.responses.append(pebble.SystemInfo.from_dict({'version': '1.0.0'}))  # type: ignore
        assert container.can_connect()
        assert container.pebble.requests == [('get_system_info',)]  # type: ignore

    def test_start(self, container: ops.Container):
        container.start('foo')
        container.start('foo', 'bar')
        assert container.pebble.requests == [  # type: ignore
            ('start', ('foo',)),
            ('start', ('foo', 'bar')),
        ]

    def test_start_no_arguments(self, container: ops.Container):
        with pytest.raises(TypeError):
            container.start()

    def test_stop(self, container: ops.Container):
        container.stop('foo')
        container.stop('foo', 'bar')
        assert container.pebble.requests == [  # type: ignore
            ('stop', ('foo',)),
            ('stop', ('foo', 'bar')),
        ]

    def test_stop_no_arguments(self, container: ops.Container):
        with pytest.raises(TypeError):
            container.stop()

    def test_restart(self, container: ops.Container):
        container.restart('foo')
        container.restart('foo', 'bar')
        assert container.pebble.requests == [  # type: ignore
            ('restart', ('foo',)),
            ('restart', ('foo', 'bar')),
        ]

    def test_restart_fallback(self, container: ops.Container):
        def restart_services(service_names: str):
            container.pebble.requests.append(('restart', service_names))  # type: ignore
            raise pebble.APIError({}, 400, '', '')

        container.pebble.restart_services = restart_services  # type: ignore
        # Setup the Pebble client to respond to a call to get_services()
        container.pebble.responses.append([  # type: ignore
            pebble.ServiceInfo.from_dict({
                'name': 'foo',
                'startup': 'enabled',
                'current': 'active',
            }),
            pebble.ServiceInfo.from_dict({
                'name': 'bar',
                'startup': 'enabled',
                'current': 'inactive',
            }),
        ])

        container.restart('foo', 'bar')
        assert container.pebble.requests == [  # type: ignore
            # This is the first request, which in real life fails with APIError on older versions
            ('restart', ('foo', 'bar')),
            # Next the code should loop over the started services, and stop them
            ('get_services', ('foo', 'bar')),
            ('stop', ('foo',)),
            # Then start all the specified services
            ('start', ('foo', 'bar')),
        ]

    def test_restart_fallback_non_400_error(self, container: ops.Container):
        def restart_services(service_names: str):
            raise pebble.APIError({}, 500, '', '')

        container.pebble.restart_services = restart_services  # type: ignore
        with pytest.raises(pebble.APIError) as excinfo:
            container.restart('foo')
        assert excinfo.value.code == 500

    def test_restart_no_arguments(self, container: ops.Container):
        with pytest.raises(TypeError):
            container.restart()

    def test_type_errors(self, container: ops.Container):
        meta = ops.CharmMeta.from_yaml("""
name: k8s-charm
containers:
  c1:
    k: v
""")
        # Only the real pebble Client checks types, so use actual backend class
        backend = _ModelBackend('myapp/0')
        model = ops.Model(meta, backend)
        container = model.unit.containers['c1']

        with pytest.raises(TypeError):
            container.start(['foo'])  # type: ignore

        with pytest.raises(TypeError):
            container.stop(['foo'])  # type: ignore

    def test_add_layer(self, container: ops.Container):
        container.add_layer('a', 'summary: str\n')
        container.add_layer('b', {'summary': 'dict'})
        container.add_layer('c', pebble.Layer('summary: Layer'))
        container.add_layer('d', 'summary: str\n', combine=True)
        assert container.pebble.requests == [  # type: ignore
            ('add_layer', 'a', 'summary: str\n', False),
            ('add_layer', 'b', 'summary: dict\n', False),
            ('add_layer', 'c', 'summary: Layer\n', False),
            ('add_layer', 'd', 'summary: str\n', True),
        ]

        # combine is a keyword-only arg (should be combine=True)
        with pytest.raises(TypeError):
            container.add_layer('x', {}, True)  # type: ignore

    def test_get_plan(self, container: ops.Container):
        plan_yaml = 'services:\n foo:\n  override: replace\n  command: bar'
        container.pebble.responses.append(pebble.Plan(plan_yaml))  # type: ignore
        plan = container.get_plan()
        assert container.pebble.requests == [('get_plan',)]  # type: ignore
        assert isinstance(plan, pebble.Plan)
        assert plan.to_yaml() == yaml.safe_dump(yaml.safe_load(plan_yaml))

    @staticmethod
    def _make_service(name: str, startup: str, current: str):
        return pebble.ServiceInfo.from_dict({'name': name, 'startup': startup, 'current': current})

    def test_get_services(self, container: ops.Container):
        two_services = [
            self._make_service('s1', 'enabled', 'active'),
            self._make_service('s2', 'disabled', 'inactive'),
        ]
        container.pebble.responses.append(two_services)  # type: ignore
        services = container.get_services()
        assert len(services) == 2
        assert set(services) == {'s1', 's2'}
        assert services['s1'].name == 's1'
        assert services['s1'].startup == pebble.ServiceStartup.ENABLED
        assert services['s1'].current == pebble.ServiceStatus.ACTIVE
        assert services['s2'].name == 's2'
        assert services['s2'].startup == pebble.ServiceStartup.DISABLED
        assert services['s2'].current == pebble.ServiceStatus.INACTIVE

        container.pebble.responses.append(two_services)  # type: ignore
        services = container.get_services('s1', 's2')
        assert len(services) == 2
        assert set(services) == {'s1', 's2'}
        assert services['s1'].name == 's1'
        assert services['s1'].startup == pebble.ServiceStartup.ENABLED
        assert services['s1'].current == pebble.ServiceStatus.ACTIVE
        assert services['s2'].name == 's2'
        assert services['s2'].startup == pebble.ServiceStartup.DISABLED
        assert services['s2'].current == pebble.ServiceStatus.INACTIVE

        assert container.pebble.requests == [  # type: ignore
            ('get_services', None),
            ('get_services', ('s1', 's2')),
        ]

    def test_get_service(self, container: ops.Container):
        # Single service returned successfully
        container.pebble.responses.append([self._make_service('s1', 'enabled', 'active')])  # type: ignore
        s = container.get_service('s1')
        assert container.pebble.requests == [('get_services', ('s1',))]  # type: ignore
        assert s.name == 's1'
        assert s.startup == pebble.ServiceStartup.ENABLED
        assert s.current == pebble.ServiceStatus.ACTIVE

        # If Pebble returns no services, should be a ops.ModelError
        container.pebble.responses.append([])  # type: ignore
        with pytest.raises(ops.ModelError) as excinfo:
            container.get_service('s2')
        assert str(excinfo.value) == "service 's2' not found"

        # If Pebble returns more than one service, RuntimeError is raised
        container.pebble.responses.append([  # type: ignore
            self._make_service('s1', 'enabled', 'active'),
            self._make_service('s2', 'disabled', 'inactive'),
        ])
        with pytest.raises(RuntimeError):
            container.get_service('s1')

    def test_get_checks(self, container: ops.Container):
        response_checks = [
            pebble.CheckInfo.from_dict({
                'name': 'c1',
                'status': 'up',
                'failures': 0,
                'threshold': 3,
            }),
            pebble.CheckInfo.from_dict({
                'name': 'c2',
                'level': 'alive',
                'status': 'down',
                'failures': 2,
                'threshold': 2,
            }),
        ]

        container.pebble.responses.append(response_checks)  # type: ignore
        checks = container.get_checks()
        assert len(checks) == 2
        assert checks['c1'].name == 'c1'
        assert checks['c1'].level == pebble.CheckLevel.UNSET
        assert checks['c1'].status == pebble.CheckStatus.UP
        assert checks['c1'].failures == 0
        assert checks['c1'].threshold == 3
        assert checks['c2'].name == 'c2'
        assert checks['c2'].level == pebble.CheckLevel.ALIVE
        assert checks['c2'].status == pebble.CheckStatus.DOWN
        assert checks['c2'].failures == 2
        assert checks['c2'].threshold == 2

        container.pebble.responses.append(response_checks[1:2])  # type: ignore
        checks = container.get_checks('c1', 'c2', level=pebble.CheckLevel.ALIVE)
        assert len(checks) == 1
        assert checks['c2'].name == 'c2'
        assert checks['c2'].level == pebble.CheckLevel.ALIVE
        assert checks['c2'].status == pebble.CheckStatus.DOWN
        assert checks['c2'].failures == 2
        assert checks['c2'].threshold == 2

        assert container.pebble.requests == [  # type: ignore
            ('get_checks', None, None),
            ('get_checks', pebble.CheckLevel.ALIVE, ('c1', 'c2')),
        ]

    def test_get_check(self, container: ops.Container):
        # Single check returned successfully
        container.pebble.responses.append([  # type: ignore
            pebble.CheckInfo.from_dict({
                'name': 'c1',
                'status': 'up',
                'failures': 0,
                'threshold': 3,
            })
        ])
        c = container.get_check('c1')
        assert container.pebble.requests == [('get_checks', None, ('c1',))]  # type: ignore
        assert c.name == 'c1'
        assert c.level == pebble.CheckLevel.UNSET
        assert c.status == pebble.CheckStatus.UP
        assert c.failures == 0
        assert c.threshold == 3

        # If Pebble returns no checks, should be a ops.ModelError
        container.pebble.responses.append([])  # type: ignore
        with pytest.raises(ops.ModelError) as excinfo:
            container.get_check('c2')
        assert str(excinfo.value) == "check 'c2' not found"

        # If Pebble returns more than one check, RuntimeError is raised
        container.pebble.responses.append([  # type: ignore
            pebble.CheckInfo.from_dict({
                'name': 'c1',
                'status': 'up',
                'failures': 0,
                'threshold': 3,
            }),
            pebble.CheckInfo.from_dict({
                'name': 'c2',
                'level': 'alive',
                'status': 'down',
                'failures': 2,
                'threshold': 2,
            }),
        ])
        with pytest.raises(RuntimeError):
            container.get_check('c1')

    def test_pull(self, container: ops.Container):
        container.pebble.responses.append('dummy1')  # type: ignore
        got = container.pull('/path/1')
        assert got == 'dummy1'
        assert container.pebble.requests == [  # type: ignore
            ('pull', '/path/1', 'utf-8'),
        ]
        container.pebble.requests = []  # type: ignore

        container.pebble.responses.append(b'dummy2')  # type: ignore
        got = container.pull('/path/2', encoding=None)
        assert got == b'dummy2'
        assert container.pebble.requests == [  # type: ignore
            ('pull', '/path/2', None),
        ]

    def test_push(self, container: ops.Container):
        container.push('/path/1', 'content1')
        assert container.pebble.requests == [  # type: ignore
            ('push', '/path/1', 'content1', 'utf-8', False, None, None, None, None, None),
        ]
        container.pebble.requests = []  # type: ignore

        container.push(
            '/path/2',
            b'content2',
            make_dirs=True,
            permissions=0o600,
            user_id=12,
            user='bob',
            group_id=34,
            group='staff',
        )
        assert container.pebble.requests == [  # type: ignore
            ('push', '/path/2', b'content2', 'utf-8', True, 0o600, 12, 'bob', 34, 'staff'),
        ]

    def test_list_files(self, container: ops.Container):
        container.pebble.responses.append('dummy1')  # type: ignore
        ret = container.list_files('/path/1')
        assert ret == 'dummy1'
        assert container.pebble.requests == [  # type: ignore
            ('list_files', '/path/1', None, False),
        ]
        container.pebble.requests = []  # type: ignore

        container.pebble.responses.append('dummy2')  # type: ignore
        ret = container.list_files('/path/2', pattern='*.txt', itself=True)
        assert ret == 'dummy2'
        assert container.pebble.requests == [  # type: ignore
            ('list_files', '/path/2', '*.txt', True),
        ]

    def test_make_dir(self, container: ops.Container):
        container.make_dir('/path/1')
        assert container.pebble.requests == [  # type: ignore
            ('make_dir', '/path/1', False, None, None, None, None, None),
        ]
        container.pebble.requests = []  # type: ignore

        container.make_dir(
            '/path/2',
            make_parents=True,
            permissions=0o700,
            user_id=12,
            user='bob',
            group_id=34,
            group='staff',
        )
        assert container.pebble.requests == [  # type: ignore
            ('make_dir', '/path/2', True, 0o700, 12, 'bob', 34, 'staff'),
        ]

    def test_remove_path(self, container: ops.Container):
        container.remove_path('/path/1')
        assert container.pebble.requests == [  # type: ignore
            ('remove_path', '/path/1', False),
        ]
        container.pebble.requests = []  # type: ignore

        container.remove_path('/path/2', recursive=True)
        assert container.pebble.requests == [  # type: ignore
            ('remove_path', '/path/2', True),
        ]

    def test_can_connect_simple(self, container: ops.Container):
        container.pebble.responses.append(pebble.SystemInfo.from_dict({'version': '1.0.0'}))  # type: ignore
        assert container.can_connect()

    def test_can_connect_connection_error(
        self,
        caplog: pytest.LogCaptureFixture,
        container: ops.Container,
    ):
        def raise_error():
            raise pebble.ConnectionError('connection error!')

        container.pebble.get_system_info = raise_error
        with caplog.at_level(level='DEBUG', logger='ops'):
            assert not container.can_connect()
        assert len(caplog.records) == 1
        assert re.search(r'connection error!', caplog.text)

    def test_can_connect_file_not_found_error(
        self,
        caplog: pytest.LogCaptureFixture,
        container: ops.Container,
    ):
        def raise_error():
            raise FileNotFoundError('file not found!')

        container.pebble.get_system_info = raise_error
        with caplog.at_level(level='DEBUG', logger='ops'):
            assert not container.can_connect()
        assert len(caplog.records) == 1
        assert re.search(r'file not found!', caplog.text)

    def test_can_connect_api_error(
        self,
        caplog: pytest.LogCaptureFixture,
        container: ops.Container,
    ):
        def raise_error():
            raise pebble.APIError({'body': ''}, 404, 'status', 'api error!')

        container.pebble.get_system_info = raise_error
        with caplog.at_level(level='WARNING', logger='ops'):
            assert not container.can_connect()
        assert len(caplog.records) == 1
        assert re.search(r'api error!', caplog.text)

    def test_exec(self, container: ops.Container, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(container, '_juju_version', JujuVersion('3.1.6'))
        container.pebble.responses.append('fake_exec_process')  # type: ignore
        stdout = io.StringIO('STDOUT')
        stderr = io.StringIO('STDERR')
        p = container.exec(
            ['echo', 'foo'],
            service_context='srv1',
            environment={'K1': 'V1', 'K2': 'V2'},
            working_dir='WD',
            timeout=10.5,
            user_id=1000,
            user='bob',
            group_id=1000,
            group='staff',
            stdin='STDIN',
            stdout=stdout,
            stderr=stderr,
            encoding='encoding',
            combine_stderr=True,
        )
        assert container.pebble.requests == [  # type: ignore
            (
                'exec',
                ['echo', 'foo'],
                dict(
                    service_context='srv1',
                    environment={'K1': 'V1', 'K2': 'V2'},
                    working_dir='WD',
                    timeout=10.5,
                    user_id=1000,
                    user='bob',
                    group_id=1000,
                    group='staff',
                    stdin='STDIN',
                    stdout=stdout,
                    stderr=stderr,
                    encoding='encoding',
                    combine_stderr=True,
                ),
            )
        ]
        assert p == 'fake_exec_process'

    def test_exec_service_context_not_supported(
        self, container: ops.Container, monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(container, '_juju_version', JujuVersion('3.1.5'))
        with pytest.raises(RuntimeError):
            container.exec(['foo'], service_context='srv1')

    def test_send_signal(self, container: ops.Container):
        with pytest.raises(TypeError):
            container.send_signal('SIGHUP')

        container.send_signal('SIGHUP', 's1')
        assert container.pebble.requests == [  # type: ignore
            ('send_signal', 'SIGHUP', ('s1',)),
        ]
        container.pebble.requests = []  # type: ignore

        container.send_signal('SIGHUP', 's1', 's2')
        assert container.pebble.requests == [  # type: ignore
            ('send_signal', 'SIGHUP', ('s1', 's2')),
        ]
        container.pebble.requests = []  # type: ignore

    def test_get_notice(self, container: ops.Container):
        container.pebble.responses.append(  # type: ignore
            pebble.Notice.from_dict({
                'id': '123',
                'user-id': 1000,
                'type': 'custom',
                'key': 'example.com/a',
                'first-occurred': '2023-12-07T17:01:02.123456789Z',
                'last-occurred': '2023-12-07T17:01:03.123456789Z',
                'last-repeated': '2023-12-07T17:01:04.123456789Z',
                'occurrences': 8,
            })
        )

        notice = container.get_notice('123')
        assert notice.id == '123'
        assert notice.type == pebble.NoticeType.CUSTOM
        assert notice.key == 'example.com/a'

        assert container.pebble.requests == [  # type: ignore
            ('get_notice', '123'),
        ]

    def test_get_notice_not_found(self, container: ops.Container):
        def raise_error(id: str):
            raise pebble.APIError({'body': ''}, 404, 'status', 'api error!')

        container.pebble.get_notice = raise_error
        with pytest.raises(ops.ModelError):
            container.get_notice('123')

    def test_get_notices(self, container: ops.Container):
        container.pebble.responses.append([  # type: ignore
            pebble.Notice.from_dict({
                'id': '124',
                'user-id': 1000,
                'type': 'custom',
                'key': 'example.com/b',
                'first-occurred': '2023-12-07T17:01:02.123456789Z',
                'last-occurred': '2023-12-07T17:01:03.123456789Z',
                'last-repeated': '2023-12-07T17:01:04.123456789Z',
                'occurrences': 8,
            }),
        ])

        notices = container.get_notices(
            user_id=1000,
            users=pebble.NoticesUsers.ALL,
            types=[pebble.NoticeType.CUSTOM],
            keys=['example.com/a', 'example.com/b'],
        )
        assert len(notices) == 1
        assert notices[0].id == '124'
        assert notices[0].type == pebble.NoticeType.CUSTOM
        assert notices[0].key == 'example.com/b'

        assert container.pebble.requests == [  # type: ignore
            (
                'get_notices',
                dict(
                    user_id=1000,
                    users=pebble.NoticesUsers.ALL,
                    types=[pebble.NoticeType.CUSTOM],
                    keys=['example.com/a', 'example.com/b'],
                ),
            )
        ]


class MockPebbleBackend(_ModelBackend):
    def get_pebble(self, socket_path: str):
        return MockPebbleClient(socket_path)


class MockPebbleClient:
    def __init__(self, socket_path: str):
        self.socket_path = socket_path
        self.requests: typing.List[typing.Tuple[typing.Any, ...]] = []
        self.responses: typing.List[typing.Any] = []

    def autostart_services(self):
        self.requests.append(('autostart',))

    def get_system_info(self):
        self.requests.append(('get_system_info',))
        return self.responses.pop(0)

    def replan_services(self):
        self.requests.append(('replan',))

    def start_services(self, service_names: str):
        self.requests.append(('start', service_names))

    def stop_services(self, service_names: str):
        self.requests.append(('stop', service_names))

    def restart_services(self, service_names: str):
        self.requests.append(('restart', service_names))

    def add_layer(
        self,
        label: str,
        layer: typing.Union[str, ops.pebble.LayerDict, ops.pebble.Layer],
        *,
        combine: bool = False,
    ):
        if isinstance(layer, dict):
            layer = pebble.Layer(layer).to_yaml()
        elif isinstance(layer, pebble.Layer):
            layer = layer.to_yaml()
        self.requests.append(('add_layer', label, layer, combine))

    def get_plan(self):
        self.requests.append(('get_plan',))
        return self.responses.pop(0)

    def get_services(self, names: typing.Optional[str] = None):
        self.requests.append(('get_services', names))
        return self.responses.pop(0)

    def get_checks(self, level: typing.Optional[str] = None, names: typing.Optional[str] = None):
        self.requests.append(('get_checks', level, names))
        return self.responses.pop(0)

    def pull(self, path: str, *, encoding: str = 'utf-8'):
        self.requests.append(('pull', path, encoding))
        return self.responses.pop(0)

    def push(
        self,
        path: str,
        source: 'ops.pebble._IOSource',
        *,
        encoding: str = 'utf-8',
        make_dirs: bool = False,
        permissions: typing.Optional[int] = None,
        user_id: typing.Optional[int] = None,
        user: typing.Optional[str] = None,
        group_id: typing.Optional[int] = None,
        group: typing.Optional[str] = None,
    ):
        self.requests.append((
            'push',
            path,
            source,
            encoding,
            make_dirs,
            permissions,
            user_id,
            user,
            group_id,
            group,
        ))

    def list_files(self, path: str, *, pattern: typing.Optional[str] = None, itself: bool = False):
        self.requests.append(('list_files', path, pattern, itself))
        return self.responses.pop(0)

    def make_dir(
        self,
        path: str,
        *,
        make_parents: bool = False,
        permissions: typing.Optional[int] = None,
        user_id: typing.Optional[int] = None,
        user: typing.Optional[str] = None,
        group_id: typing.Optional[int] = None,
        group: typing.Optional[str] = None,
    ):
        self.requests.append((
            'make_dir',
            path,
            make_parents,
            permissions,
            user_id,
            user,
            group_id,
            group,
        ))

    def remove_path(self, path: str, *, recursive: bool = False):
        self.requests.append(('remove_path', path, recursive))

    def exec(self, command: typing.List[str], **kwargs: typing.Any):
        self.requests.append(('exec', command, kwargs))
        return self.responses.pop(0)

    def send_signal(self, signal: typing.Union[str, int], service_names: str):
        self.requests.append(('send_signal', signal, service_names))

    def get_notice(self, id: str) -> pebble.Notice:
        self.requests.append(('get_notice', id))
        return self.responses.pop(0)

    def get_notices(self, **kwargs: typing.Any):
        self.requests.append(('get_notices', kwargs))
        return self.responses.pop(0)


class TestModelBindings:
    @pytest.fixture
    def model(self, fake_script: FakeScript):
        meta = ops.CharmMeta()
        meta.relations = {
            'db0': ops.RelationMeta(
                ops.RelationRole.provides, 'db0', {'interface': 'db0', 'scope': 'global'}
            ),
            'db1': ops.RelationMeta(
                ops.RelationRole.requires, 'db1', {'interface': 'db1', 'scope': 'global'}
            ),
            'db2': ops.RelationMeta(
                ops.RelationRole.peer, 'db2', {'interface': 'db2', 'scope': 'global'}
            ),
        }
        backend = _ModelBackend('myapp/0')
        model = ops.Model(meta, backend)

        fake_script.write('relation-ids', """([ "$1" = db0 ] && echo '["db0:4"]') || echo '[]'""")
        fake_script.write('relation-list', """[ "$2" = 4 ] && echo '["remoteapp1/0"]' || exit 2""")
        self.network_get_out = """{
  "bind-addresses": [
    {
      "mac-address": "de:ad:be:ef:ca:fe",
      "interface-name": "lo",
      "addresses": [
        {
          "hostname": "",
          "value": "192.0.2.2",
          "cidr": "192.0.2.0/24"
        },
        {
          "hostname": "deadbeef.example",
          "value": "dead:beef::1",
          "cidr": "dead:beef::/64"
        }
      ]
    },
    {
      "mac-address": "",
      "interface-name": "tun",
      "addresses": [
        {
          "hostname": "",
          "value": "192.0.3.3",
          "cidr": ""
        },
        {
          "hostname": "",
          "value": "2001:db8::3",
          "cidr": ""
        },
        {
          "hostname": "deadbeef.local",
          "value": "fe80::1:1",
          "cidr": "fe80::/64"
        }
      ]
    }
  ],
  "egress-subnets": [
    "192.0.2.2/32",
    "192.0.3.0/24",
    "dead:beef::/64",
    "2001:db8::3/128"
  ],
  "ingress-addresses": [
    "192.0.2.2",
    "192.0.3.3",
    "dead:beef::1",
    "2001:db8::3"
  ]
}"""
        return model

    def ensure_relation(
        self, model: ops.Model, name: str = 'db1', relation_id: typing.Optional[int] = None
    ):
        """Wrapper around model.get_relation that enforces that None is not returned."""
        rel_db1 = model.get_relation(name, relation_id)
        assert rel_db1 is not None, rel_db1  # Type checkers don't understand `assertIsNotNone`
        return rel_db1

    def ensure_binding(self, model: ops.Model, binding_key: typing.Union[str, ops.Relation]):
        """Wrapper around self.model.get_binding that enforces that None is not returned."""
        binding = model.get_binding(binding_key)
        assert binding is not None
        assert binding is not None  # Type checkers understand this, but not the previous line.
        return binding

    def _check_binding_data(self, binding_name: str, binding: ops.Binding):
        assert binding.name == binding_name
        assert binding.network.bind_address == ipaddress.ip_address('192.0.2.2')
        assert binding.network.ingress_address == ipaddress.ip_address('192.0.2.2')
        # /32 and /128 CIDRs are valid one-address networks for IPv{4,6}Network types respectively.
        assert binding.network.egress_subnets == [
            ipaddress.ip_network('192.0.2.2/32'),
            ipaddress.ip_network('192.0.3.0/24'),
            ipaddress.ip_network('dead:beef::/64'),
            ipaddress.ip_network('2001:db8::3/128'),
        ]

        for i, (name, address, subnet) in enumerate([
            ('lo', '192.0.2.2', '192.0.2.0/24'),
            ('lo', 'dead:beef::1', 'dead:beef::/64'),
            ('tun', '192.0.3.3', '192.0.3.3/32'),
            ('tun', '2001:db8::3', '2001:db8::3/128'),
            ('tun', 'fe80::1:1', 'fe80::/64'),
        ]):
            assert binding.network.interfaces[i].name == name
            assert binding.network.interfaces[i].address == ipaddress.ip_address(address)
            assert binding.network.interfaces[i].subnet == ipaddress.ip_network(subnet)

        for i, (name, address, subnet) in enumerate([
            ('lo', '192.0.2.2', '192.0.2.0/24'),
            ('lo', 'dead:beef::1', 'dead:beef::/64'),
            ('tun', '192.0.3.3', '192.0.3.3/32'),
            ('tun', '2001:db8::3', '2001:db8::3/128'),
            ('tun', 'fe80::1:1', 'fe80::/64'),
        ]):
            assert binding.network.interfaces[i].name == name
            assert binding.network.interfaces[i].address == ipaddress.ip_address(address)
            assert binding.network.interfaces[i].subnet == ipaddress.ip_network(subnet)

    def test_invalid_keys(self, model: ops.Model):
        # Basic validation for passing invalid keys.
        for name in (object, 0):
            with pytest.raises(ops.ModelError):
                model.get_binding(name)  # type: ignore

    def test_dead_relations(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write(
            'network-get',
            f"""
                if [ "$1" = db0 ] && [ "$2" = --format=json ]; then
                    echo '{self.network_get_out}'
                else
                    echo ERROR invalid value "$2" for option -r: relation not found >&2
                    exit 2
                fi
            """,
        )
        # Validate the behavior for dead relations.
        binding = ops.Binding('db0', 42, model._backend)
        assert binding.network.bind_address == ipaddress.ip_address('192.0.2.2')
        assert fake_script.calls(clear=True) == [
            ['network-get', 'db0', '-r', '42', '--format=json'],
            ['network-get', 'db0', '--format=json'],
        ]

    def test_broken_relations(self, fake_script: FakeScript):
        meta = ops.CharmMeta()
        meta.relations = {
            'db0': ops.RelationMeta(
                ops.RelationRole.provides, 'db0', {'interface': 'db0', 'scope': 'global'}
            ),
            'db1': ops.RelationMeta(
                ops.RelationRole.requires, 'db1', {'interface': 'db1', 'scope': 'global'}
            ),
            'db2': ops.RelationMeta(
                ops.RelationRole.peer, 'db2', {'interface': 'db2', 'scope': 'global'}
            ),
        }
        backend = _ModelBackend('myapp/0')
        model = ops.Model(meta, backend, broken_relation_id=8)
        fake_script.write(
            'relation-ids',
            """if [ "$1" = "db0" ]; then
                         echo '["db0:4"]'
                       elif [ "$1" = "db1" ]; then
                         echo '["db1:8"]'
                       elif [ "$1" = "db2" ]; then
                         echo '["db2:16"]'
                       else
                         echo '[]'
                       fi
                    """,
        )
        fake_script.write('relation-list', """echo '""'""")
        assert model.relations['db0']
        assert not model.relations['db1']
        assert model.relations['db2']

    def test_binding_by_relation_name(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write(
            'network-get', f"""[ "$1" = db0 ] && echo '{self.network_get_out}' || exit 1"""
        )
        binding_name = 'db0'
        expected_calls = [['network-get', 'db0', '--format=json']]

        binding = self.ensure_binding(model, binding_name)
        self._check_binding_data(binding_name, binding)
        assert fake_script.calls(clear=True) == expected_calls

    def test_binding_by_relation(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write(
            'network-get', f"""[ "$1" = db0 ] && echo '{self.network_get_out}' || exit 1"""
        )
        binding_name = 'db0'
        expected_calls = [
            ['relation-ids', 'db0', '--format=json'],
            # The two invocations below are due to the get_relation call.
            ['relation-list', '-r', '4', '--format=json'],
            ['network-get', 'db0', '-r', '4', '--format=json'],
        ]
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        self._check_binding_data(binding_name, binding)
        assert fake_script.calls(clear=True) == expected_calls

    def test_binding_no_iface_name(self, fake_script: FakeScript, model: ops.Model):
        network_get_out_obj = {
            'bind-addresses': [
                {
                    'mac-address': '',
                    'interface-name': '',
                    'addresses': [{'hostname': '', 'value': '10.1.89.35', 'cidr': ''}],
                }
            ],
            'egress-subnets': ['10.152.183.158/32'],
            'ingress-addresses': ['10.152.183.158'],
        }
        network_get_out = json.dumps(network_get_out_obj)
        fake_script.write(
            'network-get', f"""[ "$1" = db0 ] && echo '{network_get_out}' || exit 1"""
        )
        binding_name = 'db0'
        expected_calls = [['network-get', 'db0', '--format=json']]

        binding = self.ensure_binding(model, binding_name)
        assert binding.name == 'db0'
        assert binding.network.bind_address == ipaddress.ip_address('10.1.89.35')
        assert binding.network.ingress_address == ipaddress.ip_address('10.152.183.158')
        assert fake_script.calls(clear=True) == expected_calls

    def test_missing_bind_addresses(self, fake_script: FakeScript, model: ops.Model):
        network_data = json.dumps({})
        fake_script.write('network-get', f"""[ "$1" = db0 ] && echo '{network_data}' || exit 1""")
        binding_name = 'db0'
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        assert binding.network.interfaces == []

    def test_empty_bind_addresses(self, fake_script: FakeScript, model: ops.Model):
        network_data = json.dumps({'bind-addresses': [{}]})
        fake_script.write('network-get', f"""[ "$1" = db0 ] && echo '{network_data}' || exit 1""")
        binding_name = 'db0'
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        assert binding.network.interfaces == []

    def test_no_bind_addresses(self, fake_script: FakeScript, model: ops.Model):
        network_data = json.dumps({'bind-addresses': [{'addresses': None}]})
        fake_script.write('network-get', f"""[ "$1" = db0 ] && echo '{network_data}' || exit 1""")
        binding_name = 'db0'
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        assert binding.network.interfaces == []

    def test_empty_interface_info(self, fake_script: FakeScript, model: ops.Model):
        network_data = json.dumps({
            'bind-addresses': [
                {
                    'interface-name': 'eth0',
                    'addresses': [{}],
                }
            ],
        })
        fake_script.write('network-get', f"""[ "$1" = db0 ] && echo '{network_data}' || exit 1""")
        binding_name = 'db0'
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        assert len(binding.network.interfaces) == 1
        interface = binding.network.interfaces[0]
        assert interface.address is None
        assert interface.subnet is None

    def test_missing_ingress_addresses(self, fake_script: FakeScript, model: ops.Model):
        network_data = json.dumps({
            'bind-addresses': [],
        })
        fake_script.write('network-get', f"""[ "$1" = db0 ] && echo '{network_data}' || exit 1""")
        binding_name = 'db0'
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        assert binding.network.ingress_addresses == []
        assert binding.network.ingress_address is None

    def test_missing_egress_subnets(self, fake_script: FakeScript, model: ops.Model):
        network_data = json.dumps({
            'bind-addresses': [],
            'ingress-addresses': [],
        })
        fake_script.write('network-get', f"""[ "$1" = db0 ] && echo '{network_data}' || exit 1""")
        binding_name = 'db0'
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        assert binding.network.egress_subnets == []

    def test_unresolved_ingress_addresses(self, fake_script: FakeScript, model: ops.Model):
        # sometimes juju fails to resolve an url to an IP, in which case
        # ingress-addresses will be the 'raw' url instead of an IP.
        network_data = json.dumps({
            'ingress-addresses': ['foo.bar.baz.com'],
        })
        fake_script.write('network-get', f"""[ "$1" = db0 ] && echo '{network_data}' || exit 1""")
        binding_name = 'db0'
        binding = self.ensure_binding(model, self.ensure_relation(model, binding_name))
        assert binding.network.ingress_addresses == ['foo.bar.baz.com']


_MetricAndLabelPair = typing.Tuple[typing.Dict[str, float], typing.Dict[str, str]]


_ValidMetricsTestCase = typing.Tuple[
    typing.Mapping[str, typing.Union[int, float]],
    typing.Mapping[str, str],
    typing.List[typing.List[str]],
]


class TestModelBackend:
    @property
    def backend(self):
        backend_instance = getattr(self, '_backend', None)
        if backend_instance is None:
            os.environ['JUJU_VERSION'] = '0.0.0'
            self._backend = _ModelBackend('myapp/0')
        return self._backend

    def test_relation_get_set_is_app_arg(self):
        # No is_app provided.
        with pytest.raises(TypeError):
            self.backend.relation_set(1, 'fookey', 'barval')  # type: ignore

        with pytest.raises(TypeError):
            self.backend.relation_get(1, 'fooentity')  # type: ignore

        # Invalid types for is_app.
        for is_app_v in [None, 1, 2.0, 'a', b'beef']:
            with pytest.raises(TypeError):
                self.backend.relation_set(1, 'fookey', 'barval', is_app=is_app_v)  # type: ignore

            with pytest.raises(TypeError):
                self.backend.relation_get(1, 'fooentity', is_app=is_app_v)  # type: ignore

    def test_is_leader_refresh(self, fake_script: FakeScript):
        meta = ops.CharmMeta.from_yaml("""
            name: myapp
        """)
        model = ops.Model(meta, self.backend)
        fake_script.write('is-leader', 'echo false')
        assert not model.unit.is_leader()

        # Change the leadership status
        fake_script.write('is-leader', 'echo true')
        # If you don't force it, we don't check, so we won't see the change
        assert not model.unit.is_leader()
        # If we force a recheck, then we notice
        self.backend._leader_check_time = None
        assert model.unit.is_leader()

        # Force a recheck without changing the leadership status.
        fake_script.write('is-leader', 'echo true')
        self.backend._leader_check_time = None
        assert model.unit.is_leader()

    def test_relation_tool_errors(self, fake_script: FakeScript, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setattr(
            self.backend, '_juju_context', _JujuContext.from_dict({'JUJU_VERSION': '2.8.0'})
        )
        err_msg = 'ERROR invalid value "$2" for option -r: relation not found'

        test_cases = [
            (
                lambda: fake_script.write('relation-list', 'echo fooerror >&2 ; exit 1'),
                lambda: self.backend.relation_list(3),
                ops.ModelError,
                [['relation-list', '-r', '3', '--format=json']],
            ),
            (
                lambda: fake_script.write('relation-list', f'echo {err_msg} >&2 ; exit 2'),
                lambda: self.backend.relation_list(3),
                ops.RelationNotFoundError,
                [['relation-list', '-r', '3', '--format=json']],
            ),
            (
                lambda: fake_script.write('relation-set', 'echo fooerror >&2 ; exit 1'),
                lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=False),
                ops.ModelError,
                [['relation-set', '-r', '3', '--file', '-']],
            ),
            (
                lambda: fake_script.write('relation-set', f'echo {err_msg} >&2 ; exit 2'),
                lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=False),
                ops.RelationNotFoundError,
                [['relation-set', '-r', '3', '--file', '-']],
            ),
            (
                lambda: None,
                lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=True),
                ops.RelationNotFoundError,
                [['relation-set', '-r', '3', '--app', '--file', '-']],
            ),
            (
                lambda: fake_script.write('relation-get', 'echo fooerror >&2 ; exit 1'),
                lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
                ops.ModelError,
                [['relation-get', '-r', '3', '-', 'remote/0', '--format=json']],
            ),
            (
                lambda: fake_script.write('relation-get', f'echo {err_msg} >&2 ; exit 2'),
                lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
                ops.RelationNotFoundError,
                [['relation-get', '-r', '3', '-', 'remote/0', '--format=json']],
            ),
            (
                lambda: None,
                lambda: self.backend.relation_get(3, 'remote/0', is_app=True),
                ops.RelationNotFoundError,
                [['relation-get', '-r', '3', '-', 'remote/0', '--app', '--format=json']],
            ),
        ]

        for _, (do_fake, run, exception, calls) in enumerate(test_cases):
            do_fake()
            with pytest.raises(exception):
                run()
            assert fake_script.calls(clear=True) == calls

    @pytest.mark.parametrize('version', ['2.8.0', '2.7.0'])
    def test_relation_get_juju_version_quirks(
        self,
        fake_script: FakeScript,
        monkeypatch: pytest.MonkeyPatch,
        version: str,
    ):
        fake_script.write('relation-get', """echo '{"foo": "bar"}' """)

        # on 2.7.0+, things proceed as expected
        monkeypatch.setattr(
            self.backend, '_juju_context', _JujuContext.from_dict({'JUJU_VERSION': version})
        )
        rel_data = self.backend.relation_get(1, 'foo/0', is_app=True)
        assert rel_data == {'foo': 'bar'}
        calls = [' '.join(i) for i in fake_script.calls(clear=True)]
        assert calls == ['relation-get -r 1 - foo/0 --app --format=json']

        # before 2.7.0, it just fails (no --app support)
        monkeypatch.setattr(
            self.backend, '_juju_context', _JujuContext.from_dict({'JUJU_VERSION': '2.6.9'})
        )
        with pytest.raises(RuntimeError, match='not supported on Juju version 2.6.9'):
            self.backend.relation_get(1, 'foo/0', is_app=True)
        assert fake_script.calls() == []

    @pytest.mark.parametrize('version', ['2.8.0', '2.7.0'])
    def test_relation_set_juju_version_quirks(
        self,
        fake_script: FakeScript,
        monkeypatch: pytest.MonkeyPatch,
        version: str,
    ):
        # on 2.7.0+, things proceed as expected
        t = tempfile.NamedTemporaryFile()
        try:
            fake_script.write(
                'relation-set',
                dedent("""
                cat >> {}
                """).format(pathlib.Path(t.name).as_posix()),
            )
            monkeypatch.setattr(
                self.backend, '_juju_context', _JujuContext.from_dict({'JUJU_VERSION': version})
            )
            self.backend.relation_set(1, 'foo', 'bar', is_app=True)
            calls = [' '.join(i) for i in fake_script.calls(clear=True)]
            assert calls == ['relation-set -r 1 --app --file -']
            t.seek(0)
            content = t.read()
        finally:
            t.close()
        decoded = content.decode('utf-8').replace('\r\n', '\n')
        assert decoded == 'foo: bar\n'

        # before 2.7.0, it just fails always (no --app support)
        monkeypatch.setattr(
            self.backend, '_juju_context', _JujuContext.from_dict({'JUJU_VERSION': '2.6.9'})
        )
        with pytest.raises(RuntimeError, match='not supported on Juju version 2.6.9'):
            self.backend.relation_set(1, 'foo', 'bar', is_app=True)
        assert fake_script.calls() == []

    def test_status_get(self, fake_script: FakeScript):
        # taken from actual Juju output
        content = '{"message": "", "status": "unknown", "status-data": {}}'
        fake_script.write('status-get', f"echo '{content}'")
        s = self.backend.status_get(is_app=False)
        assert s['status'] == 'unknown'
        assert s['message'] == ''
        # taken from actual Juju output
        content = dedent("""
            {
                "application-status": {
                    "message": "installing",
                    "status": "maintenance",
                    "status-data": {},
                    "units": {
                        "uo/0": {
                            "message": "",
                            "status": "active",
                            "status-data": {}
                        }
                    }
                }
            }
            """)
        fake_script.write('status-get', f"echo '{content}'")
        s = self.backend.status_get(is_app=True)
        assert s['status'] == 'maintenance'
        assert s['message'] == 'installing'
        assert fake_script.calls(clear=True) == [
            ['status-get', '--include-data', '--application=False', '--format=json'],
            ['status-get', '--include-data', '--application=True', '--format=json'],
        ]

    def test_status_is_app_forced_kwargs(self, fake_script: FakeScript):
        fake_script.write('status-get', 'exit 1')
        fake_script.write('status-set', 'exit 1')

        test_cases = (
            lambda: self.backend.status_get(False),  # type: ignore
            lambda: self.backend.status_get(True),  # type: ignore
            lambda: self.backend.status_set('active', '', False),  # type: ignore
            lambda: self.backend.status_set('active', '', True),  # type: ignore
        )

        for case in test_cases:
            with pytest.raises(TypeError):
                case()

    def test_local_set_invalid_status(self, fake_script: FakeScript):
        # juju returns exit code 1 if you ask to set status to 'unknown' or 'error'
        meta = ops.CharmMeta.from_yaml("""
            name: myapp
        """)
        model = ops.Model(meta, self.backend)
        fake_script.write('status-set', 'exit 1')
        fake_script.write('is-leader', 'echo true')

        with pytest.raises(ops.ModelError):
            model.unit.status = ops.UnknownStatus()
        with pytest.raises(ops.ModelError):
            model.unit.status = ops.ErrorStatus()

        assert fake_script.calls(True) == [
            ['status-set', '--application=False', 'unknown', ''],
            ['status-set', '--application=False', 'error', ''],
        ]

        with pytest.raises(ops.ModelError):
            model.app.status = ops.UnknownStatus()
        with pytest.raises(ops.ModelError):
            model.app.status = ops.ErrorStatus()

        # A leadership check is needed for application status.
        assert fake_script.calls(True) == [
            ['is-leader', '--format=json'],
            ['status-set', '--application=True', 'unknown', ''],
            ['status-set', '--application=True', 'error', ''],
        ]

    @pytest.mark.parametrize('name', ['active', 'waiting', 'blocked', 'maintenance', 'error'])
    def test_local_get_status(self, fake_script: FakeScript, name: str):
        expected_cls = {
            'active': ops.ActiveStatus,
            'waiting': ops.WaitingStatus,
            'blocked': ops.BlockedStatus,
            'maintenance': ops.MaintenanceStatus,
            'error': ops.ErrorStatus,
        }

        meta = ops.CharmMeta.from_yaml("""
            name: myapp
        """)
        model = ops.Model(meta, self.backend)

        content = json.dumps({
            'message': 'foo',
            'status': name,
            'status-data': {},
        })
        fake_script.write('status-get', f"echo '{content}'")

        assert isinstance(model.unit.status, expected_cls[name])
        assert model.unit.status.name == name
        assert model.unit.status.message == 'foo'

        content = json.dumps({
            'application-status': {
                'message': 'bar',
                'status': name,
                'status-data': {},
            }
        })
        fake_script.write('status-get', f"echo '{content}'")
        fake_script.write('is-leader', 'echo true')

        assert isinstance(model.app.status, expected_cls[name])
        assert model.app.status.name == name
        assert model.app.status.message == 'bar'

    def test_status_set_is_app_not_bool_raises(self):
        for is_app_v in [None, 1, 2.0, 'a', b'beef', object]:
            with pytest.raises(TypeError):
                self.backend.status_set(ops.ActiveStatus, is_app=is_app_v)  # type: ignore

    def test_storage_tool_errors(self, fake_script: FakeScript):
        fake_script.write('storage-list', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(ops.ModelError):
            self.backend.storage_list('foobar')
        assert fake_script.calls(clear=True) == [['storage-list', 'foobar', '--format=json']]
        fake_script.write('storage-get', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(ops.ModelError):
            self.backend.storage_get('foobar', 'someattr')
        assert fake_script.calls(clear=True) == [
            ['storage-get', '-s', 'foobar', 'someattr', '--format=json']
        ]
        fake_script.write('storage-add', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(ops.ModelError):
            self.backend.storage_add('foobar', count=2)
        assert fake_script.calls(clear=True) == [['storage-add', 'foobar=2']]
        fake_script.write('storage-add', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(TypeError):
            (self.backend.storage_add('foobar', count=object),)  # type: ignore
        assert fake_script.calls(clear=True) == []
        fake_script.write('storage-add', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(TypeError):
            self.backend.storage_add('foobar', count=True)
        assert fake_script.calls(clear=True) == []

    def test_network_get(self, fake_script: FakeScript):
        network_get_out = """{
  "bind-addresses": [
    {
      "mac-address": "",
      "interface-name": "",
      "addresses": [
        {
          "hostname": "",
          "value": "192.0.2.2",
          "cidr": ""
        }
      ]
    }
  ],
  "egress-subnets": [
    "192.0.2.2/32"
  ],
  "ingress-addresses": [
    "192.0.2.2"
  ]
}"""
        fake_script.write(
            'network-get', f"""[ "$1" = deadbeef ] && echo '{network_get_out}' || exit 1"""
        )
        network_info = self.backend.network_get('deadbeef')
        assert network_info == json.loads(network_get_out)
        assert fake_script.calls(clear=True) == [['network-get', 'deadbeef', '--format=json']]

        network_info = self.backend.network_get('deadbeef', 1)
        assert network_info == json.loads(network_get_out)
        assert fake_script.calls(clear=True) == [
            ['network-get', 'deadbeef', '-r', '1', '--format=json']
        ]

    def test_network_get_errors(self, fake_script: FakeScript):
        err_no_endpoint = 'ERROR no network config found for binding "$2"'
        err_no_rel = 'ERROR invalid value "$3" for option -r: relation not found'

        test_cases = [
            (
                lambda: fake_script.write('network-get', f'echo {err_no_endpoint} >&2 ; exit 1'),
                lambda: self.backend.network_get('deadbeef'),
                ops.ModelError,
                [['network-get', 'deadbeef', '--format=json']],
            ),
            (
                lambda: fake_script.write('network-get', f'echo {err_no_rel} >&2 ; exit 2'),
                lambda: self.backend.network_get('deadbeef', 3),
                ops.RelationNotFoundError,
                [['network-get', 'deadbeef', '-r', '3', '--format=json']],
            ),
        ]
        for do_fake, run, exception, calls in test_cases:
            do_fake()
            with pytest.raises(exception):
                run()
            assert fake_script.calls(clear=True) == calls

    def test_action_get_error(self, fake_script: FakeScript):
        fake_script.write('action-get', '')
        fake_script.write('action-get', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(ops.ModelError):
            self.backend.action_get()
        calls = [['action-get', '--format=json']]
        assert fake_script.calls(clear=True) == calls

    def test_action_set_error(self, fake_script: FakeScript):
        fake_script.write('action-get', '')
        fake_script.write('action-set', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(ops.ModelError):
            self.backend.action_set(OrderedDict([('foo', 'bar'), ('dead', 'beef cafe')]))
        assert sorted(['action-set', 'dead=beef cafe', 'foo=bar']) == sorted(
            fake_script.calls(clear=True)[0]
        )

    def test_action_log_error(self, fake_script: FakeScript):
        fake_script.write('action-get', '')
        fake_script.write('action-log', 'echo fooerror >&2 ; exit 1')
        with pytest.raises(ops.ModelError):
            self.backend.action_log('log-message')
        calls = [['action-log', 'log-message']]
        assert fake_script.calls(clear=True) == calls

    def test_action_get(self, fake_script: FakeScript):
        fake_script.write('action-get', """echo '{"foo-name": "bar", "silent": false}'""")
        params = self.backend.action_get()
        assert params['foo-name'] == 'bar'
        assert not params['silent']
        assert fake_script.calls() == [['action-get', '--format=json']]

    def test_action_set(self, fake_script: FakeScript):
        fake_script.write('action-get', 'exit 1')
        fake_script.write('action-set', 'exit 0')
        self.backend.action_set({'x': 'dead beef', 'y': 1})
        assert sorted(['action-set', 'x=dead beef', 'y=1']), sorted(fake_script.calls()[0])

    def test_action_set_key_validation(self, fake_script: FakeScript):
        with pytest.raises(ValueError):
            self.backend.action_set({'X': 'dead beef', 'y': 1})
        with pytest.raises(ValueError):
            self.backend.action_set({'some&key': 'dead beef', 'y': 1})
        with pytest.raises(ValueError):
            self.backend.action_set({'someKey': 'dead beef', 'y': 1})
        with pytest.raises(ValueError):
            self.backend.action_set({'some_key': 'dead beef', 'y': 1})

    def test_action_set_nested(self, fake_script: FakeScript):
        fake_script.write('action-get', 'exit 1')
        fake_script.write('action-set', 'exit 0')
        self.backend.action_set({'a': {'b': 1, 'c': 2}, 'd': 3})
        assert sorted(['action-set', 'a.b=1', 'a.c=2', 'd=3']) == sorted(fake_script.calls()[0])

    def test_action_set_more_nested(self, fake_script: FakeScript):
        fake_script.write('action-get', 'exit 1')
        fake_script.write('action-set', 'exit 0')
        self.backend.action_set({'a': {'b': 1, 'c': 2, 'd': {'e': 3}}, 'f': 4})
        assert sorted(['action-set', 'a.b=1', 'a.c=2', 'a.d.e=3', 'f=4']) == sorted(
            fake_script.calls()[0]
        )

    def test_action_set_dotted_dict(self, fake_script: FakeScript):
        fake_script.write('action-get', 'exit 1')
        fake_script.write('action-set', 'exit 0')
        self.backend.action_set({'a.b': 1, 'a': {'c': 2}, 'd': 3})
        assert sorted(['action-set', 'a.b=1', 'a.c=2', 'd=3']) == sorted(fake_script.calls()[0])

    def test_action_set_duplicated_keys(self, fake_script: FakeScript):
        fake_script.write('action-get', 'exit 1')
        fake_script.write('action-set', 'exit 0')
        with pytest.raises(ValueError):
            self.backend.action_set({'a.b': 1, 'a': {'b': 2}, 'd': 3})
        with pytest.raises(ValueError):
            self.backend.action_set({'a': {'b': 1, 'c': 2, 'd': {'e': 3}}, 'f': 4, 'a.d.e': 'foo'})

    def test_action_fail(self, fake_script: FakeScript):
        fake_script.write('action-get', 'exit 1')
        fake_script.write('action-fail', 'exit 0')
        self.backend.action_fail('error 42')
        assert fake_script.calls() == [['action-fail', 'error 42']]

    def test_action_log(self, fake_script: FakeScript):
        fake_script.write('action-get', 'exit 1')
        fake_script.write('action-log', 'exit 0')
        self.backend.action_log('progress: 42%')
        assert fake_script.calls() == [['action-log', 'progress: 42%']]

    def test_application_version_set(self, fake_script: FakeScript):
        fake_script.write('application-version-set', 'exit 0')
        self.backend.application_version_set('1.2b3')
        assert fake_script.calls() == [['application-version-set', '--', '1.2b3']]

    def test_application_version_set_invalid(self, fake_script: FakeScript):
        fake_script.write('application-version-set', 'exit 0')
        with pytest.raises(TypeError):
            self.backend.application_version_set(2)  # type: ignore
        with pytest.raises(TypeError):
            self.backend.application_version_set()  # type: ignore
        assert fake_script.calls() == []

    def test_juju_log(self, fake_script: FakeScript):
        fake_script.write('juju-log', 'exit 0')
        self.backend.juju_log('WARNING', 'foo')
        assert fake_script.calls(clear=True) == [
            ['juju-log', '--log-level', 'WARNING', '--', 'foo']
        ]

        with pytest.raises(TypeError):
            self.backend.juju_log('DEBUG')  # type: ignore
        assert fake_script.calls(clear=True) == []

        fake_script.write('juju-log', 'exit 1')
        with pytest.raises(ops.ModelError):
            self.backend.juju_log('BAR', 'foo')
        assert fake_script.calls(clear=True) == [['juju-log', '--log-level', 'BAR', '--', 'foo']]

    def test_valid_metrics(self, fake_script: FakeScript):
        fake_script.write('add-metric', 'exit 0')
        test_cases: typing.List[_ValidMetricsTestCase] = [
            (
                OrderedDict([('foo', 42), ('b-ar', 4.5), ('ba_-z', 4.5), ('a', 1)]),
                OrderedDict([('de', 'ad'), ('be', 'ef_ -')]),
                [
                    [
                        'add-metric',
                        '--labels',
                        'de=ad,be=ef_ -',
                        'foo=42',
                        'b-ar=4.5',
                        'ba_-z=4.5',
                        'a=1',
                    ]
                ],
            ),
            (
                OrderedDict([('foo1', 0), ('b2r', 4.5)]),
                OrderedDict([('d3', 'aд'), ('b33f', '3_ -')]),
                [['add-metric', '--labels', 'd3=aд,b33f=3_ -', 'foo1=0', 'b2r=4.5']],
            ),
        ]
        for metrics, labels, expected_calls in test_cases:
            self.backend.add_metrics(metrics, labels)
            assert fake_script.calls(clear=True) == expected_calls

    def test_invalid_metric_names(self, fake_script: FakeScript):
        invalid_inputs: typing.List[_MetricAndLabelPair] = [
            ({'': 4.2}, {}),
            ({'1': 4.2}, {}),
            ({'1': -4.2}, {}),
            ({'123': 4.2}, {}),
            ({'1foo': 4.2}, {}),
            ({'-foo': 4.2}, {}),
            ({'_foo': 4.2}, {}),
            ({'foo-': 4.2}, {}),
            ({'foo_': 4.2}, {}),
            ({'a-': 4.2}, {}),
            ({'a_': 4.2}, {}),
            ({'BAЯ': 4.2}, {}),
        ]
        for metrics, labels in invalid_inputs:
            with pytest.raises(ops.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_values(self):
        invalid_inputs: typing.List[_MetricAndLabelPair] = [
            ({'a': float('+inf')}, {}),
            ({'a': float('-inf')}, {}),
            ({'a': float('nan')}, {}),
            ({'foo': 'bar'}, {}),  # type: ignore
            ({'foo': '1O'}, {}),
        ]
        for metrics, labels in invalid_inputs:
            with pytest.raises(ops.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_labels(self):
        invalid_inputs: typing.List[_MetricAndLabelPair] = [
            ({'foo': 4.2}, {'': 'baz'}),
            ({'foo': 4.2}, {',bar': 'baz'}),
            ({'foo': 4.2}, {'b=a=r': 'baz'}),
            ({'foo': 4.2}, {'BAЯ': 'baz'}),
        ]
        for metrics, labels in invalid_inputs:
            with pytest.raises(ops.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_label_values(self):
        invalid_inputs: typing.List[_MetricAndLabelPair] = [
            ({'foo': 4.2}, {'bar': ''}),
            ({'foo': 4.2}, {'bar': 'b,az'}),
            ({'foo': 4.2}, {'bar': 'b=az'}),
        ]
        for metrics, labels in invalid_inputs:
            with pytest.raises(ops.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_relation_remote_app_name_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv('JUJU_RELATION_ID', 'x:5')
        monkeypatch.setenv('JUJU_REMOTE_APP', 'remoteapp1')
        assert self.backend.relation_remote_app_name(5) == 'remoteapp1'
        os.environ['JUJU_RELATION_ID'] = '5'
        assert self.backend.relation_remote_app_name(5) == 'remoteapp1'

    def test_relation_remote_app_name_script_success(
        self, fake_script: FakeScript, monkeypatch: pytest.MonkeyPatch
    ):
        # JUJU_RELATION_ID and JUJU_REMOTE_APP both unset
        fake_script.write(
            'relation-list',
            r"""
echo '"remoteapp2"'
""",
        )
        assert self.backend.relation_remote_app_name(1) == 'remoteapp2'
        assert fake_script.calls(clear=True) == [
            ['relation-list', '-r', '1', '--app', '--format=json'],
        ]

        # JUJU_RELATION_ID set but JUJU_REMOTE_APP unset
        monkeypatch.setenv('JUJU_RELATION_ID', 'x:5')
        assert self.backend.relation_remote_app_name(5) == 'remoteapp2'

        # JUJU_RELATION_ID unset but JUJU_REMOTE_APP set
        monkeypatch.delenv('JUJU_RELATION_ID')
        os.environ['JUJU_REMOTE_APP'] = 'remoteapp1'
        assert self.backend.relation_remote_app_name(5) == 'remoteapp2'

        # Both set, but JUJU_RELATION_ID a different relation
        monkeypatch.setenv('JUJU_RELATION_ID', 'x:6')
        assert self.backend.relation_remote_app_name(5) == 'remoteapp2'

    def test_relation_remote_app_name_script_errors(self, fake_script: FakeScript):
        fake_script.write(
            'relation-list',
            r"""
echo "ERROR invalid value \"6\" for option -r: relation not found" >&2  # NOQA
exit 2
""",
        )
        assert self.backend.relation_remote_app_name(6) is None
        assert fake_script.calls(clear=True) == [
            ['relation-list', '-r', '6', '--app', '--format=json'],
        ]

        fake_script.write(
            'relation-list',
            r"""
echo "ERROR option provided but not defined: --app" >&2
exit 2
""",
        )
        assert self.backend.relation_remote_app_name(6) is None
        assert fake_script.calls(clear=True) == [
            ['relation-list', '-r', '6', '--app', '--format=json'],
        ]

    def test_planned_units(self, fake_script: FakeScript):
        # no units
        fake_script.write(
            'goal-state',
            """
echo '{"units":{}, "relations":{}}'
""",
        )
        assert self.backend.planned_units() == 0

        # only active units
        fake_script.write(
            'goal-state',
            """
echo '{
    "units":{
        "app/0": {"status":"active","since":"2023-05-23 17:05:05Z"},
        "app/1": {"status":"active","since":"2023-05-23 17:57:05Z"}
    },
    "relations": {}
}'""",
        )
        assert self.backend.planned_units() == 2

        # active and dying units
        fake_script.write(
            'goal-state',
            """
echo '{
    "units":{
        "app/0": {"status":"active","since":"2023-05-23 17:05:05Z"},
        "app/1": {"status":"dying","since":"2023-05-23 17:57:05Z"}
    },
    "relations": {}
}'""",
        )
        assert self.backend.planned_units() == 1


class TestLazyMapping:
    def test_invalidate(self):
        loaded: typing.List[int] = []

        class MyLazyMap(ops.LazyMapping):
            def _load(self):
                loaded.append(1)
                return {'foo': 'bar'}

        map = MyLazyMap()
        assert map['foo'] == 'bar'
        assert loaded == [1]
        assert map['foo'] == 'bar'
        assert loaded == [1]
        map._invalidate()
        assert map['foo'] == 'bar'
        assert loaded == [1, 1]


class TestSecrets:
    @pytest.fixture
    def model(self):
        return ops.Model(ops.CharmMeta(), _ModelBackend('myapp/0'))

    def test_app_add_secret_simple(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-add', 'echo secret:123')

        secret = model.app.add_secret({'foo': 'x'})
        assert isinstance(secret, ops.Secret)
        assert secret.id == 'secret:123'
        assert secret.label is None

        assert fake_script.calls(clear=True) == [['secret-add', '--owner', 'application', ANY]]
        assert fake_script.secrets() == {'foo': 'x'}

    def test_app_add_secret_args(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-add', 'echo secret:234')

        expire = datetime.datetime(2022, 12, 9, 16, 17, 0)
        secret = model.app.add_secret(
            {'foo': 'x', 'bar': 'y'},
            label='lbl',
            description='desc',
            expire=expire,
            rotate=ops.SecretRotate.HOURLY,
        )
        assert secret.id == 'secret:234'
        assert secret.label == 'lbl'
        assert secret.get_content() == {'foo': 'x', 'bar': 'y'}

        assert fake_script.calls(clear=True) == [
            [
                'secret-add',
                '--label',
                'lbl',
                '--description',
                'desc',
                '--expire',
                '2022-12-09T16:17:00',
                '--rotate',
                'hourly',
                '--owner',
                'application',
                ANY,
                ANY,
            ]
        ]
        assert fake_script.secrets() == {'foo': 'x', 'bar': 'y'}

    def test_unit_add_secret_simple(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-add', 'echo secret:345')

        secret = model.unit.add_secret({'foo': 'x'})
        assert isinstance(secret, ops.Secret)
        assert secret.id == 'secret:345'
        assert secret.label is None

        assert fake_script.calls(clear=True) == [['secret-add', '--owner', 'unit', ANY]]
        assert fake_script.secrets() == {'foo': 'x'}

    def test_unit_add_secret_args(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-add', 'echo secret:456')

        expire = datetime.datetime(2022, 12, 9, 16, 22, 0)
        secret = model.unit.add_secret(
            {'foo': 'w', 'bar': 'z'},
            label='l2',
            description='xyz',
            expire=expire,
            rotate=ops.SecretRotate.YEARLY,
        )
        assert secret.id == 'secret:456'
        assert secret.label == 'l2'
        assert secret.get_content() == {'foo': 'w', 'bar': 'z'}

        assert fake_script.calls(clear=True) == [
            [
                'secret-add',
                '--label',
                'l2',
                '--description',
                'xyz',
                '--expire',
                '2022-12-09T16:22:00',
                '--rotate',
                'yearly',
                '--owner',
                'unit',
                ANY,
                ANY,
            ]
        ]
        assert fake_script.secrets() == {'foo': 'w', 'bar': 'z'}

    def test_unit_add_secret_errors(self, model: ops.Model):
        # Additional add_secret tests are done in TestApplication
        errors: typing.Any = [
            ({'xy': 'bar'}, {}, ValueError),
            ({'foo': 'x'}, {'expire': 7}, TypeError),
        ]
        for content, kwargs, exc_type in errors:
            with pytest.raises(exc_type):
                model.unit.add_secret(content, **kwargs)

    def test_add_secret_errors(self, model: ops.Model):
        errors: typing.Any = [
            # Invalid content dict or types
            (None, {}, TypeError),
            ({}, {}, ValueError),
            ({b'foo', 'bar'}, {}, TypeError),
            ({3: 'bar'}, {}, TypeError),
            ({'foo': 1, 'bar': 2}, {}, TypeError),
            # Invalid content keys
            ({'xy': 'bar'}, {}, ValueError),
            ({'FOO': 'bar'}, {}, ValueError),
            ({'foo-': 'bar'}, {}, ValueError),
            ({'-foo': 'bar'}, {}, ValueError),
            # Invalid "expire" type
            ({'foo': 'x'}, {'expire': 7}, TypeError),
        ]
        for content, kwargs, exc_type in errors:
            with pytest.raises(exc_type):
                model.app.add_secret(content, **kwargs)
            with pytest.raises(exc_type):
                model.unit.add_secret(content, **kwargs)

    def test_get_secret_id(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-get', """echo '{"foo": "g"}'""")

        secret = model.get_secret(id='123')
        assert secret.id == 'secret:123'
        assert secret.label is None
        assert secret.get_content() == {'foo': 'g'}

        assert fake_script.calls(clear=True) == [['secret-get', 'secret:123', '--format=json']]

    def test_get_secret_label(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-get', """echo '{"foo": "g"}'""")

        secret = model.get_secret(label='lbl')
        assert secret.id is None
        assert secret.label == 'lbl'
        assert secret.get_content() == {'foo': 'g'}

        assert fake_script.calls(clear=True) == [['secret-get', '--label', 'lbl', '--format=json']]

    def test_get_secret_id_and_label(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-get', """echo '{"foo": "h"}'""")

        secret = model.get_secret(id='123', label='l')
        assert secret.id == 'secret:123'
        assert secret.label == 'l'
        assert secret.get_content() == {'foo': 'h'}

        assert fake_script.calls(clear=True) == [
            ['secret-get', 'secret:123', '--label', 'l', '--format=json']
        ]

    def test_get_secret_no_args(self, model: ops.Model):
        with pytest.raises(TypeError):
            model.get_secret()

    def test_get_secret_not_found(self, fake_script: FakeScript, model: ops.Model):
        script = """echo 'ERROR secret "123" not found' >&2; exit 1"""
        fake_script.write('secret-get', script)

        with pytest.raises(ops.SecretNotFoundError):
            model.get_secret(id='123')

    def test_get_secret_other_error(self, fake_script: FakeScript, model: ops.Model):
        script = """echo 'ERROR other error' >&2; exit 1"""
        fake_script.write('secret-get', script)

        with pytest.raises(ops.ModelError) as excinfo:
            model.get_secret(id='123')
        assert not isinstance(excinfo.value, ops.SecretNotFoundError)

    def test_secret_unique_identifier(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('secret-get', """echo '{"foo": "g"}'""")

        secret = model.get_secret(label='lbl')
        assert secret.id is None
        assert secret.unique_identifier is None

        secret = model.get_secret(id='123')
        assert secret.id == 'secret:123'
        assert secret.unique_identifier == '123'

        secret = model.get_secret(id='secret:124')
        assert secret.id == 'secret:124'
        assert secret.unique_identifier == '124'

        secret = model.get_secret(id='secret://modeluuid/125')
        assert secret.id == 'secret://modeluuid/125'
        assert secret.unique_identifier == '125'

        assert fake_script.calls(clear=True) == [
            ['secret-get', '--label', 'lbl', '--format=json'],
            ['secret-get', 'secret:123', '--format=json'],
            ['secret-get', 'secret:124', '--format=json'],
            ['secret-get', 'secret://modeluuid/125', '--format=json'],
        ]


class TestSecretInfo:
    def test_init(self):
        info = ops.SecretInfo(
            id='3',
            label='lbl',
            revision=7,
            expires=datetime.datetime(2022, 12, 9, 14, 10, 0),
            rotation=ops.SecretRotate.MONTHLY,
            rotates=datetime.datetime(2023, 1, 9, 14, 10, 0),
            description='desc',
        )
        assert info.id == 'secret:3'
        assert info.label == 'lbl'
        assert info.revision == 7
        assert info.expires == datetime.datetime(2022, 12, 9, 14, 10, 0)
        assert info.rotation == ops.SecretRotate.MONTHLY
        assert info.rotates == datetime.datetime(2023, 1, 9, 14, 10, 0)
        assert info.description == 'desc'

        assert repr(info).startswith('SecretInfo(')
        assert repr(info).endswith(')')

    def test_from_dict(self):
        utc = datetime.timezone.utc
        info = ops.SecretInfo.from_dict(
            'secret:4',
            {
                'label': 'fromdict',
                'revision': 8,
                'expiry': '2022-12-09T14:10:00Z',
                'rotation': 'yearly',
                'rotates': '2023-01-09T14:10:00Z',
                'description': 'desc',
            },
        )
        assert info.id == 'secret:4'
        assert info.label == 'fromdict'
        assert info.revision == 8
        assert info.expires == datetime.datetime(2022, 12, 9, 14, 10, 0, tzinfo=utc)
        assert info.rotation == ops.SecretRotate.YEARLY
        assert info.rotates == datetime.datetime(2023, 1, 9, 14, 10, 0, tzinfo=utc)
        assert info.description == 'desc'

        info = ops.SecretInfo.from_dict(
            'secret:4',
            {
                'label': 'fromdict',
                'revision': 8,
                'rotation': 'badvalue',
            },
        )
        assert info.id == 'secret:4'
        assert info.label == 'fromdict'
        assert info.revision == 8
        assert info.expires is None
        assert info.rotation is None
        assert info.rotates is None
        assert info.description is None

        info = ops.SecretInfo.from_dict('5', {'revision': 9})
        assert info.id == 'secret:5'
        assert info.revision == 9


class TestSecretClass:
    @pytest.fixture
    def model(self):
        return ops.Model(ops.CharmMeta(), _ModelBackend('myapp/0'))

    def make_secret(
        self,
        model: ops.Model,
        id: typing.Optional[str] = None,
        label: typing.Optional[str] = None,
        content: typing.Optional[typing.Dict[str, str]] = None,
    ) -> ops.Secret:
        return ops.Secret(model._backend, id=id, label=label, content=content)

    def test_id_and_label(self, model: ops.Model):
        secret = self.make_secret(model, id=' abc ', label='lbl')
        assert secret.id == 'secret:abc'
        assert secret.label == 'lbl'

        secret = self.make_secret(model, id='x')
        assert secret.id == 'secret:x'
        assert secret.label is None

        secret = self.make_secret(model, label='y')
        assert secret.id is None
        assert secret.label == 'y'

    def test_get_content_cached(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-get', """exit 1""")

        secret = self.make_secret(model, id='x', label='y', content={'foo': 'bar'})
        content = secret.get_content()  # will use cached content, not run secret-get
        assert content == {'foo': 'bar'}

        assert fake_script.calls(clear=True) == []

    def test_get_content_refresh(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-get', """echo '{"foo": "refreshed"}'""")

        secret = self.make_secret(model, id='y', content={'foo': 'bar'})
        content = secret.get_content(refresh=True)
        assert content == {'foo': 'refreshed'}

        assert fake_script.calls(clear=True) == [
            ['secret-get', 'secret:y', '--refresh', '--format=json']
        ]

    def test_get_content_uncached(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-get', """echo '{"foo": "notcached"}'""")

        secret = self.make_secret(model, id='z')
        content = secret.get_content()
        assert content == {'foo': 'notcached'}

        assert fake_script.calls(clear=True) == [['secret-get', 'secret:z', '--format=json']]

    def test_get_content_copies_dict(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-get', """echo '{"foo": "bar"}'""")

        secret = self.make_secret(model, id='z')
        content = secret.get_content()
        assert content == {'foo': 'bar'}
        content['new'] = 'value'
        assert secret.get_content() == {'foo': 'bar'}

        assert fake_script.calls(clear=True) == [['secret-get', 'secret:z', '--format=json']]

    def test_peek_content(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-get', """echo '{"foo": "peeked"}'""")

        secret = self.make_secret(model, id='a', label='b')
        content = secret.peek_content()
        assert content == {'foo': 'peeked'}

        assert fake_script.calls(clear=True) == [
            ['secret-get', 'secret:a', '--label', 'b', '--peek', '--format=json']
        ]

    def test_get_info(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-info-get', """echo '{"x": {"label": "y", "revision": 7}}'""")

        # Secret with ID only
        secret = self.make_secret(model, id='x')
        info = secret.get_info()
        assert info.id == 'secret:x'
        assert info.label == 'y'
        assert info.revision == 7

        # Secret with label only
        secret = self.make_secret(model, label='y')
        info = secret.get_info()
        assert info.id == 'secret:x'
        assert info.label == 'y'
        assert info.revision == 7

        # Secret with ID and label
        secret = self.make_secret(model, id='x', label='y')
        info = secret.get_info()
        assert info.id == 'secret:x'
        assert info.label == 'y'
        assert info.revision == 7

        assert fake_script.calls(clear=True) == [
            ['secret-info-get', 'secret:x', '--format=json'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-info-get', 'secret:x', '--format=json'],
        ]

    def test_set_content(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-set', """exit 0""")
        fake_script.write('secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(model, id='x')
        secret.set_content({'foo': 'bar'})

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(model, label='y')
        assert secret.id is None
        secret.set_content({'bar': 'foo'})
        assert secret.id == 'secret:z'

        with pytest.raises(ValueError):
            secret.set_content({'s': 't'})  # ensure it validates content (key too short)

        assert fake_script.calls(clear=True) == [
            ['secret-set', 'secret:x', ANY],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-set', 'secret:z', ANY],
        ]
        assert fake_script.secrets() == {'foo': 'bar', 'bar': 'foo'}

    def test_set_info(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-set', """exit 0""")
        fake_script.write('secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(model, id='x')
        expire = datetime.datetime(2022, 12, 9, 16, 59, 0)
        secret.set_info(
            label='lab',
            description='desc',
            expire=expire,
            rotate=ops.SecretRotate.MONTHLY,
        )

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(model, label='y')
        assert secret.id is None
        secret.set_info(label='lbl')
        assert secret.id == 'secret:z'

        assert fake_script.calls(clear=True) == [
            [
                'secret-set',
                'secret:x',
                '--label',
                'lab',
                '--description',
                'desc',
                '--expire',
                '2022-12-09T16:59:00',
                '--rotate',
                'monthly',
            ],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-set', 'secret:z', '--label', 'lbl'],
        ]

        with pytest.raises(TypeError):
            secret.set_info()  # no args provided

    def test_grant(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('relation-list', """echo '[]'""")
        fake_script.write('secret-grant', """exit 0""")
        fake_script.write('secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(model, id='x')
        backend = ops.model._ModelBackend('test', 'test', 'test')
        meta = ops.CharmMeta()
        cache = ops.model._ModelCache(meta, backend)
        unit = ops.Unit('test', meta, backend, cache)
        rel123 = ops.Relation('test', 123, True, unit, backend, cache)
        rel234 = ops.Relation('test', 234, True, unit, backend, cache)
        secret.grant(rel123)
        unit = ops.Unit('app/0', meta, backend, cache)
        secret.grant(rel234, unit=unit)

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(model, label='y')
        assert secret.id is None
        rel345 = ops.Relation('test', 345, True, unit, backend, cache)
        secret.grant(rel345)
        assert secret.id == 'secret:z'

        assert fake_script.calls(clear=True) == [
            ['relation-list', '-r', '123', '--format=json'],
            ['relation-list', '-r', '234', '--format=json'],
            ['secret-grant', 'secret:x', '--relation', '123'],
            ['secret-grant', 'secret:x', '--relation', '234', '--unit', 'app/0'],
            ['relation-list', '-r', '345', '--format=json'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-grant', 'secret:z', '--relation', '345'],
        ]

    def test_revoke(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('relation-list', """echo '[]'""")
        fake_script.write('secret-revoke', """exit 0""")
        fake_script.write('secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(model, id='x')
        unit = ops.Unit('test', ops.CharmMeta(), model._backend, model._cache)
        rel123 = ops.Relation('test', 123, True, unit, model._backend, model._cache)
        rel234 = ops.Relation('test', 234, True, unit, model._backend, model._cache)
        secret.revoke(rel123)
        unit = ops.Unit('app/0', ops.CharmMeta(), model._backend, model._cache)
        secret.revoke(rel234, unit=unit)

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(model, label='y')
        assert secret.id is None
        rel345 = ops.Relation('test', 345, True, unit, model._backend, model._cache)
        secret.revoke(rel345)
        assert secret.id == 'secret:z'

        assert fake_script.calls(clear=True) == [
            ['relation-list', '-r', '123', '--format=json'],
            ['relation-list', '-r', '234', '--format=json'],
            ['secret-revoke', 'secret:x', '--relation', '123'],
            ['secret-revoke', 'secret:x', '--relation', '234', '--unit', 'app/0'],
            ['relation-list', '-r', '345', '--format=json'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-revoke', 'secret:z', '--relation', '345'],
        ]

    def test_remove_revision(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-remove', """exit 0""")
        fake_script.write('secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(model, id='x')
        secret.remove_revision(123)

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(model, label='y')
        assert secret.id is None
        secret.remove_revision(234)
        assert secret.id == 'secret:z'

        assert fake_script.calls(clear=True) == [
            ['secret-remove', 'secret:x', '--revision', '123'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-remove', 'secret:z', '--revision', '234'],
        ]

    def test_remove_all_revisions(self, model: ops.Model, fake_script: FakeScript):
        fake_script.write('secret-remove', """exit 0""")
        fake_script.write('secret-info-get', """echo '{"z": {"label": "y", "revision": 7}}'""")

        secret = self.make_secret(model, id='x')
        secret.remove_all_revisions()

        # If secret doesn't have an ID, we'll run secret-info-get to fetch it
        secret = self.make_secret(model, label='y')
        assert secret.id is None
        secret.remove_all_revisions()
        assert secret.id == 'secret:z'

        assert fake_script.calls(clear=True) == [
            ['secret-remove', 'secret:x'],
            ['secret-info-get', '--label', 'y', '--format=json'],
            ['secret-remove', 'secret:z'],
        ]


class TestPorts:
    @pytest.fixture
    def unit(self):
        model = ops.Model(ops.charm.CharmMeta(), ops.model._ModelBackend('myapp/0'))
        return model.unit

    def test_open_port(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('open-port', 'exit 0')

        unit.open_port('tcp', 8080)
        unit.open_port('UDP', 4000)  # type: ignore
        unit.open_port('icmp')

        assert fake_script.calls(clear=True) == [
            ['open-port', '8080/tcp'],
            ['open-port', '4000/udp'],
            ['open-port', 'icmp'],
        ]

    def test_open_port_error(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('open-port', "echo 'ERROR bad protocol' >&2; exit 1")

        with pytest.raises(ops.ModelError) as excinfo:
            unit.open_port('ftp', 8080)  # type: ignore
        assert str(excinfo.value) == 'ERROR bad protocol\n'

        assert fake_script.calls(clear=True) == [
            ['open-port', '8080/ftp'],
        ]

    def test_close_port(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('close-port', 'exit 0')

        unit.close_port('tcp', 8080)
        unit.close_port('UDP', 4000)  # type: ignore
        unit.close_port('icmp')

        assert fake_script.calls(clear=True) == [
            ['close-port', '8080/tcp'],
            ['close-port', '4000/udp'],
            ['close-port', 'icmp'],
        ]

    def test_close_port_error(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('close-port', "echo 'ERROR bad protocol' >&2; exit 1")

        with pytest.raises(ops.ModelError) as excinfo:
            unit.close_port('ftp', 8080)  # type: ignore
        assert str(excinfo.value) == 'ERROR bad protocol\n'

        assert fake_script.calls(clear=True) == [
            ['close-port', '8080/ftp'],
        ]

    def test_opened_ports(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('opened-ports', """echo 8080/tcp; echo icmp""")

        ports_set = unit.opened_ports()
        assert isinstance(ports_set, set)
        ports = sorted(ports_set, key=lambda p: (p.protocol, p.port))
        assert len(ports) == 2
        assert isinstance(ports[0], ops.Port)
        assert ports[0].protocol == 'icmp'
        assert ports[0].port is None
        assert isinstance(ports[1], ops.Port)
        assert ports[1].protocol == 'tcp'
        assert ports[1].port == 8080

        assert fake_script.calls(clear=True) == [
            ['opened-ports', ''],
        ]

    def test_opened_ports_warnings(
        self, caplog: pytest.LogCaptureFixture, fake_script: FakeScript, unit: ops.Unit
    ):
        fake_script.write('opened-ports', """echo 8080/tcp; echo 1234/ftp; echo 1000-2000/udp""")

        with caplog.at_level(level='WARNING', logger='ops.model'):
            ports_set = unit.opened_ports()
        assert len(caplog.records) == 2
        assert re.search(r'.*protocol.*', caplog.records[0].message)
        assert re.search(r'.*range.*', caplog.records[1].message)

        assert isinstance(ports_set, set)
        ports = sorted(ports_set, key=lambda p: (p.protocol, p.port))
        assert len(ports) == 2
        assert isinstance(ports[0], ops.Port)
        assert ports[0].protocol == 'tcp'
        assert ports[0].port == 8080
        assert isinstance(ports[1], ops.Port)
        assert ports[1].protocol == 'udp'
        assert ports[1].port == 1000

        assert fake_script.calls(clear=True) == [
            ['opened-ports', ''],
        ]

    def test_set_ports_all_open(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('open-port', 'exit 0')
        fake_script.write('close-port', 'exit 0')
        fake_script.write('opened-ports', 'exit 0')
        unit.set_ports(8000, 8025)
        calls = fake_script.calls(clear=True)
        assert calls.pop(0) == ['opened-ports', '']
        calls.sort()  # We make no guarantee on the order the ports are opened.
        assert calls == [
            ['open-port', '8000/tcp'],
            ['open-port', '8025/tcp'],
        ]

    def test_set_ports_mixed(self, fake_script: FakeScript, unit: ops.Unit):
        # Two open ports, leave one alone and open another one.
        fake_script.write('open-port', 'exit 0')
        fake_script.write('close-port', 'exit 0')
        fake_script.write('opened-ports', 'echo 8025/tcp; echo 8028/tcp')
        unit.set_ports(ops.Port('udp', 8022), 8028)
        assert fake_script.calls(clear=True) == [
            ['opened-ports', ''],
            ['close-port', '8025/tcp'],
            ['open-port', '8022/udp'],
        ]

    def test_set_ports_replace(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('open-port', 'exit 0')
        fake_script.write('close-port', 'exit 0')
        fake_script.write('opened-ports', 'echo 8025/tcp; echo 8028/tcp')
        unit.set_ports(8001, 8002)
        calls = fake_script.calls(clear=True)
        assert calls.pop(0) == ['opened-ports', '']
        calls.sort()
        assert calls == [
            ['close-port', '8025/tcp'],
            ['close-port', '8028/tcp'],
            ['open-port', '8001/tcp'],
            ['open-port', '8002/tcp'],
        ]

    def test_set_ports_close_all(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('open-port', 'exit 0')
        fake_script.write('close-port', 'exit 0')
        fake_script.write('opened-ports', 'echo 8022/udp')
        unit.set_ports()
        assert fake_script.calls(clear=True) == [
            ['opened-ports', ''],
            ['close-port', '8022/udp'],
        ]

    def test_set_ports_noop(self, fake_script: FakeScript, unit: ops.Unit):
        fake_script.write('open-port', 'exit 0')
        fake_script.write('close-port', 'exit 0')
        fake_script.write('opened-ports', 'echo 8000/tcp')
        unit.set_ports(ops.Port('tcp', 8000))
        assert fake_script.calls(clear=True) == [
            ['opened-ports', ''],
        ]


class TestUnit:
    def test_reboot(self, fake_script: FakeScript):
        model = ops.model.Model(ops.charm.CharmMeta(), ops.model._ModelBackend('myapp/0'))
        unit = model.unit
        fake_script.write('juju-reboot', 'exit 0')
        unit.reboot()
        assert fake_script.calls(clear=True) == [
            ['juju-reboot', ''],
        ]
        with pytest.raises(SystemExit):
            unit.reboot(now=True)
        assert fake_script.calls(clear=True) == [
            ['juju-reboot', '--now'],
        ]

        with pytest.raises(RuntimeError):
            model.get_unit('other').reboot()
        with pytest.raises(RuntimeError):
            model.get_unit('other').reboot(now=True)


class TestLazyNotice:
    def test_lazy_notice(self):
        calls = 0
        timestamp = datetime.datetime.now()

        class FakeWorkload:
            def get_notice(self, id: str):
                nonlocal calls
                calls += 1
                return ops.pebble.Notice(
                    id=id,
                    user_id=1000,
                    type=ops.pebble.NoticeType.CUSTOM,
                    key='example.com/a',
                    first_occurred=timestamp,
                    last_occurred=timestamp,
                    last_repeated=timestamp,
                    occurrences=7,
                    last_data={'key': 'val'},
                )

        workload = typing.cast(ops.Container, FakeWorkload())
        n = ops.model.LazyNotice(workload, '123', 'custom', 'example.com/a')
        assert n.id == '123'
        assert n.type == ops.pebble.NoticeType.CUSTOM
        assert n.key == 'example.com/a'
        assert calls == 0

        assert n.occurrences == 7
        assert calls == 1

        assert n.user_id == 1000
        assert n.last_data == {'key': 'val'}
        assert calls == 1

        with pytest.raises(AttributeError):
            assert n.not_exist

    def test_repr(self):
        workload = typing.cast(ops.Container, None)
        n = ops.model.LazyNotice(workload, '123', 'custom', 'example.com/a')
        assert repr(n) == "LazyNotice(id='123', type=NoticeType.CUSTOM, key='example.com/a')"

        n = ops.model.LazyNotice(workload, '123', 'foobar', 'example.com/a')
        assert repr(n) == "LazyNotice(id='123', type='foobar', key='example.com/a')"


class TestCloudCredential:
    def test_from_dict(self):
        d = {
            'auth-type': 'certificate',
        }
        cloud_cred = ops.CloudCredential.from_dict(d)
        assert cloud_cred.auth_type == d['auth-type']
        assert cloud_cred.attributes == {}
        assert cloud_cred.redacted == []

    def test_from_dict_full(self):
        d = {
            'auth-type': 'certificate',
            'attrs': {'client-cert': 'foo', 'client-key': 'bar', 'server-cert': 'baz'},
            'redacted': ['foo'],
        }
        cloud_cred = ops.CloudCredential.from_dict(d)
        assert cloud_cred.auth_type == d['auth-type']
        assert cloud_cred.attributes == d['attrs']
        assert cloud_cred.redacted == d['redacted']


class TestCloudSpec:
    def test_from_dict(self):
        cloud_spec = ops.CloudSpec.from_dict({
            'type': 'lxd',
            'name': 'localhost',
        })
        assert cloud_spec.type == 'lxd'
        assert cloud_spec.name == 'localhost'
        assert cloud_spec.region is None
        assert cloud_spec.endpoint is None
        assert cloud_spec.identity_endpoint is None
        assert cloud_spec.storage_endpoint is None
        assert cloud_spec.credential is None
        assert cloud_spec.ca_certificates == []
        assert not cloud_spec.skip_tls_verify
        assert not cloud_spec.is_controller_cloud

    def test_from_dict_full(self):
        cred = {
            'auth-type': 'certificate',
            'attrs': {'client-cert': 'foo', 'client-key': 'bar', 'server-cert': 'baz'},
            'redacted': ['foo'],
        }
        d = {
            'type': 'lxd',
            'name': 'localhost',
            'region': 'localhost',
            'endpoint': 'https://10.76.251.1:8443',
            'credential': cred,
            'identity-endpoint': 'foo',
            'storage-endpoint': 'bar',
            'cacertificates': ['foo', 'bar'],
            'skip-tls-verify': False,
            'is-controller-cloud': True,
        }
        cloud_spec = ops.CloudSpec.from_dict(d)
        assert cloud_spec.type == d['type']
        assert cloud_spec.name == d['name']
        assert cloud_spec.region == d['region']
        assert cloud_spec.endpoint == d['endpoint']
        assert cloud_spec.credential == ops.CloudCredential.from_dict(cred)
        assert cloud_spec.identity_endpoint == d['identity-endpoint']
        assert cloud_spec.storage_endpoint == d['storage-endpoint']
        assert cloud_spec.ca_certificates == d['cacertificates']
        assert not cloud_spec.skip_tls_verify
        assert cloud_spec.is_controller_cloud

    def test_from_dict_no_credential(self):
        d = {
            'type': 'lxd',
            'name': 'localhost',
            'region': 'localhost',
            'endpoint': 'https://10.76.251.1:8443',
            'identity-endpoint': 'foo',
            'storage-endpoint': 'bar',
            'cacertificates': ['foo', 'bar'],
            'skip-tls-verify': False,
            'is-controller-cloud': True,
        }
        cloud_spec = ops.CloudSpec.from_dict(d)
        assert cloud_spec.type == d['type']
        assert cloud_spec.name == d['name']
        assert cloud_spec.region == d['region']
        assert cloud_spec.endpoint == d['endpoint']
        assert cloud_spec.credential is None
        assert cloud_spec.identity_endpoint == d['identity-endpoint']
        assert cloud_spec.storage_endpoint == d['storage-endpoint']
        assert cloud_spec.ca_certificates == d['cacertificates']
        assert not cloud_spec.skip_tls_verify
        assert cloud_spec.is_controller_cloud


class TestGetCloudSpec:
    @pytest.fixture
    def model(self):
        return ops.Model(ops.CharmMeta(), _ModelBackend('myapp/0'))

    def test_success(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write('credential-get', """echo '{"type": "lxd", "name": "localhost"}'""")
        cloud_spec = model.get_cloud_spec()
        assert cloud_spec.type == 'lxd'
        assert cloud_spec.name == 'localhost'
        assert fake_script.calls(clear=True) == [['credential-get', '--format=json']]

    def test_error(self, fake_script: FakeScript, model: ops.Model):
        fake_script.write(
            'credential-get', """echo 'ERROR cannot access cloud credentials' >&2; exit 1"""
        )
        with pytest.raises(ops.ModelError) as excinfo:
            model.get_cloud_spec()
        assert str(excinfo.value) == 'ERROR cannot access cloud credentials\n'


if __name__ == '__main__':
    unittest.main()
