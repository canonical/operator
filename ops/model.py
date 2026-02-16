# Copyright 2019 Canonical Ltd.
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

from __future__ import annotations

import contextlib
import contextvars
import copy
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
import sys
import tempfile
import time
import typing
import warnings
import weakref
from abc import ABC, abstractmethod
from collections.abc import Callable, Generator, Iterable, Mapping, MutableMapping
from pathlib import Path, PurePath
from typing import (
    Any,
    BinaryIO,
    ClassVar,
    Literal,
    TextIO,
    TypeAlias,
    TypedDict,
    TypeVar,
    get_args,
    get_type_hints,
)

from . import charm as _charm
from . import hookcmds, pebble
from ._private import timeconv, tracer, yaml
from .jujucontext import JujuContext
from .jujuversion import JujuVersion
from .log import _log_security_event, _SecurityEvent, _SecurityEventLevel

if typing.TYPE_CHECKING:
    from .hookcmds._types import AddressDict as _AddressDict
    from .hookcmds._types import BindAddressDict as _BindAddressDict


# JujuVersion is not used in this file, but there are charms that are importing JujuVersion
# from ops.model, so we keep it here.
_ = JujuVersion

# a k8s spec is a mapping from names/"types" to json/yaml spec objects
K8sSpec = Mapping[str, Any]

_StorageDictType: TypeAlias = 'dict[str, list[Storage] | None]'
_BindingDictType: TypeAlias = 'dict[str | Relation, Binding]'

_ReadOnlyStatusName = Literal['error', 'unknown']
_SettableStatusName = Literal['active', 'blocked', 'maintenance', 'waiting']
_StatusName: TypeAlias = _SettableStatusName | _ReadOnlyStatusName
_StatusDict = TypedDict('_StatusDict', {'status': _StatusName, 'message': str})
_SETTABLE_STATUS_NAMES: tuple[_SettableStatusName, ...] = get_args(_SettableStatusName)

# mapping from relation name to a list of relation objects
_RelationMapping_Raw: TypeAlias = 'dict[str, list[Relation] | None]'
# mapping from container name to container metadata
_ContainerMeta_Raw: TypeAlias = 'dict[str, _charm.ContainerMeta]'  # prevent import loop

# relation data is a string key: string value mapping so far as the
# controller is concerned
_RelationDataContent_Raw: TypeAlias = dict[str, str]
UnitOrApplicationType: TypeAlias = 'type[Unit] | type[Application]'

_NetworkDict = TypedDict(
    '_NetworkDict',
    {
        'bind-addresses': list['_BindAddressDict'],
        'ingress-addresses': list[str],
        'egress-subnets': list[str],
    },
)

logger = logging.getLogger(__name__)

MAX_LOG_LINE_LEN = 131071  # Max length of strings to pass to subshell.


_T = TypeVar('_T')


class Model:
    """Represents the Juju Model as seen from this unit.

    This should not be instantiated directly by Charmers, but can be accessed
    as ``self.model`` from any class that derives from :class:`Object`.
    """

    def __init__(
        self,
        meta: _charm.CharmMeta,
        backend: _ModelBackend,
        broken_relation_id: int | None = None,
        remote_unit_name: str | None = None,
    ):
        self._cache = _ModelCache(meta, backend)
        self._backend = backend
        self._unit = self.get_unit(self._backend.unit_name)
        relations: dict[str, _charm.RelationMeta] = meta.relations
        self._relations = RelationMapping(
            relations,
            self.unit,
            self._backend,
            self._cache,
            broken_relation_id=broken_relation_id,
            _remote_unit=self._cache.get(Unit, remote_unit_name) if remote_unit_name else None,
        )
        self._config = ConfigData(self._backend)
        resources: Iterable[str] = meta.resources
        self._resources = Resources(list(resources), self._backend)
        self._pod = Pod(self._backend)
        storages: Iterable[str] = meta.storages
        self._storages = StorageMapping(list(storages), self._backend)
        self._bindings = BindingMapping(self._backend)

    @property
    def unit(self) -> Unit:
        """The current unit. Equivalent to :attr:`CharmBase.unit`.

        To get a unit by name, use :meth:`get_unit`.
        """
        return self._unit

    @property
    def app(self) -> Application:
        """The application that this unit is part of. Equivalent to :attr:`CharmBase.app`.

        To get an application by name, use :meth:`get_app`.
        """
        return self._unit.app

    @property
    def relations(self) -> RelationMapping:
        """Mapping of endpoint to list of :class:`Relation`.

        Answers the question "what am I currently integrated with".
        See also :meth:`.get_relation`.

        In a ``relation-broken`` event, the broken relation is excluded from
        this list.
        """
        return self._relations

    @property
    def config(self) -> ConfigData:
        """Return a mapping of config for the current application."""
        return self._config

    @property
    def resources(self) -> Resources:
        """Access to resources for this charm.

        Use ``model.resources.fetch(resource_name)`` to get the path on disk
        where the resource can be found.
        """
        return self._resources

    @property
    def storages(self) -> StorageMapping:
        """Mapping of storage_name to :class:`Storage` as defined in metadata.yaml."""
        return self._storages

    @property
    def pod(self) -> Pod:
        """Represents the definition of a pod spec in legacy Kubernetes models.

        Use :meth:`Pod.set_spec` to set the container specification for legacy
        Kubernetes charms.

        .. deprecated:: 2.4.0
            New charms should use the sidecar pattern with Pebble.
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

    @property
    def juju_version(self) -> JujuVersion:
        """Return the version of Juju that is running the model."""
        return self._backend._juju_context.version

    def get_unit(self, unit_name: str) -> Unit:
        """Get a unit by name.

        Internally this uses a cache, so asking for the same unit two times will
        return the same object.

        To get the current unit, use :attr:`CharmBase.unit` or :attr:`unit`.
        """
        return self._cache.get(Unit, unit_name)

    def get_app(self, app_name: str) -> Application:
        """Get an application by name.

        Internally this uses a cache, so asking for the same application two times will
        return the same object.

        To get the application that this unit is part of, use :attr:`CharmBase.app` or :attr:`app`.
        """
        return self._cache.get(Application, app_name)

    def get_relation(self, relation_name: str, relation_id: int | None = None) -> Relation | None:
        """Get a specific Relation instance.

        If relation_id is not given, this will return the Relation instance if the
        relation is established only once or None if it is not established. If this
        same relation is established multiple times the error TooManyRelatedAppsError is raised.

        Args:
            relation_name: The name of the endpoint for this charm
            relation_id: An identifier for a specific relation. Used to disambiguate when a
                given application has more than one relation on a given endpoint.

        Raises:
            TooManyRelatedAppsError: is raised if there is more than one relation with the
                supplied relation_name and no relation_id was supplied
        """
        return self.relations._get_unique(relation_name, relation_id)

    def get_binding(self, binding_key: str | Relation) -> Binding:
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

    def get_secret(self, *, id: str | None = None, label: str | None = None) -> Secret:
        """Get the :class:`Secret` with the given ID or label.

        The caller must provide at least one of `id` (the secret's locator ID)
        or `label` (the charm-local "name").

        If both are provided, the secret will be fetched by ID, and the
        secret's label will be updated to the label provided. Normally secret
        owners set a label using ``add_secret``, whereas secret observers set
        a label using ``get_secret`` (see an example at :attr:`Secret.label`).

        The content of the secret is retrieved, so calls to
        :meth:`Secret.get_content` do not require querying the secret storage
        again, unless ``refresh=True`` is used, or :meth:`Secret.set_content`
        has been called.

        .. jujuadded:: 3.0
            Charm secrets added in Juju 3.0, user secrets added in Juju 3.3

        Args:
            id: Secret ID if fetching by ID.
            label: Secret label if fetching by label (or updating it).

        Raises:
            SecretNotFoundError: If a secret with this ID or label doesn't exist.
            ModelError: if the charm does not have permission to access the
                secret.
        """
        if not (id or label):
            raise TypeError('Must provide an id or label, or both')
        if id is not None:
            # Canonicalize to "secret:<id>" form for consistency in backend calls.
            id = Secret._canonicalize_id(id, self.uuid)
        content = self._backend.secret_get(id=id, label=label)
        return Secret(
            self._backend,
            id=id,
            label=label,
            content=content,
        )

    def get_cloud_spec(self) -> CloudSpec:
        """Get details of the cloud in which the model is deployed.

        .. jujuchanged:: 3.6.10
            This information is available on both machine charms and Kubernetes
            charms. With earlier Juju versions, it was only available on machine charms.

        Returns:
            a specification for the cloud in which the model is deployed,
            including credential information.

        Raises:
            :class:`ModelError`: if called without trust.
        """
        return self._backend.credential_get()


class _ModelCache:
    def __init__(self, meta: _charm.CharmMeta, backend: _ModelBackend):
        self._meta = meta
        self._backend = backend
        # (entity type, name): instance.
        self._weakrefs: weakref.WeakValueDictionary[
            tuple[UnitOrApplicationType, str], Unit | Application | None
        ] = weakref.WeakValueDictionary()

    @typing.overload
    def get(self, entity_type: type[Unit], name: str) -> Unit: ...
    @typing.overload
    def get(self, entity_type: type[Application], name: str) -> Application: ...

    def get(self, entity_type: UnitOrApplicationType, name: str):
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

    This might be this charm's application, or might be an application this charm is integrated
    with.

    Don't instantiate Application objects directly. To get the application that this unit is
    part of, use :attr:`CharmBase.app`. To get an application by name, use :meth:`Model.get_app`.
    """

    name: str
    """The name of this application (eg, 'mysql'). This name may differ from the name of
    the charm, if the user has deployed it to a different name.
    """

    def __init__(
        self, name: str, meta: _charm.CharmMeta, backend: _ModelBackend, cache: _ModelCache
    ):
        self.name = name
        self._backend = backend
        self._cache = cache
        self._is_our_app = self.name == self._backend.app_name
        self._status = None
        self._collected_statuses: list[StatusBase] = []

    def _invalidate(self):
        self._status = None

    @property
    def status(self) -> StatusBase:
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

            self.app.status = ops.BlockedStatus('I need a human to come help me')
        """
        if not self._is_our_app:
            return UnknownStatus()

        if not self._backend.is_leader():
            _log_security_event(
                _SecurityEventLevel.CRITICAL,
                _SecurityEvent.AUTHZ_FAIL,
                'status-get',
                description='Attempted to get application status when not leader',
            )
            raise RuntimeError('cannot get application status as a non-leader unit')

        if self._status:
            return self._status

        s = self._backend.status_get(is_app=True)
        self._status = StatusBase.from_name(s['status'], s['message'])
        return self._status

    @status.setter
    def status(self, value: StatusBase):
        if not isinstance(value, StatusBase):
            raise InvalidStatusError(
                f'invalid value provided for application {self} status: {value}'
            )

        if not self._is_our_app:
            raise RuntimeError(f'cannot set status for a remote application {self}')

        if not self._backend.is_leader():
            _log_security_event(
                _SecurityEventLevel.CRITICAL,
                _SecurityEvent.AUTHZ_FAIL,
                'status-set',
                description='Attempted to set application status when not leader.',
            )
            raise RuntimeError('cannot set application status as a non-leader unit')

        self._backend.status_set(
            typing.cast('_SettableStatusName', value.name),  # status_set will validate at runtime
            value.message,
            is_app=True,
        )

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
            raise RuntimeError(f'cannot get planned units for a remote application {self}.')

        return self._backend.planned_units()

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'

    def add_secret(
        self,
        content: dict[str, str],
        *,
        label: str | None = None,
        description: str | None = None,
        expire: datetime.datetime | datetime.timedelta | None = None,
        rotate: SecretRotate | None = None,
    ) -> Secret:
        """Create a :class:`Secret` owned by this application.

        .. jujuadded:: 3.0

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
            owner='application',
        )
        return Secret(
            self._backend,
            id=id,
            label=label,
            content=content,
        )


def _calculate_expiry(
    expire: datetime.datetime | datetime.timedelta | None,
) -> datetime.datetime | None:
    if expire is None:
        return None
    if isinstance(expire, datetime.datetime):
        return expire
    elif isinstance(expire, datetime.timedelta):
        return datetime.datetime.now() + expire
    else:
        raise TypeError(
            'Expiration time must be a datetime or timedelta from now, '
            f'not {type(expire).__name__}'
        )


