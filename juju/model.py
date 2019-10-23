import json
from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping
from subprocess import run, PIPE
from weakref import WeakValueDictionary


class Model:
    def __init__(self, local_unit_name, relation_names, backend):
        self._cache = ModelCache()
        self._backend = backend
        self.unit = self.get_unit(local_unit_name)
        self.app = self.unit.app
        self.relations = RelationMapping(relation_names, self.unit, self._backend, self._cache)
        self.config = ConfigData(self._backend)

    def get_relation(self, relation_name):
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

    def get_relation_by_id(self, relation_name, relation_id):
        def _norm(relation_id):
            # Relation IDs can be in the form '{relation_name}:{id}', so we need to
            # normalize them to just '{id}' for comparison.
            return relation_id.split(':')[-1]

        for relation in self.relations[relation_name]:
            if _norm(relation.relation_id) == _norm(relation_id):
                return relation
        else:
            # The relation may be dead, but it is not forgotten.
            return DeadRelation(relation_name, relation_id)

    def get_unit(self, unit_name):
        return self._cache.get(Unit, unit_name)


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


class RelationMapping(Mapping):
    """Map of relation names to lists of Relation instances."""
    def __init__(self, relation_names, local_unit, backend, cache):
        self._local_unit = local_unit
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
                relation_list.append(Relation(relation_name, relation_id, self._local_unit, self._backend, self._cache))
        return relation_list


class Relation:
    def __init__(self, relation_name, relation_id, local_unit, backend, cache):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self.apps = set()
        self.units = set()
        for unit_name in backend.relation_list(relation_id):
            unit = cache.get(Unit, unit_name)
            self.units.add(unit)
            self.apps.add(unit.app)
        self.data = RelationData(relation_name, relation_id, local_unit, self.units, backend)


class DeadRelation(Relation):
    def __init__(self, relation_name, relation_id):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self.apps = set()
        self.units = set()
        self.data = RelationData(relation_name, relation_id, None, None, None)


class RelationData(Mapping):
    def __init__(self, relation_name, relation_id, local_unit, remote_units, backend):
        self.relation_name = relation_name
        self.relation_id = relation_id
        if local_unit:
            self._data = {local_unit: RelationUnitData(relation_id, local_unit, True, backend)}
            self._data.update({unit: RelationUnitData(relation_id, unit, False, backend) for unit in remote_units})
        else:
            # If we don't have even a local unit, then we're dealing with a dead relation;
            # and dead relations tell no tales.
            self._data = {}

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
    def __init__(self, relation_id, unit, is_mutable, backend):
        self.relation_id = relation_id
        self.unit = unit
        self._is_mutable = is_mutable
        self._backend = backend

    def _load(self):
        # TODO: We will need to ensure we properly handle modifications when support for those are added.
        # Specifically, if we're caching relation data in memory, modifications need to affect both the
        # in-memory cache as well as calling out to relation-set.
        return self._backend.relation_get(self.relation_id, self.unit.name)

    def __setitem__(self, key, value):
        if not self._is_mutable:
            raise RelationDataError(f'cannot set relation data for {self.unit.name}')
        if not isinstance(value, str):
            raise RelationDataError('relation data values must be strings')
        self._backend.relation_set(self.relation_id, key, value)
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


class ModelError(Exception):
    pass


class TooManyRelatedApps(ModelError):
    def __init__(self, relation_name, num_related, max_supported):
        super().__init__(f'Too many remote applications on {relation_name} ({num_related} > {max_supported})')
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class RelationDataError(ModelError):
    pass


class ModelBackend:
    def _run(self, *args):
        result = run(args + ('--format=json',), stdout=PIPE, check=True)
        text = result.stdout.decode('utf8')
        data = json.loads(text)
        return data

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
