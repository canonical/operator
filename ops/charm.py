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

"""Base objects for the Charm, events and metadata."""

from __future__ import annotations

import dataclasses
import enum
import logging
import os
import pathlib
import warnings
from collections.abc import Mapping
from typing import (
    TYPE_CHECKING,
    Any,
    ClassVar,
    Literal,
    NoReturn,
    TextIO,
    TypedDict,
    TypeVar,
    cast,
)

from . import model
from ._private import yaml
from .framework import (
    EventBase,
    EventSource,
    Framework,
    Handle,
    LifecycleEvent,
    Object,
    ObjectEvents,
)
from .jujuversion import JujuVersion

if TYPE_CHECKING:
    from typing_extensions import Required

    _Scopes = Literal['global', 'container']
    _RelationMetaDict = TypedDict(
        '_RelationMetaDict',
        {'interface': Required[str], 'limit': int, 'optional': bool, 'scope': _Scopes},
        total=False,
    )

    _MultipleRange = TypedDict('_MultipleRange', {'range': str})
    _StorageMetaDict = TypedDict(
        '_StorageMetaDict',
        {
            'type': Required[str],
            'description': str,
            'shared': bool,
            'read-only': bool,
            'minimum-size': str,
            'location': str,
            'multiple-range': str,
            'multiple': _MultipleRange,
        },
        total=False,
    )

    _ResourceMetaDict = TypedDict(
        '_ResourceMetaDict',
        {'type': Required[str], 'filename': str, 'description': str},
        total=False,
    )

    _MountDict = TypedDict('_MountDict', {'storage': Required[str], 'location': str}, total=False)


class _ContainerBaseDict(TypedDict):
    name: str
    channel: str
    architectures: list[str]


logger = logging.getLogger(__name__)


class HookEvent(EventBase):
    """Events raised by Juju to progress a charm's lifecycle.

    Hooks are callback methods of a charm class (a subclass of
    :class:`CharmBase`) that are invoked in response to events raised
    by Juju. These callback methods are the means by which a charm
    governs the lifecycle of its application.

    The :class:`HookEvent` class is the base of a type hierarchy of events
    related to the charm's lifecycle.

    :class:`HookEvent` subtypes are grouped into the following categories

    - Core lifecycle events
    - Relation events
    - Storage events
    - Metric events
    """


