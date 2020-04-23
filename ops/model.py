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

import json
import weakref
import os
import shutil
import tempfile
import time
import datetime
import re
import ipaddress
import decimal

from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from subprocess import run, PIPE, CalledProcessError


class Model:

    def __init__(self, unit_name, meta, backend):
        self._cache = _ModelCache(backend)
        self._backend = backend
        self.unit = self.get_unit(unit_name)
        self.app = self.unit.app
        self.relations = RelationMapping(meta.relations, self.unit, self._backend, self._cache)
        self.config = ConfigData(self._backend)
        self.resources = Resources(list(meta.resources), self._backend)
        self.pod = Pod(self._backend)
        self.storages = StorageMapping(list(meta.storages), self._backend)
        self._bindings = BindingMapping(self._backend)

    def get_unit(self, unit_name):
        return self._cache.get(Unit, unit_name)

    def get_app(self, app_name):
        return self._cache.get(Application, app_name)

    def get_relation(self, relation_name, relation_id=None):
        """Get a specific Relation instance.

        If relation_id is given, this will return that Relation instance.

        If relation_id is not given, this will return the Relation instance if the
        relation is established only once or None if it is not established. If this
        same relation is established multiple times the error TooManyRelatedAppsError is raised.
        """
        return self.relations._get_unique(relation_name, relation_id)

    def get_binding(self, binding_key):
        """Get a network space binding.

        binding_key -- The relation name or instance to obtain bindings for.

        If binding_key is a relation name, the method returns the default binding for that
        relation. If a relation instance is provided, the method first looks up a more specific
        binding for that specific relation ID, and if none is found falls back to the default
        binding for the relation name.
        """
        return self._bindings.get(binding_key)


class _ModelCache:

    def __init__(self, backend):
        self._backend = backend
        self._weakrefs = weakref.WeakValueDictionary()

    def get(self, entity_type, *args):
        key = (entity_type,) + args
        entity = self._weakrefs.get(key)
        if entity is None:
            entity = entity_type(*args, backend=self._backend, cache=self)
            self._weakrefs[key] = entity
        return entity


class Application:

    def __init__(self, name, backend, cache):
        self.name = name
        self._backend = backend
        self._cache = cache
        self._is_our_app = self.name == self._backend.app_name
        self._status = None

    @property
    def status(self):
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
    def status(self, value):
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

    def __repr__(self):
        return '<{}.{} {}>'.format(type(self).__module__, type(self).__name__, self.name)


class Unit:

    def __init__(self, name, backend, cache):
        self.name = name

        app_name = name.split('/')[0]
        self.app = cache.get(Application, app_name)

        self._backend = backend
        self._cache = cache
        self._is_our_unit = self.name == self._backend.unit_name
        self._status = None

    @property
    def status(self):
        if not self._is_our_unit:
            return UnknownStatus()

        if self._status:
            return self._status

        s = self._backend.status_get(is_app=False)
        self._status = StatusBase.from_name(s['status'], s['message'])
        return self._status

    @status.setter
    def status(self, value):
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

    def is_leader(self):
        if self._is_our_unit:
            # This value is not cached as it is not guaranteed to persist for the whole duration
            # of a hook execution.
            return self._backend.is_leader()
        else:
            raise RuntimeError(
                'cannot determine leadership status for remote applications: {}'.format(self)
            )

    def set_workload_version(self, version):
        """Record the version of the software running as the workload.

        This shouldn't be confused with the revision of the charm. This is informative only;
        shown in the output of 'juju status'.
        """
        if not isinstance(version, str):
            raise TypeError("workload version must be a str, not {}: {!r}".format(
                type(version).__name__, version))
        self._backend.application_version_set(version)


class LazyMapping(Mapping, ABC):

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


