# Copyright 2019-2021 Canonical Ltd.
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

"""Representations of Juju's model, application, unit, and other entities."""

import datetime
import ipaddress
import json
import logging
import math
import os
import re
import shutil
import tempfile
import time
import typing
import weakref
from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from subprocess import PIPE, CalledProcessError, run

import ops
import ops.pebble as pebble
from ops._private import yaml
from ops.jujuversion import JujuVersion

logger = logging.getLogger(__name__)

MAX_LOG_LINE_LEN = 131071  # Max length of strings to pass to subshell.


class Model:
    """Represents the Juju Model as seen from this unit.

    This should not be instantiated directly by Charmers, but can be accessed as `self.model`
    from any class that derives from Object.
    """

    def __init__(self, meta: 'ops.charm.CharmMeta', backend: '_ModelBackend'):
        self._cache = _ModelCache(meta, backend)
        self._backend = backend
        self._unit = self.get_unit(self._backend.unit_name)
        self._relations = RelationMapping(meta.relations, self.unit, self._backend, self._cache)
        self._config = ConfigData(self._backend)
        self._resources = Resources(list(meta.resources), self._backend)
        self._pod = Pod(self._backend)
        self._storages = StorageMapping(list(meta.storages), self._backend)
        self._bindings = BindingMapping(self._backend)

    @property
    def unit(self) -> 'Unit':
        """A :class:`Unit` that represents the unit that is running this code (eg yourself)."""
        return self._unit

    @property
    def app(self):
        """A :class:`Application` that represents the application this unit is a part of."""
        return self._unit.app

    @property
    def relations(self) -> 'RelationMapping':
        """Mapping of endpoint to list of :class:`Relation`.

        Answers the question "what am I currently related to".
        See also :meth:`.get_relation`.
        """
        return self._relations

    @property
    def config(self) -> 'ConfigData':
        """Return a mapping of config for the current application."""
        return self._config

    @property
    def resources(self) -> 'Resources':
        """Access to resources for this charm.

        Use ``model.resources.fetch(resource_name)`` to get the path on disk
        where the resource can be found.
        """
        return self._resources

    @property
    def storages(self) -> 'StorageMapping':
        """Mapping of storage_name to :class:`Storage` as defined in metadata.yaml."""
        return self._storages

    @property
    def pod(self) -> 'Pod':
        """Use ``model.pod.set_spec`` to set the container specification for Kubernetes charms."""
        return self._pod

    @property
    def name(self) -> str:
        """Return the name of the Model that this unit is running in.

        This is read from the environment variable ``JUJU_MODEL_NAME``.
        """
        return self._backend.model_name

    @property
    def uuid(self) -> str:
        """Return the identifier of the Model that this unit is running in.

        This is read from the environment variable ``JUJU_MODEL_UUID``.
        """
        return self._backend.model_uuid

    def get_unit(self, unit_name: str) -> 'Unit':
        """Get an arbitrary unit by name.

        Internally this uses a cache, so asking for the same unit two times will
        return the same object.
        """
        return self._cache.get(Unit, unit_name)

    def get_app(self, app_name: str) -> 'Application':
        """Get an application by name.

        Internally this uses a cache, so asking for the same application two times will
        return the same object.
        """
        return self._cache.get(Application, app_name)

    def get_relation(
            self, relation_name: str,
            relation_id: typing.Optional[int] = None) -> 'Relation':
        """Get a specific Relation instance.

        If relation_id is not given, this will return the Relation instance if the
        relation is established only once or None if it is not established. If this
        same relation is established multiple times the error TooManyRelatedAppsError is raised.

        Args:
            relation_name: The name of the endpoint for this charm
            relation_id: An identifier for a specific relation. Used to disambiguate when a
                given application has more than one relation on a given endpoint.

        Raises:
            TooManyRelatedAppsError: is raised if there is more than one relation to the
                supplied relation_name and no relation_id was supplied
        """
        return self.relations._get_unique(relation_name, relation_id)

    def get_binding(self, binding_key: typing.Union[str, 'Relation']) -> 'Binding':
        """Get a network space binding.

        Args:
            binding_key: The relation name or instance to obtain bindings for.

        Returns:
            If ``binding_key`` is a relation name, the method returns the default binding
            for that relation. If a relation instance is provided, the method first looks
            up a more specific binding for that specific relation ID, and if none is found
            falls back to the default binding for the relation name.
        """
        return self._bindings.get(binding_key)


class _ModelCache:

    def __init__(self, meta, backend):
        self._meta = meta
        self._backend = backend
        self._weakrefs = weakref.WeakValueDictionary()

    def get(self, entity_type, *args):
        key = (entity_type,) + args
        entity = self._weakrefs.get(key)
        if entity is None:
            entity = entity_type(*args, meta=self._meta, backend=self._backend, cache=self)
            self._weakrefs[key] = entity
        return entity


class Application:
    """Represents a named application in the model.

    This might be your application, or might be an application that you are related to.
    Charmers should not instantiate Application objects directly, but should use
    :meth:`Model.get_app` if they need a reference to a given application.

    Attributes:
        name: The name of this application (eg, 'mysql'). This name may differ from the name of
            the charm, if the user has deployed it to a different name.
    """

    def __init__(self, name, meta, backend, cache):
        self.name = name
        self._backend = backend
        self._cache = cache
        self._is_our_app = self.name == self._backend.app_name
        self._status = None

    def _invalidate(self):
        self._status = None

    @property
    def status(self) -> 'StatusBase':
        """Used to report or read the status of the overall application.

        Can only be read and set by the lead unit of the application.

        The status of remote units is always Unknown.

        Raises:
            RuntimeError: if you try to set the status of another application, or if you try to
                set the status of this application as a unit that is not the leader.
            InvalidStatusError: if you try to set the status to something that is not a
                :class:`StatusBase`

        Example::

            self.model.app.status = BlockedStatus('I need a human to come help me')
        """
        if not self._is_our_app:
            return UnknownStatus()

        if not self._backend.is_leader():
            raise RuntimeError('cannot get application status as a non-leader unit')

        if self._status:
            return self._status

        s = self._backend.status_get(is_app=True)
        self._status = StatusBase.from_name(s['status'], s['message'])
        return self._status

    @status.setter
    def status(self, value: 'StatusBase'):
        if not isinstance(value, StatusBase):
            raise InvalidStatusError(
                'invalid value provided for application {} status: {}'.format(self, value)
            )

        if not self._is_our_app:
            raise RuntimeError('cannot to set status for a remote application {}'.format(self))

        if not self._backend.is_leader():
            raise RuntimeError('cannot set application status as a non-leader unit')

        self._backend.status_set(value.name, value.message, is_app=True)
        self._status = value

    def planned_units(self) -> int:
        """Get the number of units that Juju has "planned" for this application.

        E.g., if an operator runs "juju deploy foo", then "juju add-unit -n 2 foo", the
        planned unit count for foo will be 3.

        The data comes from the Juju agent, based on data it fetches from the
        controller. Pending units are included in the count, and scale down events may
        modify the count before some units have been fully torn down. The information in
        planned_units is up-to-date as of the start of the current hook invocation.

        This method only returns data for this charm's application -- the Juju agent isn't
        able to see planned unit counts for other applications in the model.

        """
        if not self._is_our_app:
            raise RuntimeError(
                'cannot get planned units for a remote application {}.'.format(self))

        return self._backend.planned_units()

    def __repr__(self):
        return '<{}.{} {}>'.format(type(self).__module__, type(self).__name__, self.name)


