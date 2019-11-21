import json
import weakref
import os
from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping
from subprocess import run, PIPE, CalledProcessError


class Model:
    def __init__(self, local_unit_name, relation_names, backend):
        self._cache = ModelCache(backend)
        self._backend = backend
        self.unit = self.get_unit(local_unit_name)
        self.app = self.unit.app
        self.relations = RelationMapping(
            relation_names, self.unit, self._backend, self._cache
        )
        self.config = ConfigData(self._backend)

    def get_relation(self, relation_name, relation_id=None):
        """Get a specific Relation instance.

        If relation_id is given, this will return that Relation instance.

        If relation_id is not given, this will return the Relation instance if the
        relation is established only once or None if it is not established. If this
        same relation is established multiple times the error TooManyRelatedApps is raised.
        """
        if relation_id is not None:
            if not isinstance(relation_id, int):
                raise ModelError(
                    f"relation id {relation_id} must be an int not {type(relation_id).__name__}"
                )
            for relation in self.relations[relation_name]:
                if relation.id == relation_id:
                    return relation
            else:
                # The relation may be dead, but it is not forgotten.
                return Relation(
                    relation_name, relation_id, self.unit, self._backend, self._cache
                )
        else:
            num_related = len(self.relations[relation_name])
            if num_related == 0:
                return None
            elif num_related == 1:
                return self.relations[relation_name][0]
            else:
                # TODO: We need something in the framework to catch and gracefully handle
                # errors, ideally integrating the error catching with Juju's mechanisms.
                raise TooManyRelatedApps(relation_name, num_related, 1)

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

        self.is_local = self.name == self._backend.local_app_name

    def __repr__(self):
        return f"<{type(self).__module__}.{type(self).__name__} {self.name}>"


class Unit:
    def __init__(self, name, backend, cache):
        self.name = name

        app_name = name.split("/")[0]
        self.app = cache.get(Application, app_name)

        self._backend = backend
        self._cache = cache

        self.is_local = self.name == self._backend.local_unit_name

    def __repr__(self):
        return f"<{type(self).__module__}.{type(self).__name__} {self.name}>"


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
                relation_list.append(
                    Relation(
                        relation_name,
                        relation_id,
                        self._local_unit,
                        self._backend,
                        self._cache,
                    )
                )
        return relation_list


class Relation:
    def __init__(self, relation_name, relation_id, local_unit, backend, cache):
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
        except RelationNotFound:
            # If the relation is dead, just treat it as if it has no remote units.
            pass
        self.data = RelationData(self, local_unit, backend)

    def __repr__(self):
        return f"<{type(self).__module__}.{type(self).__name__} {self.name}:{self.id}>"


class RelationData(Mapping):
    def __init__(self, relation, local_unit, backend):
        self.relation = weakref.proxy(relation)
        self._data = {
            local_unit: RelationUnitData(self.relation, local_unit, True, backend)
        }
        self._data.update(
            {
                unit: RelationUnitData(self.relation, unit, False, backend)
                for unit in self.relation.units
            }
        )

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
        except RelationNotFound:
            # Dead relations tell no tales (and have no data).
            return {}

    def __setitem__(self, key, value):
        if not self._is_mutable:
            raise RelationDataError(f"cannot set relation data for {self.unit.name}")
        if not isinstance(value, str):
            raise RelationDataError("relation data values must be strings")
        self._backend.relation_set(self.relation.id, key, value)
        # Don't load data unnecessarily if we're only updating.
        if self._lazy_data is not None:
            if value == "":
                # Match the behavior of Juju, which is that setting the value to an empty string will
                # remove the key entirely from the relation data.
                del self._data[key]
            else:
                self._data[key] = value

    def __delitem__(self, key):
        # Match the behavior of Juju, which is that setting the value to an empty string will
        # remove the key entirely from the relation data.
        self.__setitem__(key, "")


class ConfigData(LazyMapping):
    def __init__(self, backend):
        self._backend = backend

    def _load(self):
        return self._backend.config_get()


class ModelError(Exception):
    pass


class TooManyRelatedApps(ModelError):
    def __init__(self, relation_name, num_related, max_supported):
        super().__init__(
            f"Too many remote applications on {relation_name} ({num_related} > {max_supported})"
        )
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class RelationDataError(ModelError):
    pass


class RelationNotFound(ModelError):
    pass


class ModelBackend:
    def __init__(self):
        self.local_unit_name = os.environ["JUJU_UNIT_NAME"]
        self.local_app_name = self.local_unit_name.split("/")[0]

    def _run(self, *args):
        result = run(args + ("--format=json",), stdout=PIPE, stderr=PIPE, check=True)
        text = result.stdout.decode("utf8")
        data = json.loads(text)
        return data

    def _run_no_output(self, *args):
        run(args, check=True)

    def relation_ids(self, relation_name):
        relation_ids = self._run("relation-ids", relation_name)
        return [int(relation_id.split(":")[-1]) for relation_id in relation_ids]

    def relation_list(self, relation_id):
        try:
            return self._run("relation-list", "-r", str(relation_id))
        except CalledProcessError as e:
            # TODO: This should use the return code if it is specific enough rather than the message.
            # It seems to be 2 for this error, but I haven't been able to confirm yet if that might
            # also apply to other error cases.
            if b"relation not found" in e.stderr:
                raise RelationNotFound() from e
            else:
                raise

    def relation_get(self, relation_id, member_name):
        try:
            return self._run("relation-get", "-r", str(relation_id), "-", member_name)
        except CalledProcessError as e:
            # TODO: This should use the return code if it is specific enough rather than the message.
            # It seems to be 2 for this error, but I haven't been able to confirm yet if that might
            # also apply to other error cases.
            if b"relation not found" in e.stderr:
                raise RelationNotFound() from e
            else:
                raise

    def relation_set(self, relation_id, key, value):
        try:
            return self._run_no_output(
                "relation-set", "-r", str(relation_id), f"{key}={value}"
            )
        except CalledProcessError as e:
            if b"relation not found" in e.stderr:
                raise RelationNotFound() from e
            else:
                raise

    def config_get(self):
        return self._run("config-get")