class RelationMapping(Mapping):
    """Map of relation names to lists of Relation instances."""

    def __init__(self, relations_meta, our_unit, backend, cache):
        self._peers = set()
        for name, relation_meta in relations_meta.items():
            if relation_meta.role == 'peers':
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

    def __init__(self, backend):
        self._backend = backend
        self._data = {}

    def get(self, binding_key):
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
    """Binding to a network space."""

    def __init__(self, name, relation_id, backend):
        self.name = name
        self._relation_id = relation_id
        self._backend = backend
        self._network = None

    @property
    def network(self):
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
    """Network space details."""

    def __init__(self, network_info):
        self.interfaces = []
        # Treat multiple addresses on an interface as multiple logical
        # interfaces with the same name.
        for interface_info in network_info['bind-addresses']:
            interface_name = interface_info['interface-name']
            for address_info in interface_info['addresses']:
                self.interfaces.append(NetworkInterface(interface_name, address_info))
        self.ingress_addresses = []
        for address in network_info['ingress-addresses']:
            self.ingress_addresses.append(ipaddress.ip_address(address))
        self.egress_subnets = []
        for subnet in network_info['egress-subnets']:
            self.egress_subnets.append(ipaddress.ip_network(subnet))

    @property
    def bind_address(self):
        return self.interfaces[0].address

    @property
    def ingress_address(self):
        return self.ingress_addresses[0]


class NetworkInterface:

    def __init__(self, name, address_info):
        self.name = name
        # TODO: expose a hardware address here, see LP: #1864070.
        self.address = ipaddress.ip_address(address_info['value'])
        cidr = address_info['cidr']
        if not cidr:
            # The cidr field may be empty, see LP: #1864102.
            # In this case, make it a /32 or /128 IP network.
            self.subnet = ipaddress.ip_network(address_info['value'])
        else:
            self.subnet = ipaddress.ip_network(cidr)
        # TODO: expose a hostname/canonical name for the address here, see LP: #1864086.


class Relation:
    def __init__(self, relation_name, relation_id, is_peer, our_unit, backend, cache):
        self.name = relation_name
        self.id = relation_id
        self.app = None
        self.units = set()

        # For peer relations, both the remote and the local app are the same.
        if is_peer:
            self.app = our_unit.app
        try:
            for unit_name in backend.relation_list(self.id):
                unit = cache.get(Unit, unit_name)
                self.units.add(unit)
                if self.app is None:
                    self.app = unit.app
        except RelationNotFoundError:
            # If the relation is dead, just treat it as if it has no remote units.
            pass
        self.data = RelationData(self, our_unit, backend)

    def __repr__(self):
        return '<{}.{} {}:{}>'.format(type(self).__module__,
                                      type(self).__name__,
                                      self.name,
                                      self.id)


class RelationData(Mapping):
    def __init__(self, relation, our_unit, backend):
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


# We mix in MutableMapping here to get some convenience implementations, but whether it's actually
# mutable or not is controlled by the flag.
class RelationDataContent(LazyMapping, MutableMapping):

    def __init__(self, relation, entity, backend):
        self.relation = relation
        self._entity = entity
        self._backend = backend
        self._is_app = isinstance(entity, Application)

    def _load(self):
        try:
            return self._backend.relation_get(self.relation.id, self._entity.name, self._is_app)
        except RelationNotFoundError:
            # Dead relations tell no tales (and have no data).
            return {}

    def _is_mutable(self):
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
                del self._data[key]
            else:
                self._data[key] = value

    def __delitem__(self, key):
        # Match the behavior of Juju, which is that setting the value to an empty
        # string will remove the key entirely from the relation data.
        self.__setitem__(key, '')


class ConfigData(LazyMapping):

    def __init__(self, backend):
        self._backend = backend

    def _load(self):
        return self._backend.config_get()


class StatusBase:
    """Status values specific to applications and units."""

    _statuses = {}

    def __init__(self, message):
        self.message = message

    def __new__(cls, *args, **kwargs):
        if cls is StatusBase:
            raise TypeError("cannot instantiate a base class")
        cls._statuses[cls.name] = cls
        return super().__new__(cls)

    @classmethod
    def from_name(cls, name, message):
        return cls._statuses[name](message)