class Unit:
    """Represents a named unit in the model.

    This might be your unit, another unit of your application, or a unit of another application
    that you are related to.

    Attributes:
        name: The name of the unit (eg, 'mysql/0')
        app: The Application the unit is a part of.
    """

    def __init__(self, name, meta, backend, cache):
        self.name = name

        app_name = name.split('/')[0]
        self.app = cache.get(Application, app_name)

        self._backend = backend
        self._cache = cache
        self._is_our_unit = self.name == self._backend.unit_name
        self._status = None

        if self._is_our_unit and hasattr(meta, "containers"):
            self._containers = ContainerMapping(meta.containers, backend)

    def _invalidate(self):
        self._status = None

    @property
    def status(self) -> 'StatusBase':
        """Used to report or read the status of a specific unit.

        The status of any unit other than yourself is always Unknown.

        Raises:
            RuntimeError: if you try to set the status of a unit other than yourself.
            InvalidStatusError: if you try to set the status to something other than
                a :class:`StatusBase`
        Example::

            self.model.unit.status = MaintenanceStatus('reconfiguring the frobnicators')
        """
        if not self._is_our_unit:
            return UnknownStatus()

        if self._status:
            return self._status

        s = self._backend.status_get(is_app=False)
        self._status = StatusBase.from_name(s['status'], s['message'])
        return self._status

    @status.setter
    def status(self, value: 'StatusBase'):
        if not isinstance(value, StatusBase):
            raise InvalidStatusError(
                'invalid value provided for unit {} status: {}'.format(self, value)
            )

        if not self._is_our_unit:
            raise RuntimeError('cannot set status for a remote unit {}'.format(self))

        self._backend.status_set(value.name, value.message, is_app=False)
        self._status = value

    def __repr__(self):
        return '<{}.{} {}>'.format(type(self).__module__, type(self).__name__, self.name)

    def is_leader(self) -> bool:
        """Return whether this unit is the leader of its application.

        This can only be called for your own unit.

        Returns:
            True if you are the leader, False otherwise
        Raises:
            RuntimeError: if called for a unit that is not yourself
        """
        if self._is_our_unit:
            # This value is not cached as it is not guaranteed to persist for the whole duration
            # of a hook execution.
            return self._backend.is_leader()
        else:
            raise RuntimeError(
                'leadership status of remote units ({}) is not visible to other'
                ' applications'.format(self)
            )

    def set_workload_version(self, version: str) -> None:
        """Record the version of the software running as the workload.

        This shouldn't be confused with the revision of the charm. This is informative only;
        shown in the output of 'juju status'.
        """
        if not isinstance(version, str):
            raise TypeError("workload version must be a str, not {}: {!r}".format(
                type(version).__name__, version))
        self._backend.application_version_set(version)

    @property
    def containers(self) -> 'ContainerMapping':
        """Return a mapping of containers indexed by name."""
        if not self._is_our_unit:
            raise RuntimeError('cannot get container for a remote unit {}'.format(self))
        return self._containers

    def get_container(self, container_name: str) -> 'Container':
        """Get a single container by name.

        Raises:
            ModelError: if the named container doesn't exist
        """
        try:
            return self.containers[container_name]
        except KeyError:
            raise ModelError('container {!r} not found'.format(container_name))


class LazyMapping(Mapping, ABC):
    """Represents a dict that isn't populated until it is accessed.

    Charm authors should generally never need to use this directly, but it forms
    the basis for many of the dicts that the framework tracks.
    """

    _lazy_data = None

    @abstractmethod
    def _load(self):
        raise NotImplementedError()

    @property
    def _data(self):
        data = self._lazy_data
        if data is None:
            data = self._lazy_data = self._load()
        return data

    def _invalidate(self):
        self._lazy_data = None

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key):
        return self._data[key]

    def __repr__(self):
        return repr(self._data)


class RelationMapping(Mapping):
    """Map of relation names to lists of :class:`Relation` instances."""

    def __init__(self, relations_meta, our_unit, backend, cache):
        self._peers = set()
        for name, relation_meta in relations_meta.items():
            if relation_meta.role.is_peer():
                self._peers.add(name)
        self._our_unit = our_unit
        self._backend = backend
        self._cache = cache
        self._data = {relation_name: None for relation_name in relations_meta}

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, relation_name):
        is_peer = relation_name in self._peers
        relation_list = self._data[relation_name]
        if relation_list is None:
            relation_list = self._data[relation_name] = []
            for rid in self._backend.relation_ids(relation_name):
                relation = Relation(relation_name, rid, is_peer,
                                    self._our_unit, self._backend, self._cache)
                relation_list.append(relation)
        return relation_list

    def _invalidate(self, relation_name):
        """Used to wipe the cache of a given relation_name.

        Not meant to be used by Charm authors. The content of relation data is
        static for the lifetime of a hook, so it is safe to cache in memory once
        accessed.
        """
        self._data[relation_name] = None

    def _get_unique(self, relation_name, relation_id=None):
        if relation_id is not None:
            if not isinstance(relation_id, int):
                raise ModelError('relation id {} must be int or None not {}'.format(
                    relation_id,
                    type(relation_id).__name__))
            for relation in self[relation_name]:
                if relation.id == relation_id:
                    return relation
            else:
                # The relation may be dead, but it is not forgotten.
                is_peer = relation_name in self._peers
                return Relation(relation_name, relation_id, is_peer,
                                self._our_unit, self._backend, self._cache)
        num_related = len(self[relation_name])
        if num_related == 0:
            return None
        elif num_related == 1:
            return self[relation_name][0]
        else:
            # TODO: We need something in the framework to catch and gracefully handle
            # errors, ideally integrating the error catching with Juju's mechanisms.
            raise TooManyRelatedAppsError(relation_name, num_related, 1)


class BindingMapping:
    """Mapping of endpoints to network bindings.

    Charm authors should not instantiate this directly, but access it via
    :meth:`Model.get_binding`
    """

    def __init__(self, backend):
        self._backend = backend
        self._data = {}

    def get(self, binding_key: typing.Union[str, 'Relation']) -> 'Binding':
        """Get a specific Binding for an endpoint/relation.

        Not used directly by Charm authors. See :meth:`Model.get_binding`
        """
        if isinstance(binding_key, Relation):
            binding_name = binding_key.name
            relation_id = binding_key.id
        elif isinstance(binding_key, str):
            binding_name = binding_key
            relation_id = None
        else:
            raise ModelError('binding key must be str or relation instance, not {}'
                             ''.format(type(binding_key).__name__))
        binding = self._data.get(binding_key)
        if binding is None:
            binding = Binding(binding_name, relation_id, self._backend)
            self._data[binding_key] = binding
        return binding


