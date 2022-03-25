# Copyright 2021 Canonical Ltd.
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

"""Infrastructure to build unittests for Charms using the Operator Framework.

Global Variables:

    SIMULATE_CAN_CONNECT: This enables can_connect simulation for the test
    harness.  It should be set *before* you create Harness instances and not
    changed after.  You *should* set this to true - it will help your tests be
    more accurate!  This causes all containers' can_connect states initially
    be False rather than True and causes the testing with the harness to model
    and track can_connect state for containers accurately.  This means that
    calls that require communication with the container API (e.g.
    Container.push, Container.get_plan, Container.add_layer, etc.) will only
    succeed if Container.can_connect() returns True and will raise exceptions
    otherwise.  can_connect state evolves automatically to track with events
    associated with container state, (e.g.  calling container_pebble_ready).
    If SIMULATE_CAN_CONNECT is True, can_connect state for containers can also
    be manually controlled using Harness.set_can_connect.
"""


import datetime
import fnmatch
import inspect
import pathlib
import random
import signal
import tempfile
import typing
import warnings
from contextlib import contextmanager
from io import BytesIO, StringIO
from textwrap import dedent

from ops import charm, framework, model, pebble, storage
from ops._private import yaml

# Toggles Container.can_connect simulation globally for all harness instances.
# For this to work, it must be set *before* Harness instances are created.
SIMULATE_CAN_CONNECT = False

# OptionalYAML is something like metadata.yaml or actions.yaml. You can
# pass in a file-like object or the string directly.
OptionalYAML = typing.Optional[typing.Union[str, typing.TextIO]]


# An instance of an Application or Unit, or the name of either.
# This is done here to avoid a scoping issue with the `model` property
# of the Harness class below.
AppUnitOrName = typing.Union[str, model.Application, model.Unit]


# CharmType represents user charms that are derived from CharmBase.
CharmType = typing.TypeVar('CharmType', bound=charm.CharmBase)


