# Copyright 2019 Canonical Ltd.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

import yaml

from ops.framework import Object, EventSource, EventBase, EventsBase


class HookEvent(EventBase):
    pass


class ActionEvent(EventBase):

    def defer(self):
        raise RuntimeError('cannot defer action events')

    def restore(self, snapshot):
        env_action_name = os.environ.get('JUJU_ACTION_NAME')
        event_action_name = self.handle.kind[:-len('_action')].replace('_', '-')
        if event_action_name != env_action_name:
            # This could only happen if the dev manually emits the action, or from a bug.
            raise RuntimeError('action event kind does not match current action')
        # Params are loaded at restore rather than __init__ because the model is not available in __init__.
        self.params = self.framework.model._backend.action_get()

    def set_results(self, results):
        self.framework.model._backend.action_set(results)

    def log(self, message):
        self.framework.model._backend.action_log(message)

    def fail(self, message=''):
        self.framework.model._backend.action_fail(message)


class InstallEvent(HookEvent):
    pass


class StartEvent(HookEvent):
    pass


class StopEvent(HookEvent):
    pass


class ConfigChangedEvent(HookEvent):
    pass


class UpdateStatusEvent(HookEvent):
    pass


class UpgradeCharmEvent(HookEvent):
    pass


class PreSeriesUpgradeEvent(HookEvent):
    pass


class PostSeriesUpgradeEvent(HookEvent):
    pass


class LeaderElectedEvent(HookEvent):
    pass


class LeaderSettingsChangedEvent(HookEvent):
    pass


class CollectMetricsEvent(HookEvent):

    def add_metrics(self, metrics, labels=None):
        self.framework.model._backend.add_metrics(metrics, labels)


class RelationEvent(HookEvent):
    def __init__(self, handle, relation, app=None, unit=None):
        super().__init__(handle)

        if unit and unit.app != app:
            raise RuntimeError('cannot create RelationEvent with application {} and unit {}'.format(app, unit))

        self.relation = relation
        self.app = app
        self.unit = unit

    def snapshot(self):
        snapshot = {
            'relation_name': self.relation.name,
            'relation_id': self.relation.id,
        }
        if self.app:
            snapshot['app_name'] = self.app.name
        if self.unit:
            snapshot['unit_name'] = self.unit.name
        return snapshot

    def restore(self, snapshot):
        self.relation = self.framework.model.get_relation(snapshot['relation_name'], snapshot['relation_id'])

        app_name = snapshot.get('app_name')
        if app_name:
            self.app = self.framework.model.get_app(app_name)
        else:
            self.app = None

        unit_name = snapshot.get('unit_name')
        if unit_name:
            self.unit = self.framework.model.get_unit(unit_name)
        else:
            self.unit = None


class RelationJoinedEvent(RelationEvent):
    pass


class RelationChangedEvent(RelationEvent):
    pass


class RelationDepartedEvent(RelationEvent):
    pass


class RelationBrokenEvent(RelationEvent):
    pass


class StorageEvent(HookEvent):
    pass


class StorageAttachedEvent(StorageEvent):
    pass


class StorageDetachingEvent(StorageEvent):
    pass


class CharmEvents(EventsBase):

    install = EventSource(InstallEvent)
    start = EventSource(StartEvent)
    stop = EventSource(StopEvent)
    update_status = EventSource(UpdateStatusEvent)
    config_changed = EventSource(ConfigChangedEvent)
    upgrade_charm = EventSource(UpgradeCharmEvent)
    pre_series_upgrade = EventSource(PreSeriesUpgradeEvent)
    post_series_upgrade = EventSource(PostSeriesUpgradeEvent)
    leader_elected = EventSource(LeaderElectedEvent)
    leader_settings_changed = EventSource(LeaderSettingsChangedEvent)
    collect_metrics = EventSource(CollectMetricsEvent)


class CharmBase(Object):

    on = CharmEvents()

    def __init__(self, framework, key):
        super().__init__(framework, key)

        for relation_name in self.framework.meta.relations:
            relation_name = relation_name.replace('-', '_')
            self.on.define_event(relation_name + '_relation_joined', RelationJoinedEvent)
            self.on.define_event(relation_name + '_relation_changed', RelationChangedEvent)
            self.on.define_event(relation_name + '_relation_departed', RelationDepartedEvent)
            self.on.define_event(relation_name + '_relation_broken', RelationBrokenEvent)

        for storage_name in self.framework.meta.storages:
            storage_name = storage_name.replace('-', '_')
            self.on.define_event(storage_name + '_storage_attached', StorageAttachedEvent)
            self.on.define_event(storage_name + '_storage_detaching', StorageDetachingEvent)

        for action_name in self.framework.meta.actions:
            action_name = action_name.replace('-', '_')
            self.on.define_event(action_name + '_action', ActionEvent)

    @property
    def app(self):
        return self.framework.model.app

    @property
    def unit(self):
        return self.framework.model.unit

    @property
    def meta(self):
        return self.framework.meta

    @property
    def charm_dir(self):
        return self.framework.charm_dir


