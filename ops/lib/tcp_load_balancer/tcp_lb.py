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

"""Implements types for provides and requires sides of the 'tcp-load-balancer' relation.

`TcpBackendManager`_ is the type that exposes the information about members that a TCP
load-balancer should provide load-balancing for.

class MyLBCharm(ops.charm.CharmBase):

   def __init__(self, *args):
      super().__init__(*args)
      self.tcp_backend_manager = TcpBackendManagers(self, 'tcp-lb')
      self.framework.observe(self.tcp_backend_manager.on.pools_changed, self._on_tcp_pools_changed)

   def _on_tcp_pools_changed(self, event):
       for pool in self.tcp_backend_manager.pools:
           logger.debug(pool.listener.port)
           logger.debug(pool.listener.name)
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

        def __init__(self, *args):
            super().__init__(*args)
            self.tcp_lb = TcpLoadBalancer(self, 'tcp-lb', load_balancer_algorithm='round_robin')
            self.framework.observe(self.tcp_lb.on.load_balancer_available,
                                   self._on_load_balancer_available)

        def _on_load_balancer_available(self, event):
            listener = Listener(name=self.app.name.replace('/', '_'), port=self.LISTENER_PORT)
            fqdn = socket.getfqdn()
            backend = Backend(fqdn, self.MEMBER_PORT, monitor_port=self.MONITOR_PORT)
            health_monitor = HTTPHealthMonitor(timeout=timedelta(seconds=10), http_method='GET',
                                               url_path='/health?ready=1')
            self.tcp_lb.expose_backend(listener, backend, health_monitor)
            # ...
"""

import logging
import yaml
import datetime

from collections.abc import Mapping

from ops.framework import Object, StoredState, EventBase, EventSetBase, EventSource

logger = logging.getLogger(__name__)


class PoolsChanged(EventBase):
    """Event emitted by TcpBackendManagers.on.pools_changed.

    This event will be emitted if any of the existing or new members exposes new data over a
    relation for the load-balancer to re-assess its current state.
    """


class TcpBackendManagerEvents(EventSetBase):
    """Events emitted by the TcpBackendManager class."""

    pools_changed = EventSource(PoolsChanged)


class TcpBackendManager(Object):
    """Handles TCP backend events and exposes pools of TCP backends."""

    on = TcpBackendManagerEvents()

    _stored = StoredState()

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self._relation_name = relation_name
        self._backend_pools = None
        self.framework.observe(charm.on[relation_name].relation_changed, self._on_relation_changed)

    def _on_relation_changed(self, event):
        self.on.pools_changed.emit()

    @property
    def pools(self):
        if self._backend_pools is None:
            self._backend_pools = []
            for relation in self.model.relations[self._relation_name]:
                if not relation.units:
                    continue
                app_data = relation.data[relation.app]

                listener_data = app_data.get('listener')
                if listener_data is None:
                    logger.debug('No listener data found for remote app %s', relation.app.name)
                    continue
                listener = Listener(**yaml.safe_load(listener_data))
                health_monitor_data = app_data.get('health_monitor')
                if health_monitor_data is None:
                    logger.debug('No health monitor data found for remote app %s',
                                 relation.app.name)
                    continue
                health_monitor = HealthMonitor(**yaml.safe_load(health_monitor_data))

                members = []
                for unit in relation.units:
                    backend_data = relation.data[unit].get('backend')
                    if backend_data is None:
                        logger.debug('No backend data found for remote unit %s', unit.name)
                        continue
                    backend = Backend(**yaml.safe_load(backend_data))
                    members.append(backend)
                self._backend_pools.append(BackendPool(listener, members, health_monitor))
        return self._backend_pools


class BackendPool:
    """Represents a pool of TCP load-balancer backends."""

    def __init__(self, listener, members, health_monitor=None):
        self.members = members
        self.listener = listener
        self.health_monitor = health_monitor


class LoadBalancerAvailable(EventBase):
    """Event emitted when a load-balancer is available.

    This event will be emitted when a new load-balancer instance appears on a relation for a member
    to expose its data. If a load-balancer is highly-available, there will be multiple of those
    events fired as instances of the load-balancer are observed by the member.
    """


