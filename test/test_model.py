#!/usr/bin/python3

import unittest

import juju.model


class TestModelBackend:
    app_name = 'myapp'
    unit_name = 'myapp/0'
    relation_names = ['db0', 'db1', 'db2']

    @classmethod
    def get_model(cls):
        return juju.model.Model(cls.app_name, cls.unit_name, cls.relation_names, cls())

    model_data = {
        'application_name': 'myapp',
        'unit_name': 'myapp/0',
        'units': [
            'myapp/0',
            'myapp/1',
        ],
        'relations': {
            'db0': {},
            'db1': {
            },
            'db2': {
            },
        },
    }

    def goal_state(self):
        return {'units': ['myapp/0', 'myapp/1']}

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
                'myapp': {'uri': 'jdbc:pgsql://my-app-0/mydb'},
                'myapp/0': {'host': 'myapp-0'},
                'remoteapp1': {'db-name': 'mydb'},
                'remoteapp1/0': {'host': 'remoteapp1-0'},
            },
            'db2:1': {
                'myapp': {'uri': 'jdbc:pgsql://my-app-0/mydb'},
                'myapp/0': {'host': 'myapp-0'},
                'remoteapp1': {'db-name': 'mydb'},
                'remoteapp1/0': {'host': 'remoteapp1-0'},
            },
            'db2:2': {
                'myapp': {'uri': 'jdbc:pgsql://my-app-0/mydb'},
                'myapp/0': {'host': 'myapp-0'},
                'remoteapp2': {'db-name': 'mydb'},
                'remoteapp2/0': {'host': 'remoteapp2-0'},
            },
        }[relation_id][member_name]


class TestModel(unittest.TestCase):
    def test_apps(self):
        model = TestModelBackend.get_model()
        myapp = juju.model.Application('myapp', [])
        otherapp = juju.model.Application('otherapp', [])
        self.assertIsNot(model.app, myapp)
        self.assertIsNot(model.app, otherapp)
        self.assertEqual(model.app, myapp)
        self.assertNotEqual(model.app, otherapp)
        d = {model.app: 'myapp',
             myapp: 'myapp',
             otherapp: 'remoteapp'}
        self.assertEqual(d, {myapp: 'myapp', otherapp: 'remoteapp'})
        self.assertEqual(model.app.units, [model.unit, juju.model.Unit('myapp/1')])

    def test_units(self):
        model = TestModelBackend.get_model()
        myunit = juju.model.Unit('myapp/0')
        otherunit = juju.model.Unit('myapp/1')
        self.assertIsNot(model.unit, myunit)
        self.assertIsNot(model.unit, otherunit)
        self.assertEqual(model.unit, myunit)
        self.assertNotEqual(model.unit, otherunit)
        d = {model.unit: 'myapp/0',
             myunit: 'myapp/0',
             otherunit: 'remoteapp/0'}
        self.assertEqual(d, {myunit: 'myapp/0', otherunit: 'remoteapp/0'})

    def test_relations(self):
        model = TestModelBackend.get_model()
        self.assertIsNone(model.relation('db0'))
        self.assertIsInstance(model.relation('db1'), juju.model.Relation)
        with self.assertRaises(juju.model.TooManyRelatedApps):
            model.relation('db2')
        self.assertEqual(model.relations['db2'][1].apps, [juju.model.Application('remoteapp2', [])])
        self.assertEqual(model.relation('db1').data[model.app], {'uri': 'jdbc:pgsql://my-app-0/mydb'})
        with self.assertRaises(KeyError):
            model.relation('db1').data[juju.model.Unit('randomunit/0')]
