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

`TCPBackendManager`_ is the type that exposes the information about members that a TCP
load-balancer should provide load-balancing for::

    class MyLBCharm(ops.charm.CharmBase):

       def __init__(self, *args):
          super().__init__(*args)
          self.tcp_backend_manager = TCPBackendManagers(self, 'tcp-lb')
          self.framework.observe(self.tcp_backend_manager.on.pools_changed,
                                 self._on_tcp_pools_changed)

       def _on_tcp_pools_changed(self, event):
           for pool in self.tcp_backend_manager.pools:
               logger.debug(pool.listener.port)
               logger.debug(pool.listener.name)
               for member in pool.members:
                   logger.debug(member.port)
                   logger.debug(member.address)
                   # Access other fields...


`TCPLoadBalancer`_ is the type that exposes the information about members that a TCP
load-balancer should provide load-balancing for::

    class MyServiceCharm(ops.charm.CharmBase):

        LISTENER_PORT = 80
        SERVICE_PORT = 8080
        MONITOR_PORT = 8081

        def __init__(self, *args):
            super().__init__(*args)
            self.tcp_lb = TCPLoadBalancer(self, 'tcp-lb')
            self.framework.observe(self.tcp_lb.on.load_balancer_available,
                                   self._on_load_balancer_available)

        def _on_load_balancer_available(self, event):
            listener = Listener(
                name=self.app.name.replace('/', '_'),
                port=self.LISTENER_PORT,
                balancing_algorithm='round_robin',
            )
            fqdn = socket.getfqdn()
            backend = Backend(fqdn, self.SERVICE_PORT, monitor_port=self.MONITOR_PORT)
            health_monitor = HTTPHealthMonitor(
                timeout=timedelta(seconds=10),
                http_method='GET',
                url_path='/health?ready=1'
            )
            self.tcp_lb.expose_backend(listener, backend, health_monitor)
"""

import logging
import json
import datetime

from types import SimpleNamespace

from ops.framework import Object, StoredState, EventBase, EventSetBase, EventSource
logger = logging.getLogger(__name__)


JSON_ENCODE_OPTIONS = dict(
    sort_keys=True,
    allow_nan=False,
    indent=None,
    separators=(',', ':'),
)


class PoolsChanged(EventBase):
    """Event emitted by TCPBackendManagers.on.pools_changed.

    This event will be emitted if any of the existing or new members exposes new data over a
    relation for the load-balancer to re-assess its current state.
    """


class TCPBackendManagerEvents(EventSetBase):
    """Events emitted by the TCPBackendManager class."""

    pools_changed = EventSource(PoolsChanged)


class TCPBackendManager(Object):
    """Handles TCP backend events and exposes pools of TCP backends."""

    on = TCPBackendManagerEvents()

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
            self._backend_pools = self._compute_backend_pools()
        return self._backend_pools

    def _compute_backend_pools(self):
        pools = []
        for relation in self.model.relations[self._relation_name]:
            if not relation.units:
                continue
            app_data = relation.data[relation.app]

            listener_data = app_data.get('listener')
            if listener_data is None:
                logger.debug('No listener data found for remote app %s', relation.app.name)
                continue
            listener = Listener(**json.loads(listener_data))
            health_monitor_data = app_data.get('health_monitor')
            if health_monitor_data is None:
                logger.debug('No health monitor data found for remote app %s',
                             relation.app.name)
                continue
            health_monitor = HealthMonitor(**json.loads(health_monitor_data))

            members = []
            for unit in relation.units:
                backend_data = relation.data[unit].get('backend')
                if backend_data is None:
                    logger.debug('No backend data found for remote unit %s', unit.name)
                    continue
                backend = Backend(**json.loads(backend_data))
                members.append(backend)
            # Add a pool only if there are members in it.
            if members:
                pools.append(BackendPool(listener, members, health_monitor))
            else:
                logger.debug('No backend data for listener {} exposed yet by any backend unit -'
                             ' no pool will be added.'.format(listener.name))
        return pools


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


class TCPLoadBalancerEvents(EventSetBase):
    """Events emitted by the TCPLoadBalancer class."""

    load_balancer_available = EventSource(LoadBalancerAvailable)


class TCPLoadBalancer(Object):
    """Represents a TCP load-balancer that distributes traffic across backends exposed to it.

    Backends would use this type to expose themselves to a single TCP load-balancer.
    """

    on = TCPLoadBalancerEvents()
    _stored = StoredState()

    def __init__(self, charm, relation_name):
        super().__init__(charm, relation_name)
        self._relation_name = relation_name
        self.framework.observe(charm.on[relation_name].relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event):
        self.on.load_balancer_available.emit()

    def expose_backend(self, backend, listener, health_monitor):
        """Expose a backend to the load-balancer.

        :param backend: a backend to expose to a TCP load-balancer.
        :type backend: :class: `.Backend`
        :param listener: a listener to provide frontend and backend configuration parameters.
        :type listener: :class: `.Listener`
        :param health_monitor: a health monitor instance to configure health-checking
            for the backend.
        :type health_monitor: :class: `.HealthMonitor`
        """
        rel = self.model.get_relation(self._relation_name)
        our_unit_data = rel.data[self.model.unit]
        if backend.address is None:
            addr = self.model.get_binding(rel).network.ingress_address
            backend.address = addr

        our_unit_data['backend'] = json.dumps(backend, cls=InterfaceDataEncoder,
                                              **JSON_ENCODE_OPTIONS)
        if self.model.unit.is_leader():
            our_app_data = rel.data[self.model.app]
            our_app_data['listener'] = json.dumps(listener, cls=InterfaceDataEncoder,
                                                  **JSON_ENCODE_OPTIONS)
            # A monitor for a pool of members.
            our_app_data['health_monitor'] = json.dumps(health_monitor, cls=InterfaceDataEncoder,
                                                        **JSON_ENCODE_OPTIONS)


class Listener(SimpleNamespace):
    """Listeners specifies load-balancer frontend and backend configuration."""

    def __init__(self, name, port, balancing_algorithm, **kwargs):
        self.name = name
        self.port = port
        self.balancing_algorithm = balancing_algorithm


class Backend(SimpleNamespace):
    """Describes the details about a particular backend service instance."""

    def __init__(self, name, port, *, address=None, monitor_port=None, weight=None,
                 data_timeout=None, **kwargs):
        self.name = name
        self.port = port
        self.address = address
        self.monitor_port = monitor_port
        self.weight = weight
        self.data_timeout = data_timeout


class HealthMonitor(SimpleNamespace):
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


class HTTPHealthMonitor(HealthMonitor):
    """HTTP health monitors provide parameters to perform health-checks over HTTP."""

    def __init__(self, http_method=None, url_path=None, expected_codes=None, *kwargs):
        super().__init__(**kwargs)
        self.http_method = http_method
        self.url_path = url_path
        self.expected_codes = expected_codes


class InterfaceDataEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.timedelta):
            return obj.total_seconds()
        elif isinstance(obj, SimpleNamespace):
            return obj.__dict__
        else:
            return super().default(obj)
