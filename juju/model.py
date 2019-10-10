import json
from collections.abc import Mapping
from functools import lru_cache
from subprocess import run, PIPE


class Model:
    def __init__(self, app_name, unit_name, relation_names, backend=None):
        self.app = Application(app_name, self._lazy_load_peer_units)
        self.unit = Unit(unit_name)
        self._backend = backend or ModelBackend()
        self.relations = RelationMap(relation_names, self.app, self.unit, self._backend)

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

    def _lazy_load_peer_units(self):
        # In lieu of an implicit peer relation, goal-state seems to be the only way to find out
        # what our peer units are. The information it returns is rather limited, but is enough
        # for our purposes here.
        return [Unit(unit_name) for unit_name in self._backend.goal_state()['units']]


class Application:
    def __init__(self, name, units):
        self.name = name
        self._units = units

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'

    @property
    def units(self):
        # This property allows for the list of units to be lazy-loaded by passing in a function instead of a list.
        if callable(self._units):
            self._units = self._units()
        return self._units

    def __hash__(self):
        # An Application instance from one relation will not be identical to one from another relation,
        # since they may have different views of the units of that app. However, they should be considered
        # equivalent, since they are views of the same entity. Generally, this should only matter for using
        # model.app as an index into a given relation's relation data.
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, Application):
            return False
        return self.name == other.name


class Unit:
    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f'<{type(self).__module__}.{type(self).__name__} {self.name}>'

    def __hash__(self):
        # A Unit instance from one relation will not be identical to one from another relation.
        # However, they should be considered equivalent, since they are views of the same entity.
        # Generally, this should only matter for using model.unit as an index into a given relation's
        # relation data.
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, Unit):
            return False
        return self.name == other.name


class RelationMap(Mapping):
    """Map of relation names to lists of Relation instances."""
    def __init__(self, relation_names, local_app, local_unit, backend):
        self._relation_names = relation_names
        self._local_app = local_app
        self._local_unit = local_unit
        self._backend = backend

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    def __iter__(self):
        return iter(self._relation_names)

    def __len__(self):
        return len(self._relation_names)

    @lru_cache(maxsize=None)
    def __getitem__(self, relation_name):
        # Lazy-load the list of relations for this relation name.
        relation_ids = self._backend.relation_ids(relation_name)
        return [Relation(relation_name, relation_id, self._local_app, self._local_unit, self._backend) for relation_id in relation_ids]


class Relation:
    def __init__(self, relation_name, relation_id, local_app, local_unit, backend):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._backend = backend
        self.data = RelationData(self.relation_name, relation_id, local_app, local_unit, self._backend)

    @property
    @lru_cache(maxsize=None)
    def apps(self):
        # Lazy-load the apps on this relation.
        unit_names = self._backend.relation_list(self.relation_id)
        apps = {}
        for unit_name in unit_names:
            app_name = unit_name.split('/')[0]
            app = apps.get(app_name)
            if not app:
                app = apps[app_name] = Application(app_name, [])
            app.units.append(Unit(unit_name))
        return list(apps.values())


class RelationData(Mapping):
    def __init__(self, relation_name, relation_id, local_app, local_unit, backend):
        self.relation_name = relation_name
        self.relation_id = relation_id
        self._local_app = local_app
        self._local_unit = local_unit
        self._backend = backend

    def __hash__(self):
        return id(self)

    def __eq__(self, other):
        return self is other

    @lru_cache(maxsize=None)
    def keys(self):
        # Lazy-load the list of members for this relation.
        members = set()
        members.add(self._local_app)
        members.add(self._local_unit)
        unit_names = self._backend.relation_list(self.relation_id)
        apps = {}
        for unit_name in unit_names:
            app_name = unit_name.split('/')[0]
            app = apps.get(app_name)
            if not app:
                app = apps[app_name] = Application(app_name, [])
                members.add(app)
            unit = Unit(unit_name)
            members.add(unit)
            app.units.append(unit)
        return members

    def __iter__(self):
        return iter(self._members)

    def __len__(self):
        return len(self._members)

    @lru_cache(maxsize=None)
    def __getitem__(self, member):
        # Lazy-load the data for this relation member.
        if member not in self.keys():
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
    def goal_state(self):
        output = run(['goal-state', '--format=json'], stdout=PIPE, check=True).stdout
        return json.loads(output.decode('utf8'))

    def relation_ids(self, relation_name):
        output = run(['relation-ids', relation_name, '--format=json'], stdout=PIPE, check=True).stdout
        return json.loads(output.decode('utf8'))

    def relation_list(self, relation_id):
        output = run(['relation-list', '-r', relation_id, '--format=json'], stdout=PIPE, check=True).stdout
        return json.loads(output.decode('utf8'))

    def relation_get(self, relation_id, member_name):
        output = run(['relation-get', '-r', relation_id, '-', member_name, '--format=json'], stdout=PIPE, check=True).stdout
        return json.loads(output.decode('utf8'))
