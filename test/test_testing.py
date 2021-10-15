# Copyright 2019-2020 Canonical Ltd.
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

import importlib
import inspect
import pathlib
import shutil
import sys
import tempfile
import textwrap
import unittest

import yaml

from ops import pebble
from ops.charm import CharmBase, PebbleReadyEvent, RelationEvent
from ops.framework import Object
from ops.model import (
    ActiveStatus,
    Application,
    MaintenanceStatus,
    ModelError,
    RelationNotFoundError,
    Unit,
    UnknownStatus,
    _ModelBackend,
)
from ops.testing import Harness, _TestingPebbleClient


class TestHarness(unittest.TestCase):

    def test_add_relation(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        backend = harness._backend
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id), [])
        # Make sure the initial data bags for our app and unit are empty.
        self.assertEqual(backend.relation_get(rel_id, 'test-app', is_app=True), {})
        self.assertEqual(backend.relation_get(rel_id, 'test-app/0', is_app=False), {})

    def test_add_relation_and_unit(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        backend = harness._backend
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id), ['postgresql/0'])
        self.assertEqual(
            backend.relation_get(rel_id, 'postgresql/0', is_app=False),
            {'foo': 'bar'})

    def test_add_relation_with_remote_app_data(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        remote_app = 'postgresql'
        rel_id = harness.add_relation('db', remote_app)
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        self.assertIsInstance(rel_id, int)
        backend = harness._backend
        self.assertEqual([rel_id], backend.relation_ids('db'))
        self.assertEqual({'app': 'data'}, backend.relation_get(rel_id, remote_app, is_app=True))

    def test_add_relation_with_our_initial_data(self):

        class InitialDataTester(CharmBase):
            """Record the relation-changed events."""

            def __init__(self, framework):
                super().__init__(framework)
                self.observed_events = []
                self.framework.observe(self.on.db_relation_changed, self._on_db_relation_changed)

            def _on_db_relation_changed(self, event):
                self.observed_events.append(event)

        # language=YAML
        harness = Harness(InitialDataTester, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v1'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.1'})
        backend = harness._backend
        self.assertEqual({'k': 'v1'}, backend.relation_get(rel_id, 'test-app', is_app=True))
        self.assertEqual({'ingress-address': '192.0.2.1'},
                         backend.relation_get(rel_id, 'test-app/0', is_app=False))

        harness.begin()
        self.assertEqual({'k': 'v1'}, backend.relation_get(rel_id, 'test-app', is_app=True))
        self.assertEqual({'ingress-address': '192.0.2.1'},
                         backend.relation_get(rel_id, 'test-app/0', is_app=False))
        # Make sure no relation-changed events are emitted for our own data bags.
        self.assertEqual([], harness.charm.observed_events)

        # A remote unit can still update our app relation data bag since our unit is not a leader.
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v2'})
        # And we get an event
        self.assertEqual([], harness.charm.observed_events)
        # We can also update our own relation data, even if it is a bit 'cheaty'
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.2'})
        # But no event happens

        # Updating our data app relation data bag and our unit data bag does not generate events.
        harness.set_leader(True)
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v3'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.2'})
        self.assertEqual([], harness.charm.observed_events)

    def test_add_peer_relation_with_initial_data_leader(self):

        class InitialDataTester(CharmBase):
            """Record the relation-changed events."""

            def __init__(self, framework):
                super().__init__(framework)
                self.observed_events = []
                self.framework.observe(self.on.cluster_relation_changed,
                                       self._on_cluster_relation_changed)

            def _on_cluster_relation_changed(self, event):
                self.observed_events.append(event)

        # language=YAML
        harness = Harness(InitialDataTester, meta='''
            name: test-app
            peers:
                cluster:
                    interface: cluster
            ''')
        self.addCleanup(harness.cleanup)
        # TODO: dmitriis 2020-04-07 test a minion unit and initial peer relation app data
        # events when the harness begins to emit events for initial data.
        harness.set_leader(is_leader=True)
        rel_id = harness.add_relation('cluster', 'test-app')
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.1'})
        backend = harness._backend
        self.assertEqual({'k': 'v'}, backend.relation_get(rel_id, 'test-app', is_app=True))
        self.assertEqual({'ingress-address': '192.0.2.1'},
                         backend.relation_get(rel_id, 'test-app/0', is_app=False))

        harness.begin()
        self.assertEqual({'k': 'v'}, backend.relation_get(rel_id, 'test-app', is_app=True))
        self.assertEqual({'ingress-address': '192.0.2.1'},
                         backend.relation_get(rel_id, 'test-app/0', is_app=False))
        # Make sure no relation-changed events are emitted for our own data bags.
        self.assertEqual([], harness.charm.observed_events)

        # Updating our app relation data bag and our unit data bag does not trigger events
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v2'})
        harness.update_relation_data(rel_id, 'test-app/0', {'ingress-address': '192.0.2.2'})
        self.assertEqual([], harness.charm.observed_events)

        # If our unit becomes a minion, updating app relation data indirectly becomes possible
        # and our charm gets notifications.
        harness.set_leader(False)
        harness.update_relation_data(rel_id, 'test-app', {'k': 'v3'})
        self.assertEqual({'k': 'v3'}, backend.relation_get(rel_id, 'test-app', is_app=True))
        self.assertTrue(len(harness.charm.observed_events), 1)
        self.assertIsInstance(harness.charm.observed_events[0], RelationEvent)

    def test_remove_relation(self):
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # First create a relation
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        backend = harness._backend
        # Check relation was created
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id), ['postgresql/0'])
        harness.charm.get_changes(reset=True)  # created event ignored
        # Now remove relation
        harness.remove_relation(rel_id)
        # Check relation no longer exists
        self.assertEqual(backend.relation_ids('db'), [])
        self.assertRaises(RelationNotFoundError, backend.relation_list, rel_id)
        # Check relation broken event is raised with correct data
        changes = harness.charm.get_changes()
        self.assertEqual(changes[0],
                         {'name': 'relation-departed',
                          'relation': 'db',
                          'data': {'app': 'postgresql',
                                   'unit': 'postgresql/0',
                                   'relation_id': 0}})
        self.assertEqual(changes[1],
                         {'name': 'relation-broken',
                          'relation': 'db',
                          'data': {'app': 'postgresql',
                                   'unit': None,
                                   'relation_id': rel_id}})

    def test_remove_specific_relation_id(self):
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')

        # Create the first relation
        rel_id_1 = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id_1, int)
        harness.add_relation_unit(rel_id_1, 'postgresql/0')
        backend = harness._backend
        # Check relation was created
        self.assertIn(rel_id_1, backend.relation_ids('db'))
        self.assertEqual(backend.relation_list(rel_id_1), ['postgresql/0'])
        harness.charm.get_changes(reset=True)  # created event ignored

        # Create the second relation
        rel_id_2 = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id_2, int)
        harness.add_relation_unit(rel_id_2, 'postgresql/1')
        backend = harness._backend
        # Check relation was created and both relations exist
        self.assertIn(rel_id_1, backend.relation_ids('db'))
        self.assertIn(rel_id_2, backend.relation_ids('db'))
        self.assertEqual(backend.relation_list(rel_id_2), ['postgresql/1'])
        harness.charm.get_changes(reset=True)  # created event ignored

        # Now remove second relation
        harness.remove_relation(rel_id_2)
        # Check second relation no longer exists but first does
        self.assertEqual(backend.relation_ids('db'), [rel_id_1])
        self.assertRaises(RelationNotFoundError, backend.relation_list, rel_id_2)

        # Check relation broken event is raised with correct data
        changes = harness.charm.get_changes()
        self.assertEqual(changes[0],
                         {'name': 'relation-departed',
                          'relation': 'db',
                          'data': {'app': 'postgresql',
                                   'unit': 'postgresql/1',
                                   'relation_id': rel_id_2}})
        self.assertEqual(changes[1],
                         {'name': 'relation-broken',
                          'relation': 'db',
                          'data': {'app': 'postgresql',
                                   'unit': None,
                                   'relation_id': rel_id_2}})

    def test_removing_invalid_relation_id_raises_exception(self):
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # First create a relation
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        backend = harness._backend
        # Check relation was created
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id), ['postgresql/0'])
        harness.charm.get_changes(reset=True)  # created event ignored
        # Check exception is raised if relation id is invalid
        with self.assertRaises(RelationNotFoundError):
            harness.remove_relation(rel_id + 1)

    def test_remove_relation_unit(self):
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # First add a relation and unit
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        # Check relation and unit were created
        backend = harness._backend
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id), ['postgresql/0'])
        harness.charm.get_changes(reset=True)  # ignore relation created events
        relation = harness.charm.model.get_relation('db')
        self.assertEqual(len(relation.units), 1)
        # Check relation data is correct
        rel_unit = harness.charm.model.get_unit('postgresql/0')
        self.assertEqual(relation.data[rel_unit]['foo'], 'bar')
        # Instruct the charm to record the relation data it sees in the list of changes
        harness.charm.record_relation_data_on_events = True
        # Now remove unit
        harness.remove_relation_unit(rel_id, 'postgresql/0')
        # Check relation still exists
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        # Check removed unit does not exist
        self.assertEqual(backend.relation_list(rel_id), [])
        # Check the unit is actually removed from the relations the model knows about
        self.assertEqual(len(harness.charm.model.get_relation('db').units), 0)
        self.assertFalse(rel_unit in harness.charm.model.get_relation('db').data)
        # Check relation departed was raised with correct data
        self.assertEqual(harness.charm.get_changes()[0],
                         {'name': 'relation-departed',
                          'relation': 'db',
                          'data': {'app': 'postgresql',
                                   'unit': 'postgresql/0',
                                   'relation_id': 0,
                                   'relation_data': {'test-app/0': {},
                                                     'test-app': {},
                                                     'postgresql/0': {'foo': 'bar'},
                                                     'postgresql': {}}}})

    def test_removing_relation_removes_remote_app_data(self):
        # language=YAML
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation and update app data
        remote_app = 'postgresql'
        rel_id = harness.add_relation('db', remote_app)
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        self.assertIsInstance(rel_id, int)
        # Check relation app data exists
        backend = harness._backend
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual({'app': 'data'}, backend.relation_get(rel_id, remote_app, is_app=True))
        harness.remove_relation(rel_id)
        # Check relation and app data are removed
        self.assertEqual(backend.relation_ids('db'), [])
        self.assertRaises(RelationNotFoundError, backend.relation_get,
                          rel_id, remote_app, is_app=True)

    def test_removing_relation_refreshes_charm_model(self):
        # language=YAML
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation and update app data
        remote_app = 'postgresql'
        rel_id = harness.add_relation('db', remote_app)
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        self.assertIsInstance(rel_id, int)
        self.assertIsNotNone(self._find_relation_in_model_by_id(harness, rel_id))

        # Check relation app data exists
        backend = harness._backend
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual({'app': 'data'}, backend.relation_get(rel_id, remote_app, is_app=True))
        harness.remove_relation(rel_id)
        self.assertIsNone(self._find_relation_in_model_by_id(harness, rel_id))

    def _find_relation_in_model_by_id(self, harness, rel_id):
        for relations in harness.charm.model.relations.values():
            for relation in relations:
                if rel_id == relation.id:
                    return relation
        return None

    def test_removing_relation_unit_removes_data_also(self):
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation and unit with data
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        # Check relation, unit and data exist
        backend = harness._backend
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id), ['postgresql/0'])
        self.assertEqual(
            backend.relation_get(rel_id, 'postgresql/0', is_app=False),
            {'foo': 'bar'})
        harness.charm.get_changes(reset=True)  # ignore relation created events
        # Remove unit but not relation
        harness.remove_relation_unit(rel_id, 'postgresql/0')
        # Check relation exists but unit and data are removed
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id), [])
        self.assertRaises(KeyError,
                          backend.relation_get,
                          rel_id,
                          'postgresql/0',
                          is_app=False)
        # Check relation departed was raised with correct data
        self.assertEqual(harness.charm.get_changes()[0],
                         {'name': 'relation-departed',
                          'relation': 'db',
                          'data': {'app': 'postgresql',
                                   'unit': 'postgresql/0',
                                   'relation_id': rel_id}})

    def test_removing_relation_unit_does_not_remove_other_unit_and_data(self):
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        # Add a relation with two units with data
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.add_relation_unit(rel_id, 'postgresql/1')
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo0': 'bar0'})
        harness.update_relation_data(rel_id, 'postgresql/1', {'foo1': 'bar1'})
        # Check both unit and data are present
        backend = harness._backend
        self.assertEqual(backend.relation_ids('db'), [rel_id])
        self.assertEqual(backend.relation_list(rel_id),
                         ['postgresql/0', 'postgresql/1'])
        self.assertEqual(
            backend.relation_get(rel_id, 'postgresql/0', is_app=False),
            {'foo0': 'bar0'})
        self.assertEqual(
            backend.relation_get(rel_id, 'postgresql/1', is_app=False),
            {'foo1': 'bar1'})
        harness.charm.get_changes(reset=True)  # ignore relation created events
        # Remove only one unit
        harness.remove_relation_unit(rel_id, 'postgresql/1')
        # Check other unit and data still exists
        self.assertEqual(backend.relation_list(rel_id),
                         ['postgresql/0'])
        self.assertEqual(
            backend.relation_get(rel_id, 'postgresql/0', is_app=False),
            {'foo0': 'bar0'})
        # Check relation departed was raised with correct data
        self.assertEqual(harness.charm.get_changes()[0],
                         {'name': 'relation-departed',
                          'relation': 'db',
                          'data': {'app': 'postgresql',
                                   'unit': 'postgresql/1',
                                   'relation_id': rel_id}})

    def test_relation_events(self):
        harness = Harness(RelationEventCharm, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
        ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.charm.observe_relation_events('db')
        self.assertEqual(harness.charm.get_changes(), [])
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertEqual(
            harness.charm.get_changes(),
            [{'name': 'relation-created',
              'relation': 'db',
              'data': {
                  'app': 'postgresql',
                  'unit': None,
                  'relation_id': rel_id,
              }}])
        harness.add_relation_unit(rel_id, 'postgresql/0')
        self.assertEqual(
            harness.charm.get_changes(),
            [{'name': 'relation-joined',
              'relation': 'db',
              'data': {
                  'app': 'postgresql',
                  'unit': 'postgresql/0',
                  'relation_id': rel_id,
              }}])
        harness.update_relation_data(rel_id, 'postgresql', {'foo': 'bar'})
        self.assertEqual(
            harness.charm.get_changes(),
            [{'name': 'relation-changed',
              'relation': 'db',
              'data': {
                  'app': 'postgresql',
                  'unit': None,
                  'relation_id': rel_id,
              }}])
        harness.update_relation_data(rel_id, 'postgresql/0', {'baz': 'bing'})
        self.assertEqual(
            harness.charm.get_changes(),
            [{'name': 'relation-changed',
              'relation': 'db',
              'data': {
                  'app': 'postgresql',
                  'unit': 'postgresql/0',
                  'relation_id': rel_id,
              }}])

    def test_get_relation_data(self):
        charm_meta = '''
            name: test-app
            requires:
                db:
                    interface: pgsql
        '''
        harness = Harness(CharmBase, meta=charm_meta)
        self.addCleanup(harness.cleanup)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.update_relation_data(rel_id, 'postgresql', {'remote': 'data'})
        self.assertEqual(harness.get_relation_data(rel_id, 'test-app'), {})
        self.assertEqual(harness.get_relation_data(rel_id, 'test-app/0'), {})
        self.assertEqual(harness.get_relation_data(rel_id, 'test-app/1'), None)
        self.assertEqual(harness.get_relation_data(rel_id, 'postgresql'), {'remote': 'data'})
        with self.assertRaises(KeyError):
            # unknown relation id
            harness.get_relation_data(99, 'postgresql')

        meta = yaml.safe_load(charm_meta)
        t_app = Application('test-app', meta, harness._backend, None)
        t_unit0 = Unit('test-app/0', meta, harness._backend, {Application: t_app})
        t_unit1 = Unit('test-app/1', meta, harness._backend, {Application: t_app})
        self.assertEqual(harness.get_relation_data(rel_id, t_app), {})
        self.assertEqual(harness.get_relation_data(rel_id, t_unit0), {})
        self.assertEqual(harness.get_relation_data(rel_id, t_unit1), None)
        pg_app = Application('postgresql', meta, harness._backend, None)
        self.assertEqual(harness.get_relation_data(rel_id, pg_app), {'remote': 'data'})

    def test_create_harness_twice(self):
        metadata = '''
            name: my-charm
            requires:
              db:
                interface: pgsql
            '''
        harness1 = Harness(CharmBase, meta=metadata)
        self.addCleanup(harness1.cleanup)
        harness2 = Harness(CharmBase, meta=metadata)
        self.addCleanup(harness2.cleanup)
        harness1.begin()
        harness2.begin()
        helper1 = DBRelationChangedHelper(harness1.charm, "helper1")
        helper2 = DBRelationChangedHelper(harness2.charm, "helper2")
        rel_id = harness2.add_relation('db', 'postgresql')
        harness2.update_relation_data(rel_id, 'postgresql', {'key': 'value'})
        # Helper2 should see the event triggered by harness2, but helper1 should see no events.
        self.assertEqual(helper1.changes, [])
        self.assertEqual(helper2.changes, [(rel_id, 'postgresql')])

    def test_begin_twice(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        with self.assertRaises(RuntimeError):
            harness.begin()

    def test_update_relation_exposes_new_data(self):
        harness = Harness(CharmBase, meta='''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': 'data'})
        self.assertEqual(viewer.changes, [{'initial': 'data'}])
        harness.update_relation_data(rel_id, 'postgresql/0', {'new': 'value'})
        self.assertEqual(viewer.changes, [{'initial': 'data'},
                                          {'initial': 'data', 'new': 'value'}])

    def test_update_relation_no_local_unit_change_event(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        helper = DBRelationChangedHelper(harness.charm, "helper")
        rel_id = harness.add_relation('db', 'postgresql')
        rel = harness.charm.model.get_relation('db')
        rel.data[harness.charm.model.unit]['key'] = 'value'
        # there should be no event for updating our own data
        harness.update_relation_data(rel_id, 'my-charm/0', {'new': 'other'})
        # but the data will be updated.
        self.assertEqual({'key': 'value', 'new': 'other'}, rel.data[harness.charm.model.unit])

        rel.data[harness.charm.model.unit]['new'] = 'value'
        # Our unit data bag got updated.
        self.assertEqual(rel.data[harness.charm.model.unit]['new'], 'value')
        # But there were no changed events registered by our unit.
        self.assertEqual([], helper.changes)

    def test_update_peer_relation_no_local_unit_change_event(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: postgresql
            peers:
              db:
                interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        helper = DBRelationChangedHelper(harness.charm, "helper")
        rel_id = harness.add_relation('db', 'postgresql')

        rel = harness.charm.model.get_relation('db')
        rel.data[harness.charm.model.unit]['key'] = 'value'
        rel = harness.charm.model.get_relation('db')
        harness.update_relation_data(rel_id, 'postgresql/0', {'key': 'v1'})
        self.assertEqual({'key': 'v1'}, rel.data[harness.charm.model.unit])
        # Make sure there was no event
        self.assertEqual([], helper.changes)

        rel.data[harness.charm.model.unit]['key'] = 'v2'
        # Our unit data bag got updated.
        self.assertEqual({'key': 'v2'}, dict(rel.data[harness.charm.model.unit]))
        # But there were no changed events registered by our unit.
        self.assertEqual([], helper.changes)

        # Same for when our unit is a leader.
        harness.set_leader(is_leader=True)
        harness.update_relation_data(rel_id, 'postgresql/0', {'key': 'v3'})
        self.assertEqual({'key': 'v3'}, dict(rel.data[harness.charm.model.unit]))
        self.assertEqual([], helper.changes)

        rel.data[harness.charm.model.unit]['key'] = 'v4'
        self.assertEqual(rel.data[harness.charm.model.unit]['key'], 'v4')
        self.assertEqual([], helper.changes)

    def test_update_peer_relation_app_data(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: postgresql
            peers:
              db:
                interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.set_leader(is_leader=True)
        helper = DBRelationChangedHelper(harness.charm, "helper")
        rel_id = harness.add_relation('db', 'postgresql')
        rel = harness.charm.model.get_relation('db')
        rel.data[harness.charm.app]['key'] = 'value'
        harness.update_relation_data(rel_id, 'postgresql', {'key': 'v1'})
        self.assertEqual({'key': 'v1'}, rel.data[harness.charm.app])
        self.assertEqual([], helper.changes)

        rel.data[harness.charm.app]['key'] = 'v2'
        # Our unit data bag got updated.
        self.assertEqual(rel.data[harness.charm.model.app]['key'], 'v2')
        # But there were no changed events registered by our unit.
        self.assertEqual([], helper.changes)

        # If our unit is not a leader unit we get an update about peer app relation data changes.
        harness.set_leader(is_leader=False)
        harness.update_relation_data(rel_id, 'postgresql', {'k2': 'v2'})
        self.assertEqual(rel.data[harness.charm.model.app]['k2'], 'v2')
        self.assertEqual(helper.changes, [(0, 'postgresql')])

    def test_update_relation_no_local_app_change_event(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.set_leader(False)
        helper = DBRelationChangedHelper(harness.charm, "helper")
        rel_id = harness.add_relation('db', 'postgresql')
        # TODO: remove this as soon as https://github.com/canonical/operator/issues/175 is fixed.
        harness.add_relation_unit(rel_id, 'postgresql/0')
        self.assertEqual(helper.changes, [])

        harness.update_relation_data(rel_id, 'my-charm', {'new': 'value'})
        rel = harness.charm.model.get_relation('db')
        self.assertEqual(rel.data[harness.charm.app]['new'], 'value')

        # Our app data bag got updated.
        self.assertEqual(rel.data[harness.charm.model.app]['new'], 'value')
        # But there were no changed events registered by our unit.
        self.assertEqual(helper.changes, [])

    def test_update_relation_remove_data(self):
        harness = Harness(CharmBase, meta='''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': 'data'})
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': ''})
        self.assertEqual(viewer.changes, [{'initial': 'data'}, {}])

    def test_update_config(self):
        harness = Harness(RecordingCharm, config='''
            options:
                a:
                    description: a config option
                    type: string
                b:
                    description: another config option
                    type: int
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.update_config(key_values={'a': 'foo', 'b': 2})
        self.assertEqual(
            harness.charm.changes,
            [{'name': 'config-changed', 'data': {'a': 'foo', 'b': 2}}])
        harness.update_config(key_values={'b': 3})
        self.assertEqual(
            harness.charm.changes,
            [{'name': 'config-changed', 'data': {'a': 'foo', 'b': 2}},
             {'name': 'config-changed', 'data': {'a': 'foo', 'b': 3}}])
        # you can set config values to the empty string, you can use unset to actually remove items
        harness.update_config(key_values={'a': ''}, unset=set('b'))
        self.assertEqual(
            harness.charm.changes,
            [{'name': 'config-changed', 'data': {'a': 'foo', 'b': 2}},
             {'name': 'config-changed', 'data': {'a': 'foo', 'b': 3}},
             {'name': 'config-changed', 'data': {'a': ''}},
             ])

    def test_update_config_undefined_option(self):
        harness = Harness(RecordingCharm)
        self.addCleanup(harness.cleanup)
        harness.begin()
        with self.assertRaises(ValueError):
            harness.update_config(key_values={'nonexistent': 'foo'})

    def test_update_config_unset_boolean(self):
        harness = Harness(RecordingCharm, config='''
            options:
                a:
                    description: a config option
                    type: bool
                    default: False
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        # Check the default was set correctly
        self.assertEqual(harness.charm.config, {'a': False})
        # Set the boolean value to True
        harness.update_config(key_values={'a': True})
        self.assertEqual(harness.charm.changes, [{'name': 'config-changed', 'data': {'a': True}}])
        # Unset the boolean value
        harness.update_config(unset={'a'})
        self.assertEqual(
            harness.charm.changes,
            [{'name': 'config-changed', 'data': {'a': True}},
             {'name': 'config-changed', 'data': {'a': False}}])

    def test_set_leader(self):
        harness = Harness(RecordingCharm)
        self.addCleanup(harness.cleanup)
        # No event happens here
        harness.set_leader(False)
        harness.begin()
        self.assertFalse(harness.charm.model.unit.is_leader())
        harness.set_leader(True)
        self.assertEqual(harness.charm.get_changes(reset=True), [{'name': 'leader-elected'}])
        self.assertTrue(harness.charm.model.unit.is_leader())
        harness.set_leader(False)
        self.assertFalse(harness.charm.model.unit.is_leader())
        # No hook event when you lose leadership.
        # TODO: verify if Juju always triggers `leader-settings-changed` if you
        #   lose leadership.
        self.assertEqual(harness.charm.get_changes(reset=True), [])
        harness.disable_hooks()
        harness.set_leader(True)
        # No hook event if you have disabled them
        self.assertEqual(harness.charm.get_changes(reset=True), [])

    def test_relation_set_app_not_leader(self):
        harness = Harness(RecordingCharm, meta='''
            name: test-charm
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.set_leader(False)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        rel = harness.charm.model.get_relation('db')
        with self.assertRaises(ModelError):
            rel.data[harness.charm.app]['foo'] = 'bar'
        # The data has not actually been changed
        self.assertEqual(harness.get_relation_data(rel_id, 'test-charm'), {})
        harness.set_leader(True)
        rel.data[harness.charm.app]['foo'] = 'bar'
        self.assertEqual(harness.get_relation_data(rel_id, 'test-charm'), {'foo': 'bar'})

    def test_hooks_enabled_and_disabled(self):
        harness = Harness(
            RecordingCharm,
            meta='''
                    name: test-charm
                ''',
            config='''
                    options:
                        value:
                            type: string
                        third:
                            type: string
                    ''')
        self.addCleanup(harness.cleanup)
        # Before begin() there are no events.
        harness.update_config({'value': 'first'})
        # By default, after begin the charm is set up to receive events.
        harness.begin()
        harness.update_config({'value': 'second'})
        self.assertEqual(
            harness.charm.get_changes(reset=True),
            [{'name': 'config-changed', 'data': {'value': 'second'}}])
        # Once disabled, we won't see config-changed when we make an update
        harness.disable_hooks()
        harness.update_config({'third': '3'})
        self.assertEqual(harness.charm.get_changes(reset=True), [])
        harness.enable_hooks()
        harness.update_config({'value': 'fourth'})
        self.assertEqual(
            harness.charm.get_changes(reset=True),
            [{'name': 'config-changed', 'data': {'value': 'fourth', 'third': '3'}}])

    def test_hooks_disabled_contextmanager(self):
        harness = Harness(RecordingCharm, meta='''
                name: test-charm
                ''', config='''
                options:
                    value:
                        type: string
                    third:
                        type: string
            ''')
        self.addCleanup(harness.cleanup)
        # Before begin() there are no events.
        harness.update_config({'value': 'first'})
        # By default, after begin the charm is set up to receive events.
        harness.begin()
        harness.update_config({'value': 'second'})
        self.assertEqual(
            harness.charm.get_changes(reset=True),
            [{'name': 'config-changed', 'data': {'value': 'second'}}])
        # Once disabled, we won't see config-changed when we make an update
        with harness.hooks_disabled():
            harness.update_config({'third': '3'})
        self.assertEqual(harness.charm.get_changes(reset=True), [])
        harness.update_config({'value': 'fourth'})
        self.assertEqual(
            harness.charm.get_changes(reset=True),
            [{'name': 'config-changed', 'data': {'value': 'fourth', 'third': '3'}}])

    def test_hooks_disabled_nested_contextmanager(self):
        harness = Harness(RecordingCharm, meta='''
                name: test-charm
            ''', config='''
                options:
                    fifth:
                        type: string
                    sixth:
                        type: string
                ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        # Context manager can be nested, so a test using it can invoke a helper using it.
        with harness.hooks_disabled():
            with harness.hooks_disabled():
                harness.update_config({'fifth': '5'})
            harness.update_config({'sixth': '6'})
        self.assertEqual(harness.charm.get_changes(reset=True), [])

    def test_hooks_disabled_noop(self):
        harness = Harness(RecordingCharm, meta='''
                name: test-charm
            ''', config='''
            options:
                seventh:
                    type: string
                eighth:
                    type: string
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        # If hooks are already disabled, it is a no op, and on exit hooks remain disabled.
        harness.disable_hooks()
        with harness.hooks_disabled():
            harness.update_config({'seventh': '7'})
        harness.update_config({'eighth': '8'})
        self.assertEqual(harness.charm.get_changes(reset=True), [])

    def test_metadata_from_directory(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(tmp))
        metadata_filename = tmp / 'metadata.yaml'
        with metadata_filename.open('wt') as metadata:
            metadata.write(textwrap.dedent('''
            name: my-charm
            requires:
                db:
                    interface: pgsql
            '''))
        harness = self._get_dummy_charm_harness(tmp)
        harness.begin()
        self.assertEqual(list(harness.model.relations), ['db'])
        # The charm_dir also gets set
        self.assertEqual(harness.framework.charm_dir, tmp)

    def test_config_from_directory(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(tmp))
        config_filename = tmp / 'config.yaml'
        with config_filename.open('wt') as config:
            config.write(textwrap.dedent('''
            options:
                opt_str:
                    type: string
                    default: "val"
                opt_str_empty:
                    type: string
                    default: ""
                opt_null:
                    type: string
                    default: null
                opt_bool:
                    type: boolean
                    default: true
                opt_int:
                    type: int
                    default: 1
                opt_float:
                    type: float
                    default: 1.0
                opt_no_default:
                    type: string
            '''))
        harness = self._get_dummy_charm_harness(tmp)
        self.assertEqual(harness.model.config['opt_str'], 'val')
        self.assertEqual(harness.model.config['opt_str_empty'], '')
        self.assertIs(harness.model.config['opt_bool'], True)
        self.assertEqual(harness.model.config['opt_int'], 1)
        self.assertIsInstance(harness.model.config['opt_int'], int)
        self.assertEqual(harness.model.config['opt_float'], 1.0)
        self.assertIsInstance(harness.model.config['opt_float'], float)
        self.assertFalse('opt_null' in harness.model.config)
        self.assertIsNone(harness._defaults['opt_null'])
        self.assertIsNone(harness._defaults['opt_no_default'])

    def test_set_model_name(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
        ''')
        self.addCleanup(harness.cleanup)
        harness.set_model_name('foo')
        self.assertEqual('foo', harness.model.name)

    def test_set_model_name_after_begin(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
        ''')
        self.addCleanup(harness.cleanup)
        harness.set_model_name('bar')
        harness.begin()
        with self.assertRaises(RuntimeError):
            harness.set_model_name('foo')
        self.assertEqual(harness.model.name, 'bar')

    def test_set_model_uuid_after_begin(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
        ''')
        self.addCleanup(harness.cleanup)
        harness.set_model_name('bar')
        harness.set_model_uuid('96957e90-e006-11eb-ba80-0242ac130004')
        harness.begin()
        with self.assertRaises(RuntimeError):
            harness.set_model_uuid('af0479ea-e006-11eb-ba80-0242ac130004')
        self.assertEqual(harness.model.uuid, '96957e90-e006-11eb-ba80-0242ac130004')

    def test_set_model_info_after_begin(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
        ''')
        self.addCleanup(harness.cleanup)
        harness.set_model_info('foo', '96957e90-e006-11eb-ba80-0242ac130004')
        harness.begin()
        with self.assertRaises(RuntimeError):
            harness.set_model_info('bar', 'af0479ea-e006-11eb-ba80-0242ac130004')
        with self.assertRaises(RuntimeError):
            harness.set_model_info('bar')
        with self.assertRaises(RuntimeError):
            harness.set_model_info(uuid='af0479ea-e006-11eb-ba80-0242ac130004')
        with self.assertRaises(RuntimeError):
            harness.set_model_name('bar')
        with self.assertRaises(RuntimeError):
            harness.set_model_uuid('af0479ea-e006-11eb-ba80-0242ac130004')
        self.assertEqual(harness.model.name, 'foo')
        self.assertEqual(harness.model.uuid, '96957e90-e006-11eb-ba80-0242ac130004')

    def test_storage_add(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)

        stor_id = harness.add_storage("test")
        self.assertIsNotNone(stor_id)

        self.assertIn(str(stor_id), harness._backend.storage_list("test"))
        self.assertEqual("/test0", harness._backend.storage_get("test/0", "location"))

    def test_actions_from_directory(self):
        tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, str(tmp))
        actions_filename = tmp / 'actions.yaml'
        with actions_filename.open('wt') as actions:
            actions.write(textwrap.dedent('''
            test:
                description: a dummy action
            '''))
        harness = self._get_dummy_charm_harness(tmp)
        harness.begin()
        self.assertEqual(list(harness.framework.meta.actions), ['test'])
        # The charm_dir also gets set
        self.assertEqual(harness.framework.charm_dir, tmp)

    def _get_dummy_charm_harness(self, tmp):
        self._write_dummy_charm(tmp)
        charm_mod = importlib.import_module('testcharm')
        harness = Harness(charm_mod.MyTestingCharm)
        self.addCleanup(harness.cleanup)
        return harness

    def _write_dummy_charm(self, tmp):
        srcdir = tmp / 'src'
        srcdir.mkdir(0o755)
        charm_filename = srcdir / 'testcharm.py'
        with charm_filename.open('wt') as charmpy:
            # language=Python
            charmpy.write(textwrap.dedent('''
                from ops.charm import CharmBase
                class MyTestingCharm(CharmBase):
                    pass
                '''))
        orig = sys.path[:]
        sys.path.append(str(srcdir))

        def cleanup():
            sys.path = orig
            sys.modules.pop('testcharm')

        self.addCleanup(cleanup)

    def test_actions_passed_in(self):
        harness = Harness(
            CharmBase,
            meta='''
                name: test-app
            ''',
            actions='''
                test-action:
                    description: a dummy test action
            ''')
        self.addCleanup(harness.cleanup)
        self.assertEqual(list(harness.framework.meta.actions), ['test-action'])

    def test_relation_set_deletes(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        harness.set_leader(False)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.update_relation_data(rel_id, 'test-charm/0', {'foo': 'bar'})
        harness.add_relation_unit(rel_id, 'postgresql/0')
        rel = harness.charm.model.get_relation('db', rel_id)
        del rel.data[harness.charm.model.unit]['foo']
        self.assertEqual({}, harness.get_relation_data(rel_id, 'test-charm/0'))

    def test_set_workload_version(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        self.assertIsNone(harness.get_workload_version())
        harness.charm.model.unit.set_workload_version('1.2.3')
        self.assertEqual(harness.get_workload_version(), '1.2.3')

    def test_get_backend_calls(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        # No calls to the backend yet
        self.assertEqual(harness._get_backend_calls(), [])
        rel_id = harness.add_relation('db', 'postgresql')
        # update_relation_data ensures the cached data for the relation is wiped
        harness.update_relation_data(rel_id, 'test-charm/0', {'foo': 'bar'})
        self.assertEqual(
            harness._get_backend_calls(reset=True), [
                ('relation_ids', 'db'),
                ('relation_list', rel_id),
                ('relation_remote_app_name', 0),
            ])
        # add_relation_unit resets the relation_list, but doesn't trigger backend calls
        harness.add_relation_unit(rel_id, 'postgresql/0')
        self.assertEqual([], harness._get_backend_calls(reset=False))
        # however, update_relation_data does, because we are preparing relation-changed
        harness.update_relation_data(rel_id, 'postgresql/0', {'foo': 'bar'})
        self.assertEqual(
            harness._get_backend_calls(reset=False), [
                ('relation_ids', 'db'),
                ('relation_list', rel_id),
            ])
        # If we check again, they are still there, but now we reset it
        self.assertEqual(
            harness._get_backend_calls(reset=True), [
                ('relation_ids', 'db'),
                ('relation_list', rel_id),
            ])
        # And the calls are gone
        self.assertEqual(harness._get_backend_calls(), [])

    def test_get_backend_calls_with_kwargs(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            requires:
                db:
                    interface: pgsql
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        unit = harness.charm.model.unit
        # Reset the list, because we don't care what it took to get here
        harness._get_backend_calls(reset=True)
        unit.status = ActiveStatus()
        self.assertEqual(
            [('status_set', 'active', '', {'is_app': False})], harness._get_backend_calls())
        harness.set_leader(True)
        app = harness.charm.model.app
        harness._get_backend_calls(reset=True)
        app.status = ActiveStatus('message')
        self.assertEqual(
            [('is_leader',),
             ('status_set', 'active', 'message', {'is_app': True})],
            harness._get_backend_calls())

    def test_unit_status(self):
        harness = Harness(CharmBase, meta='name: test-app')
        self.addCleanup(harness.cleanup)
        harness.set_leader(True)
        harness.begin()
        # default status
        self.assertEqual(harness.model.unit.status, MaintenanceStatus(''))
        status = ActiveStatus('message')
        harness.model.unit.status = status
        self.assertEqual(harness.model.unit.status, status)

    def test_app_status(self):
        harness = Harness(CharmBase, meta='name: test-app')
        self.addCleanup(harness.cleanup)
        harness.set_leader(True)
        harness.begin()
        # default status
        self.assertEqual(harness.model.app.status, UnknownStatus())
        status = ActiveStatus('message')
        harness.model.app.status = status
        self.assertEqual(harness.model.app.status, status)

    def test_populate_oci_resources(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
              image2:
                type: oci-image
                description: "Another image."
            ''')
        self.addCleanup(harness.cleanup)
        harness.populate_oci_resources()
        path = harness.model.resources.fetch('image')
        self.assertEqual(path.name, 'contents.yaml')
        self.assertEqual(path.parent.name, 'image')
        with path.open('r') as resource_file:
            contents = yaml.safe_load(resource_file.read())
        self.assertEqual(contents['registrypath'], 'registrypath')
        self.assertEqual(contents['username'], 'username')
        self.assertEqual(contents['password'], 'password')
        path = harness.model.resources.fetch('image2')
        self.assertEqual(path.name, 'contents.yaml')
        self.assertEqual(path.parent.name, 'image2')

    def test_resource_folder_cleanup(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        harness.populate_oci_resources()
        path = harness.model.resources.fetch('image')
        self.assertTrue(path.exists())
        harness.cleanup()
        self.assertFalse(path.exists())
        self.assertFalse(path.parent.exists())
        self.assertFalse(path.parent.parent.exists())

    def test_add_oci_resource_custom(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        custom = {
            "registrypath": "custompath",
            "username": "custom_username",
            "password": "custom_password",
        }
        harness.add_oci_resource('image', custom)
        resource = harness.model.resources.fetch('image')
        with resource.open('r') as resource_file:
            contents = yaml.safe_load(resource_file.read())
        self.assertEqual(contents['registrypath'], 'custompath')
        self.assertEqual(contents['username'], 'custom_username')
        self.assertEqual(contents['password'], 'custom_password')

    def test_add_oci_resource_no_image(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        with self.assertRaises(RuntimeError):
            harness.add_oci_resource("image")
        with self.assertRaises(RuntimeError):
            harness.add_oci_resource("missing-resource")
        self.assertEqual(len(harness._backend._resources_map), 0)

    def test_add_resource_unknown(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        with self.assertRaises(RuntimeError):
            harness.add_resource('unknown', 'content')

    def test_add_resource_but_oci(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        with self.assertRaises(RuntimeError):
            harness.add_resource('image', 'content')

    def test_add_resource_string(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: file
                filename: foo.txt
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        harness.add_resource('image', 'foo contents\n')
        path = harness.model.resources.fetch('image')
        self.assertEqual(path.name, 'foo.txt')
        self.assertEqual(path.parent.name, 'image')
        with path.open('rt') as f:
            self.assertEqual('foo contents\n', f.read())

    def test_add_resource_bytes(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: file
                filename: foo.zip
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        raw_contents = b'\xff\xff\x00blah\n'
        harness.add_resource('image', raw_contents)
        path = harness.model.resources.fetch('image')
        self.assertEqual(path.name, 'foo.zip')
        self.assertEqual(path.parent.name, 'image')
        with path.open('rb') as f:
            self.assertEqual(raw_contents, f.read())

    def test_add_resource_unknown_filename(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        harness.add_resource('image', 'foo contents\n')
        path = harness.model.resources.fetch('image')
        self.assertEqual(path.name, 'image')
        self.assertEqual(path.parent.name, 'image')

    def test_get_pod_spec(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            ''')
        self.addCleanup(harness.cleanup)
        harness.set_leader(True)
        container_spec = {'container': 'spec'}
        k8s_resources = {'k8s': 'spec'}
        harness.model.pod.set_spec(container_spec, k8s_resources)
        self.assertEqual(harness.get_pod_spec(), (container_spec, k8s_resources))

    def test_begin_with_initial_hooks_no_relations(self):
        harness = Harness(RecordingCharm, meta='''
            name: test-app
            ''', config='''
            options:
                foo:
                    description: a config option
                    type: string
            ''')
        self.addCleanup(harness.cleanup)
        harness.update_config({'foo': 'bar'})
        harness.set_leader(True)
        self.assertIsNone(harness.charm)
        harness.begin_with_initial_hooks()
        self.assertIsNotNone(harness.charm)
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'leader-elected'},
                {'name': 'config-changed', 'data': {'foo': 'bar'}},
                {'name': 'start'},
            ]
        )

    def test_begin_with_initial_hooks_no_relations_not_leader(self):
        harness = Harness(RecordingCharm, meta='''
            name: test-app
            ''', config='''
            options:
                foo:
                    description: a config option
                    type: string
            ''')
        self.addCleanup(harness.cleanup)
        harness.update_config({'foo': 'bar'})
        self.assertIsNone(harness.charm)
        harness.begin_with_initial_hooks()
        self.assertIsNotNone(harness.charm)
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'leader-settings-changed'},
                {'name': 'config-changed', 'data': {'foo': 'bar'}},
                {'name': 'start'},
            ]
        )

    def test_begin_with_initial_hooks_with_peer_relation(self):
        class PeerCharm(RelationEventCharm):
            def __init__(self, framework):
                super().__init__(framework)
                self.observe_relation_events('peer')
        harness = Harness(PeerCharm, meta='''
            name: test-app
            peers:
              peer:
                interface: app-peer
            ''', config='''
            options:
                foo:
                    description: a config option
                    type: string
            ''')
        self.addCleanup(harness.cleanup)
        harness.update_config({'foo': 'bar'})
        self.assertIsNone(harness.charm)
        harness.begin_with_initial_hooks()
        self.assertIsNotNone(harness.charm)
        rel_id = harness.model.get_relation('peer').id
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'relation-created',
                 'relation': 'peer',
                 'data': {
                     'relation_id': rel_id,
                     'unit': None,
                     'app': 'test-app',
                 }},
                {'name': 'leader-settings-changed'},
                {'name': 'config-changed', 'data': {'foo': 'bar'}},
                {'name': 'start'},
            ])
        # With a single unit, no peer-relation-joined is fired

    def test_begin_with_initial_hooks_peer_relation_pre_defined(self):
        class PeerCharm(RelationEventCharm):
            def __init__(self, framework):
                super().__init__(framework)
                self.observe_relation_events('peer')
        harness = Harness(PeerCharm, meta='''
            name: test-app
            peers:
              peer:
                interface: app-peer
            ''')
        self.addCleanup(harness.cleanup)
        peer_rel_id = harness.add_relation('peer', 'test-app')
        harness.begin_with_initial_hooks()
        # If the peer relation is already defined by the user, we don't create the relation a
        # second time, but we do still fire relation-created.
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'relation-created',
                 'relation': 'peer',
                 'data': {
                     'relation_id': peer_rel_id,
                     'unit': None,
                     'app': 'test-app',
                 }},
                {'name': 'leader-settings-changed'},
                {'name': 'config-changed', 'data': {}},
                {'name': 'start'},
            ])

    def test_begin_with_initial_hooks_relation_charm_with_no_relation(self):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework):
                super().__init__(framework)
                self.observe_relation_events('db')
        harness = Harness(CharmWithDB, meta='''
            name: test-app
            requires:
              db:
                interface: sql
            ''')
        self.addCleanup(harness.cleanup)
        harness.set_leader()
        harness.begin_with_initial_hooks()
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'leader-elected'},
                {'name': 'config-changed', 'data': {}},
                {'name': 'start'},
            ])

    def test_begin_with_initial_hooks_with_one_relation(self):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework):
                super().__init__(framework)
                self.observe_relation_events('db')
        harness = Harness(CharmWithDB, meta='''
            name: test-app
            requires:
              db:
                interface: sql
            ''')
        self.addCleanup(harness.cleanup)
        harness.set_leader()
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'new': 'data'})
        harness.begin_with_initial_hooks()
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'relation-created',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': None,
                     'app': 'postgresql',
                 }},
                {'name': 'leader-elected'},
                {'name': 'config-changed', 'data': {}},
                {'name': 'start'},
                {'name': 'relation-joined',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/0',
                     'app': 'postgresql',
                 }},
                {'name': 'relation-changed',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/0',
                     'app': 'postgresql',
                 }},
            ])

    def test_begin_with_initial_hooks_with_application_data(self):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework):
                super().__init__(framework)
                self.observe_relation_events('db')
        harness = Harness(CharmWithDB, meta='''
            name: test-app
            requires:
              db:
                interface: sql
            ''')
        self.addCleanup(harness.cleanup)
        harness.set_leader()
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.update_relation_data(rel_id, 'postgresql/0', {'new': 'data'})
        harness.update_relation_data(rel_id, 'postgresql', {'app': 'data'})
        harness.begin_with_initial_hooks()
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'relation-created',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': None,
                     'app': 'postgresql',
                 }},
                {'name': 'leader-elected'},
                {'name': 'config-changed', 'data': {}},
                {'name': 'start'},
                {'name': 'relation-changed',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': None,
                     'app': 'postgresql',
                 }},
                {'name': 'relation-joined',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/0',
                     'app': 'postgresql',
                 }},
                {'name': 'relation-changed',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/0',
                     'app': 'postgresql',
                 }},
            ])

    def test_begin_with_initial_hooks_with_multiple_units(self):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework):
                super().__init__(framework)
                self.observe_relation_events('db')
        harness = Harness(CharmWithDB, meta='''
            name: test-app
            requires:
              db:
                interface: sql
            ''')
        self.addCleanup(harness.cleanup)
        harness.set_leader()
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/1')
        harness.update_relation_data(rel_id, 'postgresql/1', {'new': 'data'})
        # We intentionally add 0 after 1 to assert that the code triggers them in order
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.begin_with_initial_hooks()
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'install'},
                {'name': 'relation-created',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': None,
                     'app': 'postgresql',
                 }},
                {'name': 'leader-elected'},
                {'name': 'config-changed', 'data': {}},
                {'name': 'start'},
                {'name': 'relation-joined',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/0',
                     'app': 'postgresql',
                 }},
                {'name': 'relation-changed',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/0',
                     'app': 'postgresql',
                 }},
                {'name': 'relation-joined',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/1',
                     'app': 'postgresql',
                 }},
                {'name': 'relation-changed',
                 'relation': 'db',
                 'data': {
                     'relation_id': rel_id,
                     'unit': 'postgresql/1',
                     'app': 'postgresql',
                 }},
            ])

    def test_begin_with_initial_hooks_multiple_relation_same_endpoint(self):
        class CharmWithDB(RelationEventCharm):
            def __init__(self, framework):
                super().__init__(framework)
                self.observe_relation_events('db')
        harness = Harness(CharmWithDB, meta='''
            name: test-app
            requires:
              db:
                interface: sql
            ''')
        self.addCleanup(harness.cleanup)
        harness.set_leader()
        rel_id_a = harness.add_relation('db', 'pg-a')
        harness.add_relation_unit(rel_id_a, 'pg-a/0')
        rel_id_b = harness.add_relation('db', 'pg-b')
        harness.add_relation_unit(rel_id_b, 'pg-b/0')
        harness.begin_with_initial_hooks()
        changes = harness.charm.changes[:]
        expected_prefix = [
            {'name': 'install'},
        ]
        # The first events are always the same
        self.assertEqual(changes[:len(expected_prefix)], expected_prefix)
        changes = changes[len(expected_prefix):]
        # However, the order of relation-created events can be in any order
        expected_relation_created = [
            {'name': 'relation-created',
             'relation': 'db',
             'data': {
                 'relation_id': rel_id_a,
                 'unit': None,
                 'app': 'pg-a',
             }},
            {'name': 'relation-created',
             'relation': 'db',
             'data': {
                 'relation_id': rel_id_b,
                 'unit': None,
                 'app': 'pg-b',
             }},
        ]
        if changes[:2] != expected_relation_created:
            # change the order
            expected_relation_created = [expected_relation_created[1],
                                         expected_relation_created[0]]
        self.assertEqual(changes[:2], expected_relation_created)
        changes = changes[2:]
        expected_middle = [
            {'name': 'leader-elected'},
            {'name': 'config-changed', 'data': {}},
            {'name': 'start'},
        ]
        self.assertEqual(changes[:len(expected_middle)], expected_middle)
        changes = changes[len(expected_middle):]
        a_first = [
            {'name': 'relation-joined',
             'relation': 'db',
             'data': {
                 'relation_id': rel_id_a,
                 'unit': 'pg-a/0',
                 'app': 'pg-a',
             }},
            {'name': 'relation-changed',
             'relation': 'db',
             'data': {
                 'relation_id': rel_id_a,
                 'unit': 'pg-a/0',
                 'app': 'pg-a',
             }},
            {'name': 'relation-joined',
             'relation': 'db',
             'data': {
                 'relation_id': rel_id_b,
                 'unit': 'pg-b/0',
                 'app': 'pg-b',
             }},
            {'name': 'relation-changed',
             'relation': 'db',
             'data': {
                 'relation_id': rel_id_b,
                 'unit': 'pg-b/0',
                 'app': 'pg-b',
             }},
        ]
        if changes != a_first:
            b_first = [a_first[2], a_first[3], a_first[0], a_first[1]]
            self.assertEqual(changes, b_first)

    def test_get_pebble_container_plan(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            containers:
              foo:
                resource: foo-image
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        initial_plan = harness.get_container_pebble_plan('foo')
        self.assertEqual(initial_plan.to_yaml(), '{}\n')
        container = harness.model.unit.get_container('foo')
        container.pebble.add_layer('test-ab', '''\
summary: test-layer
description: a layer that we can use for testing
services:
  a:
    command: /bin/echo hello from a
  b:
    command: /bin/echo hello from b
''')
        container.pebble.add_layer('test-c', '''\
summary: test-for-c
services:
  c:
    command: /bin/echo hello from c
''')
        plan = container.pebble.get_plan()
        self.assertEqual(plan.to_yaml(), '''\
services:
  a:
    command: /bin/echo hello from a
  b:
    command: /bin/echo hello from b
  c:
    command: /bin/echo hello from c
''')
        harness_plan = harness.get_container_pebble_plan('foo')
        self.assertEqual(harness_plan.to_yaml(), plan.to_yaml())

    def test_get_pebble_container_plan_unknown(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            containers:
              foo:
                resource: foo-image
            ''')
        self.addCleanup(harness.cleanup)
        harness.begin()
        with self.assertRaises(KeyError):
            harness.get_container_pebble_plan('unknown')
        plan = harness.get_container_pebble_plan('foo')
        self.assertEqual(plan.to_yaml(), "{}\n")

    def test_container_pebble_ready(self):
        harness = Harness(ContainerEventCharm, meta='''
            name: test-app
            containers:
              foo:
                resource: foo-image
        ''')
        self.addCleanup(harness.cleanup)
        # This is a no-op if it is called before begin(), but it isn't an error
        harness.container_pebble_ready('foo')
        harness.begin()
        harness.charm.observe_container_events('foo')
        harness.container_pebble_ready('foo')
        self.assertEqual(
            harness.charm.changes,
            [
                {'name': 'pebble-ready',
                 'container': 'foo',
                 },
            ]
        )


class DBRelationChangedHelper(Object):
    def __init__(self, parent, key):
        super().__init__(parent, key)
        self.changes = []
        parent.framework.observe(parent.on.db_relation_changed, self.on_relation_changed)

    def on_relation_changed(self, event):
        if event.unit is not None:
            self.changes.append((event.relation.id, event.unit.name))
        else:
            self.changes.append((event.relation.id, event.app.name))


class RelationChangedViewer(Object):
    """Track relation_changed events and saves the data seen in the relation bucket."""

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self.changes = []
        charm.framework.observe(charm.on[relation_name].relation_changed, self.on_relation_changed)

    def on_relation_changed(self, event):
        if event.unit is not None:
            data = event.relation.data[event.unit]
        else:
            data = event.relation.data[event.app]
        self.changes.append(dict(data))


class RecordingCharm(CharmBase):
    """Record the events that we see, and any associated data."""

    def __init__(self, framework):
        super().__init__(framework)
        self.changes = []
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.leader_elected, self._on_leader_elected)
        self.framework.observe(self.on.leader_settings_changed, self._on_leader_settings_changed)
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.start, self._on_start)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on.remove, self._on_remove)
        self.framework.observe(self.on.upgrade_charm, self._on_upgrade_charm)
        self.framework.observe(self.on.update_status, self._on_update_status)

    def get_changes(self, reset=True):
        changes = self.changes
        if reset:
            self.changes = []
        return changes

    def _on_install(self, _):
        self.changes.append(dict(name='install'))

    def _on_start(self, _):
        self.changes.append(dict(name='start'))

    def _on_stop(self, _):
        self.changes.append(dict(name='stop'))

    def _on_remove(self, _):
        self.changes.append(dict(name='remove'))

    def _on_config_changed(self, _):
        self.changes.append(dict(name='config-changed', data=dict(self.framework.model.config)))

    def _on_leader_elected(self, _):
        self.changes.append(dict(name='leader-elected'))

    def _on_leader_settings_changed(self, _):
        self.changes.append(dict(name='leader-settings-changed'))

    def _on_upgrade_charm(self, _):
        self.changes.append(dict(name='upgrade-charm'))

    def _on_update_status(self, _):
        self.changes.append(dict(name='update-status'))


class RelationEventCharm(RecordingCharm):
    """Record events related to relation lifecycles."""

    def __init__(self, framework):
        super().__init__(framework)
        # When set, this instructs the charm to include a 'relation_data' field in the 'data'
        # section of each change it logs, which allows us to test which relation data was available
        # in each hook invocation
        self.record_relation_data_on_events = False

    def observe_relation_events(self, relation_name):
        self.framework.observe(self.on[relation_name].relation_created, self._on_relation_created)
        self.framework.observe(self.on[relation_name].relation_joined, self._on_relation_joined)
        self.framework.observe(self.on[relation_name].relation_changed, self._on_relation_changed)
        self.framework.observe(self.on[relation_name].relation_departed,
                               self._on_relation_departed)
        self.framework.observe(self.on[relation_name].relation_broken, self._on_relation_broken)

    def _on_relation_created(self, event):
        self._observe_relation_event('relation-created', event)

    def _on_relation_joined(self, event):
        self._observe_relation_event('relation-joined', event)

    def _on_relation_changed(self, event):
        self._observe_relation_event('relation-changed', event)

    def _on_relation_departed(self, event):
        self._observe_relation_event('relation-departed', event)

    def _on_relation_broken(self, event):
        self._observe_relation_event('relation-broken', event)

    def _observe_relation_event(self, event_name, event):
        unit_name = None
        if event.unit is not None:
            unit_name = event.unit.name
        app_name = None
        if event.app is not None:
            app_name = event.app.name

        recording = dict(name=event_name, relation=event.relation.name,
                         data=dict(app=app_name, unit=unit_name, relation_id=event.relation.id))

        if self.record_relation_data_on_events:
            recording["data"].update({'relation_data': {
                str(x.name): dict(event.relation.data[x])
                for x in event.relation.data
            }})

        self.changes.append(recording)


class ContainerEventCharm(RecordingCharm):
    """Record events related to container lifecycles."""

    def __init__(self, framework):
        super().__init__(framework)

    def observe_container_events(self, container_name):
        self.framework.observe(self.on[container_name].pebble_ready, self._on_pebble_ready)

    def _on_pebble_ready(self, event):
        self._observe_container_event('pebble-ready', event)

    def _observe_container_event(self, event_name, event: PebbleReadyEvent):
        container_name = None
        if event.workload is not None:
            container_name = event.workload.name
        self.changes.append(
            dict(name=event_name, container=container_name))


def get_public_methods(obj):
    """Get the public attributes of obj to compare to another object."""
    public = set()
    members = inspect.getmembers(obj)
    for name, member in members:
        if name.startswith('_'):
            continue
        if inspect.isfunction(member) or inspect.ismethod(member):
            public.add(name)
    return public


class TestTestingModelBackend(unittest.TestCase):

    def test_conforms_to_model_backend(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        mb_methods = get_public_methods(_ModelBackend)
        backend_methods = get_public_methods(backend)
        self.assertEqual(mb_methods, backend_methods)

    def test_status_set_get_unit(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=False)
        self.assertEqual(
            backend.status_get(is_app=False),
            {'status': 'blocked', 'message': 'message'})
        self.assertEqual(
            backend.status_get(is_app=True),
            {'status': 'unknown', 'message': ''})

    def test_status_set_get_app(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=True)
        self.assertEqual(
            backend.status_get(is_app=True),
            {'status': 'blocked', 'message': 'message'})
        self.assertEqual(
            backend.status_get(is_app=False),
            {'status': 'maintenance', 'message': ''})

    def test_relation_ids_unknown_relation(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            provides:
              db:
                interface: mydb
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        # With no relations added, we just get an empty list for the interface
        self.assertEqual(backend.relation_ids('db'), [])
        # But an unknown interface raises a ModelError
        with self.assertRaises(ModelError):
            backend.relation_ids('unknown')

    def test_relation_get_unknown_relation_id(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        with self.assertRaises(RelationNotFoundError):
            backend.relation_get(1234, 'unit/0', False)

    def test_relation_list_unknown_relation_id(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        with self.assertRaises(RelationNotFoundError):
            backend.relation_list(1234)

    def test_lazy_resource_directory(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: oci-image
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        harness.populate_oci_resources()
        backend = harness._backend
        self.assertIsNone(backend._resource_dir)
        path = backend.resource_get('image')
        self.assertIsNotNone(backend._resource_dir)
        self.assertTrue(
            str(path).startswith(str(backend._resource_dir.name)),
            msg='expected {} to be a subdirectory of {}'.format(path, backend._resource_dir.name))

    def test_resource_get_no_resource(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            resources:
              image:
                type: file
                description: "Image to deploy."
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend
        with self.assertRaises(ModelError) as cm:
            backend.resource_get('foo')
        self.assertIn(
            "units/unit-test-app-0/resources/foo: resource#test-app/foo not found",
            str(cm.exception))

    def test_relation_remote_app_name(self):
        harness = Harness(CharmBase, meta='''
            name: test-charm
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend

        self.assertIs(backend.relation_remote_app_name(1), None)

        rel_id = harness.add_relation('db', 'postgresql')
        self.assertEqual(backend.relation_remote_app_name(rel_id), 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.add_relation_unit(rel_id, 'postgresql/1')
        self.assertEqual(backend.relation_remote_app_name(rel_id), 'postgresql')

        self.assertIs(backend.relation_remote_app_name(7), None)

    def test_get_pebble_methods(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend

        client = backend.get_pebble('/custom/socket/path')
        self.assertIsInstance(client, _TestingPebbleClient)


class TestTestingPebbleClient(unittest.TestCase):

    def get_testing_client(self):
        harness = Harness(CharmBase, meta='''
            name: test-app
            ''')
        self.addCleanup(harness.cleanup)
        backend = harness._backend

        return backend.get_pebble('/custom/socket/path')

    def test_methods_match_pebble_client(self):
        client = self.get_testing_client()
        self.assertIsNotNone(client)
        pebble_client_methods = get_public_methods(pebble.Client)
        testing_client_methods = get_public_methods(client)
        self.assertEqual(pebble_client_methods, testing_client_methods)

    def test_add_layer(self):
        client = self.get_testing_client()
        plan = client.get_plan()
        self.assertIsInstance(plan, pebble.Plan)
        self.assertEqual('{}\n', plan.to_yaml())
        client.add_layer('foo', pebble.Layer('''\
summary: Foo
description: |
  A longer description about Foo
services:
  serv:
    summary: Serv
    description: |
      A description about Serv the amazing service.
    startup: enabled
    override: replace
    command: '/bin/echo hello'
    environment:
      KEY: VALUE
'''))
        plan = client.get_plan()
        # The YAML should be normalized
        self.assertEqual('''\
services:
  serv:
    command: /bin/echo hello
    description: 'A description about Serv the amazing service.

      '
    environment:
      KEY: VALUE
    override: replace
    startup: enabled
    summary: Serv
''', plan.to_yaml())

    def test_add_layer_not_combined(self):
        client = self.get_testing_client()
        plan = client.get_plan()
        self.assertIsInstance(plan, pebble.Plan)
        self.assertEqual('{}\n', plan.to_yaml())
        service = '''\
summary: Foo
description: |
  A longer description about Foo
services:
  serv:
    summary: Serv
    description: |
      A description about Serv the amazing service.
    startup: enabled
    override: replace
    command: '/bin/echo hello'
    environment:
      KEY: VALUE
'''
        client.add_layer('foo', pebble.Layer(service))
        # TODO: jam 2021-04-19 We should have a clearer error type for this case. The actual
        #  pebble raises an HTTP exception. See https://github.com/canonical/operator/issues/514
        #  that this should be cleaned up into a clearer error type, however, they should get an
        #  error
        with self.assertRaises(RuntimeError):
            client.add_layer('foo', pebble.Layer(service))

    def test_add_layer_three_services(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    override: replace
    command: '/bin/echo foo'
''')
        client.add_layer('bar', '''\
summary: bar
services:
  bar:
    summary: The Great Bar
    startup: enabled
    override: replace
    command: '/bin/echo bar'
''')
        client.add_layer('baz', '''\
summary: baz
services:
  baz:
    summary: Not Bar, but Baz
    startup: enabled
    override: replace
    command: '/bin/echo baz'
''')
        plan = client.get_plan()
        self.maxDiff = 1000
        # Alphabetical services, and the YAML should be normalized
        self.assertEqual('''\
services:
  bar:
    command: /bin/echo bar
    override: replace
    startup: enabled
    summary: The Great Bar
  baz:
    command: /bin/echo baz
    override: replace
    startup: enabled
    summary: Not Bar, but Baz
  foo:
    command: /bin/echo foo
    override: replace
    startup: enabled
    summary: Foo
''', plan.to_yaml())

    def test_add_layer_combine_no_override(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
command: '/bin/echo foo'
''')
        # TODO: jam 2021-04-19 Pebble currently raises a HTTP Error 500 Internal Service Error
        #  if you don't supply an override directive. That needs to be fixed and this test
        #  should be updated. https://github.com/canonical/operator/issues/514
        with self.assertRaises(RuntimeError):
            client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    command: '/bin/echo foo'
''', combine=True)

    def test_add_layer_combine_override_replace(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  bar:
    summary: Bar
    command: '/bin/echo bar'
  foo:
    summary: Foo
    command: '/bin/echo foo'
''')
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    command: '/bin/echo foo new'
    override: replace
''', combine=True)
        self.assertEqual('''\
services:
  bar:
    command: /bin/echo bar
    summary: Bar
  foo:
    command: /bin/echo foo new
    override: replace
''', client.get_plan().to_yaml())

    def test_add_layer_combine_override_merge(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  bar:
    summary: Bar
    command: '/bin/echo bar'
  foo:
    summary: Foo
    command: '/bin/echo foo'
''')
        # TODO: jam 2021-04-19 override: merge should eventually be supported, but if it isn't
        #  supported by the framework, we should fail rather than do the wrong thing
        with self.assertRaises(RuntimeError):
            client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    command: '/bin/echo foob'
    override: merge
''', combine=True)

    def test_add_layer_combine_override_unknown(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  bar:
    summary: Bar
    command: '/bin/echo bar'
  foo:
    summary: Foo
    command: '/bin/echo foo'
''')
        with self.assertRaises(RuntimeError):
            client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    command: '/bin/echo foob'
    override: blah
''', combine=True)

    def test_get_services_none(self):
        client = self.get_testing_client()
        service_info = client.get_services()
        self.assertEqual([], service_info)

    def test_get_services_not_started(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)
        self.assertFalse(bar_info.is_running())
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)
        self.assertFalse(foo_info.is_running())

    def test_get_services_autostart(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        client.autostart_services()
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)
        self.assertFalse(bar_info.is_running())
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, foo_info.current)
        self.assertTrue(foo_info.is_running())

    def test_get_services_start_stop(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        client.start_services(['bar'])
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Even though bar defaults to DISABLED, we explicitly started it
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, bar_info.current)
        # foo would be started by autostart, but we only called start_services
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)
        client.stop_services(['bar'])
        infos = client.get_services()
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)

    def test_get_services_bad_request(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        # It is a common mistake to pass just a name vs a list of names, so catch it with a
        # TypeError
        with self.assertRaises(TypeError):
            client.get_services('foo')

    def test_get_services_subset(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        infos = client.get_services(['foo'])
        self.assertEqual(len(infos), 1)
        foo_info = infos[0]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)

    def test_get_services_unknown(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        # This doesn't seem to be an error at the moment.
        # pebble_cli.py service just returns an empty list
        # pebble service unknown says "No matching services" (but exits 0)
        infos = client.get_services(['unknown'])
        self.assertEqual(infos, [])

    def test_invalid_start_service(self):
        client = self.get_testing_client()
        # TODO: jam 2021-04-20 This should become a better error
        with self.assertRaises(RuntimeError):
            client.start_services(['unknown'])

    def test_start_service_str(self):
        # Start service takes a list of names, but it is really easy to accidentally pass just a
        # name
        client = self.get_testing_client()
        with self.assertRaises(TypeError):
            client.start_services('unknown')

    def test_stop_service_str(self):
        # Start service takes a list of names, but it is really easy to accidentally pass just a
        # name
        client = self.get_testing_client()
        with self.assertRaises(TypeError):
            client.stop_services('unknown')

    def test_mixed_start_service(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
''')
        # TODO: jam 2021-04-20 better error type
        with self.assertRaises(RuntimeError):
            client.start_services(['foo', 'unknown'])
        # foo should not be started
        infos = client.get_services()
        self.assertEqual(len(infos), 1)
        foo_info = infos[0]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, foo_info.current)

    def test_stop_services_unknown(self):
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
''')
        client.autostart_services()
        # TODO: jam 2021-04-20 better error type
        with self.assertRaises(RuntimeError):
            client.stop_services(['foo', 'unknown'])
        # foo should still be running
        infos = client.get_services()
        self.assertEqual(len(infos), 1)
        foo_info = infos[0]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, foo_info.current)

    def test_start_started_service(self):
        # If you try to start a service which is started, you get a ChangeError:
        # $ PYTHONPATH=. python3 ./test/pebble_cli.py start serv
        # ChangeError: cannot perform the following tasks:
        # - Start service "serv" (service "serv" was previously started)
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        client.autostart_services()
        # Foo is now started, but Bar is not
        with self.assertRaises(pebble.ChangeError):
            client.start_services(['bar', 'foo'])
        # bar could have been started, but won't be, because foo did not validate
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, foo_info.current)

    def test_stop_stopped_service(self):
        # If you try to stop a service which is stop, you get a ChangeError:
        # $ PYTHONPATH=. python3 ./test/pebble_cli.py stop other serv
        # ChangeError: cannot perform the following tasks:
        # - Stop service "other" (service "other" is not active)
        client = self.get_testing_client()
        client.add_layer('foo', '''\
summary: foo
services:
  foo:
    summary: Foo
    startup: enabled
    command: '/bin/echo foo'
  bar:
    summary: Bar
    command: '/bin/echo bar'
''')
        client.autostart_services()
        # Foo is now started, but Bar is not
        with self.assertRaises(pebble.ChangeError):
            client.stop_services(['foo', 'bar'])
        # foo could have been stopped, but won't be, because bar did not validate
        infos = client.get_services()
        self.assertEqual(len(infos), 2)
        bar_info = infos[0]
        self.assertEqual('bar', bar_info.name)
        # Default when not specified is DISABLED
        self.assertEqual(pebble.ServiceStartup.DISABLED, bar_info.startup)
        self.assertEqual(pebble.ServiceStatus.INACTIVE, bar_info.current)
        foo_info = infos[1]
        self.assertEqual('foo', foo_info.name)
        self.assertEqual(pebble.ServiceStartup.ENABLED, foo_info.startup)
        self.assertEqual(pebble.ServiceStatus.ACTIVE, foo_info.current)
