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

import dataclasses
import datetime
import enum
import ipaddress
import json
import logging
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import typing
import weakref
from abc import ABC, abstractmethod
from pathlib import Path, PurePath
from typing import (
    Any,
    BinaryIO,
    Callable,
    Dict,
    Generator,
    Iterable,
    List,
    Literal,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    TextIO,
    Tuple,
    Type,
    TypedDict,
    Union,
)

import ops
import ops.pebble as pebble
from ops._private import timeconv, yaml
from ops.jujuversion import JujuVersion

# a k8s spec is a mapping from names/"types" to json/yaml spec objects
K8sSpec = Mapping[str, Any]

_ConfigOption = TypedDict('_ConfigOption', {
    'type': Literal['string', 'int', 'float', 'boolean'],
    'description': str,
    'default': Union[str, int, float, bool],
})

_StorageDictType = Dict[str, Optional[List['Storage']]]
_BindingDictType = Dict[Union[str, 'Relation'], 'Binding']

_StatusDict = TypedDict('_StatusDict', {'status': str, 'message': str})

# mapping from relation name to a list of relation objects
_RelationMapping_Raw = Dict[str, Optional[List['Relation']]]
# mapping from container name to container metadata
_ContainerMeta_Raw = Dict[str, 'ops.charm.ContainerMeta']

# relation data is a string key: string value mapping so far as the
# controller is concerned
_RelationDataContent_Raw = Dict[str, str]
UnitOrApplicationType = Union[Type['Unit'], Type['Application']]

_AddressDict = TypedDict('_AddressDict', {
    'address': str,  # Juju < 2.9
    'value': str,  # Juju >= 2.9
    'cidr': str
})
_BindAddressDict = TypedDict('_BindAddressDict', {
    'interface-name': str,
    'addresses': List[_AddressDict]
})
_NetworkDict = TypedDict('_NetworkDict', {
    'bind-addresses': List[_BindAddressDict],
    'ingress-addresses': List[str],
    'egress-subnets': List[str]
})


logger = logging.getLogger(__name__)

MAX_LOG_LINE_LEN = 131071  # Max length of strings to pass to subshell.


class Model:
    """Represents the Juju Model as seen from this unit.

    This should not be instantiated directly by Charmers, but can be accessed
    as ``self.model`` from any class that derives from :class:`Object`.
    """

    def __init__(self, meta: 'ops.charm.CharmMeta', backend: '_ModelBackend'):
        self._cache = _ModelCache(meta, backend)
        self._backend = backend
        self._unit = self.get_unit(self._backend.unit_name)
        relations: Dict[str, 'ops.RelationMeta'] = meta.relations
        self._relations = RelationMapping(relations, self.unit, self._backend, self._cache)
        self._config = ConfigData(self._backend)
        resources: Iterable[str] = meta.resources
        self._resources = Resources(list(resources), self._backend)
        self._pod = Pod(self._backend)
        storages: Iterable[str] = meta.storages
        self._storages = StorageMapping(list(storages), self._backend)
        self._bindings = BindingMapping(self._backend)

    @property
    def unit(self) -> 'Unit':
        """The unit that is running this code.

        Use :meth:`get_unit` to get an arbitrary unit by name.
        """
        return self._unit

    @property
    def app(self) -> 'Application':
        """The application this unit is a part of.

        Use :meth:`get_app` to get an arbitrary application by name.
        """
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
        """Represents the definition of a pod spec in legacy Kubernetes models.

        DEPRECATED: New charms should use the sidecar pattern with Pebble.

        Use :meth:`Pod.set_spec` to set the container specification for legacy
        Kubernetes charms.
        """
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

        Use :attr:`unit` to get the current unit.

        Internally this uses a cache, so asking for the same unit two times will
        return the same object.
        """
        return self._cache.get(Unit, unit_name)

    def get_app(self, app_name: str) -> 'Application':
        """Get an application by name.

        Use :attr:`app` to get this charm's application.

        Internally this uses a cache, so asking for the same application two times will
        return the same object.
        """
        return self._cache.get(Application, app_name)

    def get_relation(
            self, relation_name: str,
            relation_id: Optional[int] = None) -> Optional['Relation']:
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

    def get_binding(self, binding_key: Union[str, 'Relation']) -> Optional['Binding']:
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

    def get_secret(self, *, id: Optional[str] = None, label: Optional[str] = None) -> 'Secret':
        """Get the :class:`Secret` with the given ID or label.

        The caller must provide at least one of `id` (the secret's locator ID)
        or `label` (the charm-local "name").

        If both are provided, the secret will be fetched by ID, and the
        secret's label will be updated to the label provided. Normally secret
        owners set a label using ``add_secret``, whereas secret observers set
        a label using ``get_secret`` (see an example at :attr:`Secret.label`).

        Args:
            id: Secret ID if fetching by ID.
            label: Secret label if fetching by label (or updating it).

        Raises:
            SecretNotFoundError: If a secret with this ID or label doesn't exist.
        """
        if not (id or label):
            raise TypeError('Must provide an id or label, or both')
        if id is not None:
            # Canonicalize to "secret:<id>" form for consistency in backend calls.
            id = Secret._canonicalize_id(id)
        content = self._backend.secret_get(id=id, label=label)
        return Secret(self._backend, id=id, label=label, content=content)


class _ModelCache:
    def __init__(self, meta: 'ops.charm.CharmMeta', backend: '_ModelBackend'):
        if typing.TYPE_CHECKING:
            # (entity type, name): instance.
            _weakcachetype = weakref.WeakValueDictionary[
                Tuple['UnitOrApplicationType', str],
                Optional[Union['Unit', 'Application']]]

        self._meta = meta
        self._backend = backend
        self._weakrefs: _weakcachetype = weakref.WeakValueDictionary()

    @typing.overload
    def get(self, entity_type: Type['Unit'], name: str) -> 'Unit': ...  # noqa
    @typing.overload
    def get(self, entity_type: Type['Application'], name: str) -> 'Application': ...  # noqa

    def get(self, entity_type: 'UnitOrApplicationType', name: str):
        """Fetch the cached entity of type `entity_type` with name `name`."""
        key = (entity_type, name)
        entity = self._weakrefs.get(key)
        if entity is not None:
            return entity

        new_entity = entity_type(name, meta=self._meta, backend=self._backend, cache=self)
        self._weakrefs[key] = new_entity
        return new_entity


class Application:
    """Represents a named application in the model.

    This might be this charm's application, or might be an application this charm is related
    to. Charmers should not instantiate Application objects directly, but should use
    :attr:`Model.app` to get the application this unit is part of, or
    :meth:`Model.get_app` if they need a reference to a given application.
    """

    name: str
    """The name of this application (eg, 'mysql'). This name may differ from the name of
    the charm, if the user has deployed it to a different name.
    """

    def __init__(self, name: str, meta: 'ops.charm.CharmMeta',
                 backend: '_ModelBackend', cache: _ModelCache):
        self.name = name
        self._backend = backend
        self._cache = cache
        self._is_our_app = self.name == self._backend.app_name
        self._status = None
        self._collected_statuses: 'List[StatusBase]' = []

    def _invalidate(self):
        self._status = None

    @property
    def status(self) -> 'StatusBase':
        """Used to report or read the status of the overall application.

        Changes to status take effect immediately, unlike other Juju operations
        such as modifying relation data or secrets, which only take effect after
        a successful event.

        Can only be read and set by the lead unit of the application.

        The status of remote units is always Unknown.

        Alternatively, use the :attr:`collect_app_status <CharmEvents.collect_app_status>`
        event to evaluate and set application status consistently at the end of every hook.

        Raises:
            RuntimeError: if setting the status of another application, or if setting the
                status of this application as a unit that is not the leader.
            InvalidStatusError: if setting the status to something that is not a
                :class:`StatusBase`

        Example::

            self.model.app.status = ops.BlockedStatus('I need a human to come help me')
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
                f'invalid value provided for application {self} status: {value}'
            )

        if not self._is_our_app:
            raise RuntimeError(f'cannot set status for a remote application {self}')

        if not self._backend.is_leader():
            raise RuntimeError('cannot set application status as a non-leader unit')

        for _key in {'name', 'message'}:
            assert isinstance(getattr(value, _key), str), f'status.{_key} must be a string'
        self._backend.status_set(value.name, value.message, is_app=True)
        self._status = value

    def planned_units(self) -> int:
        """Get the number of units that Juju has "planned" for this application.

        E.g., if an admin runs "juju deploy foo", then "juju add-unit -n 2 foo", the
        planned unit count for foo will be 3.

        The data comes from the Juju agent, based on data it fetches from the
        controller. Pending units are included in the count, and scale down events may
        modify the count before some units have been fully torn down. The information in
        planned_units is up-to-date as of the start of the current hook invocation.

        This method only returns data for this charm's application -- the Juju agent isn't
        able to see planned unit counts for other applications in the model.

        Raises:
            RuntimeError: on trying to get the planned units for a remote application.
        """
        if not self._is_our_app:
            raise RuntimeError(
                f'cannot get planned units for a remote application {self}.')

        return self._backend.planned_units()

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'

    def add_secret(self, content: Dict[str, str], *,
                   label: Optional[str] = None,
                   description: Optional[str] = None,
                   expire: Optional[Union[datetime.datetime, datetime.timedelta]] = None,
                   rotate: Optional['SecretRotate'] = None) -> 'Secret':
        """Create a :class:`Secret` owned by this application.

        Args:
            content: A key-value mapping containing the payload of the secret,
                for example :code:`{"password": "foo123"}`.
            label: Charm-local label (or "name") to assign to this secret,
                which can later be used for lookup.
            description: Description of the secret's purpose.
            expire: Time in the future (or timedelta from now) at which the
                secret is due to expire. When that time elapses, Juju will
                notify the charm by sending a SecretExpired event. None (the
                default) means the secret will never expire.
            rotate: Rotation policy/time. Every time this elapses, Juju will
                notify the charm by sending a SecretRotate event. None (the
                default) means to use the Juju default, which is never rotate.

        Raises:
            ValueError: if the secret is empty, or the secret key is invalid.
        """
        Secret._validate_content(content)
        id = self._backend.secret_add(
            content,
            label=label,
            description=description,
            expire=_calculate_expiry(expire),
            rotate=rotate,
            owner='application')
        return Secret(self._backend, id=id, label=label, content=content)


def _calculate_expiry(expire: Optional[Union[datetime.datetime, datetime.timedelta]],
                      ) -> Optional[datetime.datetime]:
    if expire is None:
        return None
    if isinstance(expire, datetime.datetime):
        return expire
    elif isinstance(expire, datetime.timedelta):
        return datetime.datetime.now() + expire
    else:
        raise TypeError('Expiration time must be a datetime or timedelta from now, not '
                        + type(expire).__name__)