class ActiveStatus(StatusBase):
    """The unit is ready.

    The unit believes it is correctly offering all the services it has been asked to offer.
    """
    name = 'active'

    def __init__(self, message=None):
        super().__init__(message or '')


class BlockedStatus(StatusBase):
    """The unit requires manual intervention.

    An operator has to manually intervene to unblock the unit and let it proceed.
    """
    name = 'blocked'


class MaintenanceStatus(StatusBase):
    """The unit is performing maintenance tasks.

    The unit is not yet providing services, but is actively doing work in preparation
    for providing those services.  This is a "spinning" state, not an error state. It
    reflects activity on the unit itself, not on peers or related units.

    """
    name = 'maintenance'


class UnknownStatus(StatusBase):
    """The unit status is unknown.

    A unit-agent has finished calling install, config-changed and start, but the
    charm has not called status-set yet.

    """
    name = 'unknown'

    def __init__(self):
        # Unknown status cannot be set and does not have a message associated with it.
        super().__init__('')


class WaitingStatus(StatusBase):
    """A unit is unable to progress.

    The unit is unable to progress to an active state because an application to which
    it is related is not running.

    """
    name = 'waiting'


class Resources:
    """Object representing resources for the charm.
    """

    def __init__(self, names, backend):
        self._backend = backend
        self._paths = {name: None for name in names}

    def fetch(self, name):
        """Fetch the resource from the controller or store.

        If successfully fetched, this returns a Path object to where the resource is stored
        on disk, otherwise it raises a ModelError.
        """
        if name not in self._paths:
            raise RuntimeError('invalid resource name: {}'.format(name))
        if self._paths[name] is None:
            self._paths[name] = Path(self._backend.resource_get(name))
        return self._paths[name]


class Pod:
    def __init__(self, backend):
        self._backend = backend

    def set_spec(self, spec, k8s_resources=None):
        if not self._backend.is_leader():
            raise ModelError('cannot set a pod spec as this unit is not a leader')
        self._backend.pod_spec_set(spec, k8s_resources)


class StorageMapping(Mapping):
    """Map of storage names to lists of Storage instances."""

    def __init__(self, storage_names, backend):
        self._backend = backend
        self._storage_map = {storage_name: None for storage_name in storage_names}

    def __contains__(self, key):
        return key in self._storage_map

    def __len__(self):
        return len(self._storage_map)

    def __iter__(self):
        return iter(self._storage_map)

    def __getitem__(self, storage_name):
        storage_list = self._storage_map[storage_name]
        if storage_list is None:
            storage_list = self._storage_map[storage_name] = []
            for storage_id in self._backend.storage_list(storage_name):
                storage_list.append(Storage(storage_name, storage_id, self._backend))
        return storage_list

    def request(self, storage_name, count=1):
        """Requests new storage instances of a given name.

        Uses storage-add tool to request additional storage. Juju will notify the unit
        via <storage-name>-storage-attached events when it becomes available.
        """
        if storage_name not in self._storage_map:
            raise ModelError(('cannot add storage {!r}:'
                              ' it is not present in the charm metadata').format(storage_name))
        self._backend.storage_add(storage_name, count)


class Storage:

    def __init__(self, storage_name, storage_id, backend):
        self.name = storage_name
        self.id = storage_id
        self._backend = backend
        self._location = None

    @property
    def location(self):
        if self._location is None:
            raw = self._backend.storage_get('{}/{}'.format(self.name, self.id), "location")
            self._location = Path(raw)
        return self._location


class ModelError(Exception):
    pass


class TooManyRelatedAppsError(ModelError):
    def __init__(self, relation_name, num_related, max_supported):
        super().__init__('Too many remote applications on {} ({} > {})'.format(
            relation_name, num_related, max_supported))
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class RelationDataError(ModelError):
    pass


class RelationNotFoundError(ModelError):
    pass


class InvalidStatusError(ModelError):
    pass


