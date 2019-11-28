#!/usr/bin/python3

import os
import tempfile
import subprocess
import pathlib
import shutil
import unittest

import op.model
import op.charm


# TODO: We need some manner of test to validate the actual ModelBackend implementation, round-tripped
# through the actual subprocess calls. Either this class could implement these functions as executables
# that were called via subprocess, or more simple tests that just test through ModelBackend while leaving
# these tests alone, depending on what proves easier.
class FakeModelBackend:
    def __init__(self):
        self.relation_set_calls = []

        self.unit_name = 'myapp/0'
        self.app_name = 'myapp'

    def relation_ids(self, relation_name):
        return {
            'db0': [],
            'db1': [4],
            'db2': [5, 6],
        }[relation_name]

    def relation_list(self, relation_id):
        try:
            return {
                4: ['remoteapp1/0'],
                5: ['remoteapp1/0'],
                6: ['remoteapp2/0'],
            }[relation_id]
        except KeyError:
            raise op.model.RelationNotFound()

    def relation_get(self, relation_id, member_name):
        try:
            return {
                4: {
                    'myapp/0': {'host': 'myapp-0'},
                    'remoteapp1/0': {'host': 'remoteapp1-0'},
                },
                5: {
                    'myapp/0': {'host': 'myapp-0'},
                    'remoteapp1/0': {'host': 'remoteapp1-0'},
                },
                6: {
                    'myapp/0': {'host': 'myapp-0'},
                    'remoteapp2/0': {'host': 'remoteapp2-0'},
                },
            }[relation_id][member_name]
        except KeyError:
            raise op.model.RelationNotFound()

    def relation_set(self, relation_id, key, value):
        if relation_id == 5:
            raise ValueError()
        self.relation_set_calls.append((relation_id, key, value))

    def config_get(self):
        return {
            'foo': 'foo',
            'bar': 1,
            'qux': True,
        }