class Unit:
    """Represents a named unit in the model.

    This might be the current unit, another unit of the charm's application, or a unit of
    another application that the charm is related to.
    """

    name: str
    """Name of the unit, for example "mysql/0"."""

    app: Application
    """Application the unit is part of."""

    def __init__(self, name: str, meta: 'ops.charm.CharmMeta',
                 backend: '_ModelBackend', cache: '_ModelCache'):
        self.name = name

        app_name = name.split('/')[0]
        self.app = cache.get(Application, app_name)

        self._backend = backend
        self._cache = cache
        self._is_our_unit = self.name == self._backend.unit_name
        self._status = None
        self._collected_statuses: 'List[StatusBase]' = []

        if self._is_our_unit and hasattr(meta, "containers"):
            containers: _ContainerMeta_Raw = meta.containers
            self._containers = ContainerMapping(iter(containers), backend)

    def _invalidate(self):
        self._status = None

    @property
    def status(self) -> 'StatusBase':
        """Used to report or read the status of a specific unit.

        Changes to status take effect immediately, unlike other Juju operations
        such as modifying relation data or secrets, which only take effect after
        a successful event.

        The status of any unit other than the current unit is always Unknown.

        Alternatively, use the :attr:`collect_unit_status <CharmEvents.collect_unit_status>`
        event to evaluate and set unit status consistently at the end of every hook.

        Raises:
            RuntimeError: if setting the status of a unit other than the current unit
            InvalidStatusError: if setting the status to something other than
                a :class:`StatusBase`

        Example::

            self.model.unit.status = ops.MaintenanceStatus('reconfiguring the frobnicators')
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
                f'invalid value provided for unit {self} status: {value}'
            )

        if not self._is_our_unit:
            raise RuntimeError(f'cannot set status for a remote unit {self}')

        # fixme: if value.messages
        self._backend.status_set(value.name, value.message, is_app=False)
        self._status = value

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'

    def is_leader(self) -> bool:
        """Return whether this unit is the leader of its application.

        This can only be called for the current unit.

        Raises:
            RuntimeError: if called for another unit
        """
        if self._is_our_unit:
            # This value is not cached as it is not guaranteed to persist for the whole duration
            # of a hook execution.
            return self._backend.is_leader()
        else:
            raise RuntimeError(
                f'leadership status of remote units ({self}) is not visible to other applications'
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
    def containers(self) -> Mapping[str, 'Container']:
        """Return a mapping of containers indexed by name.

        Raises:
            RuntimeError: if called for another unit
        """
        if not self._is_our_unit:
            raise RuntimeError(f'cannot get container for a remote unit {self}')
        return self._containers

    def get_container(self, container_name: str) -> 'Container':
        """Get a single container by name.

        Raises:
            ModelError: if the named container doesn't exist
        """
        try:
            return self.containers[container_name]
        except KeyError:
            raise ModelError(f'container {container_name!r} not found') from None

    def add_secret(self, content: Dict[str, str], *,
                   label: Optional[str] = None,
                   description: Optional[str] = None,
                   expire: Optional[Union[datetime.datetime, datetime.timedelta]] = None,
                   rotate: Optional['SecretRotate'] = None) -> 'Secret':
        """Create a :class:`Secret` owned by this unit.

        See :meth:`Application.add_secret` for parameter details.

        Raises:
            ValueError: if the secret is empty, or the secret key is invalid.
        """
        Secret._validate_content(content)
        id = self._backend.secret_add(
            content,
            label=label,
            description=description,
            expire=_calculate_expiry(expire),
            rotate=rotate,
            owner='unit')
        return Secret(self._backend, id=id, label=label, content=content)

    def open_port(self, protocol: typing.Literal['tcp', 'udp', 'icmp'],
                  port: Optional[int] = None) -> None:
        """Open a port with the given protocol for this unit.

        Some behaviour, such as whether the port is opened externally without
        using "juju expose" and whether the opened ports are per-unit, differs
        between Kubernetes and machine charms. See the
        `Juju documentation <https://juju.is/docs/sdk/hook-tool#heading--open-port>`__
        for more detail.

        Use :meth:`set_ports` for a more declarative approach where all of
        the ports that should be open are provided in a single call.

        Args:
            protocol: String representing the protocol; must be one of
                'tcp', 'udp', or 'icmp' (lowercase is recommended, but
                uppercase is also supported).
            port: The port to open. Required for TCP and UDP; not allowed
                for ICMP.

        Raises:
            ModelError: If ``port`` is provided when ``protocol`` is 'icmp'
                or ``port`` is not provided when ``protocol`` is 'tcp' or
                'udp'.
        """
        self._backend.open_port(protocol.lower(), port)

    def close_port(self, protocol: typing.Literal['tcp', 'udp', 'icmp'],
                   port: Optional[int] = None) -> None:
        """Close a port with the given protocol for this unit.

        Some behaviour, such as whether the port is closed externally without
        using "juju unexpose", differs between Kubernetes and machine charms.
        See the
        `Juju documentation <https://juju.is/docs/sdk/hook-tool#heading--close-port>`__
        for more detail.

        Use :meth:`set_ports` for a more declarative approach where all
        of the ports that should be open are provided in a single call.
        For example, ``set_ports()`` will close all open ports.

        Args:
            protocol: String representing the protocol; must be one of
                'tcp', 'udp', or 'icmp' (lowercase is recommended, but
                uppercase is also supported).
            port: The port to open. Required for TCP and UDP; not allowed
                for ICMP.

        Raises:
            ModelError: If ``port`` is provided when ``protocol`` is 'icmp'
                or ``port`` is not provided when ``protocol`` is 'tcp' or
                'udp'.
        """
        self._backend.close_port(protocol.lower(), port)

    def opened_ports(self) -> Set['Port']:
        """Return a list of opened ports for this unit."""
        return self._backend.opened_ports()

    def set_ports(self, *ports: Union[int, 'Port']) -> None:
        """Set the open ports for this unit, closing any others that are open.

        Some behaviour, such as whether the port is opened or closed externally without
        using Juju's ``expose`` and ``unexpose`` commands, differs between Kubernetes
        and machine charms. See the
        `Juju documentation <https://juju.is/docs/sdk/hook-tool#heading--networking>`__
        for more detail.

        Use :meth:`open_port` and :meth:`close_port` to manage ports
        individually.

        *New in version 2.7*

        Args:
            ports: The ports to open. Provide an int to open a TCP port, or
                a :class:`Port` to open a port for another protocol.

        Raises:
            ModelError: if a :class:`Port` is provided where ``protocol`` is 'icmp' but
                ``port`` is not ``None``, or where ``protocol`` is 'tcp' or 'udp' and ``port``
                is ``None``.
        """
        # Normalise to get easier comparisons.
        existing = {
            (port.protocol, port.port)
            for port in self._backend.opened_ports()
        }
        desired = {
            ('tcp', port) if isinstance(port, int) else (port.protocol, port.port)
            for port in ports
        }
        for protocol, port in existing - desired:
            self._backend.close_port(protocol, port)
        for protocol, port in desired - existing:
            self._backend.open_port(protocol, port)

    def reboot(self, now: bool = False) -> None:
        """Reboot the host machine.

        Normally, the reboot will only take place after the current hook successfully
        completes. Use ``now=True`` to reboot immediately without waiting for the
        hook to complete; this is useful when multiple restarts are required (Juju
        will re-run the hook after rebooting).

        This is not supported on Kubernetes charms, can only be called for the current unit,
        and cannot be used in an action hook.

        *New in version 2.8*

        Args:
            now: terminate immediately without waiting for the current hook to complete,
                restarting the hook after reboot.

        Raises:
            RuntimeError: if called on a remote unit.
            :class:`ModelError`: if used in an action hook.

        """
        if not self._is_our_unit:
            raise RuntimeError(f'cannot reboot a remote unit {self}')
        self._backend.reboot(now)


@dataclasses.dataclass(frozen=True)
class Port:
    """Represents a port opened by :meth:`Unit.open_port` or :meth:`Unit.set_ports`."""

    protocol: typing.Literal['tcp', 'udp', 'icmp']
    """The IP protocol."""

    port: Optional[int]
    """The port number. Will be ``None`` if protocol is ``'icmp'``."""


OpenedPort = Port  # Alias for backwards compatibility.


class LazyMapping(Mapping[str, str], ABC):
    """Represents a dict that isn't populated until it is accessed.

    Charm authors should generally never need to use this directly, but it forms
    the basis for many of the dicts that the framework tracks.
    """

    # key-value mapping
    _lazy_data: Optional[Dict[str, str]] = None

    @abstractmethod
    def _load(self) -> Dict[str, str]:
        raise NotImplementedError()

    @property
    def _data(self) -> Dict[str, str]:
        data = self._lazy_data
        if data is None:
            data = self._lazy_data = self._load()
        return data

    def _invalidate(self):
        self._lazy_data = None

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key: str) -> str:
        return self._data[key]

    def __repr__(self):
        return repr(self._data)


class RelationMapping(Mapping[str, List['Relation']]):
    """Map of relation names to lists of :class:`Relation` instances."""

    def __init__(self, relations_meta: Dict[str, 'ops.RelationMeta'], our_unit: 'Unit',
                 backend: '_ModelBackend', cache: '_ModelCache'):
        self._peers: Set[str] = set()
        for name, relation_meta in relations_meta.items():
            if relation_meta.role.is_peer():
                self._peers.add(name)
        self._our_unit = our_unit
        self._backend = backend
        self._cache = cache
        self._data: _RelationMapping_Raw = {r: None for r in relations_meta}

    def __contains__(self, key: str):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self) -> Iterable[str]:
        return iter(self._data)

    def __getitem__(self, relation_name: str) -> List['Relation']:
        is_peer = relation_name in self._peers
        relation_list: Optional[List[Relation]] = self._data[relation_name]
        if not isinstance(relation_list, list):
            relation_list = self._data[relation_name] = []  # type: ignore
            for rid in self._backend.relation_ids(relation_name):
                relation = Relation(relation_name, rid, is_peer,
                                    self._our_unit, self._backend, self._cache)
                relation_list.append(relation)
        return relation_list

    def _invalidate(self, relation_name: str):
        """Used to wipe the cache of a given relation_name.

        Not meant to be used by Charm authors. The content of relation data is
        static for the lifetime of a hook, so it is safe to cache in memory once
        accessed.
        """
        self._data[relation_name] = None

    def _get_unique(self, relation_name: str, relation_id: Optional[int] = None):
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
        relations = self[relation_name]
        num_related = len(relations)
        self._backend._validate_relation_access(
            relation_name, relations)
        if num_related == 0:
            return None
        elif num_related == 1:
            return self[relation_name][0]
        else:
            # TODO: We need something in the framework to catch and gracefully handle
            # errors, ideally integrating the error catching with Juju's mechanisms.
            raise TooManyRelatedAppsError(relation_name, num_related, 1)


class BindingMapping(Mapping[str, 'Binding']):
    """Mapping of endpoints to network bindings.

    Charm authors should not instantiate this directly, but access it via
    :meth:`Model.get_binding`
    """

    def __init__(self, backend: '_ModelBackend'):
        self._backend = backend
        self._data: _BindingDictType = {}

    def get(self, binding_key: Union[str, 'Relation']) -> 'Binding':
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

    # implemented to satisfy the Mapping ABC, but not meant to be used.
    def __getitem__(self, item: Union[str, 'Relation']) -> 'Binding':
        raise NotImplementedError()

    def __iter__(self) -> Iterable['Binding']:
        raise NotImplementedError()

    def __len__(self) -> int:
        raise NotImplementedError()


class Binding:
    """Binding to a network space."""

    name: str
    """The name of the endpoint this binding represents (eg, 'db')."""

    def __init__(self, name: str, relation_id: Optional[int], backend: '_ModelBackend'):
        self.name = name
        self._relation_id = relation_id
        self._backend = backend
        self._network = None

    def _network_get(self, name: str, relation_id: Optional[int] = None) -> 'Network':
        return Network(self._backend.network_get(name, relation_id))

    @property
    def network(self) -> 'Network':
        """The network information for this binding."""
        if self._network is None:
            try:
                self._network = self._network_get(self.name, self._relation_id)
            except RelationNotFoundError:
                if self._relation_id is None:
                    raise
                # If a relation is dead, we can still get network info associated with an
                # endpoint itself
                self._network = self._network_get(self.name)
        return self._network


def _cast_network_address(raw: str) -> Union[ipaddress.IPv4Address, ipaddress.IPv6Address, str]:
    # fields marked as network addresses need not be IPs; they could be
    # hostnames that juju failed to resolve. In that case, we'll log a
    # debug message and leave it as-is.
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        logger.debug(f"could not cast {raw} to IPv4/v6 address")
        return raw


class Network:
    """Network space details.

    Charm authors should not instantiate this directly, but should get access to the Network
    definition from :meth:`Model.get_binding` and its :code:`network` attribute.
    """

    interfaces: List['NetworkInterface']
    """A list of network interface details. This includes the information
    about how the application should be configured (for example, what IP
    addresses should be bound to).

    Multiple addresses for a single interface are represented as multiple
    interfaces, for example::

        [NetworkInfo('ens1', '10.1.1.1/32'), NetworkInfo('ens1', '10.1.2.1/32'])
    """

    ingress_addresses: List[Union[ipaddress.IPv4Address, ipaddress.IPv6Address, str]]
    """A list of IP addresses that other units should use to get in touch with the charm."""

    egress_subnets: List[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]
    """A list of networks representing the subnets that other units will see
    the charm connecting from. Due to things like NAT it isn't always possible to
    narrow it down to a single address, but when it is clear, the CIDRs will
    be constrained to a single address (for example, 10.0.0.1/32).
    """

    def __init__(self, network_info: '_NetworkDict'):
        """Initialize a Network instance.

        Args:
            network_info: A dict of network information as returned by ``network-get``.
        """
        self.interfaces = []
        # Treat multiple addresses on an interface as multiple logical
        # interfaces with the same name.
        for interface_info in network_info.get('bind-addresses', []):
            interface_name: str = interface_info.get('interface-name')
            addrs: Optional[List[_AddressDict]] = interface_info.get('addresses')
            if addrs is not None:
                for address_info in addrs:
                    self.interfaces.append(NetworkInterface(interface_name, address_info))

        self.ingress_addresses = []
        for address in network_info.get('ingress-addresses', []):
            self.ingress_addresses.append(_cast_network_address(address))

        self.egress_subnets = []
        for subnet in network_info.get('egress-subnets', []):
            self.egress_subnets.append(ipaddress.ip_network(subnet))

    @property
    def bind_address(self) -> Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address, str]]:
        """A single address that the charm's application should bind() to.

        For the common case where there is a single answer. This represents a single
        address from :attr:`.interfaces` that can be used to configure where the charm's
        application should bind() and listen().
        """
        if self.interfaces:
            return self.interfaces[0].address
        else:
            return None

    @property
    def ingress_address(self) -> Optional[
            Union[ipaddress.IPv4Address, ipaddress.IPv6Address, str]]:
        """The address other applications should use to connect to the current unit.

        Due to things like public/private addresses, NAT and tunneling, the address the charm
        will bind() to is not always the address other people can use to connect() to the
        charm. This is just the first address from :attr:`.ingress_addresses`.
        """
        if self.ingress_addresses:
            return self.ingress_addresses[0]
        else:
            return None


class NetworkInterface:
    """Represents a single network interface that the charm needs to know about.

    Charmers should not instantiate this type directly. Instead use :meth:`Model.get_binding`
    to get the network information for a given endpoint.
    """

    name: str
    """The name of the interface (for example, 'eth0' or 'ens1')."""

    address: Optional[Union[ipaddress.IPv4Address, ipaddress.IPv6Address, str]]
    """The address of the network interface."""

    subnet: Optional[Union[ipaddress.IPv4Network, ipaddress.IPv6Network]]
    """The subnet of the network interface. This may be a single address
    (for example, '10.0.1.2/32').
    """

    def __init__(self, name: str, address_info: '_AddressDict'):
        self.name = name
        # TODO: expose a hardware address here, see LP: #1864070.

        address = address_info.get('value')
        if address is None:
            # Compatibility with Juju <2.9: legacy address_info only had
            # an 'address' field instead of 'value'.
            address = address_info.get('address')

        # The value field may be empty.
        address_ = _cast_network_address(address) if address else None
        self.address = address_
        cidr: str = address_info.get('cidr')
        # The cidr field may be empty, see LP: #1864102.
        if cidr:
            subnet = ipaddress.ip_network(cidr)
        elif address:
            # If we have an address, convert it to a /32 or /128 IP network.
            subnet = ipaddress.ip_network(address)
        else:
            subnet = None
        self.subnet = subnet
        # TODO: expose a hostname/canonical name for the address here, see LP: #1864086.


class SecretRotate(enum.Enum):
    """Secret rotation policies."""

    NEVER = 'never'  # the default in juju
    HOURLY = 'hourly'
    DAILY = 'daily'
    WEEKLY = 'weekly'
    MONTHLY = 'monthly'
    QUARTERLY = 'quarterly'
    YEARLY = 'yearly'


class SecretInfo:
    """Secret information (metadata)."""

    def __init__(self,
                 id: str,
                 label: Optional[str],
                 revision: int,
                 expires: Optional[datetime.datetime],
                 rotation: Optional[SecretRotate],
                 rotates: Optional[datetime.datetime]):
        self.id = Secret._canonicalize_id(id)
        self.label = label
        self.revision = revision
        self.expires = expires
        self.rotation = rotation
        self.rotates = rotates

    @classmethod
    def from_dict(cls, id: str, d: Dict[str, Any]) -> 'SecretInfo':
        """Create new SecretInfo object from ID and dict parsed from JSON."""
        expires = typing.cast(Optional[str], d.get('expires'))
        try:
            rotation = SecretRotate(typing.cast(Optional[str], d.get('rotation')))
        except ValueError:
            rotation = None
        rotates = typing.cast(Optional[str], d.get('rotates'))
        return cls(
            id=id,
            label=typing.cast(Optional[str], d.get('label')),
            revision=typing.cast(int, d['revision']),
            expires=timeconv.parse_rfc3339(expires) if expires is not None else None,
            rotation=rotation,
            rotates=timeconv.parse_rfc3339(rotates) if rotates is not None else None,
        )

    def __repr__(self):
        return ('SecretInfo('
                'id={self.id!r}, '
                'label={self.label!r}, '
                'revision={self.revision}, '
                'expires={self.expires!r}, '
                'rotation={self.rotation}, '
                'rotates={self.rotates!r})'
                ).format(self=self)


class Secret:
    """Represents a single secret in the model.

    This class should not be instantiated directly, instead use
    :meth:`Model.get_secret` (for observers and owners), or
    :meth:`Application.add_secret` or :meth:`Unit.add_secret` (for owners).

    All secret events have a :code:`.secret` attribute which provides the
    :class:`Secret` associated with that event.
    """

    _key_re = re.compile(r'^([a-z](?:-?[a-z0-9]){2,})$')  # copied from Juju code

    def __init__(self, backend: '_ModelBackend',
                 id: Optional[str] = None,
                 label: Optional[str] = None,
                 content: Optional[Dict[str, str]] = None):
        if not (id or label):
            raise TypeError('Must provide an id or label, or both')
        if id is not None:
            id = self._canonicalize_id(id)
        self._backend = backend
        self._id = id
        self._label = label
        self._content = content

    def __repr__(self):
        fields: List[str] = []
        if self._id is not None:
            fields.append(f'id={self._id!r}')
        if self._label is not None:
            fields.append(f'label={self._label!r}')
        return f"<Secret {' '.join(fields)}>"

    @staticmethod
    def _canonicalize_id(id: str) -> str:
        """Return the canonical form of the given secret ID, with the 'secret:' prefix."""
        id = id.strip()
        if not id.startswith('secret:'):
            id = f"secret:{id}"  # add the prefix if not there already
        return id

    @classmethod
    def _validate_content(cls, content: Optional[Dict[str, str]]):
        """Ensure the given secret content is valid, or raise ValueError."""
        if not isinstance(content, dict):
            raise TypeError(f'Secret content must be a dict, not {type(content).__name__}')
        if not content:
            raise ValueError('Secret content must not be empty')

        invalid_keys: List[str] = []
        invalid_value_keys: List[str] = []
        invalid_value_types: Set[str] = set()
        for k, v in content.items():
            if not cls._key_re.match(k):
                invalid_keys.append(k)
            if not isinstance(v, str):
                invalid_value_keys.append(k)
                invalid_value_types.add(type(v).__name__)

        if invalid_keys:
            raise ValueError(
                f'Invalid secret keys: {invalid_keys}. '
                f'Keys should be lowercase letters and digits, at least 3 characters long, '
                f'start with a letter, and not start or end with a hyphen.')

        if invalid_value_keys:
            invalid_types = ' or '.join(sorted(invalid_value_types))
            raise TypeError(f'Invalid secret values for keys: {invalid_value_keys}. '
                            f'Values should be of type str, not {invalid_types}.')

    @property
    def id(self) -> Optional[str]:
        """Locator ID (URI) for this secret.

        This has an unfortunate name for historical reasons, as it's not
        really a unique identifier, but the secret's locator URI, which may or
        may not include the model UUID (for cross-model secrets).

        Charms should treat this as an opaque string for looking up secrets
        and sharing them via relation data. If a charm-local "name" is needed
        for a secret, use a :attr:`label`. (If a charm needs a truly unique
        identifier for identifying one secret in a set of secrets of arbitrary
        size, use :attr:`unique_identifier` -- this should be rare.)

        This will be None if the secret was obtained using
        :meth:`Model.get_secret` with a label but no ID.
        """
        return self._id

    @property
    def unique_identifier(self) -> Optional[str]:
        """Unique identifier of this secret.

        This is the secret's globally-unique identifier (currently a
        20-character Xid, for example "9m4e2mr0ui3e8a215n4g").

        Charms should use :attr:`id` (the secret's locator ID) to send
        the secret's ID across relation data, and labels (:attr:`label`) to
        assign a charm-local "name" to the secret for lookup in this charm.
        However, ``unique_identifier`` can be useful to distinguish secrets in
        cases where the charm has a set of secrets of arbitrary size, for
        example, a group of 10 or 20 TLS certificates.

        This will be None if the secret was obtained using
        :meth:`Model.get_secret` with a label but no ID.
        """
        if self._id is None:
            return None
        if '/' in self._id:
            return self._id.rsplit('/', 1)[-1]
        elif self._id.startswith('secret:'):
            return self._id[len('secret:'):]
        else:
            # Shouldn't get here as id is canonicalized, but just in case.
            return self._id

    @property
    def label(self) -> Optional[str]:
        """Label used to reference this secret locally.

        This label is effectively a name for the secret that's local to the
        charm, for example "db-password" or "tls-cert". The secret owner sets
        a label with :meth:`Application.add_secret` or :meth:`Unit.add_secret`,
        and the secret observer sets a label with a call to
        :meth:`Model.get_secret`.

        The label property can be used distinguish between multiple secrets
        in event handlers like :class:`ops.SecretChangedEvent <ops.charm.SecretChangedEvent>`.
        For example, if a charm is observing two secrets, it might call
        ``model.get_secret(id=secret_id, label='db-password')`` and
        ``model.get_secret(id=secret_id, label='tls-cert')`` in the relevant
        relation-changed event handlers, and then switch on ``event.secret.label``
        in secret-changed::

            def _on_secret_changed(self, event):
                if event.secret.label == 'db-password':
                    content = event.secret.get_content(refresh=True)
                    self._configure_db_credentials(content['username'], content['password'])
                elif event.secret.label == 'tls-cert':
                    content = event.secret.get_content(refresh=True)
                    self._update_tls_cert(content['cert'])
                else:
                    pass  # ignore other labels (or log a warning)

        Juju will ensure that the entity (the owner or observer) only has one
        secret with this label at once.

        This will be None if the secret was obtained using
        :meth:`Model.get_secret` with an ID but no label.
        """
        return self._label

    def get_content(self, *, refresh: bool = False) -> Dict[str, str]:
        """Get the secret's content.

        Returns:
            A copy of the secret's content dictionary.

        Args:
            refresh: If true, fetch the latest revision's content and tell
                Juju to update to tracking that revision. The default is to
                get the content of the currently-tracked revision.
        """
        if refresh or self._content is None:
            self._content = self._backend.secret_get(
                id=self.id, label=self.label, refresh=refresh)
        return self._content.copy()

    def peek_content(self) -> Dict[str, str]:
        """Get the content of the latest revision of this secret.

        This returns the content of the latest revision without updating the
        tracking.
        """
        return self._backend.secret_get(id=self.id, label=self.label, peek=True)

    def get_info(self) -> SecretInfo:
        """Get this secret's information (metadata).

        Only secret owners can fetch this information.
        """
        return self._backend.secret_info_get(id=self.id, label=self.label)

    def set_content(self, content: Dict[str, str]):
        """Update the content of this secret.

        This will create a new secret revision, and notify all units tracking
        the secret (the "observers") that a new revision is available with a
        :class:`ops.SecretChangedEvent <ops.charm.SecretChangedEvent>`.

        Args:
            content: A key-value mapping containing the payload of the secret,
                for example :code:`{"password": "foo123"}`.
        """
        self._validate_content(content)
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_set(typing.cast(str, self.id), content=content)
        self._content = None  # invalidate cache so it's refetched next get_content()

    def set_info(self, *,
                 label: Optional[str] = None,
                 description: Optional[str] = None,
                 expire: Optional[Union[datetime.datetime, datetime.timedelta]] = None,
                 rotate: Optional[SecretRotate] = None):
        """Update this secret's information (metadata).

        This will not create a new secret revision (that applies only to
        :meth:`set_content`). Once attributes are set, they cannot be unset.

        Args:
            label: New label to apply.
            description: New description to apply.
            expire: New expiration time (or timedelta from now) to apply.
            rotate: New rotation policy to apply. The new policy will take
                effect only after the currently-scheduled rotation.
        """
        if label is None and description is None and expire is None and rotate is None:
            raise TypeError('Must provide a label, description, expiration time, '
                            'or rotation policy')
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_set(typing.cast(str, self.id),
                                 label=label,
                                 description=description,
                                 expire=_calculate_expiry(expire),
                                 rotate=rotate)

    def grant(self, relation: 'Relation', *, unit: Optional[Unit] = None):
        """Grant read access to this secret.

        If the application or unit has already been granted access to this
        secret, do nothing.

        Args:
            relation: The relation used to scope the life of this secret.
            unit: If specified, grant access to only this unit, rather than
                all units in the application.
        """
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_grant(
            typing.cast(str, self.id),
            relation.id,
            unit=unit.name if unit is not None else None)

    def revoke(self, relation: 'Relation', *, unit: Optional[Unit] = None):
        """Revoke read access to this secret.

        If the application or unit does not have access to this secret, do
        nothing.

        Args:
            relation: The relation used to scope the life of this secret.
            unit: If specified, revoke access to only this unit, rather than
                all units in the application.
        """
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_revoke(
            typing.cast(str, self.id),
            relation.id,
            unit=unit.name if unit is not None else None)

    def remove_revision(self, revision: int):
        """Remove the given secret revision.

        This is normally called when handling
        :class:`ops.SecretRemoveEvent <ops.charm.SecretRemoveEvent>` or
        :class:`ops.SecretExpiredEvent <ops.charm.SecretExpiredEvent>`.

        Args:
            revision: The secret revision to remove. If being called from a
                secret event, this should usually be set to
                :attr:`SecretRemoveEvent.revision`.
        """
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_remove(typing.cast(str, self.id), revision=revision)

    def remove_all_revisions(self) -> None:
        """Remove all revisions of this secret.

        This is called when the secret is no longer needed, for example when
        handling :class:`ops.RelationBrokenEvent <ops.charm.RelationBrokenEvent>`.
        """
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_remove(typing.cast(str, self.id))


class Relation:
    """Represents an established relation between this application and another application.

    This class should not be instantiated directly, instead use :meth:`Model.get_relation`,
    :attr:`Model.relations`, or :attr:`ops.RelationEvent.relation`. This is principally used by
    :class:`ops.RelationMeta` to represent the relationships between charms.
    """

    name: str
    """The name of the local endpoint of the relation (for example, 'db')."""

    id: int
    """The identifier for a particular relation."""

    app: Optional[Application]
    """Represents the remote application of this relation.

    For peer relations, this will be the local application.
    """

    units: Set[Unit]
    """A set of units that have started and joined this relation.

    For subordinate relations, this set will include only one unit: the principal unit.
    """

    data: 'RelationData'
    """Holds the data buckets for each entity of a relation.

    This is accessed using, for example, ``Relation.data[unit]['foo']``.
    """

    def __init__(
            self, relation_name: str, relation_id: int, is_peer: bool, our_unit: Unit,
            backend: '_ModelBackend', cache: '_ModelCache'):
        self.name = relation_name
        self.id = relation_id
        self.app: Optional[Application] = None
        self.units: Set[Unit] = set()

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
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}:{self.id}>'


class RelationData(Mapping[Union['Unit', 'Application'], 'RelationDataContent']):
    """Represents the various data buckets of a given relation.

    Each unit and application involved in a relation has their own data bucket.
    For example, ``{entity: RelationDataContent}``,
    where entity can be either a :class:`Unit` or an :class:`Application`.

    Units can read and write their own data, and if they are the leader,
    they can read and write their application data. They are allowed to read
    remote unit and application data.

    This class should not be instantiated directly, instead use
    :attr:`Relation.data`
    """

    def __init__(self, relation: Relation, our_unit: Unit, backend: '_ModelBackend'):
        self.relation = weakref.proxy(relation)
        self._data: Dict[Union['Unit', 'Application'], RelationDataContent] = {
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

    def __contains__(self, key: Union['Unit', 'Application']):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key: Union['Unit', 'Application']):
        if key is None and self.relation.app is None:
            # NOTE: if juju gets fixed to set JUJU_REMOTE_APP for relation-broken events, then that
            # should fix the only case in which we expect key to be None - potentially removing the
            # need for this error in future ops versions (i.e. if relation.app is guaranteed to not
            # be None. See https://bugs.launchpad.net/juju/+bug/1960934.
            raise KeyError(
                'Cannot index relation data with "None".'
                ' Are you trying to access remote app data during a relation-broken event?'
                ' This is not allowed.')
        return self._data[key]

    def __repr__(self):
        return repr(self._data)


# We mix in MutableMapping here to get some convenience implementations, but whether it's actually
# mutable or not is controlled by the flag.
class RelationDataContent(LazyMapping, MutableMapping[str, str]):
    """Data content of a unit or application in a relation."""

    def __init__(self, relation: 'Relation', entity: Union['Unit', 'Application'],
                 backend: '_ModelBackend'):
        self.relation = relation
        self._entity = entity
        self._backend = backend
        self._is_app: bool = isinstance(entity, Application)

    @property
    def _hook_is_running(self) -> bool:
        # this flag controls whether the access we have to RelationDataContent
        # is 'strict' aka the same as a deployed charm would have, or whether it is
        # unrestricted, allowing test code to read/write databags at will.
        return bool(self._backend._hook_is_running)

    def _load(self) -> '_RelationDataContent_Raw':
        """Load the data from the current entity / relation."""
        try:
            return self._backend.relation_get(self.relation.id, self._entity.name, self._is_app)
        except RelationNotFoundError:
            # Dead relations tell no tales (and have no data).
            return {}

    def _validate_read(self):
        """Return if the data content can be read."""
        # if we're not in production (we're testing): we skip access control rules
        if not self._hook_is_running:
            return

        # Only remote units (and the leader unit) can read *this* app databag.

        # is this an app databag?
        if not self._is_app:
            # all unit databags are publicly readable
            return

        # Am I leader?
        if self._backend.is_leader():
            # leaders have no read restrictions
            return

        # type guard; we should not be accessing relation data
        # if the remote app does not exist.
        app = self.relation.app
        if app is None:
            raise RelationDataAccessError(
                f"Remote application instance cannot be retrieved for {self.relation}."
            )

        # is this a peer relation?
        if app.name == self._entity.name:
            # peer relation data is always publicly readable
            return

        # if we're here it means: this is not a peer relation,
        # this is an app databag, and we don't have leadership.

        # is this a LOCAL app databag?
        if self._backend.app_name == self._entity.name:
            # minions can't read local app databags
            raise RelationDataAccessError(
                "{} is not leader and cannot read its own application databag".format(
                    self._backend.unit_name
                )
            )

        return True

    def _validate_write(self, key: str, value: str):
        """Validate writing key:value to this databag.

        1) that key: value is a valid str:str pair
        2) that we have write access to this databag
        """
        # firstly, we validate WHAT we're trying to write.
        # this is independent of whether we're in testing code or production.
        if not isinstance(key, str):
            raise RelationDataTypeError(
                f'relation data keys must be strings, not {type(key)}')
        if not isinstance(value, str):
            raise RelationDataTypeError(
                f'relation data values must be strings, not {type(value)}')

        # if we're not in production (we're testing): we skip access control rules
        if not self._hook_is_running:
            return

        # finally, we check whether we have permissions to write this databag
        if self._is_app:
            is_our_app: bool = self._backend.app_name == self._entity.name
            if not is_our_app:
                raise RelationDataAccessError(
                    "{} cannot write the data of remote application {}".format(
                        self._backend.app_name, self._entity.name
                    ))
            # Whether the application data bag is mutable or not depends on
            # whether this unit is a leader or not, but this is not guaranteed
            # to be always true during the same hook execution.
            if self._backend.is_leader():
                return  # all good
            raise RelationDataAccessError(
                f"{self._backend.unit_name} is not leader and cannot write application data."
            )
        else:
            # we are attempting to write a unit databag
            # is it OUR UNIT's?
            if self._backend.unit_name != self._entity.name:
                raise RelationDataAccessError(
                    "{} cannot write databag of {}: not the same unit.".format(
                        self._backend.unit_name, self._entity.name
                    )
                )

    def __setitem__(self, key: str, value: str):
        self._validate_write(key, value)
        self._commit(key, value)
        self._update(key, value)

    def _commit(self, key: str, value: str):
        self._backend.update_relation_data(self.relation.id, self._entity, key, value)

    def _update(self, key: str, value: str):
        """Cache key:value in our local lazy data."""
        # Don't load data unnecessarily if we're only updating.
        if self._lazy_data is not None:
            if value == '':
                # Match the behavior of Juju, which is that setting the value to an
                # empty string will remove the key entirely from the relation data.
                self._data.pop(key, None)
            else:
                self._data[key] = value

    def __getitem__(self, key: str) -> str:
        self._validate_read()
        return super().__getitem__(key)

    def __delitem__(self, key: str):
        self._validate_write(key, '')
        # Match the behavior of Juju, which is that setting the value to an empty
        # string will remove the key entirely from the relation data.
        self.__setitem__(key, '')

    def __repr__(self):
        try:
            self._validate_read()
        except RelationDataAccessError:
            return '<n/a>'
        return super().__repr__()


class ConfigData(LazyMapping):
    """Configuration data.

    This class should not be instantiated directly. It should be accessed via :attr:`Model.config`.
    """

    def __init__(self, backend: '_ModelBackend'):
        self._backend = backend

    def _load(self):
        return self._backend.config_get()


class StatusBase:
    """Status values specific to applications and units.

    To access a status by name, use :meth:`StatusBase.from_name`. However, most use cases will
    directly use the child class such as :class:`ActiveStatus` to indicate their status.
    """

    _statuses: Dict[str, Type['StatusBase']] = {}

    # Subclasses should override this attribute
    name = ''

    def __init__(self, message: str = ''):
        if self.__class__ is StatusBase:
            raise TypeError("cannot instantiate a base class")
        self.message = message

    def __eq__(self, other: 'StatusBase') -> bool:
        if not isinstance(self, type(other)):
            return False
        return self.message == other.message

    def __repr__(self):
        return f"{self.__class__.__name__}({self.message!r})"

    @classmethod
    def from_name(cls, name: str, message: str):
        """Create a status instance from a name and message.

        If ``name`` is "unknown", ``message`` is ignored, because unknown status
        does not have an associated message.

        Args:
            name: Name of the status, for example "active" or "blocked".
            message: Message to include with the status.

        Raises:
            KeyError: If ``name`` is not a registered status.
        """
        if name == 'unknown':
            # unknown is special
            return UnknownStatus()
        else:
            return cls._statuses[name](message)

    @classmethod
    def register(cls, child: Type['StatusBase']):
        """Register a Status for the child's name."""
        if not isinstance(getattr(child, 'name'), str):
            raise TypeError(f"Can't register StatusBase subclass {child}: ",
                            "missing required `name: str` class attribute")
        cls._statuses[child.name] = child
        return child

    _priorities = {
        'error': 5,
        'blocked': 4,
        'maintenance': 3,
        'waiting': 2,
        'active': 1,
        # 'unknown' or any other status is handled below
    }

    @classmethod
    def _get_highest_priority(cls, statuses: 'List[StatusBase]') -> 'StatusBase':
        """Return the highest-priority status from a list of statuses.

        If there are multiple highest-priority statuses, return the first one.
        """
        return max(statuses, key=lambda status: cls._priorities.get(status.name, 0))


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
class ErrorStatus(StatusBase):
    """The unit status is error.

    The unit-agent has encountered an error (the application or unit requires
    human intervention in order to operate correctly).
    """
    name = 'error'


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

    An admin has to manually intervene to unblock the unit and let it proceed.
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

    def __init__(self, names: Iterable[str], backend: '_ModelBackend'):
        self._backend = backend
        self._paths: Dict[str, Optional[Path]] = {name: None for name in names}

    def fetch(self, name: str) -> Path:
        """Fetch the resource from the controller or store.

        If successfully fetched, this returns the path where the resource is stored
        on disk, otherwise it raises a :class:`NameError`.

        Raises:
            NameError: if the resource's path cannot be fetched.
        """
        if name not in self._paths:
            raise NameError(f'invalid resource name: {name}')
        if self._paths[name] is None:
            self._paths[name] = Path(self._backend.resource_get(name))
        return typing.cast(Path, self._paths[name])


