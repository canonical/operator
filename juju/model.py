import json
from collections.abc import Mapping
from functools import lru_cache
from subprocess import run, PIPE


class Model:
    def __init__(self, relation_names, backend):
        self.relations = RelationMap(relation_names, backend)
        self._backend = backend

    @property
    def app(self):
        return self._backend.local_app

    @property
    def unit(self):
        return self._backend.local_unit

    def relation(self, relation_name):
        """Return the first Relation object for the named relation, or None.

        This is a convenience method for the case where only a single related
        app is supported. If there are more than one remote apps on the relation,
        it will raise a TooManyRelatedApps model error. If no there are no remote
        apps on the relation, it will return None. Otherwise, it is equivalent
        to self.relations[relation_name][0].
        """
        num_related = len(self.relations[relation_name])
        if num_related > 1:
            raise TooManyRelatedApps(relation_name, num_related, 1)
        elif num_related == 0:
            return None
        else:
            return self.relations[relation_name][0]


class Application:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


class Unit:
    def __init__(self, name, app):
        self.name = name
        self.app = app

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'


class RelationMap(Mapping):
    """Map of relation names to lists of Relation instances."""
    def __init__(self, relation_names, backend):
        self._relation_names = relation_names
        self._backend = backend

    def __iter__(self):
        return iter(self._relation_names)

    def __len__(self):
        return len(self._relation_names)

    def __getitem__(self, relation_name):
        return self._backend.get_relations(relation_name)


class Relation:
    def __init__(self, relation_name, relation_id, backend):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._backend = backend
        self.data = RelationData(self.relation_name, relation_id, self._backend)

    @property
    def apps(self):
        return [unit.app for unit in self.units]

    @property
    def units(self):
        return list(self.data.keys())


class RelationData(Mapping):
    def __init__(self, relation_name, relation_id, backend):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._backend = backend
        self._keys = self._backend.get_relation_members(self.relation_id)

    def keys(self):
        return self._keys

    def __contains__(self, key):
        return key in self._keys

    def __iter__(self):
        return iter(self._keys)

    def __len__(self):
        return len(self._keys)

    def __getitem__(self, member):
        if member not in self._keys:
            raise KeyError(member)
        return self._backend.relation_get(self.relation_id, member.name)


class ModelError(Exception):
    pass


class TooManyRelatedApps(ModelError):
    def __init__(self, relation_name, num_related, max_supported):
        super().__init__(f'Too many remote applications on {relation_name} ({num_related} > {max_supported})')
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported


class ModelBackend:
    def __init__(self, local_unit_name):
        local_app_name = local_unit_name.split('/')[0]
        self.local_app = Application(local_app_name)
        self.local_unit = Unit(local_unit_name, self.local_app)
        self._apps = {local_app_name: self.local_app}
        self._units = {local_unit_name: self.local_unit}

    def relation_ids(self, relation_name):
        output = run(['relation-ids', relation_name, '--format=json'], stdout=PIPE, check=True).stdout
        return json.loads(output.decode('utf8'))

    def relation_list(self, relation_id):
        output = run(['relation-list', '-r', relation_id, '--format=json'], stdout=PIPE, check=True).stdout
        return json.loads(output.decode('utf8'))

    @lru_cache(maxsize=None)
    def relation_get(self, relation_id, member_name):
        output = run(['relation-get', '-r', relation_id, '-', member_name, '--format=json'], stdout=PIPE, check=True).stdout
        return json.loads(output.decode('utf8'))

    @lru_cache(maxsize=None)
    def get_relations(self, relation_name):
        relation_ids = self.relation_ids(relation_name)
        return [Relation(relation_name, relation_id, self) for relation_id in relation_ids]

    @lru_cache(maxsize=None)
    def get_relation_members(self, relation_id):
        # The local unit is always a member of this charm's relations.
        # TODO: Juju will add support for application-level relation data, at
        # which point the local app will also become a member of all relations.
        members = {self.local_unit}
        for remote_unit_name in self.relation_list(relation_id):
            remote_app_name = remote_unit_name.split('/')[0]
            remote_app = self._apps.get(remote_app_name)
            if remote_app is None:
                remote_app = self._apps[remote_app_name] = Application(remote_app_name)
            remote_unit = self._units.get(remote_unit_name)
            if remote_unit is None:
                remote_unit = self._units[remote_unit_name] = Unit(remote_unit_name, remote_app)
            # TODO: When Juju adds support for application-level relation data, the
            # remote app will also be a member of the relation.
            members.add(remote_unit)
        return list(members)
