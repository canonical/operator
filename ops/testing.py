# Copyright 2020 Canonical Ltd.
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

import inspect
import pathlib
from textwrap import dedent
import typing

from ops import charm, framework, model


# OptionalYAML is something like metadata.yaml or actions.yaml. You can
# pass in a file-like object or the string directly.
OptionalYAML = typing.Optional[typing.Union[str, typing.TextIO]]


# noinspection PyProtectedMember
class Harness:
    """This class represents a way to build up the model that will drive a test suite.

    The model that is created is from the viewpoint of the charm that you are testing.

    Example::

        harness = Harness(MyCharm)
        # Do initial setup here
        relation_id = harness.add_relation('db', 'postgresql')
        # Now instantiate the charm to see events as the model changes
        harness.begin()
        harness.add_relation_unit(relation_id, 'postgresql/0')
        harness.update_relation_data(relation_id, 'postgresql/0', {'key': 'val'})
        # Check that charm has properly handled the relation_joined event for postgresql/0
        self.assertEqual(harness.charm. ...)

    Args:
        charm_cls: The Charm class that you'll be testing.
        meta: charm.CharmBase is a A string or file-like object containing the contents of
            metadata.yaml. If not supplied, we will look for a 'metadata.yaml' file in the
            parent directory of the Charm, and if not found fall back to a trivial
            'name: test-charm' metadata.
        actions: A string or file-like object containing the contents of
            actions.yaml. If not supplied, we will look for a 'actions.yaml' file in the
            parent directory of the Charm.
    """

    def __init__(
            self,
            charm_cls: typing.Type[charm.CharmBase],
            *,
            meta: OptionalYAML = None,
            actions: OptionalYAML = None):
        # TODO: jam 2020-03-05 We probably want to take config as a parameter as well, since
        #       it would define the default values of config that the charm would see.
        self._charm_cls = charm_cls
        self._charm = None
        self._charm_dir = 'no-disk-path'  # this may be updated by _create_meta
        self._meta = self._create_meta(meta, actions)
        self._unit_name = self._meta.name + '/0'
        self._framework = None
        self._hooks_enabled = True
        self._relation_id_counter = 0
        self._backend = _TestingModelBackend(self._unit_name, self._meta)
        self._model = model.Model(self._unit_name, self._meta, self._backend)
        self._framework = framework.Framework(":memory:", self._charm_dir, self._meta, self._model)

    @property
    def charm(self) -> charm.CharmBase:
        """Return the instance of the charm class that was passed to __init__.

        Note that the Charm is not instantiated until you have called
        :meth:`.begin()`.
        """
        return self._charm

    @property
    def model(self) -> model.Model:
        """Return the :class:`~ops.model.Model` that is being driven by this Harness."""
        return self._model

    @property
    def framework(self) -> framework.Framework:
        """Return the Framework that is being driven by this Harness."""
        return self._framework

    def begin(self) -> None:
        """Instantiate the Charm and start handling events.

        Before calling begin(), there is no Charm instance, so changes to the Model won't emit
        events. You must call begin before :attr:`.charm` is valid.
        """
        if self._charm is not None:
            raise RuntimeError('cannot call the begin method on the harness more than once')

        # The Framework adds attributes to class objects for events, etc. As such, we can't re-use
        # the original class against multiple Frameworks. So create a locally defined class
        # and register it.
        # TODO: jam 2020-03-16 We are looking to changes this to Instance attributes instead of
        #       Class attributes which should clean up this ugliness. The API can stay the same
        class TestEvents(self._charm_cls.on.__class__):
            pass

        TestEvents.__name__ = self._charm_cls.on.__class__.__name__

        class TestCharm(self._charm_cls):
            on = TestEvents()

        # Note: jam 2020-03-01 This is so that errors in testing say MyCharm has no attribute foo,
        # rather than TestCharm has no attribute foo.
        TestCharm.__name__ = self._charm_cls.__name__
        self._charm = TestCharm(self._framework, self._framework.meta.name)

    def _create_meta(self, charm_metadata, action_metadata):
        """Create a CharmMeta object.

        Handle the cases where a user doesn't supply explicit metadata snippets.
        """
        filename = inspect.getfile(self._charm_cls)
        charm_dir = pathlib.Path(filename).parents[1]

        if charm_metadata is None:
            metadata_path = charm_dir / 'metadata.yaml'
            if metadata_path.is_file():
                charm_metadata = metadata_path.read_text()
                self._charm_dir = charm_dir
            else:
                # The simplest of metadata that the framework can support
                charm_metadata = 'name: test-charm'
        elif isinstance(charm_metadata, str):
            charm_metadata = dedent(charm_metadata)

        if action_metadata is None:
            actions_path = charm_dir / 'actions.yaml'
            if actions_path.is_file():
                action_metadata = actions_path.read_text()
                self._charm_dir = charm_dir
        elif isinstance(action_metadata, str):
            action_metadata = dedent(action_metadata)

        return charm.CharmMeta.from_yaml(charm_metadata, action_metadata)

    def disable_hooks(self) -> None:
        """Stop emitting hook events when the model changes.

        This can be used by developers to stop changes to the model from emitting events that
        the charm will react to. Call :meth:`.enable_hooks`
        to re-enable them.
        """
        self._hooks_enabled = False

    def enable_hooks(self) -> None:
        """Re-enable hook events from charm.on when the model is changed.

        By default hook events are enabled once you call :meth:`.begin`,
        but if you have used :meth:`.disable_hooks`, this can be used to
        enable them again.
        """
        self._hooks_enabled = True

    def _next_relation_id(self):
        rel_id = self._relation_id_counter
        self._relation_id_counter += 1
        return rel_id

    def add_relation(self, relation_name: str, remote_app: str) -> int:
        """Declare that there is a new relation between this app and `remote_app`.

        Args:
            relation_name: The relation on Charm that is being related to
            remote_app: The name of the application that is being related to

        Return:
            The relation_id created by this add_relation.
        """
        rel_id = self._next_relation_id()
        self._backend._relation_ids_map.setdefault(relation_name, []).append(rel_id)
        self._backend._relation_names[rel_id] = relation_name
        self._backend._relation_list_map[rel_id] = []
        self._backend._relation_data[rel_id] = {
            remote_app: {},
            self._backend.unit_name: {},
            self._backend.app_name: {},
        }
        # Reload the relation_ids list
        if self._model is not None:
            self._model.relations._invalidate(relation_name)
        if self._charm is None or not self._hooks_enabled:
            return rel_id
        relation = self._model.get_relation(relation_name, rel_id)
        app = self._model.get_app(remote_app)
        self._charm.on[relation_name].relation_created.emit(
            relation, app)
        return rel_id

    def add_relation_unit(self, relation_id: int, remote_unit_name: str) -> None:
        """Add a new unit to a relation.

        Example::

          rel_id = harness.add_relation('db', 'postgresql')
          harness.add_relation_unit(rel_id, 'postgresql/0')

        This will trigger a `relation_joined` event and a `relation_changed` event.

        Args:
            relation_id: The integer relation identifier (as returned by add_relation).
            remote_unit_name: A string representing the remote unit that is being added.
        Return:
            None
        """
        self._backend._relation_list_map[relation_id].append(remote_unit_name)
        self._backend._relation_data[relation_id][remote_unit_name] = {}
        relation_name = self._backend._relation_names[relation_id]
        # Make sure that the Model reloads the relation_list for this relation_id, as well as
        # reloading the relation data for this unit.
        if self._model is not None:
            remote_unit = self._model.get_unit(remote_unit_name)
            relation = self._model.get_relation(relation_name, relation_id)
            unit_cache = relation.data.get(remote_unit, None)
            if unit_cache is not None:
                unit_cache._invalidate()
            self._model.relations._invalidate(relation_name)
        if self._charm is None or not self._hooks_enabled:
            return
        self._charm.on[relation_name].relation_joined.emit(
            relation, remote_unit.app, remote_unit)

    def get_relation_data(self, relation_id: int, app_or_unit: str) -> typing.Mapping:
        """Get the relation data bucket for a single app or unit in a given relation.

        This ignores all of the safety checks of who can and can't see data in relations (eg,
        non-leaders can't read their own application's relation data because there are no events
        that keep that data up-to-date for the unit).

        Args:
            relation_id: The relation whose content we want to look at.
            app_or_unit: The name of the application or unit whose data we want to read
        Return:
            a dict containing the relation data for `app_or_unit` or None.
        Raises:
            KeyError: if relation_id doesn't exist
        """
        return self._backend._relation_data[relation_id].get(app_or_unit, None)

    def get_workload_version(self) -> str:
        """Read the workload version that was set by the unit."""
        return self._backend._workload_version

    def update_relation_data(
            self,
            relation_id: int,
            app_or_unit: str,
            key_values: typing.Mapping,
    ) -> None:
        """Update the relation data for a given unit or application in a given relation.

        This also triggers the `relation_changed` event for this relation_id.

        Args:
            relation_id: The integer relation_id representing this relation.
            app_or_unit: The unit or application name that is being updated.
                This can be the local or remote application.
            key_values: Each key/value will be updated in the relation data.
        """
        relation_name = self._backend._relation_names[relation_id]
        relation = self._model.get_relation(relation_name, relation_id)
        if '/' in app_or_unit:
            entity = self._model.get_unit(app_or_unit)
        else:
            entity = self._model.get_app(app_or_unit)
        rel_data = relation.data.get(entity, None)
        if rel_data is not None:
            # rel_data may have cached now-stale data, so _invalidate() it.
            # Note, this won't cause the data to be loaded if it wasn't already.
            rel_data._invalidate()

        new_values = self._backend._relation_data[relation_id][app_or_unit].copy()
        for k, v in key_values.items():
            if v == '':
                new_values.pop(k, None)
            else:
                new_values[k] = v
        self._backend._relation_data[relation_id][app_or_unit] = new_values

        if app_or_unit == self._model.unit.name:
            # No events for our own unit
            return
        if app_or_unit == self._model.app.name:
            # updating our own app only generates an event if it is a peer relation and we
            # aren't the leader
            is_peer = self._meta.relations[relation_name].role.is_peer()
            if not is_peer:
                return
            if self._model.unit.is_leader():
                return
        self._emit_relation_changed(relation_id, app_or_unit)

    def _emit_relation_changed(self, relation_id, app_or_unit):
        if self._charm is None or not self._hooks_enabled:
            return
        rel_name = self._backend._relation_names[relation_id]
        relation = self.model.get_relation(rel_name, relation_id)
        if '/' in app_or_unit:
            app_name = app_or_unit.split('/')[0]
            unit_name = app_or_unit
            app = self.model.get_app(app_name)
            unit = self.model.get_unit(unit_name)
            args = (relation, app, unit)
        else:
            app_name = app_or_unit
            app = self.model.get_app(app_name)
            args = (relation, app)
        self._charm.on[rel_name].relation_changed.emit(*args)

    def update_config(
            self,
            key_values: typing.Mapping[str, str] = None,
            unset: typing.Iterable[str] = (),
    ) -> None:
        """Update the config as seen by the charm.

        This will trigger a `config_changed` event.

        Args:
            key_values: A Mapping of key:value pairs to update in config.
            unset: An iterable of keys to remove from Config. (Note that this does
                not currently reset the config values to the default defined in config.yaml.)
        """
        config = self._backend._config
        if key_values is not None:
            for key, value in key_values.items():
                config[key] = value
        for key in unset:
            config.pop(key, None)
        # NOTE: jam 2020-03-01 Note that this sort of works "by accident". Config
        # is a LazyMapping, but its _load returns a dict and this method mutates
        # the dict that Config is caching. Arguably we should be doing some sort
        # of charm.framework.model.config._invalidate()
        if self._charm is None or not self._hooks_enabled:
            return
        self._charm.on.config_changed.emit()

    def set_leader(self, is_leader: bool = True) -> None:
        """Set whether this unit is the leader or not.

        If this charm becomes a leader then `leader_elected` will be triggered.

        Args:
            is_leader: True/False as to whether this unit is the leader.
        """
        was_leader = self._backend._is_leader
        self._backend._is_leader = is_leader
        # Note: jam 2020-03-01 currently is_leader is cached at the ModelBackend level, not in
        # the Model objects, so this automatically gets noticed.
        if is_leader and not was_leader and self._charm is not None and self._hooks_enabled:
            self._charm.on.leader_elected.emit()

    def _get_backend_calls(self, reset: bool = True) -> list:
        """Return the calls that we have made to the TestingModelBackend.

        This is useful mostly for testing the framework itself, so that we can assert that we
        do/don't trigger extra calls.

        Args:
            reset: If True, reset the calls list back to empty, if false, the call list is
                preserved.
        Return:
            ``[(call1, args...), (call2, args...)]``
        """
        calls = self._backend._calls.copy()
        if reset:
            self._backend._calls.clear()
        return calls


