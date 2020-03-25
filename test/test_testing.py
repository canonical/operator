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

import importlib
import pathlib
import shutil
import sys
import tempfile
import textwrap
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
from ops.testing import Harness


class TestHarness(unittest.TestCase):

    def test_add_relation(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        rel_id = harness.add_relation('db', 'postgresql')
        self.assertIsInstance(rel_id, int)
        backend = harness._backend
        self.assertEqual([rel_id], backend.relation_ids('db'))
        self.assertEqual([], backend.relation_list(rel_id))

    def test_add_relation_and_unit(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        remote_unit = 'postgresql/0'
        rel_id = harness.add_relation('db', 'postgresql', remote_app_data={'app': 'data'})
        self.assertIsInstance(rel_id, int)
        harness.add_relation_unit(rel_id, remote_unit, remote_unit_data={'foo': 'bar'})
        backend = harness._backend
        self.assertEqual([rel_id], backend.relation_ids('db'))
        self.assertEqual([remote_unit], backend.relation_list(rel_id))
        self.assertEqual({'foo': 'bar'}, backend.relation_get(rel_id, remote_unit, is_app=False))
        self.assertEqual({'app': 'data'}, backend.relation_get(rel_id, remote_unit, is_app=True))

    def test_get_relation_data(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: test-app
            requires:
                db:
                    interface: pgsql
            ''')
        rel_id = harness.add_relation('db', 'postgresql',
                                      remote_app_data={'remote': 'data'})
        harness.begin()
        self.assertEqual(harness.get_relation_data(rel_id, 'test-app'), {})
        self.assertEqual(harness.get_relation_data(rel_id, 'test-app/0'), {})
        self.assertEqual(harness.get_relation_data(rel_id, 'test-app/1'), None)
        self.assertEqual(harness.get_relation_data(rel_id, 'postgresql'), {'remote': 'data'})
        with self.assertRaises(KeyError):
            # unknown relation id
            harness.get_relation_data(99, 'postgresql')

    def test_create_harness_twice(self):
        # language=YAML
        metadata = '''
            name: my-charm
            requires:
              db:
                interface: pgsql
            '''
        harness1 = Harness(CharmBase, meta=metadata)
        harness2 = Harness(CharmBase, meta=metadata)
        harness1.begin()
        harness2.begin()
        helper1 = DBRelationChangedHelper(harness1.charm, "helper1")
        helper2 = DBRelationChangedHelper(harness2.charm, "helper2")
        rel_id = harness2.add_relation('db', 'postgresql')
        harness2.update_relation_data(rel_id, 'postgresql', {'key': 'value'})
        # Helper2 should see the event triggered by harness2, but helper1 should see no events.
        self.assertEqual(helper1.changes, [])
        self.assertEqual(helper2.changes, [(rel_id, 'postgresql')])

    def test_update_relation_exposes_new_data(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0', remote_unit_data={'initial': 'data'})
        self.assertEqual(viewer.changes, [{'initial': 'data'}])
        harness.update_relation_data(rel_id, 'postgresql/0', {'new': 'value'})
        self.assertEqual(viewer.changes, [{'initial': 'data'},
                                          {'initial': 'data', 'new': 'value'}])

    def test_update_relation_remove_data(self):
        # language=YAML
        harness = Harness(CharmBase, meta='''
            name: my-charm
            requires:
              db:
                interface: pgsql
            ''')
        harness.begin()
        viewer = RelationChangedViewer(harness.charm, 'db')
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0', remote_unit_data={'initial': 'data'})
        harness.update_relation_data(rel_id, 'postgresql/0', {'initial': ''})
        self.assertEqual(viewer.changes, [{'initial': 'data'}, {}])

    def test_update_config(self):
        harness = Harness(RecordingCharm)
        harness.begin()
        harness.update_config(key_values={'a': 'foo', 'b': 2})
        self.assertEqual(
            [{'name': 'config', 'data': {'a': 'foo', 'b': 2}}],
            harness.charm.changes)
        harness.update_config(key_values={'b': 3})
        self.assertEqual(
            [{'name': 'config', 'data': {'a': 'foo', 'b': 2}},
             {'name': 'config', 'data': {'a': 'foo', 'b': 3}}],
            harness.charm.changes)
        # you can set config values to the empty string, you can use unset to actually remove items
        harness.update_config(key_values={'a': ''}, unset=set('b'))
        self.assertEqual(
            [{'name': 'config', 'data': {'a': 'foo', 'b': 2}},
             {'name': 'config', 'data': {'a': 'foo', 'b': 3}},
             {'name': 'config', 'data': {'a': ''}},
             ],
            harness.charm.changes)

    def test_set_leader(self):
        harness = Harness(RecordingCharm)
        # No event happens here
        harness.set_leader(False)
        harness.begin()
        self.assertFalse(harness.charm.model.unit.is_leader())
        harness.set_leader(True)
        self.assertEqual([{'name': 'leader-elected'}], harness.charm.get_changes(reset=True))
        self.assertTrue(harness.charm.model.unit.is_leader())
        harness.set_leader(False)
        self.assertFalse(harness.charm.model.unit.is_leader())
        # No hook event when you lose leadership.
        # TODO: verify if Juju always triggers `leader-settings-changed` if you
        #   lose leadership.
        self.assertEqual([], harness.charm.get_changes(reset=True))
        harness.disable_hooks()
        harness.set_leader(True)
        # No hook event if you have disabled them
        self.assertEqual([], harness.charm.get_changes(reset=True))

    def test_relation_set_app_not_leader(self):
        # language=YAML
        harness = Harness(RecordingCharm, meta='''
            name: test-charm
            requires:
                db:
                    interface: pgsql
            ''')
        harness.set_leader(False)
        rel_id = harness.add_relation('db', 'postgresql')
        harness.add_relation_unit(rel_id, 'postgresql/0')
        harness.begin()
        rel = harness.charm.model.get_relation('db')
        with self.assertRaises(ModelError):
            rel.data[harness.charm.app]['foo'] = 'bar'
        # The data has not actually been changed
        self.assertEqual(harness.get_relation_data(rel_id, 'test-charm'), {})
        harness.set_leader(True)
        rel.data[harness.charm.app]['foo'] = 'bar'
        self.assertEqual(harness.get_relation_data(rel_id, 'test-charm'), {'foo': 'bar'})

    def test_hooks_enabled_and_disabled(self):
        # language=YAML
        harness = Harness(RecordingCharm, meta='''
            name: test-charm
        ''')
        # Before begin() there are no events.
        harness.update_config({'value': 'first'})
        # By default, after begin the charm is set up to receive events.
        harness.begin()
        harness.update_config({'value': 'second'})
        self.assertEqual(
            [{'name': 'config', 'data': {'value': 'second'}}],
            harness.charm.get_changes(reset=True), )
        # Once disabled, we won't see config-changed when we make an update
        harness.disable_hooks()
        harness.update_config({'third': '3'})
        self.assertEqual(harness.charm.get_changes(reset=True), [])
        harness.enable_hooks()
        harness.update_config({'value': 'fourth'})
        self.assertEqual(
            [{'name': 'config', 'data': {'value': 'fourth', 'third': '3'}}],
            harness.charm.get_changes(reset=True))

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
        srcdir = tmp / 'src'
        srcdir.mkdir(0o755)
        charm_filename = srcdir / 'charm.py'
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
            sys.modules.pop('charm')
        self.addCleanup(cleanup)
        charm_mod = importlib.import_module('charm')
        harness = Harness(charm_mod.MyTestingCharm)
        harness.begin()
        self.assertEqual(['db'], list(harness.model.relations))
        # The charm_dir also gets set
        self.assertEqual(harness.framework.charm_dir, tmp)


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

    def __init__(self, framework, charm_name):
        super().__init__(framework, charm_name)
        self.changes = []
        self.framework.observe(self.on.config_changed, self.on_config_changed)
        self.framework.observe(self.on.leader_elected, self.on_leader_elected)

    def get_changes(self, reset=True):
        changes = self.changes
        if reset:
            self.changes = []
        return changes

    def on_config_changed(self, _):
        self.changes.append(dict(name='config', data=dict(self.framework.model.config)))

    def on_leader_elected(self, _):
        self.changes.append(dict(name='leader-elected'))


class TestTestingModelBackend(unittest.TestCase):

    def test_status_set_get_unit(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=False)
        self.assertEqual(('blocked', 'message'), backend.status_get(is_app=False))
        self.assertEqual(None, backend.status_get(is_app=True))

    def test_status_set_get_app(self):
        harness = Harness(CharmBase, meta='''
            name: app
            ''')
        backend = harness._backend
        backend.status_set('blocked', 'message', is_app=True)
        self.assertEqual(('blocked', 'message'), backend.status_get(is_app=True))
        self.assertEqual(None, backend.status_get(is_app=False))


if __name__ == "__main__":
    unittest.main()