class Unit:
    """Represents a named unit in the model.

    This might be the current unit, another unit of the charm's application, or a unit of
    another application that the charm is integrated with.

    Don't instantiate Unit objects directly. To get the current unit, use :attr:`CharmBase.unit`.
    To get a unit by name, use :meth:`Model.get_unit`.
    """

    name: str
    """Name of the unit, for example "mysql/0"."""

    app: Application
    """Application the unit is part of."""

    def __init__(
        self,
        name: str,
        meta: _charm.CharmMeta,
        backend: _ModelBackend,
        cache: _ModelCache,
    ):
        self.name = name

        app_name = name.split('/')[0]
        self.app = cache.get(Application, app_name)

        self._backend = backend
        self._cache = cache
        self._is_our_unit = self.name == self._backend.unit_name
        self._status = None
        self._collected_statuses: list[StatusBase] = []

        if self._is_our_unit and hasattr(meta, 'containers'):
            containers: _ContainerMeta_Raw = meta.containers
            self._containers = ContainerMapping(iter(containers), backend)

    def _invalidate(self):
        self._status = None

    @property
    def status(self) -> StatusBase:
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

            self.unit.status = ops.MaintenanceStatus('reconfiguring the frobnicators')
        """
        if not self._is_our_unit:
            return UnknownStatus()

        if self._status:
            return self._status

        s = self._backend.status_get(is_app=False)
        self._status = StatusBase.from_name(s['status'], s['message'])
        return self._status

    @status.setter
    def status(self, value: StatusBase):
        if not isinstance(value, StatusBase):
            raise InvalidStatusError(f'invalid value provided for unit {self} status: {value}')

        if not self._is_our_unit:
            raise RuntimeError(f'cannot set status for a remote unit {self}')

        self._backend.status_set(
            typing.cast('_SettableStatusName', value.name),  # status_set will validate at runtime
            value.message,
            is_app=False,
        )
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
            raise TypeError(
                f'workload version must be a str, not {type(version).__name__}: {version!r}'
            )
        self._backend.application_version_set(version)

    @property
    def containers(self) -> Mapping[str, Container]:
        """Return a mapping of containers indexed by name.

        Raises:
            RuntimeError: if called for another unit
        """
        if not self._is_our_unit:
            raise RuntimeError(f'cannot get container for a remote unit {self}')
        return self._containers

    def get_container(self, container_name: str) -> Container:
        """Get a single container by name.

        Raises:
            ModelError: if the named container doesn't exist
        """
        try:
            return self.containers[container_name]
        except KeyError:
            raise ModelError(f'container {container_name!r} not found') from None

    def add_secret(
        self,
        content: dict[str, str],
        *,
        label: str | None = None,
        description: str | None = None,
        expire: datetime.datetime | datetime.timedelta | None = None,
        rotate: SecretRotate | None = None,
    ) -> Secret:
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
            owner='unit',
        )
        return Secret(
            self._backend,
            id=id,
            label=label,
            content=content,
        )

    def open_port(
        self, protocol: typing.Literal['tcp', 'udp', 'icmp'], port: int | None = None
    ) -> None:
        """Open a port with the given protocol for this unit.

        Some behaviour, such as whether the port is opened externally without
        using "juju expose" and whether the opened ports are per-unit, differs
        between Kubernetes and machine charms. See the
        `Juju documentation <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/open-port/#details>`_
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

    def close_port(
        self, protocol: typing.Literal['tcp', 'udp', 'icmp'], port: int | None = None
    ) -> None:
        """Close a port with the given protocol for this unit.

        Some behaviour, such as whether the port is closed externally without
        using "juju unexpose", differs between Kubernetes and machine charms.
        See the
        `Juju documentation <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/open-port/#details>`_
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

    def opened_ports(self) -> set[Port]:
        """Return a list of opened ports for this unit."""
        return self._backend.opened_ports()

    def set_ports(self, *ports: int | Port) -> None:
        """Set the open ports for this unit, closing any others that are open.

        Some behaviour, such as whether the port is opened or closed externally without
        using Juju's ``expose`` and ``unexpose`` commands, differs between Kubernetes
        and machine charms. See the
        `Juju documentation <https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/open-port/#details>`_
        for more detail.

        Use :meth:`open_port` and :meth:`close_port` to manage ports
        individually.

        Args:
            ports: The ports to open. Provide an int to open a TCP port, or
                a :class:`Port` to open a port for another protocol.

        Raises:
            ModelError: if a :class:`Port` is provided where ``protocol`` is 'icmp' but
                ``port`` is not ``None``, or where ``protocol`` is 'tcp' or 'udp' and ``port``
                is ``None``.
        """
        # Normalise to get easier comparisons.
        existing = {(port.protocol, port.port) for port in self._backend.opened_ports()}
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

    port: int | None
    """The port number. Will be ``None`` if protocol is ``'icmp'``."""


OpenedPort = Port
"""Alias to Port for backwards compatibility.

.. deprecated:: 2.7.0
    Use :class:`Port` instead.