def _record_calls(cls):
    """Replace methods on cls with methods that record that they have been called.

    Iterate all attributes of cls, and for public methods, replace them with a wrapped method
    that records the method called along with the arguments and keyword arguments.
    """
    for meth_name, orig_method in cls.__dict__.items():
        if meth_name.startswith('_'):
            continue

        def decorator(orig_method):
            def wrapped(self, *args, **kwargs):
                full_args = (orig_method.__name__,) + args
                if kwargs:
                    full_args = full_args + (kwargs,)
                self._calls.append(full_args)
                return orig_method(self, *args, **kwargs)
            return wrapped

        setattr(cls, meth_name, decorator(orig_method))
    return cls


@_record_calls
class _TestingModelBackend:
    """This conforms to the interface for ModelBackend but provides canned data.

    DO NOT use this class directly, it is used by `Harness`_ to drive the model.
    `Harness`_ is responsible for maintaining the internal consistency of the values here,
    as the only public methods of this type are for implementing ModelBackend.
    """

    def __init__(self, unit_name, meta):
        self.unit_name = unit_name
        self.app_name = self.unit_name.split('/')[0]
        self._calls = []
        self._meta = meta
        self._is_leader = None
        self._relation_ids_map = {}  # relation name to [relation_ids,...]
        self._relation_names = {}  # reverse map from relation_id to relation_name
        self._relation_list_map = {}  # relation_id: [unit_name,...]
        self._relation_data = {}  # {relation_id: {name: data}}
        self._config = {}
        self._is_leader = False
        self._resources_map = {}
        self._pod_spec = None
        self._app_status = {'status': 'unknown', 'message': ''}
        self._unit_status = {'status': 'maintenance', 'message': ''}
        self._workload_version = None

    def relation_ids(self, relation_name):
        try:
            return self._relation_ids_map[relation_name]
        except KeyError as e:
            if relation_name not in self._meta.relations:
                raise model.ModelError('{} is not a known relation'.format(relation_name)) from e
            return []

    def relation_list(self, relation_id):
        try:
            return self._relation_list_map[relation_id]
        except KeyError as e:
            raise model.RelationNotFoundError from e

    def relation_get(self, relation_id, member_name, is_app):
        if is_app and '/' in member_name:
            member_name = member_name.split('/')[0]
        if relation_id not in self._relation_data:
            raise model.RelationNotFoundError()
        return self._relation_data[relation_id][member_name].copy()

    def relation_set(self, relation_id, key, value, is_app):
        relation = self._relation_data[relation_id]
        if is_app:
            bucket_key = self.app_name
        else:
            bucket_key = self.unit_name
        if bucket_key not in relation:
            relation[bucket_key] = {}
        bucket = relation[bucket_key]
        if value == '':
            bucket.pop(key, None)
        else:
            bucket[key] = value

    def config_get(self):
        return self._config

    def is_leader(self):
        return self._is_leader

    def application_version_set(self, version):
        self._workload_version = version

    def resource_get(self, resource_name):
        return self._resources_map[resource_name]

    def pod_spec_set(self, spec, k8s_resources):
        self._pod_spec = (spec, k8s_resources)

    def status_get(self, *, is_app=False):
        if is_app:
            return self._app_status
        else:
            return self._unit_status

    def status_set(self, status, message='', *, is_app=False):
        if is_app:
            self._app_status = {'status': status, 'message': message}
        else:
            self._unit_status = {'status': status, 'message': message}

    def storage_list(self, name):
        raise NotImplementedError(self.storage_list)

    def storage_get(self, storage_name_id, attribute):
        raise NotImplementedError(self.storage_get)

    def storage_add(self, name, count=1):
        raise NotImplementedError(self.storage_add)

    def action_get(self):
        raise NotImplementedError(self.action_get)

    def action_set(self, results):
        raise NotImplementedError(self.action_set)

    def action_log(self, message):
        raise NotImplementedError(self.action_log)

    def action_fail(self, message=''):
        raise NotImplementedError(self.action_fail)

    def network_get(self, endpoint_name, relation_id=None):
        raise NotImplementedError(self.network_get)
