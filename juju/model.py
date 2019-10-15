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


# TODO: Replace RelationMapping with non-lazy mapping with LazyList values instead.
# Specifically, we want to avoid calling relation-ids for every relation and instead
# only do it on demand for relations that are accessed. That will also allow us to
# get rid of this extra layer of wrapping and just use a plain dict.
class RelationMapping(LazyMapping):
    """Map of relation names to lists of Relation instances."""
    def __init__(self, relation_names, local_unit, backend, cache):
        self._relation_names = relation_names
        self._local_unit = local_unit
        self._backend = backend
        self._cache = cache

    def _load(self):
        data = {}
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
            units = [self._local_unit] + self.units
            self._data = {unit: RelationUnitData(self.relation_id, unit, self._backend) for unit in units}
        return self._data


class RelationUnitData(LazyMapping):
    def __init__(self, relation_id, unit, backend):
        self.relation_id = relation_id
        self.unit = unit
        self._backend = backend

    def _load(self):
        return self._backend.relation_get(self.relation_id, self.unit.name)


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

    def relation_ids(self, relation_name):
        return self._run('relation-ids', relation_name)

    def relation_list(self, relation_id):
        return self._run('relation-list', '-r', relation_id)

    def relation_get(self, relation_id, member_name):
        return self._run('relation-get', '-r', relation_id, '-', member_name)
