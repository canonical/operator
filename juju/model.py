import json
from abc import ABC, abstractmethod
from collections.abc import Mapping
from subprocess import run, PIPE
from weakref import WeakValueDictionary


class Model:
    def __init__(self, local_unit_name, relation_names, backend):
        self._entity_cache = ModelEntityCache(local_unit_name)
        self._backend = backend
        self.relations = RelationMap(relation_names, self._backend, self._entity_cache)
        self.unit = self._entity_cache.get(Unit, local_unit_name)
        self.app = self.unit.app

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


class ModelEntityCache(WeakValueDictionary):
    def __init__(self, local_unit_name):
        super().__init__()
        self.local_unit_name = local_unit_name

    def get(self, entity_type, entity_name):
        key = (entity_type, entity_name)
        entity = super().get(key)
        if entity is None:
            entity = entity_type(entity_name, self)
            self[key] = entity
        return entity


class Application:
    def __init__(self, name, entity_cache):
        self.name = name

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


class Unit:
    def __init__(self, name, entity_cache):
        self.name = name
        self.app = entity_cache.get(Application, name.split('/')[0])

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


class LazyMapping(Mapping, ABC):
    @abstractmethod
    def _load(self):
        raise NotImplementedError()

    @property
    def _data(self):
        if not hasattr(self, '_lazy_data'):
            self._lazy_data = self._load()
        return self._lazy_data

    def __contains__(self, key):
        return key in self._data

    def __len__(self):
        return len(self._data)

    def __iter__(self):
        return iter(self._data)

    def __getitem__(self, key):
        return self._data[key]


class RelationMap(LazyMapping):
    """Map of relation names to lists of Relation instances."""
    def __init__(self, relation_names, backend, entity_cache):
        self._relation_names = relation_names
        self._backend = backend
        self._entity_cache = entity_cache

    def _load(self):
        data = {}
        for relation_name in self._relation_names:
            relations = data[relation_name] = []
            for relation_id in self._backend.relation_ids(relation_name):
                relations.append(Relation(relation_name, relation_id, self._backend, self._entity_cache))
        return data


class Relation:
    def __init__(self, relation_name, relation_id, backend, entity_cache):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._backend = backend
        self.data = RelationData(self.relation_name, relation_id, self._backend, entity_cache)

    @property
    def apps(self):
        return [unit.app for unit in self.units]

    @property
    def units(self):
        return list(self.data.keys())


class RelationData(LazyMapping):
    def __init__(self, relation_name, relation_id, backend, entity_cache):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._backend = backend
        self._entity_cache = entity_cache

    def _load(self):
        data = {}
        for unit_name in self._backend.relation_list(self.relation_id):
            unit = self._entity_cache.get(Unit, unit_name)
            data[unit] = RelationDataBag(self.relation_id, unit, self._backend)
        # Juju's relation-list doesn't include the local unit(s), even though they are part of
        # the relation. Technically, you can also call relation-get for your peers' data, but
        # we don't want to support that, so we only manually add this local unit.
        local_unit = self._entity_cache.get(Unit, self._entity_cache.local_unit_name)
        data[local_unit] = RelationDataBag(self.relation_id, local_unit, self._backend)
        return data


class RelationDataBag(LazyMapping):
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