# noinspection PyProtectedMember
class Harness(typing.Generic[CharmType]):
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
        config: A string or file-like object containing the contents of
            config.yaml. If not supplied, we will look for a 'config.yaml' file in the
            parent directory of the Charm.
    """

    def __init__(
            self,
            charm_cls: typing.Type[CharmType],
            *,
            meta: OptionalYAML = None,
            actions: OptionalYAML = None,
            config: OptionalYAML = None):
        self._charm_cls = charm_cls
        self._charm = None
        self._charm_dir = 'no-disk-path'  # this may be updated by _create_meta
        self._meta = self._create_meta(meta, actions)
        self._unit_name = self._meta.name + '/0'
        self._framework = None
        self._hooks_enabled = True
        self._relation_id_counter = 0
        self._backend = _TestingModelBackend(self._unit_name, self._meta)
        self._model = model.Model(self._meta, self._backend)
        self._storage = storage.SQLiteStorage(':memory:')
        self._oci_resources = {}
        self._framework = framework.Framework(
            self._storage, self._charm_dir, self._meta, self._model)
        self._defaults = self._load_config_defaults(config)
        self._update_config(key_values=self._defaults)

        # TODO: If/when we decide to allow breaking changes for a release,
        # change SIMULATE_CAN_CONNECT default value to True and remove the
        # warning message below.  This warning was added 2022-03-22
        if not SIMULATE_CAN_CONNECT:
            warnings.warn(
                'Please set ops.testing.SIMULATE_CAN_CONNECT=True.'
                'See https://juju.is/docs/sdk/testing#heading--simulate-can-connect for details.')

    def set_can_connect(self, container: typing.Union[str, model.Container], val: bool):
        """Change the simulated can_connect status of a container's underlying pebble client.

        Calling this method raises an exception if SIMULATE_CAN_CONNECT is False.
        """
        if isinstance(container, str):
            container = self.model.unit.get_container(container)
        self._backend._set_can_connect(container._pebble, val)

    @property
    def charm(self) -> CharmType:
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

        Before calling :meth:`begin`, there is no Charm instance, so changes to the Model won't
        emit events. You must call :meth:`.begin` before :attr:`.charm` is valid.
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
        self._charm = TestCharm(self._framework)

    def begin_with_initial_hooks(self) -> None:
        """Called when you want the Harness to fire the same hooks that Juju would fire at startup.

        This triggers install, relation-created, config-changed, start, and any relation-joined
        hooks based on what relations have been defined+added before you called begin. This does
        NOT trigger a pebble-ready hook. Note that all of these are fired before returning control
        to the test suite, so if you want to introspect what happens at each step, you need to fire
        them directly (e.g. Charm.on.install.emit()).  In your hook callback functions, you should
        not assume that workload containers are active; guard such code with checks to
        Container.can_connect().  You are encouraged to test this by setting the global
        SIMULATE_CAN_CONNECT variable to True.

        To use this with all the normal hooks, you should instantiate the harness, setup any
        relations that you want active when the charm starts, and then call this method.  This
        method will automatically create and add peer relations that are specified in
        metadata.yaml.

        Example::

            harness = Harness(MyCharm)
            # Do initial setup here
            # Add storage if needed before begin_with_initial_hooks() is called
            storage_id = harness.add_storage('data', count=1)
            relation_id = harness.add_relation('db', 'postgresql')
            harness.add_relation_unit(relation_id, 'postgresql/0')
            harness.update_relation_data(relation_id, 'postgresql/0', {'key': 'val'})
            harness.set_leader(True)
            harness.update_config({'initial': 'config'})
            harness.begin_with_initial_hooks()
            # This will cause
            # install, db-relation-created('postgresql'), leader-elected, config-changed, start
            # db-relation-joined('postrgesql/0'), db-relation-changed('postgresql/0')
            # To be fired.
        """
        self.begin()

        # Checking if disks have been added
        # storage-attached events happen before install
        for storage_name in self._meta.storages:
            for storage_index in self._backend.storage_list(storage_name):
                storage_name = storage_name.replace('-', '_')
                # Storage device(s) detected, emit storage-attached event(s)
                self._charm.on[storage_name].storage_attached.emit(
                    model.Storage(storage_name, storage_index, self._backend))
        # Storage done, emit install event
        self._charm.on.install.emit()
        # Juju itself iterates what relation to fire based on a map[int]relation, so it doesn't
        # guarantee a stable ordering between relation events. It *does* give a stable ordering
        # of joined units for a given relation.
        items = list(self._meta.relations.items())
        random.shuffle(items)
        this_app_name = self._meta.name
        for relname, rel_meta in items:
            if rel_meta.role == charm.RelationRole.peer:
                # If the user has directly added a relation, leave it be, but otherwise ensure
                # that peer relations are always established at before leader-elected.
                rel_ids = self._backend._relation_ids_map.get(relname)
                if rel_ids is None:
                    self.add_relation(relname, self._meta.name)
                else:
                    random.shuffle(rel_ids)
                    for rel_id in rel_ids:
                        self._emit_relation_created(relname, rel_id, this_app_name)
            else:
                rel_ids = self._backend._relation_ids_map.get(relname, [])
                random.shuffle(rel_ids)
                for rel_id in rel_ids:
                    app_name = self._backend._relation_app_and_units[rel_id]["app"]
                    self._emit_relation_created(relname, rel_id, app_name)
        if self._backend._is_leader:
            self._charm.on.leader_elected.emit()
        else:
            self._charm.on.leader_settings_changed.emit()
        self._charm.on.config_changed.emit()
        self._charm.on.start.emit()
        # If the initial hooks do not set a unit status, the Juju controller will switch
        # the unit status from "Maintenance" to "Unknown". See gh#726
        post_setup_sts = self._backend.status_get()
        if post_setup_sts.get("status") == "maintenance" and not post_setup_sts.get("message"):
            self._backend.status_set("unknown", "", is_app=False)
        all_ids = list(self._backend._relation_names.items())
        random.shuffle(all_ids)
        for rel_id, rel_name in all_ids:
            rel_app_and_units = self._backend._relation_app_and_units[rel_id]
            app_name = rel_app_and_units["app"]
            # Note: Juju *does* fire relation events for a given relation in the sorted order of
            # the unit names. It also always fires relation-changed immediately after
            # relation-joined for the same unit.
            # Juju only fires relation-changed (app) if there is data for the related application
            relation = self._model.get_relation(rel_name, rel_id)
            if self._backend._relation_data[rel_id].get(app_name):
                app = self._model.get_app(app_name)
                self._charm.on[rel_name].relation_changed.emit(
                    relation, app, None)
            for unit_name in sorted(rel_app_and_units["units"]):
                remote_unit = self._model.get_unit(unit_name)
                self._charm.on[rel_name].relation_joined.emit(
                    relation, remote_unit.app, remote_unit)
                self._charm.on[rel_name].relation_changed.emit(
                    relation, remote_unit.app, remote_unit)

    def cleanup(self) -> None:
        """Called by your test infrastructure to cleanup any temporary directories/files/etc.

        Currently this only needs to be called if you test with resources. But it is reasonable
        to always include a `testcase.addCleanup(harness.cleanup)` just in case.
        """
        self._backend._cleanup()

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

    def _load_config_defaults(self, charm_config):
        """Load default values from config.yaml.

        Handle the case where a user doesn't supply explicit config snippets.
        """
        filename = inspect.getfile(self._charm_cls)
        charm_dir = pathlib.Path(filename).parents[1]

        if charm_config is None:
            config_path = charm_dir / 'config.yaml'
            if config_path.is_file():
                charm_config = config_path.read_text()
                self._charm_dir = charm_dir
            else:
                # The simplest of config that the framework can support
                charm_config = '{}'
        elif isinstance(charm_config, str):
            charm_config = dedent(charm_config)
        charm_config = yaml.safe_load(charm_config)
        charm_config = charm_config.get('options', {})
        return {key: value.get('default', None) for key, value in charm_config.items()}

    def add_oci_resource(self, resource_name: str,
                         contents: typing.Mapping[str, str] = None) -> None:
        """Add oci resources to the backend.

        This will register an oci resource and create a temporary file for processing metadata
        about the resource. A default set of values will be used for all the file contents
        unless a specific contents dict is provided.

        Args:
            resource_name: Name of the resource to add custom contents to.
            contents: Optional custom dict to write for the named resource.
        """
        if not contents:
            contents = {'registrypath': 'registrypath',
                        'username': 'username',
                        'password': 'password',
                        }
        if resource_name not in self._meta.resources.keys():
            raise RuntimeError('Resource {} is not a defined resources'.format(resource_name))
        if self._meta.resources[resource_name].type != "oci-image":
            raise RuntimeError('Resource {} is not an OCI Image'.format(resource_name))

        as_yaml = yaml.safe_dump(contents)
        self._backend._resources_map[resource_name] = ('contents.yaml', as_yaml)

    def add_resource(self, resource_name: str, content: typing.AnyStr) -> None:
        """Add content for a resource to the backend.

        This will register the content, so that a call to `Model.resources.fetch(resource_name)`
        will return a path to a file containing that content.

        Args:
            resource_name: The name of the resource being added
            content: Either string or bytes content, which will be the content of the filename
                returned by resource-get. If contents is a string, it will be encoded in utf-8
        """
        if resource_name not in self._meta.resources.keys():
            raise RuntimeError('Resource {} is not a defined resources'.format(resource_name))
        record = self._meta.resources[resource_name]
        if record.type != "file":
            raise RuntimeError(
                'Resource {} is not a file, but actually {}'.format(resource_name, record.type))
        filename = record.filename
        if filename is None:
            filename = resource_name

        self._backend._resources_map[resource_name] = (filename, content)

    def populate_oci_resources(self) -> None:
        """Populate all OCI resources."""
        for name, data in self._meta.resources.items():
            if data.type == "oci-image":
                self.add_oci_resource(name)

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

    @contextmanager
    def hooks_disabled(self):
        """A context manager to run code with hooks disabled.

        Example::

            with harness.hooks_disabled():
                # things in here don't fire events
                harness.set_leader(True)
                harness.update_config(unset=['foo', 'bar'])
            # things here will again fire events
        """
        if self._hooks_enabled:
            self.disable_hooks()
            try:
                yield None
            finally:
                self.enable_hooks()
        else:
            yield None

    def _next_relation_id(self):
        rel_id = self._relation_id_counter
        self._relation_id_counter += 1
        return rel_id

    def add_storage(self, storage_name: str, count: int = 1) -> typing.List[str]:
        """Declare a new storage device attached to this unit.

        To have repeatable tests, each device will be initialized with
        location set to /<storage_name>N, where N is the counter and
        will be a number from [0,total_num_disks-1]

        Args:
            storage_name: The storage backend name on the Charm
            count: Number of disks being added

        Return:
            A list of storage IDs, e.g. ["my-storage/1", "my-storage/2"].
        """
        if storage_name not in self._meta.storages:
            raise RuntimeError(
                "the key '{}' is not specified as a storage key in metadata".format(storage_name))
        storage_indices = self._backend.storage_add(storage_name, count)

        # Reset associated cached value in the storage mappings.  If we don't do this,
        # Model._storages won't return Storage objects for subsequently-added storage.
        self._model._storages._invalidate(storage_name)

        if self.charm is not None and self._hooks_enabled:
            for storage_index in storage_indices:
                self.charm.on[storage_name].storage_attached.emit(
                    model.Storage(storage_name, storage_index, self._backend))
        return ["{}/{}".format(storage_name, storage_index) for storage_index in storage_indices]

    def detach_storage(self, storage_id: str) -> None:
        """Detach a storage device.

        The intent of this function is to simulate a "juju detach-storage" call.
        It will trigger a storage-detaching hook if the storage unit in question exists
        and is presently marked as attached.

        Args:
            storage_id: The full storage ID of th e storage unit being detached, including the
                storage key, e.g. my-storage/0.
        """
        if self.charm is None:
            raise RuntimeError('cannot detach storage before Harness is initialised')
        storage_name, storage_index = storage_id.split('/', 1)
        storage_index = int(storage_index)
        if self._backend._storage_is_attached(storage_name, storage_index) and self._hooks_enabled:
            self.charm.on[storage_name].storage_detaching.emit(
                model.Storage(storage_name, storage_index, self._backend))
        self._backend._storage_detach(storage_id)

    def attach_storage(self, storage_id: str) -> None:
        """Attach a storage device.

        The intent of this function is to simulate a "juju attach-storage" call.
        It will trigger a storage-attached hook if the storage unit in question exists
        and is presently marked as detached.

        Args:
            storage_id: The full storage ID of the storage unit being attached, including the
                storage key, e.g. my-storage/0.
        """
        if self._backend._storage_attach(storage_id) and self._hooks_enabled:
            storage_name, storage_index = storage_id.split('/', 1)
            storage_index = int(storage_index)
            self.charm.on[storage_name].storage_attached.emit(
                model.Storage(storage_name, storage_index, self._backend))

    def remove_storage(self, storage_id: str) -> None:
        """Attach a storage device.

        The intent of this function is to simulate a "juju remove-storage" call.
        It will trigger a storage-detaching hook if the storage unit in question exists
        and is presently marked as detached.  Additionally, it will remove the storage
        unit from the testing backend.

        Args:
            storage_id: The full storage ID of the storage unit being removed, including the
                storage key, e.g. my-storage/0.
        """
        storage_name, storage_index = storage_id.split('/', 1)
        storage_index = int(storage_index)
        if storage_name not in self._meta.storages:
            raise RuntimeError(
                "the key '{}' is not specified as a storage key in metadata".format(storage_name))
        is_attached = self._backend._storage_is_attached(storage_name, storage_index)
        if self.charm is not None and self._hooks_enabled and is_attached:
            self.charm.on[storage_name].storage_detaching.emit(
                model.Storage(storage_name, storage_index, self._backend))
        self._backend._storage_remove(storage_id)

    def add_relation(self, relation_name: str, remote_app: str) -> int:
        """Declare that there is a new relation between this app and `remote_app`.

        In the case of adding peer relations, `remote_app` is *this* app.  This function creates a
        relation with an application and will trigger a relation-created hook. To relate units (and
        trigger relation-joined and relation-changed hooks), you should also call
        :meth:`.add_relation_unit`.

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
        self._backend._relation_app_and_units[rel_id] = {
            "app": remote_app,
            "units": [],
        }
        # Reload the relation_ids list
        if self._model is not None:
            self._model.relations._invalidate(relation_name)
        self._emit_relation_created(relation_name, rel_id, remote_app)
        return rel_id

    def remove_relation(self, relation_id: int) -> None:
        """Remove a relation.

        Args:
            relation_id: The relation ID for the relation to be removed.

        Raises:
            RelationNotFoundError: if relation id is not valid
        """
        try:
            relation_name = self._backend._relation_names[relation_id]
            remote_app = self._backend.relation_remote_app_name(relation_id)
        except KeyError as e:
            raise model.RelationNotFoundError from e

        for unit_name in self._backend._relation_list_map[relation_id].copy():
            self.remove_relation_unit(relation_id, unit_name)

        self._emit_relation_broken(relation_name, relation_id, remote_app)
        if self._model is not None:
            self._model.relations._invalidate(relation_name)

        self._backend._relation_app_and_units.pop(relation_id)
        self._backend._relation_data.pop(relation_id)
        self._backend._relation_list_map.pop(relation_id)
        self._backend._relation_ids_map[relation_name].remove(relation_id)
        self._backend._relation_names.pop(relation_id)

    def _emit_relation_created(self, relation_name: str, relation_id: int,
                               remote_app: str) -> None:
        """Trigger relation-created for a given relation with a given remote application."""
        if self._charm is None or not self._hooks_enabled:
            return
        relation = self._model.get_relation(relation_name, relation_id)
        app = self._model.get_app(remote_app)
        self._charm.on[relation_name].relation_created.emit(
            relation, app)

    def _emit_relation_broken(self, relation_name: str, relation_id: int,
                              remote_app: str) -> None:
        """Trigger relation-broken for a given relation with a given remote application."""
        if self._charm is None or not self._hooks_enabled:
            return
        relation = self._model.get_relation(relation_name, relation_id)
        app = self._model.get_app(remote_app)
        self._charm.on[relation_name].relation_broken.emit(
            relation, app)

    def add_relation_unit(self, relation_id: int, remote_unit_name: str) -> None:
        """Add a new unit to a relation.

        Example::

          rel_id = harness.add_relation('db', 'postgresql')
          harness.add_relation_unit(rel_id, 'postgresql/0')

        This will trigger a `relation_joined` event. This would naturally be
        followed by a `relation_changed` event, which you can trigger with
        :meth:`.update_relation_data`. This separation is artificial in the
        sense that Juju will always fire the two, but is intended to make
        testing relations and their data bags slightly more natural.

        Args:
            relation_id: The integer relation identifier (as returned by add_relation).
            remote_unit_name: A string representing the remote unit that is being added.

        Return:
            None
        """
        self._backend._relation_list_map[relation_id].append(remote_unit_name)
        self._backend._relation_data[relation_id][remote_unit_name] = {}
        # TODO: jam 2020-08-03 This is where we could assert that the unit name matches the
        #  application name (eg you don't have a relation to 'foo' but add units of 'bar/0'
        self._backend._relation_app_and_units[relation_id]["units"].append(remote_unit_name)
        relation_name = self._backend._relation_names[relation_id]
        # Make sure that the Model reloads the relation_list for this relation_id, as well as
        # reloading the relation data for this unit.
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

    def remove_relation_unit(self, relation_id: int, remote_unit_name: str) -> None:
        """Remove a unit from a relation.

        Example::

          rel_id = harness.add_relation('db', 'postgresql')
          harness.add_relation_unit(rel_id, 'postgresql/0')
          ...
          harness.remove_relation_unit(rel_id, 'postgresql/0')

        This will trigger a `relation_departed` event. This would
        normally be followed by a `relation_changed` event triggered
        by Juju. However when using the test harness a
        `relation_changed` event must be triggererd using
        :meth:`.update_relation_data`. This deviation from normal Juju
        behaviour, facilitates testing by making each step in the
        charm life cycle explicit.

        Args:
            relation_id: The integer relation identifier (as returned by add_relation).
            remote_unit_name: A string representing the remote unit that is being added.

        Raises:
            KeyError: if relation_id or remote_unit_name is not valid
            ValueError: if remote_unit_name is not valid
        """
        relation_name = self._backend._relation_names[relation_id]

        # gather data to invalidate cache later
        remote_unit = self._model.get_unit(remote_unit_name)
        relation = self._model.get_relation(relation_name, relation_id)
        unit_cache = relation.data.get(remote_unit, None)

        # remove the unit from the list of units in the relation
        relation.units.remove(remote_unit)

        self._emit_relation_departed(relation_id, remote_unit_name)
        # remove the relation data for the departed unit now that the event has happened
        self._backend._relation_list_map[relation_id].remove(remote_unit_name)
        self._backend._relation_app_and_units[relation_id]["units"].remove(remote_unit_name)
        self._backend._relation_data[relation_id].pop(remote_unit_name)
        self.model._relations._invalidate(relation_name=relation.name)

        if unit_cache is not None:
            unit_cache._invalidate()

    def _emit_relation_departed(self, relation_id, unit_name):
        """Trigger relation-departed event for a given relation id and unit."""
        if self._charm is None or not self._hooks_enabled:
            return
        rel_name = self._backend._relation_names[relation_id]
        relation = self.model.get_relation(rel_name, relation_id)
        if '/' in unit_name:
            app_name = unit_name.split('/')[0]
            app = self.model.get_app(app_name)
            unit = self.model.get_unit(unit_name)
        else:
            raise ValueError('Invalid Unit Name')
        self._charm.on[rel_name].relation_departed.emit(relation, app, unit)

    def get_relation_data(self, relation_id: int, app_or_unit: AppUnitOrName) -> typing.Mapping:
        """Get the relation data bucket for a single app or unit in a given relation.

        This ignores all of the safety checks of who can and can't see data in relations (eg,
        non-leaders can't read their own application's relation data because there are no events
        that keep that data up-to-date for the unit).

        Args:
            relation_id: The relation whose content we want to look at.
            app_or_unit: An Application or Unit instance, or its name, whose data we want to read
        Return:
            A dict containing the relation data for `app_or_unit` or None.

        Raises:
            KeyError: if relation_id doesn't exist
        """
        if hasattr(app_or_unit, 'name'):
            app_or_unit = app_or_unit.name
        return self._backend._relation_data[relation_id].get(app_or_unit, None)

    def get_pod_spec(self) -> (typing.Mapping, typing.Mapping):
        """Return the content of the pod spec as last set by the charm.

        This returns both the pod spec and any k8s_resources that were supplied.
        See the signature of Model.pod.set_spec
        """
        return self._backend._pod_spec

    def get_container_pebble_plan(
            self, container_name: str
    ) -> pebble.Plan:
        """Return the current Plan that pebble is executing for the given container.

        Args:
            container_name: The simple name of the associated container
        Return:
            The pebble.Plan for this container. You can use :meth:`ops.pebble.Plan.to_yaml` to get
            a string form for the content. Will raise KeyError if no pebble client exists
            for that container name. (should only happen if container is not present in
            metadata.yaml)
        """
        socket_path = '/charm/containers/{}/pebble.socket'.format(container_name)
        client = self._backend._pebble_clients.get(socket_path)
        if client is None:
            raise KeyError('no known pebble client for container "{}"'.format(container_name))
        return client.get_plan()

    def container_pebble_ready(self, container_name: str):
        """Fire the pebble_ready hook for the associated container.

        This will do nothing if the begin() has not been called.  If
        SIMULATE_CAN_CONNECT is True, this will switch the given
        container's can_connect state to True before the hook
        function is called.
        """
        if self.charm is None:
            return
        container = self.model.unit.get_container(container_name)
        if SIMULATE_CAN_CONNECT:
            self.set_can_connect(container, True)
        self.charm.on[container_name].pebble_ready.emit(container)

    def get_workload_version(self) -> str:
        """Read the workload version that was set by the unit."""
        return self._backend._workload_version

    def set_model_info(self, name: str = None, uuid: str = None) -> None:
        """Set the name and uuid of the Model that this is representing.

        This cannot be called once begin() has been called. But it lets you set the value that
        will be returned by Model.name and Model.uuid.

        This is a convenience method to invoke both Harness.set_model_name
        and Harness.set_model_uuid at once.
        """
        self.set_model_name(name)
        self.set_model_uuid(uuid)

    def set_model_name(self, name: str) -> None:
        """Set the name of the Model that this is representing.

        This cannot be called once begin() has been called. But it lets you set the value that
        will be returned by Model.name.
        """
        if self._charm is not None:
            raise RuntimeError('cannot set the Model name after begin()')
        self._backend.model_name = name

    def set_model_uuid(self, uuid: str) -> None:
        """Set the uuid of the Model that this is representing.

        This cannot be called once begin() has been called. But it lets you set the value that
        will be returned by Model.uuid.
        """
        if self._charm is not None:
            raise RuntimeError('cannot set the Model uuid after begin()')
        self._backend.model_uuid = uuid

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
        values_have_changed = False
        for k, v in key_values.items():
            if v == '':
                if new_values.pop(k, None) != v:
                    values_have_changed = True
            else:
                if k not in new_values or new_values[k] != v:
                    new_values[k] = v
                    values_have_changed = True

        # Update the relation data in any case to avoid spurious references
        # by an test to an updated value to be invalidated by a lack of assignment
        self._backend._relation_data[relation_id][app_or_unit] = new_values

        if not values_have_changed:
            # Do not issue a relation changed event if the data bags have not changed
            return

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

    def _update_config(
            self,
            key_values: typing.Mapping[str, str] = None,
            unset: typing.Iterable[str] = (),
    ) -> None:
        """Update the config as seen by the charm.

        This will *not* trigger a `config_changed` event, and is intended for internal use.

        Note that the `key_values` mapping will only add or update configuration items.
        To remove existing ones, see the `unset` parameter.

        Args:
            key_values: A Mapping of key:value pairs to update in config.
            unset: An iterable of keys to remove from config.
        """
        # NOTE: jam 2020-03-01 Note that this sort of works "by accident". Config
        # is a LazyMapping, but its _load returns a dict and this method mutates
        # the dict that Config is caching. Arguably we should be doing some sort
        # of charm.framework.model.config._invalidate()
        config = self._backend._config
        if key_values is not None:
            for key, value in key_values.items():
                if key in self._defaults:
                    if value is not None:
                        config[key] = value
                else:
                    raise ValueError("unknown config option: '{}'".format(key))

        for key in unset:
            # When the key is unset, revert to the default if one exists
            default = self._defaults.get(key, None)
            if default is not None:
                config[key] = default
            else:
                config.pop(key, None)

    def update_config(
            self,
            key_values: typing.Mapping[str, str] = None,
            unset: typing.Iterable[str] = (),
    ) -> None:
        """Update the config as seen by the charm.

        This will trigger a `config_changed` event.

        Note that the `key_values` mapping will only add or update configuration items.
        To remove existing ones, see the `unset` parameter.

        Args:
            key_values: A Mapping of key:value pairs to update in config.
            unset: An iterable of keys to remove from Config. (Note that this does
                not currently reset the config values to the default defined in config.yaml.)
        """
        self._update_config(key_values, unset)
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

    def set_planned_units(self, num_units: int) -> None:
        """Set the number of "planned" units  that "Application.planned_units" should return.

        In real world circumstances, this number will be the number of units in the
        application. E.g., this number will be the number of peers this unit has, plus one, as we
        count our own unit in the total.

        A change to the return from planned_units will not generate an event. Typically, a charm
        author would check planned units during a config or install hook, or after receiving a peer
        relation joined event.

        """
        if num_units < 0:
            raise TypeError("num_units must be 0 or a positive integer.")
        self._backend._planned_units = num_units

    def reset_planned_units(self):
        """Reset the planned units override.

        This allows the harness to fall through to the built in methods that will try to
        guess at a value for planned units, based on the number of peer relations that
        have been setup in the testing harness.

        """
        self._backend._planned_units = None

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