class Binding:
    """Binding to a network space.

    Attributes:
        name: The name of the endpoint this binding represents (eg, 'db')
    """

    def __init__(self, name, relation_id, backend):
        self.name = name
        self._relation_id = relation_id
        self._backend = backend
        self._network = None

    @property
    def network(self) -> 'Network':
        """The network information for this binding."""
        if self._network is None:
            try:
                self._network = Network(self._backend.network_get(self.name, self._relation_id))
            except RelationNotFoundError:
                if self._relation_id is None:
                    raise
                # If a relation is dead, we can still get network info associated with an
                # endpoint itself
                self._network = Network(self._backend.network_get(self.name))
        return self._network


class Network:
    """Network space details.

    Charm authors should not instantiate this directly, but should get access to the Network
    definition from :meth:`Model.get_binding` and its ``network`` attribute.

    Attributes:
        interfaces: A list of :class:`NetworkInterface` details. This includes the
            information about how your application should be configured (eg, what
            IP addresses should you bind to.)
            Note that multiple addresses for a single interface are represented as multiple
            interfaces. (eg, ``[NetworkInfo('ens1', '10.1.1.1/32'),
            NetworkInfo('ens1', '10.1.2.1/32'])``)
        ingress_addresses: A list of :class:`ipaddress.ip_address` objects representing the IP
            addresses that other units should use to get in touch with you.
        egress_subnets: A list of :class:`ipaddress.ip_network` representing the subnets that
            other units will see you connecting from. Due to things like NAT it isn't always
            possible to narrow it down to a single address, but when it is clear, the CIDRs
            will be constrained to a single address. (eg, 10.0.0.1/32)
    Args:
        network_info: A dict of network information as returned by ``network-get``.
    """

    def __init__(self, network_info: dict):
        self.interfaces = []
        # Treat multiple addresses on an interface as multiple logical
        # interfaces with the same name.
        for interface_info in network_info.get('bind-addresses', []):
            interface_name = interface_info.get('interface-name')
            addrs = interface_info.get('addresses')
            if addrs is not None:
                for address_info in addrs:
                    self.interfaces.append(NetworkInterface(interface_name, address_info))
        self.ingress_addresses = []
        for address in network_info.get('ingress-addresses', []):
            self.ingress_addresses.append(ipaddress.ip_address(address))
        self.egress_subnets = []
        for subnet in network_info.get('egress-subnets', []):
            self.egress_subnets.append(ipaddress.ip_network(subnet))

    @property
    def bind_address(self):
        """A single address that your application should bind() to.

        For the common case where there is a single answer. This represents a single
        address from :attr:`.interfaces` that can be used to configure where your
        application should bind() and listen().
        """
        if self.interfaces:
            return self.interfaces[0].address
        else:
            return None

    @property
    def ingress_address(self):
        """The address other applications should use to connect to your unit.

        Due to things like public/private addresses, NAT and tunneling, the address you bind()
        to is not always the address other people can use to connect() to you.
        This is just the first address from :attr:`.ingress_addresses`.
        """
        if self.ingress_addresses:
            return self.ingress_addresses[0]
        else:
            return None


class NetworkInterface:
    """Represents a single network interface that the charm needs to know about.

    Charmers should not instantiate this type directly. Instead use :meth:`Model.get_binding`
    to get the network information for a given endpoint.

    Attributes:
        name: The name of the interface (eg. 'eth0', or 'ens1')
        subnet: An :class:`ipaddress.ip_network` representation of the IP for the network
            interface. This may be a single address (eg '10.0.1.2/32')
    """

    def __init__(self, name: str, address_info: dict):
        self.name = name
        # TODO: expose a hardware address here, see LP: #1864070.
        address = address_info.get('value')
        # The value field may be empty.
        if address:
            self.address = ipaddress.ip_address(address)
        else:
            self.address = None
        cidr = address_info.get('cidr')
        # The cidr field may be empty, see LP: #1864102.
        if cidr:
            self.subnet = ipaddress.ip_network(cidr)
        elif address:
            # If we have an address, convert it to a /32 or /128 IP network.
            self.subnet = ipaddress.ip_network(address)
        else:
            self.subnet = None
        # TODO: expose a hostname/canonical name for the address here, see LP: #1864086.


class Relation:
    """Represents an established relation between this application and another application.

    This class should not be instantiated directly, instead use :meth:`Model.get_relation`
    or :attr:`ops.charm.RelationEvent.relation`. This is principally used by
    :class:`ops.charm.RelationMeta` to represent the relationships between charms.

    Attributes:
        name: The name of the local endpoint of the relation (eg 'db')
        id: The identifier for a particular relation (integer)
        app: An :class:`Application` representing the remote application of this relation.
            For peer relations this will be the local application.
        units: A set of :class:`Unit` for units that have started and joined this relation.
        data: A :class:`RelationData` holding the data buckets for each entity
            of a relation. Accessed via eg Relation.data[unit]['foo']
    """

    def __init__(
            self, relation_name: str, relation_id: int, is_peer: bool, our_unit: Unit,
            backend: '_ModelBackend', cache: '_ModelCache'):
        self.name = relation_name
        self.id = relation_id
        self.app = None
        self.units = set()

        if is_peer:
            # For peer relations, both the remote and the local app are the same.
            self.app = our_unit.app

        try:
            for unit_name in backend.relation_list(self.id):
                unit = cache.get(Unit, unit_name)
                self.units.add(unit)
                if self.app is None:
                    # Use the app of one of the units if available.
                    self.app = unit.app
        except RelationNotFoundError:
            # If the relation is dead, just treat it as if it has no remote units.
            pass

        # If we didn't get the remote app via our_unit.app or the units list,
        # look it up via JUJU_REMOTE_APP or "relation-list --app".
        if self.app is None:
            app_name = backend.relation_remote_app_name(relation_id)
            if app_name is not None:
                self.app = cache.get(Application, app_name)

        self.data = RelationData(self, our_unit, backend)

    def __repr__(self):
        return '<{}.{} {}:{}>'.format(type(self).__module__,
                                      type(self).__name__,
                                      self.name,
                                      self.id)


class RelationData(Mapping):
    """Represents the various data buckets of a given relation.

    Each unit and application involved in a relation has their own data bucket.
    Eg: ``{entity: RelationDataContent}``
    where entity can be either a :class:`Unit` or a :class:`Application`.

    Units can read and write their own data, and if they are the leader,
    they can read and write their application data. They are allowed to read
    remote unit and application data.

    This class should not be created directly. It should be accessed via
    :attr:`Relation.data`
    """

    def __init__(self, relation: Relation, our_unit: Unit, backend: '_ModelBackend'):
        self.relation = weakref.proxy(relation)
        self._data = {
            our_unit: RelationDataContent(self.relation, our_unit, backend),
            our_unit.app: RelationDataContent(self.relation, our_unit.app, backend),
        }
        self._data.update({
            unit: RelationDataContent(self.relation, unit, backend)
            for unit in self.relation.units})
        # The relation might be dead so avoid a None key here.
        if self.relation.app is not None:
            self._data.update({
                self.relation.app: RelationDataContent(self.relation, self.relation.app, backend),
            })

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key):
        return self._data[key]

    def __repr__(self):
        return repr(self._data)