class ActionEvent(EventBase):
    """Events raised by Juju when an administrator invokes a Juju Action.

    This class is the data type of events triggered when an administrator
    invokes a Juju Action. Callbacks bound to these events may be used
    for responding to the administrator's Juju Action request.

    To read the parameters for the action, see the instance variable
    :attr:`~ops.ActionEvent.params`.
    To respond with the result of the action, call
    :meth:`~ops.ActionEvent.set_results`. To add progress messages that are
    visible as the action is progressing use :meth:`~ops.ActionEvent.log`.
    """

    id: str = ''
    """The Juju ID of the action invocation."""

    params: dict[str, Any]
    """The parameters passed to the action."""

    def __init__(self, handle: Handle, id: str | None = None):
        super().__init__(handle)
        self.id = id  # type: ignore (for backwards compatibility)

    def defer(self) -> NoReturn:
        """Action events are not deferrable like other events.

        This is because an action runs synchronously and the administrator
        is waiting for the result.

        Raises:
            RuntimeError: always.
        """
        raise RuntimeError('cannot defer action events')

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to record the action.

        Not meant to be called directly by charm code.
        """
        self.id = cast('str', snapshot['id'])
        # Params are loaded at restore rather than __init__ because
        # the model is not available in __init__.
        self.params = self.framework.model._backend.action_get()

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        return {'id': self.id}

    def set_results(self, results: dict[str, Any]):
        """Report the result of the action.

        Juju eventually only accepts a str:str mapping, so we will attempt
        to flatten any more complex data structure like so:

        * ``{'a': 'b'}`` becomes ``'a'='b'``
        * ``{'a': {'b': 'c'}}`` becomes ``'a.b'='c'``
        * ``{'a': {'b': 'c', 'd': 'e'}}`` becomes ``'a.b'='c', 'a.d' = 'e'``
        * ``{'a.b': 'c', 'a.d': 'e'}`` is equivalent to the previous example

        Note that duplicate keys are not allowed, so this is invalid::

            {'a': {'b': 'c'}, 'a.b': 'c'}

        Note that the resulting keys must start and end with lowercase
        alphanumeric, and can only contain lowercase alphanumeric, hyphens
        and periods.

        Because results are passed to Juju using the command line, the maximum
        size is around 100KB. However, actions results are designed to be
        small: a few key-value pairs shown in the Juju CLI. If larger content
        is needed, store it in a file and use something like ``juju scp``.

        If any exceptions occur whilst the action is being handled, juju will
        gather any stdout/stderr data (and the return code) and inject them into the
        results object. Thus, the results object might contain the following keys,
        additionally to those specified by the charm code:

        - Stdout
        - Stderr
        - Stdout-encoding
        - Stderr-encoding
        - ReturnCode

        Args:
            results: The result of the action as a Dict

        Raises:
            ModelError: if a reserved key is used.
            ValueError: if ``results`` has a mix of dotted/non-dotted keys that expand out to
                result in duplicate keys, for example: :code:`{'a': {'b': 1}, 'a.b': 2}`. Also
                raised if a dict is passed with a key that fails to meet the format requirements.
            OSError: if extremely large (>100KB) results are provided.
        """
        self.framework.model._backend.action_set(results)

    def log(self, message: str):
        """Send a message that a user will see while the action is running.

        Args:
            message: The message for the user.
        """
        self.framework.model._backend.action_log(message)

    def fail(self, message: str = ''):
        """Report that this action has failed.

        Args:
            message: Optional message to record why it has failed.
        """
        self.framework.model._backend.action_fail(message)

    def load_params(
        self,
        cls: type[_T],
        *args: Any,
        errors: Literal['raise', 'fail'] = 'raise',
        **kwargs: Any,
    ) -> _T:
        """Load the action parameters into an instance of an action class.

        The raw Juju action parameters are passed to the action class's
        ``__init__`` method as keyword arguments, with dashes in names
        converted to underscores.

        For dataclasses and Pydantic ``BaseModel`` subclasses, only fields in
        the Juju action parameters that have a matching field in the class are
        passed as arguments.

        For example::

            class BackupParams(pydantic.BaseModel):
                filename: str

            def _on_do_backup(self, event: ops.ActionEvent):
                params = event.load_params(BackupParams)
                # params.filename contains the value passed by the Juju user.

        Any additional positional or keyword arguments will be passed through to
        the action class ``__init__``.

        Args:
            cls: A class that will accept the Juju parameters as keyword
                arguments, and raise ``ValueError`` if validation fails.
            errors: what to do if the parameters are invalid. If ``fail``, this
                will set the action to failed with an appropriate message and
                then immediately exit. If ``raise``, ``load_params`` will not
                catch any exceptions, leaving the charm to handle errors.
            args: positional arguments to pass through to the action class.
            kwargs: keyword arguments to pass through to the action class.

        Returns:
            An instance of the action class that was provided in the ``cls``
            argument with the provided parameter values.

        Raises:
            ValueError: if ``errors`` is set to ``raise`` and instantiating the
                action class raises a ValueError.
        """
        try:
            fields = _juju_fields(cls)
        except ValueError:
            fields = None
        params: dict[str, Any] = kwargs.copy()
        for key, value in sorted(self.params.items()):
            attr = key.replace('-', '_')
            if fields is None:
                params[attr] = value
            else:
                if attr not in fields:
                    continue
                params[fields[attr]] = value
        try:
            return cls(*args, **params)
        except ValueError as e:
            if errors == 'raise':
                raise
            self.fail(f'Error in action parameters: {e}')
            from ._main import _Abort

            raise _Abort(0) from e

    def __repr__(self):
        return f'<{self.__class__.__name__} {self.id=} via {self.handle}>'


class InstallEvent(HookEvent):
    """Event triggered when a charm is installed.

    This event is triggered at the beginning of a charm's
    lifecycle. Any associated callback method should be used to
    perform one-time setup operations, such as installing prerequisite
    software.

    See also: `Juju | Hook | install <https://documentation.ubuntu.com/juju/3.6/reference/hook/#install>`_.
    """


class StartEvent(HookEvent):
    """Event triggered immediately after first configuration change.

    This event is triggered immediately after the first
    :class:`~ops.ConfigChangedEvent`. Callback methods bound to the event should be
    used to ensure that the charm's software is in a running state. Note that
    the charm's software should be configured so as to persist in this state
    through reboots without further intervention on Juju's part.

    See also: `Juju | Hook | start <https://documentation.ubuntu.com/juju/3.6/reference/hook/#start>`_.
    """


class StopEvent(HookEvent):
    """Event triggered when a charm is shut down.

    This event is triggered when an application's removal is requested
    by the client. The event fires immediately before the end of the
    unit's destruction sequence. Callback methods bound to this event
    should be used to ensure that the charm's software is not running,
    and that it will not start again on reboot.

    See also: `Juju | Hook | stop <https://documentation.ubuntu.com/juju/3.6/reference/hook/#stop>`_.
    """

    def defer(self) -> NoReturn:
        """Stop events are not deferrable like other events.

        This is because the unit is in the process of tearing down, and there
        will not be an opportunity for the deferred event to run.

        Raises:
            RuntimeError: always.
        """
        raise RuntimeError('cannot defer stop events')


class RemoveEvent(HookEvent):
    """Event triggered when a unit is about to be terminated.

    This event fires prior to Juju removing the charm and terminating its unit.

    See also: `Juju | Hook | remove <https://documentation.ubuntu.com/juju/3.6/reference/hook/#remove>`_.
    """

    def defer(self) -> NoReturn:
        """Remove events are not deferrable like other events.

        This is because the unit is about to be torn down, and there
        will not be an opportunity for the deferred event to run.

        Raises:
            RuntimeError: always.
        """
        raise RuntimeError('cannot defer remove events')


class ConfigChangedEvent(HookEvent):
    """Event triggered when a configuration change occurs.

    This event will fire in several situations:

    - When the admin reconfigures the charm using the Juju CLI, for example
      ``juju config mycharm foo=bar``. This event notifies the charm of
      its new configuration. (The event itself, however, is not aware of *what*
      specifically has changed in the config).
    - Right after the unit starts up for the first time.
      This event notifies the charm of its initial configuration.
      Typically, this event will fire between an :class:`~ops.InstallEvent`
      and a :class:`~ops.StartEvent` during the startup sequence
      (when a unit is first deployed), but in general it will fire whenever
      the unit is (re)started, for example after pod churn on Kubernetes, on unit
      rescheduling, on unit upgrade or refresh, and so on.
    - As a specific instance of the above point: when networking changes
      (if the machine reboots and comes up with a different IP).
    - When the app config changes, for example when `juju trust` is run.

    Any callback method bound to this event cannot assume that the
    software has already been started; it should not start stopped
    software, but should (if appropriate) restart running software to
    take configuration changes into account.

    See also: `Juju | Hook | config-changed <https://documentation.ubuntu.com/juju/3.6/reference/hook/#config-changed>`_.
    """


class UpdateStatusEvent(HookEvent):
    """Event triggered by a status update request from Juju.

    This event is periodically triggered by Juju so that it can
    provide constant feedback to the administrator about the status of
    the application the charm is modeling. Any callback method bound
    to this event should determine the "health" of the application and
    set the status appropriately.

    The interval between :class:`~ops.UpdateStatusEvent` events can
    be configured model-wide, e.g.  ``juju model-config
    update-status-hook-interval=1m``.

    See also: `Juju | Hook | update-status <https://documentation.ubuntu.com/juju/3.6/reference/hook/#update-status>`_.
    """


class UpgradeCharmEvent(HookEvent):
    """Event triggered by request to upgrade the charm.

    This event will be triggered when an administrator executes ``juju
    upgrade-charm``. The event fires after Juju has unpacked the upgraded charm
    code, and so this event will be handled by the callback method bound to the
    event in the new codebase. The associated callback method is invoked
    provided there is no existing error state. The callback method should be
    used to reconcile current state written by an older version of the charm
    into whatever form that is needed by the current charm version.

    See also: `Juju | Hook | upgrade-charm <https://documentation.ubuntu.com/juju/3.6/reference/hook/#upgrade-charm>`_.
    """


class PreSeriesUpgradeEvent(HookEvent):
    """Event triggered to prepare a unit for series upgrade.

    This event triggers when an administrator executes ``juju upgrade-machine
    <machine> prepare``. The event will fire for each unit that is running on the
    specified machine. Any callback method bound to this event must prepare the
    charm for an upgrade to the series. This may include things like exporting
    database content to a version neutral format, or evacuating running
    instances to other machines.

    It can be assumed that only after all units on a machine have executed the
    callback method associated with this event, the administrator will initiate
    steps to actually upgrade the series.  After the upgrade has been completed,
    the :class:`~ops.PostSeriesUpgradeEvent` will fire.

    See also: `Juju | Hook | pre-series-upgrade <https://documentation.ubuntu.com/juju/3.6/reference/hook/#pre-series-upgrade>`_.

    .. jujuremoved:: 4.0
    """

    def __init__(self, handle: Handle):
        warnings.warn(
            'pre-series-upgrade events will not be emitted from Juju 4.0 onwards',
            DeprecationWarning,
            stacklevel=3,
        )
        super().__init__(handle)


class PostSeriesUpgradeEvent(HookEvent):
    """Event triggered after a series upgrade.

    This event is triggered after the administrator has done a distribution
    upgrade (or rolled back and kept the same series). It is called in response
    to ``juju upgrade-machine <machine> complete``. Associated charm callback
    methods are expected to do whatever steps are necessary to reconfigure their
    applications for the new series. This may include things like populating the
    upgraded version of a database. Note however charms are expected to check if
    the series has actually changed or whether it was rolled back to the
    original series.

    See also: `Juju | Hook | post-series-upgrade <https://documentation.ubuntu.com/juju/3.6/reference/hook/#post-series-upgrade>`_.

    .. jujuremoved:: 4.0
    """

    def __init__(self, handle: Handle):
        warnings.warn(
            'post-series-upgrade events will not be emitted from Juju 4.0 onwards',
            DeprecationWarning,
            stacklevel=3,
        )
        super().__init__(handle)


class LeaderElectedEvent(HookEvent):
    """Event triggered when a new leader has been elected.

    Juju will trigger this event when a new leader unit is chosen for
    a given application.

    This event fires at least once after Juju selects a leader
    unit. Callback methods bound to this event may take any action
    required for the elected unit to assert leadership. Note that only
    the elected leader unit will receive this event.

    See also: `Juju | Hook | leader-elected <https://documentation.ubuntu.com/juju/3.6/reference/hook/#leader-elected>`_.
    """


class LeaderSettingsChangedEvent(HookEvent):
    """Event triggered when leader changes any settings.

    See also: `Juju | Hook | leader-settings-changed <https://documentation.ubuntu.com/juju/3.6/reference/hook/#leader-settings-changed>`_.

    .. deprecated:: 2.4.0
        This event has been deprecated in favor of using a Peer relation,
        and having the leader set a value in the Application data bag for
        that peer relation. (See :class:`~ops.RelationChangedEvent`.)
    """


class CollectMetricsEvent(HookEvent):
    """Event triggered by Juju to collect metrics.

    Juju fires this event every five minutes for the lifetime of the
    unit. Callback methods bound to this event may use the :meth:`add_metrics`
    method of this class to send measurements to Juju.

    Note that associated callback methods are currently sandboxed in
    how they can interact with Juju.

    .. jujuremoved:: 3.6.11
    """

    def __init__(self, handle: Handle):
        warnings.warn(
            'collect-metrics events are not be emitted from Juju 3.6.11 onwards - '
            'consider using the Canonical Observability Stack',
            DeprecationWarning,
            stacklevel=3,
        )
        super().__init__(handle)

    def add_metrics(
        self, metrics: Mapping[str, int | float], labels: Mapping[str, str] | None = None
    ):
        """Record metrics that have been gathered by the charm for this unit.

        Args:
            metrics: Key-value mapping of metrics that have been gathered.
            labels: Key-value labels applied to the metrics.

        Raises:
            ModelError: if invalid keys or values are provided.
        """
        self.framework.model._backend.add_metrics(metrics, labels)


class RelationEvent(HookEvent):
    """A base class representing the various relation lifecycle events.

    Relation lifecycle events are generated when application units
    participate in relations.  Units can only participate in relations
    after they have been "started", and before they have been
    "stopped". Within that time window, the unit may participate in
    several different relations at a time, including multiple
    relations with the same name.
    """

    relation: model.Relation
    """The relation involved in this event."""

    app: model.Application
    """The remote application that has triggered this event."""

    unit: model.Unit | None
    """The remote unit that has triggered this event.

    This will be ``None`` if the relation event was triggered as an
    :class:`Application <model.Application>`-level event.
    """

    def __init__(
        self,
        handle: Handle,
        relation: model.Relation,
        app: model.Application | None = None,
        unit: model.Unit | None = None,
    ):
        super().__init__(handle)

        if unit is not None and unit.app != app:
            raise RuntimeError(
                f'cannot create RelationEvent with application {app} and unit {unit}'
            )

        self.relation = relation
        if app is None:
            logger.warning(
                "'app' expected but not received, see https://bugs.launchpad.net/juju/+bug/1960934"
            )
            # Do an explicit assignment here so that we can contain the type: ignore.
            self.app = None  # type: ignore
        else:
            self.app = app
        self.unit = unit

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        snapshot: dict[str, Any] = {
            'relation_name': self.relation.name,
            'relation_id': self.relation.id,
        }
        if self.app:
            snapshot['app_name'] = self.app.name
        if self.unit:
            snapshot['unit_name'] = self.unit.name
        return snapshot

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        relation = self.framework.model.get_relation(
            snapshot['relation_name'], snapshot['relation_id']
        )
        if relation is None:
            raise ValueError(
                'Unable to restore {}: relation {} (id={}) not found.'.format(
                    self, snapshot['relation_name'], snapshot['relation_id']
                )
            )
        self.relation = relation

        app_name = snapshot.get('app_name')
        if app_name:
            self.app = self.framework.model.get_app(app_name)
        else:
            logger.warning("'app_name' expected in snapshot but not found.")
            self.app = None  # type: ignore

        unit_name = snapshot.get('unit_name')
        if unit_name:
            self.unit = self.framework.model.get_unit(unit_name)
        else:
            self.unit = None

    def __repr__(self):
        app = None if self.app is None else self.app.name
        unit = None if self.unit is None else self.unit.name
        return f'<{self.__class__.__name__} {app=} {unit=} on {self.relation!r} via {self.handle}>'


class RelationCreatedEvent(RelationEvent):
    """Event triggered when a new relation is created.

    This is triggered when a new relation with another app is added in Juju. This
    can occur before units for those applications have started. All existing
    relations will trigger `RelationCreatedEvent` before :class:`~ops.StartEvent` is
    emitted.

    See also: `Juju | Hook | <endpoint>-relation-created <https://documentation.ubuntu.com/juju/3.6/reference/hook/#endpoint-relation-created>`_.
    """

    unit: None  # pyright: ignore[reportIncompatibleVariableOverride]
    """Always ``None``."""


class RelationJoinedEvent(RelationEvent):
    """Event triggered when a new unit joins a relation.

    This event is triggered whenever a new unit of an integrated
    application joins the relation.  The event fires only when that
    remote unit is first observed by the unit. Callback methods bound
    to this event may set any local unit data that can be
    determined using no more than the name of the joining unit and the
    remote ``private-address`` setting, which is always available when
    the relation is created and is by convention not deleted.

    See also: `Juju | Hook | <endpoint>-relation-joined <https://documentation.ubuntu.com/juju/3.6/reference/hook/#endpoint-relation-joined>`_.
    """

    unit: model.Unit  # pyright: ignore[reportIncompatibleVariableOverride]
    """The remote unit that has triggered this event."""


class RelationChangedEvent(RelationEvent):
    """Event triggered when relation data changes.

    This event is triggered whenever there is a change to the data bucket for an
    integrated application or unit. Look at ``event.relation.data[event.unit/app]``
    to see the new information, where ``event`` is the event object passed to
    the callback method bound to this event.

    This event always fires once, after :class:`~ops.RelationJoinedEvent`, and
    will subsequently fire whenever that remote unit changes its data for
    the relation. Callback methods bound to this event should be the only ones
    that rely on remote relation data. They should not error if the data
    is incomplete, since it can be guaranteed that when the remote unit or
    application changes its data, the event will fire again.

    The data that may be queried, or set, are determined by the relation's
    interface.

    See also: `Juju | Hook | <endpoint>-relation-changed <https://documentation.ubuntu.com/juju/3.6/reference/hook/#endpoint-relation-changed>`_.
    """


class RelationDepartedEvent(RelationEvent):
    """Event triggered when a unit leaves a relation.

    This is the inverse of the :class:`~ops.RelationJoinedEvent`, representing when a
    unit is leaving the relation (the unit is being removed, the app is being
    removed, the relation is being removed). For remaining units, this event is
    emitted once for each departing unit.  For departing units, this event is
    emitted once for each remaining unit.

    Callback methods bound to this event may be used to remove all
    references to the departing remote unit, because there's no
    guarantee that it's still part of the system; it's perfectly
    probable (although not guaranteed) that the system running that
    unit has already shut down.

    Once all callback methods bound to this event have been run for such a
    relation, the unit agent will fire the :class:`~ops.RelationBrokenEvent`.

    See also: `Juju | Hook | <endpoint>-relation-departed <https://documentation.ubuntu.com/juju/3.6/reference/hook/#endpoint-relation-departed>`_.
    """

    unit: model.Unit  # pyright: ignore[reportIncompatibleVariableOverride]
    """The remote unit that has triggered this event."""

    def __init__(
        self,
        handle: Handle,
        relation: model.Relation,
        app: model.Application | None = None,
        unit: model.Unit | None = None,
        departing_unit_name: str | None = None,
    ):
        super().__init__(handle, relation, app=app, unit=unit)

        self._departing_unit_name = departing_unit_name

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        snapshot = super().snapshot()
        if self._departing_unit_name:
            snapshot['departing_unit'] = self._departing_unit_name
        return snapshot

    @property
    def departing_unit(self) -> model.Unit | None:
        """The :class:`ops.Unit` that is departing, if any.

        Use this method to determine (for example) whether this unit is the
        departing one.
        """
        # doing this on init would fail because `framework` gets patched in
        # post-init
        if not self._departing_unit_name:
            return None
        return self.framework.model.get_unit(self._departing_unit_name)

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        super().restore(snapshot)
        self._departing_unit_name = snapshot.get('departing_unit')


class RelationBrokenEvent(RelationEvent):
    """Event triggered when a relation is removed.

    If a relation is being removed (``juju remove-relation`` or ``juju
    remove-application``), once all the units have been removed, this event will
    fire to signal that the relationship has been fully terminated.

    The event indicates that the current relation is no longer valid, and that
    the charm's software must be configured as though the relation had never
    existed. It will only be called after every callback method bound to
    :class:`~ops.RelationDepartedEvent` has been run. If a callback method
    bound to this event is being executed, it is guaranteed that no remote units
    are currently known locally.

    See also: `Juju | Hook | <endpoint>-relation-broken <https://documentation.ubuntu.com/juju/3.6/reference/hook/#endpoint-relation-broken>`_.
    """

    unit: None  # pyright: ignore[reportIncompatibleVariableOverride]
    """Always ``None``."""


class StorageEvent(HookEvent):
    """Base class representing events to do with storage.

    Juju can provide a variety of storage types to a charms. The
    charms can define several different types of storage that are
    allocated from Juju. Changes in state of storage trigger sub-types
    of :class:`StorageEvent`.
    """

    storage: model.Storage
    """Storage instance this event refers to."""

    def __init__(self, handle: Handle, storage: model.Storage):
        super().__init__(handle)
        self.storage = storage

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        snapshot: dict[str, Any] = {}
        if isinstance(self.storage, model.Storage):
            snapshot['storage_name'] = self.storage.name
            snapshot['storage_index'] = self.storage.index
            snapshot['storage_location'] = str(self.storage.location)
        return snapshot

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        storage_name = snapshot.get('storage_name')
        storage_index = snapshot.get('storage_index')
        storage_location = snapshot.get('storage_location')

        if storage_name and storage_index is not None:
            storages = self.framework.model.storages[storage_name]
            self.storage = next((s for s in storages if s.index == storage_index), None)  # type: ignore
            if self.storage is None:
                raise RuntimeError(
                    f'failed loading storage (name={storage_name!r}, '
                    f'index={storage_index!r}) from snapshot'
                )
            if storage_location is None:
                raise RuntimeError(
                    'failed loading storage location from snapshot.'
                    f'(name={storage_name!r}, index={storage_index!r}, storage_location=None)'
                )

            self.storage.location = storage_location

    def __repr__(self):
        return f'<{self.__class__.__name__} on {self.storage!r} via {self.handle}>'


class StorageAttachedEvent(StorageEvent):
    """Event triggered when new storage becomes available.

    This event is triggered when new storage is available for the
    charm to use.

    Callback methods bound to this event allow the charm to run code
    when storage has been added. Such methods will be run before the
    :class:`~ops.InstallEvent` fires, so that the installation routine may
    use the storage. The name prefix of this hook will depend on the
    storage key defined in the ``metadata.yaml`` file.

    See also: `Juju | Hook | <storage>-storage-attached <https://documentation.ubuntu.com/juju/3.6/reference/hook/#storage-storage-attached>`_.
    """


class StorageDetachingEvent(StorageEvent):
    """Event triggered prior to removal of storage.

    This event is triggered when storage a charm has been using is
    going away.

    Callback methods bound to this event allow the charm to run code
    before storage is removed. Such methods will be run before storage
    is detached, and always before the :class:`~ops.StopEvent` fires, thereby
    allowing the charm to gracefully release resources before they are
    removed and before the unit terminates. The name prefix of the
    hook will depend on the storage key defined in the ``metadata.yaml``
    file.

    See also: `Juju | Hook | <storage>-storage-detaching <https://documentation.ubuntu.com/juju/3.6/reference/hook/#storage-storage-detaching>`_.
    """


class WorkloadEvent(HookEvent):
    """Base class representing events to do with the workload.

    Workload events are generated for all containers that the charm
    expects in metadata.
    """

    workload: model.Container
    """The workload involved in this event.

    Workload currently only can be a :class:`Container <model.Container>`, but
    in future may be other types that represent the specific workload type,
    for example a machine.
    """

    def __init__(self, handle: Handle, workload: model.Container):
        super().__init__(handle)

        self.workload = workload

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        snapshot: dict[str, Any] = {}
        if isinstance(self.workload, model.Container):
            snapshot['container_name'] = self.workload.name
        return snapshot

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        container_name = snapshot.get('container_name')
        if container_name:
            self.workload = self.framework.model.unit.get_container(container_name)
        else:
            self.workload = None  # type: ignore

    def __repr__(self):
        return f'<{self.__class__.__name__} on {self.workload!r} via {self.handle}>'


class PebbleReadyEvent(WorkloadEvent):
    """Event triggered when Pebble is ready for a workload.

    This event is triggered when the Pebble process for a workload/container
    starts up, allowing the charm to configure how services should be launched.

    Callback methods bound to this event allow the charm to run code after
    a workload has started its Pebble instance and is ready to receive instructions
    regarding what services should be started. The name prefix of the hook
    will depend on the container key defined in the ``metadata.yaml`` file.

    See also: `Juju | Hook | <container>-pebble-ready <https://documentation.ubuntu.com/juju/3.6/reference/hook/#container-pebble-ready>`_.
    """


class PebbleNoticeEvent(WorkloadEvent):
    """Base class for Pebble notice events (each notice type is a subclass)."""

    notice: model.LazyNotice
    """Provide access to the event notice's details."""

    def __init__(
        self,
        handle: Handle,
        workload: model.Container,
        notice_id: str,
        notice_type: str,
        notice_key: str,
    ):
        super().__init__(handle, workload)
        self.notice = model.LazyNotice(workload, notice_id, notice_type, notice_key)

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        d = super().snapshot()
        d['notice_id'] = self.notice.id
        d['notice_type'] = (
            self.notice.type if isinstance(self.notice.type, str) else self.notice.type.value
        )
        d['notice_key'] = self.notice.key
        return d

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        super().restore(snapshot)
        notice_id = snapshot.pop('notice_id')
        notice_type = snapshot.pop('notice_type')
        notice_key = snapshot.pop('notice_key')
        self.notice = model.LazyNotice(self.workload, notice_id, notice_type, notice_key)


