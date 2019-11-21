#!/usr/bin/python3

import unittest

import op.model


# TODO: We need some manner of test to validate the actual ModelBackend implementation, round-tripped
# through the actual subprocess calls. Either this class could implement these functions as executables
# that were called via subprocess, or more simple tests that just test through ModelBackend while leaving
# these tests alone, depending on what proves easier.
class FakeModelBackend:
    def __init__(self):
        self.relation_set_calls = []

        self.local_unit_name = 'myapp/0'
        self.local_app_name = 'myapp'

    def local_app_name(self):
        return 'myapp'

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
        self.model = op.model.Model('myapp/0', ['db0', 'db1', 'db2'], self.backend)

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

    def test_remote_units_is_local(self):
        for u in self.model.get_relation('db1').units:
            self.assertFalse(u.is_local)
            self.assertFalse(u.app.is_local)

    def test_local_unit_is_local(self):
        self.assertTrue(self.model.unit.is_local)
        self.assertTrue(self.model.unit.app.is_local)

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

    def test_relation_data_modify_local(self):
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