def _copy_docstrings(source_cls):
    """Copy the docstrings from source_cls to target_cls.

    Use this as:
      @_copy_docstrings(source_class)
      class TargetClass:

    And for any public method that exists on both classes, it will copy the
    __doc__ for that method.
    """
    def decorator(target_cls):
        for meth_name, orig_method in target_cls.__dict__.items():
            if meth_name.startswith('_'):
                continue
            source_method = source_cls.__dict__.get(meth_name)
            if source_method is not None and source_method.__doc__:
                target_cls.__dict__[meth_name].__doc__ = source_method.__doc__
        return target_cls
    return decorator


class _ResourceEntry:
    """Tracks the contents of a Resource."""

    def __init__(self, resource_name):
        self.name = resource_name


@_copy_docstrings(model._ModelBackend)
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
        self.model_name = None
        self.model_uuid = 'f2c1b2a6-e006-11eb-ba80-0242ac130004'
        self._calls = []
        self._meta = meta
        self._relation_ids_map = {}  # relation name to [relation_ids,...]
        self._relation_names = {}  # reverse map from relation_id to relation_name
        self._relation_list_map = {}  # relation_id: [unit_name,...]
        self._relation_data = {}  # {relation_id: {name: data}}
        # {relation_id: {"app": app_name, "units": ["app/0",...]}
        self._relation_app_and_units = {}
        self._config = {}
        self._is_leader = False
        self._resources_map = {}  # {resource_name: resource_content}
        self._pod_spec = None
        self._app_status = {'status': 'unknown', 'message': ''}
        self._unit_status = {'status': 'maintenance', 'message': ''}
        self._workload_version = None
        self._resource_dir = None
        # Format:
        # { "storage_name": {"<ID1>": { <other-properties> }, ... }
        # <ID1>: device id that is key for given storage_name
        # Initialize the _storage_list with values present on metadata.yaml
        self._storage_list = {k: {} for k in self._meta.storages}
        self._storage_detached = {k: set() for k in self._meta.storages}
        self._storage_id_counter = 0
        # {socket_path : _TestingPebbleClient}
        # socket_path = '/charm/containers/{container_name}/pebble.socket'
        self._pebble_clients = {}  # type: {str: _TestingPebbleClient}
        self._pebble_clients_can_connect = {}  # type: {_TestingPebbleClient: bool}
        self._planned_units = None

    def _can_connect(self, pebble_client) -> bool:
        """Returns whether the mock client is active and can support API calls with no errors."""
        return self._pebble_clients_can_connect[pebble_client]

    def _set_can_connect(self, pebble_client, val):
        """Manually sets the can_connect state for the given mock client."""
        if not SIMULATE_CAN_CONNECT:
            raise RuntimeError('must set SIMULATE_CAN_CONNECT=True before using set_can_connect')
        if pebble_client not in self._pebble_clients_can_connect:
            msg = 'cannot set can_connect for the client - are you running a "real" pebble test?'
            raise RuntimeError(msg)
        self._pebble_clients_can_connect[pebble_client] = val

    def _cleanup(self):
        if self._resource_dir is not None:
            self._resource_dir.cleanup()
            self._resource_dir = None

    def _get_resource_dir(self) -> pathlib.Path:
        if self._resource_dir is None:
            # In actual Juju, the resource path for a charm's resource is
            # $AGENT_DIR/resources/$RESOURCE_NAME/$RESOURCE_FILENAME
            # However, charms shouldn't depend on this.
            self._resource_dir = tempfile.TemporaryDirectory(prefix='tmp-ops-test-resource-')
        return pathlib.Path(self._resource_dir.name)

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

    def relation_remote_app_name(self, relation_id: int) -> typing.Optional[str]:
        if relation_id not in self._relation_app_and_units:
            # Non-existent or dead relation
            return None
        return self._relation_app_and_units[relation_id]['app']

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
        if resource_name not in self._resources_map:
            raise model.ModelError(
                "ERROR could not download resource: HTTP request failed: "
                "Get https://.../units/unit-{}/resources/{}: resource#{}/{} not found".format(
                    self.unit_name.replace('/', '-'), resource_name, self.app_name, resource_name
                ))
        filename, contents = self._resources_map[resource_name]
        resource_dir = self._get_resource_dir()
        resource_filename = resource_dir / resource_name / filename
        if not resource_filename.exists():
            if isinstance(contents, bytes):
                mode = 'wb'
            else:
                mode = 'wt'
            resource_filename.parent.mkdir(exist_ok=True)
            with resource_filename.open(mode=mode) as resource_file:
                resource_file.write(contents)
        return resource_filename

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
        return list(index for index in self._storage_list[name]
                    if self._storage_is_attached(name, index))

    def storage_get(self, storage_name_id, attribute):
        name, index = storage_name_id.split("/", 1)
        index = int(index)
        try:
            if index in self._storage_detached[name]:
                raise KeyError()  # Pretend the key isn't there
            else:
                return self._storage_list[name][index][attribute]
        except KeyError:
            raise model.ModelError(
                'ERROR invalid value "{}/{}" for option -s: storage not found'.format(name, index))

    def storage_add(self, name: str, count: int = 1):
        if name not in self._storage_list:
            self._storage_list[name] = {}
        result = []
        for i in range(count):
            index = self._storage_id_counter
            self._storage_id_counter += 1
            self._storage_list[name][index] = {
                "location": "/{}/{}".format(name, index)
            }
            result.append(index)
        return result

    def _storage_detach(self, storage_id: str):
        # NOTE: This is an extra function for _TestingModelBackend to simulate
        # detachment of a storage unit.  This is not present in ops.model._ModelBackend.
        name, index = storage_id.split('/', 1)
        index = int(index)
        if self._storage_is_attached(name, index):
            self._storage_detached[name].add(index)

    def _storage_attach(self, storage_id: str):
        # NOTE: This is an extra function for _TestingModelBackend to simulate
        # re-attachment of a storage unit.  This is not present in
        # ops.model._ModelBackend.
        name, index = storage_id.split('/', 1)
        index = int(index)
        if not self._storage_is_attached(name, index):
            self._storage_detached[name].remove(index)
            return True
        return False

    def _storage_is_attached(self, storage_name, storage_index):
        return storage_index not in self._storage_detached[storage_name]

    def _storage_remove(self, storage_id: str):
        # NOTE: This is an extra function for _TestingModelBackend to simulate
        # full removal of a storage unit.  This is not present in
        # ops.model._ModelBackend.
        self._storage_detach(storage_id)
        name, index = storage_id.split('/', 1)
        index = int(index)
        self._storage_list[name].pop(index, None)

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

    def add_metrics(self, metrics, labels=None):
        raise NotImplementedError(self.add_metrics)

    @classmethod
    def log_split(cls, message, max_len):
        raise NotImplementedError(cls.log_split)

    def juju_log(self, level, msg):
        raise NotImplementedError(self.juju_log)

    def get_pebble(self, socket_path: str):
        client = self._pebble_clients.get(socket_path, None)
        if client is None:
            client = _TestingPebbleClient(self)
            self._pebble_clients[socket_path] = client
        self._pebble_clients_can_connect[client] = not SIMULATE_CAN_CONNECT
        return client

    def planned_units(self):
        """Simulate fetching the number of planned application units from the model.

        If self._planned_units is None, then we simulate what the Juju controller will do, which is
        to report the number of peers, plus one (we include this unit in the count). This can be
        overridden for testing purposes: a charm author can set the number of planned units
        explicitly by calling `Harness.set_planned_units`
        """
        if self._planned_units is not None:
            return self._planned_units

        units = []
        peer_names = set(self._meta.peers.keys())
        for peer_id, peer_name in self._relation_names.items():
            if peer_name not in peer_names:
                continue
            peer_units = self._relation_list_map[peer_id]
            units += peer_units

        count = len(set(units))  # de-dupe and get length.

        return count + 1  # Account for this unit.