class Pod:
    """Represents the definition of a pod spec in legacy Kubernetes models.

    DEPRECATED: New charms should use the sidecar pattern with Pebble.

    Currently only supports simple access to setting the Juju pod spec via
    :attr:`.set_spec`.
    """

    def __init__(self, backend: '_ModelBackend'):
        self._backend = backend

    def set_spec(self, spec: 'K8sSpec', k8s_resources: Optional['K8sSpec'] = None):
        """Set the specification for pods that Juju should start in kubernetes.

        See ``juju help-tool pod-spec-set`` for details of what should be passed.

        Args:
            spec: The mapping defining the pod specification
            k8s_resources: Additional kubernetes specific specification.
        """
        if not self._backend.is_leader():
            raise ModelError('cannot set a pod spec as this unit is not a leader')
        self._backend.pod_spec_set(spec, k8s_resources)


class StorageMapping(Mapping[str, List['Storage']]):
    """Map of storage names to lists of Storage instances."""

    def __init__(self, storage_names: Iterable[str], backend: '_ModelBackend'):
        self._backend = backend
        self._storage_map: _StorageDictType = {storage_name: None
                                               for storage_name in storage_names}

    def __contains__(self, key: str):  # pyright: ignore[reportIncompatibleMethodOverride]
        return key in self._storage_map

    def __len__(self):
        return len(self._storage_map)

    def __iter__(self):
        return iter(self._storage_map)

    def __getitem__(self, storage_name: str) -> List['Storage']:
        if storage_name not in self._storage_map:
            meant = ', or '.join(repr(k) for k in self._storage_map.keys())
            raise KeyError(
                f'Storage {storage_name!r} not found. Did you mean {meant}?')
        storage_list = self._storage_map[storage_name]
        if storage_list is None:
            storage_list = self._storage_map[storage_name] = []
            for storage_index in self._backend.storage_list(storage_name):
                storage = Storage(storage_name, storage_index, self._backend)
                storage_list.append(storage)  # type: ignore
        return storage_list

    def request(self, storage_name: str, count: int = 1):
        """Requests new storage instances of a given name.

        Uses storage-add tool to request additional storage. Juju will notify the unit
        via ``<storage-name>-storage-attached`` events when it becomes available.

        Raises:
            ModelError: if the storage is not in the charm's metadata.
        """
        if storage_name not in self._storage_map:
            raise ModelError(('cannot add storage {!r}:'
                              ' it is not present in the charm metadata').format(storage_name))
        self._backend.storage_add(storage_name, count)

    def _invalidate(self, storage_name: str):
        """Remove an entry from the storage map.

        Not meant to be used by charm authors -- this exists mainly for testing purposes.
        """
        self._storage_map[storage_name] = None


