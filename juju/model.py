import yaml
from subprocess import run, PIPE


class Model:
    def __init__(self, data):
        if 'units' in data:
            units = [Unit(unit_name) for unit_name in data['units']]
        else:
            units = self._lazy_load_peer_units()
        self.app = Application(data['application_name'], units)
        self.unit = Unit(data['unit_name'])
        self.relations = RelationMap(data['relations'])

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
        """Return a generator which lazy-loads the list of peer units."""
        # In lieu of an implicit peer relation, goal-state seems to be the only way to find out
        # what our peer units are. The information it returns, however, is rather limited.
        output = run(['goal-state'], stdout=PIPE, check=True).stdout
        data = yaml.safe_load(output.decode('utf8'))
        for unit_name in data['units']:
            yield Unit(unit_name)


class Application:
    def __init__(self, name, units):
        # TODO Do we want to move to UUIDs? Is that even possible with the number of
        # places that rely on unit names being of the form {app_name}/{unit_number}?
        # Note that CMRs don't expose the actual unit name, but still follow the form,
        # using someething like remote-56a0f163eb4e4f2e88d50983dca7be02/0.
        self.name = name
        self.units = units

    def __hash__(self):
        # An Application instance from one relation will not be identical to one from another relation,
        # since they may have different views of the units of that app. However, they should be considered
        # equivalent, since they are views of the same entity. Generally, this should only matter for using
        # model.app as an index into a given relation's relation data.
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, Application):
            raise TypeError(f"'==' not supported between instances of '{type(self).__name__}' and '{type(other).__name__}'")
        return self.name == other.name


class Unit:
    def __init__(self, name):
        # TODO Do we want to move to UUIDs? Is that even possible with the number of
        # places that rely on unit names being of the form {app_name}/{unit_number}?
        # Note that CMRs don't expose the actual unit name, but still follow the form,
        # using someething like remote-56a0f163eb4e4f2e88d50983dca7be02/0.
        self.name = name

    def __hash__(self):
        # A Unit instance from one relation will not be identical to one from another relation.
        # However, they should be considered equivalent, since they are views of the same entity.
        # Generally, this should only matter for using model.unit as an index into a given relation's
        # relation data.
        return hash(self.name)

    def __eq__(self, other):
        if not isinstance(other, Unit):
            raise TypeError(f"'==' not supported between instances of '{type(self).__name__}' and '{type(other).__name__}'")
        return self.name == other.name


class RelationMap(dict):
    """Map of relation names to lists of Relation instances.

    The data for each relation name may be lazy-loaded.
    """
    def __init__(self, data):
        super().__init__()
        for relation_name, relations in data.items():
            if relations is not None:
                relations = [Relation(relation_id, relation_data)
                             for relation_id, relation_data in sorted(relations.items())]
            self[relation_name] = relations

    def __getitem__(self, relation_name):
        value = super().__getitem__(relation_name)
        if value is None:
            # Lazy-load the list of relations for this relation name.
            output = run(['relation-ids', relation_name, '--format=yaml'], stdout=PIPE, check=True).stdout
            value = [Relation(relation_id) for relation_id in yaml.safe_load(output.decode('utf8'))]
            self[relation_name] = value
        return value


class Relation:
    def __init__(self, relation_id, data=None):
        self.relation_id = relation_id
        self.data = RelationData(relation_id, data)
        if data is not None:
            self._apps = [key for key in self.data if isinstance(key, Application)]
        else:
            self._apps = None

    @property
    def apps(self):
        if self._apps is None:
            # Lazy-load the apps on this relation.
            output = run(['relation-list', '-r', self.relation_id, '--format=yaml'], stdout=PIPE, check=True).stdout
            member_names = yaml.safe_load(output.decode('utf8'))
            units_by_app = {}
            for member_name in sorted(member_names):
                if '/' not in member_name:
                    # Handle possible future support from Juju for application relation data.
                    continue
                app_name = member_name.split('/')[0]
                units_by_app.setdefault(app_name, []).append(Unit(member_name))
            self._apps = [Application(app_name, units) for app_name, units in sorted(units_by_app.items())]
        return self._apps


class RelationData(dict):
    def __init__(self, relation_id, relation_data=None):
        super().__init__()
        self.relation_id = relation_id
        if relation_data is not None:
            app_units = {}
            for app_or_unit_name, member_data in sorted(relation_data.items()):
                # Apps and units are represented in the same data structure to match the expected
                # pattern for interacting with Juju and how we present it to the charm code. However,
                # this means we have to distinguish them by the presence or lack of a / in the name.
                if '/' not in app_or_unit_name:
                    # Skip the apps until we have all of the info about which
                    # of its units are available on the relation.
                    continue
                unit = Unit(app_or_unit_name)
                app_name = unit.name.split('/')[0]
                app_units.setdefault(app_name, []).append(unit)
                self[unit] = member_data
            for app_name, units in app_units.items():
                app = Application(app_name, units)
                self[app] = relation_data[app.name]

    def __getitem__(self, app_or_unit):
        if app_or_unit not in self:
            # Lazy-load the data for this relation member.
            # TODO: We should also lazy-load the list of members so that
            # KeyErrors can be raised if invalid members are accessed.
            output = run(['relation-get', '-r', self.relation_id, '-', app_or_unit.name, '--format=yaml'], stdout=PIPE, check=True).stdout
            value = yaml.safe_load(output.decode('utf8'))
            self[app_or_unit] = value
        else:
            value = super().__getitem__(app_or_unit)
        return value


class ModelError(Exception):
    pass


class TooManyRelatedApps(ModelError):
    def __init__(self, relation_name, num_related, max_supported):
        super().__init__(f'Too many remote applications on {relation_name} ({num_related} > {max_supported})')
        self.relation_name = relation_name
        self.num_related = num_related
        self.max_supported = max_supported
