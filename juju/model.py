import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from subprocess import run, PIPE
from weakref import WeakValueDictionary


class Model:
    def __init__(self, local_unit_name, relation_names, backend):
        self._cache = ModelCache()
        self._backend = backend
        self.unit = self._cache.get(Unit, local_unit_name)
        self.app = self.unit.app
        self.relations = RelationMapping(relation_names, self.unit, self._backend, self._cache)
        self.config = ConfigData(self._backend)

    def relation(self, relation_name):
        """Return the single Relation object for the named relation, or None.

        This convenience method returns None if the relation is not established, or the
        single Relation if the relation is established only once. If this same relation
        is established multiple times the error TooManyRelatedApps is raised.
        """
        num_related = len(self.relations[relation_name])
        if num_related == 0:
            return None
        elif num_related == 1:
            return self.relations[relation_name][0]
        else:
            # TODO: We need something in the framework to catch and gracefully handle errors,
            # ideally integrating the error catching with Juju's mechanisms.
            raise TooManyRelatedApps(relation_name, num_related, 1)


class ModelCache(WeakValueDictionary):
    def get(self, entity_type, *args):
        key = (entity_type,) + args
        entity = super().get(key)
        if entity is None:
            entity = entity_type(*args, cache=self)
            self[key] = entity
        return entity


class Application:
    def __init__(self, name, cache):
        self.name = name

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


class Unit:
    def __init__(self, name, cache):
        self.name = name
        self.app = cache.get(Application, name.split('/')[0])

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


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


class MutableLazyMapping(ABC):
    @abstractmethod
    def _store(self, key, value):
        raise NotImplementedError()

    @abstractmethod
    def _remove(self, key):
        raise NotImplementedError()

    def __setitem__(self, key, value):
        # We make the external call first on the off chance that it raises an error which is subsequently caught
        # and handled. This way, we don't end up modifying the in-memory value if the external call failed.
        self._store(key, value)
        if self._lazy_data is not None:
            # Don't load data unnecessarily if we're only updating.
            self._data[key] = value

    def __delitem__(self, key):
        # We make the external call first on the off chance that it raises an error which is subsequently caught
        # and handled. This way, we don't end up modifying the in-memory value if the external call failed.
        self._remove(key)
        if self._lazy_data is not None:
            # Don't load data unnecessarily if we're only updating.
            del self._data[key]


class RelationMapping(LazyMapping):
    """Map of relation names to lists of Relation instances."""
    def __init__(self, relation_names, local_unit, backend, cache):
        self._relation_names = relation_names
        self._local_unit = local_unit
        self._backend = backend
        self._cache = cache

    def _load(self):
        data = {}
        # TODO: Make this more lazy. We don't want to call relation-ids for relations that we don't access.
        for relation_name in self._relation_names:
            relations = data[relation_name] = []
            for relation_id in self._backend.relation_ids(relation_name):
                relations.append(Relation(relation_name, relation_id, self._local_unit, self._backend, self._cache))
        return data


class Relation:
    def __init__(self, relation_name, relation_id, local_unit, backend, cache):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._local_unit = local_unit
        self._backend = backend
        self._cache = cache
        self._apps = None
        self._units = None
        self._data = None

    @property
    def apps(self):
        if self._apps is None:
            self._apps = list({unit.app for unit in self.units})
        return self._apps

    @property
    def units(self):
        if self._units is None:
            self._units = []
            for unit_name in self._backend.relation_list(self.relation_id):
                self._units.append(self._cache.get(Unit, unit_name))
        return self._units

    @property
    def data(self):
        if self._data is None:
            self._data = RelationData(self.relation_name, self.relation_id, self._local_unit, self.units, self._backend)
        return self._data


class RelationData(Mapping):
    def __init__(self, relation_name, relation_id, local_unit, remote_units, backend):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._data = {local_unit: MutableRelationUnitData(relation_id, local_unit, backend)}
        self._data.update({unit: RelationUnitData(relation_id, unit, backend) for unit in remote_units})

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key):
        return self._data[key]


class RelationUnitData(LazyMapping):
    def __init__(self, relation_id, unit, backend):
        self.relation_id = relation_id
        self.unit = unit
        self._backend = backend

    def _load(self):
        # TODO: We will need to ensure we properly handle modifications when support for those are added.
        # Specifically, if we're caching relation data in memory, modifications need to affect both the
        # in-memory cache as well as calling out to relation-set.
        return self._backend.relation_get(self.relation_id, self.unit.name)


class MutableRelationUnitData(RelationUnitData, MutableLazyMapping):
    def _store(self, key, value):
        self._backend.relation_set(self.relation_id, key, value)

    def _remove(self, key):
        # Relation values are simple strings only, and setting the value to an empty string will actually
        # remove the key from the relation. Note that this implies that there is no way to distinguish
        # between a missing key, an empty string, or an explicit None value without some form of encoding,
        # such as JSON.
        self._store(key, '')

    def __setitem__(self, key, value):
        if not isinstance(value, str):
            raise TypeError('Relation data values must be strings')
        if value == '':
            # Setting a relation data value to an empty string will actually remove the key from the relation.
            # We need to ensure that this is reflected in-memory as well.
            del self[key]
        else:
            super().__setitem__(key, value)


class ConfigData(LazyMapping):
    def __init__(self, backend):
        self._backend = backend

    def _load(self):
        return self._backend.config_get()


class ModelError(Exception):
    pass


class TooManyRelatedApps(ModelError):
    def __init__(self, relation_name, num_related, max_supported):
        super().__init__(f'Too many remote applications on {relation_name} ({num_related} > {max_supported})')
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class ModelBackend:
    def _run(self, *args):
        return json.loads(run(args + ('--format=json',), stdout=PIPE, check=True).stdout.decode('utf8'))

    def _run_no_output(self, *args):
        run(args, check=True)

    def relation_ids(self, relation_name):
        return self._run('relation-ids', relation_name)

    def relation_list(self, relation_id):
        return self._run('relation-list', '-r', relation_id)

    def relation_get(self, relation_id, member_name):
        return self._run('relation-get', '-r', relation_id, '-', member_name)

    def relation_set(self, relation_id, key, value):
        return self._run_no_output('relation-set', '-r', relation_id, f'{key}={value}')

    def config_get(self):
        return self._run('config-get')