# We mix in MutableMapping here to get some convenience implementations, but whether it's actually
# mutable or not is controlled by the flag.
class RelationDataContent(LazyMapping, MutableMapping):
    """Data content of a unit or application in a relation."""

    def __init__(self, relation, entity, backend):
        self.relation = relation
        self._entity = entity
        self._backend = backend
        self._is_app = isinstance(entity, Application)

    def _load(self):
        """Load the data from the current entity / relation."""
        try:
            return self._backend.relation_get(self.relation.id, self._entity.name, self._is_app)
        except RelationNotFoundError:
            # Dead relations tell no tales (and have no data).
            return {}

    def _is_mutable(self):
        """Return if the data content can be modified."""
        if self._is_app:
            is_our_app = self._backend.app_name == self._entity.name
            if not is_our_app:
                return False
            # Whether the application data bag is mutable or not depends on
            # whether this unit is a leader or not, but this is not guaranteed
            # to be always true during the same hook execution.
            return self._backend.is_leader()
        else:
            is_our_unit = self._backend.unit_name == self._entity.name
            if is_our_unit:
                return True
        return False

    def __setitem__(self, key, value):
        if not self._is_mutable():
            raise RelationDataError('cannot set relation data for {}'.format(self._entity.name))
        if not isinstance(value, str):
            raise RelationDataError('relation data values must be strings')

        self._backend.relation_set(self.relation.id, key, value, self._is_app)

        # Don't load data unnecessarily if we're only updating.
        if self._lazy_data is not None:
            if value == '':
                # Match the behavior of Juju, which is that setting the value to an
                # empty string will remove the key entirely from the relation data.
                self._data.pop(key, None)
            else:
                self._data[key] = value

    def __delitem__(self, key):
        # Match the behavior of Juju, which is that setting the value to an empty
        # string will remove the key entirely from the relation data.
        self.__setitem__(key, '')


class ConfigData(LazyMapping):
    """Configuration data.

    This class should not be created directly. It should be accessed via :attr:`Model.config`.
    """

    def __init__(self, backend):
        self._backend = backend

    def _load(self):
        return self._backend.config_get()


class StatusBase:
    """Status values specific to applications and units.

    To access a status by name, see :meth:`StatusBase.from_name`, most use cases will just
    directly use the child class to indicate their status.
    """

    _statuses = {}
    name = None

    def __init__(self, message: str):
        self.message = message

    def __new__(cls, *args, **kwargs):
        """Forbid the usage of StatusBase directly."""
        if cls is StatusBase:
            raise TypeError("cannot instantiate a base class")
        return super().__new__(cls)

    def __eq__(self, other):
        if not isinstance(self, type(other)):
            return False
        return self.message == other.message

    def __repr__(self):
        return "{.__class__.__name__}({!r})".format(self, self.message)

    @classmethod
    def from_name(cls, name: str, message: str):
        """Get the specific Status for the name (or UnknownStatus if not registered)."""
        if name == 'unknown':
            # unknown is special
            return UnknownStatus()
        else:
            return cls._statuses[name](message)

    @classmethod
    def register(cls, child):
        """Register a Status for the child's name."""
        if child.name is None:
            raise AttributeError('cannot register a Status which has no name')
        cls._statuses[child.name] = child
        return child


@StatusBase.register
class UnknownStatus(StatusBase):
    """The unit status is unknown.

    A unit-agent has finished calling install, config-changed and start, but the
    charm has not called status-set yet.

    """
    name = 'unknown'

    def __init__(self):
        # Unknown status cannot be set and does not have a message associated with it.
        super().__init__('')

    def __repr__(self):
        return "UnknownStatus()"


@StatusBase.register
class ActiveStatus(StatusBase):
    """The unit is ready.

    The unit believes it is correctly offering all the services it has been asked to offer.
    """
    name = 'active'

    def __init__(self, message: str = ''):
        super().__init__(message)


@StatusBase.register
class BlockedStatus(StatusBase):
    """The unit requires manual intervention.

    An operator has to manually intervene to unblock the unit and let it proceed.
    """
    name = 'blocked'


@StatusBase.register
class MaintenanceStatus(StatusBase):
    """The unit is performing maintenance tasks.

    The unit is not yet providing services, but is actively doing work in preparation
    for providing those services.  This is a "spinning" state, not an error state. It
    reflects activity on the unit itself, not on peers or related units.

    """
    name = 'maintenance'


@StatusBase.register
class WaitingStatus(StatusBase):
    """A unit is unable to progress.

    The unit is unable to progress to an active state because an application to which
    it is related is not running.

    """
    name = 'waiting'


class Resources:
    """Object representing resources for the charm."""

    def __init__(self, names: typing.Iterable[str], backend: '_ModelBackend'):
        self._backend = backend
        self._paths = {name: None for name in names}

    def fetch(self, name: str) -> Path:
        """Fetch the resource from the controller or store.

        If successfully fetched, this returns a Path object to where the resource is stored
        on disk, otherwise it raises a NameError.
        """
        if name not in self._paths:
            raise NameError('invalid resource name: {}'.format(name))
        if self._paths[name] is None:
            self._paths[name] = Path(self._backend.resource_get(name))
        return self._paths[name]


class Pod:
    """Represents the definition of a pod spec in Kubernetes models.

    Currently only supports simple access to setting the Juju pod spec via :attr:`.set_spec`.
    """

    def __init__(self, backend: '_ModelBackend'):
        self._backend = backend

    def set_spec(self, spec: typing.Mapping, k8s_resources: typing.Mapping = None):
        """Set the specification for pods that Juju should start in kubernetes.

        See `juju help-tool pod-spec-set` for details of what should be passed.

        Args:
            spec: The mapping defining the pod specification
            k8s_resources: Additional kubernetes specific specification.

        Returns:
            None
        """
        if not self._backend.is_leader():
            raise ModelError('cannot set a pod spec as this unit is not a leader')
        self._backend.pod_spec_set(spec, k8s_resources)


class StorageMapping(Mapping):
    """Map of storage names to lists of Storage instances."""

    def __init__(self, storage_names: typing.Iterable[str], backend: '_ModelBackend'):
        self._backend = backend
        self._storage_map = {storage_name: None for storage_name in storage_names}

    def __contains__(self, key: str):
        return key in self._storage_map

    def __len__(self):
        return len(self._storage_map)

    def __iter__(self):
        return iter(self._storage_map)

    def __getitem__(self, storage_name: str) -> typing.List['Storage']:
        storage_list = self._storage_map[storage_name]
        if storage_list is None:
            storage_list = self._storage_map[storage_name] = []
            for storage_id in self._backend.storage_list(storage_name):
                storage_list.append(Storage(storage_name, storage_id, self._backend))
        return storage_list

    def request(self, storage_name: str, count: int = 1):
        """Requests new storage instances of a given name.

        Uses storage-add tool to request additional storage. Juju will notify the unit
        via <storage-name>-storage-attached events when it becomes available.
        """
        if storage_name not in self._storage_map:
            raise ModelError(('cannot add storage {!r}:'
                              ' it is not present in the charm metadata').format(storage_name))
        self._backend.storage_add(storage_name, count)

    def _invalidate(self, storage_name):
        """Remove an entry from the storage map.

        Not meant to be used by charm authors -- this exists mainly for testing purposes.
        """
        self._storage_map[storage_name] = None