class ModelBackend:

    LEASE_RENEWAL_PERIOD = datetime.timedelta(seconds=30)

    def __init__(self):
        self.unit_name = os.environ['JUJU_UNIT_NAME']
        self.app_name = self.unit_name.split('/')[0]

        self._is_leader = None
        self._leader_check_time = None

    def _run(self, *args, return_output=False, use_json=False):
        kwargs = dict(stdout=PIPE, stderr=PIPE)
        if use_json:
            args += ('--format=json',)
        try:
            result = run(args, check=True, **kwargs)
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

    def relation_ids(self, relation_name):
        relation_ids = self._run('relation-ids', relation_name, return_output=True, use_json=True)
        return [int(relation_id.split(':')[-1]) for relation_id in relation_ids]

    def relation_list(self, relation_id):
        try:
            return self._run('relation-list', '-r', str(relation_id),
                             return_output=True, use_json=True)
        except ModelError as e:
            if 'relation not found' in str(e):
                raise RelationNotFoundError() from e
            raise

    def relation_get(self, relation_id, member_name, is_app):
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_get must be a boolean')

        try:
            return self._run('relation-get', '-r', str(relation_id),
                             '-', member_name, '--app={}'.format(is_app),
                             return_output=True, use_json=True)
        except ModelError as e:
            if 'relation not found' in str(e):
                raise RelationNotFoundError() from e
            raise

    def relation_set(self, relation_id, key, value, is_app):
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter to relation_set must be a boolean')

        try:
            return self._run('relation-set', '-r', str(relation_id),
                             '{}={}'.format(key, value), '--app={}'.format(is_app))
        except ModelError as e:
            if 'relation not found' in str(e):
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
            spec_path = tmpdir / 'spec.json'
            spec_path.write_text(json.dumps(spec))
            args = ['--file', str(spec_path)]
            if k8s_resources:
                k8s_res_path = tmpdir / 'k8s-resources.json'
                k8s_res_path.write_text(json.dumps(k8s_resources))
                args.extend(['--k8s-resources', str(k8s_res_path)])
            self._run('pod-spec-set', *args)
        finally:
            shutil.rmtree(str(tmpdir))

    def status_get(self, *, is_app=False):
        """Get a status of a unit or an application.

        app -- A boolean indicating whether the status should be retrieved for a unit
               or an application.
        """
        return self._run('status-get', '--include-data', '--application={}'.format(is_app))

    def status_set(self, status, message='', *, is_app=False):
        """Set a status of a unit or an application.

        app -- A boolean indicating whether the status should be set for a unit or an
               application.
        """
        if not isinstance(is_app, bool):
            raise TypeError('is_app parameter must be boolean')
        return self._run('status-set', '--application={}'.format(is_app), status, message)

    def storage_list(self, name):
        return [int(s.split('/')[1]) for s in self._run('storage-list', name,
                                                        return_output=True, use_json=True)]

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
        self._run('action-set', *["{}={}".format(k, v) for k, v in results.items()])

    def action_log(self, message):
        self._run('action-log', message)

    def action_fail(self, message=''):
        self._run('action-fail', message)

    def application_version_set(self, version):
        self._run('application-version-set', '--', version)

    def juju_log(self, level, message):
        self._run('juju-log', '--log-level', level, message)

    def network_get(self, binding_name, relation_id=None):
        """Return network info provided by network-get for a given binding.

        binding_name -- A name of a binding (relation name or extra-binding name).
        relation_id -- An optional relation id to get network info for.
        """
        cmd = ['network-get', binding_name]
        if relation_id is not None:
            cmd.extend(['-r', str(relation_id)])
        try:
            return self._run(*cmd, return_output=True, use_json=True)
        except ModelError as e:
            if 'relation not found' in str(e):
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
        try:
            decimal_value = decimal.Decimal.from_float(value)
        except TypeError as e:
            e2 = ModelError('invalid metric value {!r} provided:'
                            ' must be a positive finite float'.format(value))
            raise e2 from e
        if decimal_value.is_nan() or decimal_value.is_infinite() or decimal_value < 0:
            raise ModelError('invalid metric value {!r} provided:'
                             ' must be a positive finite float'.format(value))
        return str(decimal_value)

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
