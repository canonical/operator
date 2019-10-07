#!/usr/bin/python3

import unittest
import unittest.mock

import juju.model


class BaseCase(unittest.TestCase):
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
                'db1:1': {
                    'myapp': {'uri': 'jdbc:pgsql://my-app-0/mydb'},
                    'myapp/0': {'host': 'myapp-0'},
                    'remoteapp1': {'db-name': 'mydb'},
                    'remoteapp1/0': {'host': 'remoteapp1-0'},
                },
            },
            'db2': {
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
            },
        },
    }

    def setUp(self):
        run_patcher = unittest.mock.patch.object(juju.model, 'run')
        self.run = run_patcher.start()
        self.run.side_effect = lambda: self.fail("Run should not be called")
        self.addCleanup(run_patcher.stop)


class TestModel(BaseCase):
    def test_relation(self):
        model = juju.model.Model(self.model_data)
        self.assertIsNone(model.relation('db0'))
        self.assertIsInstance(model.relation('db1'), juju.model.Relation)
        with self.assertRaises(juju.model.TooManyRelatedApps):
            model.relation('db2')


class TestApplication(BaseCase):
    def test_equivalence(self):
        model = juju.model.Model(self.model_data)
        myapp = model.app
        rel_myapp = model.relation('db1').apps[0]
        rel_remoteapp = model.relation('db1').apps[1]
        self.assertIsNot(myapp, rel_myapp)
        self.assertIsNot(myapp, rel_remoteapp)
        self.assertEqual(myapp, rel_myapp)
        self.assertNotEqual(myapp, rel_remoteapp)
        d = {myapp: 'myapp',
             rel_myapp: 'myapp',
             rel_remoteapp: 'remoteapp'}
        self.assertEqual(d, {myapp: 'myapp', rel_remoteapp: 'remoteapp'})


class TestUnit(BaseCase):
    def test_equivalence(self):
        model = juju.model.Model(self.model_data)
        myunit = model.unit
        rel_myunit = model.relation('db1').apps[0].units[0]
        rel_remoteunit = model.relation('db1').apps[1].units[0]
        self.assertIsNot(myunit, rel_myunit)
        self.assertIsNot(myunit, rel_remoteunit)
        self.assertEqual(myunit, rel_myunit)
        self.assertNotEqual(myunit, rel_remoteunit)
        d = {myunit: 'myapp/0',
             rel_myunit: 'myapp/0',
             rel_remoteunit: 'remoteapp/0'}
        self.assertEqual(d, {myunit: 'myapp/0', rel_remoteunit: 'remoteapp/0'})


class _ProcResult:
    def __init__(self, stdout):
        self.stdout = stdout


class TestRelationMap(BaseCase):
    def test_lazyload(self):
        # TODO: This needs an integration test in an actual Juju model, but until then, this will
        # give basic coverage of the code.
        self.run.side_effect = [_ProcResult(b"- db-admin:2\n- db-admin:3\n")]
        rel_map = juju.model.RelationMap({'db-admin': None, 'db': None})
        rels = rel_map['db-admin']
        self.assertEqual(len(rels), 2)
        self.assertIsInstance(rels[0], juju.model.Relation)
        self.assertIsInstance(rels[1], juju.model.Relation)
        # Confirm that value is cached.
        rel_map['db-admin']
        # Confirm that accessing other values tries to fetch more data.
        with self.assertRaises(StopIteration):
            rel_map['db']


class TestRelation(BaseCase):
    def test_lazyload(self):
        # TODO: This needs an integration test in an actual Juju model, but until then, this will
        # give basic coverage of the code.
        self.run.side_effect = [_ProcResult(b"- remote-56a0f163eb4e4f2e88d50983dca7be02/0\n")]
        rel = juju.model.Relation('db-admin:3')
        self.assertEqual(len(rel.apps), 1)
        self.assertEqual(len(rel.apps[0].units), 1)
        self.assertEqual(rel.apps[0].name, 'remote-56a0f163eb4e4f2e88d50983dca7be02')
        self.assertEqual(rel.apps[0].units[0].name, 'remote-56a0f163eb4e4f2e88d50983dca7be02/0')


class TestRelationData(BaseCase):
    def test_lazyload(self):
        # TODO: This needs an integration test in an actual Juju model, but until then, this will
        # give basic coverage of the code.
        self.run.side_effect = None
        self.run.side_effect = [_ProcResult(b"database: snap_store_proxy\n"
                                            b"private-address: 10.4.23.156\n")]
        rel_data = juju.model.RelationData('db-admin:3')
        unit = juju.model.Unit('unit/0')
        self.assertEqual(rel_data[unit], {'database': 'snap_store_proxy',
                                          'private-address': '10.4.23.156'})
        self.assertIn('unit/0', self.run.call_args[0][0])
        # Confirm that value is cached.
        rel_data[juju.model.Unit('unit/0')]
        # Confirm that accessing other values tries to fetch more data.
        with self.assertRaises(StopIteration):
            rel_data[juju.model.Unit('unit/1')]