"""


_LazyValueType = typing.TypeVar('_LazyValueType')


class _GenericLazyMapping(Mapping[str, _LazyValueType], ABC):
    """Represents a dict that isn't populated until it is accessed.

    Charm authors should generally never need to use this directly, but it forms
    the basis for many of the dicts that the framework tracks.
    """

    # key-value mapping
    _lazy_data: dict[str, _LazyValueType] | None = None

    @abstractmethod
    def _load(self) -> dict[str, _LazyValueType]:
        raise NotImplementedError()

    @property
    def _data(self) -> dict[str, _LazyValueType]:
        data = self._lazy_data
        if data is None:
            data = self._lazy_data = self._load()
        return data

    def _invalidate(self):
        self._lazy_data = None

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key: str) -> _LazyValueType:
        return self._data[key]

    def __repr__(self) -> str:
        return repr(self._data)


class LazyMapping(_GenericLazyMapping[str]):
    """Represents a dict[str, str] that isn't populated until it is accessed.

    Charm authors should generally never need to use this directly, but it forms
    the basis for many of the dicts that the framework tracks.
    """


class RelationMapping(Mapping[str, list['Relation']]):
    """Map of relation names to lists of :class:`Relation` instances."""

    def __init__(
        self,
        relations_meta: dict[str, _charm.RelationMeta],
        our_unit: Unit,
        backend: _ModelBackend,
        cache: _ModelCache,
        broken_relation_id: int | None,
        _remote_unit: Unit | None = None,
    ):
        self._peers: set[str] = set()
        for name, relation_meta in relations_meta.items():
            if relation_meta.role.is_peer():
                self._peers.add(name)
        self._our_unit = our_unit
        self._remote_unit = _remote_unit
        self._backend = backend
        self._cache = cache
        self._broken_relation_id = broken_relation_id
        self._data: _RelationMapping_Raw = dict.fromkeys(relations_meta)

    def __contains__(self, key: str):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self) -> Iterable[str]:
        return iter(self._data)

    def __getitem__(self, relation_name: str) -> list[Relation]:
        is_peer = relation_name in self._peers
        relation_list: list[Relation] | None = self._data[relation_name]
        if not isinstance(relation_list, list):
            relation_list = self._data[relation_name] = []
            for rid in self._backend.relation_ids(relation_name):
                if rid == self._broken_relation_id:
                    continue
                relation = Relation(
                    relation_name,
                    rid,
                    is_peer,
                    self._our_unit,
                    self._backend,
                    self._cache,
                    _remote_unit=self._remote_unit,
                )
                relation_list.append(relation)
        return relation_list

    def _invalidate(self, relation_name: str):
        """Used to wipe the cache of a given relation_name.

        Not meant to be used by Charm authors. The content of relation data is
        static for the lifetime of a hook, so it is safe to cache in memory once
        accessed.
        """
        self._data[relation_name] = None

    def _get_unique(self, relation_name: str, relation_id: int | None = None):
        if relation_id is not None:
            if not isinstance(relation_id, int):
                raise ModelError(
                    f'relation id {relation_id} must be int or None, '
                    f'not {type(relation_id).__name__}'
                )
            for relation in self[relation_name]:
                if relation.id == relation_id:
                    return relation
            else:
                # The relation may be dead, but it is not forgotten.
                is_peer = relation_name in self._peers
                return Relation(
                    relation_name,
                    relation_id,
                    is_peer,
                    self._our_unit,
                    self._backend,
                    self._cache,
                    active=False,
                    _remote_unit=self._remote_unit,
                )
        relations = self[relation_name]
        num_related = len(relations)
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

    def __init__(self, backend: _ModelBackend):
        self._backend = backend
        self._data: _BindingDictType = {}

    def get(self, binding_key: str | Relation) -> Binding:
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
            raise ModelError(
                f'binding key must be str or relation instance, not {type(binding_key).__name__}'
            )
        binding = self._data.get(binding_key)
        if binding is None:
            binding = Binding(binding_name, relation_id, self._backend)
            self._data[binding_key] = binding
        return binding

    # implemented to satisfy the Mapping ABC, but not meant to be used.
    def __getitem__(self, item: str | Relation) -> Binding:
        raise NotImplementedError()

    def __iter__(self) -> Iterable[Binding]:
        raise NotImplementedError()

    def __len__(self) -> int:
        raise NotImplementedError()


class Binding:
    """Binding to a network space."""

    name: str
    """The name of the endpoint this binding represents (eg, 'db')."""

    def __init__(self, name: str, relation_id: int | None, backend: _ModelBackend):
        self.name = name
        self._relation_id = relation_id
        self._backend = backend
        self._network = None

    def _network_get(self, name: str, relation_id: int | None = None) -> Network:
        return Network(self._backend.network_get(name, relation_id))

    @property
    def network(self) -> Network:
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


def _cast_network_address(raw: str) -> ipaddress.IPv4Address | ipaddress.IPv6Address | str:
    # fields marked as network addresses need not be IPs; they could be
    # hostnames that juju failed to resolve. In that case, we'll log a
    # debug message and leave it as-is.
    try:
        return ipaddress.ip_address(raw)
    except ValueError:
        logger.debug('could not cast %s to IPv4/v6 address', raw)
        return raw


class Network:
    """Network space details.

    Charm authors should not instantiate this directly, but should get access to the Network
    definition from :meth:`Model.get_binding` and its :code:`network` attribute.
    """

    interfaces: list[NetworkInterface]
    """A list of network interface details. This includes the information
    about how the application should be configured (for example, what IP
    addresses should be bound to).

    Multiple addresses for a single interface are represented as multiple
    interfaces, for example::

        [NetworkInfo('ens1', '10.1.1.1/32'), NetworkInfo('ens1', '10.1.2.1/32'])
    """

    ingress_addresses: list[ipaddress.IPv4Address | ipaddress.IPv6Address | str]
    """A list of IP addresses that other units should use to get in touch with the charm."""

    egress_subnets: list[ipaddress.IPv4Network | ipaddress.IPv6Network]
    """A list of networks representing the subnets that other units will see
    the charm connecting from. Due to things like NAT it isn't always possible to
    narrow it down to a single address, but when it is clear, the CIDRs will
    be constrained to a single address (for example, 10.0.0.1/32).
    """

    def __init__(self, network_info: _NetworkDict):
        """Initialize a Network instance.

        Args:
            network_info: A dict of network information as returned by ``network-get``.
        """
        self.interfaces = []
        # Treat multiple addresses on an interface as multiple logical
        # interfaces with the same name.
        for interface_info in network_info.get('bind-addresses', []):
            interface_name: str = interface_info.get('interface-name')
            addrs: list[_AddressDict] | None = interface_info.get('addresses')
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
    def bind_address(self) -> ipaddress.IPv4Address | ipaddress.IPv6Address | str | None:
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
    def ingress_address(
        self,
    ) -> ipaddress.IPv4Address | ipaddress.IPv6Address | str | None:
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

    address: ipaddress.IPv4Address | ipaddress.IPv6Address | str | None
    """The address of the network interface."""

    subnet: ipaddress.IPv4Network | ipaddress.IPv6Network | None
    """The subnet of the network interface. This may be a single address
    (for example, '10.0.1.2/32').
    """

    def __init__(self, name: str, address_info: _AddressDict):
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
        cidr: str = address_info.get('cidr', '')
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

    def __init__(
        self,
        id: str,
        label: str | None,
        revision: int,
        expires: datetime.datetime | None,
        rotation: SecretRotate | None,
        rotates: datetime.datetime | None,
        description: str | None = None,
        *,
        model_uuid: str | None = None,
    ):
        if model_uuid is None:
            warnings.warn(
                '`model_uuid` should always be provided when creating a '
                'SecretInfo instance, and will be required in the future.',
                DeprecationWarning,
                stacklevel=2,
            )
        self.id = Secret._canonicalize_id(id, model_uuid)
        self.label = label
        self.revision = revision
        self.expires = expires
        self.rotation = rotation
        self.rotates = rotates
        self.description = description

    @classmethod
    def from_dict(cls, id: str, d: dict[str, Any], model_uuid: str | None = None) -> SecretInfo:
        """Create new SecretInfo object from ID and dict parsed from JSON."""
        expires = typing.cast('str | None', d.get('expiry'))
        try:
            rotation = SecretRotate(typing.cast('str | None', d.get('rotation')))
        except ValueError:
            rotation = None
        rotates = typing.cast('str | None', d.get('rotates'))
        return cls(
            id=id,
            label=typing.cast('str | None', d.get('label')),
            revision=typing.cast('int', d['revision']),
            expires=timeconv.parse_rfc3339(expires) if expires is not None else None,
            rotation=rotation,
            rotates=timeconv.parse_rfc3339(rotates) if rotates is not None else None,
            description=typing.cast('str | None', d.get('description')),
            model_uuid=model_uuid,
        )

    def __repr__(self):
        return (
            'SecretInfo('
            f'id={self.id!r}, '
            f'label={self.label!r}, '
            f'revision={self.revision}, '
            f'expires={self.expires!r}, '
            f'rotation={self.rotation}, '
            f'rotates={self.rotates!r}, '
            f'description={self.description!r})'
        )


class Secret:
    """Represents a single secret in the model.

    This class should not be instantiated directly, instead use
    :meth:`Model.get_secret` (for observers and owners), or
    :meth:`Application.add_secret` or :meth:`Unit.add_secret` (for owners).

    All secret events have a :code:`.secret` attribute which provides the
    :class:`Secret` associated with that event.

    .. jujuadded:: 3.0
        Charm secrets added in Juju 3.0, user secrets added in Juju 3.3
    """

    _key_re = re.compile(r'^([a-z](?:-?[a-z0-9]){2,})$')  # copied from Juju code

    def __init__(
        self,
        backend: _ModelBackend,
        id: str | None = None,
        label: str | None = None,
        content: dict[str, str] | None = None,
    ):
        if not (id or label):
            raise TypeError('Must provide an id or label, or both')
        if id is not None:
            id = self._canonicalize_id(id, backend.model_uuid)
        self._backend = backend
        self._id = id
        self._label = label
        self._content = content

    def __repr__(self):
        fields: list[str] = []
        if self._id is not None:
            fields.append(f'id={self._id!r}')
        if self._label is not None:
            fields.append(f'label={self._label!r}')
        return f'<Secret {" ".join(fields)}>'

    @staticmethod
    def _canonicalize_id(id: str, model_uuid: str | None) -> str:
        """Return the canonical form of the given secret ID, with the 'secret:' prefix."""
        id = id.strip()
        if not id.startswith('secret:'):
            # Add the prefix and, if provided, model UUID.
            id = f'secret:{id}' if model_uuid is None else f'secret://{model_uuid}/{id}'

        return id

    @classmethod
    def _validate_content(cls, content: dict[str, str] | None):
        """Ensure the given secret content is valid, or raise ValueError."""
        if not isinstance(content, dict):
            raise TypeError(f'Secret content must be a dict, not {type(content).__name__}')
        if not content:
            raise ValueError('Secret content must not be empty')

        invalid_keys: list[str] = []
        invalid_value_keys: list[str] = []
        invalid_value_types: set[str] = set()
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
                f'start with a letter, and not start or end with a hyphen.'
            )

        if invalid_value_keys:
            invalid_types = ' or '.join(sorted(invalid_value_types))
            raise TypeError(
                f'Invalid secret values for keys: {invalid_value_keys}. '
                f'Values should be of type str, not {invalid_types}.'
            )

    @property
    def id(self) -> str | None:
        """Locator ID (URI) for this secret.

        This has an unfortunate name for historical reasons, as it's not
        really a unique identifier, but the secret's locator URI, which will
        include the model UUID (for cross-model secrets).

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
    def unique_identifier(self) -> str | None:
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
            return self._id[len('secret:') :]
        else:
            # Shouldn't get here as id is canonicalized, but just in case.
            return self._id

    @property
    def label(self) -> str | None:
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

    def get_content(self, *, refresh: bool = False) -> dict[str, str]:
        """Get the secret's content.

        The content of the secret is cached on the :class:`Secret` object, so
        subsequent calls do not require querying the secret storage again,
        unless ``refresh=True`` is used, or :meth:`set_content` is called.

        Returns:
            A copy of the secret's content dictionary.

        Args:
            refresh: If true, fetch the latest revision's content and tell
                Juju to update to tracking that revision. The default is to
                get the content of the currently-tracked revision.

        Raises:
            SecretNotFoundError: if the secret no longer exists.
            ModelError: if the charm does not have permission to access the
                secret.
        """
        if refresh or self._content is None:
            self._content = self._backend.secret_get(id=self.id, label=self.label, refresh=refresh)
        return self._content.copy()

    def peek_content(self) -> dict[str, str]:
        """Get the content of the latest revision of this secret.

        This returns the content of the latest revision without updating the
        tracking. The content is not cached locally, so multiple calls will
        result in multiple queries to the secret storage.

        Raises:
            SecretNotFoundError: if the secret no longer exists.
            ModelError: if the charm does not have permission to access the
                secret.
        """
        return self._backend.secret_get(id=self.id, label=self.label, peek=True)

    def get_info(self) -> SecretInfo:
        """Get this secret's information (metadata).

        Only secret owners can fetch this information.

        Raises:
            SecretNotFoundError: if the secret no longer exists, or if the charm
                does not have permission to access the secret.
        """
        return self._backend.secret_info_get(id=self.id, label=self.label)

    def set_content(self, content: dict[str, str]):
        """Update the content of this secret.

        This will create a new secret revision, and notify all units tracking
        the secret (the "observers") that a new revision is available with a
        :class:`ops.SecretChangedEvent <ops.charm.SecretChangedEvent>`.

        If the charm does not have permission to update the secret, or the
        secret no longer exists, this method will succeed, but the unit will go
        into error state on completion of the current Juju hook.

        .. jujuchanged:: 3.6
            A new secret revision will *not* be created if the content being set
            is identical to the latest revision.

        Args:
            content: A key-value mapping containing the payload of the secret,
                for example :code:`{"password": "foo123"}`.
        """
        self._validate_content(content)
        if self._id is None:
            self._id = self.get_info().id

        self._backend.secret_set(typing.cast('str', self.id), content=content)
        # We do not need to invalidate the cache here, as the content is the
        # same until `refresh` is used, at which point the cache is invalidated.

    def set_info(
        self,
        *,
        label: str | None = None,
        description: str | None = None,
        expire: datetime.datetime | datetime.timedelta | None = None,
        rotate: SecretRotate | None = None,
    ):
        """Update this secret's information (metadata).

        This will not create a new secret revision (that applies only to
        :meth:`set_content`). Once attributes are set, they cannot be unset.

        If the charm does not have permission to update the secret, or the
        secret no longer exists, this method will succeed, but the unit will go
        into error state on completion of the current Juju hook.

        Args:
            label: New label to apply.
            description: New description to apply.
            expire: New expiration time (or timedelta from now) to apply.
            rotate: New rotation policy to apply. The new policy will take
                effect only after the currently-scheduled rotation.
        """
        if label is None and description is None and expire is None and rotate is None:
            raise TypeError(
                'Must provide a label, description, expiration time, or rotation policy'
            )
        if self._id is None:
            self._id = self.get_info().id

        self._backend.secret_set(
            typing.cast('str', self.id),
            label=label,
            description=description,
            expire=_calculate_expiry(expire),
            rotate=rotate,
        )

    def grant(self, relation: Relation, *, unit: Unit | None = None):
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
            typing.cast('str', self.id), relation.id, unit=unit.name if unit is not None else None
        )

    def revoke(self, relation: Relation, *, unit: Unit | None = None):
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
            typing.cast('str', self.id), relation.id, unit=unit.name if unit is not None else None
        )

    def remove_revision(self, revision: int):
        """Remove the given secret revision.

        This is normally only called when handling
        :class:`ops.SecretRemoveEvent <ops.charm.SecretRemoveEvent>` or
        :class:`ops.SecretExpiredEvent <ops.charm.SecretExpiredEvent>`.

        If the charm does not have permission to remove the secret, or it no
        longer exists, this method will succeed, but the unit will go into error
        state on completion of the current Juju hook.

        Args:
            revision: The secret revision to remove. This should usually be set to
                :attr:`SecretRemoveEvent.revision` or :attr:`SecretExpiredEvent.revision`.
        """
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_remove(typing.cast('str', self.id), revision=revision)

    def remove_all_revisions(self) -> None:
        """Remove all revisions of this secret.

        This is called when the secret is no longer needed, for example when
        handling :class:`ops.RelationBrokenEvent <ops.charm.RelationBrokenEvent>`.

        If the charm does not have permission to remove the secret, or it no
        longer exists, this method will succeed, but the unit will go into error
        state on completion of the current Juju hook.
        """
        if self._id is None:
            self._id = self.get_info().id
        self._backend.secret_remove(typing.cast('str', self.id))


