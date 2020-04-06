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

import pickle

from ops.framework import Object, StoredState, EventBase, EventSetBase, EventSource


'''Implements types for provides and requires sides of the 'tcp-load-balancer' relation.

`TcpMemberPools`_ is the type that exposes the information about members that a TCP
load-balancer should provide load-balancing for.


     class MyLBCharm(ops.charm.CharmBase):

        def __init__(self, framework):
           super().__init__(framework, None)
           self.tcp_member_pools = TcpMemberPools(self, 'tcp-lb')
           self.framework.observe(self.member_pools.on.pools_changed, self._on_tcp_pools_changed)
        ...
        def _on_tcp_pools_changed(self, event):
            pools = self.tcp_member_pools.pools
            for pool in self.tcp_member_pools.pools:
                logger.debug(pools.listener.port)
                logger.debug(pools.listener.name)
                for member in pool.members:
                    logger.debug(member.port)
                    logger.debug(member.address)
                    # other fields...


`TcpLoadBalancer`_ is the type that exposes the information about members that a TCP
load-balancer should provide load-balancing for.

    class MyServiceCharm(ops.charm.CharmBase):

        LISTENER_PORT = 80
        SERVICE_PORT = 8080
        MONITOR_PORT = 8081

        def __init__(self, framework):
            super().__init__(framework, None)
            self.tcp_lb = TcpLoadBalancer(self, 'tcp-lb', lb_algorithm='round_robin')
            self.framework.observe(self.tcp_lb.on.lb_available, self._on_lb_available)

        def _on_lb_available(self, event):
            listener = Listener(name=self.app.name.replace('/', '_'), port=self.LISTENER_PORT)
            fqdn = socket.getfqdn()
            member = Member(fqdn, self.MEMBER_PORT, monitor_port=self.MONITOR_PORT)
            health_monitor = HTTPHealthMonitor(timeout=timedelta(seconds=10), http_method='GET',
                                               url_path='/health?ready=1')
            self.tcp_lb.expose_member(listener, member, health_monitor)
            # ...
'''


class PoolsChanged(EventBase):

    '''Event emitted by TcpMemberPools.on.pools_changed.

    This event will be emitted if any of the existing or new members exposes new data over a
    relation for the load-balancer to re-assess its current state.
    '''
    pass


class TcpMemberPoolEvents(EventSetBase):

    '''Events emitted by the TcpMemberPoolEvents class.'''
    pools_changed = EventSource(PoolsChanged)


class TcpMemberPools(Object):

    '''Provides the information about pools of TCP load-balancer members.'''

    on = TcpMemberPoolEvents()

    _stored = StoredState()

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self._relation_name = relation_name
        self._member_pools = None
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_relation_changed)

    def _on_relation_changed(self, event):
        self.on.pools_changed.emit()

    @property
    def pools(self):
        if self._member_pools is None:
            self._member_pools = []
            for relation in self.model.relations[self._relation_name]:
                if not relation.units:
                    continue
                app_data = relation.data[relation.app]

                listener_data = app_data.get('listener')
                if listener_data is None:
                    continue
                listener = pickle.loads(listener_data.encode('utf-8'))
                health_monitor_data = app_data.get('health_monitor')
                if health_monitor_data is None:
                    continue
                health_monitor = pickle.loads(health_monitor_data.encode('utf-8'))

                members = []
                for unit in relation.units:
                    member_data = relation.data[unit].get('member')
                    if member_data is None:
                        continue
                    members.append(pickle.loads(member_data.encode('utf-8')))
                self._member_pools.append(MemberPool(listener, members, health_monitor))
        return self._member_pools


class MemberPool:

    '''A class that aggregates the information about a pool of load-balancer members'''

    def __init__(self, listener, members, health_monitor=None):
        self.members = members
        self.listener = listener
        self.health_monitor = health_monitor


class LBAvailable(EventBase):

    '''Event emitted by TcpLoadBalancer.on.lb_available.

    This event will be emitted when a new load-balancer instance appears on a relation for a member
    to expose its data. If a load-balancer is highly-available, there will be multiple of those
    events fired as instances of the load-balancer are observed by the member.
    '''
    pass


class TcpLoadBalancerEvents(EventSetBase):

    '''Events emitted by the TcpLoadBalancer class.'''
    lb_available = EventSource(LBAvailable)


class TcpLoadBalancer(Object):

    on = TcpLoadBalancerEvents()
    _stored = StoredState()

    def __init__(self, charm, relation_name, lb_algorithm=None):
        super().__init__(charm, relation_name)
        self._relation_name = relation_name
        self._lb_algorithm = lb_algorithm

        self.framework.observe(charm.on[relation_name].relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event):
        self.on.lb_available.emit()

    @property
    def _relation(self):
        # TODO: there could be multiple independent reverse proxies in theory, address that later.
        return self.model.get_relation(self._relation_name)

    def expose_member(self, member, listener, health_monitor):
        our_unit_data = self._relation.data[self.model.unit]
        if member.address is None:
            addr = self.model.get_binding(self._relation).network.ingress_address
            member.set_address(addr)

        our_unit_data['member'] = pickle.dumps(member, 0).decode('utf-8')
        if self.model.unit.is_leader():
            our_app_data = self._relation.data[self.model.app]
            our_app_data['listener'] = pickle.dumps(listener, 0).decode('utf-8')
            # A monitor for a pool of members.
            our_app_data['health_monitor'] = pickle.dumps(health_monitor, 0).decode('utf-8')
            our_app_data['lb_algorithm'] = self._lb_algorithm


class Listener:

    '''Listeners determine how load-balancer front-ends are configured.
    '''

    def __init__(self, name, port):
        self.name = name
        self.port = port


class Member:

    '''Members describe the details about a particular backend service instance.
    '''

    def __init__(self, name, port, *, address=None, monitor_port=None, weight=None,
                 data_timeout=None):
        self.name = name
        self.port = port
        self.address = address
        self.monitor_port = monitor_port
        self.weight = weight
        self.data_timeout = data_timeout

    def set_address(self, address):
        self.address = address


class HealthMonitor:

    '''Health-monitors provide parameters for regular health-checking operations.
    '''

    def __init__(self, *, delay=None, timeout=None, max_retries=None, max_retries_down=None):
        self.delay = delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_retries_down = max_retries_down


class HTTPHealthMonitor(HealthMonitor):

    '''HTTP health monitors provide parameters to perform health-checks over HTTP.
    '''

    def __init__(self, http_method=None, url_path=None, expected_codes=None, *args):
        super().__init__(*args)
        self.http_method = http_method
        self.url_path = url_path
        self.expected_codes = expected_codes