class Storage:
    """Represents a storage as defined in metadata.yaml.

    Attributes:
        name: Simple string name of the storage
        id: The provider id for storage
    """

    def __init__(self, storage_name, storage_id, backend):
        self.name = storage_name
        self.id = storage_id
        self._backend = backend
        self._location = None

    @property
    def location(self) -> Path:
        """Return the location of the storage."""
        if self._location is None:
            raw = self._backend.storage_get('{}/{}'.format(self.name, self.id), "location")
            self._location = Path(raw)
        return self._location

    @location.setter
    def location(self, location: str) -> None:
        """Sets the location for use in events.

        For :class:`StorageAttachedEvent` and :class:`StorageDetachingEvent` in case
        the actual details are gone from Juju by the time of a dynamic lookup.
        """
        self._location = Path(location)


class Container:
    """Represents a named container in a unit.

    This class should not be instantiated directly, instead use :meth:`Unit.get_container`
    or :attr:`Unit.containers`.

    Attributes:
        name: The name of the container from metadata.yaml (eg, 'postgres').
    """

    def __init__(self, name, backend, pebble_client=None):
        self.name = name

        if pebble_client is None:
            socket_path = '/charm/containers/{}/pebble.socket'.format(name)
            pebble_client = backend.get_pebble(socket_path)
        self._pebble = pebble_client

    @property
    def pebble(self) -> 'pebble.Client':
        """The low-level :class:`ops.pebble.Client` instance for this container."""
        return self._pebble

    def can_connect(self) -> bool:
        """Report whether the Pebble API is reachable in the container.

        :meth:`can_connect` returns a bool that indicates whether the Pebble API is available at
        the time the method is called. It does not guard against the Pebble API becoming
        unavailable, and should be treated as a 'point in time' status only.

        If the Pebble API later fails, serious consideration should be given as to the reason for
        this.

        Example::

            container = self.unit.get_container("example")
            if container.can_connect():
                try:
                    c.pull('/does/not/exist')
                except ProtocolError, PathError:
                    # handle it
            else:
                event.defer()
        """
        try:
            # TODO: This call to `get_system_info` should be replaced with a call to a more
            # appropriate endpoint that has stronger connotations of what constitutes a Pebble
            # instance that is in fact 'ready'.
            self._pebble.get_system_info()
        except pebble.ConnectionError as e:
            logger.debug("Pebble API is not ready; ConnectionError: %s", e.message())
            return False
        except FileNotFoundError as e:
            # In some cases, charm authors can attempt to hit the Pebble API before it has had the
            # chance to create the UNIX socket in the shared volume.
            logger.debug("Pebble API is not ready; UNIX socket not found:", str(e))
            return False
        except pebble.APIError as e:
            # An API error is only raised when the Pebble API returns invalid JSON, or the response
            # cannot be read. Both of these are a likely indicator that something is wrong.
            logger.warning("Pebble API is not ready; APIError: %s", str(e))
            return False
        return True

    def autostart(self):
        """Autostart all services marked as startup: enabled."""
        self._pebble.autostart_services()

    def replan(self):
        """Replan all services: restart changed services and start startup-enabled services."""
        self._pebble.replan_services()

    def start(self, *service_names: str):
        """Start given service(s) by name."""
        if not service_names:
            raise TypeError('start expected at least 1 argument, got 0')

        self._pebble.start_services(service_names)

    def restart(self, *service_names: str):
        """Restart the given service(s) by name."""
        if not service_names:
            raise TypeError('restart expected at least 1 argument, got 0')

        try:
            self._pebble.restart_services(service_names)
        except pebble.APIError as e:
            if e.code != 400:
                raise e
            # support old Pebble instances that don't support the "restart" action
            stop = tuple(s.name for s in self.get_services(*service_names).values()
                         if s.is_running())
            if stop:
                self._pebble.stop_services(stop)

            self._pebble.start_services(service_names)

    def stop(self, *service_names: str):
        """Stop given service(s) by name."""
        if not service_names:
            raise TypeError('stop expected at least 1 argument, got 0')

        self._pebble.stop_services(service_names)

    # TODO(benhoyt) - should be: layer: typing.Union[str, typing.Dict, 'pebble.Layer'],
    # but this breaks on Python 3.5.2 (the default on Xenial). See:
    # https://github.com/canonical/operator/issues/517
    def add_layer(self, label: str, layer, *, combine: bool = False):
        """Dynamically add a new layer onto the Pebble configuration layers.

        Args:
            label: Label for new layer (and label of layer to merge with if
                combining).
            layer: A YAML string, configuration layer dict, or pebble.Layer
                object containing the Pebble layer to add.
            combine: If combine is False (the default), append the new layer
                as the top layer with the given label (must be unique). If
                combine is True and the label already exists, the two layers
                are combined into a single one considering the layer override
                rules; if the layer doesn't exist, it is added as usual.
        """
        self._pebble.add_layer(label, layer, combine=combine)

    def get_plan(self) -> 'pebble.Plan':
        """Get the current effective pebble configuration."""
        return self._pebble.get_plan()

    def get_services(self, *service_names: str) -> 'ServiceInfoMapping':
        """Fetch and return a mapping of status information indexed by service name.

        If no service names are specified, return status information for all
        services, otherwise return information for only the given services.
        """
        service_names = service_names or None
        services = self._pebble.get_services(service_names)
        return ServiceInfoMapping(services)

    def get_service(self, service_name: str) -> 'pebble.ServiceInfo':
        """Get status information for a single named service.

        Raises :class:`ModelError` if service_name is not found.
        """
        services = self.get_services(service_name)
        if not services:
            raise ModelError('service {!r} not found'.format(service_name))
        if len(services) > 1:
            raise RuntimeError('expected 1 service, got {}'.format(len(services)))
        return services[service_name]

    def get_checks(
            self,
            *check_names: str,
            level: 'pebble.CheckLevel' = None) -> 'CheckInfoMapping':
        """Fetch and return a mapping of check information indexed by check name.

        Args:
            check_names: Optional check names to query for. If no check names
                are specified, return checks with any name.
            level: Optional check level to query for. If not specified, fetch
                checks with any level.
        """
        checks = self._pebble.get_checks(names=check_names or None, level=level)
        return CheckInfoMapping(checks)

    def get_check(self, check_name: str) -> 'pebble.CheckInfo':
        """Get check information for a single named check.

        Raises :class:`ModelError` if check_name is not found.
        """
        checks = self.get_checks(check_name)
        if not checks:
            raise ModelError('check {!r} not found'.format(check_name))
        if len(checks) > 1:
            raise RuntimeError('expected 1 check, got {}'.format(len(checks)))
        return checks[check_name]

    def pull(self, path: str, *, encoding: str = 'utf-8') -> typing.Union[typing.BinaryIO,
                                                                          typing.TextIO]:
        """Read a file's content from the remote system.

        Args:
            path: Path of the file to read from the remote system.
            encoding: Encoding to use for decoding the file's bytes to str,
                or None to specify no decoding.

        Returns:
            A readable file-like object, whose read() method will return str
            objects decoded according to the specified encoding, or bytes if
            encoding is None.
        """
        return self._pebble.pull(path, encoding=encoding)

    def push(
            self, path: str, source: typing.Union[bytes, str, typing.BinaryIO, typing.TextIO], *,
            encoding: str = 'utf-8', make_dirs: bool = False, permissions: int = None,
            user_id: int = None, user: str = None, group_id: int = None, group: str = None):
        """Write content to a given file path on the remote system.

        Args:
            path: Path of the file to write to on the remote system.
            source: Source of data to write. This is either a concrete str or
                bytes instance, or a readable file-like object.
            encoding: Encoding to use for encoding source str to bytes, or
                strings read from source if it is a TextIO type. Ignored if
                source is bytes or BinaryIO.
            make_dirs: If True, create parent directories if they don't exist.
            permissions: Permissions (mode) to create file with (Pebble default
                is 0o644).
            user_id: User ID (UID) for file.
            user: Username for file. User's UID must match user_id if both are
                specified.
            group_id: Group ID (GID) for file.
            group: Group name for file. Group's GID must match group_id if
                both are specified.
        """
        self._pebble.push(path, source, encoding=encoding, make_dirs=make_dirs,
                          permissions=permissions, user_id=user_id, user=user,
                          group_id=group_id, group=group)

    def list_files(self, path: str, *, pattern: str = None,
                   itself: bool = False) -> typing.List['pebble.FileInfo']:
        """Return list of directory entries from given path on remote system.

        Despite the name, this method returns a list of files *and*
        directories, similar to :func:`os.listdir` or :func:`os.scandir`.

        Args:
            path: Path of the directory to list, or path of the file to return
                information about.
            pattern: If specified, filter the list to just the files that match,
                for example ``*.txt``.
            itself: If path refers to a directory, return information about the
                directory itself, rather than its contents.
        """
        return self._pebble.list_files(path, pattern=pattern, itself=itself)

    def exists(self, path: str) -> bool:
        """Return true if the path exists on the container filesystem."""
        try:
            self._pebble.list_files(path, itself=True)
        except pebble.APIError as err:
            if err.code == 404:
                return False
            raise err
        return True

    def isdir(self, path: str) -> bool:
        """Return true if a directory exists at the given path on the container filesystem."""
        try:
            files = self._pebble.list_files(path, itself=True)
        except pebble.APIError as err:
            if err.code == 404:
                return False
            raise err
        return files[0].type == pebble.FileType.DIRECTORY

    def make_dir(
            self, path: str, *, make_parents: bool = False, permissions: int = None,
            user_id: int = None, user: str = None, group_id: int = None, group: str = None):
        """Create a directory on the remote system with the given attributes.

        Args:
            path: Path of the directory to create on the remote system.
            make_parents: If True, create parent directories if they don't exist.
            permissions: Permissions (mode) to create directory with (Pebble
                default is 0o755).
            user_id: User ID (UID) for directory.
            user: Username for directory. User's UID must match user_id if
                both are specified.
            group_id: Group ID (GID) for directory.
            group: Group name for directory. Group's GID must match group_id
                if both are specified.
        """
        self._pebble.make_dir(path, make_parents=make_parents, permissions=permissions,
                              user_id=user_id, user=user, group_id=group_id, group=group)

    def remove_path(self, path: str, *, recursive: bool = False):
        """Remove a file or directory on the remote system.

        Args:
            path: Path of the file or directory to delete from the remote system.
            recursive: If True, recursively delete path and everything under it.
        """
        self._pebble.remove_path(path, recursive=recursive)

    def exec(
        self,
        command: typing.List[str],
        *,
        environment: typing.Dict[str, str] = None,
        working_dir: str = None,
        timeout: float = None,
        user_id: int = None,
        user: str = None,
        group_id: int = None,
        group: str = None,
        stdin: typing.Union[str, bytes, typing.TextIO, typing.BinaryIO] = None,
        stdout: typing.Union[typing.TextIO, typing.BinaryIO] = None,
        stderr: typing.Union[typing.TextIO, typing.BinaryIO] = None,
        encoding: str = 'utf-8',
        combine_stderr: bool = False
    ) -> 'pebble.ExecProcess':
        """Execute the given command on the remote system.

        See :meth:`ops.pebble.Client.exec` for documentation of the parameters
        and return value, as well as examples.
        """
        return self._pebble.exec(
            command,
            environment=environment,
            working_dir=working_dir,
            timeout=timeout,
            user_id=user_id,
            user=user,
            group_id=group_id,
            group=group,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            encoding=encoding,
            combine_stderr=combine_stderr,
        )

    def send_signal(self, sig: typing.Union[int, str], *service_names: str):
        """Send the given signal to one or more services.

        Args:
            sig: Name or number of signal to send, e.g., "SIGHUP", 1, or
                signal.SIGHUP.
            service_names: Name(s) of the service(s) to send the signal to.

        Raises:
            pebble.APIError: If any of the services are not in the plan or are
                not currently running.
        """
        if not service_names:
            raise TypeError('send_signal expected at least 1 service name, got 0')

        self._pebble.send_signal(sig, service_names)