@dataclasses.dataclass(frozen=True)
class RemoteModel:
    """Information about the model on the remote side of a relation."""

    uuid: str
    """The remote model's UUID."""


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

    app: Application
    """Represents the remote application of this relation.

    For peer relations, this will be the local application.
    """

    units: set[Unit]
    """A set of units that have started and joined this relation.

    For subordinate relations, this set will include only one unit: the principal unit.
    """

    data: RelationData
    """Holds the data buckets for each entity of a relation.

    This is accessed using, for example, ``Relation.data[unit]['foo']``.

    Note that peer relation data is not readable or writable during the Juju ``install``
    event, even though the relation exists. :class:`ModelError` will be raised in that case.
    """

    active: bool
    """Indicates whether this relation is active.

    This is normally ``True``; it will be ``False`` if the current event is a
    ``relation-broken`` event associated with this relation.
    """

    _remote_unit: Unit | None

    def __init__(
        self,
        relation_name: str,
        relation_id: int,
        is_peer: bool,
        our_unit: Unit,
        backend: _ModelBackend,
        cache: _ModelCache,
        active: bool = True,
        _remote_unit: Unit | None = None,
    ):
        self.name = relation_name
        self.id = relation_id
        self.units: set[Unit] = set()
        self.active = active
        self._backend = backend
        self._cache = cache

        # For peer relations, both the remote and the local app are the same.
        app = our_unit.app if is_peer else None

        try:
            for unit_name in backend.relation_list(self.id):
                unit = cache.get(Unit, unit_name)
                self.units.add(unit)
                if app is None:
                    # Use the app of one of the units if available.
                    app = unit.app
        except RelationNotFoundError:
            # If the relation is dead, just treat it as if it has no remote units.
            self.active = False

        # If we didn't get the remote app via our_unit.app or the units list,
        # look it up via JUJU_REMOTE_APP or "relation-list --app".
        if app is None:
            app_name = backend.relation_remote_app_name(relation_id)
            if app_name is not None:
                app = cache.get(Application, app_name)

        # self.app will not be None and always be set because of the fallback mechanism above.
        self.app = typing.cast('Application', app)

        # In relation-departed `relation-list` doesn't include the remote unit,
        # but the data should still be available.
        if (
            _remote_unit is not None
            and not is_peer
            # In practice, the "self.app will not be None" statement above is not
            # necessarily true. Once https://bugs.launchpad.net/juju/+bug/1960934
            # is resolved, we should be able to remove the next line.
            and self.app is not None
            and _remote_unit.name.startswith(f'{self.app.name}/')
        ):
            remote_unit = _remote_unit
        else:
            remote_unit = None

        self.data = RelationData(self, our_unit, backend, remote_unit)

        self._remote_model: RemoteModel | None = None

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}:{self.id}>'

    @property
    def remote_model(self) -> RemoteModel:
        """Information about the model on the remote side of this relation.

        .. jujuadded:: 3.6.2

        Raises:
            ModelError: if on a version of Juju that doesn't support the
                "relation-model-get" hook command.
        """
        if self._remote_model is None:
            d = self._backend.relation_model_get(self.id)
            self._remote_model = RemoteModel(uuid=d['uuid'])
        return self._remote_model

    def load(
        self,
        cls: type[_T],
        src: Unit | Application,
        *args: Any,
        decoder: Callable[[str], Any] | None = None,
        **kwargs: Any,
    ) -> _T:
        """Load the data for this relation into an instance of a data class.

        The raw Juju relation data is passed to the data class's ``__init__``
        method as keyword arguments, with values decoded using the provided
        decoder function, or :func:`json.loads` if no decoder is provided.

        For example::

            data = event.relation.load(DatabaseModel, event.app)
            secret_id = data.credentials

        For dataclasses and Pydantic ``BaseModel`` subclasses, only fields in
        the Juju relation data that have a matching field in the class are
        passed as arguments. Pydantic fields that have an ``alias``, or
        dataclasses that have a ``metadata{'alias'=}``, will expect the Juju
        relation data field to have the alias name, but will set the attribute
        on the class to the field name.

        For example::

            class Data(pydantic.BaseModel):
                # This field is called 'secret-id' in the Juju relation data.
                secret_id: str = pydantic.Field(alias='secret-id')

            def _observer(self, event: ops.RelationEvent):
                data = event.relation.load(Data, event.app)
                secret = self.model.get_secret(data.secret_id)

        Any additional positional or keyword arguments will be passed through to
        the data class ``__init__``.

        Args:
            cls: A class, typically a Pydantic `BaseModel` subclass or a
                dataclass, that will accept the Juju relation data as keyword
                arguments, and raise ``ValueError`` if validation fails.
            src: The source of the data to load. This can be either a
                :class:`Unit` or :class:`Application` instance.
            decoder: An optional callable that will be used to decode each field
                before loading into the class. If not provided,
                :func:`json.loads` will be used.
            args: positional arguments to pass through to the data class.
            kwargs: keyword arguments to pass through to the data class.

        Returns:
            An instance of the data class that was provided as ``cls`` with the
            current relation data values.
        """
        try:
            fields = _charm._juju_fields(cls)
        except ValueError:
            fields = None
        data: dict[str, Any] = copy.deepcopy(kwargs)
        if decoder is None:
            decoder = json.loads
        for key, value in sorted(self.data[src].items()):
            value = decoder(value)
            if fields is None:
                data[key] = value
            elif key in fields:
                data[fields[key]] = value
        return cls(*args, **data)

    def save(
        self,
        obj: object,
        dst: Unit | Application,
        *,
        encoder: Callable[[Any], str] | None = None,
    ):
        """Save the data from the provided object to the Juju relation data.

        For example::

            relation = self.model.get_relation('tracing')
            data = TracingRequirerData(receivers=['otlp_http'])
            relation.save(data, self.app)

        For dataclasses and Pydantic ``BaseModel`` subclasses, only the class's
        fields will be saved through to the relation data. Pydantic fields that
        have an ``alias``, or dataclasses that have a ``metadata{'alias'=}``,
        will have the object's value saved to the Juju relation data with the
        alias as the key. For other classes, all of the object's attributes that
        have a class type annotation and value set on the object will be saved
        through to the relation data.

        For example::

            class TransferData(pydantic.BaseModel):
                source: pydantic.AnyHttpUrl = pydantic.Field(alias='from')
                destination: pydantic.AnyHttpUrl = pydantic.Field(alias='to')

            def _add_transfer(self):
                data = TransferData(
                    source='https://a.example.com',
                    destination='https://b.example.com',
                )
                relation = self.model.get_relation('mover')
                # data.source will be stored under the Juju relation key 'from'
                # data.destination will be stored under the Juju relation key 'to'
                relation.save(data, self.unit)

        Args:
            obj: an object with attributes to save to the relation data, typically
                a Pydantic ``BaseModel`` subclass or dataclass.
            dst: The destination in which to save the data to save. This
                can be either a :class:`Unit` or :class:`Application` instance.
            encoder: An optional callable that will be used to encode each field
                before passing to Juju. If not provided, :func:`json.dumps` will
                be used.

        Raises:
            RelationDataTypeError: if the encoder does not return a string.
            RelationNotFoundError: if the relation does not exist.
            RelationDataAccessError: if the charm does not have permission to
                write to the relation data.
        """
        if encoder is None:
            encoder = json.dumps

        # Determine the fields, which become the Juju keys, and the values for
        # each field.
        fields: dict[str, str] = {}  # Class attribute name: Juju key.
        if dataclasses.is_dataclass(obj):
            assert not isinstance(obj, type)  # dataclass instance, not class.
            for field in dataclasses.fields(obj):
                alias = field.metadata.get('alias', field.name)
                fields[field.name] = alias
            values = dataclasses.asdict(obj)
        elif hasattr(obj.__class__, 'model_fields'):
            # Pydantic models:
            for name, field in obj.__class__.model_fields.items():  # type: ignore
                # Pydantic takes care of the alias.
                fields[field.alias or name] = field.alias or name  # type: ignore
            values = obj.model_dump(mode='json', by_alias=True, exclude_defaults=False)  # type: ignore
        else:
            # If we could not otherwise determine the fields for the class,
            # store all the fields that have type annotations. If a charm needs
            # a more specific set of fields, then it should use a dataclass or
            # Pydantic model instead.
            fields = {k: k for k in get_type_hints(obj.__class__)}
            values = {field: getattr(obj, field) for field in fields}

        # Encode each value, and then pass it over to Juju.
        data = {field: encoder(values[attr]) for attr, field in sorted(fields.items())}
        self.data[dst].update(data)


class RelationData(Mapping[Unit | Application, 'RelationDataContent']):
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

    def __init__(
        self,
        relation: Relation,
        our_unit: Unit,
        backend: _ModelBackend,
        remote_unit: Unit | None = None,
    ):
        self.relation = weakref.proxy(relation)
        self._data: dict[Unit | Application, RelationDataContent] = {
            our_unit: RelationDataContent(self.relation, our_unit, backend),
            our_unit.app: RelationDataContent(self.relation, our_unit.app, backend),
        }
        self._data.update({
            unit: RelationDataContent(self.relation, unit, backend) for unit in self.relation.units
        })
        # The relation might be dead so avoid a None key here.
        if self.relation.app is not None:
            self._data.update({
                self.relation.app: RelationDataContent(self.relation, self.relation.app, backend),
            })
        # The unit might be departing or broken, so not in relation-list, but accessible.
        if remote_unit is not None and remote_unit not in self._data:
            self._data[remote_unit] = RelationDataContent(self.relation, remote_unit, backend)

    def __contains__(self, key: Unit | Application):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key: Unit | Application) -> RelationDataContent:
        return self._data[key]

    def __repr__(self):
        return repr(self._data)


# We mix in MutableMapping here to get some convenience implementations, but whether it's actually
# mutable or not is controlled by the flag.
class RelationDataContent(LazyMapping, MutableMapping[str, str]):
    """Data content of a unit or application in a relation."""

    def __init__(self, relation: Relation, entity: Unit | Application, backend: _ModelBackend):
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

    def _load(self) -> _RelationDataContent_Raw:
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
                f'Remote application instance cannot be retrieved for {self.relation}.'
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
                f'{self._backend.unit_name} is not leader and cannot read its own '
                f'application databag'
            )

        return True

    def _validate_write(self, data: Mapping[str, str]) -> None:
        """Validate writing key:value pairs to this databag.

        1) that key: value is a valid str:str pair
        2) that we have write access to this databag
        """
        for key, value in data.items():
            self._validate_write_content(key, value)
        self._validate_write_access()

    def _validate_write_content(self, key: str, value: str) -> None:
        # firstly, we validate WHAT we're trying to write.
        # this is independent of whether we're in testing code or production.
        if not isinstance(key, str):
            raise RelationDataTypeError(f'relation data keys must be strings, not {type(key)}')
        if not isinstance(value, str):
            raise RelationDataTypeError(f'relation data values must be strings, not {type(value)}')

    def _validate_write_access(self) -> None:
        # if we're not in production (we're testing): we skip access control rules
        if not self._hook_is_running:
            return

        # finally, we check whether we have permissions to write this databag
        if self._is_app:
            is_our_app: bool = self._backend.app_name == self._entity.name
            if not is_our_app:
                raise RelationDataAccessError(
                    f'{self._backend.app_name} cannot write the data of remote application '
                    f'{self._entity.name}'
                )
            # Whether the application data bag is mutable or not depends on
            # whether this unit is a leader or not, but this is not guaranteed
            # to be always true during the same hook execution.
            if self._backend.is_leader():
                return  # all good
            raise RelationDataAccessError(
                f'{self._backend.unit_name} is not leader and cannot write application data.'
            )
        else:
            # we are attempting to write a unit databag
            # is it OUR UNIT's?
            if self._backend.unit_name != self._entity.name:
                raise RelationDataAccessError(
                    f'{self._backend.unit_name} cannot write databag of {self._entity.name}: '
                    f'not the same unit.'
                )

    def __setitem__(self, key: str, value: str):
        self.update({key: value})

    def _commit(self, data: Mapping[str, str]) -> None:
        self._backend.update_relation_data(
            relation_id=self.relation.id, entity=self._entity, data=data
        )

    def _update_cache(self, data: Mapping[str, str]) -> None:
        """Cache key:value in our local lazy data."""
        # Don't load data unnecessarily if we're only updating.
        if self._lazy_data is None:
            return
        for key, value in data.items():
            if value == '':
                # Match the behavior of Juju, which is that setting the value to an
                # empty string will remove the key entirely from the relation data.
                self._data.pop(key, None)
            else:
                self._data[key] = value

    def __getitem__(self, key: str) -> str:
        self._validate_read()
        return super().__getitem__(key)

    def update(
        self, data: Mapping[str, str] | Iterable[tuple[str, str]] = (), /, **kwargs: str
    ) -> None:
        """Efficiently write multiple keys and values to the databag.

        Has the same ultimate result as this, but uses a single relation-set call::

            for k, v in dict(data).items():
                self[k] = v
            for k, v in kwargs.items():
                self[k] = v
        """
        data = dict(data, **kwargs)
        changes = {
            key: val
            for key, val in data.items()
            if (key not in self and val != '') or (key in self and val != self[key])
        }
        self._validate_write(changes)  # always check permissions
        if not changes:  # return early if there are no changes required
            return
        self._commit(changes)
        self._update_cache(changes)

    def __delitem__(self, key: str):
        # Match the behavior of Juju, which is that setting the value to an empty
        # string will remove the key entirely from the relation data.
        self.__setitem__(key, '')

    def __repr__(self):
        try:
            self._validate_read()
        except RelationDataAccessError:
            return '<n/a>'
        return super().__repr__()


class ConfigData(_GenericLazyMapping['bool | int | float | str']):
    """Configuration data.

    Don't instantiate ConfigData objects directly. To get configuration data for the application
    that this unit is part of, use :meth:`CharmBase.load_config` or :attr:`CharmBase.config`.
    """

    def __init__(self, backend: _ModelBackend):
        self._backend = backend

    def _load(self) -> dict[str, bool | int | float | str]:
        return self._backend.config_get()


class StatusBase:
    """Status values specific to applications and units.

    To access a status by name, use :meth:`StatusBase.from_name`. However, most use cases will
    directly use the child class such as :class:`ActiveStatus` to indicate their status.
    """

    _statuses: ClassVar[dict[_StatusName, type[StatusBase]]] = {}

    # Subclasses must provide this attribute
    name: _StatusName

    def __init__(self, message: str = ''):
        if self.__class__ is StatusBase:
            raise TypeError('cannot instantiate a base class')
        self.message = message

    def __init_subclass__(cls):
        StatusBase._register(cls)

    def __eq__(self, other: StatusBase) -> bool:
        if not isinstance(self, type(other)):
            return False
        return self.message == other.message

    def __repr__(self):
        return f'{self.__class__.__name__}({self.message!r})'

    @classmethod
    def from_name(cls, name: str, message: str):
        """Create a status instance from a name and message.

        If ``name`` is "unknown", ``message`` is ignored, because unknown status
        does not have an associated message.

        Args:
            name: Name of the status, one of:
                "active", "blocked", "maintenance", "waiting", "error", or "unknown".
            message: Message to include with the status.

        Raises:
            KeyError: If ``name`` is not a registered status.
        """
        if name == 'unknown':
            # unknown is special
            return UnknownStatus()
        else:
            return cls._statuses[typing.cast('_StatusName', name)](message)

    @classmethod
    def register(cls, child: type[StatusBase]):
        """.. deprecated:: 2.17.0 Deprecated - this was for internal use only."""
        warnings.warn(
            'StatusBase.register is for internal use only', DeprecationWarning, stacklevel=2
        )
        cls._register(child)
        return child

    @classmethod
    def _register(cls, child: type[StatusBase]) -> None:
        if not (hasattr(child, 'name') and isinstance(child.name, str)):
            raise TypeError(
                f"Can't register StatusBase subclass {child}: ",
                'missing required `name: str` class attribute',
            )
        cls._statuses[child.name] = child

    _priorities: ClassVar[dict[str, Any]] = {
        'error': 5,
        'blocked': 4,
        'maintenance': 3,
        'waiting': 2,
        'active': 1,
        # 'unknown' or any other status is handled below
    }

    @classmethod
    def _get_highest_priority(cls, statuses: list[StatusBase]) -> StatusBase:
        """Return the highest-priority status from a list of statuses.

        If there are multiple highest-priority statuses, return the first one.
        """
        return max(statuses, key=lambda status: cls._priorities.get(status.name, 0))