class Storage:
    """Represents a storage as defined in ``metadata.yaml``."""

    name: str
    """Name of the storage."""

    def __init__(self, storage_name: str, storage_index: int, backend: '_ModelBackend'):
        self.name = storage_name
        self._index = storage_index
        self._backend = backend
        self._location = None

    @property
    def index(self) -> int:
        """Index associated with the storage (usually 0 for singular storage)."""
        return self._index

    @property
    def id(self) -> int:
        """DEPRECATED. Use :attr:`Storage.index` instead."""
        logger.warning("model.Storage.id is being replaced - please use model.Storage.index")
        return self.index

    @property
    def full_id(self) -> str:
        """Canonical storage name with index, for example "bigdisk/0"."""
        return f'{self.name}/{self._index}'

    @property
    def location(self) -> Path:
        """Location of the storage."""
        if self._location is None:
            raw = self._backend.storage_get(self.full_id, "location")
            self._location = Path(raw)
        return self._location

    @location.setter
    def location(self, location: str) -> None:
        """Sets the location for use in events.

        For :class:`StorageAttachedEvent` and :class:`StorageDetachingEvent` in case
        the actual details are gone from Juju by the time of a dynamic lookup.
        """
        self._location = Path(location)


class MultiPushPullError(Exception):
    """Aggregates multiple push and pull exceptions into one.

    This class should not be instantiated directly. It is raised by
    :meth:`Container.push_path` and :meth:`Container.pull_path`.
    """

    message: str
    """The error message."""

    errors: List[Tuple[str, Exception]]
    """The list of errors.

    Each error is represented by a tuple of (<source_path>, <exception>),
    where source_path is the path being pushed to or pulled from.
    """

    def __init__(self, message: str, errors: List[Tuple[str, Exception]]):
        self.message = message
        self.errors = errors

    def __str__(self):
        return f'{self.message} ({len(self.errors)} errors): {self.errors[0][1]}, ...'

    def __repr__(self):
        return f'MultiPushPullError({self.message!r}, {len(self.errors)} errors)'