class ContainerMapping(Mapping):
    """Map of container names to Container objects.

    This is done as a mapping object rather than a plain dictionary so that we
    can extend it later, and so it's not mutable.
    """

    def __init__(self, names: typing.Iterable[str], backend: '_ModelBackend'):
        self._containers = {name: Container(name, backend) for name in names}

    def __getitem__(self, key: str):
        return self._containers[key]

    def __iter__(self):
        return iter(self._containers)

    def __len__(self):
        return len(self._containers)

    def __repr__(self):
        return repr(self._containers)


class ServiceInfoMapping(Mapping):
    """Map of service names to :class:`ops.pebble.ServiceInfo` objects.

    This is done as a mapping object rather than a plain dictionary so that we
    can extend it later, and so it's not mutable.
    """

    def __init__(self, services: typing.Iterable['pebble.ServiceInfo']):
        self._services = {s.name: s for s in services}

    def __getitem__(self, key: str):
        return self._services[key]

    def __iter__(self):
        return iter(self._services)

    def __len__(self):
        return len(self._services)

    def __repr__(self):
        return repr(self._services)


class CheckInfoMapping(Mapping):
    """Map of check names to :class:`ops.pebble.CheckInfo` objects.

    This is done as a mapping object rather than a plain dictionary so that we
    can extend it later, and so it's not mutable.
    """

    def __init__(self, checks: typing.Iterable['pebble.CheckInfo']):
        self._checks = {c.name: c for c in checks}

    def __getitem__(self, key: str):
        return self._checks[key]

    def __iter__(self):
        return iter(self._checks)

    def __len__(self):
        return len(self._checks)

    def __repr__(self):
        return repr(self._checks)


class ModelError(Exception):
    """Base class for exceptions raised when interacting with the Model."""
    pass


class TooManyRelatedAppsError(ModelError):
    """Raised by :meth:`Model.get_relation` if there is more than one related application."""

    def __init__(self, relation_name, num_related, max_supported):
        super().__init__('Too many remote applications on {} ({} > {})'.format(
            relation_name, num_related, max_supported))
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class RelationDataError(ModelError):
    """Raised by ``Relation.data[entity][key] = 'foo'`` if the data is invalid.

    This is raised if you're either trying to set a value to something that isn't a string,
    or if you are trying to set a value in a bucket that you don't have access to. (eg,
    another application/unit or setting your application data but you aren't the leader.)
    """