class UnknownStatus(StatusBase):
    """The unit status is unknown.

    A unit-agent has finished calling install, config-changed and start, but the
    charm has not called status-set yet.

    This status is read-only; trying to set unit or application status to
    ``UnknownStatus`` will raise :class:`~ops.InvalidStatusError`.
    """

    name = 'unknown'

    def __init__(self):
        # Unknown status cannot be set and does not have a message associated with it.
        super().__init__('')

    def __repr__(self):
        return 'UnknownStatus()'


class ErrorStatus(StatusBase):
    """The unit status is error.

    The unit-agent has encountered an error (the application or unit requires
    human intervention in order to operate correctly).

    This status is read-only; trying to set unit or application status to
    ``ErrorStatus`` will raise :class:`~ops.InvalidStatusError`.
    """

    name = 'error'


class ActiveStatus(StatusBase):
    """The unit or application is ready and active.

    Set this status when the charm is correctly offering all the services it
    has been asked to offer. If the unit or application is operational but
    some feature (like high availability) is in a degraded state, set "active"
    with an appropriate message.
    """

    name = 'active'

    def __init__(self, message: str = ''):
        super().__init__(message)


class BlockedStatus(StatusBase):
    """The unit or application requires manual intervention.

    Set this status when an administrator has to manually intervene to unblock
    the charm to let it proceed.
    """

    name = 'blocked'


class MaintenanceStatus(StatusBase):
    """The unit or application is performing maintenance tasks.

    Set this status when the charm is performing an operation such as
    ``apt install``, or is waiting for something under its control, such as
    ``pebble-ready`` or an exec operation in the workload container. In
    contrast to :class:`WaitingStatus`, "maintenance" reflects activity on
    this unit (for unit status), or this app (for app status).
    """

    name = 'maintenance'


class WaitingStatus(StatusBase):
    """The unit or application is waiting on a charm it's integrated with.

    Set this status when waiting on a charm this is integrated with. For
    example, a web app charm would set "waiting" status when it is integrated
    with a database charm that is not ready yet (it might be creating a
    database). In contrast to :class:`MaintenanceStatus`, "waiting" reflects
    activity on integrated units (for unit status) and integrated apps (for
    app status).
    """

    name = 'waiting'


class Resources:
    """Object representing resources for the charm."""

    def __init__(self, names: Iterable[str], backend: _ModelBackend):
        self._backend = backend
        self._paths: dict[str, Path | None] = dict.fromkeys(names)

    def fetch(self, name: str) -> Path:
        """Fetch the resource path from the controller or store.

        Returns:
            The path where the resource is stored on disk.

        Raises:
            NameError: if the resource name is not in the charm metadata.
            ModelError: if the controller is unable to fetch the resource; for
                example, if you ``juju deploy`` from a local charm file and
                forget the appropriate ``--resource``.
        """
        if name not in self._paths:
            raise NameError(f'invalid resource name: {name}')
        if self._paths[name] is None:
            self._paths[name] = Path(self._backend.resource_get(name))
        return typing.cast('Path', self._paths[name])


class Pod:
    """Represents the definition of a pod spec in legacy Kubernetes models.

    Currently only supports simple access to setting the Juju pod spec via
    :attr:`.set_spec`.

    .. deprecated:: 2.4.0

        New charms should use the sidecar pattern with Pebble.
    """

    def __init__(self, backend: _ModelBackend):
        self._backend = backend

    def set_spec(self, spec: K8sSpec, k8s_resources: K8sSpec | None = None):
        """Set the specification for pods that Juju should start in kubernetes.

        See ``juju help-tool pod-spec-set`` for details of what should be passed.

        Args:
            spec: The mapping defining the pod specification
            k8s_resources: Additional kubernetes specific specification.
        """
        if not self._backend.is_leader():
            raise ModelError('cannot set a pod spec as this unit is not a leader')
        self._backend.pod_spec_set(spec, k8s_resources)