class PebbleCustomNoticeEvent(PebbleNoticeEvent):
    """Event triggered when a Pebble notice of type "custom" is created or repeats.

    See also: `Juju | Hook | <container>-pebble-notice-custom <https://documentation.ubuntu.com/juju/3.6/reference/hook/#container-pebble-custom-notice>`_.

    .. jujuadded:: 3.4
    """


class PebbleCheckEvent(WorkloadEvent):
    """Base class for Pebble check events."""

    info: model.LazyCheckInfo
    """Provide access to the check's current state."""

    def __init__(
        self,
        handle: Handle,
        workload: model.Container,
        check_name: str,
    ):
        super().__init__(handle, workload)
        self.info = model.LazyCheckInfo(workload, check_name)

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        d = super().snapshot()
        d['check_name'] = self.info.name
        return d

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        check_name = snapshot.pop('check_name')
        super().restore(snapshot)
        self.info = model.LazyCheckInfo(self.workload, check_name)


class PebbleCheckFailedEvent(PebbleCheckEvent):
    """Event triggered when a Pebble check exceeds the configured failure threshold.

    Note that the check may have started passing by the time this event is
    emitted (which will mean that a :class:`~ops.PebbleCheckRecoveredEvent` will be
    emitted next). If the handler is executing code that should only be done
    if the check is currently failing, check the current status with
    ``event.info.status == ops.pebble.CheckStatus.DOWN``.

    See also: `Juju | Hook | <container>-pebble-check-failed <https://documentation.ubuntu.com/juju/3.6/reference/hook/#container-pebble-check-failed>`_.

    .. jujuadded:: 3.6
    """