class RelationNotFoundError(ModelError):
    """Backend error when querying juju for a given relation and that relation doesn't exist."""


class InvalidStatusError(ModelError):
    """Raised if trying to set an Application or Unit status to something invalid."""


_ACTION_RESULT_KEY_REGEX = re.compile(r'^[a-z0-9](([a-z0-9-.]+)?[a-z0-9])?$')


def _format_action_result_dict(input: dict, parent_key: str = None, output: dict = None) -> dict:
    """Turn a nested dictionary into a flattened dictionary, using '.' as a key seperator.

    This is used to allow nested dictionaries to be translated into the dotted format required by
    the Juju `action-set` hook tool in order to set nested data on an action.

    Additionally, this method performs some validation on keys to ensure they only use permitted
    characters.

    Example::

        >>> test_dict = {'a': {'b': 1, 'c': 2}}
        >>> _format_action_result_dict(test_dict)
        {'a.b': 1, 'a.c': 2}

    Arguments:
        input: The dictionary to flatten
        parent_key: The string to prepend to dictionary's keys
        output: The current dictionary to be returned, which may or may not yet be completely flat

    Returns:
        A flattened dictionary with validated keys

    Raises:
        ValueError: if the dict is passed with a mix of dotted/non-dotted keys that expand out to
            result in duplicate keys. For example: {'a': {'b': 1}, 'a.b': 2}. Also raised if a dict
            is passed with a key that fails to meet the format requirements.
    """
    if output is None:
        output = {}

    for key, value in input.items():
        # Ensure the key is of a valid format, and raise a ValueError if not
        if not _ACTION_RESULT_KEY_REGEX.match(key):
            raise ValueError("key '{!r}' is invalid: must be similar to 'key', 'some-key2', or "
                             "'some.key'".format(key))

        if parent_key:
            key = "{}.{}".format(parent_key, key)

        if isinstance(value, MutableMapping):
            output = _format_action_result_dict(value, key, output)
        elif key in output:
            raise ValueError("duplicate key detected in dictionary passed to 'action-set': {!r}"
                             .format(key))
        else:
            output[key] = value

    return output