class StorageMapping(Mapping[str, list['Storage']]):
    """Map of storage names to lists of Storage instances."""

    def __init__(self, storage_names: Iterable[str], backend: _ModelBackend):
        self._backend = backend
        self._storage_map: _StorageDictType = dict.fromkeys(storage_names)

    def __contains__(self, key: str):
        return key in self._storage_map

    def __len__(self):
        return len(self._storage_map)

    def __iter__(self):
        return iter(self._storage_map)

    def __getitem__(self, storage_name: str) -> list[Storage]:
        if storage_name not in self._storage_map:
            meant = ', or '.join(repr(k) for k in self._storage_map)
            raise KeyError(f'Storage {storage_name!r} not found. Did you mean {meant}?')
        storage_list = self._storage_map[storage_name]
        if storage_list is None:
            storage_list = self._storage_map[storage_name] = []
            for storage_index in self._backend.storage_list(storage_name):
                storage = Storage(storage_name, storage_index, self._backend)
                storage_list.append(storage)
        return storage_list

    def request(self, storage_name: str, count: int = 1):
        """Requests new storage instances of a given name.

        Uses storage-add hook command to request additional storage. Juju will notify the unit
        via ``<storage-name>-storage-attached`` events when it becomes available.

        Raises:
            ModelError: if the storage is not in the charm's metadata.
        """
        if storage_name not in self._storage_map:
            raise ModelError(
                f'cannot add storage {storage_name!r}: it is not present in the charm metadata'
            )
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

    def __init__(self, storage_name: str, storage_index: int, backend: _ModelBackend):
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
        """.. deprecated:: 2.4.0 Use :attr:`Storage.index` instead."""
        logger.warning('model.Storage.id is being replaced - please use model.Storage.index')
        return self.index

    @property
    def full_id(self) -> str:
        """Canonical storage name with index, for example "bigdisk/0"."""
        return f'{self.name}/{self._index}'

    @property
    def location(self) -> Path:
        """Location of the storage."""
        if self._location is None:
            raw = self._backend.storage_get(self.full_id, 'location')
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

    errors: list[tuple[str, Exception]]
    """The list of errors.

    Each error is represented by a tuple of (<source_path>, <exception>),
    where source_path is the path being pushed to or pulled from.
    """

    def __init__(self, message: str, errors: list[tuple[str, Exception]]):
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

    Interactions with the container use Pebble, so all methods may raise
    exceptions when there are problems communicating with Pebble. Problems
    connecting to or transferring data with Pebble will raise a
    :class:`ops.pebble.ConnectionError` - you can guard against these by first
    checking :meth:`can_connect`, but that generally introduces a race condition
    where problems occur after :meth:`can_connect` has succeeded. When an error
    occurs executing the request, such as trying to add an invalid layer or
    execute a command that does not exist, an :class:`ops.pebble.APIError` is
    raised.
    """

    name: str
    """The name of the container from ``metadata.yaml``, for example "postgres"."""

    def __init__(
        self, name: str, backend: _ModelBackend, pebble_client: pebble.Client | None = None
    ):
        self.name = name

        self._juju_version = backend._juju_context.version

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

            # Add status based on any earlier errors communicating with Pebble.
            ...
            # Check that Pebble is still reachable now.
            container = self.unit.get_container("example")
            if not container.can_connect():
                event.add_status(ops.MaintenanceStatus("Waiting for Pebble..."))
        """
        try:
            self._pebble.get_system_info()
        except pebble.ConnectionError as e:
            logger.debug('Pebble API is not ready; ConnectionError: %s', e)
            return False
        except FileNotFoundError as e:
            # In some cases, charm authors can attempt to hit the Pebble API before it has had the
            # chance to create the UNIX socket in the shared volume.
            logger.debug('Pebble API is not ready; UNIX socket not found: %s', e)
            return False
        except pebble.APIError as e:
            # An API error is only raised when the Pebble API returns invalid JSON, or the response
            # cannot be read. Both of these are a likely indicator that something is wrong.
            logger.warning('Pebble API is not ready; APIError: %s', e)
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
        """Restart the given service(s) by name.

        Listed running services will be stopped and restarted, and listed stopped
        services will be started.
        """
        if not service_names:
            raise TypeError('restart expected at least 1 argument, got 0')

        try:
            self._pebble.restart_services(service_names)
        except pebble.APIError as e:
            if e.code != 400:
                raise e
            # support old Pebble instances that don't support the "restart" action
            stop: tuple[str, ...] = tuple(
                s.name for s in self.get_services(*service_names).values() if s.is_running()
            )
            if stop:
                self._pebble.stop_services(stop)
            self._pebble.start_services(service_names)

    def stop(self, *service_names: str):
        """Stop given service(s) by name."""
        if not service_names:
            raise TypeError('stop expected at least 1 argument, got 0')

        self._pebble.stop_services(service_names)

    def add_layer(
        self,
        label: str,
        layer: str | pebble.LayerDict | pebble.Layer,
        *,
        combine: bool = False,
    ):
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

    def get_services(self, *service_names: str) -> Mapping[str, pebble.ServiceInfo]:
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
            ModelError: if a service with the given name is not found
        """
        services = self.get_services(service_name)
        if not services:
            raise ModelError(f'service {service_name!r} not found')
        if len(services) > 1:
            raise RuntimeError(f'expected 1 service, got {len(services)}')
        return services[service_name]

    def get_checks(
        self, *check_names: str, level: pebble.CheckLevel | None = None
    ) -> CheckInfoMapping:
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
            ModelError: if a check with the given name is not found
        """
        checks = self.get_checks(check_name)
        if not checks:
            raise ModelError(f'check {check_name!r} not found')
        if len(checks) > 1:
            raise RuntimeError(f'expected 1 check, got {len(checks)}')
        return checks[check_name]

    def start_checks(self, *check_names: str) -> list[str]:
        """Start given check(s) by name.

        .. jujuadded:: 3.6.4

        Returns:
            A list of check names that were started. Checks that were already
            running will not be included.
        """
        if not check_names:
            raise TypeError('start-checks expected at least 1 argument, got 0')

        return self._pebble.start_checks(check_names)

    def stop_checks(self, *check_names: str) -> list[str]:
        """Stop given check(s) by name.

        .. jujuadded:: 3.6.4

        Returns:
            A list of check names that were stopped. Checks that were already
            inactive will not be included.
        """
        if not check_names:
            raise TypeError('stop-checks expected at least 1 argument, got 0')

        stopped_checks = self._pebble.stop_checks(check_names)
        for check in stopped_checks:
            _log_security_event(
                _SecurityEventLevel.WARN,
                _SecurityEvent.SYS_MONITOR_DISABLED,
                f'{os.getuid()},{check}',
                description=f'Stopped check {check}',
            )
        return stopped_checks

    @typing.overload
    def pull(self, path: str | PurePath, *, encoding: None) -> BinaryIO: ...

    @typing.overload
    def pull(self, path: str | PurePath, *, encoding: str = 'utf-8') -> TextIO: ...

    def pull(self, path: str | PurePath, *, encoding: str | None = 'utf-8') -> BinaryIO | TextIO:
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
        return self._pebble.pull(path, encoding=encoding)

    def push(
        self,
        path: str | PurePath,
        source: bytes | str | BinaryIO | TextIO,
        *,
        encoding: str = 'utf-8',
        make_dirs: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ):
        """Write content to a given file path on the remote system.

        Note that if another process has the file open on the remote system,
        or if the remote file is a bind mount, pushing will fail with a
        :class:`pebble.PathError`. Use :meth:`Container.exec` for full
        control.

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
            user_id: User ID (UID) for file. If neither ``group_id`` nor ``group`` is provided,
                the group is set to the user's default group.
            user: Username for file. User's UID must match ``user_id`` if both are
                specified. If neither ``group_id`` nor ``group`` is provided,
                the group is set to the user's default group.
            group_id: Group ID (GID) for file. May only be specified with ``user_id`` or ``user``.
            group: Group name for file. Group's GID must match ``group_id`` if
                both are specified. May only be specified with ``user_id`` or ``user``.
        """
        self._pebble.push(
            path,
            source,
            encoding=encoding,
            make_dirs=make_dirs,
            permissions=permissions,
            user_id=user_id,
            user=user,
            group_id=group_id,
            group=group,
        )

    def list_files(
        self, path: str | PurePath, *, pattern: str | None = None, itself: bool = False
    ) -> list[pebble.FileInfo]:
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

    def push_path(
        self,
        source_path: str | Path | Iterable[str | Path],
        dest_dir: str | PurePath,
    ):
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
            source_paths = typing.cast('Iterable[str | Path]', source_path)
        else:
            source_paths = typing.cast('Iterable[str | Path]', [source_path])
        source_paths = [Path(p) for p in source_paths]
        dest_dir = Path(dest_dir)

        def local_list(source_path: Path) -> list[pebble.FileInfo]:
            paths = source_path.iterdir() if source_path.is_dir() else [source_path]
            files = [self._build_fileinfo(f) for f in paths]
            return files

        errors: list[tuple[str, Exception]] = []
        for source_path in source_paths:
            try:
                for info in Container._list_recursive(local_list, source_path):
                    dstpath = self._build_destpath(info.path, source_path, dest_dir)
                    if info.type is pebble.FileType.DIRECTORY:
                        self.make_dir(dstpath, make_parents=True)
                        continue
                    with open(info.path, 'rb') as src:
                        self.push(
                            dstpath,
                            src,
                            make_dirs=True,
                            permissions=info.permissions,
                            user_id=info.user_id,
                            user=info.user,
                            group_id=info.group_id,
                            group=info.group,
                        )
            except (OSError, pebble.Error) as err:
                errors.append((str(source_path), err))
        if errors:
            raise MultiPushPullError('failed to push one or more files', errors)

    def pull_path(
        self,
        source_path: str | PurePath | Iterable[str | PurePath],
        dest_dir: str | Path,
    ):
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
            source_paths = typing.cast('Iterable[str | Path]', source_path)
        else:
            source_paths = typing.cast('Iterable[str | Path]', [source_path])
        source_paths = [Path(p) for p in source_paths]
        dest_dir = Path(dest_dir)

        errors: list[tuple[str, Exception]] = []
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
    def _build_fileinfo(path: str | Path) -> pebble.FileInfo:
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
            logger.warning('Could not get name for user %s', info.st_uid)
            pw_name = None
        try:
            gr_name = grp.getgrgid(info.st_gid).gr_name
        except KeyError:
            logger.warning('Could not get name for group %s', info.st_gid)
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
            group=gr_name,
        )

    @staticmethod
    def _list_recursive(
        list_func: Callable[[Path], Iterable[pebble.FileInfo]], path: Path
    ) -> Generator[pebble.FileInfo, None, None]:
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
                    'skipped unsupported file in Container.[push/pull]_path: %s', info.path
                )

    @staticmethod
    def _build_destpath(
        file_path: str | Path, source_path: str | Path, dest_dir: str | Path
    ) -> Path:
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
            raise RuntimeError(f'file "{file_path}" does not have specified prefix "{prefix}"')
        path_suffix = os.path.relpath(str(file_path), prefix)
        return dest_dir / path_suffix

    def exists(self, path: str | PurePath) -> bool:
        """Report whether a path exists on the container filesystem."""
        try:
            self._pebble.list_files(path, itself=True)
        except pebble.APIError as err:
            if err.code == 404:
                return False
            raise err
        return True

    def isdir(self, path: str | PurePath) -> bool:
        """Report whether a directory exists at the given path on the container filesystem."""
        try:
            files = self._pebble.list_files(path, itself=True)
        except pebble.APIError as err:
            if err.code == 404:
                return False
            raise err
        return files[0].type == pebble.FileType.DIRECTORY

    def make_dir(
        self,
        path: str | PurePath,
        *,
        make_parents: bool = False,
        permissions: int | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
    ):
        """Create a directory on the remote system with the given attributes.

        Args:
            path: Path of the directory to create on the remote system.
            make_parents: If True, create parent directories if they don't exist.
            permissions: Permissions (mode) to create directory with (Pebble
                default is 0o755).
            user_id: User ID (UID) for directory. If neither ``group_id`` nor ``group``
                is provided, the group is set to the user's default group.
            user: Username for directory. User's UID must match ``user_id`` if
                both are specified. If neither ``group_id`` nor ``group`` is provided,
                the group is set to the user's default group.
            group_id: Group ID (GID) for directory.
                May only be specified with ``user_id`` or ``user``.
            group: Group name for directory. Group's GID must match ``group_id``
                if both are specified. May only be specified with ``user_id`` or ``user``.
        """
        self._pebble.make_dir(
            path,
            make_parents=make_parents,
            permissions=permissions,
            user_id=user_id,
            user=user,
            group_id=group_id,
            group=group,
        )

    def remove_path(self, path: str | PurePath, *, recursive: bool = False):
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
        self._pebble.remove_path(path, recursive=recursive)

    # Exec I/O is str if encoding is provided (the default)
    @typing.overload
    def exec(
        self,
        command: list[str],
        *,
        service_context: str | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | PurePath | None = None,
        timeout: float | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
        stdin: str | TextIO | None = None,
        stdout: TextIO | None = None,
        stderr: TextIO | None = None,
        encoding: str = 'utf-8',
        combine_stderr: bool = False,
    ) -> pebble.ExecProcess[str]: ...

    # Exec I/O is bytes if encoding is explicitly set to None
    @typing.overload
    def exec(
        self,
        command: list[str],
        *,
        service_context: str | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | PurePath | None = None,
        timeout: float | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
        stdin: bytes | BinaryIO | None = None,
        stdout: BinaryIO | None = None,
        stderr: BinaryIO | None = None,
        encoding: None,
        combine_stderr: bool = False,
    ) -> pebble.ExecProcess[bytes]: ...

    def exec(
        self,
        command: list[str],
        *,
        service_context: str | None = None,
        environment: dict[str, str] | None = None,
        working_dir: str | PurePath | None = None,
        timeout: float | None = None,
        user_id: int | None = None,
        user: str | None = None,
        group_id: int | None = None,
        group: str | None = None,
        stdin: str | bytes | TextIO | BinaryIO | None = None,
        stdout: TextIO | BinaryIO | None = None,
        stderr: TextIO | BinaryIO | None = None,
        encoding: str | None = 'utf-8',
        combine_stderr: bool = False,
    ) -> pebble.ExecProcess[Any]:
        """Execute the given command on the remote system.

        See :meth:`ops.pebble.Client.exec` for documentation of the parameters
        and return value, as well as examples.

        Note that older versions of Juju do not support the ``service_context`` parameter, so if
        the Charm is to be used on those versions, then
        :meth:`JujuVersion.supports_exec_service_context` should be used as a guard.

        Raises:
            ExecError: if the command exits with a non-zero exit code.
        """
        assert self._juju_version is not None
        if service_context is not None and not self._juju_version.supports_exec_service_context:
            raise RuntimeError(
                f'exec with service_context not supported on Juju version {self._juju_version}'
            )
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

    def send_signal(self, sig: int | str, *service_names: str):
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

    def get_notice(self, id: str) -> pebble.Notice:
        """Get details about a single notice by ID.

        .. jujuadded:: 3.4

        Raises:
            ModelError: if a notice with the given ID is not found
        """
        try:
            return self._pebble.get_notice(id)
        except pebble.APIError as e:
            if e.code == 404:
                raise ModelError(f'notice {id!r} not found') from e
            raise

    def get_notices(
        self,
        *,
        users: pebble.NoticesUsers | None = None,
        user_id: int | None = None,
        types: Iterable[pebble.NoticeType | str] | None = None,
        keys: Iterable[str] | None = None,
    ) -> list[pebble.Notice]:
        """Query for notices that match all of the provided filters.

        See :meth:`ops.pebble.Client.get_notices` for documentation of the
        parameters.

        .. jujuadded:: 3.4
        """
        return self._pebble.get_notices(
            users=users,
            user_id=user_id,
            types=types,
            keys=keys,
        )

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

    def __init__(self, names: Iterable[str], backend: _ModelBackend):
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
    """Raised by :meth:`Model.get_relation` if there is more than one integrated application."""

    def __init__(self, relation_name: str, num_related: int, max_supported: int):
        super().__init__(
            f'Too many remote applications on {relation_name} ({num_related} > {max_supported})'
        )
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