class PebbleCheckRecoveredEvent(PebbleCheckEvent):
    """Event triggered when a Pebble check recovers.

    This event is only triggered when the check has previously reached a failure
    state (not simply failed, but failed at least as many times as the
    configured threshold).

    See also: `Juju | Hook | <container>-pebble-check-recovered <https://documentation.ubuntu.com/juju/3.6/reference/hook/#container-pebble-check-recovered>`_.

    .. jujuadded:: 3.6
    """


class SecretEvent(HookEvent):
    """Base class for all secret events."""

    def __init__(self, handle: Handle, id: str, label: str | None):
        super().__init__(handle)
        self._id = id
        self._label = label

    @property
    def secret(self) -> model.Secret:
        """The secret instance this event refers to.

        Note that the secret content is not retrieved from the secret storage
        until :meth:`Secret.get_content()` is called.
        """
        backend = self.framework.model._backend
        return model.Secret(
            backend=backend,
            id=self._id,
            label=self._label,
        )

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        return {'id': self._id, 'label': self._label}

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        self._id = cast('str', snapshot['id'])
        self._label = cast('str | None', snapshot['label'])


class SecretChangedEvent(SecretEvent):
    """Event triggered on the secret observer charm when the secret owner changes its contents.

    When the owner of a secret changes the secret's contents, Juju will create
    a new secret revision, and all applications or units that are tracking this
    secret will be notified via this event that a new revision is available.

    Typically, the charm will fetch the new content by calling
    :meth:`event.secret.get_content() <ops.Secret.get_content>` with ``refresh=True``
    to tell Juju to start tracking the new revision.

    See also: `Juju | Hook | secret-changed <https://documentation.ubuntu.com/juju/3.6/reference/hook/#secret-changed>`_.

    .. jujuadded:: 3.0
        Charm secrets added in Juju 3.0, user secrets added in Juju 3.3
    """


class SecretRotateEvent(SecretEvent):
    """Event triggered on the secret owner charm when the secret's rotation policy elapses.

    This event is fired on the secret owner to inform it that the secret must
    be rotated. The event will keep firing until the owner creates a new
    revision by calling :meth:`event.secret.set_content() <ops.Secret.set_content>`.

    See also: `Juju | Hook | secret-rotate <https://documentation.ubuntu.com/juju/3.6/reference/hook/#secret-rotate>`_.

    .. jujuadded:: 3.0
    """

    def defer(self) -> NoReturn:
        """Secret rotation events are not deferrable (Juju handles re-invocation).

        Raises:
            RuntimeError: always.
        """
        raise RuntimeError(
            'Cannot defer secret rotation events. Juju will keep firing this '
            'event until you create a new revision.'
        )


class SecretRemoveEvent(SecretEvent):
    """Event triggered on the secret owner charm when a secret revision can be removed.

    When the owner of a secret creates a new revision, and after all
    observers have updated to that new revision, this event will be fired to
    inform the secret owner that the old revision can be removed.

    After any required cleanup, the charm should call
    :meth:`event.remove_revision() <ops.SecretRemoveEvent.remove_revision>` to
    remove the now-unused revision. If the charm does not, then the event will
    be emitted again, when further revisions are ready for removal.

    See also: `Juju | Hook | secret-remove <https://documentation.ubuntu.com/juju/3.6/reference/hook/#secret-remove>`_.

    .. jujuadded:: 3.0
    """

    def __init__(self, handle: Handle, id: str, label: str | None, revision: int):
        super().__init__(handle, id, label)
        self._revision = revision

    @property
    def revision(self) -> int:
        """The secret revision this event refers to."""
        return self._revision

    def remove_revision(self):
        """Remove the revision this event refers to.

        Call this method after any required cleanup to inform Juju that the
        secret revision can be removed.
        """
        self.secret.remove_revision(self._revision)

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        data = super().snapshot()
        data['revision'] = self._revision
        return data

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        super().restore(snapshot)
        self._revision = cast('int', snapshot['revision'])


class SecretExpiredEvent(SecretEvent):
    """Event triggered on the secret owner charm when a secret's expiration time elapses.

    This event is fired on the secret owner to inform it that the secret revision
    must be removed. The event will keep firing until the owner removes the
    revision by calling :meth:`event.remove_revision()
    <ops.SecretExpiredEvent.remove_revision>`.

    See also: `Juju | Hook | secret-expired <https://documentation.ubuntu.com/juju/3.6/reference/hook/#secret-expired>`_.

    .. jujuadded:: 3.0
    """

    def __init__(self, handle: Handle, id: str, label: str | None, revision: int):
        super().__init__(handle, id, label)
        self._revision = revision

    @property
    def revision(self) -> int:
        """The secret revision this event refers to."""
        return self._revision

    def remove_revision(self):
        """Remove the revision this event refers to.

        Call this method after any required cleanup to inform Juju that the
        secret revision can be removed.
        """
        self.secret.remove_revision(self._revision)

    def snapshot(self) -> dict[str, Any]:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        data = super().snapshot()
        data['revision'] = self._revision
        return data

    def restore(self, snapshot: dict[str, Any]):
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        super().restore(snapshot)
        self._revision = cast('int', snapshot['revision'])

    def defer(self) -> NoReturn:
        """Secret expiration events are not deferrable (Juju handles re-invocation).

        Raises:
            RuntimeError: always.
        """
        raise RuntimeError(
            'Cannot defer secret expiration events. Juju will keep firing '
            'this event until you create a new revision.'
        )


