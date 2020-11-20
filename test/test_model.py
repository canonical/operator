#!/usr/bin/python3
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

from collections import OrderedDict
import json
import ipaddress
import os
import pathlib
from textwrap import dedent
import unittest

import ops.model
import ops.charm
import ops.testing
from ops.charm import RelationMeta, RelationRole

from test.test_helpers import fake_script, fake_script_calls


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
        ''')
        self.addCleanup(self.harness.cleanup)
        self.relation_id_db0 = self.harness.add_relation('db0', 'db')
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
            self.model.get_relation('db1', 'db1:{}'.format(relation_id_db1))
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
            ('relation_list', relation_id_db0_b),
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

    def test_unit_relation_data(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
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
        self.harness.update_relation_data(relation_id, 'remoteapp1', {'secret': 'cafedeadbeef'})
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
        self.harness.update_relation_data(relation_id, 'remoteapp1', {'secret': 'cafedeadbeef'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.update_relation_data(relation_id, 'remoteapp1/0', {'host': 'remoteapp1/0'})
        self.model.relations._invalidate('db1')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0',
                                   self.model.get_relation('db1').units))
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[remoteapp1_0])
        self.assertEqual(repr(rel_db1.data[remoteapp1_0]), "{'host': 'remoteapp1/0'}")

        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[remoteapp1_0]['foo'] = 'bar'
        self.assertNotIn('foo', rel_db1.data[remoteapp1_0])

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'remoteapp1/0', False),
        ])

        # this will fire more backend calls
        # the CountEqual and weird (and brittle) splitting is to accommodate python 3.5
        # TODO: switch to assertEqual when we drop 3.5
        self.assertCountEqual(
            repr(rel_db1.data)[1:-1].split(', '),
            ["<ops.model.Unit myapp/0>: {}",
             "<ops.model.Application myapp>: {}",
             "<ops.model.Unit remoteapp1/0>: {'host': 'remoteapp1/0'}",
             "<ops.model.Application remoteapp1>: {'secret': 'cafedeadbeef'}"])

    def test_relation_data_modify_our(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'nothing'})
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        rel_db1.data[self.model.unit]['host'] = 'bar'
        self.assertEqual(rel_db1.data[self.model.unit]['host'], 'bar')

        self.assertBackendCalls([
            ('relation_get', relation_id, 'myapp/0', False),
            ('relation_set', relation_id, 'host', 'bar', False),
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

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp', True),
            ('is_leader',),
            ('relation_set', relation_id, 'password', 'foo', True),
        ])

    def test_app_relation_data_modify_local_as_minion(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp', {'password': 'deadbeefcafe'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.harness.set_leader(False)
        self.resetBackendCalls()

        local_app = self.model.unit.app

        rel_db1 = self.model.get_relation('db1')
        self.assertEqual(rel_db1.data[local_app], {'password': 'deadbeefcafe'})

        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[local_app]['password'] = 'foobar'

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp', True),
            ('is_leader',),
        ])

    def test_relation_data_del_key(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
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
            ('relation_set', relation_id, 'host', '', False),
        ])

    def test_relation_data_del_missing_key(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'bar'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        rel_db1.data[self.model.unit]['port'] = ''   # Same as a delete, should not fail.
        self.assertNotIn('port', rel_db1.data[self.model.unit])
        self.assertEqual({'host': 'bar'}, self.harness.get_relation_data(relation_id, 'myapp/0'))

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp/0', False),
            ('relation_set', relation_id, 'port', '', False),
        ])

    def test_relation_set_fail(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'myapp-0'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls()

        backend = self.harness._backend
        # TODO: jam 2020-03-06 This is way too much information about relation_set
        #       The original test forced 'relation-set' to return exit code 2,
        #       but there was nothing illegal about the data that was being set,
        #       for us to properly test the side effects of relation-set failing.

        def broken_relation_set(relation_id, key, value, is_app):
            backend._calls.append(('relation_set', relation_id, key, value, is_app))
            raise ops.model.ModelError()
        backend.relation_set = broken_relation_set

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
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
            ('relation_set', relation_id, 'host', 'bar', False),
            ('relation_set', relation_id, 'host', '', False),
        ])

    def test_relation_data_type_check(self):
        relation_id = self.harness.add_relation('db1', 'remoteapp1')
        self.harness.update_relation_data(relation_id, 'myapp/0', {'host': 'myapp-0'})
        self.harness.add_relation_unit(relation_id, 'remoteapp1/0')
        self.resetBackendCalls()

        rel_db1 = self.model.get_relation('db1')
        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = 1
        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = {'foo': 'bar'}
        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = None
        # No data has actually been changed
        self.assertEqual(dict(rel_db1.data[self.model.unit]), {'host': 'myapp-0'})

        self.assertBackendCalls([
            ('relation_ids', 'db1'),
            ('relation_list', relation_id),
            ('relation_get', relation_id, 'myapp/0', False),
        ])

    def test_config(self):
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

        with self.assertRaises(RuntimeError):
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
        # TODO: (jam) 2020-05-07 Harness doesn't yet expose storage-get issue #263
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

    def resetBackendCalls(self):
        self.harness._get_backend_calls(reset=True)

    def assertBackendCalls(self, expected, *, reset=True):
        self.assertEqual(expected, self.harness._get_backend_calls(reset=reset))


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

    def test_invalid_keys(self):
        # Basic validation for passing invalid keys.
        for name in (object, 0):
            with self.assertRaises(ops.model.ModelError):
                self.model.get_binding(name)

    def test_dead_relations(self):
        fake_script(
            self,
            'network-get',
            '''
                if [ "$1" = db0 ] && [ "$2" = --format=json ]; then
                    echo '{}'
                else
                    echo ERROR invalid value "$2" for option -r: relation not found >&2
                    exit 2
                fi
            '''.format(self.network_get_out))
        # Validate the behavior for dead relations.
        binding = ops.model.Binding('db0', 42, self.model._backend)
        self.assertEqual(binding.network.bind_address, ipaddress.ip_address('192.0.2.2'))
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['network-get', 'db0', '-r', '42', '--format=json'],
            ['network-get', 'db0', '--format=json'],
        ])

    def test_binding_by_relation_name(self):
        fake_script(self, 'network-get',
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(self.network_get_out))
        binding_name = 'db0'
        expected_calls = [['network-get', 'db0', '--format=json']]

        binding = self.model.get_binding(binding_name)
        self._check_binding_data(binding_name, binding)
        self.assertEqual(fake_script_calls(self, clear=True), expected_calls)

    def test_binding_by_relation(self):
        fake_script(self, 'network-get',
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(self.network_get_out))
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
                            'hostname':  '',
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
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(network_get_out))
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
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(network_data))
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.interfaces, [])

    def test_empty_bind_addresses(self):
        network_data = json.dumps({'bind-addresses': [{}]})
        fake_script(self, 'network-get',
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(network_data))
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
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(network_data))
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
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(network_data))
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
                    '''[ "$1" = db0 ] && echo '{}' || exit 1'''.format(network_data))
        binding_name = 'db0'
        binding = self.model.get_binding(self.model.get_relation(binding_name))
        self.assertEqual(binding.network.egress_subnets, [])


class TestModelBackend(unittest.TestCase):

    def setUp(self):
        self._backend = None

    @property
    def backend(self):
        if self._backend is None:
            self._backend = ops.model._ModelBackend('myapp/0')
        return self._backend

    def test_relation_get_set_is_app_arg(self):
        # No is_app provided.
        with self.assertRaises(TypeError):
            self.backend.relation_set(1, 'fookey', 'barval')

        with self.assertRaises(TypeError):
            self.backend.relation_get(1, 'fooentity')

        # Invalid types for is_app.
        for is_app_v in [None, 1, 2.0, 'a', b'beef']:
            with self.assertRaises(TypeError):
                self.backend.relation_set(1, 'fookey', 'barval', is_app=is_app_v)

            with self.assertRaises(TypeError):
                self.backend.relation_get(1, 'fooentity', is_app=is_app_v)

    def test_is_leader_refresh(self):
        meta = ops.charm.CharmMeta.from_yaml('''
            name: myapp
        ''')
        model = ops.model.Model(meta, self.backend)
        fake_script(self, 'is-leader', 'echo false')
        self.assertFalse(model.unit.is_leader())

        # Change the leadership status
        fake_script(self, 'is-leader', 'echo true')
        # If you don't force it, we don't check, so we won't see the change
        self.assertFalse(model.unit.is_leader())
        # If we force a recheck, then we notice
        self.backend._leader_check_time = None
        self.assertTrue(model.unit.is_leader())

        # Force a recheck without changing the leadership status.
        fake_script(self, 'is-leader', 'echo true')
        self.backend._leader_check_time = None
        self.assertTrue(model.unit.is_leader())

    def test_relation_tool_errors(self):
        self.addCleanup(os.environ.pop, 'JUJU_VERSION', None)
        os.environ['JUJU_VERSION'] = '2.8.0'
        err_msg = 'ERROR invalid value "$2" for option -r: relation not found'

        test_cases = [(
            lambda: fake_script(self, 'relation-list', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.relation_list(3),
            ops.model.ModelError,
            [['relation-list', '-r', '3', '--format=json']],
        ), (
            lambda: fake_script(self, 'relation-list', 'echo {} >&2 ; exit 2'.format(err_msg)),
            lambda: self.backend.relation_list(3),
            ops.model.RelationNotFoundError,
            [['relation-list', '-r', '3', '--format=json']],
        ), (
            lambda: fake_script(self, 'relation-set', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=False),
            ops.model.ModelError,
            [['relation-set', '-r', '3', 'foo=bar']],
        ), (
            lambda: fake_script(self, 'relation-set', 'echo {} >&2 ; exit 2'.format(err_msg)),
            lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=False),
            ops.model.RelationNotFoundError,
            [['relation-set', '-r', '3', 'foo=bar']],
        ), (
            lambda: None,
            lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=True),
            ops.model.RelationNotFoundError,
            [['relation-set', '-r', '3', 'foo=bar', '--app']],
        ), (
            lambda: fake_script(self, 'relation-get', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
            ops.model.ModelError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--format=json']],
        ), (
            lambda: fake_script(self, 'relation-get', 'echo {} >&2 ; exit 2'.format(err_msg)),
            lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
            ops.model.RelationNotFoundError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--format=json']],
        ), (
            lambda: None,
            lambda: self.backend.relation_get(3, 'remote/0', is_app=True),
            ops.model.RelationNotFoundError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--app', '--format=json']],
        )]

        for i, (do_fake, run, exception, calls) in enumerate(test_cases):
            with self.subTest(i):
                do_fake()
                with self.assertRaises(exception):
                    run()
                self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_relation_get_juju_version_quirks(self):
        self.addCleanup(os.environ.pop, 'JUJU_VERSION', None)

        fake_script(self, 'relation-get', '''echo '{"foo": "bar"}' ''')

        # on 2.7.0+, things proceed as expected
        for v in ['2.8.0', '2.7.0']:
            with self.subTest(v):
                os.environ['JUJU_VERSION'] = v
                rel_data = self.backend.relation_get(1, 'foo/0', is_app=True)
                self.assertEqual(rel_data, {"foo": "bar"})
                calls = [' '.join(i) for i in fake_script_calls(self, clear=True)]
                self.assertEqual(calls, ['relation-get -r 1 - foo/0 --app --format=json'])

        # before 2.7.0, it just fails (no --app support)
        os.environ['JUJU_VERSION'] = '2.6.9'
        with self.assertRaisesRegex(RuntimeError, 'not supported on Juju version 2.6.9'):
            self.backend.relation_get(1, 'foo/0', is_app=True)
        self.assertEqual(fake_script_calls(self), [])

    def test_relation_set_juju_version_quirks(self):
        self.addCleanup(os.environ.pop, 'JUJU_VERSION', None)

        fake_script(self, 'relation-set', 'exit 0')

        # on 2.7.0+, things proceed as expected
        for v in ['2.8.0', '2.7.0']:
            with self.subTest(v):
                os.environ['JUJU_VERSION'] = v
                self.backend.relation_set(1, 'foo', 'bar', is_app=True)
                calls = [' '.join(i) for i in fake_script_calls(self, clear=True)]
                self.assertEqual(calls, ['relation-set -r 1 foo=bar --app'])

        # before 2.7.0, it just fails always (no --app support)
        os.environ['JUJU_VERSION'] = '2.6.9'
        with self.assertRaisesRegex(RuntimeError, 'not supported on Juju version 2.6.9'):
            self.backend.relation_set(1, 'foo', 'bar', is_app=True)
        self.assertEqual(fake_script_calls(self), [])

    def test_status_get(self):
        # taken from actual Juju output
        content = '{"message": "", "status": "unknown", "status-data": {}}'
        fake_script(self, 'status-get', "echo '{}'".format(content))
        s = self.backend.status_get(is_app=False)
        self.assertEqual(s['status'], "unknown")
        self.assertEqual(s['message'], "")
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
        fake_script(self, 'status-get', "echo '{}'".format(content))
        s = self.backend.status_get(is_app=True)
        self.assertEqual(s['status'], "maintenance")
        self.assertEqual(s['message'], "installing")
        self.assertEqual(fake_script_calls(self, clear=True), [
            ['status-get', '--include-data', '--application=False', '--format=json'],
            ['status-get', '--include-data', '--application=True', '--format=json'],
        ])

    def test_status_is_app_forced_kwargs(self):
        fake_script(self, 'status-get', 'exit 1')
        fake_script(self, 'status-set', 'exit 1')

        test_cases = (
            lambda: self.backend.status_get(False),
            lambda: self.backend.status_get(True),
            lambda: self.backend.status_set('active', '', False),
            lambda: self.backend.status_set('active', '', True),
        )

        for case in test_cases:
            with self.assertRaises(TypeError):
                case()

    def test_local_set_invalid_status(self):
        # juju return exit code 1 if you ask to set status to 'unknown'
        meta = ops.charm.CharmMeta.from_yaml('''
            name: myapp
        ''')
        model = ops.model.Model(meta, self.backend)
        fake_script(self, 'status-set', 'exit 1')
        fake_script(self, 'is-leader', 'echo true')

        with self.assertRaises(ops.model.ModelError):
            model.unit.status = ops.model.UnknownStatus()

        self.assertEqual(fake_script_calls(self, True), [
            ['status-set', '--application=False', 'unknown', ''],
        ])

        with self.assertRaises(ops.model.ModelError):
            model.app.status = ops.model.UnknownStatus()

        # A leadership check is needed for application status.
        self.assertEqual(fake_script_calls(self, True), [
            ['is-leader', '--format=json'],
            ['status-set', '--application=True', 'unknown', ''],
        ])

    def test_status_set_is_app_not_bool_raises(self):
        for is_app_v in [None, 1, 2.0, 'a', b'beef', object]:
            with self.assertRaises(TypeError):
                self.backend.status_set(ops.model.ActiveStatus, is_app=is_app_v)

    def test_storage_tool_errors(self):
        test_cases = [(
            lambda: fake_script(self, 'storage-list', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_list('foobar'),
            ops.model.ModelError,
            [['storage-list', 'foobar', '--format=json']],
        ), (
            lambda: fake_script(self, 'storage-get', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_get('foobar', 'someattr'),
            ops.model.ModelError,
            [['storage-get', '-s', 'foobar', 'someattr', '--format=json']],
        ), (
            lambda: fake_script(self, 'storage-add', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_add('foobar', count=2),
            ops.model.ModelError,
            [['storage-add', 'foobar=2']],
        ), (
            lambda: fake_script(self, 'storage-add', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_add('foobar', count=object),
            TypeError,
            [],
        ), (
            lambda: fake_script(self, 'storage-add', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.storage_add('foobar', count=True),
            TypeError,
            [],
        )]
        for do_fake, run, exception, calls in test_cases:
            do_fake()
            with self.assertRaises(exception):
                run()
            self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_network_get(self):
        network_get_out = '''{
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
}'''
        fake_script(self, 'network-get',
                    '''[ "$1" = deadbeef ] && echo '{}' || exit 1'''.format(network_get_out))
        network_info = self.backend.network_get('deadbeef')
        self.assertEqual(network_info, json.loads(network_get_out))
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['network-get', 'deadbeef', '--format=json']])

        network_info = self.backend.network_get('deadbeef', 1)
        self.assertEqual(network_info, json.loads(network_get_out))
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['network-get', 'deadbeef', '-r', '1', '--format=json']])

    def test_network_get_errors(self):
        err_no_endpoint = 'ERROR no network config found for binding "$2"'
        err_no_rel = 'ERROR invalid value "$3" for option -r: relation not found'

        test_cases = [(
            lambda: fake_script(self, 'network-get',
                                'echo {} >&2 ; exit 1'.format(err_no_endpoint)),
            lambda: self.backend.network_get("deadbeef"),
            ops.model.ModelError,
            [['network-get', 'deadbeef', '--format=json']],
        ), (
            lambda: fake_script(self, 'network-get', 'echo {} >&2 ; exit 2'.format(err_no_rel)),
            lambda: self.backend.network_get("deadbeef", 3),
            ops.model.RelationNotFoundError,
            [['network-get', 'deadbeef', '-r', '3', '--format=json']],
        )]
        for do_fake, run, exception, calls in test_cases:
            do_fake()
            with self.assertRaises(exception):
                run()
            self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_action_get_error(self):
        fake_script(self, 'action-get', '')
        fake_script(self, 'action-get', 'echo fooerror >&2 ; exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.action_get()
        calls = [['action-get', '--format=json']]
        self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_action_set_error(self):
        fake_script(self, 'action-get', '')
        fake_script(self, 'action-set', 'echo fooerror >&2 ; exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.action_set(OrderedDict([('foo', 'bar'), ('dead', 'beef cafe')]))
        calls = [["action-set", "foo=bar", "dead=beef cafe"]]
        self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_action_log_error(self):
        fake_script(self, 'action-get', '')
        fake_script(self, 'action-log', 'echo fooerror >&2 ; exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.action_log('log-message')
        calls = [["action-log", "log-message"]]
        self.assertEqual(fake_script_calls(self, clear=True), calls)

    def test_action_get(self):
        fake_script(self, 'action-get', """echo '{"foo-name": "bar", "silent": false}'""")
        params = self.backend.action_get()
        self.assertEqual(params['foo-name'], 'bar')
        self.assertEqual(params['silent'], False)
        self.assertEqual(fake_script_calls(self), [['action-get', '--format=json']])

    def test_action_set(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-set', 'exit 0')
        self.backend.action_set(OrderedDict([('x', 'dead beef'), ('y', 1)]))
        self.assertEqual(fake_script_calls(self), [['action-set', 'x=dead beef', 'y=1']])

    def test_action_fail(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-fail', 'exit 0')
        self.backend.action_fail('error 42')
        self.assertEqual(fake_script_calls(self), [['action-fail', 'error 42']])

    def test_action_log(self):
        fake_script(self, 'action-get', 'exit 1')
        fake_script(self, 'action-log', 'exit 0')
        self.backend.action_log('progress: 42%')
        self.assertEqual(fake_script_calls(self), [['action-log', 'progress: 42%']])

    def test_application_version_set(self):
        fake_script(self, 'application-version-set', 'exit 0')
        self.backend.application_version_set('1.2b3')
        self.assertEqual(fake_script_calls(self), [['application-version-set', '--', '1.2b3']])

    def test_application_version_set_invalid(self):
        fake_script(self, 'application-version-set', 'exit 0')
        with self.assertRaises(TypeError):
            self.backend.application_version_set(2)
        with self.assertRaises(TypeError):
            self.backend.application_version_set()
        self.assertEqual(fake_script_calls(self), [])

    def test_juju_log(self):
        fake_script(self, 'juju-log', 'exit 0')
        self.backend.juju_log('WARNING', 'foo')
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['juju-log', '--log-level', 'WARNING', '--', 'foo']])

        with self.assertRaises(TypeError):
            self.backend.juju_log('DEBUG')
        self.assertEqual(fake_script_calls(self, clear=True), [])

        fake_script(self, 'juju-log', 'exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.juju_log('BAR', 'foo')
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['juju-log', '--log-level', 'BAR', '--', 'foo']])

    def test_valid_metrics(self):
        fake_script(self, 'add-metric', 'exit 0')
        test_cases = [(
            OrderedDict([('foo', 42), ('b-ar', 4.5), ('ba_-z', 4.5), ('a', 1)]),
            OrderedDict([('de', 'ad'), ('be', 'ef_ -')]),
            [['add-metric', '--labels', 'de=ad,be=ef_ -',
              'foo=42', 'b-ar=4.5', 'ba_-z=4.5', 'a=1']]
        ), (
            OrderedDict([('foo1', 0), ('b2r', 4.5)]),
            OrderedDict([('d3', 'aд'), ('b33f', '3_ -')]),
            [['add-metric', '--labels', 'd3=aд,b33f=3_ -', 'foo1=0', 'b2r=4.5']],
        )]
        for metrics, labels, expected_calls in test_cases:
            self.backend.add_metrics(metrics, labels)
            self.assertEqual(fake_script_calls(self, clear=True), expected_calls)

    def test_invalid_metric_names(self):
        invalid_inputs = [
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
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_values(self):
        invalid_inputs = [
            ({'a': float('+inf')}, {}),
            ({'a': float('-inf')}, {}),
            ({'a': float('nan')}, {}),
            ({'foo': 'bar'}, {}),
            ({'foo': '1O'}, {}),
        ]
        for metrics, labels in invalid_inputs:
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_labels(self):
        invalid_inputs = [
            ({'foo': 4.2}, {'': 'baz'}),
            ({'foo': 4.2}, {',bar': 'baz'}),
            ({'foo': 4.2}, {'b=a=r': 'baz'}),
            ({'foo': 4.2}, {'BAЯ': 'baz'}),
        ]
        for metrics, labels in invalid_inputs:
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)

    def test_invalid_metric_label_values(self):
        invalid_inputs = [
            ({'foo': 4.2}, {'bar': ''}),
            ({'foo': 4.2}, {'bar': 'b,az'}),
            ({'foo': 4.2}, {'bar': 'b=az'}),
        ]
        for metrics, labels in invalid_inputs:
            with self.assertRaises(ops.model.ModelError):
                self.backend.add_metrics(metrics, labels)


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