def _format_action_result_dict(
    input: dict[str, Any],
    parent_key: str | None = None,
    output: dict[str, str] | None = None,
) -> dict[str, str]:
    """Turn a nested dictionary into a flattened dictionary, using '.' as a key separator.

    This is used to allow nested dictionaries to be translated into the dotted format required by
    the Juju `action-set` hook command in order to set nested data on an action.

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
    output_: dict[str, str] = output or {}

    for key, value in input.items():
        # Ensure the key is of a valid format, and raise a ValueError if not
        if not isinstance(key, str):
            # technically a type error, but for consistency with the
            # other exceptions raised on key validation...
            raise ValueError(f'invalid key {key!r}; must be a string')
        if not _ACTION_RESULT_KEY_REGEX.match(key):
            raise ValueError(
                f"key {key!r} is invalid: must be similar to 'key', 'some-key2', or 'some.key'"
            )

        if parent_key:
            key = f'{parent_key}.{key}'

        if isinstance(value, MutableMapping):
            value = typing.cast('dict[str, Any]', value)
            output_ = _format_action_result_dict(value, key, output_)
        elif key in output_:
            raise ValueError(
                f"duplicate key detected in dictionary passed to 'action-set': {key!r}"
            )
        else:
            output_[key] = value

    return output_


class _ModelBackend:
    """Represents the connection between the Model representation and talking to Juju.

    Charm authors should not directly interact with the ModelBackend, it is a private
    implementation of Model.
    """

    LEASE_RENEWAL_PERIOD = datetime.timedelta(seconds=30)

    def __init__(
        self,
        unit_name: str | None = None,
        model_name: str | None = None,
        model_uuid: str | None = None,
        juju_context: JujuContext | None = None,
    ):
        if juju_context is None:
            juju_context = JujuContext._from_dict(os.environ)
        self._juju_context = juju_context
        # if JUJU_UNIT_NAME is not being passed nor in the env, something is wrong
        unit_name_ = unit_name or self._juju_context.unit_name
        if unit_name_ is None:
            raise ValueError('JUJU_UNIT_NAME not set')
        self.unit_name: str = unit_name_

        # we can cast to str because these envvars are guaranteed to be set
        self.model_name: str = model_name or self._juju_context.model_name
        self.model_uuid: str = model_uuid or self._juju_context.model_uuid
        self.app_name: str = self.unit_name.split('/')[0]

        self._is_leader: bool | None = None
        self._leader_check_time = None
        self._hook_is_running = ''
        self._is_recursive = contextvars.ContextVar('_is_recursive', default=False)

    @contextlib.contextmanager
    def _prevent_recursion(self):
        token = self._is_recursive.set(True)
        try:
            yield
        finally:
            self._is_recursive.reset(token)

    @contextlib.contextmanager
    def _wrap_hookcmd(self, cmd: str, *args: Any, **kwargs: Any):
        if self._is_recursive.get():
            # Either `juju-log` hook command failed or there's a bug in ops.
            return
        # Logs are collected via log integration, omit the subprocess calls that push
        # the same content to juju from telemetry.
        mgr = self._prevent_recursion() if cmd == 'juju-log' else tracer.start_as_current_span(cmd)
        try:
            with mgr as span:
                if span is not None:
                    span.set_attribute('call', 'subprocess.run')
                    if args:
                        span.set_attribute('args', args)
                    if kwargs:
                        span.set_attribute('kwargs', [f'{k}={v}' for k, v in kwargs.items()])
                yield
        except hookcmds.Error as e:
            self._check_for_security_event(e.cmd[0], e.returncode, e.stderr)
            if (
                cmd.startswith(('relation-', 'network-'))
                and 'relation not found' in e.stderr.lower()
            ):
                raise RelationNotFoundError() from e
            elif cmd.startswith('secret-') and 'not found' in e.stderr.lower():
                raise SecretNotFoundError() from e
            raise ModelError(e.stderr) from e

    def _check_for_security_event(self, cmd: str, returncode: int, stderr: str):
        authz_messages = (
            'access denied',
            'permission denied',
            'not the leader',
            'cannot write relation settings',
        )
        if not any(message in stderr.lower() for message in authz_messages):
            return
        base_cmd = os.path.basename(cmd)
        leadership = ' (as leader)' if self.is_leader() else ''
        description = (
            f'Hook command {base_cmd!r}{leadership} failed with code {returncode}: '
            f'{stderr.strip()!r}. '
        )
        _log_security_event(
            _SecurityEventLevel.CRITICAL,
            _SecurityEvent.AUTHZ_FAIL,
            base_cmd,
            description=description,
        )

    def relation_ids(self, relation_name: str) -> list[int]:
        with self._wrap_hookcmd('relation-ids', relation_name=relation_name):
            relation_ids = hookcmds.relation_ids(relation_name)
        return [int(relation_id.split(':')[-1]) for relation_id in relation_ids]

    def relation_list(self, relation_id: int) -> list[str]:
        with self._wrap_hookcmd('relation-list', relation_id=relation_id):
            return hookcmds.relation_list(relation_id)

    def relation_remote_app_name(self, relation_id: int) -> str | None:
        """Return remote app name for given relation ID, or None if not known."""
        if (
            self._juju_context.relation_id is not None
            and self._juju_context.remote_app_name is not None
        ):
            event_relation_id = self._juju_context.relation_id
            if relation_id == event_relation_id:
                # JUJU_RELATION_ID is this relation, use JUJU_REMOTE_APP.
                return self._juju_context.remote_app_name

        # If caller is asking for information about another relation, use
        # "relation-list --app" to get it.
        try:
            with self._wrap_hookcmd('relation-list', relation_id=relation_id, app=True):
                return hookcmds.relation_list(relation_id, app=True)
        except RelationNotFoundError:
            return None

    def relation_get(
        self, relation_id: int, member_name: str, is_app: bool
    ) -> _RelationDataContent_Raw:
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_get must be a boolean')

        if is_app and not self._juju_context.version.has_app_data():
            raise RuntimeError(
                'getting application data is not supported on Juju version '
                f'{self._juju_context.version}'
            )

        with self._wrap_hookcmd(
            'relation-get', relation_id=relation_id, unit=member_name, app=is_app
        ):
            return hookcmds.relation_get(relation_id, unit=member_name, app=is_app)

    def relation_set(self, relation_id: int, data: Mapping[str, str], is_app: bool) -> None:
        if not data:
            raise ValueError('at least one key:value pair is required for relation-set')
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_set must be a boolean')

        if is_app and not self._juju_context.version.has_app_data():
            raise RuntimeError(
                'setting application data is not supported on Juju version '
                f'{self._juju_context.version}'
            )

        with self._wrap_hookcmd('relation-set', relation_id=relation_id, data=data, app=is_app):
            hookcmds.relation_set(data, relation_id, app=is_app)

    def relation_model_get(self, relation_id: int) -> dict[str, Any]:
        with self._wrap_hookcmd('relation-model-get', relation_id=relation_id):
            raw = hookcmds.relation_model_get(relation_id)
        return {'uuid': raw.uuid}

    def config_get(self) -> dict[str, bool | int | float | str]:
        with self._wrap_hookcmd('config-get'):
            return hookcmds.config_get()

    def is_leader(self) -> bool:
        """Obtain the current leadership status for the unit the charm code is executing on.

        The value is cached for the duration of a lease which is 30s in Juju.
        """
        now = time.monotonic()
        if self._leader_check_time is None:
            check = True
        else:
            time_since_check = datetime.timedelta(seconds=now - self._leader_check_time)
            check = time_since_check > self.LEASE_RENEWAL_PERIOD or self._is_leader is None
        if check:
            # Current time MUST be saved before running is-leader to ensure the cache
            # is only used inside the window that is-leader itself asserts.
            self._leader_check_time = now
            with self._wrap_hookcmd('is-leader'):
                self._is_leader = hookcmds.is_leader()

        # We can cast to bool now since if we're here it means we checked.
        return typing.cast('bool', self._is_leader)

    def resource_get(self, resource_name: str) -> str:
        with self._wrap_hookcmd('resource-get', resource_name=resource_name):
            return str(hookcmds.resource_get(resource_name))

    def pod_spec_set(
        self, spec: Mapping[str, Any], k8s_resources: Mapping[str, Any] | None = None
    ):
        tmpdir = Path(tempfile.mkdtemp('-pod-spec-set'))
        try:
            spec_path = tmpdir / 'spec.yaml'
            with spec_path.open('wt', encoding='utf8') as f:
                yaml.safe_dump(spec, stream=f)
            args = ['--file', str(spec_path)]
            if k8s_resources:
                k8s_res_path = tmpdir / 'k8s-resources.yaml'
                with k8s_res_path.open('wt', encoding='utf8') as f:
                    yaml.safe_dump(k8s_resources, stream=f)
                args.extend(['--k8s-resources', str(k8s_res_path)])
            with self._wrap_hookcmd('pod-spec-set', spec=spec, k8s_resources=k8s_resources):
                hookcmds._utils.run('pod-spec-set', *args)
        finally:
            shutil.rmtree(str(tmpdir))

    def status_get(self, *, is_app: bool = False) -> _StatusDict:
        """Get a status of a unit or an application.

        Args:
            is_app: A boolean indicating whether the status should be retrieved for a unit
                or an application.
        """
        with self._wrap_hookcmd('status-get', app=is_app):
            content = hookcmds.status_get(app=is_app)

        # hookcmds doesn't constrain the status to the five that _StatusDict expects,
        # but we know that will be the case, so we type: ignore.
        return {
            'status': content.status,  # type: ignore[arg-type]
            'message': content.message,
        }

    def status_set(
        self, status: _SettableStatusName, message: str = '', *, is_app: bool = False
    ) -> None:
        """Set a status of a unit or an application.

        Args:
            status: The status to set.
            message: The message to set in the status.
            is_app: A boolean indicating whether the status should be set for a unit or an
                    application.
        """
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter must be boolean')
        if not isinstance(message, str):
            raise TypeError('message parameter must be a string')
        if status not in _SETTABLE_STATUS_NAMES:
            raise InvalidStatusError(f'status must be in {_SETTABLE_STATUS_NAMES}, not {status!r}')
        with self._wrap_hookcmd('status-set', status=status, message=message, app=is_app):
            hookcmds.status_set(status, message, app=is_app)

    def storage_list(self, name: str) -> list[int]:
        with self._wrap_hookcmd('storage-list', name=name):
            storages = hookcmds.storage_list(name)
        return [int(s.split('/')[1]) for s in storages]

    def storage_get(self, storage_name_id: str, attribute: str) -> str:
        if not len(attribute) > 0:  # assume it's an empty string.
            raise RuntimeError(
                'calling storage_get with `attribute=""` will return a dict '
                'and not a string. This usage is not supported.'
            )
        with self._wrap_hookcmd('storage-get', name=storage_name_id, attribute=attribute):
            return getattr(hookcmds.storage_get(storage_name_id), attribute)

    def storage_add(self, name: str, count: int = 1) -> None:
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError(f'storage count must be integer, got: {count} ({type(count)})')
        with self._wrap_hookcmd('storage-add', name=name, count=count):
            hookcmds.storage_add({name: count})

    def action_get(self) -> dict[str, Any]:
        with self._wrap_hookcmd('action-get'):
            return hookcmds.action_get()

    def action_set(self, results: dict[str, Any]) -> None:
        # The Juju action-set hook command cannot interpret nested dicts, so we use a helper to
        # flatten out any nested dict structures into a dotted notation, and validate keys.
        # The hookcmds action_set method will handle flattening nested structures, but does
        # not do validation, so we handle both here.
        flat_results = _format_action_result_dict(results)
        # We do not trace the arguments here, as they may contain sensitive data.
        with self._wrap_hookcmd('action-set', '...'):
            hookcmds.action_set(flat_results)

    def action_log(self, message: str) -> None:
        with self._wrap_hookcmd('action-log', message=message):
            hookcmds.action_log(message)

    def action_fail(self, message: str = '') -> None:
        with self._wrap_hookcmd('action-fail', message=message):
            hookcmds.action_fail(message)

    def application_version_set(self, version: str) -> None:
        with self._wrap_hookcmd('app-version-set', version=version):
            hookcmds.app_version_set(version)

    @classmethod
    def log_split(
        cls, message: str, max_len: int = MAX_LOG_LINE_LEN
    ) -> Generator[str, None, None]:
        """Helper to handle log messages that are potentially too long.

        This is a generator that splits a message string into multiple chunks if it is too long
        to safely pass to bash. Will only generate a single entry if the line is not too long.
        """
        if len(message) > max_len:
            yield f'Log string greater than {max_len}. Splitting into multiple chunks: '

        while message:
            yield message[:max_len]
            message = message[max_len:]

    def juju_log(self, level: str, message: str) -> None:
        """Pass a log message on to the juju logger."""
        # We do not trace this call. This is partly because we don't want to
        # force charms to mix logging in with tracing (if we include the level
        # and message, that's essentially the entire log), and partly because
        # it avoids a loop if the tracing or hook command execution itself
        # causes logging, either directly or via a traceback.
        for line in self.log_split(message):
            # For backwards compatibility we allow arbitrary level strings.
            try:
                hookcmds.juju_log(
                    line,
                    level=level,  # type: ignore[arg-type]
                )
            except hookcmds.Error as e:  # noqa: PERF203
                self._check_for_security_event('juju-log', e.returncode, e.stderr)
                raise ModelError(e.stderr) from e

    def network_get(self, binding_name: str, relation_id: int | None = None) -> _NetworkDict:
        """Return network info provided by network-get for a given binding.

        Args:
            binding_name: A name of a binding (relation name or extra-binding name).
            relation_id: An optional relation id to get network info for.
        """
        with self._wrap_hookcmd('network-get', binding_name=binding_name, relation_id=relation_id):
            raw = hookcmds.network_get(binding_name, relation_id=relation_id)
        return {
            'bind-addresses': [
                {
                    'mac-address': b_addr.mac_address,
                    'interface-name': b_addr.interface_name,
                    'addresses': [
                        {'value': addr.value, 'cidr': addr.cidr, 'hostname': addr.hostname}
                        for addr in b_addr.addresses
                    ],
                }
                for b_addr in raw.bind_addresses
            ],
            'ingress-addresses': list(raw.ingress_addresses),
            'egress-subnets': list(raw.egress_subnets),
        }

    def add_metrics(
        self, metrics: Mapping[str, int | float], labels: Mapping[str, str] | None = None
    ) -> None:
        cmd: list[str] = ['add-metric']
        if labels:
            label_args: list[str] = []
            for k, v in labels.items():
                _ModelBackendValidator.validate_metric_label(k)
                _ModelBackendValidator.validate_label_value(k, v)
                label_args.append(f'{k}={v}')
            cmd.extend(['--labels', ','.join(label_args)])

        metric_args: list[str] = []
        for k, v in metrics.items():
            _ModelBackendValidator.validate_metric_key(k)
            metric_value = _ModelBackendValidator.format_metric_value(v)
            metric_args.append(f'{k}={metric_value}')
        cmd.extend(metric_args)
        with self._wrap_hookcmd(*cmd):
            hookcmds._utils.run(*cmd)

    def get_pebble(self, socket_path: str) -> pebble.Client:
        """Create a pebble.Client instance from given socket path."""
        return pebble.Client(socket_path=socket_path)

    def planned_units(self) -> int:
        """Count of "planned" units that will run this application.

        This will include the current unit, any units that are alive, units that are in the process
        of being started, but will not include units that are being shut down.

        """
        # The goal-state will return the information that we need. Goal state as a general
        # concept is being deprecated, however, in favor of approaches such as the one that we use
        # here.
        with self._wrap_hookcmd('goal-state'):
            app_state = hookcmds.goal_state()

        # Planned units can be zero. We don't need to do error checking here.
        # But we need to filter out dying units as they may be reported before being deleted
        num_alive = sum(1 for goal in app_state.units.values() if goal.status != 'dying')
        return num_alive

    def update_relation_data(
        self, relation_id: int, entity: Unit | Application, data: Mapping[str, str]
    ):
        self.relation_set(
            relation_id=relation_id, data=data, is_app=isinstance(entity, Application)
        )

    def secret_get(
        self,
        *,
        id: str | None = None,
        label: str | None = None,
        refresh: bool = False,
        peek: bool = False,
    ) -> dict[str, str]:
        # The type: ignore here is because the type checker can't tell that
        # we will always have refresh or peek but not both, and either id or
        # label.
        with self._wrap_hookcmd('secret-get', id=id, label=label, refresh=refresh, peek=peek):
            return hookcmds.secret_get(
                id=id,
                label=label,  # type: ignore[arg-type]
                refresh=refresh,  # type: ignore[arg-type]
                peek=peek,  # type: ignore[arg-type]
            )

    def secret_info_get(self, *, id: str | None = None, label: str | None = None) -> SecretInfo:
        if id is not None:
            with self._wrap_hookcmd('secret-info-get', id=id):
                raw = hookcmds.secret_info_get(id=id)
        elif label is not None:  # elif because Juju secret-info-get doesn't allow id and label
            with self._wrap_hookcmd('secret-info-get', label=label):
                raw = hookcmds.secret_info_get(label=label)
        else:
            raise TypeError('either `id` or `label` must be provided')
        return SecretInfo(
            raw.id,
            label=raw.label,
            revision=raw.revision,
            expires=raw.expiry,  # Note the different names.
            rotation=SecretRotate(raw.rotation) if raw.rotation else None,
            rotates=raw.rotates,
            description=raw.description,
            model_uuid=self.model_uuid,
        )

    def secret_set(
        self,
        id: str,
        *,
        content: dict[str, str] | None = None,
        label: str | None = None,
        description: str | None = None,
        expire: datetime.datetime | None = None,
        rotate: SecretRotate | None = None,
    ):
        # The content is None or has already been validated with Secret._validate_content
        if self._juju_context.version < '3.6':
            # Older Juju series don't coalesce multiple secret updates within a hook.
            # To work around that, we perform a smart read-modify-write cycle.
            # See https://bugs.launchpad.net/juju/+bug/2081034 for details.
            if content is None:
                content = self.secret_get(id=id, peek=True)
            if description is None or expire is None or rotate is None or label is None:
                # Metadata fix is needed for Juju < 3.6 or < 3.5.5
                info = self.secret_info_get(id=id)
                description = description or info.description
                expire = expire or info.expires
                rotate = rotate or info.rotation
                # The label fix is needed for Juju < 3.5
                label = label or info.label
        with self._wrap_hookcmd(
            'secret-set',
            id=id,
            content=content,
            label=label,
            description=description,
            expire=expire,
            rotate=rotate,
        ):
            hookcmds.secret_set(
                id,
                content=content,
                label=label,
                description=description,
                expire=expire,
                rotate=rotate.value if rotate else None,
            )

    def secret_add(
        self,
        content: dict[str, str],
        *,
        label: str | None = None,
        description: str | None = None,
        expire: datetime.datetime | None = None,
        rotate: SecretRotate | None = None,
        owner: str | None = None,
    ) -> str:
        # The content has already been validated with Secret._validate_content
        with self._wrap_hookcmd(
            'secret-add',
            content=content,
            label=label,
            description=description,
            expire=expire,
            rotate=rotate,
            owner=owner,
        ):
            return hookcmds.secret_add(
                content,
                label=label,
                description=description,
                expire=expire,
                rotate=rotate.value if rotate else None,
                owner=owner,  # type: ignore  # lenient for backwards compatibility
            )

    def secret_grant(self, id: str, relation_id: int, *, unit: str | None = None):
        with self._wrap_hookcmd('secret-grant', id=id, relation_id=relation_id, unit=unit):
            hookcmds.secret_grant(id, relation_id=relation_id, unit=unit)

    def secret_revoke(self, id: str, relation_id: int, *, unit: str | None = None):
        with self._wrap_hookcmd('secret-revoke', id=id, relation_id=relation_id, unit=unit):
            hookcmds.secret_revoke(id, relation_id=relation_id, unit=unit)

    def secret_remove(self, id: str, *, revision: int | None = None):
        with self._wrap_hookcmd('secret-remove', id=id, revision=revision):
            hookcmds.secret_remove(id, revision=revision)

    def open_port(self, protocol: str, port: int | None = None):
        with self._wrap_hookcmd('open-port', protocol=protocol, port=port):
            hookcmds.open_port(protocol, port)

    def close_port(self, protocol: str, port: int | None = None):
        with self._wrap_hookcmd('close-port', protocol=protocol, port=port):
            hookcmds.close_port(protocol, port)

    def opened_ports(self) -> set[Port]:
        with self._wrap_hookcmd('opened-ports'):
            results = hookcmds.opened_ports()
        ports: set[Port] = set()
        for raw_port in results:
            if raw_port.protocol not in ('tcp', 'udp', 'icmp'):
                logger.warning('Unexpected opened-ports protocol: %s', raw_port.protocol)
                continue
            if raw_port.to_port is not None:
                logger.warning('Ignoring opened-ports port range: %s', raw_port)
            port = Port(raw_port.protocol or 'tcp', raw_port.port)
            ports.add(port)
        return ports

    def reboot(self, now: bool = False):
        _log_security_event(
            _SecurityEventLevel.WARN,
            _SecurityEvent.SYS_RESTART,
            str(os.getuid()),
            description=f'Rebooting unit {self.unit_name!r} in model {self.model_name!r}',
        )
        with tracer.start_as_current_span('juju-reboot'):
            if now:
                hookcmds.juju_reboot(now=True)
                # Juju will kill the Charm process, and in testing no code after
                # this point would execute. However, we want to guarantee that for
                # Charmers, so we force that to be the case.
                sys.exit()
            hookcmds.juju_reboot()

    def credential_get(self) -> CloudSpec:
        """Access cloud credentials by running the credential-get hook command.

        Returns the cloud specification used by the model.
        """
        with self._wrap_hookcmd('credential-get'):
            raw_spec = hookcmds.credential_get()
        return CloudSpec._from_hookcmds(raw_spec)


class _ModelBackendValidator:
    """Provides facilities for validating inputs and formatting them for model backends."""

    METRIC_KEY_REGEX = re.compile(r'^[a-zA-Z](?:[a-zA-Z0-9-_]*[a-zA-Z0-9])?$')

    @classmethod
    def validate_metric_key(cls, key: str):
        if cls.METRIC_KEY_REGEX.match(key) is None:
            raise ModelError(
                f'invalid metric key {key!r}: must match {cls.METRIC_KEY_REGEX.pattern}'
            )

    @classmethod
    def validate_metric_label(cls, label_name: str):
        if cls.METRIC_KEY_REGEX.match(label_name) is None:
            raise ModelError(
                f'invalid metric label name {label_name!r}: '
                f'must match {cls.METRIC_KEY_REGEX.pattern}'
            )

    @classmethod
    def format_metric_value(cls, value: int | float):
        if not isinstance(value, (int, float)):
            raise ModelError(
                f'invalid metric value {value!r} provided: must be a positive finite float'
            )

        if math.isnan(value) or math.isinf(value) or value < 0:
            raise ModelError(
                f'invalid metric value {value!r} provided: must be a positive finite float'
            )
        return str(value)

    @classmethod
    def validate_label_value(cls, label: str, value: str):
        # Label values cannot be empty, contain commas or equal signs as those are
        # used by add-metric as separators.
        if not value:
            raise ModelError(f'metric label {label} has an empty value, which is not allowed')
        v = str(value)
        if re.search(r'[,=]', v) is not None:
            raise ModelError(f'metric label values must not contain "," or "=": {label}={value!r}')


class LazyNotice:
    """Provide lazily-loaded access to a Pebble notice's details.

    The attributes provided by this class are the same as those of
    :class:`ops.pebble.Notice`, however, the notice details are only fetched
    from Pebble if necessary (and cached on the instance).
    """

    id: str
    user_id: int | None
    type: pebble.NoticeType | str
    key: str
    first_occurred: datetime.datetime
    last_occurred: datetime.datetime
    last_repeated: datetime.datetime
    occurrences: int
    last_data: dict[str, str]
    repeat_after: datetime.timedelta | None
    expire_after: datetime.timedelta | None

    def __init__(self, container: Container, id: str, type: str, key: str):
        self._container = container
        self.id = id
        try:
            self.type = pebble.NoticeType(type)
        except ValueError:
            self.type = type
        self.key = key

        self._notice: pebble.Notice | None = None

    def __repr__(self):
        type_repr = self.type if isinstance(self.type, pebble.NoticeType) else repr(self.type)
        return f'LazyNotice(id={self.id!r}, type={type_repr}, key={self.key!r})'

    def __getattr__(self, item: str):
        # Note: not called for defined attributes (id, type, key)
        self._ensure_loaded()
        return getattr(self._notice, item)

    def _ensure_loaded(self):
        if self._notice is not None:
            return
        self._notice = self._container.get_notice(self.id)
        assert self._notice.type == self.type
        assert self._notice.key == self.key


class LazyCheckInfo:
    """Provide lazily-loaded access to a Pebble check's info.

    The attributes provided by this class are the same as those of
    :class:`ops.pebble.CheckInfo`, however, the notice details are only fetched
    from Pebble if necessary (and cached on the instance).
    """

    name: str
    level: pebble.CheckLevel | str | None
    startup: pebble.CheckStartup
    status: pebble.CheckStatus | str
    successes: int | None
    failures: int
    threshold: int
    change_id: pebble.ChangeID | None

    def __init__(self, container: Container, name: str):
        self._container = container
        self.name = name
        self._info: pebble.CheckInfo | None = None

    def __repr__(self):
        return f'LazyCheckInfo(name={self.name!r})'

    def __getattr__(self, item: str):
        # Note: not called for defined attribute `name`.
        self._ensure_loaded()
        return getattr(self._info, item)

    def _ensure_loaded(self):
        if self._info is not None:
            return
        self._info = self._container.get_check(self.name)


@dataclasses.dataclass(frozen=True)
class CloudCredential:
    """Credentials for cloud.

    Used as the type of attribute `credential` in :class:`CloudSpec`.
    """

    auth_type: str
    """Authentication type."""

    attributes: dict[str, str] = dataclasses.field(default_factory=dict[str, str])
    """A dictionary containing cloud credentials.

    For example, for AWS, it contains `access-key` and `secret-key`;
    for Azure, `application-id`, `application-password` and `subscription-id`
    can be found here.
    """

    redacted: list[str] = dataclasses.field(default_factory=list[str])
    """A list of redacted secrets."""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CloudCredential:
        """Create a new CloudCredential object from a dictionary."""
        return cls(
            auth_type=d['auth-type'],
            attributes=d.get('attrs') or {},
            redacted=d.get('redacted') or [],
        )

    @classmethod
    def _from_hookcmds(cls, o: hookcmds.CloudCredential) -> CloudCredential:
        """Create a new model.CloudCredential object from a hookcmds.CloudCredential object."""
        return cls(
            auth_type=o.auth_type,
            attributes=o.attributes,
            redacted=o.redacted,
        )


@dataclasses.dataclass(frozen=True)
class CloudSpec:
    """Cloud specification information (metadata) including credentials."""

    type: str
    """Type of the cloud."""

    name: str
    """Juju cloud name."""

    region: str | None = None
    """Region of the cloud."""

    endpoint: str | None = None
    """Endpoint of the cloud."""

    identity_endpoint: str | None = None
    """Identity endpoint of the cloud."""

    storage_endpoint: str | None = None
    """Storage endpoint of the cloud."""

    credential: CloudCredential | None = None
    """Cloud credentials with key-value attributes."""

    ca_certificates: list[str] = dataclasses.field(default_factory=list[str])
    """A list of CA certificates."""

    skip_tls_verify: bool = False
    """Whether to skip TLS verification."""

    is_controller_cloud: bool = False
    """If this is the cloud used by the controller, defaults to False."""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> CloudSpec:
        """Create a new CloudSpec object from a dict parsed from JSON."""
        return cls(
            type=d['type'],
            name=d['name'],
            region=d.get('region') or None,
            endpoint=d.get('endpoint') or None,
            identity_endpoint=d.get('identity-endpoint') or None,
            storage_endpoint=d.get('storage-endpoint') or None,
            credential=CloudCredential.from_dict(d['credential']) if d.get('credential') else None,
            ca_certificates=d.get('cacertificates') or [],
            skip_tls_verify=d.get('skip-tls-verify') or False,
            is_controller_cloud=d.get('is-controller-cloud') or False,
        )

    @classmethod
    def _from_hookcmds(cls, o: hookcmds.CloudSpec) -> CloudSpec:
        """Create a new model.CloudSpec object from a hookcmds.CloudSpec object."""
        return cls(
            type=o.type,
            name=o.name,
            region=o.region,
            endpoint=o.endpoint,
            identity_endpoint=o.identity_endpoint,
            storage_endpoint=o.storage_endpoint,
            credential=CloudCredential._from_hookcmds(o.credential) if o.credential else None,
            ca_certificates=o.ca_certificates,
            skip_tls_verify=o.skip_tls_verify,
            is_controller_cloud=o.is_controller_cloud,
        )
