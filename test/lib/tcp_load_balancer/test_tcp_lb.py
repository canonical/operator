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
import pickle
import datetime

from ops.charm import CharmBase
from ops.testing import Harness

from ops.lib.tcp_load_balancer.tcp_lb import (
    TcpMemberPools,
    Listener,
    Member,
    HealthMonitor,
    TcpLoadBalancer,
)


class TestTcpMemberPools(unittest.TestCase):

    def setUp(self):
        self.harness = Harness(CharmBase, meta='''
            name: haproxy
            provides:
              tcp-lb:
                interface: tcp-load-balancer
        ''')

        self.harness.begin()
        self.tcp_member_pools = TcpMemberPools(self.harness.charm, 'tcp-lb')

    def test_pools(self):
        relation_id = self.harness.add_relation('tcp-lb', 'tcp-server')
        self.harness.update_relation_data(
            relation_id, 'haproxy/0', {'ingress-address': '192.0.2.1'})

        self.harness.add_relation_unit(
            relation_id, 'tcp-server/0', {
                'ingress-address': '192.0.2.2',
                'member': pickle.dumps(Member(name='tcp-server-0.example', port=80,
                                              address='192.0.2.2'), 0).decode('utf-8')
            })
        self.harness.add_relation_unit(
            relation_id, 'tcp-server/1', {
                'ingress-address': '192.0.2.3',
                'member': pickle.dumps(Member(name='tcp-server-1.example', port=80,
                                              address='192.0.2.3'), 0).decode('utf-8')
            })
        self.harness.update_relation_data(relation_id, 'tcp-server', {
            'listener': pickle.dumps(Listener('tcp-server', 80), 0).decode('utf-8'),
            'health_monitor': pickle.dumps(
                HealthMonitor(timeout=datetime.timedelta(seconds=10)), 0).decode('utf-8')
        })

        pools = self.tcp_member_pools.pools
        test_pool = pools[0]
        self.assertEqual(test_pool.listener.port, 80)
        self.assertEqual(test_pool.listener.name, 'tcp-server')
        self.assertEqual(test_pool.health_monitor.timeout, datetime.timedelta(seconds=10))


class TestLoadBalancer(unittest.TestCase):

    def setUp(self):
        self.harness = Harness(CharmBase, meta='''
            name: tcp-server
            requires:
              tcp-lb:
                interface: tcp-load-balancer
        ''')

        self.harness.begin()
        self.tcp_lb = TcpLoadBalancer(self.harness.charm, 'tcp-lb', 'round_robin')

    def test_expose_member(self):
        relation_id = self.harness.add_relation('tcp-lb', 'tcp-server')
        self.harness.update_relation_data(
            relation_id, 'tcp-server/0', {'ingress-address': '192.0.2.1'})

        listener = Listener('tcp-server', 80)
        member = Member(name='tcp-server-0.example', port=80, address='192.0.2.1')
        health_monitor = HealthMonitor(timeout=datetime.timedelta(seconds=10))

        self.tcp_lb.expose_member(member, listener, health_monitor)

        rel = self.harness.charm.model.get_relation('tcp-lb')
        self.assertEqual(rel.data[self.harness.charm.unit]['member'],
                         pickle.dumps(member, 0).decode('utf-8'))
        with self.assertRaises(KeyError):
            rel.data[self.harness.charm.app]['listener']
        with self.assertRaises(KeyError):
            rel.data[self.harness.charm.app]['health_monitor'],

        self.harness.set_leader()
        self.tcp_lb.expose_member(member, listener, health_monitor)
        self.assertEqual(rel.data[self.harness.charm.unit]['member'],
                         pickle.dumps(member, 0).decode('utf-8'))
        self.assertEqual(rel.data[self.harness.charm.app]['listener'],
                         pickle.dumps(listener, 0).decode('utf-8'))
        self.assertEqual(rel.data[self.harness.charm.app]['health_monitor'],
                         pickle.dumps(health_monitor, 0).decode('utf-8'))
        self.assertEqual(rel.data[self.harness.charm.app]['lb_algorithm'], 'round_robin')


if __name__ == "__main__":
    unittest.main()