class CollectStatusEvent(LifecycleEvent):
    """Event triggered at the end of every hook to collect statuses for evaluation.

    If the charm wants to provide application or unit status in a consistent
    way after the end of every hook, it should observe the
    :attr:`collect_app_status <CharmEvents.collect_app_status>` or
    :attr:`collect_unit_status <CharmEvents.collect_unit_status>` event,
    respectively.

    The framework will trigger these events after the hook code runs
    successfully (``collect_app_status`` will only be triggered on the leader
    unit). This happens on every Juju event, whether it was
    :meth:`observed <ops.Framework.observe>` or not.
    If any statuses were added by the event handler using
    :meth:`add_status`, the framework will choose the highest-priority status
    and set that as the status (application status for ``collect_app_status``,
    or unit status for ``collect_unit_status``).

    The order of priorities is as follows, from highest to lowest:

    * blocked
    * maintenance
    * waiting
    * active

    It is an error to call :meth:`add_status` with an instance of
    :class:`ErrorStatus` or :class:`UnknownStatus`.

    If there are multiple statuses with the same priority, the first one added
    wins (and if an event is observed multiple times, the handlers are called
    in the order they were observed).

    A collect-status event can be observed multiple times, and
    :meth:`add_status` can be called multiple times to add multiple statuses
    for evaluation. This is useful when a charm has multiple components that
    each have a status. Each code path in a collect-status handler should
    call ``add_status`` at least once.

    Below is an example "web app" charm component that observes
    ``collect_unit_status`` to provide the status of the component, which
    requires a "port" config option set before it can proceed::

        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                self.webapp = Webapp(self)
                # initialize other components

        class WebApp(ops.Object):
            def __init__(self, charm: ops.CharmBase):
                super().__init__(charm, 'webapp')
                self.framework.observe(charm.on.collect_unit_status, self._on_collect_status)

            def _on_collect_status(self, event: ops.CollectStatusEvent):
                if 'port' not in self.model.config:
                    event.add_status(ops.BlockedStatus('please set "port" config'))
                    return
                event.add_status(ops.ActiveStatus())
    """  # noqa: D405, D214, D411, D416  Final return confuses docstyle.

    def add_status(self, status: model.StatusBase):
        """Add a status for evaluation.

        See :class:`CollectStatusEvent` for a description of how to use this.
        """
        if not isinstance(status, model.StatusBase):
            raise TypeError(f'status should be a StatusBase, not {type(status).__name__}')
        if status.name not in model._SETTABLE_STATUS_NAMES:
            raise model.InvalidStatusError(
                f'status.name must be in {model._SETTABLE_STATUS_NAMES}, not {status.name!r}'
            )
        model_ = self.framework.model
        if self.handle.kind == 'collect_app_status':
            if not isinstance(status, model.ActiveStatus):
                logger.debug('Adding app status %s', status, stacklevel=2)
            model_.app._collected_statuses.append(status)
        else:
            if not isinstance(status, model.ActiveStatus):
                logger.debug('Adding unit status %s', status, stacklevel=2)
            model_.unit._collected_statuses.append(status)


class CharmEvents(ObjectEvents):
    """Events generated by Juju pertaining to application lifecycle.

    By default, the events listed as attributes of this class will be
    provided via the :attr:`CharmBase.on` attribute. For example::

        framework.observe(self.on.config_changed, self._on_config_changed)

    In addition to the events listed as attributes of this class,
    dynamically-named events will also be defined based on the charm's
    metadata (``metadata.yaml``) for relations, storage, actions, and
    containers. These named events may be accessed as
    ``self.on[<name>].<event>`` or using a prefix like
    ``self.on.<name>_<event>``, for example::

        framework.observe(self.on["db"].relation_created, self._on_db_relation_created)
        framework.observe(self.on.workload_pebble_ready, self._on_workload_pebble_ready)
    """

    # NOTE: The one-line docstrings below are copied from the first line of
    #       each event class's docstring. Please keep in sync.

    install = EventSource(InstallEvent)
    """Triggered when a charm is installed (see :class:`~ops.InstallEvent`)."""

    start = EventSource(StartEvent)
    """Triggered immediately after first configuration change (see :class:`~ops.StartEvent`)."""

    stop = EventSource(StopEvent)
    """Triggered when a charm is shut down (see :class:`~ops.StopEvent`)."""

    remove = EventSource(RemoveEvent)
    """Triggered when a unit is about to be terminated (see :class:`~ops.RemoveEvent`)."""

    update_status = EventSource(UpdateStatusEvent)
    """Triggered periodically by a status update request from Juju (see
    :class:`~ops.UpdateStatusEvent`).
    """

    config_changed = EventSource(ConfigChangedEvent)
    """Triggered when a configuration change occurs (see :class:`~ops.ConfigChangedEvent`)."""

    upgrade_charm = EventSource(UpgradeCharmEvent)
    """Triggered by request to upgrade the charm (see :class:`~ops.UpgradeCharmEvent`)."""

    pre_series_upgrade = EventSource(PreSeriesUpgradeEvent)
    """Triggered to prepare a unit for series upgrade (see :class:`~ops.PreSeriesUpgradeEvent`).

    .. jujuremoved:: 4.0
    """

    post_series_upgrade = EventSource(PostSeriesUpgradeEvent)
    """Triggered after a series upgrade (see :class:`~ops.PostSeriesUpgradeEvent`).

    .. jujuremoved:: 4.0
    """

    leader_elected = EventSource(LeaderElectedEvent)
    """Triggered when a new leader has been elected (see :class:`~ops.LeaderElectedEvent`)."""

    leader_settings_changed = EventSource(LeaderSettingsChangedEvent)
    """Triggered when leader changes any settings (see
    :class:`~ops.LeaderSettingsChangedEvent`).

    .. deprecated:: 2.4.0
    """

    collect_metrics = EventSource(CollectMetricsEvent)
    """Triggered by Juju to collect metrics (see :class:`~ops.CollectMetricsEvent`).

    .. jujuremoved:: 3.6.11
    """

    secret_changed = EventSource(SecretChangedEvent)
    """Triggered by Juju on the observer when the secret owner changes its contents (see
    :class:`~ops.SecretChangedEvent`).

    .. jujuadded:: 3.0
        Charm secrets added in Juju 3.0, user secrets added in Juju 3.3
    """

    secret_expired = EventSource(SecretExpiredEvent)
    """Triggered by Juju on the owner when a secret's expiration time elapses (see
    :class:`~ops.SecretExpiredEvent`).

    .. jujuadded:: 3.0
    """

    secret_rotate = EventSource(SecretRotateEvent)
    """Triggered by Juju on the owner when the secret's rotation policy elapses (see
    :class:`~ops.SecretRotateEvent`).

    .. jujuadded:: 3.0
    """

    secret_remove = EventSource(SecretRemoveEvent)
    """Triggered by Juju on the owner when a secret revision can be removed (see
    :class:`~ops.SecretRemoveEvent`).

    .. jujuadded:: 3.0
    """

    collect_app_status = EventSource(CollectStatusEvent)
    """Triggered on the leader at the end of every hook to collect app statuses for evaluation
    (see :class:`~ops.CollectStatusEvent`).
    """

    collect_unit_status = EventSource(CollectStatusEvent)
    """Triggered at the end of every hook to collect unit statuses for evaluation
    (see :class:`~ops.CollectStatusEvent`).
    """


_T = TypeVar('_T')


