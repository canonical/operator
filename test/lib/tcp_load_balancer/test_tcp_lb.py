#!/usr/bin/env python3

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
import datetime
import json

from ops.charm import CharmBase
from ops.testing import Harness

from ops.lib.tcp_load_balancer.tcp_lb import (
    TCPBackendManager,
    Listener,
    Backend,
    HealthMonitor,
    TCPLoadBalancer,
    JSON_ENCODE_OPTIONS,
)


class TestTCPBackendManager(unittest.TestCase):

    def setUp(self):
        self.harness = Harness(CharmBase, meta='''
            name: haproxy
            provides:
              tcp-lb:
                interface: tcp-load-balancer
        ''')
        self.harness.begin()
        self.tcp_backend_manager = TCPBackendManager(self.harness.charm, 'tcp-lb')

    def test_pools(self):
        relation_id = self.harness.add_relation('tcp-lb', 'tcp-server')
        self.harness.update_relation_data(
            relation_id, 'haproxy/0', {'ingress-address': '192.0.2.1'})

        self.harness.add_relation_unit(
            relation_id, 'tcp-server/0', {
                'ingress-address': '192.0.2.2',
                'backend': json.dumps({
                    'name': 'tcp-server-0.example',
                    'port': 80,
                    'address': '192.0.2.2',
                }, **JSON_ENCODE_OPTIONS)
            })
        self.harness.add_relation_unit(
            relation_id, 'tcp-server/1', {
                'ingress-address': '192.0.2.3',
                'backend': json.dumps({
                    'name': 'tcp-server-1.example',
                    'port': 80,
                    'address': '192.0.2.3',
                }, **JSON_ENCODE_OPTIONS)
            })
        self.harness.update_relation_data(relation_id, 'tcp-server', {
            'listener': json.dumps({
                'name': 'tcp-server',
                'port': 80,
                'balancing_algorithm': 'least_connections',
            }, **JSON_ENCODE_OPTIONS),
            'health_monitor': json.dumps({
                'timeout': 10.0
            }, **JSON_ENCODE_OPTIONS),
        })
        pools = self.tcp_backend_manager.pools
        test_pool = pools[0]
        self.assertEqual(test_pool.listener.port, 80)
        self.assertEqual(test_pool.listener.name, 'tcp-server')
        self.assertEqual(test_pool.listener.balancing_algorithm, 'least_connections')
        self.assertEqual(test_pool.health_monitor.timeout, datetime.timedelta(seconds=10))

    def test_empty_pool(self):
        relation_id = self.harness.add_relation('tcp-lb', 'tcp-server')
        self.harness.update_relation_data(
            relation_id, 'haproxy/0', {'ingress-address': '192.0.2.1'})

        self.harness.update_relation_data(relation_id, 'tcp-server', {
            'listener': json.dumps({
                'name': 'tcp-server',
                'port': 80,
            }, **JSON_ENCODE_OPTIONS),
            'health_monitor': json.dumps({
                'timeout': 10.0
            }, **JSON_ENCODE_OPTIONS),
        })
        self.assertEqual(len(self.tcp_backend_manager.pools), 0)

    def test_empty_pool_no_backend_data(self):
        relation_id = self.harness.add_relation('tcp-lb', 'tcp-server')
        self.harness.update_relation_data(
            relation_id, 'haproxy/0', {'ingress-address': '192.0.2.1'})

        self.harness.update_relation_data(relation_id, 'tcp-server', {
            'listener': json.dumps({
                'name': 'tcp-server',
                'port': 80,
                'balancing_algorithm': 'round_robin',
            }, **JSON_ENCODE_OPTIONS),
            'health_monitor': json.dumps({
                'timeout': 10.0
            }, **JSON_ENCODE_OPTIONS),
        })
        # Add a unit without backend data - this should not result in a presence
        # of a pool because there is no useful data for any units in it yet.
        self.harness.add_relation_unit(
            relation_id, 'tcp-server/0', {
                'ingress-address': '192.0.2.2',
            })
        self.assertEqual(len(self.tcp_backend_manager.pools), 0)


class TestLoadBalancer(unittest.TestCase):

    def setUp(self):
        self.harness = Harness(CharmBase, meta='''
            name: tcp-server
            requires:
              tcp-lb:
                interface: tcp-load-balancer
        ''')
        self.harness.begin()
        self.tcp_lb = TCPLoadBalancer(self.harness.charm, 'tcp-lb')

    def test_expose_backend(self):
        relation_id = self.harness.add_relation('tcp-lb', 'tcp-server')
        self.harness.update_relation_data(
            relation_id, 'tcp-server/0', {'ingress-address': '192.0.2.1'})

        listener = Listener('tcp-server', 80, 'round_robin')
        backend = Backend(name='tcp-server-0.example', port=80, address='192.0.2.1')
        health_monitor = HealthMonitor(timeout=datetime.timedelta(seconds=10))

        self.tcp_lb.expose_backend(backend, listener, health_monitor)

        rel = self.harness.charm.model.get_relation('tcp-lb')
        self.assertEqual(json.loads(rel.data[self.harness.charm.unit]['backend']),
                         {
                             'address': '192.0.2.1',
                             'monitor_port': None,
                             'name': 'tcp-server-0.example',
                             'port': 80,
                             'weight': None,
                             'data_timeout': None,
                         })
        with self.assertRaises(KeyError):
            rel.data[self.harness.charm.app]['listener']
        with self.assertRaises(KeyError):
            rel.data[self.harness.charm.app]['health_monitor'],

        self.harness.set_leader()
        self.tcp_lb.expose_backend(backend, listener, health_monitor)
        self.assertEqual(json.loads(rel.data[self.harness.charm.unit]['backend']),
                         {
                             'address': '192.0.2.1',
                             'monitor_port': None,
                             'name': 'tcp-server-0.example',
                             'port': 80,
                             'weight': None,
                             'data_timeout': None,
                         })
        self.assertEqual(json.loads(rel.data[self.harness.charm.app]['listener']),
                         {
                             'name': 'tcp-server',
                             'port': 80,
                             'balancing_algorithm': 'round_robin'
                         })
        self.assertEqual(json.loads(rel.data[self.harness.charm.app]['health_monitor']),
                         {
                             'delay': None,
                             'max_retries': None,
                             'max_retries_down': None,
                             'timeout': 10.0
                         })


if __name__ == "__main__":
    unittest.main()