class Container:
    """Represents a named container in a unit.

    This class should not be instantiated directly, instead use :meth:`Unit.get_container`
    or :attr:`Unit.containers`.

    For methods that make changes to the container, if the change fails or times out, then a
    :class:`ops.pebble.ChangeError` or :class:`ops.pebble.TimeoutError` will be raised.

    Interactions with the container use Pebble, so all methods may raise exceptions when there are
    problems communicating with Pebble. Problems connecting to or transferring data with Pebble
    will raise a :class:`ops.pebble.ConnectionError` - generally you can guard against these by
    first checking :meth:`can_connect`, but it is possible for problems to occur after
    :meth:`can_connect` has succeeded. When an error occurs executing the request, such as trying
    to add an invalid layer or execute a command that does not exist, an
    :class:`ops.pebble.APIError` is raised.
    """

    name: str
    """The name of the container from ``metadata.yaml``, for example "postgres"."""

    def __init__(self, name: str, backend: '_ModelBackend',
                 pebble_client: Optional[pebble.Client] = None):
        self.name = name

        if pebble_client is None:
            socket_path = f'/charm/containers/{name}/pebble.socket'
            pebble_client = backend.get_pebble(socket_path)
        self._pebble: pebble.Client = pebble_client

    def can_connect(self) -> bool:
        """Report whether the Pebble API is reachable in the container.

        This method returns a bool that indicates whether the Pebble API is available at
        the time the method is called. It does not guard against the Pebble API becoming
        unavailable, and should be treated as a "point in time" status only.

        For example::

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
            self._pebble.get_system_info()
        except pebble.ConnectionError as e:
            logger.debug("Pebble API is not ready; ConnectionError: %s", e)
            return False
        except FileNotFoundError as e:
            # In some cases, charm authors can attempt to hit the Pebble API before it has had the
            # chance to create the UNIX socket in the shared volume.
            logger.debug("Pebble API is not ready; UNIX socket not found: %s", e)
            return False
        except pebble.APIError as e:
            # An API error is only raised when the Pebble API returns invalid JSON, or the response
            # cannot be read. Both of these are a likely indicator that something is wrong.
            logger.warning("Pebble API is not ready; APIError: %s", e)
            return False
        return True

    def autostart(self) -> None:
        """Autostart all services marked as ``startup: enabled``."""
        self._pebble.autostart_services()

    def replan(self) -> None:
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
            stop: Tuple[str, ...] = tuple(s.name for s in self.get_services(
                *service_names).values() if s.is_running())
            if stop:
                self._pebble.stop_services(stop)
            self._pebble.start_services(service_names)

    def stop(self, *service_names: str):
        """Stop given service(s) by name."""
        if not service_names:
            raise TypeError('stop expected at least 1 argument, got 0')

        self._pebble.stop_services(service_names)

    def add_layer(self, label: str, layer: Union[str, pebble.LayerDict, pebble.Layer], *,
                  combine: bool = False):
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

    def get_plan(self) -> pebble.Plan:
        """Get the combined Pebble configuration.

        This will immediately reflect changes from any previous
        :meth:`add_layer` calls, regardless of whether :meth:`replan` or
        :meth:`restart` have been called.
        """
        return self._pebble.get_plan()

    def get_services(self, *service_names: str) -> Mapping[str, 'pebble.ServiceInfo']:
        """Fetch and return a mapping of status information indexed by service name.

        If no service names are specified, return status information for all
        services, otherwise return information for only the given services.
        """
        names = service_names or None
        services = self._pebble.get_services(names)
        return ServiceInfoMapping(services)

    def get_service(self, service_name: str) -> pebble.ServiceInfo:
        """Get status information for a single named service.

        Raises:
            ModelError: if service_name is not found.
        """
        services = self.get_services(service_name)
        if not services:
            raise ModelError(f'service {service_name!r} not found')
        if len(services) > 1:
            raise RuntimeError(f'expected 1 service, got {len(services)}')
        return services[service_name]

    def get_checks(
            self,
            *check_names: str,
            level: Optional[pebble.CheckLevel] = None) -> 'CheckInfoMapping':
        """Fetch and return a mapping of check information indexed by check name.

        Args:
            check_names: Optional check names to query for. If no check names
                are specified, return checks with any name.
            level: Optional check level to query for. If not specified, fetch
                all checks.
        """
        checks = self._pebble.get_checks(names=check_names or None, level=level)
        return CheckInfoMapping(checks)

    def get_check(self, check_name: str) -> pebble.CheckInfo:
        """Get check information for a single named check.

        Raises:
            ModelError: if ``check_name`` is not found.
        """
        checks = self.get_checks(check_name)
        if not checks:
            raise ModelError(f'check {check_name!r} not found')
        if len(checks) > 1:
            raise RuntimeError(f'expected 1 check, got {len(checks)}')
        return checks[check_name]

    @typing.overload
    def pull(self, path: Union[str, PurePath], *, encoding: None) -> BinaryIO:  # noqa
        ...

    @typing.overload
    def pull(self, path: Union[str, PurePath], *, encoding: str = 'utf-8') -> TextIO:  # noqa
        ...

    def pull(self, path: Union[str, PurePath], *,
             encoding: Optional[str] = 'utf-8') -> Union[BinaryIO, TextIO]:
        """Read a file's content from the remote system.

        Args:
            path: Path of the file to read from the remote system.
            encoding: Encoding to use for decoding the file's bytes to string,
                or ``None`` to specify no decoding.

        Returns:
            A readable file-like object, whose ``read()`` method will return
            strings decoded according to the specified encoding, or bytes if
            encoding is ``None``.

        Raises:
            pebble.PathError: If there was an error reading the file at path,
                for example, if the file doesn't exist or is a directory.
        """
        return self._pebble.pull(str(path), encoding=encoding)

    def push(self,
             path: Union[str, PurePath],
             source: Union[bytes, str, BinaryIO, TextIO],
             *,
             encoding: str = 'utf-8',
             make_dirs: bool = False,
             permissions: Optional[int] = None,
             user_id: Optional[int] = None,
             user: Optional[str] = None,
             group_id: Optional[int] = None,
             group: Optional[str] = None):
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
        self._pebble.push(str(path), source, encoding=encoding,
                          make_dirs=make_dirs,
                          permissions=permissions,
                          user_id=user_id, user=user,
                          group_id=group_id, group=group)

    def list_files(self, path: Union[str, PurePath], *, pattern: Optional[str] = None,
                   itself: bool = False) -> List[pebble.FileInfo]:
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
        return self._pebble.list_files(str(path),
                                       pattern=pattern, itself=itself)

    def push_path(self,
                  source_path: Union[str, Path, Iterable[Union[str, Path]]],
                  dest_dir: Union[str, PurePath]):
        """Recursively push a local path or files to the remote system.

        Only regular files and directories are copied; symbolic links, device files, etc. are
        skipped.  Pushing is attempted to completion even if errors occur during the process.  All
        errors are collected incrementally. After copying has completed, if any errors occurred, a
        single :class:`MultiPushPullError` is raised containing details for each error.

        Assuming the following files exist locally:

        * /foo/bar/baz.txt
        * /foo/foobar.txt
        * /quux.txt

        These are various push examples::

            # copy one file
            container.push_path('/foo/foobar.txt', '/dst')
            # Destination results: /dst/foobar.txt

            # copy a directory
            container.push_path('/foo', '/dst')
            # Destination results: /dst/foo/bar/baz.txt, /dst/foo/foobar.txt

            # copy a directory's contents
            container.push_path('/foo/*', '/dst')
            # Destination results: /dst/bar/baz.txt, /dst/foobar.txt

            # copy multiple files
            container.push_path(['/foo/bar/baz.txt', 'quux.txt'], '/dst')
            # Destination results: /dst/baz.txt, /dst/quux.txt

            # copy a file and a directory
            container.push_path(['/foo/bar', '/quux.txt'], '/dst')
            # Destination results: /dst/bar/baz.txt, /dst/quux.txt

        Args:
            source_path: A single path or list of paths to push to the remote
                system. The paths can be either a file or a directory. If
                ``source_path`` is a directory, the directory base name is
                attached to the destination directory -- that is, the source
                path directory is placed inside the destination directory. If
                a source path ends with a trailing ``/*`` it will have its
                *contents* placed inside the destination directory.
            dest_dir: Remote destination directory inside which the source
                dir/files will be placed. This must be an absolute path.
        """
        if hasattr(source_path, '__iter__') and not isinstance(source_path, str):
            source_paths = typing.cast(Iterable[Union[str, Path]], source_path)
        else:
            source_paths = typing.cast(Iterable[Union[str, Path]], [source_path])
        source_paths = [Path(p) for p in source_paths]
        dest_dir = Path(dest_dir)

        def local_list(source_path: Path) -> List[pebble.FileInfo]:
            paths = source_path.iterdir() if source_path.is_dir() else [source_path]
            files = [self._build_fileinfo(f) for f in paths]
            return files

        errors: List[Tuple[str, Exception]] = []
        for source_path in source_paths:
            try:
                for info in Container._list_recursive(local_list, source_path):
                    dstpath = self._build_destpath(info.path, source_path, dest_dir)
                    if info.type is pebble.FileType.DIRECTORY:
                        self.make_dir(dstpath, make_parents=True)
                        continue
                    with open(info.path) as src:
                        self.push(
                            dstpath,
                            src,
                            make_dirs=True,
                            permissions=info.permissions,
                            user_id=info.user_id,
                            user=info.user,
                            group_id=info.group_id,
                            group=info.group)
            except (OSError, pebble.Error) as err:
                errors.append((str(source_path), err))
        if errors:
            raise MultiPushPullError('failed to push one or more files', errors)

    def pull_path(self,
                  source_path: Union[str, PurePath, Iterable[Union[str, PurePath]]],
                  dest_dir: Union[str, Path]):
        """Recursively pull a remote path or files to the local system.

        Only regular files and directories are copied; symbolic links, device files, etc. are
        skipped.  Pulling is attempted to completion even if errors occur during the process.  All
        errors are collected incrementally. After copying has completed, if any errors occurred, a
        single :class:`MultiPushPullError` is raised containing details for each error.

        Assuming the following files exist remotely:

        * /foo/bar/baz.txt
        * /foo/foobar.txt
        * /quux.txt

        These are various pull examples::

            # copy one file
            container.pull_path('/foo/foobar.txt', '/dst')
            # Destination results: /dst/foobar.txt

            # copy a directory
            container.pull_path('/foo', '/dst')
            # Destination results: /dst/foo/bar/baz.txt, /dst/foo/foobar.txt

            # copy a directory's contents
            container.pull_path('/foo/*', '/dst')
            # Destination results: /dst/bar/baz.txt, /dst/foobar.txt

            # copy multiple files
            container.pull_path(['/foo/bar/baz.txt', 'quux.txt'], '/dst')
            # Destination results: /dst/baz.txt, /dst/quux.txt

            # copy a file and a directory
            container.pull_path(['/foo/bar', '/quux.txt'], '/dst')
            # Destination results: /dst/bar/baz.txt, /dst/quux.txt

        Args:
            source_path: A single path or list of paths to pull from the
                remote system. The paths can be either a file or a directory
                but must be absolute paths. If ``source_path`` is a directory,
                the directory base name is attached to the destination
                directory -- that is, the source path directory is placed
                inside the destination directory. If a source path ends with a
                trailing ``/*`` it will have its *contents* placed inside the
                destination directory.
            dest_dir: Local destination directory inside which the source
                dir/files will be placed.
        """
        if hasattr(source_path, '__iter__') and not isinstance(source_path, str):
            source_paths = typing.cast(Iterable[Union[str, Path]], source_path)
        else:
            source_paths = typing.cast(Iterable[Union[str, Path]], [source_path])
        source_paths = [Path(p) for p in source_paths]
        dest_dir = Path(dest_dir)

        errors: List[Tuple[str, Exception]] = []
        for source_path in source_paths:
            try:
                for info in Container._list_recursive(self.list_files, source_path):
                    dstpath = self._build_destpath(info.path, source_path, dest_dir)
                    if info.type is pebble.FileType.DIRECTORY:
                        dstpath.mkdir(parents=True, exist_ok=True)
                        continue
                    dstpath.parent.mkdir(parents=True, exist_ok=True)
                    with self.pull(info.path, encoding=None) as src:
                        with dstpath.open(mode='wb') as dst:
                            shutil.copyfileobj(src, dst)
            except (OSError, pebble.Error) as err:
                errors.append((str(source_path), err))
        if errors:
            raise MultiPushPullError('failed to pull one or more files', errors)

    @staticmethod
    def _build_fileinfo(path: Union[str, Path]) -> pebble.FileInfo:
        """Constructs a FileInfo object by stat'ing a local path."""
        path = Path(path)
        if path.is_symlink():
            ftype = pebble.FileType.SYMLINK
        elif path.is_dir():
            ftype = pebble.FileType.DIRECTORY
        elif path.is_file():
            ftype = pebble.FileType.FILE
        else:
            ftype = pebble.FileType.UNKNOWN

        import grp
        import pwd
        info = path.lstat()
        try:
            pw_name = pwd.getpwuid(info.st_uid).pw_name
        except KeyError:
            logger.warning("Could not get name for user %s", info.st_uid)
            pw_name = None
        try:
            gr_name = grp.getgrgid(info.st_gid).gr_name
        except KeyError:
            logger.warning("Could not get name for group %s", info.st_gid)
            gr_name = None
        return pebble.FileInfo(
            path=str(path),
            name=path.name,
            type=ftype,
            size=info.st_size,
            permissions=stat.S_IMODE(info.st_mode),
            last_modified=datetime.datetime.fromtimestamp(info.st_mtime),
            user_id=info.st_uid,
            user=pw_name,
            group_id=info.st_gid,
            group=gr_name)

    @staticmethod
    def _list_recursive(list_func: Callable[[Path], Iterable[pebble.FileInfo]],
                        path: Path) -> Generator[pebble.FileInfo, None, None]:
        """Recursively lists all files under path using the given list_func.

        Args:
            list_func: Function taking 1 Path argument that returns a list of FileInfo objects
                representing files residing directly inside the given path.
            path: Filepath to recursively list.
        """
        if path.name == '*':
            # ignore trailing '/*' that we just use for determining how to build paths
            # at destination
            path = path.parent

        for info in list_func(path):
            if info.type is pebble.FileType.DIRECTORY:
                # Yield the directory to ensure empty directories are created, then
                # all of the contained files.
                yield info
                yield from Container._list_recursive(list_func, Path(info.path))
            elif info.type in (pebble.FileType.FILE, pebble.FileType.SYMLINK):
                yield info
            else:
                logger.debug(
                    'skipped unsupported file in Container.[push/pull]_path: %s', info.path)

    @staticmethod
    def _build_destpath(
            file_path: Union[str, Path],
            source_path: Union[str, Path],
            dest_dir: Union[str, Path]) -> Path:
        """Converts a source file and destination dir into a full destination filepath.

        file_path:
            Full source-side path for the file being copied to dest_dir.
        source_path
            Source prefix under which the given file_path was found.
        dest_dir
            Destination directory to place file_path into.
        """
        # select between the two following src+dst combos via trailing '/*'
        # /src/* --> /dst/*
        # /src --> /dst/src
        file_path, source_path, dest_dir = Path(file_path), Path(source_path), Path(dest_dir)
        prefix = str(source_path.parent)
        if prefix != '.' and os.path.commonprefix([prefix, str(file_path)]) != prefix:
            raise RuntimeError(
                f'file "{file_path}" does not have specified prefix "{prefix}"')
        path_suffix = os.path.relpath(str(file_path), prefix)
        return dest_dir / path_suffix

    def exists(self, path: Union[str, PurePath]) -> bool:
        """Report whether a path exists on the container filesystem."""
        try:
            self._pebble.list_files(str(path), itself=True)
        except pebble.APIError as err:
            if err.code == 404:
                return False
            raise err
        return True

    def isdir(self, path: Union[str, PurePath]) -> bool:
        """Report whether a directory exists at the given path on the container filesystem."""
        try:
            files = self._pebble.list_files(str(path), itself=True)
        except pebble.APIError as err:
            if err.code == 404:
                return False
            raise err
        return files[0].type == pebble.FileType.DIRECTORY

    def make_dir(
            self,
            path: Union[str, PurePath],
            *,
            make_parents: bool = False,
            permissions: Optional[int] = None,
            user_id: Optional[int] = None,
            user: Optional[str] = None,
            group_id: Optional[int] = None,
            group: Optional[str] = None):
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
        self._pebble.make_dir(str(path), make_parents=make_parents,
                              permissions=permissions,
                              user_id=user_id, user=user,
                              group_id=group_id, group=group)

    def remove_path(self, path: Union[str, PurePath], *, recursive: bool = False):
        """Remove a file or directory on the remote system.

        Args:
            path: Path of the file or directory to delete from the remote system.
            recursive: If True, and path is a directory, recursively delete it and
                       everything under it. If path is a file, delete the file. In
                       either case, do nothing if the file or directory does not
                       exist. Behaviourally similar to ``rm -rf <file|dir>``.

        Raises:
            pebble.PathError: If a relative path is provided, or if `recursive` is False
                and the file or directory cannot be removed (it does not exist or is not empty).
        """
        self._pebble.remove_path(str(path), recursive=recursive)

    # Exec I/O is str if encoding is provided (the default)
    @typing.overload
    def exec(  # noqa
        self,
        command: List[str],
        *,
        service_context: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        working_dir: Optional[str] = None,
        timeout: Optional[float] = None,
        user_id: Optional[int] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
        group: Optional[str] = None,
        stdin: Optional[Union[str, TextIO]] = None,
        stdout: Optional[TextIO] = None,
        stderr: Optional[TextIO] = None,
        encoding: str = 'utf-8',
        combine_stderr: bool = False
    ) -> pebble.ExecProcess[str]:
        ...

    # Exec I/O is bytes if encoding is explicitly set to None
    @typing.overload
    def exec(  # noqa
        self,
        command: List[str],
        *,
        service_context: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        working_dir: Optional[str] = None,
        timeout: Optional[float] = None,
        user_id: Optional[int] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
        group: Optional[str] = None,
        stdin: Optional[Union[bytes, BinaryIO]] = None,
        stdout: Optional[BinaryIO] = None,
        stderr: Optional[BinaryIO] = None,
        encoding: None = None,
        combine_stderr: bool = False
    ) -> pebble.ExecProcess[bytes]:
        ...

    def exec(
        self,
        command: List[str],
        *,
        service_context: Optional[str] = None,
        environment: Optional[Dict[str, str]] = None,
        working_dir: Optional[str] = None,
        timeout: Optional[float] = None,
        user_id: Optional[int] = None,
        user: Optional[str] = None,
        group_id: Optional[int] = None,
        group: Optional[str] = None,
        stdin: Optional[Union[str, bytes, TextIO, BinaryIO]] = None,
        stdout: Optional[Union[TextIO, BinaryIO]] = None,
        stderr: Optional[Union[TextIO, BinaryIO]] = None,
        encoding: Optional[str] = 'utf-8',
        combine_stderr: bool = False
    ) -> pebble.ExecProcess[Any]:
        """Execute the given command on the remote system.

        See :meth:`ops.pebble.Client.exec` for documentation of the parameters
        and return value, as well as examples.

        Note that older versions of Juju do not support the ``service_content`` parameter, so if
        the Charm is to be used on those versions, then
        :meth:`JujuVersion.supports_exec_service_context` should be used as a guard.

        Raises:
            ExecError: if the command exits with a non-zero exit code.
        """
        if service_context is not None:
            version = JujuVersion.from_environ()
            if not version.supports_exec_service_context:
                raise RuntimeError(
                    f'exec with service_context not supported on Juju version {version}')
        return self._pebble.exec(
            command,
            service_context=service_context,
            environment=environment,
            working_dir=working_dir,
            timeout=timeout,
            user_id=user_id,
            user=user,
            group_id=group_id,
            group=group,
            stdin=stdin,  # type: ignore
            stdout=stdout,  # type: ignore
            stderr=stderr,  # type: ignore
            encoding=encoding,  # type: ignore
            combine_stderr=combine_stderr,
        )

    def send_signal(self, sig: Union[int, str], *service_names: str):
        """Send the given signal to one or more services.

        Args:
            sig: Name or number of signal to send, for example ``"SIGHUP"``, ``1``, or
                ``signal.SIGHUP``.
            service_names: Name(s) of the service(s) to send the signal to.

        Raises:
            pebble.APIError: If any of the services are not in the plan or are
                not currently running.
        """
        if not service_names:
            raise TypeError('send_signal expected at least 1 service name, got 0')

        self._pebble.send_signal(sig, service_names)

    # Define this last to avoid clashes with the imported "pebble" module
    @property
    def pebble(self) -> pebble.Client:
        """The low-level :class:`ops.pebble.Client` instance for this container."""
        return self._pebble


class ContainerMapping(Mapping[str, Container]):
    """Map of container names to Container objects.

    This is done as a mapping object rather than a plain dictionary so that we
    can extend it later, and so it's not mutable.
    """

    def __init__(self, names: Iterable[str], backend: '_ModelBackend'):
        self._containers = {name: Container(name, backend) for name in names}

    def __getitem__(self, key: str):
        return self._containers[key]

    def __iter__(self):
        return iter(self._containers)

    def __len__(self):
        return len(self._containers)

    def __repr__(self):
        return repr(self._containers)


class ServiceInfoMapping(Mapping[str, pebble.ServiceInfo]):
    """Map of service names to :class:`pebble.ServiceInfo` objects.

    This is done as a mapping object rather than a plain dictionary so that we
    can extend it later, and so it's not mutable.
    """

    def __init__(self, services: Iterable[pebble.ServiceInfo]):
        self._services = {s.name: s for s in services}

    def __getitem__(self, key: str):
        return self._services[key]

    def __iter__(self):
        return iter(self._services)

    def __len__(self):
        return len(self._services)

    def __repr__(self):
        return repr(self._services)


class CheckInfoMapping(Mapping[str, pebble.CheckInfo]):
    """Map of check names to :class:`ops.pebble.CheckInfo` objects.

    This is done as a mapping object rather than a plain dictionary so that we
    can extend it later, and so it's not mutable.
    """

    def __init__(self, checks: Iterable[pebble.CheckInfo]):
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

    def __init__(self, relation_name: str, num_related: int, max_supported: int):
        super().__init__('Too many remote applications on {} ({} > {})'.format(
            relation_name, num_related, max_supported))
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class RelationDataError(ModelError):
    """Raised when a relation data read/write is invalid.

    This is raised either when trying to set a value to something that isn't a string,
    or when trying to set a value in a bucket without the required access. (For example,
    another application/unit, or setting application data without being the leader.)
    """


class RelationDataTypeError(RelationDataError):
    """Raised by ``Relation.data[entity][key] = value`` if `key` or `value` are not strings."""


class RelationDataAccessError(RelationDataError):
    """Raised by ``Relation.data[entity][key] = value`` if unable to access.

    This typically means that permission to write read/write the databag is missing,
    but in some cases it is raised when attempting to read/write from a deceased remote entity.
    """


class RelationNotFoundError(ModelError):
    """Raised when querying Juju for a given relation and that relation doesn't exist."""


class InvalidStatusError(ModelError):
    """Raised if trying to set an Application or Unit status to something invalid."""


class SecretNotFoundError(ModelError):
    """Raised when the specified secret does not exist."""


_ACTION_RESULT_KEY_REGEX = re.compile(r'^[a-z0-9](([a-z0-9-.]+)?[a-z0-9])?$')


def _format_action_result_dict(input: Dict[str, Any],
                               parent_key: Optional[str] = None,
                               output: Optional[Dict[str, str]] = None
                               ) -> Dict[str, str]:
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
    output_: Dict[str, str] = output or {}

    for key, value in input.items():
        # Ensure the key is of a valid format, and raise a ValueError if not
        if not isinstance(key, str):
            # technically a type error, but for consistency with the
            # other exceptions raised on key validation...
            raise ValueError(f'invalid key {key!r}; must be a string')
        if not _ACTION_RESULT_KEY_REGEX.match(key):
            raise ValueError("key '{!r}' is invalid: must be similar to 'key', 'some-key2', or "
                             "'some.key'".format(key))

        if parent_key:
            key = f"{parent_key}.{key}"

        if isinstance(value, MutableMapping):
            value = typing.cast(Dict[str, Any], value)
            output_ = _format_action_result_dict(value, key, output_)
        elif key in output_:
            raise ValueError("duplicate key detected in dictionary passed to 'action-set': {!r}"
                             .format(key))
        else:
            output_[key] = value  # type: ignore

    return output_


class _ModelBackend:
    """Represents the connection between the Model representation and talking to Juju.

    Charm authors should not directly interact with the ModelBackend, it is a private
    implementation of Model.
    """

    LEASE_RENEWAL_PERIOD = datetime.timedelta(seconds=30)
    _STORAGE_KEY_RE = re.compile(
        r'.*^-s\s+\(=\s+(?P<storage_key>.*?)\)\s*?$',
        re.MULTILINE | re.DOTALL
    )

    def __init__(self, unit_name: Optional[str] = None,
                 model_name: Optional[str] = None,
                 model_uuid: Optional[str] = None):

        # if JUJU_UNIT_NAME is not being passed nor in the env, something is wrong
        unit_name_ = unit_name or os.getenv('JUJU_UNIT_NAME')
        if unit_name_ is None:
            raise ValueError('JUJU_UNIT_NAME not set')
        self.unit_name: str = unit_name_

        # we can cast to str because these envvars are guaranteed to be set
        self.model_name: str = model_name or typing.cast(str, os.getenv('JUJU_MODEL_NAME'))
        self.model_uuid: str = model_uuid or typing.cast(str, os.getenv('JUJU_MODEL_UUID'))
        self.app_name: str = self.unit_name.split('/')[0]

        self._is_leader: Optional[bool] = None
        self._leader_check_time = None
        self._hook_is_running = ''

    def _run(self, *args: str, return_output: bool = False,
             use_json: bool = False, input_stream: Optional[str] = None
             ) -> Union[str, Any, None]:
        kwargs = dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, encoding='utf-8')
        if input_stream:
            kwargs.update({"input": input_stream})
        which_cmd = shutil.which(args[0])
        if which_cmd is None:
            raise RuntimeError(f'command not found: {args[0]}')
        args = (which_cmd,) + args[1:]
        if use_json:
            args += ('--format=json',)
        # TODO(benhoyt): all the "type: ignore"s below kinda suck, but I've
        #                been fighting with Pyright for half an hour now...
        try:
            result = subprocess.run(args, **kwargs)  # type: ignore
        except subprocess.CalledProcessError as e:
            raise ModelError(e.stderr) from e
        if return_output:
            if result.stdout is None:  # type: ignore
                return ''
            else:
                text: str = result.stdout  # type: ignore
                if use_json:
                    return json.loads(text)  # type: ignore
                else:
                    return text  # type: ignore

    @staticmethod
    def _is_relation_not_found(model_error: Exception) -> bool:
        return 'relation not found' in str(model_error)

    def _validate_relation_access(self, relation_name: str, relations: Sequence['Relation']):
        """Checks for relation usage inconsistent with the framework/backend state.

        This is used for catching Harness configuration errors and the production implementation
        here should remain empty.
        """
        pass

    def relation_ids(self, relation_name: str) -> List[int]:
        relation_ids = self._run('relation-ids', relation_name, return_output=True, use_json=True)
        relation_ids = typing.cast(Iterable[str], relation_ids)
        return [int(relation_id.split(':')[-1]) for relation_id in relation_ids]

    def relation_list(self, relation_id: int) -> List[str]:
        try:
            rel_list = self._run('relation-list', '-r', str(relation_id),
                                 return_output=True, use_json=True)
            return typing.cast(List[str], rel_list)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def relation_remote_app_name(self, relation_id: int) -> Optional[str]:
        """Return remote app name for given relation ID, or None if not known."""
        if 'JUJU_RELATION_ID' in os.environ and 'JUJU_REMOTE_APP' in os.environ:
            event_relation_id = int(os.environ['JUJU_RELATION_ID'].split(':')[-1])
            if relation_id == event_relation_id:
                # JUJU_RELATION_ID is this relation, use JUJU_REMOTE_APP.
                return os.getenv('JUJU_REMOTE_APP') or None

        # If caller is asking for information about another relation, use
        # "relation-list --app" to get it.
        try:
            rel_id = self._run('relation-list', '-r', str(relation_id), '--app',
                               return_output=True, use_json=True)
            # if it returned anything at all, it's a str.
            return typing.cast(str, rel_id)

        except ModelError as e:
            if self._is_relation_not_found(e):
                return None
            if 'option provided but not defined: --app' in str(e):
                # "--app" was introduced to relation-list in Juju 2.8.1, so
                # handle previous versions of Juju gracefully
                return None
            raise

    def relation_get(self, relation_id: int, member_name: str, is_app: bool
                     ) -> '_RelationDataContent_Raw':
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_get must be a boolean')

        if is_app:
            version = JujuVersion.from_environ()
            if not version.has_app_data():
                raise RuntimeError(
                    f'getting application data is not supported on Juju version {version}')

        args = ['relation-get', '-r', str(relation_id), '-', member_name]
        if is_app:
            args.append('--app')

        try:
            raw_data_content = self._run(*args, return_output=True, use_json=True)
            return typing.cast('_RelationDataContent_Raw', raw_data_content)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def relation_set(self, relation_id: int, key: str, value: str, is_app: bool) -> None:
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_set must be a boolean')

        if is_app:
            version = JujuVersion.from_environ()
            if not version.has_app_data():
                raise RuntimeError(
                    f'setting application data is not supported on Juju version {version}')

        args = ['relation-set', '-r', str(relation_id)]
        if is_app:
            args.append('--app')
        args.extend(["--file", "-"])

        try:
            content = yaml.safe_dump({key: value})
            self._run(*args, input_stream=content)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def config_get(self) -> Dict[str, '_ConfigOption']:
        out = self._run('config-get', return_output=True, use_json=True)
        return typing.cast(Dict[str, '_ConfigOption'], out)

    def is_leader(self) -> bool:
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
            is_leader = self._run('is-leader', return_output=True, use_json=True)
            self._is_leader = typing.cast(bool, is_leader)

        # we can cast to bool now since if we're here it means we checked.
        return typing.cast(bool, self._is_leader)

    def resource_get(self, resource_name: str) -> str:
        out = self._run('resource-get', resource_name, return_output=True)
        return typing.cast(str, out).strip()

    def pod_spec_set(self, spec: Mapping[str, Any],
                     k8s_resources: Optional[Mapping[str, Any]] = None):
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

    def status_get(self, *, is_app: bool = False) -> '_StatusDict':
        """Get a status of a unit or an application.

        Args:
            is_app: A boolean indicating whether the status should be retrieved for a unit
                or an application.
        """
        content = self._run(
            'status-get', '--include-data', f'--application={is_app}',
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
            content = typing.cast(Dict[str, Dict[str, str]], content)
            app_status = content['application-status']
            return {'status': app_status['status'],
                    'message': app_status['message']}
        else:
            return typing.cast('_StatusDict', content)

    def status_set(self, status: str, message: str = '', *, is_app: bool = False) -> None:
        """Set a status of a unit or an application.

        Args:
            status: The status to set.
            message: The message to set in the status.
            is_app: A boolean indicating whether the status should be set for a unit or an
                    application.
        """
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter must be boolean')
        self._run('status-set', f'--application={is_app}', status, message)

    def storage_list(self, name: str) -> List[int]:
        storages = self._run('storage-list', name, return_output=True, use_json=True)
        storages = typing.cast(List[str], storages)
        return [int(s.split('/')[1]) for s in storages]

    def _storage_event_details(self) -> Tuple[int, str]:
        output = self._run('storage-get', '--help', return_output=True)
        output = typing.cast(str, output)
        # Match the entire string at once instead of going line by line
        match = self._STORAGE_KEY_RE.match(output)
        if match is None:
            raise RuntimeError(f'unable to find storage key in {output!r}')
        key = match.groupdict()["storage_key"]

        index = int(key.split("/")[1])
        location = self.storage_get(key, "location")
        return index, location

    def storage_get(self, storage_name_id: str, attribute: str) -> str:
        if not len(attribute) > 0:  # assume it's an empty string.
            raise RuntimeError('calling storage_get with `attribute=""` will return a dict '
                               'and not a string. This usage is not supported.')
        out = self._run('storage-get', '-s', storage_name_id, attribute,
                        return_output=True, use_json=True)
        return typing.cast(str, out)

    def storage_add(self, name: str, count: int = 1) -> None:
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError(f'storage count must be integer, got: {count} ({type(count)})')
        self._run('storage-add', f'{name}={count}')

    def action_get(self) -> Dict[str, Any]:
        out = self._run('action-get', return_output=True, use_json=True)
        return typing.cast(Dict[str, Any], out)

    def action_set(self, results: Dict[str, Any]) -> None:
        # The Juju action-set hook tool cannot interpret nested dicts, so we use a helper to
        # flatten out any nested dict structures into a dotted notation, and validate keys.
        flat_results = _format_action_result_dict(results)
        self._run('action-set', *[f"{k}={v}" for k, v in flat_results.items()])

    def action_log(self, message: str) -> None:
        self._run('action-log', message)

    def action_fail(self, message: str = '') -> None:
        self._run('action-fail', message)

    def application_version_set(self, version: str) -> None:
        self._run('application-version-set', '--', version)

    @classmethod
    def log_split(cls, message: str, max_len: int = MAX_LOG_LINE_LEN
                  ) -> Generator[str, None, None]:
        """Helper to handle log messages that are potentially too long.

        This is a generator that splits a message string into multiple chunks if it is too long
        to safely pass to bash. Will only generate a single entry if the line is not too long.
        """
        if len(message) > max_len:
            yield f"Log string greater than {max_len}. Splitting into multiple chunks: "

        while message:
            yield message[:max_len]
            message = message[max_len:]

    def juju_log(self, level: str, message: str) -> None:
        """Pass a log message on to the juju logger."""
        for line in self.log_split(message):
            self._run('juju-log', '--log-level', level, "--", line)

    def network_get(self, binding_name: str, relation_id: Optional[int] = None) -> '_NetworkDict':
        """Return network info provided by network-get for a given binding.

        Args:
            binding_name: A name of a binding (relation name or extra-binding name).
            relation_id: An optional relation id to get network info for.
        """
        cmd = ['network-get', binding_name]
        if relation_id is not None:
            cmd.extend(['-r', str(relation_id)])
        try:
            network = self._run(*cmd, return_output=True, use_json=True)
            return typing.cast('_NetworkDict', network)
        except ModelError as e:
            if self._is_relation_not_found(e):
                raise RelationNotFoundError() from e
            raise

    def add_metrics(self, metrics: Mapping[str, Union[int, float]],
                    labels: Optional[Mapping[str, str]] = None) -> None:
        cmd: List[str] = ['add-metric']
        if labels:
            label_args: List[str] = []
            for k, v in labels.items():
                _ModelBackendValidator.validate_metric_label(k)
                _ModelBackendValidator.validate_label_value(k, v)
                label_args.append(f'{k}={v}')
            cmd.extend(['--labels', ','.join(label_args)])

        metric_args: List[str] = []
        for k, v in metrics.items():
            _ModelBackendValidator.validate_metric_key(k)
            metric_value = _ModelBackendValidator.format_metric_value(v)
            metric_args.append(f'{k}={metric_value}')
        cmd.extend(metric_args)
        self._run(*cmd)

    def get_pebble(self, socket_path: str) -> pebble.Client:
        """Create a pebble.Client instance from given socket path."""
        return pebble.Client(socket_path=socket_path)

    def planned_units(self) -> int:
        """Count of "planned" units that will run this application.

        This will include the current unit, any units that are alive, units that are in the process
        of being started, but will not include units that are being shut down.

        """
        # The goal-state tool will return the information that we need. Goal state as a general
        # concept is being deprecated, however, in favor of approaches such as the one that we use
        # here.
        app_state = self._run('goal-state', return_output=True, use_json=True)
        app_state = typing.cast(Dict[str, Dict[str, Any]], app_state)

        # Planned units can be zero. We don't need to do error checking here.
        # But we need to filter out dying units as they may be reported before being deleted
        units = app_state.get('units', {})
        num_alive = sum(1 for unit in units.values() if unit['status'] != 'dying')
        return num_alive

    def update_relation_data(self, relation_id: int, _entity: Union['Unit', 'Application'],
                             key: str, value: str):
        self.relation_set(relation_id, key, value, isinstance(_entity, Application))

    def secret_get(self, *,
                   id: Optional[str] = None,
                   label: Optional[str] = None,
                   refresh: bool = False,
                   peek: bool = False) -> Dict[str, str]:
        args: List[str] = []
        if id is not None:
            args.append(id)
        if label is not None:
            args.extend(['--label', label])
        if refresh:
            args.append('--refresh')
        if peek:
            args.append('--peek')
        # IMPORTANT: Don't call shared _run_for_secret method here; we want to
        # be extra sensitive inside secret_get to ensure we never
        # accidentally log or output secrets, even if _run_for_secret changes.
        try:
            result = self._run('secret-get', *args, return_output=True, use_json=True)
        except ModelError as e:
            if 'not found' in str(e):
                raise SecretNotFoundError() from e
            raise
        return typing.cast(Dict[str, str], result)

    def _run_for_secret(self, *args: str, return_output: bool = False,
                        use_json: bool = False) -> Union[str, Any, None]:
        try:
            return self._run(*args, return_output=return_output, use_json=use_json)
        except ModelError as e:
            if 'not found' in str(e):
                raise SecretNotFoundError() from e
            raise

    def secret_info_get(self, *,
                        id: Optional[str] = None,
                        label: Optional[str] = None) -> SecretInfo:
        args: List[str] = []
        if id is not None:
            args.append(id)
        elif label is not None:  # elif because Juju secret-info-get doesn't allow id and label
            args.extend(['--label', label])
        result = self._run_for_secret('secret-info-get', *args, return_output=True, use_json=True)
        info_dicts = typing.cast(Dict[str, Any], result)
        id = list(info_dicts)[0]  # Juju returns dict of {secret_id: {info}}
        return SecretInfo.from_dict(id, typing.cast(Dict[str, Any], info_dicts[id]))

    def secret_set(self, id: str, *,
                   content: Optional[Dict[str, str]] = None,
                   label: Optional[str] = None,
                   description: Optional[str] = None,
                   expire: Optional[datetime.datetime] = None,
                   rotate: Optional[SecretRotate] = None):
        args = [id]
        if label is not None:
            args.extend(['--label', label])
        if description is not None:
            args.extend(['--description', description])
        if expire is not None:
            args.extend(['--expire', expire.isoformat()])
        if rotate is not None:
            args += ['--rotate', rotate.value]
        if content is not None:
            # The content has already been validated with Secret._validate_content
            for k, v in content.items():
                args.append(f'{k}={v}')
        self._run_for_secret('secret-set', *args)

    def secret_add(self, content: Dict[str, str], *,
                   label: Optional[str] = None,
                   description: Optional[str] = None,
                   expire: Optional[datetime.datetime] = None,
                   rotate: Optional[SecretRotate] = None,
                   owner: Optional[str] = None) -> str:
        args: List[str] = []
        if label is not None:
            args.extend(['--label', label])
        if description is not None:
            args.extend(['--description', description])
        if expire is not None:
            args.extend(['--expire', expire.isoformat()])
        if rotate is not None:
            args += ['--rotate', rotate.value]
        if owner is not None:
            args += ['--owner', owner]
        # The content has already been validated with Secret._validate_content
        for k, v in content.items():
            args.append(f'{k}={v}')
        result = self._run('secret-add', *args, return_output=True)
        secret_id = typing.cast(str, result)
        return secret_id.strip()

    def secret_grant(self, id: str, relation_id: int, *, unit: Optional[str] = None):
        args = [id, '--relation', str(relation_id)]
        if unit is not None:
            args += ['--unit', str(unit)]
        self._run_for_secret('secret-grant', *args)

    def secret_revoke(self, id: str, relation_id: int, *, unit: Optional[str] = None):
        args = [id, '--relation', str(relation_id)]
        if unit is not None:
            args += ['--unit', str(unit)]
        self._run_for_secret('secret-revoke', *args)

    def secret_remove(self, id: str, *, revision: Optional[int] = None):
        args = [id]
        if revision is not None:
            args.extend(['--revision', str(revision)])
        self._run_for_secret('secret-remove', *args)

    def open_port(self, protocol: str, port: Optional[int] = None):
        arg = f'{port}/{protocol}' if port is not None else protocol
        self._run('open-port', arg)

    def close_port(self, protocol: str, port: Optional[int] = None):
        arg = f'{port}/{protocol}' if port is not None else protocol
        self._run('close-port', arg)

    def opened_ports(self) -> Set[Port]:
        # We could use "opened-ports --format=json", but it's not really
        # structured; it's just an array of strings which are the lines of the
        # text output, like ["icmp","8081/udp"]. So it's probably just as
        # likely to change as the text output, and doesn't seem any better.
        output = typing.cast(str, self._run('opened-ports', return_output=True))
        ports: Set[Port] = set()
        for line in output.splitlines():
            line = line.strip()
            if not line:
                continue
            port = self._parse_opened_port(line)
            if port is not None:
                ports.add(port)
        return ports

    @classmethod
    def _parse_opened_port(cls, port_str: str) -> Optional[Port]:
        if port_str == 'icmp':
            return Port('icmp', None)
        port_range, slash, protocol = port_str.partition('/')
        if not slash or protocol not in ['tcp', 'udp']:
            logger.warning('Unexpected opened-ports protocol: %s', port_str)
            return None
        port, hyphen, _ = port_range.partition('-')
        if hyphen:
            logger.warning('Ignoring opened-ports port range: %s', port_str)
        protocol_lit = typing.cast(typing.Literal['tcp', 'udp'], protocol)
        return Port(protocol_lit, int(port))

    def reboot(self, now: bool = False):
        if now:
            self._run("juju-reboot", "--now")
            # Juju will kill the Charm process, and in testing no code after
            # this point would execute. However, we want to guarantee that for
            # Charmers, so we force that to be the case.
            sys.exit()
        else:
            self._run("juju-reboot")


class _ModelBackendValidator:
    """Provides facilities for validating inputs and formatting them for model backends."""

    METRIC_KEY_REGEX = re.compile(r'^[a-zA-Z](?:[a-zA-Z0-9-_]*[a-zA-Z0-9])?$')

    @classmethod
    def validate_metric_key(cls, key: str):
        if cls.METRIC_KEY_REGEX.match(key) is None:
            raise ModelError(
                f'invalid metric key {key!r}: must match {cls.METRIC_KEY_REGEX.pattern}')

    @classmethod
    def validate_metric_label(cls, label_name: str):
        if cls.METRIC_KEY_REGEX.match(label_name) is None:
            raise ModelError(
                'invalid metric label name {!r}: must match {}'.format(
                    label_name, cls.METRIC_KEY_REGEX.pattern))

    @classmethod
    def format_metric_value(cls, value: Union[int, float]):
        if not isinstance(value, (int, float)):  # pyright: ignore[reportUnnecessaryIsInstance]
            raise ModelError('invalid metric value {!r} provided:'
                             ' must be a positive finite float'.format(value))

        if math.isnan(value) or math.isinf(value) or value < 0:
            raise ModelError('invalid metric value {!r} provided:'
                             ' must be a positive finite float'.format(value))
        return str(value)

    @classmethod
    def validate_label_value(cls, label: str, value: str):
        # Label values cannot be empty, contain commas or equal signs as those are
        # used by add-metric as separators.
        if not value:
            raise ModelError(
                f'metric label {label} has an empty value, which is not allowed')
        v = str(value)
        if re.search('[,=]', v) is not None:
            raise ModelError(
                f'metric label values must not contain "," or "=": {label}={value!r}')