class _ModelBackend:
    """Represents the connection between the Model representation and talking to Juju.

    Charm authors should not directly interact with the ModelBackend, it is a private
    implementation of Model.
    """

    LEASE_RENEWAL_PERIOD = datetime.timedelta(seconds=30)

    def __init__(self, unit_name=None, model_name=None, model_uuid=None):
        if unit_name is None:
            self.unit_name = os.environ['JUJU_UNIT_NAME']
        else:
            self.unit_name = unit_name
        if model_name is None:
            model_name = os.environ.get('JUJU_MODEL_NAME')
        if model_uuid is None:
            model_uuid = os.environ.get('JUJU_MODEL_UUID')
        self.model_name = model_name
        self.model_uuid = model_uuid
        self.app_name = self.unit_name.split('/')[0]

        self._is_leader = None
        self._leader_check_time = None

    def _run(self, *args, return_output=False, use_json=False):
        kwargs = dict(stdout=PIPE, stderr=PIPE, check=True)
        args = (shutil.which(args[0]),) + args[1:]
        if use_json:
            args += ('--format=json',)
        try:
            result = run(args, **kwargs)
        except CalledProcessError as e:
            raise ModelError(e.stderr)
        if return_output:
            if result.stdout is None:
                return ''
            else:
                text = result.stdout.decode('utf8')
                if use_json:
                    return json.loads(text)
                else:
                    return text

    @staticmethod
    def _is_relation_not_found(model_error):
        return 'relation not found' in str(model_error)

    def relation_ids(self, relation_name):
        relation_ids = self._run('relation-ids', relation_name, return_output=True, use_json=True)
        return [int(relation_id.split(':')[-1]) for relation_id in relation_ids]

    def relation_list(self, relation_id):
        try:
            return self._run('relation-list', '-r', str(relation_id),
                             return_output=True, use_json=True)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def relation_remote_app_name(self, relation_id: int) -> typing.Optional[str]:
        """Return remote app name for given relation ID, or None if not known."""
        if 'JUJU_RELATION_ID' in os.environ and 'JUJU_REMOTE_APP' in os.environ:
            event_relation_id = int(os.environ['JUJU_RELATION_ID'].split(':')[-1])
            if relation_id == event_relation_id:
                # JUJU_RELATION_ID is this relation, use JUJU_REMOTE_APP.
                return os.environ['JUJU_REMOTE_APP']

        # If caller is asking for information about another relation, use
        # "relation-list --app" to get it.
        try:
            return self._run('relation-list', '-r', str(relation_id), '--app',
                             return_output=True, use_json=True)
        except ModelError as e:
            if self._is_relation_not_found(e):
                return None
            if 'option provided but not defined: --app' in str(e):
                # "--app" was introduced to relation-list in Juju 2.8.1, so
                # handle previous versions of Juju gracefully
                return None
            raise

    def relation_get(self, relation_id, member_name, is_app):
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_get must be a boolean')

        if is_app:
            version = JujuVersion.from_environ()
            if not version.has_app_data():
                raise RuntimeError(
                    'getting application data is not supported on Juju version {}'.format(version))

        args = ['relation-get', '-r', str(relation_id), '-', member_name]
        if is_app:
            args.append('--app')

        try:
            return self._run(*args, return_output=True, use_json=True)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def relation_set(self, relation_id, key, value, is_app):
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_set must be a boolean')

        if is_app:
            version = JujuVersion.from_environ()
            if not version.has_app_data():
                raise RuntimeError(
                    'setting application data is not supported on Juju version {}'.format(version))

        args = ['relation-set', '-r', str(relation_id), '{}={}'.format(key, value)]
        if is_app:
            args.append('--app')

        try:
            return self._run(*args)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def config_get(self):
        return self._run('config-get', return_output=True, use_json=True)

    def is_leader(self):
        """Obtain the current leadership status for the unit the charm code is executing on.

        The value is cached for the duration of a lease which is 30s in Juju.
        """
        now = time.monotonic()
        if self._leader_check_time is None:
            check = True
        else:
            time_since_check = datetime.timedelta(seconds=now - self._leader_check_time)
            check = (time_since_check > self.LEASE_RENEWAL_PERIOD or self._is_leader is None)
        if check:
            # Current time MUST be saved before running is-leader to ensure the cache
            # is only used inside the window that is-leader itself asserts.
            self._leader_check_time = now
            self._is_leader = self._run('is-leader', return_output=True, use_json=True)

        return self._is_leader

    def resource_get(self, resource_name):
        return self._run('resource-get', resource_name, return_output=True).strip()

    def pod_spec_set(self, spec, k8s_resources):
        tmpdir = Path(tempfile.mkdtemp('-pod-spec-set'))
        try:
            spec_path = tmpdir / 'spec.yaml'
            with spec_path.open("wt", encoding="utf8") as f:
                yaml.safe_dump(spec, stream=f)
            args = ['--file', str(spec_path)]
            if k8s_resources:
                k8s_res_path = tmpdir / 'k8s-resources.yaml'
                with k8s_res_path.open("wt", encoding="utf8") as f:
                    yaml.safe_dump(k8s_resources, stream=f)
                args.extend(['--k8s-resources', str(k8s_res_path)])
            self._run('pod-spec-set', *args)
        finally:
            shutil.rmtree(str(tmpdir))

    def status_get(self, *, is_app=False):
        """Get a status of a unit or an application.

        Args:
            is_app: A boolean indicating whether the status should be retrieved for a unit
                or an application.
        """
        content = self._run(
            'status-get', '--include-data', '--application={}'.format(is_app),
            use_json=True,
            return_output=True)
        # Unit status looks like (in YAML):
        # message: 'load: 0.28 0.26 0.26'
        # status: active
        # status-data: {}
        # Application status looks like (in YAML):
        # application-status:
        #   message: 'load: 0.28 0.26 0.26'
        #   status: active
        #   status-data: {}
        #   units:
        #     uo/0:
        #       message: 'load: 0.28 0.26 0.26'
        #       status: active
        #       status-data: {}

        if is_app:
            return {'status': content['application-status']['status'],
                    'message': content['application-status']['message']}
        else:
            return content

    def status_set(self, status, message='', *, is_app=False):
        """Set a status of a unit or an application.

        Args:
            status: The status to set.
            message: The message to set in the status.
            is_app: A boolean indicating whether the status should be set for a unit or an
                    application.
        """
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter must be boolean')
        return self._run('status-set', '--application={}'.format(is_app), status, message)

    def storage_list(self, name):
        return [int(s.split('/')[1]) for s in self._run('storage-list', name,
                                                        return_output=True, use_json=True)]

    def _storage_event_details(self) -> typing.Tuple[int, str]:
        output = self._run('storage-get', '--help', return_output=True)

        # Match the entire string at once instead of going line by line
        matcher = re.compile(
            r'.*^-s\s+\(=\s+(?P<storage_key>.*?)\)\s*?$',
            re.MULTILINE | re.DOTALL
        )
        key = matcher.match(output).groupdict()["storage_key"]

        id = int(key.split("/")[1])
        location = self.storage_get(key, "location")
        return id, location

    def storage_get(self, storage_name_id, attribute):
        return self._run('storage-get', '-s', storage_name_id, attribute,
                         return_output=True, use_json=True)

    def storage_add(self, name, count=1):
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError('storage count must be integer, got: {} ({})'.format(count,
                                                                                 type(count)))
        self._run('storage-add', '{}={}'.format(name, count))

    def action_get(self):
        return self._run('action-get', return_output=True, use_json=True)

    def action_set(self, results):
        # The Juju action-set hook tool cannot interpret nested dicts, so we use a helper to
        # flatten out any nested dict structures into a dotted notation, and validate keys.
        flat_results = _format_action_result_dict(results)
        self._run('action-set', *["{}={}".format(k, v) for k, v in flat_results.items()])

    def action_log(self, message):
        self._run('action-log', message)

    def action_fail(self, message=''):
        self._run('action-fail', message)

    def application_version_set(self, version):
        self._run('application-version-set', '--', version)

    @classmethod
    def log_split(cls, message, max_len=MAX_LOG_LINE_LEN):
        """Helper to handle log messages that are potentially too long.

        This is a generator that splits a message string into multiple chunks if it is too long
        to safely pass to bash. Will only generate a single entry if the line is not too long.
        """
        if len(message) > max_len:
            yield "Log string greater than {}. Splitting into multiple chunks: ".format(max_len)

        while message:
            yield message[:max_len]
            message = message[max_len:]

    def juju_log(self, level, message):
        """Pass a log message on to the juju logger."""
        for line in self.log_split(message):
            self._run('juju-log', '--log-level', level, "--", line)

    def network_get(self, binding_name, relation_id=None):
        """Return network info provided by network-get for a given binding.

        Args:
            binding_name: A name of a binding (relation name or extra-binding name).
            relation_id: An optional relation id to get network info for.
        """
        cmd = ['network-get', binding_name]
        if relation_id is not None:
            cmd.extend(['-r', str(relation_id)])
        try:
            return self._run(*cmd, return_output=True, use_json=True)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def add_metrics(self, metrics, labels=None):
        cmd = ['add-metric']

        if labels:
            label_args = []
            for k, v in labels.items():
                _ModelBackendValidator.validate_metric_label(k)
                _ModelBackendValidator.validate_label_value(k, v)
                label_args.append('{}={}'.format(k, v))
            cmd.extend(['--labels', ','.join(label_args)])

        metric_args = []
        for k, v in metrics.items():
            _ModelBackendValidator.validate_metric_key(k)
            metric_value = _ModelBackendValidator.format_metric_value(v)
            metric_args.append('{}={}'.format(k, metric_value))
        cmd.extend(metric_args)
        self._run(*cmd)

    def get_pebble(self, socket_path: str) -> 'pebble.Client':
        """Create a pebble.Client instance from given socket path."""
        return pebble.Client(socket_path=socket_path)

    def planned_units(self) -> int:
        """Count of "planned" units that will run this application.

        Includes the current unit in the count.

        """
        # The goal-state tool will return the information that we need. Goal state as a general
        # concept is being deprecated, however, in favor of approaches such as the one that we use
        # here.
        app_state = self._run('goal-state', return_output=True, use_json=True)
        # Planned units can be zero. We don't need to do error checking here.
        return len(app_state.get('units', []))


class _ModelBackendValidator:
    """Provides facilities for validating inputs and formatting them for model backends."""

    METRIC_KEY_REGEX = re.compile(r'^[a-zA-Z](?:[a-zA-Z0-9-_]*[a-zA-Z0-9])?$')

    @classmethod
    def validate_metric_key(cls, key):
        if cls.METRIC_KEY_REGEX.match(key) is None:
            raise ModelError(
                'invalid metric key {!r}: must match {}'.format(
                    key, cls.METRIC_KEY_REGEX.pattern))

    @classmethod
    def validate_metric_label(cls, label_name):
        if cls.METRIC_KEY_REGEX.match(label_name) is None:
            raise ModelError(
                'invalid metric label name {!r}: must match {}'.format(
                    label_name, cls.METRIC_KEY_REGEX.pattern))

    @classmethod
    def format_metric_value(cls, value):
        if not isinstance(value, (int, float)):
            raise ModelError('invalid metric value {!r} provided:'
                             ' must be a positive finite float'.format(value))

        if math.isnan(value) or math.isinf(value) or value < 0:
            raise ModelError('invalid metric value {!r} provided:'
                             ' must be a positive finite float'.format(value))
        return str(value)

    @classmethod
    def validate_label_value(cls, label, value):
        # Label values cannot be empty, contain commas or equal signs as those are
        # used by add-metric as separators.
        if not value:
            raise ModelError(
                'metric label {} has an empty value, which is not allowed'.format(label))
        v = str(value)
        if re.search('[,=]', v) is not None:
            raise ModelError(
                'metric label values must not contain "," or "=": {}={!r}'.format(label, value))