class CharmBase(Object):
    """Base class that represents the charm overall.

    :code:`CharmBase` is used to create a charm. This is done by inheriting
    from :code:`CharmBase` and customising the subclass as required. So to
    create a charm called ``MyCharm``, define a charm class and set up the
    required event handlers (“hooks”) in its constructor::

        import logging

        import ops

        class MyCharm(ops.CharmBase):
            def __init__(self, framework: ops.Framework):
                super().__init__(framework)
                framework.observe(self.on.config_changed, self._on_config_changed)
                framework.observe(self.on.stop, self._on_stop)
                # ...

        if __name__ == "__main__":
            ops.main(MyCharm)

    As shown in the example above, a charm class is instantiated by
    :code:`ops.main` rather than charm authors directly instantiating a
    charm.

    Args:
        framework: The framework responsible for managing the Model and events for this
            charm.
    """

    on: CharmEvents = CharmEvents()  # type: ignore
    """This property is used to create an event handler using :meth:`Framework.observe`,
    and can be one of the events listed at :class:`CharmEvents`.
    """

    if TYPE_CHECKING:
        # to help the type checker and IDEs:
        @property
        def on(self) -> CharmEvents: ...  # noqa

    def __init__(self, framework: Framework):
        super().__init__(framework, None)

        for relation_name in self.framework.meta.relations:
            relation_name = relation_name.replace('-', '_')
            self.on.define_event(f'{relation_name}_relation_created', RelationCreatedEvent)
            self.on.define_event(f'{relation_name}_relation_joined', RelationJoinedEvent)
            self.on.define_event(f'{relation_name}_relation_changed', RelationChangedEvent)
            self.on.define_event(f'{relation_name}_relation_departed', RelationDepartedEvent)
            self.on.define_event(f'{relation_name}_relation_broken', RelationBrokenEvent)

        for storage_name in self.framework.meta.storages:
            storage_name = storage_name.replace('-', '_')
            self.on.define_event(f'{storage_name}_storage_attached', StorageAttachedEvent)
            self.on.define_event(f'{storage_name}_storage_detaching', StorageDetachingEvent)

        for action_name in self.framework.meta.actions:
            action_name = action_name.replace('-', '_')
            self.on.define_event(f'{action_name}_action', ActionEvent)

        for container_name in self.framework.meta.containers:
            container_name = container_name.replace('-', '_')
            self.on.define_event(f'{container_name}_pebble_ready', PebbleReadyEvent)
            self.on.define_event(f'{container_name}_pebble_custom_notice', PebbleCustomNoticeEvent)
            self.on.define_event(f'{container_name}_pebble_check_failed', PebbleCheckFailedEvent)
            self.on.define_event(
                f'{container_name}_pebble_check_recovered', PebbleCheckRecoveredEvent
            )

    @property
    def app(self) -> model.Application:
        """The application that this unit is part of."""
        return self.framework.model.app

    @property
    def unit(self) -> model.Unit:
        """The current unit."""
        return self.framework.model.unit

    @property
    def meta(self) -> CharmMeta:
        """Metadata of this charm."""
        return self.framework.meta

    @property
    def charm_dir(self) -> pathlib.Path:
        """Root directory of the charm as it is running."""
        return self.framework.charm_dir

    @property
    def config(self) -> model.ConfigData:
        """A mapping containing the charm's config and current values."""
        return self.model.config

    def load_config(
        self,
        cls: type[_T],
        *args: Any,
        errors: Literal['raise', 'blocked'] = 'raise',
        **kwargs: Any,
    ) -> _T:
        """Load the config into an instance of a config class.

        The raw Juju config is passed to the config class's ``__init__``, as
        keyword arguments, with the following changes:

        * ``secret`` type options have a :class:`model.Secret` value rather
          than the secret ID. Note that the secret object is not validated by
          Juju at this time, so may raise :class:`SecretNotFoundError` when it
          is used later (if the secret does not exist or the unit does not have
          permission to access it).
        * dashes in names are converted to underscores.

        For dataclasses and Pydantic ``BaseModel`` subclasses, only fields in
        the Juju config that have a matching field in the class are passed as
        arguments. Pydantic fields that have an ``alias``, or dataclasses that
        have a ``metadata{'alias'=}``, will have the alias applied when loading.

        For example::

            class Config(pydantic.BaseModel):
                # This field is called 'class' in the Juju config options.
                workload_class: str = pydantic.Field(alias='class')

            def _on_config_changed(self, event: ops.ConfigChangedEvent):
                data = self.load_config(Config, errors='blocked')
                # `data.workload_class` has the value of the Juju option `class`

        Pydantic classes that have fields that are not simple or
        Pydantic types, such as :class:`ops.Secret`, require setting
        ``arbitrary_types_allowed`` in the Pydantic model config.

        Any additional positional or keyword arguments to this method will be
        passed through to the config class ``__init__``.

        Args:
            cls: A class that will accept the Juju options as keyword arguments,
                and raise ``ValueError`` if validation fails.
            errors: what to do if the config is invalid. If ``blocked``, this
                will set the unit status to blocked with an appropriate message
                and then exit successfully (this informs Juju that
                the event was handled and it will not be retried).
                If ``raise``, ``load_config``
                will not catch any exceptions, leaving the charm to handle
                errors.
            args: positional arguments to pass through to the config class.
            kwargs: keyword arguments to pass through to the config class.

        Returns:
            An instance of the config class that was passed in the ``cls`` argument
            with the current config values.

        Raises:
            ValueError: if the configuration is invalid and ``errors`` is set to
                ``raise``.
        """
        from ._main import _Abort

        config: dict[str, bool | int | float | str | model.Secret] = kwargs.copy()
        try:
            fields = set(_juju_fields(cls))
        except ValueError:
            fields = None
        for key, value in self.config.items():
            attr = key.replace('-', '_')
            if fields is not None and attr not in fields:
                continue
            option_type = self.meta.config.get(key)
            # Convert secret IDs to secret objects. We create the object rather
            # that using model.get_secret so that it's entirely lazy, in the
            # same way that SecretEvent.secret is.
            if option_type and option_type.type == 'secret':
                assert isinstance(value, str)  # Juju will have made sure of this.
                value = model.Secret(
                    backend=self.model._backend,
                    id=value,
                )
            config[attr] = value
        try:
            return cls(*args, **config)
        except ValueError as e:
            if errors == 'raise':
                raise
            # We exit with a zero code because we don't want Juju to retry
            # (the config needs to be fixed by the Juju user), and we don't
            # want the status we just set to be overridden by an error
            # status.
            self.unit.status = model.BlockedStatus(f'Invalid config: {e}')
            raise _Abort(0) from e


def _evaluate_status(charm: CharmBase):  # pyright: ignore[reportUnusedFunction]
    """Trigger collect-status events and evaluate and set the highest-priority status.

    See :class:`CollectStatusEvent` for details.
    """
    if charm.framework.model._backend.is_leader():
        charm.on.collect_app_status.emit()
        app = charm.app
        if app._collected_statuses:
            app.status = model.StatusBase._get_highest_priority(app._collected_statuses)

    charm.on.collect_unit_status.emit()
    unit = charm.unit
    if unit._collected_statuses:
        unit.status = model.StatusBase._get_highest_priority(unit._collected_statuses)


def _juju_fields(cls: type[object]) -> dict[str, str]:
    """Iterates over all the field names to include when loading into a class.

    Any Juju names that are not in the returned dictionary should not be passed
    to the class. Names that are in the dictionary are mapped to the argument
    name; in most cases this is the same string, but for aliases will differ.

    Returns:
        A dictionary where the key is the Juju name and the value is the name of
        the attribute in the Python class.

    Raises:
        ValueError: if unable to determine which fields to include
    """
    # Dataclasses:
    juju_to_arg: dict[str, str] = {}
    if dataclasses.is_dataclass(cls):
        for field in dataclasses.fields(cls):
            alias = field.metadata.get('alias', field.name)
            # If this a Pydantic dataclass, then it handles the alias.
            # Using pydantic.dataclasses.is_pydantic_dataclass() would be
            # best here, but we don't want to import pydantic in ops, so
            # we look more explicitly.
            if getattr(cls, '__is_pydantic_dataclass__', False):
                juju_to_arg[alias] = alias
            else:
                juju_to_arg[alias] = field.name
        return juju_to_arg
    # Pydantic models:
    class_fields: dict[str, str] = {}
    if hasattr(cls, 'model_fields'):
        for name, field in cls.model_fields.items():  # type: ignore
            # Pydantic takes care of the alias.
            class_fields[field.alias or name] = field.alias or name  # type: ignore
        return class_fields
    # It's not clear, so give up.
    raise ValueError('Unable to find class fields')