class CharmMeta:
    """Object containing the metadata for the charm.

    The maintainers, tags, terms, series, and extra_bindings attributes are all
    lists of strings.  The requires, provides, peers, relations, storage,
    resources, and payloads attributes are all mappings of names to instances
    of the respective RelationMeta, StorageMeta, ResourceMeta, or PayloadMeta.

    The relations attribute is a convenience accessor which includes all of the
    requires, provides, and peers RelationMeta items.  If needed, the role of
    the relation definition can be obtained from its role attribute.
    """

    def __init__(self, raw={}, actions_raw={}):
        self.name = raw.get('name', '')
        self.summary = raw.get('summary', '')
        self.description = raw.get('description', '')
        self.maintainers = []
        if 'maintainer' in raw:
            self.maintainers.append(raw['maintainer'])
        if 'maintainers' in raw:
            self.maintainers.extend(raw['maintainers'])
        self.tags = raw.get('tags', [])
        self.terms = raw.get('terms', [])
        self.series = raw.get('series', [])
        self.subordinate = raw.get('subordinate', False)
        self.min_juju_version = raw.get('min-juju-version')
        self.requires = {name: RelationMeta('requires', name, rel)
                         for name, rel in raw.get('requires', {}).items()}
        self.provides = {name: RelationMeta('provides', name, rel)
                         for name, rel in raw.get('provides', {}).items()}
        self.peers = {name: RelationMeta('peers', name, rel)
                      for name, rel in raw.get('peers', {}).items()}
        self.relations = {}
        self.relations.update(self.requires)
        self.relations.update(self.provides)
        self.relations.update(self.peers)
        self.storages = {name: StorageMeta(name, storage)
                         for name, storage in raw.get('storage', {}).items()}
        self.resources = {name: ResourceMeta(name, res)
                          for name, res in raw.get('resources', {}).items()}
        self.payloads = {name: PayloadMeta(name, payload)
                         for name, payload in raw.get('payloads', {}).items()}
        self.extra_bindings = raw.get('extra-bindings', {})
        self.actions = {name: ActionMeta(name, action) for name, action in actions_raw.items()}

    @classmethod
    def from_yaml(cls, metadata, actions=None):
        meta = yaml.safe_load(metadata)
        raw_actions = {}
        if actions is not None:
            raw_actions = yaml.safe_load(actions)
        return cls(meta, raw_actions)


class RelationMeta:
    """Object containing metadata about a relation definition."""

    def __init__(self, role, relation_name, raw):
        self.role = role
        self.relation_name = relation_name
        self.interface_name = raw['interface']
        self.scope = raw.get('scope')


class StorageMeta:
    """Object containing metadata about a storage definition."""

    def __init__(self, name, raw):
        self.storage_name = name
        self.type = raw['type']
        self.description = raw.get('description', '')
        self.shared = raw.get('shared', False)
        self.read_only = raw.get('read-only', False)
        self.minimum_size = raw.get('minimum-size')
        self.location = raw.get('location')
        self.multiple_range = None
        if 'multiple' in raw:
            range = raw['multiple']['range']
            if '-' not in range:
                self.multiple_range = (int(range), int(range))
            else:
                range = range.split('-')
                self.multiple_range = (int(range[0]), int(range[1]) if range[1] else None)


class ResourceMeta:
    """Object containing metadata about a resource definition."""

    def __init__(self, name, raw):
        self.resource_name = name
        self.type = raw['type']
        self.filename = raw.get('filename', None)
        self.description = raw.get('description', '')


class PayloadMeta:
    """Object containing metadata about a payload definition."""

    def __init__(self, name, raw):
        self.payload_name = name
        self.type = raw['type']


class ActionMeta:

    def __init__(self, name, raw=None):
        raw = raw or {}
        self.name = name
        self.title = raw.get('title', '')
        self.description = raw.get('description', '')
        self.parameters = raw.get('params', {})  # {<parameter name>: <JSON Schema definition>}
        self.required = raw.get('required', [])  # [<parameter name>, ...]