class TcpLoadBalancerEvents(EventSetBase):
    """Events emitted by the TcpLoadBalancer class."""

    load_balancer_available = EventSource(LoadBalancerAvailable)


class TcpLoadBalancer(Object):
    """Represents a TCP load-balancer that distributes traffic across backends exposed to it.

    Backends would use this type to expose themselves to a single TCP load-balancer.
    """

    on = TcpLoadBalancerEvents()
    _stored = StoredState()

    def __init__(self, charm, relation_name, load_balancer_algorithm=None):
        super().__init__(charm, relation_name)
        self._relation_name = relation_name
        self._load_balancer_algorithm = load_balancer_algorithm

        self.framework.observe(charm.on[relation_name].relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event):
        self.on.load_balancer_available.emit()

    def expose_backend(self, backend, listener, health_monitor):
        """Expose a backend to the load-balancer.

        backend -- a backend to expose to a TCP load-balancer.
        listener -- a listener instance to provide frontend configuration parameters.
        health_monitor -- a health monitor instance to configure health-checking for the backend.
        """
        rel = self.model.get_relation(self._relation_name)
        our_unit_data = rel.data[self.model.unit]
        if backend.address is None:
            addr = self.model.get_binding(rel).network.ingress_address
            backend.address = addr

        our_unit_data['backend'] = yaml.dump(backend, Dumper=InterfaceDataDumper)
        if self.model.unit.is_leader():
            our_app_data = rel.data[self.model.app]
            our_app_data['listener'] = yaml.dump(listener, Dumper=InterfaceDataDumper)
            # A monitor for a pool of members.
            our_app_data['health_monitor'] = yaml.dump(health_monitor, Dumper=InterfaceDataDumper)
            our_app_data['load_balancer_algorithm'] = self._load_balancer_algorithm


class InterfaceDataType(dict):

    def __getattr__(self, name):
        if name in self:
            return self[name]
        else:
            raise AttributeError("No such attribute: {}".format(name))

    def __setattr__(self, name, value):
        self[name] = value

    def __delattr__(self, name):
        if name in self:
            del self[name]
        else:
            raise AttributeError("No such attribute: {}".format(name))


class Listener(InterfaceDataType):
    """Listeners determine how load-balancer front-ends are configured."""

    def __init__(self, name, port, **kwargs):
        self.name = name
        self.port = port


class Backend(InterfaceDataType):
    """Describes the details about a particular backend service instance."""

    def __init__(self, name, port, *, address=None, monitor_port=None, weight=None,
                 data_timeout=None, **kwargs):
        self.name = name
        self.port = port
        self.address = address
        self.monitor_port = monitor_port
        self.weight = weight
        self.data_timeout = data_timeout


class HealthMonitor(InterfaceDataType):
    """Health-monitors provide parameters for regular health-checking operations."""

    def __init__(self, *, delay=None, timeout=None, max_retries=None, max_retries_down=None,
                 **kwargs):
        if isinstance(delay, float):
            self.delay = datetime.timedelta(seconds=delay)
        elif isinstance(delay, (datetime.timedelta, type(None))):
            self.delay = delay
        else:
            raise RuntimeError('Invalid type provided for the delay attribute: {}'
                               ''.format(type(delay).__name__))
        if isinstance(timeout, float):
            self.timeout = datetime.timedelta(seconds=timeout)
        elif isinstance(timeout, (datetime.timedelta, type(None))):
            self.timeout = timeout
        else:
            raise RuntimeError('Invalid type provided for the delay attribute: {}'
                               ''.format(type(delay).__name__))
        self.max_retries = max_retries
        self.max_retries_down = max_retries_down


class HttpHealthMonitor(HealthMonitor):
    """HTTP health monitors provide parameters to perform health-checks over HTTP."""

    def __init__(self, http_method=None, url_path=None, expected_codes=None, *kwargs):
        super().__init__(**kwargs)
        self.http_method = http_method
        self.url_path = url_path
        self.expected_codes = expected_codes


class InterfaceDataDumper(yaml.SafeDumper):

    def represent_data(self, data):
        if isinstance(data, Mapping):
            return self.represent_dict(data.items())
        if isinstance(data, datetime.timedelta):
            return self.represent_float(data.total_seconds())
        return super().represent_data(data)
