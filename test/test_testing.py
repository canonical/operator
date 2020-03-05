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

import unittest

from ops.charm import (
    CharmBase,
)
from ops.framework import (
    Object,
)
from ops.model import (
    ModelError,
)
from ops.testing import TestingHarness, create_harness


class TestTestingHarness(unittest.TestCase):

    def test_add_relation(self):
        builder = TestingHarness('test-unit/0')
        rel_id = builder.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        backend = builder._get_backend()
        self.assertEqual([rel_id], backend.relation_ids('db'))
        self.assertEqual([], backend.relation_list(rel_id))

    def test_add_relation_and_unit(self):
        builder = TestingHarness('test-unit/0')
        remote_unit = 'postgresql/0'
        rel_id = builder.add_relation('db', 'postgresql', remote_app_data={'app': 'data'})
        self.assertIsInstance(rel_id, int)
        builder.add_relation_unit(rel_id, remote_unit, remote_unit_data={'foo': 'bar'})
        backend = builder._get_backend()
        self.assertEqual([rel_id], backend.relation_ids('db'))
        self.assertEqual([remote_unit], backend.relation_list(rel_id))
        self.assertEqual({'foo': 'bar'}, backend.relation_get(rel_id, remote_unit, is_app=False))
        self.assertEqual({'app': 'data'}, backend.relation_get(rel_id, remote_unit, is_app=True))

    def test_create_harness(self):
        charm, builder = create_harness(CharmBase, '''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        helper = DBRelationChangedHelper(charm, "helper")
        rel_id = builder.add_relation('db', 'postgresql')
        relation = charm.framework.model.get_relation('db', rel_id)
        app = charm.framework.model.get_app('postgresql')
        charm.on.db_relation_changed.emit(relation, app)
        self.assertEqual(helper.changes, [(rel_id, 'postgresql')])

    def test_create_harness_twice(self):
        charm1, builder1 = create_harness(CharmBase, '''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        charm2, builder2 = create_harness(CharmBase, '''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        helper1 = DBRelationChangedHelper(charm1, "helper1")
        helper2 = DBRelationChangedHelper(charm2, "helper2")
        rel_id = builder2.add_relation('db', 'postgresql')
        builder2.update_relation_data(rel_id, 'postgresql', {'key': 'value'})
        # Helper2 should see the event triggered by builder2, but helper1 should see no events.
        self.assertEqual(helper1.changes, [])
        self.assertEqual(helper2.changes, [(rel_id, 'postgresql')])

    def test_update_relation_exposes_new_data(self):
        charm, builder = create_harness(CharmBase, '''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')

        viewer = RelationChangedViewer(charm, 'db')
        rel_id = builder.add_relation('db', 'postgresql')
        builder.add_relation_unit(rel_id, 'postgresql/0', remote_unit_data={'initial': 'data'})
        self.assertEqual(viewer.changes, [{'initial': 'data'}])
        builder.update_relation_data(rel_id, 'postgresql/0', {'new': 'value'})
        self.assertEqual(viewer.changes, [{'initial': 'data'}, {'initial': 'data', 'new': 'value'}])

    def test_update_relation_remove_data(self):
        charm, builder = create_harness(CharmBase, '''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        viewer = RelationChangedViewer(charm, 'db')
        rel_id = builder.add_relation('db', 'postgresql')
        builder.add_relation_unit(rel_id, 'postgresql/0', remote_unit_data={'initial': 'data'})
        builder.update_relation_data(rel_id, 'postgresql/0', {'initial': ''})
        self.assertEqual(viewer.changes, [{'initial': 'data'}, {}])

    def test_update_config(self):
        charm, builder = create_harness(RecordingCharm, '''
            name: my-charm
            ''')
        builder.update_config(key_values={'a': 'foo', 'b': 2})
        self.assertEqual(charm.changes, [{'name': 'config', 'data': {'a': 'foo', 'b': 2}}])
        builder.update_config(key_values={'b': 3})
        self.assertEqual(charm.changes, [{'name': 'config', 'data': {'a': 'foo', 'b': 2}},
                                         {'name': 'config', 'data': {'a': 'foo', 'b': 3}}])
        # you can set config values to the empty string, you can use unset to actually remove items
        builder.update_config(key_values={'a': ''}, unset=set('b'))
        self.assertEqual(charm.changes, [{'name': 'config', 'data': {'a': 'foo', 'b': 2}},
                                         {'name': 'config', 'data': {'a': 'foo', 'b': 3}},
                                         {'name': 'config', 'data': {'a': ''}},
                                         ])

    def test_set_leader(self):
        charm, builder = create_harness(RecordingCharm, '''
            name: my-charm
            ''')
        # No event happens here
        builder.set_leader(False)
        self.assertFalse(charm.framework.model.unit.is_leader())
        builder.set_leader(True)
        self.assertEqual(charm.changes, [{'name': 'leader-elected'}])
        self.assertTrue(charm.framework.model.unit.is_leader())

    def test_relation_set_app_not_leader(self):
        charm, builder = create_harness(RecordingCharm, '''
            name: test-charm
            requires:
                db:
                    interface: pgsql
            ''')
        builder.set_leader(False)
        rel_id = builder.add_relation('db', 'postgresql')
        builder.add_relation_unit(rel_id, 'postgresql/0')
        rel = charm.framework.model.get_relation('db')
        with self.assertRaises(ModelError):
            rel.data[charm.framework.model.app]['foo'] = 'bar'
        # The data has not actually been changed
        self.assertEqual(builder._get_backend()._relation_data[rel_id]['test-charm'], {})
        builder.set_leader(True)
        rel.data[charm.framework.model.app]['foo'] = 'bar'
        self.assertEqual(builder._get_backend()._relation_data[rel_id]['test-charm'], {'foo': 'bar'})


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
    """Helper class that just tracks relation_changed events and saves the data seen in the relation bucket."""

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

    def __init__(self, framework, charm_name):
        super().__init__(framework, charm_name)
        self.changes = []
        self.framework.observe(self.on.config_changed, self.on_config_changed)
        self.framework.observe(self.on.leader_elected, self.on_leader_elected)

    def on_config_changed(self, event):
        self.changes.append(dict(name='config', data=dict(self.framework.model.config)))

    def on_leader_elected(self, event):
        self.changes.append(dict(name='leader-elected'))


if __name__ == "__main__":
    unittest.main()