class TestModel(unittest.TestCase):

    def setUp(self):
        self.backend = FakeModelBackend()
        meta = op.charm.CharmMeta()
        meta.relations = {'db0': None, 'db1': None, 'db2': None}
        self.model = op.model.Model('myapp/0', meta, self.backend)

        os.environ['JUJU_UNIT_NAME'] = 'myapp/0'
        self.addCleanup(os.environ.pop, 'JUJU_UNIT_NAME')

    def test_model(self):
        self.assertIs(self.model.app, self.model.unit.app)

    def test_relations_keys(self):
        for relation in self.model.relations['db2']:
            self.assertIn(self.model.unit, relation.data)
            unit_from_rel = next(filter(lambda u: u.name == 'myapp/0', relation.data.keys()))
            self.assertIs(self.model.unit, unit_from_rel)

    def test_get_relation(self):
        with self.assertRaises(op.model.ModelError):
            self.model.get_relation('db1', 'db1:4')
        db1_4 = self.model.get_relation('db1', 4)
        self.assertIsInstance(db1_4, op.model.Relation)
        dead_rel = self.model.get_relation('db1', 7)
        self.assertIsInstance(dead_rel, op.model.Relation)
        self.assertEqual(list(dead_rel.data.keys()), [self.model.unit])
        self.assertEqual(dead_rel.data[self.model.unit], {})
        self.assertIsNone(self.model.get_relation('db0'))
        self.assertIs(self.model.get_relation('db1'), db1_4)
        with self.assertRaises(op.model.TooManyRelatedApps):
            self.model.get_relation('db2')

    def test_remote_units_is_our(self):
        for u in self.model.get_relation('db1').units:
            self.assertFalse(u._is_our_unit)
            self.assertFalse(u.app._is_our_app)

    def test_our_unit_is_our(self):
        self.assertTrue(self.model.unit._is_our_unit)
        self.assertTrue(self.model.unit.app._is_our_app)

    def test_relation_data(self):
        random_unit = self.model._cache.get(op.model.Unit, 'randomunit/0')
        with self.assertRaises(KeyError):
            self.model.get_relation('db1').data[random_unit]
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0', self.model.get_relation('db1').units))
        self.assertEqual(self.model.get_relation('db1').data[remoteapp1_0], {'host': 'remoteapp1-0'})

    def test_relation_data_modify_remote(self):
        rel_db1 = self.model.get_relation('db1')
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0', self.model.get_relation('db1').units))
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[remoteapp1_0])
        with self.assertRaises(op.model.RelationDataError):
            rel_db1.data[remoteapp1_0]['foo'] = 'bar'
        self.assertEqual(self.backend.relation_set_calls, [])
        self.assertNotIn('foo', rel_db1.data[remoteapp1_0])

    def test_relation_data_modify_our(self):
        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        rel_db1.data[self.model.unit]['host'] = 'bar'
        self.assertEqual(self.backend.relation_set_calls, [(4, 'host', 'bar')])
        self.assertEqual(rel_db1.data[self.model.unit]['host'], 'bar')

    def test_relation_data_del_key(self):
        rel_db1 = self.model.get_relation('db1')
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        del rel_db1.data[self.model.unit]['host']
        self.assertEqual(self.backend.relation_set_calls, [(4, 'host', '')])
        self.assertNotIn('host', rel_db1.data[self.model.unit])

    def test_relation_set_fail(self):
        rel_db2 = self.model.relations['db2'][0]
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db2.data[self.model.unit])
        with self.assertRaises(ValueError):
            rel_db2.data[self.model.unit]['host'] = 'bar'
        self.assertEqual(rel_db2.data[self.model.unit]['host'], 'myapp-0')
        with self.assertRaises(ValueError):
            del rel_db2.data[self.model.unit]['host']
        self.assertIn('host', rel_db2.data[self.model.unit])

    def test_relation_data_type_check(self):
        rel_db1 = self.model.get_relation('db1')
        with self.assertRaises(op.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = 1
        with self.assertRaises(op.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = {'foo': 'bar'}
        with self.assertRaises(op.model.RelationDataError):
            rel_db1.data[self.model.unit]['foo'] = None
        self.assertEqual(self.backend.relation_set_calls, [])

    def test_config(self):
        self.assertEqual(self.model.config, {
            'foo': 'foo',
            'bar': 1,
            'qux': True,
        })
        with self.assertRaises(TypeError):
            # Confirm that we cannot modify config values.
            self.model.config['foo'] = 'bar'

    def test_is_leader(self):
        self.backend = op.model.ModelBackend()
        meta = op.charm.CharmMeta()
        meta.relations = {'db0': None, 'db1': None, 'db2': None}
        self.model = op.model.Model('myapp/0', meta, self.backend)

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

        self.backend = op.model.ModelBackend()
        self.model = op.model.Model('myapp/0', meta, self.backend)

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

    def test_resources(self):
        backend = op.model.ModelBackend()
        meta = op.charm.CharmMeta()
        meta.resources = {'foo': None, 'bar': None}
        model = op.model.Model('myapp/0', meta, backend)

        with self.assertRaises(RuntimeError):
            model.resources.fetch('qux')

        fake_script(self, 'resource-get', 'exit 1')
        with self.assertRaises(subprocess.CalledProcessError):
            model.resources.fetch('foo')

        fake_script(self, 'resource-get', 'echo /var/lib/juju/agents/unit-test-0/resources/$1/$1.tgz')
        self.assertEqual(model.resources.fetch('foo').name, 'foo.tgz')
        self.assertEqual(model.resources.fetch('bar').name, 'bar.tgz')

    def test_pod_spec(self):
        meta = op.charm.CharmMeta()
        meta.relations = {'db0': None, 'db1': None, 'db2': None}
        model = op.model.Model('myapp/0', meta, op.model.ModelBackend())

        fake_script(self, 'pod-spec-set', """
                    cat $2 > $(dirname $0)/spec.json
                    [[ -n $4 ]] && cat $4 > $(dirname $0)/k8s_res.json || true
                    """)
        spec_path = self.fake_script_path / 'spec.json'
        k8s_res_path = self.fake_script_path / 'k8s_res.json'

        model.pod.set_spec({'foo': 'bar'})
        self.assertEqual(spec_path.read_text(), '{"foo": "bar"}')
        self.assertFalse(k8s_res_path.exists())

        model.pod.set_spec({'bar': 'foo'}, {'qux': 'baz'})
        self.assertEqual(spec_path.read_text(), '{"bar": "foo"}')
        self.assertEqual(k8s_res_path.read_text(), '{"qux": "baz"}')


def fake_script(test_case, name, content):
    if not hasattr(test_case, 'fake_script_path'):
        fake_script_path = tempfile.mkdtemp('-fake_script')
        os.environ['PATH'] = f'{fake_script_path}:{os.environ["PATH"]}'

        def cleanup():
            shutil.rmtree(fake_script_path)
            os.environ['PATH'] = os.environ['PATH'].replace(fake_script_path + ':', '')

        test_case.addCleanup(cleanup)
        test_case.fake_script_path = pathlib.Path(fake_script_path)

    with open(test_case.fake_script_path / name, "w") as f:
        # Before executing the provided script, dump the provided arguments in calls.txt.
        f.write('#!/bin/bash\n{ echo -n $(basename $0); for s in "$@"; do echo -n \\;$s; done; echo; } >> $(dirname $0)/calls.txt\n' + content)
    os.chmod(test_case.fake_script_path / name, 0o755)

def fake_script_calls(test_case):
    with open(test_case.fake_script_path / 'calls.txt') as f:
        return [line.split(';') for line in f.read().splitlines()]


class FakeScriptTest(unittest.TestCase):

    def test_fake_script_works(self):
        fake_script(self, 'foo', 'echo foo runs')
        fake_script(self, 'bar', 'echo bar runs')
        output = subprocess.getoutput('foo a "b c"; bar "d e" f')
        self.assertEqual(output, 'foo runs\nbar runs')
        self.assertEqual(fake_script_calls(self), [
            ['foo', 'a', 'b c'],
            ['bar', 'd e', 'f'],
        ])