class CharmMeta:
    """Object containing the metadata for the charm.

    This is read from ``metadata.yaml``, ``config.yaml``, and ``actions.yaml``.
    Generally charms will define this information, rather than reading it at
    runtime. This class is mostly for the framework to understand what the charm
    has defined.

    Args:
        raw: a mapping containing the contents of metadata.yaml
        actions_raw: a mapping containing the contents of actions.yaml
        config_raw: a mapping containing the contents of config.yaml
    """

    name: str
    """Name of this charm."""

    summary: str
    """Short description of what this charm does."""

    description: str
    """Long description for this charm."""

    maintainers: list[str]
    """List of email addresses of charm maintainers."""

    links: MetadataLinks
    """Links to more details about the charm."""

    tags: list[str]
    """Charmhub tag metadata for categories associated with this charm."""

    terms: list[str]
    """Charmhub terms that should be agreed to before this charm can be deployed."""

    series: list[str]
    """List of supported OS series that this charm can support.

    The first entry in the list is the default series that will be used by
    deploy if no other series is requested by the user.
    """

    subordinate: bool
    """Whether this charm is intended to be used as a subordinate charm."""

    min_juju_version: str | None
    """Indicates the minimum Juju version this charm requires."""

    assumes: JujuAssumes
    """Juju features this charm requires."""

    charm_user: Literal['root', 'sudoer', 'non-root']
    """Type of user used to run the charm hook code.

    The value of ``root`` ensures the charm runs as root. The value of
    ``sudoer`` runs the charm as a user other than root with access to sudo to
    elevate its privileges. ``non-root`` ensures the charm does not run as root
    and also does not have ``sudo`` privileges.

    .. jujuadded 3.6.0
    """

    containers: dict[str, ContainerMeta]
    """Container metadata for each defined container."""

    requires: dict[str, RelationMeta]
    """Relations this charm requires."""

    provides: dict[str, RelationMeta]
    """Relations this charm provides."""

    peers: dict[str, RelationMeta]
    """Peer relations."""

    relations: dict[str, RelationMeta]
    """All :class:`RelationMeta` instances.

    This is merged from ``requires``, ``provides``, and ``peers``. If needed,
    the role of the relation definition can be obtained from its
    :attr:`role <RelationMeta.role>` attribute.
    """

    storages: dict[str, StorageMeta]
    """Storage metadata for each defined storage."""

    resources: dict[str, ResourceMeta]
    """Resource metadata for each defined resource."""

    payloads: dict[str, PayloadMeta]
    """Payload metadata for each defined payload."""

    extra_bindings: dict[str, None]
    """Additional named bindings that a charm can use for network configuration."""

    actions: dict[str, ActionMeta]
    """Actions the charm has defined."""

    config: dict[str, ConfigMeta]
    """Config options the charm has defined."""

    def __init__(
        self,
        raw: dict[str, Any] | None = None,
        actions_raw: dict[str, Any] | None = None,
        config_raw: dict[str, Any] | None = None,
    ):
        raw_: dict[str, Any] = raw or {}
        actions_raw_: dict[str, Any] = actions_raw or {}
        # config_raw might be {'options': None} - this is accepted by
        # charmcraft, even though {'options: {}} would be more correct.
        options_raw: dict[str, Any] = (config_raw or {}).get('options') or {}

        # When running in production, this data is generally loaded from
        # metadata.yaml. However, when running tests, this data is
        # potentially loaded from charmcraft.yaml (which will be split out
        # into a metadata.yaml as part of packing). Most of the field names
        # are the same, but there are some differences that we handle here,
        # and in _load_links(), so that loading from either file works.
        self.name = raw_.get('name', '')
        self.summary = raw_.get('summary', '')
        self.description = raw_.get('description', '')
        # The metadata spec says that these should be display-name <email>
        # (roughly 'name-addr' from RFC 5322). However, many charms have only
        # an email, or have a URL, or something else, so we leave these as
        # a plain string.
        self.maintainers: list[str] = []
        # Note that metadata v2 only defines 'maintainers' not 'maintainer'.
        if 'maintainer' in raw_:
            self.maintainers.append(raw_['maintainer'])
        if 'maintainers' in raw_:
            self.maintainers.extend(raw_['maintainers'])
        if 'links' in raw_ and 'contact' in raw_['links']:
            self.maintainers.append(raw_['links']['contact'])
        self._load_links(raw_)
        # Note that metadata v2 does not define tags.
        self.tags = raw_.get('tags', [])
        self.terms = raw_.get('terms', [])
        # Note that metadata v2 does not define series.
        self.series = raw_.get('series', [])
        self.subordinate = raw_.get('subordinate', False)
        self.assumes = JujuAssumes.from_list(raw_.get('assumes', []))
        # Note that metadata v2 does not define min-juju-version ('assumes'
        # should be used instead).
        self.min_juju_version = raw_.get('min-juju-version')
        self.charm_user = raw_.get('charm-user', 'root')
        self.requires = {
            name: RelationMeta(RelationRole.requires, name, rel)
            for name, rel in raw_.get('requires', {}).items()
        }
        self.provides = {
            name: RelationMeta(RelationRole.provides, name, rel)
            for name, rel in raw_.get('provides', {}).items()
        }
        self.peers = {
            name: RelationMeta(RelationRole.peer, name, rel)
            for name, rel in raw_.get('peers', {}).items()
        }
        self.relations: dict[str, RelationMeta] = {}
        self.relations.update(self.requires)
        self.relations.update(self.provides)
        self.relations.update(self.peers)
        self.storages = {
            name: StorageMeta(name, storage) for name, storage in raw_.get('storage', {}).items()
        }
        self.resources = {
            name: ResourceMeta(name, res) for name, res in raw_.get('resources', {}).items()
        }
        self.payloads = {
            name: PayloadMeta(name, payload) for name, payload in raw_.get('payloads', {}).items()
        }
        self.extra_bindings = raw_.get('extra-bindings', {})
        self.actions = {name: ActionMeta(name, action) for name, action in actions_raw_.items()}
        # This is predominately for backwards compatibility with Harness. In a
        # real Juju environment this shouldn't be possible, because charmcraft
        # validates the config when packing.
        for name, config in options_raw.items():
            if 'type' not in config:
                raise RuntimeError(
                    f'Incorrectly formatted config in YAML, option {name} is '
                    f'expected to declare a `type`.'
                )
        self.config = {
            name: ConfigMeta(
                name,
                type=config['type'],
                default=config.get('default'),
                description=config.get('description'),
            )
            for name, config in options_raw.items()
        }
        self.containers = {
            name: ContainerMeta(name, container)
            for name, container in raw_.get('containers', {}).items()
        }

    @staticmethod
    def from_charm_root(charm_root: pathlib.Path | str):
        """Initialise CharmMeta from the path to a charm repository root folder."""
        charm_root = pathlib.Path(charm_root)
        metadata_path = charm_root / 'metadata.yaml'

        with metadata_path.open() as f:
            meta = yaml.safe_load(f.read())

        actions = None
        actions_path = charm_root / 'actions.yaml'
        if actions_path.exists():
            with actions_path.open() as f:
                actions = yaml.safe_load(f.read())

        options = None
        config_path = charm_root / 'config.yaml'
        if config_path.exists():
            with config_path.open() as f:
                options = yaml.safe_load(f.read())

        return CharmMeta(meta, actions, options)

    def _load_links(self, raw: dict[str, Any]):
        websites = raw.get('website', [])
        if not websites and 'links' in raw:
            websites = raw['links'].get('website', [])
        # In YAML, this can be a single string, or a list of strings.
        if isinstance(websites, str):
            websites = [websites]
        sources = raw.get('source', [])
        if not sources and 'links' in raw:
            sources = raw['links'].get('source', [])
        # In YAML, this can be a single string, or a list of strings.
        if isinstance(sources, str):
            sources = [sources]
        issues = raw.get('issues', [])
        if not issues and 'links' in raw:
            issues = raw['links'].get('issues', [])
        # In YAML, this can be a single string, or a list of strings.
        if isinstance(issues, str):
            issues = [issues]
        documentation = raw.get('docs')
        if documentation is None:
            documentation = raw.get('links', {}).get('documentation')
        self.links = MetadataLinks(
            websites=websites,
            sources=sources,
            issues=issues,
            documentation=documentation,
        )

    @classmethod
    def from_yaml(
        cls,
        metadata: str | TextIO,
        actions: str | TextIO | None = None,
        config: str | TextIO | None = None,
    ) -> CharmMeta:
        """Instantiate a :class:`CharmMeta` from a YAML description of ``metadata.yaml``.

        Args:
            metadata: A YAML description of charm metadata (name, relations, etc.)
                This can be a simple string, or a file-like object (passed to ``yaml.safe_load``).
            actions: YAML description of Actions for this charm (e.g., actions.yaml)
            config: YAML description of Config for this charm (e.g., config.yaml)
        """
        meta = yaml.safe_load(metadata)
        raw_actions = {}
        if actions is not None:
            raw_actions = cast('dict[str, Any] | None', yaml.safe_load(actions))
            if raw_actions is None:
                raw_actions = {}
        raw_config = {}
        if config is not None:
            raw_config = cast('dict[str, Any] | None', yaml.safe_load(config))
            if raw_config is None:
                raw_config = {}
        return cls(meta, raw_actions, raw_config)


class RelationRole(enum.Enum):
    """An annotation for a charm's role in a relation.

    For each relation a charm's role may be

    - A Peer
    - A service consumer in the relation ('requires')
    - A service provider in the relation ('provides')
    """

    peer = 'peer'
    requires = 'requires'
    provides = 'provides'

    def is_peer(self) -> bool:
        """Report whether this role is 'peer'.

        ``role.is_peer()`` is a shortcut for ``role == ops.RelationRole.peer``.
        """
        return self is RelationRole.peer


class RelationMeta:
    """Object containing metadata about a relation definition.

    Should not be constructed directly by charm code, but gotten from one of
    :attr:`CharmMeta.peers`, :attr:`CharmMeta.requires`, :attr:`CharmMeta.provides`,
    or :attr:`CharmMeta.relations`.
    """

    role: RelationRole
    """Role this relation takes, one of 'peer', 'requires', or 'provides'."""

    relation_name: str
    """Name of this relation."""

    interface_name: str | None
    """Definition of the interface protocol."""

    limit: int | None
    """Maximum number of connections to this relation endpoint."""

    scope: str
    """Scope based on how this relation should be used.

    Will be either ``"global"`` or ``"container"``.
    """

    optional: bool
    """If true, the relation is considered optional.

    This value is informational only and is not used by Juju itself (all
    relations are optional from Juju's perspective), but it may be set in
    ``metadata.yaml`` and used by the charm code if appropriate.
    """

    VALID_SCOPES: ClassVar[list[str]] = ['global', 'container']

    def __init__(self, role: RelationRole, relation_name: str, raw: _RelationMetaDict):
        assert isinstance(role, RelationRole), (
            f'role should be one of {list(RelationRole)}, not {role!r}'
        )
        self._default_scope = self.VALID_SCOPES[0]
        self.role = role
        self.relation_name = relation_name
        self.interface_name = raw['interface']

        self.limit = limit = raw.get('limit', None)
        if limit is not None and not isinstance(limit, int):
            raise TypeError(f'limit should be an int, not {type(limit)}')

        self.scope = raw.get('scope') or self._default_scope
        if self.scope not in self.VALID_SCOPES:
            raise TypeError(
                "scope should be one of {}; not '{}'".format(
                    ', '.join(f"'{s}'" for s in self.VALID_SCOPES), self.scope
                )
            )

        self.optional = raw.get('optional', False)


