import json
import weakref
from abc import ABC, abstractmethod
from collections.abc import Mapping, MutableMapping
from subprocess import run, PIPE, CalledProcessError
from enum import Enum, unique


class Model:
    def __init__(self, local_unit_name, relation_names, backend):
        self._cache = ModelCache()
        self._backend = backend
        self._local_unit_name = local_unit_name
        self.unit = self.get_unit(local_unit_name)
        self.app = self.unit.app
        self.relations = RelationMapping(relation_names, self.unit, self._backend, self._cache)
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
                raise TooManyRelatedApps(relation_name, num_related, 1)

    def _is_local_unit(self, unit_name):
        return unit_name == self._local_unit_name

    def get_unit(self, unit_name):
        return self._cache.get(Unit, unit_name, self._is_local_unit(unit_name), self._backend)


class ModelCache(weakref.WeakValueDictionary):
    def get(self, entity_type, *args):
        key = (entity_type,) + args
        entity = super().get(key)
        if entity is None:
            entity = entity_type(*args, cache=self)
            self[key] = entity
        return entity

class EntityStatus:
    """A helper class for getting and setting entity (application or unit) status."""

    def __init__(self):
        self._cached = None

    def __get__(self, instance, owner):
        is_app = isinstance(instance, Application)

        if not is_app and not isinstance(instance, Unit):
            raise RuntimeError(f'EntityStatus was used as an attribute on {type(instance)} which is not supported')

        if not instance.is_local:
            return Unknown()

        if self._cached:
            return self._cached

        s = instance._backend.status_get(is_app)
        self._cached = StatusTypes[s['status']].value(s['message'])

        return self._cached

    def __set__(self, instance, value):
        is_app = isinstance(instance, Application)

        if not is_app and not isinstance(instance, Unit):
            raise RuntimeError(f'EntityStatus was used as an attribute on {type(instance)} which is not supported')
        if not isinstance(value, Status):
            raise InvalidStatusError(f'Invalid value provided for entity {instance} status: {value}')

        if not instance.is_local:
            raise RuntimeError(f'Unable to get status for a non-local entity {instance}')

        self._cached = value
        instance._backend.status_set(is_app, value.id, value.message)

class Application:
    status = EntityStatus()

    def __init__(self, name, is_local, backend, cache):
        self.name = name
        self.is_local = is_local
        self._backend = backend

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


class Unit:
    status = EntityStatus()

    def __init__(self, name, is_local, backend, cache):
        self.name = name
        self.app = cache.get(Application, name.split('/')[0], is_local, backend)
        self.is_local = is_local
        self._backend = backend

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
        self.name = relation_name
        self.id = relation_id
        self.apps = set()
        self.units = set()
        try:
            for unit_name in backend.relation_list(self.id):
                unit = cache.get(Unit, unit_name, False, backend)
                self.units.add(unit)
                self.apps.add(unit.app)
        except RelationNotFound:
            # If the relation is dead, just treat it as if it has no remote units.
            pass
        self.data = RelationData(self, local_unit, backend)

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}:{self.id}>'


class RelationData(Mapping):
    def __init__(self, relation, local_unit, backend):
        self.relation = weakref.proxy(relation)
        self._data = {local_unit: RelationUnitData(self.relation, local_unit, True, backend)}
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
        except RelationNotFound:
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


class RelationNotFound(ModelError):
    pass


class Status:
    """Status values specific to applications and units."""
    def __init__(self, id, message):
        self.id = id
        self.message = message

class Active(Status):
    """The unit believes it is correctly offering all the services it has been asked to offer."""
    def __init__(self, message):
        super().__init__('active', message)

class Blocked(Status):
    """The unit needs manual intervention to get back to the Running state."""
    def __init__(self, message):
        super().__init__('blocked', message)

class Maintenance(Status):
    """
    The unit is not yet providing services, but is actively doing work in preparation for providing those services.
    This is a "spinning" state, not an error state. It reflects activity on the unit itself, not on peers or related units.
    """
    def __init__(self, message):
        super().__init__('maintenance', message)

class Unknown(Status):
    """A unit-agent has finished calling install, config-changed and start, but the charm has not called status-set yet."""
    def __init__(self, message=''):
        # Unknown status cannot be set and does not have a message associated with it.
        super().__init__('unknown', '')

class Waiting(Status):
    """The unit is unable to progress to an active state because an application to which it is related is not running."""
    def __init__(self, message):
        super().__init__('waiting', message)

@unique
class StatusTypes(Enum):
    active = Active
    blocked = Blocked
    maintenance = Maintenance
    unknown = Unknown
    waiting = Waiting


class InvalidStatusError(ModelError):
    pass


class ModelBackend:
    def _run(self, *args):
        result = run(args + ('--format=json',), stdout=PIPE, stderr=PIPE, check=True)
        text = result.stdout.decode('utf8')
        data = json.loads(text)
        return data

    def _run_no_output(self, *args):
        run(args, check=True)

    def relation_ids(self, relation_name):
        relation_ids = self._run('relation-ids', relation_name)
        return [int(relation_id.split(':')[-1]) for relation_id in relation_ids]

    def relation_list(self, relation_id):
        try:
            return self._run('relation-list', '-r', str(relation_id))
        except CalledProcessError as e:
            # TODO: This should use the return code if it is specific enough rather than the message.
            # It seems to be 2 for this error, but I haven't been able to confirm yet if that might
            # also apply to other error cases.
            if b'relation not found' in e.stderr:
                raise RelationNotFound() from e
            else:
                raise

    def relation_get(self, relation_id, member_name):
        try:
            return self._run('relation-get', '-r', str(relation_id), '-', member_name)
        except CalledProcessError as e:
            # TODO: This should use the return code if it is specific enough rather than the message.
            # It seems to be 2 for this error, but I haven't been able to confirm yet if that might
            # also apply to other error cases.
            if b'relation not found' in e.stderr:
                raise RelationNotFound() from e
            else:
                raise

    def relation_set(self, relation_id, key, value):
        try:
            return self._run_no_output('relation-set', '-r', str(relation_id), f'{key}={value}')
        except CalledProcessError as e:
            if b'relation not found' in e.stderr:
                raise RelationNotFound() from e
            else:
                raise

    def config_get(self):
        return self._run('config-get')

    def status_get(self, app):
        """Get a status of a unit or an application.

        app -- A boolean indicating whether the status should be retrieved for a unit or an application.
        """
        return self._run('status-get', '--include-data', f'--application={app}')

    def status_set(self, app, status, message=''):
        """Set a status of a unit or an application.

        app -- A boolean indicating whether the status should be set for a unit or an application.
        """
        return self._run_no_output('status-set', f'--application={app}', status, message)
