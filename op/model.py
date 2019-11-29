import json
import weakref
import os
import shutil
import tempfile
import time
import datetime


from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping
from pathlib import Path
from subprocess import run, PIPE, CalledProcessError


class Model:
    def __init__(self, unit_name, meta, backend):
        self._cache = ModelCache(backend)
        self._backend = backend
        self.unit = self.get_unit(unit_name)
        self.app = self.unit.app
        self.relations = RelationMapping(list(meta.relations), self.unit, self._backend, self._cache)
        self.config = ConfigData(self._backend)
        self.resources = Resources(list(meta.resources), self._backend)
        self.pod = Pod(self._backend)

    def get_relation(self, relation_name, relation_id=None):
        """Get a specific Relation instance.

        If relation_id is given, this will return that Relation instance.

        If relation_id is not given, this will return the Relation instance if the
        relation is established only once or None if it is not established. If this
        same relation is established multiple times the error TooManyRelatedAppsError is raised.
        """
        if relation_id is not None:
            if not isinstance(relation_id, int):
                raise ModelError(f'relation id {relation_id} must be an int not {type(relation_id).__name__}')
            for relation in self.relations[relation_name]:
                if relation.id == relation_id:
                    return relation
            else:
                # The relation may be dead, but it is not forgotten.
                return Relation(relation_name, relation_id, self.unit, self._backend, self._cache)
        else:
            num_related = len(self.relations[relation_name])
            if num_related == 0:
                return None
            elif num_related == 1:
                return self.relations[relation_name][0]
            else:
                # TODO: We need something in the framework to catch and gracefully handle
                # errors, ideally integrating the error catching with Juju's mechanisms.
                raise TooManyRelatedAppsError(relation_name, num_related, 1)

    def get_unit(self, unit_name):
        return self._cache.get(Unit, unit_name)


class ModelCache:

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

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


class Unit:
    def __init__(self, name, backend, cache):
        self.name = name

        app_name = name.split('/')[0]
        self.app = cache.get(Application, app_name)

        self._backend = backend
        self._cache = cache

        self._is_our_unit = self.name == self._backend.unit_name

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'

    def is_leader(self):
        if self._is_our_unit:
            # This value is not cached as it is not guaranteed to persist for the whole duration
            # of a hook execution.
            return self._backend.is_leader()
        else:
            raise RuntimeError(f"cannot determine leadership status for remote applications: {self}")

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

    def __init__(self, relation_names, our_unit, backend, cache):
        self._our_unit = our_unit
        self._backend = backend
        self._cache = cache
        self._data = {relation_name: None for relation_name in relation_names}

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, relation_name):
        relation_list = self._data[relation_name]
        if relation_list is None:
            relation_list = self._data[relation_name] = []
            for relation_id in self._backend.relation_ids(relation_name):
                relation_list.append(Relation(relation_name, relation_id, self._our_unit, self._backend, self._cache))
        return relation_list


class Relation:
    def __init__(self, relation_name, relation_id, our_unit, backend, cache):
        self.name = relation_name
        self.id = relation_id
        self.app = None
        self.units = set()
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
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}:{self.id}>'


class RelationData(Mapping):
    def __init__(self, relation, our_unit, backend):
        self.relation = weakref.proxy(relation)
        self._data = {our_unit: RelationUnitData(self.relation, our_unit, True, backend)}
        self._data.update({unit: RelationUnitData(self.relation, unit, False, backend) for unit in self.relation.units})

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
class RelationUnitData(LazyMapping, MutableMapping):
    def __init__(self, relation, unit, is_mutable, backend):
        self.relation = relation
        self.unit = unit
        self._is_mutable = is_mutable
        self._backend = backend

    def _load(self):
        try:
            return self._backend.relation_get(self.relation.id, self.unit.name)
        except RelationNotFoundError:
            # Dead relations tell no tales (and have no data).
            return {}

    def __setitem__(self, key, value):
        if not self._is_mutable:
            raise RelationDataError(f'cannot set relation data for {self.unit.name}')
        if not isinstance(value, str):
            raise RelationDataError('relation data values must be strings')
        self._backend.relation_set(self.relation.id, key, value)
        # Don't load data unnecessarily if we're only updating.
        if self._lazy_data is not None:
            if value == '':
                # Match the behavior of Juju, which is that setting the value to an empty string will
                # remove the key entirely from the relation data.
                del self._data[key]
            else:
                self._data[key] = value

    def __delitem__(self, key):
        # Match the behavior of Juju, which is that setting the value to an empty string will
        # remove the key entirely from the relation data.
        self.__setitem__(key, '')


class ConfigData(LazyMapping):
    def __init__(self, backend):
        self._backend = backend

    def _load(self):
        return self._backend.config_get()


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
            raise RuntimeError(f'invalid resource name: {name}')
        if self._paths[name] is None:
            self._paths[name] = Path(self._backend.resource_get(name))
        return self._paths[name]


class Pod:
    def __init__(self, backend):
        self._backend = backend

    def set_spec(self, spec, k8s_resources=None):
        self._backend.pod_spec_set(spec, k8s_resources)


class ModelError(Exception):
    pass

class TooManyRelatedAppsError(ModelError):
    def __init__(self, relation_name, num_related, max_supported):
        super().__init__(f'Too many remote applications on {relation_name} ({num_related} > {max_supported})')
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class RelationDataError(ModelError):
    pass


class RelationNotFoundError(ModelError):
    pass


class ModelBackend:

    LEASE_RENEWAL_PERIOD = datetime.timedelta(seconds=30)

    def __init__(self):
        self.unit_name = os.environ['JUJU_UNIT_NAME']
        self.app_name = self.unit_name.split('/')[0]

        self._is_leader = None
        self._leader_check_time = 0

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
            return self._run('relation-list', '-r', str(relation_id), return_output=True, use_json=True)
        except ModelError as e:
            if 'relation not found' in str(e):
                raise RelationNotFoundError() from e
            raise

    def relation_get(self, relation_id, member_name):
        try:
            return self._run('relation-get', '-r', str(relation_id), '-', member_name, return_output=True, use_json=True)
        except ModelError as e:
            if 'relation not found' in str(e):
                raise RelationNotFoundError() from e
            raise

    def relation_set(self, relation_id, key, value):
        try:
            return self._run('relation-set', '-r', str(relation_id), f'{key}={value}')
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
        time_since_check = datetime.timedelta(seconds=now - self._leader_check_time)
        if time_since_check > self.LEASE_RENEWAL_PERIOD or self._is_leader is None:
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
            args = ['--spec', str(spec_path)]
            if k8s_resources:
                k8s_res_path = tmpdir / 'k8s-resources.json'
                k8s_res_path.write_text(json.dumps(k8s_resources))
                args.extend(['--k8s-resources', str(k8s_res_path)])
            self._run('pod-spec-set', *args)
        finally:
            shutil.rmtree(tmpdir)