class StorageMeta:
    """Object containing metadata about a storage definition."""

    storage_name: str
    """Name of storage."""

    type: str
    """Storage type, "filesystem" or "block"."""

    description: str
    """Text description of the storage."""

    shared: bool
    """True if all units of the application share the storage."""

    read_only: bool
    """True if the storage is read-only."""

    minimum_size: str | None
    """Minimum size of the storage."""

    location: str | None
    """Mount point of the storage."""

    multiple_range: tuple[int, int | None] | None
    """Range of numeric qualifiers when multiple storage units are used."""

    properties = list[str]
    """List of additional characteristics of the storage."""

    def __init__(self, name: str, raw: _StorageMetaDict):
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
            if range[-1] == '+':
                self.multiple_range = (int(range[:-1]), None)
            elif '-' not in range:
                self.multiple_range = (int(range), int(range))
            else:
                range = range.split('-')
                self.multiple_range = (int(range[0]), int(range[1]) if range[1] else None)
        self.properties = raw.get('properties', [])


class ResourceMeta:
    """Object containing metadata about a resource definition."""

    resource_name: str
    """Name of the resource."""

    type: str
    """Type of the resource. One of ``"file"`` or ``"oci-image"``."""

    filename: str | None
    """Filename of the resource file."""

    description: str
    """A description of the resource.

    This will be empty string (rather than None) if not set in ``metadata.yaml``.
    """

    def __init__(self, name: str, raw: _ResourceMetaDict):
        self.resource_name = name
        self.type = raw['type']
        self.filename = raw.get('filename', None)
        self.description = raw.get('description', '')


class PayloadMeta:
    """Object containing metadata about a payload definition."""

    payload_name: str
    """Name of the payload."""

    type: str
    """Payload type."""

    def __init__(self, name: str, raw: dict[str, Any]):
        self.payload_name = name
        self.type = raw['type']


@dataclasses.dataclass(frozen=True)
class MetadataLinks:
    """Links to additional information about a charm."""

    websites: list[str]
    """List of links to project websites."""

    sources: list[str]
    """List of links to the charm source code."""

    issues: list[str]
    """List of links to the charm issue tracker."""

    documentation: str | None
    """Link to charm documentation."""


class JujuAssumesCondition(enum.Enum):
    """Distinguishes between :class:`JujuAssumes` that must match all or any features."""

    ALL = 'all-of'
    """All features are required to satisfy the requirement."""

    ANY = 'any-of'
    """Any of the features satisfies the requirement."""


@dataclasses.dataclass(frozen=True)
class JujuAssumes:
    """Juju model features that are required by the charm.

    See the `Charmcraft docs <https://documentation.ubuntu.com/charmcraft/stable/reference/files/charmcraft-yaml-file/#assumes>`_
    for a list of available features.
    """

    features: list[str | JujuAssumes]
    condition: JujuAssumesCondition = JujuAssumesCondition.ALL

    @classmethod
    def from_list(
        cls,
        raw: list[Any],
        condition: JujuAssumesCondition = JujuAssumesCondition.ALL,
    ) -> JujuAssumes:
        """Create new JujuAssumes object from list parsed from YAML."""
        features: list[str | JujuAssumes] = []
        for feature in raw:
            if isinstance(feature, str):
                features.append(feature)
            else:
                for nested_condition, nested_features in feature.items():
                    features.append(
                        JujuAssumes.from_list(
                            nested_features, JujuAssumesCondition(nested_condition)
                        )
                    )
        return cls(features=features, condition=condition)


class ActionMeta:
    """Object containing metadata about an action's definition."""

    def __init__(self, name: str, raw: dict[str, Any] | None = None):
        raw = raw or {}
        self.name = name
        self.title = raw.get('title', '')
        self.description = raw.get('description', '')
        self.parameters = raw.get('params', {})  # {<parameter name>: <JSON Schema definition>}
        self.required = raw.get('required', [])  # [<parameter name>, ...]
        # The default in Juju 4 is False. The default in earlier Juju versions is True.
        juju_version = JujuVersion(os.environ.get('JUJU_VERSION', '0.0.0'))
        self.additional_properties = raw.get('additionalProperties', juju_version < '4.0.0')


@dataclasses.dataclass(frozen=True)
class ConfigMeta:
    """Object containing metadata about a config option."""

    name: str
    """Name of the config option."""

    type: Literal['boolean', 'int', 'float', 'string', 'secret']
    """Type of the config option."""

    default: bool | int | float | str | None
    """Default value of the config option."""

    description: str | None
    """Description of the config option."""


@dataclasses.dataclass(frozen=True)
class ContainerBase:
    """Metadata to resolve a container image."""

    os_name: str
    """Name of the OS.

    For example: ``ubuntu``
    """

    channel: str
    """Channel of the OS in format ``track[/risk][/branch]`` as used by Snaps.

    For example: ``20.04/stable`` or ``18.04/stable/fips``
    """

    architectures: list[str]
    """List of architectures that this charm can run on."""

    @classmethod
    def from_dict(cls, d: _ContainerBaseDict) -> ContainerBase:
        """Create new ContainerBase object from dict parsed from YAML."""
        return cls(
            os_name=d['name'],
            channel=d['channel'],
            architectures=d['architectures'],
        )


class ContainerMeta:
    """Metadata about an individual container."""

    name: str
    """Name of the container (key in the YAML)."""

    resource: str | None
    """Reference for an entry in the ``resources`` field.

    Specifies the oci-image resource used to create the container. Must not be
    present if a base/channel is specified.
    """

    bases: list[ContainerBase] | None
    """List of bases for use in resolving a container image.

    Sorted by descending order of preference, and must not be present if
    resource is specified.
    """

    def __init__(self, name: str, raw: dict[str, Any]):
        self.name = name
        self._mounts: dict[str, ContainerStorageMeta] = {}
        self.bases = None
        self.resource = None

        # This is not guaranteed to be populated/is not enforced yet
        if raw:
            self._populate_mounts(raw.get('mounts', []))
            self.resource = raw.get('resource')
            self.bases = [ContainerBase.from_dict(base) for base in raw.get('bases', ())]

        if self.resource and self.bases:
            raise model.ModelError('A container may specify a resource or base, not both.')

    @property
    def mounts(self) -> dict[str, ContainerStorageMeta]:
        """An accessor for the mounts in a container.

        Dict keys match key name in :class:`StorageMeta`

        Example::

            storage:
              foo:
                type: filesystem
                location: /test
            containers:
              bar:
                mounts:
                  - storage: foo
                  - location: /test/mount
        """
        return self._mounts

    def _populate_mounts(self, mounts: list[_MountDict]):
        """Populate a list of container mountpoints.

        Since Charm Metadata v2 specifies the mounts as a List, do a little data manipulation
        to convert the values to "friendly" names which contain a list of mountpoints
        under each key.
        """
        for mount in mounts:
            storage = mount.get('storage', '')
            mount = mount.get('location', '')

            if not mount:
                continue

            if storage in self._mounts:
                self._mounts[storage].add_location(mount)
            else:
                self._mounts[storage] = ContainerStorageMeta(storage, mount)


class ContainerStorageMeta:
    """Metadata about storage for an individual container.

    If multiple locations are specified for the same storage, such as Kubernetes subPath mounts,
    ``location`` will not be an accessible attribute, as it would not be possible to determine
    which mount point was desired, and ``locations`` should be iterated over.
    """

    storage: str
    """Name for the mount point, which should exist in the keys of the charm's
    :class:`StorageMeta`.
    """

    def __init__(self, storage: str, location: str):
        self.storage = storage
        self._locations: list[str] = [location]

    def add_location(self, location: str):
        """Add an additional mount point to a known storage."""
        self._locations.append(location)

    @property
    def locations(self) -> list[str]:
        """An accessor for the list of locations for a mount."""
        return self._locations

    @property
    def location(self) -> str:
        """The location the storage is mounted at.

        Raises:
            RuntimeError: if there is more than one mount point with the same
                backing storage - use :attr:`locations` instead.
        """
        if len(self._locations) == 1:
            return self._locations[0]
        raise RuntimeError(
            'container has more than one mount point with the same backing storage. '
            'Request .locations to see a list'
        )
