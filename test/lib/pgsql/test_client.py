# Copyright 2020 Canonical Ltd.
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

import yaml

from ops.lib.pgsql import client
from ops import (
    charm,
    framework,
    model,
    testing,
)


class TestPostgreSQLDatabase(unittest.TestCase):

    def test_master_host(self):
        master_str = "host=10.11.12.13 user=myuser"
        db = client.PostgreSQLDatabase(master_str)
        self.assertEqual(db.master, master_str)
        self.assertEqual(db.host, "10.11.12.13")
        self.assertEqual(db.properties, {"host": "10.11.12.13", "user": "myuser"})

    def test_real_master(self):
        # Taken from an actual connection to the postgresql charm
        master = ("dbname=test-charm_test-charm host=10.210.24.14"
                  " password=PASS port=5432 user=juju_test-charm")
        db = client.PostgreSQLDatabase(master)
        self.assertEqual(db.database, "test-charm_test-charm")
        self.assertEqual(db.host, "10.210.24.14")
        self.assertEqual(db.user, "juju_test-charm")
        self.assertEqual(db.password, "PASS")
        self.assertEqual(db.port, "5432")


class TestPostgreSQLClient(unittest.TestCase):

    # This is the actual output of 'relation-get' from a stable relation
    # language=YAML
    realData = yaml.safe_load('''
allowed-subnets: 10.210.24.239/32
allowed-units: test-charm/0
database: test-charm_test-charm
egress-subnets: 10.210.24.14/32
host: 10.210.24.14
ingress-address: 10.210.24.14
master: dbname=test-charm_test-charm host=10.210.24.14
  password=MS6ycrxdzmwbRSpsNMnHhPS28bNkYf5b9nWVX8 port=5432 user=juju_test-charm
password: MS6ycrxdzmwbRSpsNMnHhPS28bNkYf5b9nWVX8
port: "5432"
private-address: 10.210.24.14
schema_password: MS6ycrxdzmwbRSpsNMnHhPS28bNkYf5b9nWVX8
schema_user: juju_test-charm
state: standalone
user: juju_test-charm
version: "10"
''')

    def setUp(self):
        self.harness = testing.Harness(charm.CharmBase, meta='''
            name: test-charm
            requires:
                db:
                    interface: client
            ''')
        self.harness.begin()
        self.client = client.PostgreSQLClient(self.harness.charm, "db")

    def test_real_relation_data(self):
        relation_id = self.harness.add_relation('db', 'postgresql')
        self.harness.update_relation_data(
            relation_id, 'test-charm/0', {'egress-subnets': '10.210.24.239/32'})
        self.harness.add_relation_unit(
            relation_id, 'postgresql/0', remote_unit_data=self.realData)
        self.assertEqual('test-charm_test-charm', self.client.master().database)

    def test_master_changed(self):
        relation_id = self.harness.add_relation('db', 'postgresql')
        self.harness.update_relation_data(
            relation_id, 'test-charm/0', {'egress-subnets': '10.210.24.239/32'})
        self.harness.add_relation_unit(
            relation_id, 'postgresql/0', remote_unit_data=self.realData)
        master = self.realData['master']
        self.assertEqual(master, self.client.master().master)

        # change the password
        class Receiver(framework.Object):
            def __init__(self, parent, key):
                super().__init__(parent, key)
                self.changes = []

            def on_master_changed(self, event):
                self.changes.append(event.master)
        r = Receiver(self.harness.framework, 'receiver')
        self.harness.framework.observe(self.client.on.master_changed, r)
        new_master = ("dbname=test-charm_test-charm host=10.210.24.14"
                      " password=2 port=5432 user=juju_test-charm")
        self.harness.update_relation_data(
            relation_id, 'postgresql/0', {'master': new_master, 'password': '2'})
        self.assertEqual(r.changes, [new_master])
        # Changing a different field *doesn't* trigger master changed a second time
        self.harness.update_relation_data(
            relation_id, 'postgresql/0', {'allowed-units': 'test-charm/1'})
        self.assertEqual(r.changes, [new_master])
        # but changing master again, does
        new_master = ("dbname=test-charm_test-charm host=10.210.24.14"
                      " password=2 port=5555 user=juju_test-charm")
        self.harness.update_relation_data(
            relation_id, 'postgresql/0', {'master': new_master, 'port': '5555'})
        self.assertEqual(new_master, self.client.master().master)

    def test_no_relation(self):
        # Without a relation, we must raise a BlockedStatus
        with self.assertRaises(client.PostgreSQLError) as cm:
            self.client.master()
        self.assertIsNotNone(cm.exception.status)
        self.assertIsInstance(cm.exception.status, model.BlockedStatus)

    def test_no_master(self):
        relation_id = self.harness.add_relation('db', 'postgresql')
        # With a relation, but no established master, raise a Waiting status
        with self.assertRaises(client.PostgreSQLError) as cm:
            self.client.master()
        self.assertIsNotNone(cm.exception.status)
        self.assertIsInstance(cm.exception.status, model.WaitingStatus)

    def test_multiple_relations(self):
        rel_id1 = self.harness.add_relation('db', 'postgresql')
        self.harness.add_relation_unit(rel_id1, 'postgresql/0')
        rel_id2 = self.harness.add_relation('db', 'pgsql2')
        self.harness.add_relation_unit(rel_id2, 'pgsql2/0')
        with self.assertRaises(client.PostgreSQLError) as cm:
            self.client.master()
        self.assertIsNotNone(cm.exception.status)
        self.assertIsInstance(cm.exception.status, model.BlockedStatus)

    def test_waits_for_allowed_subnets(self):
        initial_data = self.realData.copy()
        # unset allowed-subnets and allowed-units from the real data.
        initial_data['allowed-subnets'] = ''
        initial_data['allowed-units'] = ''
        # set by Juju
        relation_id = self.harness.add_relation('db', 'postgresql')
        self.harness.update_relation_data(
            relation_id, 'test-charm/0', {'egress-subnets': '10.20.30.40/24'})
        # Initially this unit isn't configured to be allowed to connect to pgsql.
        # There is a master that postgresql is advertising, but we aren't listed as being
        # allowed to talk to it.
        self.harness.add_relation_unit(
            relation_id, 'postgresql/0', remote_unit_data=initial_data)
        with self.assertRaises(client.PostgreSQLError) as cm:
            self.client.master()
        self.assertIsInstance(cm.exception.status, model.WaitingStatus)
        # Someone is allowed, but it isn't us
        self.harness.update_relation_data(
            relation_id, 'postgresql/0', {'allowed-subnets': '1.2.3.4/24'})
        with self.assertRaises(client.PostgreSQLError) as cm:
            self.client.master()
        self.assertIsInstance(cm.exception.status, model.WaitingStatus)
        self.harness.update_relation_data(
            relation_id, 'postgresql/0', {'allowed-subnets': '1.2.3.4/24,10.20.30.40/24'})
        self.assertEqual(self.realData['master'], self.client.master().master)


class TestCommaSeparatedList(unittest.TestCase):

    def test_empty(self):
        self.assertEqual([], client.comma_separated_list(''))

    def test_single_entry(self):
        self.assertEqual(['a'], client.comma_separated_list('a'))

    def test_simple_entries(self):
        self.assertEqual(['a', 'b'], client.comma_separated_list('a,b'))

    def test_strips_whitespace(self):
        self.assertEqual(['a', 'b'], client.comma_separated_list('a,b'))


if __name__ == '__main__':
    unittest.main()
