# Copyright 2023 Canonical Ltd.
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

import ipaddress
import json
import pathlib
import unittest
from test.test_helpers import fake_script, fake_script_calls

import pytest

import ops.charm
import ops.model
import ops.testing
from ops import model
from ops.charm import RelationMeta, RelationRole


class TestModel(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(ops.charm.CharmBase, meta='''
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
        ''', config='''
        options:
            foo:
                type: string
            bar:
                type: int
            qux:
                type: boolean
        ''')
        self.addCleanup(self.harness.cleanup)
        self.relation_id_db0 = self.harness.add_relation('db0', 'db')
        self.harness._get_backend_calls(reset=True)
        self.model = self.harness.model

    def test_model_attributes(self):
        self.assertIs(self.model.app, self.model.unit.app)
        self.assertIsNone(self.model.name)

    def test_unit_immutable(self):
        with self.assertRaises(AttributeError):
            self.model.unit = object()

    def test_app_immutable(self):
        with self.assertRaises(AttributeError):
            self.model.app = object()

    def test_model_name_from_backend(self):
        self.harness.set_model_name('default')
        m = ops.model.Model(ops.charm.CharmMeta(), self.harness._backend)
        self.assertEqual(m.name, 'default')
        with self.assertRaises(AttributeError):
            m.name = "changes-disallowed"

    def test_relations_keys(self):
        rel_app1 = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(rel_app1, 'remoteapp1/0')
        self.harness.add_relation_unit(rel_app1, 'remoteapp1/1')
        rel_app2 = self.harness.add_relation('db1', 'remoteapp2')
        self.harness.add_relation_unit(rel_app2, 'remoteapp2/0')

        # We invalidate db1 so that it causes us to reload it
        self.model.relations._invalidate('db1')
        self.resetBackendCalls()
        for relation in self.model.relations['db1']:
            self.assertIn(self.model.unit, relation.data)
            unit_from_rel = next(filter(lambda u: u.name == 'myapp/0', relation.data.keys()))
            self.assertIs(self.model.unit, unit_from_rel)

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', rel_app1),
            ('relation_list', rel_app2),
        ])

    def test_relations_immutable(self):
        with self.assertRaises(AttributeError):
            self.model.relations = {}

    def test_get_relation(self):
        # one relation on db1
        # two relations on db0
        # no relations on db2
        relation_id_db1 = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id_db1, 'remoteapp1/0')
        relation_id_db0_b = self.harness.add_relation('db0', 'another')
        self.resetBackendCalls()

        with self.assertRaises(ops.model.ModelError):
            # You have to specify it by just the integer ID
            self.model.get_relation('db1', f'db1:{relation_id_db1}')
        rel_db1 = self.model.get_relation('db1', relation_id_db1)
        self.assertIsInstance(rel_db1, ops.model.Relation)
        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id_db1),
        ])
        dead_rel = self.model.get_relation('db1', 7)
        self.assertIsInstance(dead_rel, ops.model.Relation)
        self.assertEqual(set(dead_rel.data.keys()), {self.model.unit, self.model.unit.app})
        self.assertEqual(dead_rel.data[self.model.unit], {})
        self.assertBackendCalls([
            ('relation_list', 7),
            ('relation_remote_app_name', 7),
            ('relation_get', 7, 'myapp/0', False),
        ])

        self.assertIsNone(self.model.get_relation('db2'))
        self.assertBackendCalls([
            ('relation_ids', 'db2'),
        ])
        self.assertIs(self.model.get_relation('db1'), rel_db1)
        with self.assertRaises(ops.model.TooManyRelatedAppsError):
            self.model.get_relation('db0')

        self.assertBackendCalls([
            ('relation_ids', 'db0'),
            ('relation_list', self.relation_id_db0),
            ('relation_remote_app_name', 0),
            ('relation_list', relation_id_db0_b),
            ('relation_remote_app_name', 2),
        ])

    def test_peer_relation_app(self):
        self.harness.add_relation('db2', 'myapp')
        rel_dbpeer = self.model.get_relation('db2')
        self.assertIs(rel_dbpeer.app, self.model.app)

    def test_remote_units_is_our(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/1')
        self.resetBackendCalls()

        for u in self.model.get_relation('db1').units:
            self.assertFalse(u._is_our_unit)
            self.assertFalse(u.app._is_our_app)

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id)
        ])

    def test_our_unit_is_our(self):
        self.assertTrue(self.model.unit._is_our_unit)
        self.assertTrue(self.model.unit.app._is_our_app)

    def test_invalid_type_relation_data(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')

        with self.assertRaises(model.RelationDataError):
            with self.harness._event_context('foo_event'):
                self.harness.update_relation_data(
                    relation_id,
                    'remoteapp1/0',
                    {42: 'remoteapp1-0'})

        with self.assertRaises(model.RelationDataError):
            with self.harness._event_context('foo_event'):
                self.harness.update_relation_data(
                    relation_id,
                    'remoteapp1/0',
                    {'foo': 42})

    def test_get_app_relation_data(self):
        self.harness.begin()
        relation_id = self.harness.add_relation('db1', 'remote')
        self.harness.add_relation_unit(relation_id, 'remote/0')
        local_app = self.harness.model.app.name
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(
                relation_id,
                local_app,
                {'foo': 'bar'})
            assert self.harness.get_relation_data(
                relation_id, self.harness.model.app) == self.harness.get_relation_data(
                relation_id, local_app) == {'foo': 'bar'}

    def test_unit_relation_data(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(
                relation_id,
                'remoteapp1/0',
                {'host': 'remoteapp1-0'})
        self.model.relations._invalidate('db1')
        self.resetBackendCalls()

        random_unit = self.model.get_unit('randomunit/0')
        with self.assertRaises(KeyError):
            self.model.get_relation('db1').data[random_unit]
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0',
                                   self.model.get_relation('db1').units))
        self.assertEqual(self.model.get_relation('db1').data[remoteapp1_0],
                         {'host': 'remoteapp1-0'})

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'remoteapp1/0', False),
        ])

    def test_remote_app_relation_data(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(relation_id, 'remoteapp1',
                                              {'secret': 'cafedeadbeef'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/1')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        # Try to get relation data for an invalid remote application.
        random_app = self.model._cache.get(ops.model.Application, 'randomapp')
        with self.assertRaises(KeyError):
            rel_db1.data[random_app]

        remoteapp1 = rel_db1.app
        self.assertEqual(remoteapp1.name, 'remoteapp1')
        self.assertEqual(rel_db1.data[remoteapp1],
                         {'secret': 'cafedeadbeef'})

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'remoteapp1', True),
        ])

    def test_relation_data_modify_remote(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(relation_id, 'remoteapp1',
                                              {'secret': 'cafedeadbeef'})
            self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
            self.harness.update_relation_data(relation_id, 'remoteapp1/0',
                                              {'host': 'remoteapp1/0'})
        self.model.relations._invalidate('db1')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0',
                                   self.model.get_relation('db1').units))
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[remoteapp1_0])
        self.assertEqual(repr(rel_db1.data[remoteapp1_0]), "{'host': 'remoteapp1/0'}")

        with self.harness._event_context('foo_event'):
            with self.assertRaises(ops.model.RelationDataError):
                rel_db1.data[remoteapp1_0]['foo'] = 'bar'
        self.assertNotIn('foo', rel_db1.data[remoteapp1_0])

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'remoteapp1/0', False),
        ])

        # this will fire more backend calls
        with self.harness._event_context('foo_event'):
            data_repr = repr(rel_db1.data)
        self.assertEqual(
            data_repr,
            ('{<ops.model.Unit myapp/0>: {}, '
             '<ops.model.Application myapp>: <n/a>, '
             "<ops.model.Unit remoteapp1/0>: {'host': 'remoteapp1/0'}, "
             "<ops.model.Application remoteapp1>: {'secret': 'cafedeadbeef'}}"))

    def test_relation_data_modify_our(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')

        self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'nothing'})
        self.resetBackendCalls()
        with self.harness._event_context('foo_event'):
            rel_db1 = self.model.get_relation('db1')
            # update_relation_data will also trigger relation-get, so we
            # invalidate the cache to ensure it will be reloaded
            rel_db1.data[self.model.unit]._invalidate()
            # Force memory cache to be loaded.
            self.assertIn('host', rel_db1.data[self.model.unit])
            rel_db1.data[self.model.unit]['host'] = 'bar'
            self.assertEqual(rel_db1.data[self.model.unit]['host'], 'bar')

        self.assertBackendCalls([
            ('relation_get', relation_id, 'myapp/0', False),
            ('update_relation_data', relation_id, self.model.unit, 'host', 'bar'),
        ])

    def test_app_relation_data_modify_local_as_leader(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp', {'password': 'deadbeefcafe'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.set_leader(True)
        self.resetBackendCalls()

        local_app = self.model.unit.app

        rel_db1 = self.model.get_relation('db1')
        self.assertEqual(rel_db1.data[local_app], {'password': 'deadbeefcafe'})

        rel_db1.data[local_app]['password'] = 'foo'

        self.assertEqual(rel_db1.data[local_app]['password'], 'foo')

        self.assertBackendCalls(
            [('relation_ids', 'db1'),
             ('relation_list', 1),
             ('relation_get', 1, 'myapp', True),
             ('update_relation_data', 1, self.model.app, 'password', 'foo')])

    def test_app_relation_data_modify_local_as_minion(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp', {'password': 'deadbeefcafe'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.set_leader(False)
        self.resetBackendCalls()

        local_app = self.model.unit.app

        rel_db1 = self.model.get_relation('db1')
        self.assertEqual(rel_db1.data[local_app], {'password': 'deadbeefcafe'})

        with self.harness._event_context('foo_event'):
            # if we were inside an event context, we'd get:
            with self.assertRaises(ops.model.RelationDataError):
                rel_db1.data[local_app]['password'] = 'foobar'

        self.assertBackendCalls([('relation_ids', 'db1'),
                                 ('relation_list', 1),
                                 ('relation_get', 1, 'myapp', True),
                                 ('is_leader',)])

    def test_relation_data_access_peer_leader(self):
        r_id = self.harness.add_relation('db2', 'myapp')
        self.harness.add_relation_unit(r_id, 'myapp/1')  # peer!
        self.harness.update_relation_data(r_id, 'myapp', {'foo': 'bar'})
        with self.harness._event_context('foo_event'):
            # leaders can read
            self.harness.set_leader(True)
            relation = self.harness.model.get_relation('db2')
            self.assertEqual(relation.data[relation.app]['foo'], 'bar')

    def test_relation_data_access_peer_minion(self):
        r_id = self.harness.add_relation('db2', 'myapp')
        self.harness.add_relation_unit(r_id, 'myapp/1')  # peer!
        self.harness.update_relation_data(r_id, 'myapp', {'foo': 'bar'})
        with self.harness._event_context('foo_event'):
            # nonleaders can read
            self.harness.set_leader(False)
            relation = self.harness.model.get_relation('db2')
            self.assertEqual(relation.data[relation.app]['foo'], 'bar')

    def test_relation_data_del_key(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'bar'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        del rel_db1.data[self.model.unit]['host']
        self.assertNotIn('host', rel_db1.data[self.model.unit])
        self.assertEqual({}, self.harness.get_relation_data(relation_id, 'myapp/0'))

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp/0', False),
            ('update_relation_data', relation_id, self.model.unit, 'host', ''),
        ])

    def test_relation_data_del_missing_key(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'bar'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        with self.harness._event_context('foo_event'):
            rel_db1.data[self.model.unit]['port'] = ''   # Same as a delete, should not fail.
        self.assertNotIn('port', rel_db1.data[self.model.unit])
        with self.harness._event_context('foo_event'):
            self.assertEqual({'host': 'bar'},
                             self.harness.get_relation_data(relation_id, 'myapp/0'))

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp/0', False),
            ('update_relation_data', relation_id, self.model.unit, 'port', ''),
        ])

    def test_relation_set_fail(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'myapp-0'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls()

        backend = self.harness._backend
        # TODO: jam 2020-03-06 This is way too much information about relation_set
        #       The original test forced 'relation-set' to return exit code 2,
        #       but there was nothing illegal about the data that was being set,
        #       for us to properly test the side effects of relation-set failing.

        def broken_update_relation_data(relation_id, entity, key, value):
            backend._calls.append(('update_relation_data', relation_id, entity, key, value))
            raise ops.model.ModelError()
        backend.update_relation_data = broken_update_relation_data

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])

        with self.harness._event_context('foo_event'):
            with self.assertRaises(ops.model.ModelError):
                rel_db1.data[self.model.unit]['host'] = 'bar'
            self.assertEqual(rel_db1.data[self.model.unit]['host'], 'myapp-0')
            with self.assertRaises(ops.model.ModelError):
                del rel_db1.data[self.model.unit]['host']
            self.assertIn('host', rel_db1.data[self.model.unit])

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp/0', False),
            ('update_relation_data', relation_id, self.model.unit, 'host', 'bar'),
            ('update_relation_data', relation_id, self.model.unit, 'host', ''),
        ])

    def test_relation_data_type_check(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'myapp-0'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        for key, value in (
                ('foo', 1),
                ('foo', None),
                ('foo', {'foo': 'bar'}),
                (1, 'foo'),
                (None, 'foo'),
                (('foo', 'bar'), 'foo'),
                (1, 1),
                (None, None)
        ):
            with self.assertRaises(ops.model.RelationDataError):
                with self.harness.framework._event_context('foo_event'):
                    rel_db1.data[self.model.unit][key] = value

        # No data has actually been changed
        self.assertEqual(dict(rel_db1.data[self.model.unit]), {'host': 'myapp-0'})

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp/0', False),
        ])

    def test_relation_local_app_data_readability_leader(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'remoteapp1',
                                          {'secret': 'cafedeadbeef'})
        self.harness.update_relation_data(relation_id, 'myapp',
                                          {'local': 'data'})

        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.update_relation_data(relation_id, 'remoteapp1/0',
                                          {'host': 'remoteapp1/0'})
        self.model.relations._invalidate('db1')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        self.harness.begin()
        self.harness.set_leader(True)
        self.resetBackendCalls()

        local_app = self.harness.charm.app
        self.resetBackendCalls()

        # addressing the object is OK
        rel_db1.data[local_app]

        self.assertBackendCalls([])

        with self.harness._event_context('foo_event'):
            self.resetBackendCalls()

            self.assertEqual(rel_db1.data[local_app]['local'], 'data')

            self.assertBackendCalls([('is_leader',),
                                     ('relation_get', 1, 'myapp', True)])

            self.resetBackendCalls()

            self.assertEqual(repr(rel_db1.data[local_app]), repr({'local': 'data'}))

            # we don't get the data, because we're lazy
            self.assertBackendCalls([('is_leader',)])

            # as well as relation data repr() in general:
            self.assertIsInstance(repr(rel_db1.data), str)

    def test_relation_local_app_data_readability_follower(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        with self.harness._event_context('foo_event'):
            self.harness.update_relation_data(relation_id, 'remoteapp1',
                                              {'secret': 'cafedeadbeef'})
            self.harness.update_relation_data(relation_id, 'myapp',
                                              {'local': 'data'})

            self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
            self.harness.update_relation_data(relation_id, 'remoteapp1/0',
                                              {'host': 'remoteapp1/0'})
        self.model.relations._invalidate('db1')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        self.harness.begin()
        self.harness.set_leader(False)

        local_app = self.harness.charm.app
        # addressing the object is OK
        rel_db1.data[local_app]
        # nonleader units cannot read their local app databag
        # attempting to read it is not
        with self.harness._event_context('foo_event'):
            self.resetBackendCalls()

            with self.assertRaises(ops.model.RelationDataError):
                # 'local' is there, but still:
                rel_db1.data[local_app]['local']

            # we didn't even get to relation-get
            self.assertBackendCalls([('is_leader', )])

            # we can't see it but repr() works
            self.assertEqual(repr(rel_db1.data[local_app]), '<n/a>')
            self.assertBackendCalls([('is_leader', )])

            # as well as relation data repr() in general:
            self.assertIsInstance(repr(rel_db1.data), str)

            expected_backend_calls = [
                ('relation_get', 1, 'myapp/0', False),
                ('is_leader',),
                ('relation_get', 1, 'remoteapp1/0', False),
                ('is_leader',),
                ('relation_get', 1, 'remoteapp1', True)]
            self.assertBackendCalls(expected_backend_calls)

    def test_relation_no_units(self):
        self.harness.add_relation('db1', 'remoteapp1')
        rel = self.model.get_relation('db1')
        self.assertEqual(rel.units, set())
        self.assertIs(rel.app, self.model.get_app('remoteapp1'))
        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', 1),
            ('relation_remote_app_name', 1),
        ])

    def test_config(self):
        self.harness._get_backend_calls(reset=True)
        self.harness.update_config({'foo': 'foo', 'bar': 1, 'qux': True})
        self.assertEqual(self.model.config, {
            'foo': 'foo',
            'bar': 1,
            'qux': True,
        })
        with self.assertRaises(TypeError):
            # Confirm that we cannot modify config values.
            self.model.config['foo'] = 'bar'

        self.assertBackendCalls([('config_get',)])

    def test_config_immutable(self):
        with self.assertRaises(AttributeError):
            self.model.config = {}

    def test_is_leader(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.set_leader(True)
        self.resetBackendCalls()

        def check_remote_units():
            # Cannot determine leadership for remote units.
            for u in self.model.get_relation('db1').units:
                with self.assertRaises(RuntimeError):
                    u.is_leader()

        self.assertTrue(self.model.unit.is_leader())

        check_remote_units()

        # Create a new model and backend to drop a cached is-leader output.
        self.harness.set_leader(False)
        self.assertFalse(self.model.unit.is_leader())

        check_remote_units()

        self.assertBackendCalls([
            ('is_leader',),
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('is_leader',),
        ])

    def test_workload_version(self):
        self.model.unit.set_workload_version('1.2.3')
        self.assertBackendCalls([
            ('application_version_set', '1.2.3'),
        ])

    def test_workload_version_invalid(self):
        with self.assertRaises(TypeError) as cm:
            self.model.unit.set_workload_version(5)
        self.assertEqual(str(cm.exception), "workload version must be a str, not int: 5")
        self.assertBackendCalls([])

    def test_resources(self):
        with self.assertRaises(ops.model.ModelError):
            self.harness.model.resources.fetch('foo')

        self.harness.add_resource('foo', 'foo contents\n')
        self.harness.add_resource('bar', '')

        with self.assertRaises(NameError):
            self.harness.model.resources.fetch('qux')

        self.assertEqual(self.harness.model.resources.fetch('foo').name, 'foo.txt')
        self.assertEqual(self.harness.model.resources.fetch('bar').name, 'bar.txt')

    def test_resources_immutable(self):
        with self.assertRaises(AttributeError):
            self.model.resources = object()

    def test_pod_spec(self):
        self.harness.set_leader(True)
        self.harness.model.pod.set_spec({'foo': 'bar'})
        self.assertEqual(self.harness.get_pod_spec(), ({'foo': 'bar'}, None))

        self.harness.model.pod.set_spec({'bar': 'foo'}, {'qux': 'baz'})
        self.assertEqual(self.harness.get_pod_spec(), ({'bar': 'foo'}, {'qux': 'baz'}))

        # no leader -> no set pod spec
        self.harness.set_leader(False)
        with self.assertRaises(ops.model.ModelError):
            self.harness.model.pod.set_spec({'foo': 'bar'})

    def test_pod_immutable(self):
        with self.assertRaises(AttributeError):
            self.model.pod = object()

    def test_base_status_instance_raises(self):
        with self.assertRaises(TypeError):
            ops.model.StatusBase('test')

        class NoNameStatus(ops.model.StatusBase):
            pass

        with self.assertRaises(AttributeError):
            ops.model.StatusBase.register_status(NoNameStatus)

    def test_status_repr(self):
        test_cases = {
            "ActiveStatus('Seashell')": ops.model.ActiveStatus('Seashell'),
            "MaintenanceStatus('Red')": ops.model.MaintenanceStatus('Red'),
            "BlockedStatus('Magenta')": ops.model.BlockedStatus('Magenta'),
            "WaitingStatus('Thistle')": ops.model.WaitingStatus('Thistle'),
            'UnknownStatus()': ops.model.UnknownStatus(),
        }
        for expected, status in test_cases.items():
            self.assertEqual(repr(status), expected)

    def test_status_eq(self):
        status_types = [
            ops.model.ActiveStatus,
            ops.model.MaintenanceStatus,
            ops.model.BlockedStatus,
            ops.model.WaitingStatus,
        ]

        self.assertEqual(ops.model.UnknownStatus(), ops.model.UnknownStatus())
        for (i, t1) in enumerate(status_types):
            self.assertNotEqual(t1(''), ops.model.UnknownStatus())
            for (j, t2) in enumerate(status_types):
                self.assertNotEqual(t1('one'), t2('two'))
                if i == j:
                    self.assertEqual(t1('one'), t2('one'))
                else:
                    self.assertNotEqual(t1('one'), t2('one'))

    def test_active_message_default(self):
        self.assertEqual(ops.model.ActiveStatus().message, '')

    def test_local_set_valid_unit_status(self):
        self.harness._get_backend_calls(reset=True)
        test_cases = [(
            'active',
            ops.model.ActiveStatus('Green'),
            ('status_set', 'active', 'Green', {'is_app': False}),
        ), (
            'maintenance',
            ops.model.MaintenanceStatus('Yellow'),
            ('status_set', 'maintenance', 'Yellow', {'is_app': False}),
        ), (
            'blocked',
            ops.model.BlockedStatus('Red'),
            ('status_set', 'blocked', 'Red', {'is_app': False}),
        ), (
            'waiting',
            ops.model.WaitingStatus('White'),
            ('status_set', 'waiting', 'White', {'is_app': False}),
        )]

        for test_case, target_status, backend_call in test_cases:
            with self.subTest(test_case):
                self.model.unit.status = target_status
                self.assertEqual(self.model.unit.status, target_status)
                self.model.unit._invalidate()
                self.assertEqual(self.model.unit.status, target_status)
                self.assertBackendCalls([backend_call, ('status_get', {'is_app': False})])

    def test_local_set_valid_app_status(self):
        self.harness.set_leader(True)
        test_cases = [(
            'active',
            ops.model.ActiveStatus('Green'),
            ('status_set', 'active', 'Green', {'is_app': True}),
        ), (
            'maintenance',
            ops.model.MaintenanceStatus('Yellow'),
            ('status_set', 'maintenance', 'Yellow', {'is_app': True}),
        ), (
            'blocked',
            ops.model.BlockedStatus('Red'),
            ('status_set', 'blocked', 'Red', {'is_app': True}),
        ), (
            'waiting',
            ops.model.WaitingStatus('White'),
            ('status_set', 'waiting', 'White', {'is_app': True}),
        )]

        for test_case, target_status, backend_call in test_cases:
            with self.subTest(test_case):
                self.model.app.status = target_status
                self.assertEqual(self.model.app.status, target_status)
                self.model.app._invalidate()
                self.assertEqual(self.model.app.status, target_status)
                # There is a backend call to check if we can set the value,
                # and then another check each time we assert the status above
                expected_calls = [
                    ('is_leader',), backend_call,
                    ('is_leader',),
                    ('is_leader',), ('status_get', {'is_app': True}),
                ]
                self.assertBackendCalls(expected_calls)

    def test_set_app_status_non_leader_raises(self):
        self.harness.set_leader(False)
        with self.assertRaises(RuntimeError):
            self.model.app.status

        with self.assertRaises(RuntimeError):
            self.model.app.status = ops.model.ActiveStatus()

    def test_set_unit_status_invalid(self):
        with self.assertRaises(ops.model.InvalidStatusError):
            self.model.unit.status = 'blocked'

    def test_set_app_status_invalid(self):
        with self.assertRaises(ops.model.InvalidStatusError):
            self.model.app.status = 'blocked'

    def test_remote_unit_status(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/1')
        remote_unit = next(filter(lambda u: u.name == 'remoteapp1/0',
                                  self.model.get_relation('db1').units))
        self.resetBackendCalls()

        # Remote unit status is always unknown.
        self.assertEqual(remote_unit.status, ops.model.UnknownStatus())

        test_statuses = (
            ops.model.UnknownStatus(),
            ops.model.ActiveStatus('Green'),
            ops.model.MaintenanceStatus('Yellow'),
            ops.model.BlockedStatus('Red'),
            ops.model.WaitingStatus('White'),
        )

        for target_status in test_statuses:
            with self.subTest(target_status.name):
                with self.assertRaises(RuntimeError):
                    remote_unit.status = target_status
        self.assertBackendCalls([])

    def test_remote_app_status(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/1')
        remoteapp1 = self.model.get_relation('db1').app
        self.resetBackendCalls()

        # Remote application status is always unknown.
        self.assertIsInstance(remoteapp1.status, ops.model.UnknownStatus)

        test_statuses = (
            ops.model.UnknownStatus(),
            ops.model.ActiveStatus(),
            ops.model.MaintenanceStatus('Upgrading software'),
            ops.model.BlockedStatus('Awaiting manual resolution'),
            ops.model.WaitingStatus('Awaiting related app updates'),
        )
        for target_status in test_statuses:
            with self.subTest(target_status.name):
                with self.assertRaises(RuntimeError):
                    remoteapp1.status = target_status
        self.assertBackendCalls([])

    def test_storage(self):
        meta = ops.charm.CharmMeta()
        meta.storages = {'disks': None, 'data': None}
        model = ops.model.Model(meta, ops.model._ModelBackend('myapp/0'))

        fake_script(self, 'storage-list', '''
            if [ "$1" = disks ]; then
                echo '["disks/0", "disks/1"]'
            else
                echo '[]'
            fi
        ''')
        fake_script(self, 'storage-get', '''
            if [ "$2" = disks/0 ]; then
                echo '"/var/srv/disks/0"'
            elif [ "$2" = disks/1 ]; then
                echo '"/var/srv/disks/1"'
            else
                exit 2
            fi
        ''')
        fake_script(self, 'storage-add', '')

        self.assertEqual(len(model.storages), 2)
        self.assertEqual(model.storages.keys(), meta.storages.keys())
        self.assertIn('disks', model.storages)

        with pytest.raises(KeyError, match='Did you mean'):
            model.storages['does-not-exist']

        test_cases = {
            0: {'name': 'disks', 'location': pathlib.Path('/var/srv/disks/0')},
            1: {'name': 'disks', 'location': pathlib.Path('/var/srv/disks/1')},
        }
        for storage in model.storages['disks']:
            self.assertEqual(storage.name, 'disks')
            self.assertIn(storage.id, test_cases)
            self.assertEqual(storage.name, test_cases[storage.id]['name'])
            self.assertEqual(storage.location, test_cases[storage.id]['location'])

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['storage-list', 'disks', '--format=json'],
            ['storage-get', '-s', 'disks/0', 'location', '--format=json'],
            ['storage-get', '-s', 'disks/1', 'location', '--format=json'],
        ])

        self.assertSequenceEqual(model.storages['data'], [])
        model.storages.request('data', count=3)
        self.assertEqual(fake_script_calls(self), [
            ['storage-list', 'data', '--format=json'],
            ['storage-add', 'data=3'],
        ])

        # Try to add storage not present in charm metadata.
        with self.assertRaises(ops.model.ModelError):
            model.storages.request('deadbeef')

        # Invalid count parameter types.
        for count_v in [None, False, 2.0, 'a', b'beef', object]:
            with self.assertRaises(TypeError):
                model.storages.request('data', count_v)

    def test_storages_immutable(self):
        with self.assertRaises(AttributeError):
            self.model.storages = {}

    def resetBackendCalls(self):  # noqa: N802
        self.harness._get_backend_calls(reset=True)

    def assertBackendCalls(self, expected, *, reset=True):  # noqa: N802
        self.assertEqual(expected, self.harness._get_backend_calls(reset=reset))

    def test_run_error(self):
        model = ops.model.Model(ops.charm.CharmMeta(), ops.model._ModelBackend('myapp/0'))
        fake_script(self, 'status-get', """echo 'ERROR cannot get status' >&2; exit 1""")
        with self.assertRaises(ops.model.ModelError) as cm:
            _ = model.unit.status.message
        self.assertEqual(str(cm.exception), 'ERROR cannot get status\n')
        self.assertEqual(cm.exception.args[0], 'ERROR cannot get status\n')


class TestApplication(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(ops.charm.CharmBase, meta='''
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
        ''')
        self.peer_rel_id = self.harness.add_relation('db2', 'db2')
        self.app = self.harness.model.app
        self.addCleanup(self.harness.cleanup)

    # Tests fix for https://github.com/canonical/operator/issues/694.
    def test_mocked_get_services(self):
        self.harness.begin()
        self.harness.set_can_connect('bar', True)
        c = self.harness.charm.unit.get_container('bar')
        c.add_layer('layer1', {
            'summary': 'layer',
            'services': {"baz": {'override': 'replace', 'summary': 'echo', 'command': 'echo 1'}},
        })

        s = c.get_service('baz')  # So far, so good
        self.assertTrue(s)
        self.assertTrue('baz' in c.get_services())

    def test_planned_units(self):
        rel_id = self.peer_rel_id

        # Test that we always count ourself.
        self.assertEqual(self.app.planned_units(), 1)

        # Add some units, and verify count.
        self.harness.add_relation_unit(rel_id, 'myapp/1')
        self.harness.add_relation_unit(rel_id, 'myapp/2')

        self.assertEqual(self.app.planned_units(), 3)

        self.harness.add_relation_unit(rel_id, 'myapp/3')
        self.assertEqual(self.app.planned_units(), 4)

        # And remove a unit
        self.harness.remove_relation_unit(rel_id, 'myapp/2')

        self.assertEqual(self.app.planned_units(), 3)

    def test_planned_units_user_set(self):

        self.harness.set_planned_units(1)
        self.assertEqual(self.app.planned_units(), 1)

        self.harness.set_planned_units(2)
        self.assertEqual(self.app.planned_units(), 2)

        self.harness.set_planned_units(100)
        self.assertEqual(self.app.planned_units(), 100)

    def test_planned_units_garbage_values(self):
        # Planned units should be a positive integer, or zero.
        with self.assertRaises(TypeError):
            self.harness.set_planned_units(-1)
        # Verify that we didn't set our value before raising the error.
        self.assertTrue(self.harness._backend._planned_units is None)
        # Verify that we still get the default value back from .planned_units.
        self.assertEqual(self.app.planned_units(), 1)

        with self.assertRaises(TypeError):
            self.harness.set_planned_units("foo")

        with self.assertRaises(TypeError):
            self.harness.set_planned_units(-3423000102312321090)

    def test_planned_units_override(self):
        """Verify that we override the calculated value of planned_units when we set it manually.

        When a charm author writes a test that explicitly calls set_planned_units, we assume that
        their intent is to override the calculated return value. Often, this will be because the
        charm author is composing a charm without peer relations, and the harness's count of
        planned units, which is based on the number of peer relations, will not be accurate.
        """
        peer_id = self.peer_rel_id

        self.harness.set_planned_units(10)
        self.harness.add_relation_unit(peer_id, 'myapp/1')
        self.harness.add_relation_unit(peer_id, 'myapp/2')
        self.harness.add_relation_unit(peer_id, 'myapp/3')

        self.assertEqual(self.app.planned_units(), 10)

        # Verify that we can clear the override.
        self.harness.reset_planned_units()
        self.assertEqual(self.app.planned_units(), 4)  # self + 3 peers


class TestContainers(unittest.TestCase):
    def setUp(self):
        meta = ops.charm.CharmMeta.from_yaml("""
name: k8s-charm
containers:
  c1:
    k: v
  c2:
    k: v
""")
        backend = ops.model._ModelBackend('myapp/0')
        self.model = ops.model.Model(meta, backend)

    def test_unit_containers(self):
        containers = self.model.unit.containers
        self.assertEqual(sorted(containers), ['c1', 'c2'])
        self.assertEqual(len(containers), 2)
        self.assertIn('c1', containers)
        self.assertIn('c2', containers)
        self.assertNotIn('c3', containers)
        for name in ['c1', 'c2']:
            container = containers[name]
            self.assertIsInstance(container, ops.model.Container)
            self.assertEqual(container.name, name)
            self.assertIsInstance(container.pebble, ops.pebble.Client)
        with self.assertRaises(KeyError):
            containers['c3']

        with self.assertRaises(RuntimeError):
            other_unit = self.model.get_unit('other')
            other_unit.containers

    def test_unit_get_container(self):
        unit = self.model.unit
        for name in ['c1', 'c2']:
            container = unit.get_container(name)
            self.assertIsInstance(container, ops.model.Container)
            self.assertEqual(container.name, name)
            self.assertIsInstance(container.pebble, ops.pebble.Client)
        with self.assertRaises(ops.model.ModelError):
            unit.get_container('c3')

        with self.assertRaises(RuntimeError):
            other_unit = self.model.get_unit('other')
            other_unit.get_container('foo')


class TestModelBindings(unittest.TestCase):
    def setUp(self):
        meta = ops.charm.CharmMeta()
        meta.relations = {
            'db0': RelationMeta(
                RelationRole.provides, 'db0', {'interface': 'db0', 'scope': 'global'}),
            'db1': RelationMeta(
                RelationRole.requires, 'db1', {'interface': 'db1', 'scope': 'global'}),
            'db2': RelationMeta(
                RelationRole.peer, 'db2', {'interface': 'db2', 'scope': 'global'}),
        }
        self.backend = ops.model._ModelBackend('myapp/0')
        self.model = ops.model.Model(meta, self.backend)

        fake_script(self, 'relation-ids',
                    """([ "$1" = db0 ] && echo '["db0:4"]') || echo '[]'""")
        fake_script(self, 'relation-list', """[ "$2" = 4 ] && echo '["remoteapp1/0"]' || exit 2""")
        self.network_get_out = '''{
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
}'''

    def _check_binding_data(self, binding_name, binding):
        self.assertEqual(binding.name, binding_name)
        self.assertEqual(binding.network.bind_address, ipaddress.ip_address('192.0.2.2'))
        self.assertEqual(binding.network.ingress_address, ipaddress.ip_address('192.0.2.2'))
        # /32 and /128 CIDRs are valid one-address networks for IPv{4,6}Network types respectively.
        self.assertEqual(binding.network.egress_subnets, [ipaddress.ip_network('192.0.2.2/32'),
                                                          ipaddress.ip_network('192.0.3.0/24'),
                                                          ipaddress.ip_network('dead:beef::/64'),
                                                          ipaddress.ip_network('2001:db8::3/128')])

        for (i, (name, address, subnet)) in enumerate([
                ('lo', '192.0.2.2', '192.0.2.0/24'),
                ('lo', 'dead:beef::1', 'dead:beef::/64'),
                ('tun', '192.0.3.3', '192.0.3.3/32'),
                ('tun', '2001:db8::3', '2001:db8::3/128'),
                ('tun', 'fe80::1:1', 'fe80::/64')]):
            self.assertEqual(binding.network.interfaces[i].name, name)
            self.assertEqual(binding.network.interfaces[i].address, ipaddress.ip_address(address))
            self.assertEqual(binding.network.interfaces[i].subnet, ipaddress.ip_network(subnet))

        for (i, (name, address, subnet)) in enumerate([
                ('lo', '192.0.2.2', '192.0.2.0/24'),
                ('lo', 'dead:beef::1', 'dead:beef::/64'),
                ('tun', '192.0.3.3', '192.0.3.3/32'),
                ('tun', '2001:db8::3', '2001:db8::3/128'),
                ('tun', 'fe80::1:1', 'fe80::/64')]):
            self.assertEqual(binding.network.interfaces[i].name, name)
            self.assertEqual(binding.network.interfaces[i].address, ipaddress.ip_address(address))
            self.assertEqual(binding.network.interfaces[i].subnet, ipaddress.ip_network(subnet))

    def test_invalid_keys(self):
        # Basic validation for passing invalid keys.
        for name in (object, 0):
            with self.assertRaises(ops.model.ModelError):
                self.model.get_binding(name)

    def test_dead_relations(self):
        fake_script(
            self,
            'network-get',
            f'''
                if [ "$1" = db0 ] && [ "$2" = --format=json ]; then
                    echo '{self.network_get_out}'
                else
                    echo ERROR invalid value "$2" for option -r: relation not found >&2
                    exit 2
                fi
            ''')
        # Validate the behavior for dead relations.
        binding = ops.model.Binding('db0', 42, self.model._backend)
        self.assertEqual(binding.network.bind_address, ipaddress.ip_address('192.0.2.2'))
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['network-get', 'db0', '-r', '42', '--format=json'],
            ['network-get', 'db0', '--format=json'],
        ])

    def test_binding_by_relation_name(self):
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{self.network_get_out}' || exit 1''')
        binding_name = 'db0'
        expected_calls = [['network-get', 'db0', '--format=json']]

        binding = self.model.get_binding(binding_name)
        self._check_binding_data(binding_name, binding)
        self.assertEqual(fake_script_calls(self, clear=True), expected_calls)

    def test_binding_by_relation(self):
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{self.network_get_out}' || exit 1''')
        binding_name = 'db0'
        expected_calls = [
            ['relation-ids', 'db0', '--format=json'],
            # The two invocations below are due to the get_relation call.
            ['relation-list', '-r', '4', '--format=json'],
            ['network-get', 'db0', '-r', '4', '--format=json'],
        ]
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self._check_binding_data(binding_name, binding)
        self.assertEqual(fake_script_calls(self, clear=True), expected_calls)

    def test_binding_no_iface_name(self):
        network_get_out_obj = {
            'bind-addresses': [
                {
                    'mac-address': '',
                    'interface-name': '',
                    'addresses': [
                        {
                            'hostname': '',
                            'value': '10.1.89.35',
                            'cidr': ''
                        }
                    ]
                }
            ],
            'egress-subnets': [
                '10.152.183.158/32'
            ],
            'ingress-addresses': [
                '10.152.183.158'
            ]
        }
        network_get_out = json.dumps(network_get_out_obj)
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_get_out}' || exit 1''')
        binding_name = 'db0'
        expected_calls = [['network-get', 'db0', '--format=json']]

        binding = self.model.get_binding(binding_name)
        self.assertEqual(binding.name, 'db0')
        self.assertEqual(binding.network.bind_address, ipaddress.ip_address('10.1.89.35'))
        self.assertEqual(binding.network.ingress_address, ipaddress.ip_address('10.152.183.158'))
        self.assertEqual(fake_script_calls(self, clear=True), expected_calls)

    def test_missing_bind_addresses(self):
        network_data = json.dumps({})
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_data}' || exit 1''')
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.interfaces, [])

    def test_empty_bind_addresses(self):
        network_data = json.dumps({'bind-addresses': [{}]})
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_data}' || exit 1''')
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.interfaces, [])

    def test_no_bind_addresses(self):
        network_data = json.dumps({'bind-addresses': [{'addresses': None}]})
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_data}' || exit 1''')
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.interfaces, [])

    def test_empty_interface_info(self):
        network_data = json.dumps({
            'bind-addresses': [{
                'interface-name': 'eth0',
                'addresses': [{}],
            }],
        })
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_data}' || exit 1''')
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(len(binding.network.interfaces), 1)
        interface = binding.network.interfaces[0]
        self.assertIsNone(interface.address)
        self.assertIsNone(interface.subnet)

    def test_missing_ingress_addresses(self):
        network_data = json.dumps({
            'bind-addresses': [],
        })
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_data}' || exit 1''')
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.ingress_addresses, [])
        self.assertEqual(binding.network.ingress_address, None)

    def test_missing_egress_subnets(self):
        network_data = json.dumps({
            'bind-addresses': [],
            'ingress-addresses': [],
        })
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_data}' || exit 1''')
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.egress_subnets, [])

    def test_unresolved_ingress_addresses(self):
        # sometimes juju fails to resolve an url to an IP, in which case
        # ingress-addresses will be the 'raw' url instead of an IP.
        network_data = json.dumps({
            'ingress-addresses': [
                'foo.bar.baz.com'
            ],
        })
        fake_script(self, 'network-get',
                    f'''[ "$1" = db0 ] && echo '{network_data}' || exit 1''')
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.ingress_addresses, ['foo.bar.baz.com'])


class TestLazyMapping(unittest.TestCase):
    def test_invalidate(self):
        loaded = []

        class MyLazyMap(ops.model.LazyMapping):
            def _load(self):
                loaded.append(1)
                return {'foo': 'bar'}

        map = MyLazyMap()
        self.assertEqual(map['foo'], 'bar')
        self.assertEqual(loaded, [1])
        self.assertEqual(map['foo'], 'bar')
        self.assertEqual(loaded, [1])
        map._invalidate()
        self.assertEqual(map['foo'], 'bar')
        self.assertEqual(loaded, [1, 1])


if __name__ == "__main__":
    unittest.main()
