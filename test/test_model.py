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

import os
import pathlib
import unittest
import json
import ipaddress
from collections import OrderedDict

import ops.model
import ops.charm
from ops.charm import RelationMeta

from test.test_helpers import fake_script, fake_script_calls


class TestModel(unittest.TestCase):

    def setUp(self):
        def restore_env(env):
            os.environ.clear()
            os.environ.update(env)
        self.addCleanup(restore_env, os.environ.copy())

        os.environ['JUJU_UNIT_NAME'] = 'myapp/0'

        self.backend = ops.model.ModelBackend()
        meta = ops.charm.CharmMeta()
        meta.relations = {
            'db0': RelationMeta('provides', 'db0', {'interface': 'db0', 'scope': 'global'}),
            'db1': RelationMeta('requires', 'db1', {'interface': 'db1', 'scope': 'global'}),
            'db2': RelationMeta('peers', 'db2', {'interface': 'db2', 'scope': 'global'}),
        }
        self.model = ops.model.Model('myapp/0', meta, self.backend)
        fake_script(self, 'relation-ids', """([ "$1" = db0 ] && echo '["db0:4"]') || echo '[]'""")

    def test_model(self):
        self.assertIs(self.model.app, self.model.unit.app)

    def test_relations_keys(self):
        fake_script(self, 'relation-ids',
                    """[ "$1" = db2 ] && echo '["db2:5", "db2:6"]' || echo '[]'""")
        fake_script(self, 'relation-list',
                    """
case "$2" in
    5)
        echo '["remoteapp1/0", "remoteapp1/1"]'
        ;;
    6)
        echo '["remoteapp2/0"]'
        ;;
    *)
        exit 2
    ;;
esac
""")

        for relation in self.model.relations['db2']:
            self.assertIn(self.model.unit, relation.data)
            unit_from_rel = next(filter(lambda u: u.name == 'myapp/0', relation.data.keys()))
            self.assertIs(self.model.unit, unit_from_rel)

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db2', '--format=json'],
            ['relation-list', '-r', '5', '--format=json'],
            ['relation-list', '-r', '6', '--format=json']
        ])

    def test_get_relation(self):
        err_msg = 'ERROR invalid value "$2" for option -r: relation not found'

        fake_script(self, 'relation-ids', '''
            case "$1" in
            db1)
                echo '["db1:4"]'
                ;;
            db2)
                echo '["db2:5", "db2:6"]'
                ;;
            *)
                echo '[]'
                ;;
            esac
        ''')
        fake_script(self, 'relation-list', '''
            if [ "$2" = 4 ]; then
                echo '["remoteapp1/0"]'
            else
                echo {} >&2
                exit 2
            fi
        '''.format(err_msg))
        fake_script(self, 'relation-get',
                    """echo {} >&2 ; exit 2""".format(err_msg))

        with self.assertRaises(ops.model.ModelError):
            self.model.get_relation('db1', 'db1:4')
        db1_4 = self.model.get_relation('db1', 4)
        self.assertIsInstance(db1_4, ops.model.Relation)
        dead_rel = self.model.get_relation('db1', 7)
        self.assertIsInstance(dead_rel, ops.model.Relation)
        self.assertEqual(set(dead_rel.data.keys()), {self.model.unit, self.model.unit.app})
        self.assertEqual(dead_rel.data[self.model.unit], {})
        self.assertIsNone(self.model.get_relation('db0'))
        self.assertIs(self.model.get_relation('db1'), db1_4)
        with self.assertRaises(ops.model.TooManyRelatedAppsError):
            self.model.get_relation('db2')

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-list', '-r', '7', '--format=json'],
            ['relation-get', '-r', '7', '-', 'myapp/0', '--app=False', '--format=json'],
            ['relation-ids', 'db0', '--format=json'],
            ['relation-ids', 'db2', '--format=json'],
            ['relation-list', '-r', '5', '--format=json'],
            ['relation-list', '-r', '6', '--format=json']
        ])

    def test_peer_relation_app(self):
        meta = ops.charm.CharmMeta()
        meta.relations = {'dbpeer': RelationMeta('peers', 'dbpeer',
                                                 {'interface': 'dbpeer', 'scope': 'global'})}
        self.model = ops.model.Model('myapp/0', meta, self.backend)

        err_msg = 'ERROR invalid value "$2" for option -r: relation not found'
        fake_script(self, 'relation-ids',
                    '''([ "$1" = dbpeer ] && echo '["dbpeer:0"]') || echo "[]"''')
        fake_script(self, 'relation-list',
                    '''([ "$2" = 0 ] && echo "[]") || (echo {} >&2 ; exit 2)'''.format(err_msg))

        db1_4 = self.model.get_relation('dbpeer')
        self.assertIs(db1_4.app, self.model.app)

    def test_remote_units_is_our(self):
        fake_script(self, 'relation-ids',
                    """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list',
                    """[ "$2" = 4 ] && echo '["remoteapp1/0", "remoteapp1/1"]' || exit 2""")

        for u in self.model.get_relation('db1').units:
            self.assertFalse(u._is_our_unit)
            self.assertFalse(u.app._is_our_app)

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json']
        ])

    def test_our_unit_is_our(self):
        self.assertTrue(self.model.unit._is_our_unit)
        self.assertTrue(self.model.unit.app._is_our_app)

    def test_unit_relation_data(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', """[ "$2" = 4 ] && echo '["remoteapp1/0"]' || exit 2""")
        fake_script(self, 'relation-get', """
if [ "$2" = 4 ] && [ "$4" = "remoteapp1/0" ]; then
    echo '{"host": "remoteapp1-0"}'
else
    exit 2
fi
""")

        random_unit = self.model._cache.get(ops.model.Unit, 'randomunit/0')
        with self.assertRaises(KeyError):
            self.model.get_relation('db1').data[random_unit]
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0',
                                   self.model.get_relation('db1').units))
        self.assertEqual(self.model.get_relation('db1').data[remoteapp1_0],
                         {'host': 'remoteapp1-0'})

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-get', '-r', '4', '-', 'remoteapp1/0', '--app=False', '--format=json']
        ])

    def test_remote_app_relation_data(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', '''
            if [ "$2" = 4 ]; then
                echo '["remoteapp1/0", "remoteapp1/1"]'
            else
                exit 2
            fi
        ''')
        fake_script(self, 'relation-get', '''
            if [ "$2" = 4 ] && [ "$4" = remoteapp1 ]; then
                echo '{"secret": "cafedeadbeef"}'
            else
                exit 2
            fi
        ''')

        # Try to get relation data for an invalid remote application.
        random_app = self.model._cache.get(ops.model.Application, 'randomapp')
        with self.assertRaises(KeyError):
            self.model.get_relation('db1').data[random_app]

        remoteapp1 = self.model.get_relation('db1').app
        self.assertEqual(self.model.get_relation('db1').data[remoteapp1],
                         {'secret': 'cafedeadbeef'})

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-get', '-r', '4', '-', 'remoteapp1', '--app=True', '--format=json'],
        ])

    def test_relation_data_modify_remote(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', """[ "$2" = 4 ] && echo '["remoteapp1/0"]' || exit 2""")
        fake_script(self, 'relation-get', """
if [ "$2" = 4 ] && [ "$4" = "remoteapp1/0" ]; then
    echo '{"host": "remoteapp1-0"}'
else
    exit 2
fi
""")

        rel_db1 = self.model.get_relation('db1')
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0',
                                   self.model.get_relation('db1').units))
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[remoteapp1_0])
        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[remoteapp1_0]['foo'] = 'bar'
        self.assertNotIn('foo', rel_db1.data[remoteapp1_0])

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-get', '-r', '4', '-', 'remoteapp1/0', '--app=False', '--format=json']
        ])

    def test_relation_data_modify_our(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', """[ "$2" = 4 ] && echo '["remoteapp1/0"]' || exit 2""")
        fake_script(self, 'relation-set', '''[ "$2" = 4 ] && exit 0 || exit 2''')
        fake_script(self, 'relation-get', '''
            if [ "$2" = 4 ] && [ "$4" = "myapp/0" ]; then
                echo '{"host": "bar"}'
            else
                exit 2
            fi
        ''')

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        rel_db1.data[self.model.unit]['host'] = 'bar'
        self.assertEqual(rel_db1.data[self.model.unit]['host'], 'bar')

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-get', '-r', '4', '-', 'myapp/0', '--app=False', '--format=json'],
            ['relation-set', '-r', '4', 'host=bar', '--app=False']
        ])

    def test_app_relation_data_modify_local_as_leader(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', '''
            if [ "$2" = 4 ]; then
                echo '["remoteapp1/0", "remoteapp1/1"]'
            else
                exit 2
            fi
        ''')
        fake_script(self, 'relation-get', '''
            if [ "$2" = 4 ] && [ "$4" = myapp ]; then
                echo '{"password": "deadbeefcafe"}'
            else
                exit 2
            fi
        ''')
        fake_script(self, 'relation-set', """[ "$2" = 4 ] && exit 0 || exit 2""")
        fake_script(self, 'is-leader', 'echo true')

        local_app = self.model.unit.app

        rel_db1 = self.model.get_relation('db1')
        self.assertEqual(rel_db1.data[local_app], {'password': 'deadbeefcafe'})

        rel_db1.data[local_app]['password'] = 'foo'

        self.assertEqual(rel_db1.data[local_app]['password'], 'foo')

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-get', '-r', '4', '-', 'myapp', '--app=True', '--format=json'],
            ['is-leader', '--format=json'],
            ['relation-set', '-r', '4', 'password=foo', '--app=True'],
        ])

    def test_app_relation_data_modify_local_as_minion(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', '''
            if [ "$2" = 4 ]; then
                echo '["remoteapp1/0", "remoteapp1/1"]'
            else
                exit 2
            fi
        ''')
        fake_script(self, 'relation-get', '''
            if [ "$2" = 4 ] && [ "$4" = myapp ]; then
                echo '{"password": "deadbeefcafe"}'
            else
                exit 2
            fi
        ''')
        fake_script(self, 'is-leader', 'echo false')

        local_app = self.model.unit.app

        rel_db1 = self.model.get_relation('db1')
        self.assertEqual(rel_db1.data[local_app], {'password': 'deadbeefcafe'})

        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[local_app]['password'] = 'foobar'

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-get', '-r', '4', '-', 'myapp', '--app=True', '--format=json'],
            ['is-leader', '--format=json'],
        ])

    def test_relation_data_del_key(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', """[ "$2" = 4 ] && echo '["remoteapp1/0"]' || exit 2""")
        fake_script(self, 'relation-set', '''[ "$2" = 4 ] && exit 0 || exit 2''')
        fake_script(self, 'relation-get', '''
            if [ "$2" = 4 ] && [ "$4" = "myapp/0" ]; then
                echo '{"host": "bar"}'
            else
                exit 2
            fi
        ''')

        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        del rel_db1.data[self.model.unit]['host']
        fake_script(self, 'relation-get', '''
            if [ "$2" = 4 ] && [ "$4" = "myapp/0" ]; then
                echo '{}'
            else
                exit 2
            fi
        ''')
        self.assertNotIn('host', rel_db1.data[self.model.unit])

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['relation-get', '-r', '4', '-', 'myapp/0', '--app=False', '--format=json'],
            ['relation-set', '-r', '4', 'host=', '--app=False']
        ])

    def test_relation_set_fail(self):
        fake_script(self, 'relation-ids', """[ "$1" = db2 ] && echo '["db2:5"]' || echo '[]'""")
        fake_script(self, 'relation-list',
                    """[ "$2" = 5 ] && echo '["remoteapp1/0"]' || exit 2""")
        fake_script(self, 'relation-get', '''
            if [ "$2" = 5 ] && [ "$4" = "myapp/0" ]; then
                echo '{"host": "myapp-0"}'
            else
                exit 2
            fi
        ''')
        fake_script(self, 'relation-set', 'exit 2')

        rel_db2 = self.model.relations['db2'][0]
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db2.data[self.model.unit])
        with self.assertRaises(ops.model.ModelError):
            rel_db2.data[self.model.unit]['host'] = 'bar'
        self.assertEqual(rel_db2.data[self.model.unit]['host'], 'myapp-0')
        with self.assertRaises(ops.model.ModelError):
            del rel_db2.data[self.model.unit]['host']
        self.assertIn('host', rel_db2.data[self.model.unit])

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db2', '--format=json'],
            ['relation-list', '-r', '5', '--format=json'],
            ['relation-get', '-r', '5', '-', 'myapp/0', '--app=False', '--format=json'],
            ['relation-set', '-r', '5', 'host=bar', '--app=False'],
            ['relation-set', '-r', '5', 'host=', '--app=False']
        ])

    def test_relation_get_set_is_app_arg(self):
        self.backend = ops.model.ModelBackend()

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

    def test_relation_data_type_check(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list',
                    """[ "$2" = 4 ] && echo '["remoteapp1/0"]' || exit 2""")
        fake_script(self, 'relation-get', '''
            if [ "$2" = 4 ] && [ "$4" = "myapp/0" ]; then
                echo '{"host": "myapp-0"}'
            else
                exit 2
            fi
        ''')

        rel_db1 = self.model.get_relation('db1')
        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = 1
        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = {'foo': 'bar'}
        with self.assertRaises(ops.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = None

        self.assertEqual(fake_script_calls(self), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json']
        ])

    def test_config(self):
        fake_script(self, 'config-get', """echo '{"foo":"foo","bar":1,"qux":true}'""")
        self.assertEqual(self.model.config, {
            'foo': 'foo',
            'bar': 1,
            'qux': True,
        })
        with self.assertRaises(TypeError):
            # Confirm that we cannot modify config values.
            self.model.config['foo'] = 'bar'

        self.assertEqual(fake_script_calls(self), [['config-get', '--format=json']])

    def test_is_leader(self):
        def check_remote_units():
            fake_script(self, 'relation-ids',
                        """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")

            fake_script(self, 'relation-list',
                        """[ "$2" = 4 ] && echo '["remoteapp1/0", "remoteapp1/1"]' || exit 2""")

            # Cannot determine leadership for remote units.
            for u in self.model.get_relation('db1').units:
                with self.assertRaises(RuntimeError):
                    u.is_leader()

        fake_script(self, 'is-leader', 'echo true')
        self.assertTrue(self.model.unit.is_leader())

        check_remote_units()

        # Create a new model and backend to drop a cached is-leader output.
        self.backend = ops.model.ModelBackend()
        meta = ops.charm.CharmMeta()
        meta.relations = {
            'db0': RelationMeta('provides', 'db0', {'interface': 'db0', 'scope': 'global'}),
            'db1': RelationMeta('requires', 'db1', {'interface': 'db1', 'scope': 'global'}),
            'db2': RelationMeta('peers', 'db2', {'interface': 'db2', 'scope': 'global'}),
        }
        self.model = ops.model.Model('myapp/0', meta, self.backend)

        fake_script(self, 'is-leader', 'echo false')
        self.assertFalse(self.model.unit.is_leader())

        check_remote_units()

        self.assertEqual(fake_script_calls(self), [
            ['is-leader', '--format=json'],
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
            ['is-leader', '--format=json'],
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
        ])

    def test_is_leader_refresh(self):
        fake_script(self, 'is-leader', 'echo false')
        self.assertFalse(self.model.unit.is_leader())

        # Change the leadership status and force a recheck.
        fake_script(self, 'is-leader', 'echo true')
        self.backend._leader_check_time = None
        self.assertTrue(self.model.unit.is_leader())

        # Force a recheck without changing the leadership status.
        fake_script(self, 'is-leader', 'echo true')
        self.backend._leader_check_time = None
        self.assertTrue(self.model.unit.is_leader())

    def test_resources(self):
        meta = ops.charm.CharmMeta()
        meta.resources = {'foo': None, 'bar': None}
        model = ops.model.Model('myapp/0', meta, self.backend)

        with self.assertRaises(RuntimeError):
            model.resources.fetch('qux')

        fake_script(self, 'resource-get', 'exit 1')
        with self.assertRaises(ops.model.ModelError):
            model.resources.fetch('foo')

        fake_script(self, 'resource-get',
                    'echo /var/lib/juju/agents/unit-test-0/resources/$1/$1.tgz')
        self.assertEqual(model.resources.fetch('foo').name, 'foo.tgz')
        self.assertEqual(model.resources.fetch('bar').name, 'bar.tgz')

    def test_pod_spec(self):
        fake_script(self, 'pod-spec-set', """
                    cat $2 > $(dirname $0)/spec.json
                    [[ -n $4 ]] && cat $4 > $(dirname $0)/k8s_res.json || true
                    """)
        fake_script(self, 'is-leader', 'echo true')
        spec_path = self.fake_script_path / 'spec.json'
        k8s_res_path = self.fake_script_path / 'k8s_res.json'

        def check_calls(calls):
            # There may 1 or 2 calls because of is-leader.
            self.assertLessEqual(len(fake_calls), 2)
            pod_spec_call = next(filter(lambda c: c[0] == 'pod-spec-set', calls))
            self.assertEqual(pod_spec_call[:2], ['pod-spec-set', '--file'])

            # 8 bytes are used as of python 3.4.0, see Python bug #12015.
            # Other characters are from POSIX 3.282 (Portable Filename
            # Character Set) a subset of which Python's mkdtemp uses.
            self.assertRegex(pod_spec_call[2], '.*/tmp[A-Za-z0-9._-]{8}-pod-spec-set')

        self.model.pod.set_spec({'foo': 'bar'})
        self.assertEqual(spec_path.read_text(), '{"foo": "bar"}')
        self.assertFalse(k8s_res_path.exists())

        fake_calls = fake_script_calls(self, clear=True)
        check_calls(fake_calls)

        self.model.pod.set_spec({'bar': 'foo'}, {'qux': 'baz'})
        self.assertEqual(spec_path.read_text(), '{"bar": "foo"}')
        self.assertEqual(k8s_res_path.read_text(), '{"qux": "baz"}')

        fake_calls = fake_script_calls(self, clear=True)
        check_calls(fake_calls)

        # Create a new model to drop is-leader caching result.
        self.backend = ops.model.ModelBackend()
        meta = ops.charm.CharmMeta()
        self.model = ops.model.Model('myapp/0', meta, self.backend)
        fake_script(self, 'is-leader', 'echo false')
        with self.assertRaises(ops.model.ModelError):
            self.model.pod.set_spec({'foo': 'bar'})

    def test_base_status_instance_raises(self):
        with self.assertRaises(TypeError):
            ops.model.StatusBase('test')

    def test_active_message_default(self):
        self.assertEqual(ops.model.ActiveStatus().message, '')

    def test_local_set_valid_unit_status(self):
        test_cases = [(
            ops.model.ActiveStatus('Green'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertEqual(fake_script_calls(self, True),
                                     [['status-set', '--application=False', 'active', 'Green']]),
        ), (
            ops.model.MaintenanceStatus('Yellow'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertEqual(
                fake_script_calls(self, True),
                [['status-set', '--application=False', 'maintenance', 'Yellow']]),
        ), (
            ops.model.BlockedStatus('Red'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertEqual(fake_script_calls(self, True),
                                     [['status-set', '--application=False', 'blocked', 'Red']]),
        ), (
            ops.model.WaitingStatus('White'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertEqual(fake_script_calls(self, True),
                                     [['status-set', '--application=False', 'waiting', 'White']]),
        )]

        for target_status, setup_tools, check_tool_calls in test_cases:
            setup_tools()

            self.model.unit.status = target_status

            self.assertEqual(self.model.unit.status, target_status)

            check_tool_calls()

    def test_local_set_valid_app_status(self):
        fake_script(self, 'is-leader', 'echo true')
        test_cases = [(
            ops.model.ActiveStatus('Green'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertIn(['status-set', '--application=True', 'active', 'Green'],
                                  fake_script_calls(self, True)),
        ), (
            ops.model.MaintenanceStatus('Yellow'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertIn(['status-set', '--application=True', 'maintenance', 'Yellow'],
                                  fake_script_calls(self, True)),
        ), (
            ops.model.BlockedStatus('Red'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertIn(['status-set', '--application=True', 'blocked', 'Red'],
                                  fake_script_calls(self, True)),
        ), (
            ops.model.WaitingStatus('White'),
            lambda: fake_script(self, 'status-set', 'exit 0'),
            lambda: self.assertIn(['status-set', '--application=True', 'waiting', 'White'],
                                  fake_script_calls(self, True)),
        )]

        for target_status, setup_tools, check_tool_calls in test_cases:
            setup_tools()

            self.model.app.status = target_status

            self.assertEqual(self.model.app.status, target_status)

            check_tool_calls()

    def test_set_app_status_non_leader_raises(self):
        fake_script(self, 'is-leader', 'echo false')

        with self.assertRaises(RuntimeError):
            self.model.app.status

        with self.assertRaises(RuntimeError):
            self.model.app.status = ops.model.ActiveStatus()

    def test_local_set_invalid_status(self):
        fake_script(self, 'status-set', 'exit 1')
        fake_script(self, 'is-leader', 'echo true')

        with self.assertRaises(ops.model.ModelError):
            self.model.unit.status = ops.model.UnknownStatus()

        self.assertEqual(fake_script_calls(self, True), [
            ['status-set', '--application=False', 'unknown', ''],
        ])

        with self.assertRaises(ops.model.ModelError):
            self.model.app.status = ops.model.UnknownStatus()

        # A leadership check is needed for application status.
        self.assertEqual(fake_script_calls(self, True), [
            ['is-leader', '--format=json'],
            ['status-set', '--application=True', 'unknown', ''],
        ])

    def test_status_set_is_app_not_bool_raises(self):
        self.backend = ops.model.ModelBackend()

        for is_app_v in [None, 1, 2.0, 'a', b'beef', object]:
            with self.assertRaises(TypeError):
                self.backend.status_set(ops.model.ActiveStatus, is_app=is_app_v)

    def test_remote_unit_status(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', '''
            if [ "$2" = 4 ]; then
                echo '["remoteapp1/0", "remoteapp1/1"]'
            else
                exit 2
            fi
        ''')

        remote_unit = next(filter(lambda u: u.name == 'remoteapp1/0',
                                  self.model.get_relation('db1').units))

        test_statuses = (
            ops.model.UnknownStatus(),
            ops.model.ActiveStatus('Green'),
            ops.model.MaintenanceStatus('Yellow'),
            ops.model.BlockedStatus('Red'),
            ops.model.WaitingStatus('White'),
        )

        for target_status in test_statuses:
            with self.assertRaises(RuntimeError):
                remote_unit.status = target_status

    def test_remote_app_status(self):
        fake_script(self, 'relation-ids', """[ "$1" = db1 ] && echo '["db1:4"]' || echo '[]'""")
        fake_script(self, 'relation-list', '''
            if [ "$2" = 4 ]; then
                echo '["remoteapp1/0", "remoteapp1/1"]'
            else
                exit 2
            fi
        ''')

        remoteapp1 = self.model.get_relation('db1').app

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
            with self.assertRaises(RuntimeError):
                remoteapp1.status = target_status

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['relation-ids', 'db1', '--format=json'],
            ['relation-list', '-r', '4', '--format=json'],
        ])

    def test_storage(self):
        meta = ops.charm.CharmMeta()
        meta.storages = {'disks': None, 'data': None}
        self.model = ops.model.Model('myapp/0', meta, self.backend)

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

        self.assertEqual(len(self.model.storages), 2)
        self.assertEqual(self.model.storages.keys(), meta.storages.keys())
        self.assertIn('disks', self.model.storages)
        test_cases = {
            0: {'name': 'disks', 'location': pathlib.Path('/var/srv/disks/0')},
            1: {'name': 'disks', 'location': pathlib.Path('/var/srv/disks/1')},
        }
        for storage in self.model.storages['disks']:
            self.assertEqual(storage.name, 'disks')
            self.assertIn(storage.id, test_cases)
            self.assertEqual(storage.name, test_cases[storage.id]['name'])
            self.assertEqual(storage.location, test_cases[storage.id]['location'])

        self.assertEqual(fake_script_calls(self, clear=True), [
            ['storage-list', 'disks', '--format=json'],
            ['storage-get', '-s', 'disks/0', 'location', '--format=json'],
            ['storage-get', '-s', 'disks/1', 'location', '--format=json'],
        ])

        self.assertSequenceEqual(self.model.storages['data'], [])
        self.model.storages.request('data', count=3)
        self.assertEqual(fake_script_calls(self), [
            ['storage-list', 'data', '--format=json'],
            ['storage-add', 'data=3'],
        ])

        # Try to add storage not present in charm metadata.
        with self.assertRaises(ops.model.ModelError):
            self.model.storages.request('deadbeef')

        # Invalid count parameter types.
        for count_v in [None, False, 2.0, 'a', b'beef', object]:
            with self.assertRaises(TypeError):
                self.model.storages.request('data', count_v)


class TestModelBindings(unittest.TestCase):

    def setUp(self):
        def restore_env(env):
            os.environ.clear()
            os.environ.update(env)
        self.addCleanup(restore_env, os.environ.copy())

        os.environ['JUJU_UNIT_NAME'] = 'myapp/0'

        meta = ops.charm.CharmMeta()
        meta.relations = {
            'db0': RelationMeta('provides', 'db0', {'interface': 'db0', 'scope': 'global'}),
            'db1': RelationMeta('requires', 'db1', {'interface': 'db1', 'scope': 'global'}),
            'db2': RelationMeta('peers', 'db2', {'interface': 'db2', 'scope': 'global'}),
        }
        self.backend = ops.model.ModelBackend()
        self.model = ops.model.Model('myapp/0', meta, self.backend)

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


class TestModelBackend(unittest.TestCase):

    def setUp(self):
        os.environ['JUJU_UNIT_NAME'] = 'myapp/0'
        self.addCleanup(os.environ.pop, 'JUJU_UNIT_NAME')

        self._backend = None

    @property
    def backend(self):
        if self._backend is None:
            self._backend = ops.model.ModelBackend()
        return self._backend

    def test_relation_tool_errors(self):
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
            [['relation-set', '-r', '3', 'foo=bar', '--app=False']],
        ), (
            lambda: fake_script(self, 'relation-set', 'echo {} >&2 ; exit 2'.format(err_msg)),
            lambda: self.backend.relation_set(3, 'foo', 'bar', is_app=False),
            ops.model.RelationNotFoundError,
            [['relation-set', '-r', '3', 'foo=bar', '--app=False']],
        ), (
            lambda: fake_script(self, 'relation-get', 'echo fooerror >&2 ; exit 1'),
            lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
            ops.model.ModelError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--app=False', '--format=json']],
        ), (
            lambda: fake_script(self, 'relation-get', 'echo {} >&2 ; exit 2'.format(err_msg)),
            lambda: self.backend.relation_get(3, 'remote/0', is_app=False),
            ops.model.RelationNotFoundError,
            [['relation-get', '-r', '3', '-', 'remote/0', '--app=False', '--format=json']],
        )]

        for do_fake, run, exception, calls in test_cases:
            do_fake()
            with self.assertRaises(exception):
                run()
            self.assertEqual(fake_script_calls(self, clear=True), calls)

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

    def test_juju_log(self):
        fake_script(self, 'juju-log', 'exit 0')
        self.backend.juju_log('WARNING', 'foo')
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['juju-log', '--log-level', 'WARNING', 'foo']])

        with self.assertRaises(TypeError):
            self.backend.juju_log('DEBUG')
        self.assertEqual(fake_script_calls(self, clear=True), [])

        fake_script(self, 'juju-log', 'exit 1')
        with self.assertRaises(ops.model.ModelError):
            self.backend.juju_log('BAR', 'foo')
        self.assertEqual(fake_script_calls(self, clear=True),
                         [['juju-log', '--log-level', 'BAR', 'foo']])

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