@_copy_docstrings(pebble.Client)
class _TestingPebbleClient:
    """This conforms to the interface for pebble.Client but provides canned data.

    DO NOT use this class directly, it is used by `Harness`_ to run interactions with Pebble.
    `Harness`_ is responsible for maintaining the internal consistency of the values here,
    as the only public methods of this type are for implementing Client.
    """

    def __init__(self, backend: _TestingModelBackend):
        self._backend = _TestingModelBackend
        self._layers = {}
        # Has a service been started/stopped?
        self._service_status = {}
        self._fs = _MockFilesystem()
        self._backend = backend

    def _check_connection(self):
        if not self._backend._can_connect(self):
            raise pebble.ConnectionError('cannot connect to pebble')

    def get_system_info(self) -> pebble.SystemInfo:
        self._check_connection()
        return pebble.SystemInfo(version='1.0.0')

    def get_warnings(
            self, select: pebble.WarningState = pebble.WarningState.PENDING,
    ) -> typing.List['pebble.Warning']:
        raise NotImplementedError(self.get_warnings)

    def ack_warnings(self, timestamp: datetime.datetime) -> int:
        raise NotImplementedError(self.ack_warnings)

    def get_changes(
            self, select: pebble.ChangeState = pebble.ChangeState.IN_PROGRESS, service: str = None,
    ) -> typing.List[pebble.Change]:
        raise NotImplementedError(self.get_changes)

    def get_change(self, change_id: pebble.ChangeID) -> pebble.Change:
        raise NotImplementedError(self.get_change)

    def abort_change(self, change_id: pebble.ChangeID) -> pebble.Change:
        raise NotImplementedError(self.abort_change)

    def autostart_services(self, timeout: float = 30.0, delay: float = 0.1) -> pebble.ChangeID:
        self._check_connection()
        for name, service in self._render_services().items():
            # TODO: jam 2021-04-20 This feels awkward that Service.startup might be a string or
            #  might be an enum. Probably should make Service.startup a property rather than an
            #  attribute.
            if service.startup == '':
                startup = pebble.ServiceStartup.DISABLED
            else:
                startup = pebble.ServiceStartup(service.startup)
            if startup == pebble.ServiceStartup.ENABLED:
                self._service_status[name] = pebble.ServiceStatus.ACTIVE

    def replan_services(self, timeout: float = 30.0, delay: float = 0.1) -> pebble.ChangeID:
        return self.autostart_services(timeout, delay)

    def start_services(
            self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> pebble.ChangeID:
        # A common mistake is to pass just the name of a service, rather than a list of services,
        # so trap that so it is caught quickly.
        if isinstance(services, str):
            raise TypeError('start_services should take a list of names, not just "{}"'.format(
                services))

        self._check_connection()

        # Note: jam 2021-04-20 We don't implement ChangeID, but the default caller of this is
        # Container.start() which currently ignores the return value
        known_services = self._render_services()
        # Names appear to be validated before any are activated, so do two passes
        for name in services:
            if name not in known_services:
                # TODO: jam 2021-04-20 This needs a better error type
                raise RuntimeError('400 Bad Request: service "{}" does not exist'.format(name))
            current = self._service_status.get(name, pebble.ServiceStatus.INACTIVE)
            if current == pebble.ServiceStatus.ACTIVE:
                # TODO: jam 2021-04-20 I believe pebble actually validates all the service names
                #  can be started before starting any, and gives a list of things that couldn't
                #  be done, but this is good enough for now
                raise pebble.ChangeError('''\
cannot perform the following tasks:
- Start service "{}" (service "{}" was previously started)
'''.format(name, name), change=1234)  # the change id is not respected
        for name in services:
            # If you try to start a service which is started, you get a ChangeError:
            # $ PYTHONPATH=. python3 ./test/pebble_cli.py start serv
            # ChangeError: cannot perform the following tasks:
            # - Start service "serv" (service "serv" was previously started)
            self._service_status[name] = pebble.ServiceStatus.ACTIVE

    def stop_services(
            self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> pebble.ChangeID:
        # handle a common mistake of passing just a name rather than a list of names
        if isinstance(services, str):
            raise TypeError('stop_services should take a list of names, not just "{}"'.format(
                services))

        self._check_connection()

        # TODO: handle invalid names
        # Note: jam 2021-04-20 We don't implement ChangeID, but the default caller of this is
        # Container.stop() which currently ignores the return value
        known_services = self._render_services()
        for name in services:
            if name not in known_services:
                # TODO: jam 2021-04-20 This needs a better error type
                #  400 Bad Request: service "bal" does not exist
                raise RuntimeError('400 Bad Request: service "{}" does not exist'.format(name))
            current = self._service_status.get(name, pebble.ServiceStatus.INACTIVE)
            if current != pebble.ServiceStatus.ACTIVE:
                # TODO: jam 2021-04-20 I believe pebble actually validates all the service names
                #  can be started before starting any, and gives a list of things that couldn't
                #  be done, but this is good enough for now
                raise pebble.ChangeError('''\
ChangeError: cannot perform the following tasks:
- Stop service "{}" (service "{}" is not active)
'''.format(name, name), change=1234)  # the change id is not respected
        for name in services:
            self._service_status[name] = pebble.ServiceStatus.INACTIVE

    def restart_services(
            self, services: typing.List[str], timeout: float = 30.0, delay: float = 0.1,
    ) -> pebble.ChangeID:
        # handle a common mistake of passing just a name rather than a list of names
        if isinstance(services, str):
            raise TypeError('restart_services should take a list of names, not just "{}"'.format(
                services))

        self._check_connection()

        # TODO: handle invalid names
        # Note: jam 2021-04-20 We don't implement ChangeID, but the default caller of this is
        # Container.restart() which currently ignores the return value
        known_services = self._render_services()
        for name in services:
            if name not in known_services:
                # TODO: jam 2021-04-20 This needs a better error type
                #  400 Bad Request: service "bal" does not exist
                raise RuntimeError('400 Bad Request: service "{}" does not exist'.format(name))
        for name in services:
            self._service_status[name] = pebble.ServiceStatus.ACTIVE

    def wait_change(
            self, change_id: pebble.ChangeID, timeout: float = 30.0, delay: float = 0.1,
    ) -> pebble.Change:
        raise NotImplementedError(self.wait_change)

    def add_layer(
            self, label: str, layer: typing.Union[str, dict, pebble.Layer], *,
            combine: bool = False):
        # I wish we could combine some of this helpful object corralling with the actual backend,
        # rather than having to re-implement it. Maybe we could subclass
        if not isinstance(label, str):
            raise TypeError('label must be a str, not {}'.format(type(label).__name__))

        if isinstance(layer, (str, dict)):
            layer_obj = pebble.Layer(layer)
        elif isinstance(layer, pebble.Layer):
            layer_obj = layer
        else:
            raise TypeError('layer must be str, dict, or pebble.Layer, not {}'.format(
                type(layer).__name__))

        self._check_connection()

        if label in self._layers:
            # TODO: jam 2021-04-19 These should not be RuntimeErrors but should be proper error
            #  types. https://github.com/canonical/operator/issues/514
            if not combine:
                raise RuntimeError('400 Bad Request: layer "{}" already exists'.format(label))
            layer = self._layers[label]
            for name, service in layer_obj.services.items():
                # 'override' is actually single quoted in the real error, but
                # it shouldn't be, hopefully that gets cleaned up.
                if not service.override:
                    raise RuntimeError('500 Internal Server Error: layer "{}" must define'
                                       '"override" for service "{}"'.format(label, name))
                if service.override not in ('merge', 'replace'):
                    raise RuntimeError('500 Internal Server Error: layer "{}" has invalid '
                                       '"override" value on service "{}"'.format(label, name))
                if service.override != 'replace':
                    raise RuntimeError(
                        'override: "{}" unsupported for layer "{}" service "{}"'.format(
                            service.override, label, name))
                layer.services[name] = service
        else:
            self._layers[label] = layer_obj

    def _render_services(self) -> typing.Mapping[str, pebble.Service]:
        services = {}
        for key in sorted(self._layers.keys()):
            layer = self._layers[key]
            for name, service in layer.services.items():
                # TODO: (jam) 2021-04-07 have a way to merge existing services
                services[name] = service
        return services

    def get_plan(self) -> pebble.Plan:
        self._check_connection()
        plan = pebble.Plan('{}')
        services = self._render_services()
        if not services:
            return plan
        for name in sorted(services.keys()):
            plan.services[name] = services[name]
        return plan

    def get_services(self, names: typing.List[str] = None) -> typing.List[pebble.ServiceInfo]:
        if isinstance(names, str):
            raise TypeError('start_services should take a list of names, not just "{}"'.format(
                names))

        self._check_connection()
        services = self._render_services()
        infos = []
        if names is None:
            names = sorted(services.keys())
        for name in sorted(names):
            try:
                service = services[name]
            except KeyError:
                # in pebble, it just returns "nothing matched" if there are 0 matches,
                # but it ignores services it doesn't recognize
                continue
            status = self._service_status.get(name, pebble.ServiceStatus.INACTIVE)
            if service.startup == '':
                startup = pebble.ServiceStartup.DISABLED
            else:
                startup = pebble.ServiceStartup(service.startup)
            info = pebble.ServiceInfo(name,
                                      startup=startup,
                                      current=pebble.ServiceStatus(status))
            infos.append(info)
        return infos

    def pull(self, path: str, *, encoding: str = 'utf-8') -> typing.Union[typing.BinaryIO,
                                                                          typing.TextIO]:
        self._check_connection()
        return self._fs.open(path, encoding=encoding)

    def push(
            self, path: str, source: typing.Union[bytes, str, typing.BinaryIO, typing.TextIO], *,
            encoding: str = 'utf-8', make_dirs: bool = False, permissions: int = None,
            user_id: int = None, user: str = None, group_id: int = None, group: str = None):
        self._check_connection()
        if permissions is not None and not (0 <= permissions <= 0o777):
            raise pebble.PathError(
                'generic-file-error',
                'permissions not within 0o000 to 0o777: {:#o}'.format(permissions))
        try:
            self._fs.create_file(
                path, source, encoding=encoding, make_dirs=make_dirs, permissions=permissions,
                user_id=user_id, user=user, group_id=group_id, group=group)
        except FileNotFoundError as e:
            raise pebble.PathError(
                'not-found', 'parent directory not found: {}'.format(e.args[0]))
        except NonAbsolutePathError as e:
            raise pebble.PathError(
                'generic-file-error',
                'paths must be absolute, got {!r}'.format(e.args[0])
            )

    def list_files(self, path: str, *, pattern: str = None,
                   itself: bool = False) -> typing.List[pebble.FileInfo]:
        self._check_connection()
        try:
            files = [self._fs.get_path(path)]
        except FileNotFoundError:
            # conform with the real pebble api
            raise pebble.APIError(
                body={}, code=404, status='Not Found',
                message="stat {}: no such file or directory".format(path))

        if not itself:
            try:
                files = self._fs.list_dir(path)
            except NotADirectoryError:
                pass

        if pattern is not None:
            files = [file for file in files if fnmatch.fnmatch(file.name, pattern)]

        type_mappings = {
            _File: pebble.FileType.FILE,
            _Directory: pebble.FileType.DIRECTORY,
        }
        return [
            pebble.FileInfo(
                path=str(file.path),
                name=file.name,
                type=type_mappings.get(type(file)),
                size=file.size if isinstance(file, _File) else None,
                permissions=file.kwargs.get('permissions'),
                last_modified=file.last_modified,
                user_id=file.kwargs.get('user_id'),
                user=file.kwargs.get('user'),
                group_id=file.kwargs.get('group_id'),
                group=file.kwargs.get('group'),
            )
            for file in files
        ]

    def make_dir(
            self, path: str, *, make_parents: bool = False, permissions: int = None,
            user_id: int = None, user: str = None, group_id: int = None, group: str = None):
        self._check_connection()
        if permissions is not None and not (0 <= permissions <= 0o777):
            raise pebble.PathError(
                'generic-file-error',
                'permissions not within 0o000 to 0o777: {:#o}'.format(permissions))
        try:
            self._fs.create_dir(
                path, make_parents=make_parents, permissions=permissions,
                user_id=user_id, user=user, group_id=group_id, group=group)
        except FileNotFoundError as e:
            # Parent directory doesn't exist and make_parents is False
            raise pebble.PathError(
                'not-found', 'parent directory not found: {}'.format(e.args[0]))
        except NotADirectoryError as e:
            # Attempted to create a subdirectory of a file
            raise pebble.PathError('generic-file-error', 'not a directory: {}'.format(e.args[0]))
        except NonAbsolutePathError as e:
            raise pebble.PathError(
                'generic-file-error',
                'paths must be absolute, got {!r}'.format(e.args[0])
            )

    def remove_path(self, path: str, *, recursive: bool = False):
        self._check_connection()
        try:
            file_or_dir = self._fs.get_path(path)
        except FileNotFoundError:
            if recursive:
                # Pebble doesn't give not-found error when recursive is specified
                return
            raise pebble.PathError(
                'not-found', 'remove {}: no such file or directory'.format(path))

        if isinstance(file_or_dir, _Directory) and len(file_or_dir) > 0 and not recursive:
            raise pebble.PathError(
                'generic-file-error', 'cannot remove non-empty directory without recursive=True')
        self._fs.delete_path(path)

    def exec(self, command, **kwargs):
        raise NotImplementedError(self.exec)

    def send_signal(self, sig: typing.Union[int, str], *service_names: str):
        if not service_names:
            raise TypeError('send_signal expected at least 1 service name, got 0')
        self._check_connection()

        # Convert signal to str
        if isinstance(sig, int):
            sig = signal.Signals(sig).name

        # pebble first validates the service name, and then the signal name

        plan = self.get_plan()
        for service in service_names:
            if service not in plan.services or not self.get_services([service])[0].is_running():
                # conform with the real pebble api
                message = 'cannot send signal to "{}": service is not running'.format(service)
                body = {'type': 'error', 'status-code': 500, 'status': 'Internal Server Error',
                        'result': {'message': message}}
                raise pebble.APIError(
                    body=body, code=500, status='Internal Server Error', message=message
                )

        # Check if signal name is valid
        try:
            signal.Signals[sig]
        except KeyError:
            # conform with the real pebble api
            message = 'cannot send signal to "{}": invalid signal name "{}"'.format(
                service_names[0],
                sig)
            body = {'type': 'error', 'status-code': 500, 'status': 'Internal Server Error',
                    'result': {'message': message}}
            raise pebble.APIError(
                body=body,
                code=500,
                status='Internal Server Error',
                message=message)

    def get_checks(self, level=None, names=None):
        raise NotImplementedError(self.get_checks)


class NonAbsolutePathError(Exception):
    """Error raised by _MockFilesystem.

    This error is raised when an absolute path is required but the code instead encountered a
    relative path.
    """


class _MockFilesystem:
    r"""An in-memory mock of a pebble-controlled container's filesystem.

    For now, the filesystem is assumed to be a POSIX-style filesytem; Windows-style directories
    (e.g. \, \foo\bar, C:\foo\bar) are not supported.
    """

    def __init__(self):
        self.root = _Directory(pathlib.PurePosixPath('/'))

    def create_dir(self, path: str, make_parents: bool = False, **kwargs) -> '_Directory':
        if not path.startswith('/'):
            raise NonAbsolutePathError(path)
        current_dir = self.root
        tokens = pathlib.PurePosixPath(path).parts[1:]
        for token in tokens[:-1]:
            if token in current_dir:
                current_dir = current_dir[token]
            else:
                if make_parents:
                    # NOTE: other parameters (e.g. ownership, permissions) only get applied to the
                    # final directory.
                    # (At the time of writing, Pebble defaults to 0o755 permissions and root:root
                    # ownership.)
                    current_dir = current_dir.create_dir(token)
                else:
                    raise FileNotFoundError(str(current_dir.path / token))
            if isinstance(current_dir, _File):
                raise NotADirectoryError(str(current_dir.path))

        # Current backend will always raise an error if the final directory component
        # already exists.
        token = tokens[-1]
        if token not in current_dir:
            current_dir = current_dir.create_dir(token, **kwargs)
        else:
            # If 'make_parents' is specified, behave like 'mkdir -p' and ignore if the dir already
            # exists.
            if make_parents:
                current_dir = _Directory(current_dir.path / token)
            else:
                raise FileExistsError(str(current_dir.path / token))
        return current_dir

    def create_file(
            self,
            path: str,
            data: typing.Union[bytes, str, typing.BinaryIO, typing.TextIO],
            encoding: typing.Optional[str] = 'utf-8',
            make_dirs: bool = False,
            **kwargs
    ) -> '_File':
        if not path.startswith('/'):
            raise NonAbsolutePathError(path)
        path_obj = pathlib.PurePosixPath(path)
        try:
            dir_ = self.get_path(path_obj.parent)
        except FileNotFoundError:
            if make_dirs:
                dir_ = self.create_dir(str(path_obj.parent), make_parents=make_dirs)
                # NOTE: other parameters (e.g. ownership, permissions) only get applied to the
                # final directory.
                # (At the time of writing, Pebble defaults to the specified permissions and
                # root:root ownership, which is inconsistent with the push function's
                # behavior for parent directories.)
            else:
                raise
        if not isinstance(dir_, _Directory):
            raise pebble.PathError(
                'generic-file-error', 'parent is not a directory: {}'.format(str(dir_)))
        return dir_.create_file(path_obj.name, data, encoding=encoding, **kwargs)

    def list_dir(self, path) -> typing.List['_File']:
        current_dir = self.root
        tokens = pathlib.PurePosixPath(path).parts[1:]
        for token in tokens:
            try:
                current_dir = current_dir[token]
            except KeyError:
                raise FileNotFoundError(str(current_dir.path / token))
            if isinstance(current_dir, _File):
                raise NotADirectoryError(str(current_dir.path))
            if not isinstance(current_dir, _Directory):
                # For now, ignoring other possible cases besides File and Directory (e.g. Symlink).
                raise NotImplementedError()

        return [child for child in current_dir]

    def open(
            self,
            path: typing.Union[str, pathlib.PurePosixPath],
            encoding: typing.Optional[str] = 'utf-8',
    ) -> typing.Union[typing.BinaryIO, typing.TextIO]:
        path = pathlib.PurePosixPath(path)
        file = self.get_path(path)  # warning: no check re: directories
        if isinstance(file, _Directory):
            raise IsADirectoryError(str(file.path))
        return file.open(encoding=encoding)

    def get_path(self, path: typing.Union[str, pathlib.PurePosixPath]) \
            -> typing.Union['_Directory', '_File']:
        path = pathlib.PurePosixPath(path)
        tokens = path.parts[1:]
        current_object = self.root
        for token in tokens:
            # ASSUMPTION / TESTME: object might be file
            if token in current_object:
                current_object = current_object[token]
            else:
                raise FileNotFoundError(str(current_object.path / token))
        return current_object

    def delete_path(self, path: typing.Union[str, pathlib.PurePosixPath]) -> None:
        path = pathlib.PurePosixPath(path)
        parent_dir = self.get_path(path.parent)
        del parent_dir[path.name]


class _Directory:
    def __init__(self, path: pathlib.PurePosixPath, **kwargs):
        self.path = path
        self._children = {}
        self.last_modified = datetime.datetime.now()
        self.kwargs = kwargs

    @property
    def name(self) -> str:
        # Need to handle special case for root.
        # pathlib.PurePosixPath('/').name is '', but pebble returns '/'.
        return self.path.name if self.path.name else '/'

    def __contains__(self, child: str) -> bool:
        return child in self._children

    def __iter__(self) -> typing.Iterator[typing.Union['_File', '_Directory']]:
        return (value for value in self._children.values())

    def __getitem__(self, key: str) -> typing.Union['_File', '_Directory']:
        return self._children[key]

    def __delitem__(self, key: str) -> None:
        try:
            del self._children[key]
        except KeyError:
            raise FileNotFoundError(str(self.path / key))

    def __len__(self):
        return len(self._children)

    def create_dir(self, name: str, **kwargs) -> '_Directory':
        self._children[name] = _Directory(self.path / name, **kwargs)
        return self._children[name]

    def create_file(
            self,
            name: str,
            data: typing.Union[bytes, str, typing.BinaryIO, typing.TextIO],
            encoding: typing.Optional[str] = 'utf-8',
            **kwargs
    ) -> '_File':
        self._children[name] = _File(self.path / name, data, encoding=encoding, **kwargs)
        return self._children[name]


class _File:
    def __init__(
            self,
            path: pathlib.PurePosixPath,
            data: typing.Union[str, bytes, typing.BinaryIO, typing.TextIO],
            encoding: typing.Optional[str] = 'utf-8',
            **kwargs):

        if hasattr(data, 'read'):
            data = data.read()
        if isinstance(data, str):
            data = data.encode(encoding)
        data_size = len(data)

        self.path = path
        self.data = data
        self.size = data_size
        self.last_modified = datetime.datetime.now()
        self.kwargs = kwargs

    @property
    def name(self) -> str:
        return self.path.name

    def open(
            self,
            encoding: typing.Optional[str] = 'utf-8',
    ) -> typing.Union[typing.TextIO, typing.BinaryIO]:
        if encoding is None:
            return BytesIO(self.data)
        else:
            return StringIO(self.data.decode(encoding))
