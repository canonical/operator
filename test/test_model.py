#!/usr/bin/python3

import unittest
from unittest.mock import Mock

import juju.model


class TestModelBackend:
    relation_set_called = False

    def relation_ids(self, relation_name):
        return {
            'db0': [],
            'db1': ['db1:1'],
            'db2': ['db2:1', 'db2:2'],
        }[relation_name]

    def relation_list(self, relation_id):
        return {
            'db1:1': ['remoteapp1/0'],
            'db2:1': ['remoteapp1/0'],
            'db2:2': ['remoteapp2/0'],
        }[relation_id]

    def relation_get(self, relation_id, member_name):
        return {
            'db1:1': {
                'myapp/0': {'host': 'myapp-0'},
                'remoteapp1/0': {'host': 'remoteapp1-0'},
            },
            'db2:1': {
                'myapp/0': {'host': 'myapp-0'},
                'remoteapp1/0': {'host': 'remoteapp1-0'},
            },
            'db2:2': {
                'myapp/0': {'host': 'myapp-0'},
                'remoteapp2/0': {'host': 'remoteapp2-0'},
            },
        }[relation_id][member_name]

    def relation_set(self, relation_id, key, value):
        self.relation_set_called = True

    def config_get(self):
        return {
            'foo': 'foo',
            'bar': 1,
            'qux': True,
        }


class TestModel(unittest.TestCase):
    def setUp(self):
        self.model = juju.model.Model('myapp/0', ['db0', 'db1', 'db2'], TestModelBackend())

    def test_model(self):
        self.assertIs(self.model.app, self.model.unit.app)

    def test_relations_keys(self):
        for relation in self.model.relations['db2']:
            self.assertIn(self.model.unit, relation.data)
            unit_from_rel = next(filter(lambda u: u.name == 'myapp/0', relation.data.keys()))
            self.assertIs(self.model.unit, unit_from_rel)

    def test_relation_helper(self):
        self.assertIsNone(self.model.relation('db0'))
        self.assertIsInstance(self.model.relation('db1'), juju.model.Relation)
        with self.assertRaises(juju.model.TooManyRelatedApps):
            self.model.relation('db2')

    def test_relation_data(self):
        random_unit = self.model._cache.get(juju.model.Unit, 'randomunit/0')
        with self.assertRaises(KeyError):
            self.model.relation('db1').data[random_unit]
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0', self.model.relation('db1').units))
        self.assertEqual(self.model.relation('db1').data[remoteapp1_0], {'host': 'remoteapp1-0'})

    def test_relation_data_modify_remote(self):
        rel_db1 = self.model.relation('db1')
        backend = self.model._backend
        remoteapp1_0 = next(filter(lambda u: u.name == 'remoteapp1/0', self.model.relation('db1').units))
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[remoteapp1_0])
        with self.assertRaises(TypeError):
            rel_db1.data[remoteapp1_0]['foo'] = 'bar'
        self.assertFalse(backend.relation_set_called)
        self.assertNotIn('foo', rel_db1.data[remoteapp1_0])

    def test_relation_data_modify_local(self):
        rel_db1 = self.model.relation('db1')
        backend = self.model._backend
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        rel_db1.data[self.model.unit]['host'] = 'bar'
        self.assertTrue(backend.relation_set_called)
        self.assertEqual(rel_db1.data[self.model.unit]['host'], 'bar')

    def test_relation_data_del_key(self):
        rel_db1 = self.model.relation('db1')
        backend = self.model._backend
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        del rel_db1.data[self.model.unit]['host']
        self.assertTrue(backend.relation_set_called)
        self.assertNotIn('host', rel_db1.data[self.model.unit])

    def test_relation_set_fail(self):
        rel_db1 = self.model.relation('db1')
        backend = self.model._backend
        backend.relation_set = Mock(side_effect=ValueError)
        # Force memory cache to be loaded.
        self.assertIn('host', rel_db1.data[self.model.unit])
        with self.assertRaises(ValueError):
            rel_db1.data[self.model.unit]['host'] = 'bar'
        self.assertEqual(rel_db1.data[self.model.unit]['host'], 'myapp-0')
        with self.assertRaises(ValueError):
            del rel_db1.data[self.model.unit]['host']
        self.assertIn('host', rel_db1.data[self.model.unit])

    def test_relation_data_type_check(self):
        rel_db1 = self.model.relation('db1')
        backend = self.model._backend
        with self.assertRaises(TypeError):
            rel_db1.data[self.model.unit]['foo'] = 1
        with self.assertRaises(TypeError):
            rel_db1.data[self.model.unit]['foo'] = {'foo': 'bar'}
        with self.assertRaises(TypeError):
            rel_db1.data[self.model.unit]['foo'] = None
        self.assertFalse(backend.relation_set_called)

    def test_config(self):
        self.assertEqual(self.model.config, {
            'foo': 'foo',
            'bar': 1,
            'qux': True,
        })
        with self.assertRaises(TypeError):
            # Confirm that we cannot modify config values.
            self.model.config['foo'] = 'bar'
