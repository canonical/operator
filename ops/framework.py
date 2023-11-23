# Copyright 2020-2021 Canonical Ltd.
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

"""The ops library's infrastructure."""

import collections
import collections.abc
import inspect
import keyword
import logging
import marshal
import os
import pathlib
import pdb
import re
import sys
import types
import typing
import weakref
from contextlib import contextmanager
from typing import (
    TYPE_CHECKING,
    Any,
    Callable,
    Dict,
    Hashable,
    Iterable,
    List,
    Literal,
    Optional,
    Protocol,
    Set,
    Tuple,
    Type,
    TypeVar,
    Union,
)

from ops import charm
from ops.model import Model, _ModelBackend
from ops.storage import JujuStorage, NoSnapshotError, SQLiteStorage


class Serializable(typing.Protocol):
    """The type returned by :meth:`Framework.load_snapshot`."""

    handle_kind = ''

    @property
    def handle(self) -> 'Handle': ...  # noqa
    @handle.setter
    def handle(self, val: 'Handle'): ...  # noqa
    def snapshot(self) -> Dict[str, Any]: ...  # noqa
    def restore(self, snapshot: Dict[str, Any]) -> None: ...  # noqa


class _StoredObject(Protocol):
    _under: Any = None  # noqa


StoredObject = Union['StoredList', 'StoredSet', 'StoredDict']

_Path = _Kind = _MethodName = _EventKey = str
# used to type Framework Attributes
_ObserverPath = List[Tuple[_Path, _MethodName, _Path, _EventKey]]
_ObjectPath = Tuple[Optional[_Path], _Kind]
_PathToObjectMapping = Dict[_Path, 'Object']
_PathToSerializableMapping = Dict[_Path, Serializable]

_T = TypeVar("_T")
_EventType = TypeVar('_EventType', bound='EventBase')
_ObjectType = TypeVar("_ObjectType", bound="Object")

logger = logging.getLogger(__name__)


class Handle:
    """Handle defines a name for an object in the form of a hierarchical path.

    The provided parent is the object (or that object's handle) that this handle
    sits under, or None if the object identified by this handle stands by itself
    as the root of its own hierarchy.

    The handle kind is a string that defines a namespace so objects with the
    same parent and kind will have unique keys.

    The handle key is a string uniquely identifying the object. No other objects
    under the same parent and kind may have the same key.
    """

    def __init__(self, parent: Optional[Union['Handle', 'Object']], kind: str, key: Optional[str]):
        if isinstance(parent, Object):
            # if it's not an Object, it will be either a Handle (good) or None (no parent)
            parent = parent.handle
        self._parent: Optional[Handle] = parent
        self._kind = kind
        self._key = key
        if parent:
            if key:
                self._path = f"{parent}/{kind}[{key}]"
            else:
                self._path = f"{parent}/{kind}"
        else:
            if key:
                self._path = f"{kind}[{key}]"
            else:
                self._path = f"{kind}"  # don't need f-string, but consistent with above

    def nest(self, kind: str, key: Optional[str]) -> 'Handle':
        """Create a new handle as child of the current one."""
        return Handle(self, kind, key)

    def __hash__(self):
        return hash((self.parent, self.kind, self.key))

    def __eq__(self, other: 'Handle'):
        return (self.parent, self.kind, self.key) == (other.parent, other.kind, other.key)

    def __str__(self):
        return self.path

    @property
    def parent(self) -> Optional['Handle']:
        """Return own parent handle."""
        return self._parent

    @property
    def kind(self) -> str:
        """Return the handle's kind."""
        return self._kind

    @property
    def key(self) -> Optional[str]:
        """Return the handle's key."""
        return self._key

    @property
    def path(self) -> str:
        """Return the handle's path."""
        return self._path

    @classmethod
    def from_path(cls, path: str) -> 'Handle':
        """Build a handle from the indicated path."""
        handle = None
        for pair in path.split("/"):
            pair = pair.split("[")
            good = False
            if len(pair) == 1:
                kind, key = pair[0], None
                good = True
            elif len(pair) == 2:
                kind, key = pair
                if key and key[-1] == ']':
                    key = key[:-1]
                    good = True
            if not good:
                raise RuntimeError(f"attempted to restore invalid handle path {path}")
            handle = Handle(handle, kind, key)  # type: ignore
        return typing.cast(Handle, handle)


class EventBase:
    """The base class for all events.

    Inherit this and override the ``snapshot`` and ``restore`` methods to
    create a custom event.
    """

    # gets patched in by `Framework.restore()`, if this event is being re-emitted
    # after being loaded from snapshot, or by `BoundEvent.emit()` if this
    # event is being fired for the first time.
    # TODO this is hard to debug, this should be refactored
    framework: 'Framework' = None  # type: ignore
    """The :class:`Framework` instance (set by the framework itself)."""

    def __init__(self, handle: Handle):
        self.handle = handle
        self.deferred: bool = False

    def __repr__(self):
        return f"<{self.__class__.__name__} via {self.handle}>"

    def defer(self) -> None:
        """Defer the event to the future.

        Deferring an event from a handler puts that handler into a queue, to be
        called again the next time the charm is invoked. This invocation may be
        the result of an action, or any event other than metric events. The
        queue of events will be dispatched before the new event is processed.

        Important points that follow from the above:

        * ``defer()`` does not interrupt the execution of the current event
          handler. In almost all cases, a call to ``defer()`` should be followed
          by an explicit ``return`` from the handler;

        * the re-execution of the deferred event handler starts from the top of
          the handler method (not where defer was called);

        * only the handlers that actually called ``defer()`` are called again
          (that is: despite talking about “deferring an event” it is actually
          the handler/event combination that is deferred); and

        * any deferred events get processed before the event (or action) that
          caused the current invocation of the charm.

        The general desire to call ``defer()`` happens when some precondition
        isn't yet met. However, care should be exercised as to whether it is
        better to defer this event so that it is seen again, or whether it is
        better to just wait for the event that indicates the precondition has
        been met.

        For example, if handling a config change requires that two config
        values are changed, there's no reason to defer the first
        ``config-changed`` because there will be a *second* ``config-changed``
        event fired when the other config value changes.

        Similarly, if two events need to occur before execution can proceed
        (say event A and B), the event A handler could ``defer()`` because B
        has not been seen yet. However, that leads to:

        1. event A fires, calls defer()

        2. event B fires, event A handler is called first, still hasn't seen B
           happen, so is deferred again. Then B happens, which progresses since
           it has seen A.

        3. At some future time, event C happens, which also checks if A can
           proceed.
        """
        logger.debug("Deferring %s.", self)
        self.deferred = True

    def snapshot(self) -> Dict[str, Any]:
        """Return the snapshot data that should be persisted.

        Subclasses must override to save any custom state.
        """
        return {}

    def restore(self, snapshot: Dict[str, Any]):
        """Restore the value state from the given snapshot.

        Subclasses must override to restore their custom state.
        """
        self.deferred = False


class EventSource:
    """EventSource wraps an event type with a descriptor to facilitate observing and emitting.

    It is generally used as::

        class SomethingHappened(ops.EventBase):
            pass

        class SomeObject(Object):
            something_happened = ops.EventSource(SomethingHappened)

    With that, instances of that type will offer the ``someobj.something_happened``
    attribute which is a :class:`BoundEvent`, and may be used to emit and observe
    the event.
    """

    def __init__(self, event_type: 'Type[EventBase]'):
        if not isinstance(event_type, type) or not issubclass(event_type, EventBase):
            raise RuntimeError(
                f'Event requires a subclass of EventBase as an argument, got {event_type}')
        self.event_type: Type[EventBase] = event_type
        self.event_kind: Optional[str] = None
        self.emitter_type: Optional[Type[Object]] = None

    def __set_name__(self, emitter_type: 'Type[Object]', event_kind: str):
        if self.event_kind is not None:
            raise RuntimeError(
                'EventSource({}) reused as {}.{} and {}.{}'.format(
                    self.event_type.__name__,
                    # emitter_type could still be None
                    getattr(self.emitter_type, '__name__', self.emitter_type),
                    self.event_kind,
                    emitter_type.__name__,
                    event_kind,
                ))
        self.event_kind = event_kind
        self.emitter_type = emitter_type

    def __get__(self, emitter: Optional['Object'],
                emitter_type: 'Type[Object]'
                ) -> 'BoundEvent':
        if emitter is None:
            return self  # type: ignore
        # Framework might not be available if accessed as CharmClass.on.event
        # rather than charm_instance.on.event, but in that case it couldn't be
        # emitted anyway, so there's no point to registering it.
        framework = getattr(emitter, 'framework', None)
        if framework is not None:
            framework.register_type(self.event_type, emitter, self.event_kind)
        return BoundEvent(emitter, self.event_type, typing.cast(str, self.event_kind))


class BoundEvent:
    """Event bound to an Object."""

    def __repr__(self):
        return '<BoundEvent {} bound to {}.{} at {}>'.format(
            self.event_type.__name__,
            type(self.emitter).__name__,
            self.event_kind,
            hex(id(self)),
        )

    def __init__(self, emitter: 'Object',
                 event_type: 'Type[EventBase]',
                 event_kind: str):
        self.emitter = emitter
        self.event_type = event_type
        self.event_kind = event_kind

    def emit(self, *args: Any, **kwargs: Any):
        """Emit event to all registered observers.

        The current storage state is committed before and after each observer
        is notified.

        Note that the emission of custom events is handled immediately. In
        other words, custom events are not queued, but rather nested. For
        example::

            1. Main hook handler (emits custom_event_1)
            2.   Custom event 1 handler (emits custom_event_2)
            3.     Custom event 2 handler
            4.   Resume custom event 1 handler
            5. Resume main hook handler
        """
        framework = self.emitter.framework
        key = framework._next_event_key()
        event = self.event_type(Handle(self.emitter, self.event_kind, key), *args, **kwargs)
        event.framework = framework
        framework._emit(event)


class HandleKind:
    """Helper descriptor to define the Object.handle_kind field.

    The handle_kind for an object defaults to its type name, but it may
    be explicitly overridden if desired.
    """

    def __get__(self, obj: 'Object', obj_type: 'Type[Object]') -> str:
        kind = typing.cast(str, obj_type.__dict__.get("handle_kind"))
        if kind:
            return kind
        return obj_type.__name__


class Object:
    """Initialize an Object as a new leaf in :class:`Framework`, identified by `key`.

    Args:
        parent: parent node in the tree.
        key: unique identifier for this object.

    Every object belongs to exactly one framework.

    Every object has a parent, which might be a framework.

    We track a "path to object," which is the path to the parent, plus the object's unique
    identifier. Event handlers use this identity to track the destination of their events, and the
    Framework uses this id to track persisted state between event executions.

    The Framework should raise an error if it ever detects that two objects with the same id have
    been created.

    """
    handle_kind: str = HandleKind()  # type: ignore

    if TYPE_CHECKING:
        # to help the type checker and IDEs:
        # all these are guaranteed to be set at runtime.
        @property
        def on(self) -> 'ObjectEvents': ...  # noqa

    def __init__(self, parent: Union['Framework', 'Object'], key: Optional[str]):
        self.framework: Framework = None  # type: ignore
        self.handle: Handle = None  # type: ignore

        kind = self.handle_kind
        if isinstance(parent, Framework):
            self.framework = parent
            # Avoid Framework instances having a circular reference to themselves.
            if self.framework is self:
                self.framework = weakref.proxy(self.framework)
            self.handle = Handle(None, kind, typing.cast(str, key))
        else:
            self.framework = parent.framework
            self.handle = Handle(parent, kind, typing.cast(str, key))
        self.framework._track(self)  # type: ignore

        # TODO Detect conflicting handles here.

    @property
    def model(self) -> 'Model':
        """Shortcut for more simple access the model."""
        return self.framework.model


class ObjectEvents(Object):
    """Convenience type to allow defining ``.on`` attributes at class level."""

    handle_kind = "on"

    def __init__(self, parent: Optional[Object] = None, key: Optional[str] = None):
        if parent is not None:
            super().__init__(parent, key)
        self._cache: weakref.WeakKeyDictionary[Object, 'ObjectEvents'] = \
            weakref.WeakKeyDictionary()

    def __get__(self, emitter: Object, emitter_type: 'Type[Object]'):
        if emitter is None:
            return self
        instance = self._cache.get(emitter)
        if instance is None:
            # Same type, different instance, more data. Doing this unusual construct
            # means people can subclass just this one class to have their own 'on'.
            instance = self._cache[emitter] = type(self)(emitter)
        return instance

    @classmethod
    def define_event(cls, event_kind: str, event_type: 'Type[EventBase]'):
        """Define an event on this type at runtime.

        Note that attempting to define the same event kind more than once will
        raise an "overlaps with existing type" runtime error. Ops uses a
        labeling system to track and reconstruct events between hook executions
        (each time a hook runs, the Juju Agent invokes a fresh instance of ops;
        there is no ops process that persists on the host between hooks).
        Having duplicate Python objects creates duplicate labels. Overwriting a
        previously created label means that only the latter code path will be
        run when the current event, if it does get deferred, is re-emitted. This
        is usually not what is desired, and is error-prone and ambiguous.

        Args:
            event_kind: An attribute name that will be used to access the
                        event. Must be a valid Python identifier, not be a keyword
                        or an existing attribute.
            event_type: A type of the event to define.

        Raises:
            RuntimeError: if the same event is defined twice, or if ``event_kind``
                is an invalid name.
        """
        prefix = 'unable to define an event with event_kind that '
        if not event_kind.isidentifier():
            raise RuntimeError(f"{prefix}is not a valid python identifier: {event_kind}")
        elif keyword.iskeyword(event_kind):
            raise RuntimeError(f"{prefix}is a python keyword: {event_kind}")
        try:
            getattr(cls, event_kind)
            raise RuntimeError(
                f"{prefix}overlaps with an existing type {cls} attribute: {event_kind}")
        except AttributeError:
            pass

        event_descriptor = EventSource(event_type)
        event_descriptor.__set_name__(cls, event_kind)
        setattr(cls, event_kind, event_descriptor)

    def _event_kinds(self) -> List[str]:
        event_kinds: List[str] = []
        # We have to iterate over the class rather than instance to allow for properties which
        # might call this method (e.g., event views), leading to infinite recursion.
        for attr_name, attr_value in inspect.getmembers(type(self)):
            if isinstance(attr_value, EventSource):
                # We actually care about the bound_event, however, since it
                # provides the most info for users of this method.
                event_kinds.append(attr_name)
        return event_kinds

    def events(self) -> Dict[str, EventSource]:
        """Return a mapping of event_kinds to bound_events for all available events."""
        return {event_kind: getattr(self, event_kind) for event_kind in self._event_kinds()}

    def __getitem__(self, key: str) -> 'PrefixedEvents':
        return PrefixedEvents(self, key)

    def __repr__(self):
        k = type(self)
        event_kinds = ', '.join(sorted(self._event_kinds()))
        return f'<{k.__module__}.{k.__qualname__}: {event_kinds}>'

    def __getattr__(self, name: str) -> Any:
        """The existence of this method tells type checkers to allow dynamic attributes.

        This allows charms to access dynamically-defined events such as
        ``self.on.db_relation_joined`` without Mypy/Pyright whining.
        """
        return super().__getattribute__(name)


class PrefixedEvents:
    """Events to be found in all events using a specific prefix."""

    def __init__(self, emitter: Object, key: str):
        self._emitter = emitter
        self._prefix = key.replace('-', '_') + '_'

    def __getattr__(self, name: str) -> BoundEvent:
        return getattr(self._emitter, self._prefix + name)


class LifecycleEvent(EventBase):
    """Events tied to the lifecycle of the Framework object."""


class PreCommitEvent(LifecycleEvent):
    """Event that will be emitted first on commit."""


class CommitEvent(LifecycleEvent):
    """Event that will be emitted second on commit."""


class FrameworkEvents(ObjectEvents):
    """Manager of all framework events."""

    pre_commit = EventSource(PreCommitEvent)
    """Triggered before the :attr:`commit` event."""

    commit = EventSource(CommitEvent)
    """Triggered before event data is committed to storage."""


class NoTypeError(Exception):
    """No class to hold it was found when restoring an event."""

    def __init__(self, handle_path: str):
        self.handle_path = handle_path

    def __str__(self):
        return f"cannot restore {self.handle_path} since no class was registered for it"


# the message to show to the user when a pdb breakpoint goes active
_BREAKPOINT_WELCOME_MESSAGE = """
Starting pdb to debug charm operator.
Run `h` for help, `c` to continue, or `exit`/CTRL-d to abort.
Future breakpoints may interrupt execution again.
More details at https://juju.is/docs/sdk/debugging

"""

_event_regex = r'^(|.*/)on/[a-zA-Z_]+\[\d+\]$'


class Framework(Object):
    """Main interface from the Charm to the ops library's infrastructure."""

    on = FrameworkEvents()  # type: ignore
    """Used for :meth:`observe`-ing framework-specific events."""

    # Override properties from Object so that we can set them in __init__.
    model: 'Model' = None  # type: ignore
    """The :class:`Model` instance for this charm."""

    meta: 'charm.CharmMeta' = None  # type: ignore
    """The charm's metadata."""

    charm_dir: 'pathlib.Path' = None  # type: ignore
    """The charm project root directory."""

    _stored: 'StoredStateData' = None  # type: ignore

    # to help the type checker and IDEs:
    if TYPE_CHECKING:
        @property
        def on(self) -> 'FrameworkEvents': ...  # noqa

    def __init__(self, storage: Union[SQLiteStorage, JujuStorage],
                 charm_dir: Union[str, pathlib.Path],
                 meta: 'charm.CharmMeta', model: 'Model',
                 event_name: Optional[str] = None):
        super().__init__(self, None)

        # an old, deprecated __init__ interface accepted an Optional charm_dir,
        #  so we have to keep supporting it:
        if charm_dir is None:
            logger.warning('Framework should not be initialized with `charm_dir` set to None.')
            self.charm_dir = None  # type: ignore
        else:
            self.charm_dir = pathlib.Path(charm_dir)

        if event_name:
            event_name = event_name.replace('-', '_')
        self._event_name = event_name

        self.meta = meta
        self.model = model
        # [(observer_path, method_name, parent_path, event_key)]
        self._observers: _ObserverPath = []
        # {observer_path: observing Object}
        self._observer: _PathToObjectMapping = weakref.WeakValueDictionary()  # type: ignore
        # {object_path: object}
        self._objects: _PathToSerializableMapping = weakref.WeakValueDictionary()  # type: ignore
        # {(parent_path, kind): cls}
        # (parent_path, kind) is the address of _this_ object: the parent path
        # plus a 'kind' string that is the name of this object.
        self._type_registry: Dict[_ObjectPath, Type[Serializable]] = {}
        self._type_known: Set[Type[Serializable]] = set()

        if isinstance(storage, (str, pathlib.Path)):
            logger.warning(
                "deprecated: Framework now takes a Storage not a path")
            storage = SQLiteStorage(storage)
        # TODO(benhoyt): should probably have a Storage protocol
        self._storage: 'SQLiteStorage' = storage  # type: ignore

        # We can't use the higher-level StoredState because it relies on events.
        self.register_type(StoredStateData, None, StoredStateData.handle_kind)
        stored_handle = Handle(None, StoredStateData.handle_kind, '_stored')
        try:
            self._stored = typing.cast(StoredStateData, self.load_snapshot(stored_handle))
        except NoSnapshotError:
            self._stored = StoredStateData(self, '_stored')
            self._stored['event_count'] = 0

        # Flag to indicate that we already presented the welcome message in a debugger breakpoint
        self._breakpoint_welcomed: bool = False

        # Parse the env var once, which may be used multiple times later
        debug_at = os.environ.get('JUJU_DEBUG_AT')
        if debug_at:
            self._juju_debug_at = {x.strip() for x in debug_at.split(',')}
        else:
            self._juju_debug_at: Set[str] = set()

    def set_breakpointhook(self) -> Optional[Any]:
        """Hook into ``sys.breakpointhook`` so the builtin ``breakpoint()`` works as expected.

        This method is called by ``main``, and is not intended to be
        called by users of the framework itself outside of perhaps
        some testing scenarios.

        The ``breakpoint()`` function is a Python >= 3.7 feature.

        This method was added in ops 1.0; before that, it was done as
        part of the Framework's ``__init__``.

        Returns:
            The old value of ``sys.breakpointhook``.
        """
        old_breakpointhook = getattr(sys, 'breakpointhook', None)
        if old_breakpointhook is not None:
            # Hook into builtin breakpoint, so if Python >= 3.7, devs will be able to just do
            # breakpoint()
            sys.breakpointhook = self.breakpoint
        return old_breakpointhook

    def close(self) -> None:
        """Close the underlying backends."""
        self._storage.close()

    def _track(self, obj: 'Serializable'):
        """Track object and ensure it is the only object created using its handle path."""
        if obj is self:
            # Framework objects don't track themselves
            return
        if obj.handle.path in self.framework._objects:
            raise RuntimeError(
                f'two objects claiming to be {obj.handle.path} have been created')
        self._objects[obj.handle.path] = obj

    def _forget(self, obj: 'Serializable'):
        """Stop tracking the given object. See also _track."""
        self._objects.pop(obj.handle.path, None)

    def commit(self) -> None:
        """Save changes to the underlying backends."""
        # Give a chance for objects to persist data they want to before a commit is made.
        self.on.pre_commit.emit()
        # Make sure snapshots are saved by instances of StoredStateData. Any possible state
        # modifications in on_commit handlers of instances of other classes will not be persisted.
        self.on.commit.emit()
        # Save our event count after all events have been emitted.
        self.save_snapshot(self._stored)
        self._storage.commit()

    def register_type(self, cls: Type[Serializable], parent: Optional[Union['Handle', 'Object']],
                      kind: Optional[str] = None):
        """Register a type to a handle."""
        parent_path: Optional[str] = None
        if isinstance(parent, Object):
            parent_path = parent.handle.path
        elif isinstance(parent, Handle):
            parent_path = parent.path

        kind_: str = kind or cls.handle_kind
        self._type_registry[(parent_path, kind_)] = cls
        self._type_known.add(cls)

    def save_snapshot(self, value: Union["StoredStateData", "EventBase"]):
        """Save a persistent snapshot of the provided value."""
        if type(value) not in self._type_known:
            raise RuntimeError(
                f'cannot save {type(value).__name__} values before registering that type')
        data = value.snapshot()

        # Use marshal as a validator, enforcing the use of simple types, as we later the
        # information is really pickled, which is too error-prone for future evolution of the
        # stored data (e.g. if the developer stores a custom object and later changes its
        # class name; when unpickling the original class will not be there and event
        # data loading will fail).
        try:
            marshal.dumps(data)
        except ValueError:
            msg = "unable to save the data for {}, it must contain only simple types: {!r}"
            raise ValueError(msg.format(value.__class__.__name__, data)) from None

        self._storage.save_snapshot(value.handle.path, data)

    def load_snapshot(self, handle: Handle) -> Serializable:
        """Load a persistent snapshot."""
        parent_path = None
        if handle.parent:
            parent_path = handle.parent.path
        cls_or_none = self._type_registry.get((parent_path, handle.kind))
        if not cls_or_none:
            raise NoTypeError(handle.path)
        cls: Type[Serializable] = cls_or_none
        data = self._storage.load_snapshot(handle.path)
        obj = cls.__new__(cls)
        obj.framework = self  # type: ignore
        obj.handle = handle
        obj.restore(data)
        self._track(obj)
        return obj

    def drop_snapshot(self, handle: Handle):
        """Discard a persistent snapshot."""
        self._storage.drop_snapshot(handle.path)

    def observe(self, bound_event: BoundEvent, observer: Callable[[Any], None]):
        """Register observer to be called when bound_event is emitted.

        If this is called multiple times for the same event type, the
        framework calls the observers in the order they were observed.

        The bound_event is generally provided as an attribute of the object that emits
        the event, and is created in this style::

            class SomeObject:
                something_happened = Event(SomethingHappened)

        That event may be observed as::

            framework.observe(someobj.something_happened, self._on_something_happened)

        Raises:
            RuntimeError: if bound_event or observer are the wrong type.
        """
        if not isinstance(bound_event, BoundEvent):
            raise RuntimeError(
                f'Framework.observe requires a BoundEvent as second parameter, got {bound_event}')
        if not isinstance(observer, types.MethodType):
            # help users of older versions of the framework
            if isinstance(observer, charm.CharmBase):
                raise TypeError(
                    'observer methods must now be explicitly provided;'
                    ' please replace observe(self.on.{0}, self)'
                    ' with e.g. observe(self.on.{0}, self._on_{0})'.format(
                        bound_event.event_kind))
            raise RuntimeError(
                f'Framework.observe requires a method as third parameter, got {observer}')

        event_type = bound_event.event_type
        event_kind = bound_event.event_kind
        emitter = bound_event.emitter

        self.register_type(event_type, emitter, event_kind)  # type: ignore

        if hasattr(emitter, "handle"):
            emitter_path = emitter.handle.path
        else:
            raise RuntimeError(
                f'event emitter {type(emitter).__name__} must have a "handle" attribute')

        # Validate that the method has an acceptable call signature.
        sig = inspect.signature(observer)
        # Self isn't included in the params list, so the first arg will be the event.
        extra_params = list(sig.parameters.values())[1:]

        method_name = observer.__name__

        assert isinstance(observer.__self__, Object), "can't register observers " \
                                                      "that aren't `Object`s"
        observer_obj = observer.__self__
        if not sig.parameters:
            raise TypeError(
                f'{type(observer_obj).__name__}.{method_name} must accept event parameter')
        elif any(param.default is inspect.Parameter.empty for param in extra_params):
            # Allow for additional optional params, since there's no reason to exclude them, but
            # required params will break.
            raise TypeError(
                f'{type(observer_obj).__name__}.{method_name} has extra required parameter')

        # TODO Prevent the exact same parameters from being registered more than once.

        self._observer[observer_obj.handle.path] = observer_obj
        self._observers.append((observer_obj.handle.path,
                                method_name, emitter_path, event_kind))

    def _next_event_key(self) -> str:
        """Return the next event key that should be used, incrementing the internal counter."""
        # Increment the count first; this means the keys will start at 1, and 0
        # means no events have been emitted.
        self._stored['event_count'] += 1  # type: ignore  #(we know event_count holds an int)
        return str(self._stored['event_count'])

    def _emit(self, event: EventBase):
        """See BoundEvent.emit for the public way to call this."""
        saved = False
        event_path = event.handle.path
        event_kind = event.handle.kind
        parent = event.handle.parent
        assert isinstance(parent, Handle), "event handle must have a parent"
        parent_path = parent.path
        # TODO Track observers by (parent_path, event_kind) rather than as a list of
        #  all observers. Avoiding linear search through all observers for every event
        for observer_path, method_name, _parent_path, _event_kind in self._observers:
            if _parent_path != parent_path:
                continue
            if _event_kind and _event_kind != event_kind:
                continue
            if not saved:
                # Save the event for all known observers before the first notification
                # takes place, so that either everyone interested sees it, or nobody does.
                self.save_snapshot(event)
                saved = True
            # Again, only commit this after all notices are saved.
            self._storage.save_notice(event_path, observer_path, method_name)
        if saved:
            self._reemit(event_path)

    def reemit(self) -> None:
        """Reemit previously deferred events to the observers that deferred them.

        Only the specific observers that have previously deferred the event will be
        notified again. Observers that asked to be notified about events after it's
        been first emitted won't be notified, as that would mean potentially observing
        events out of order.
        """
        self._reemit()

    @contextmanager
    def _event_context(self, event_name: str):
        """Handles toggling the hook-is-running state in backends.

        This allows e.g. harness logic to know if it is executing within a running hook context
        or not.  It sets backend._hook_is_running equal to the name of the currently running
        hook (e.g. "set-leader") and reverts back to the empty string when the hook execution
        is completed.

        Usage:
            >>> with harness._event_context('db-relation-changed'):
            >>>     print('Harness thinks it is running an event hook.')
            >>> with harness._event_context(''):
            >>>     print('harness thinks it is not running an event hook.')
        """
        backend: Optional[_ModelBackend] = self.model._backend if self.model else None
        if not backend:
            yield  # context does nothing in this case
            return

        old_event_name = self._event_name
        self._event_name = event_name

        old_hook_is_running = backend._hook_is_running
        backend._hook_is_running = event_name
        yield
        backend._hook_is_running = old_hook_is_running

        self._event_name = old_event_name

    def _reemit(self, single_event_path: Optional[str] = None):
        last_event_path = None
        deferred = True
        for event_path, observer_path, method_name in self._storage.notices(single_event_path):
            event_handle = Handle.from_path(event_path)

            if last_event_path != event_path:
                if not deferred and last_event_path is not None:
                    self._storage.drop_snapshot(last_event_path)
                last_event_path = event_path
                deferred = False

            try:
                event = self.load_snapshot(event_handle)
            except NoTypeError:
                self._storage.drop_notice(event_path, observer_path, method_name)
                continue

            event = typing.cast(EventBase, event)
            event.deferred = False
            observer = self._observer.get(observer_path)

            if observer:
                if single_event_path is None:
                    logger.debug("Re-emitting deferred event %s.", event)
                elif isinstance(event, LifecycleEvent):
                    # Ignore Lifecycle events: they are "private" and not interesting.
                    pass
                elif self._event_name and self._event_name != event.handle.kind:
                    # if the event we are emitting now is not the event being
                    # dispatched, and it also is not an event we have deferred,
                    # it must be a custom event
                    logger.debug("Emitting custom event %s.", event)

                custom_handler = getattr(observer, method_name, None)
                if custom_handler:
                    event_is_from_juju = isinstance(event, charm.HookEvent)
                    event_is_action = isinstance(event, charm.ActionEvent)
                    with self._event_context(event_handle.kind):
                        if (
                            event_is_from_juju or event_is_action
                        ) and self._juju_debug_at.intersection({'all', 'hook'}):
                            # Present the welcome message and run under PDB.
                            self._show_debug_code_message()
                            pdb.runcall(custom_handler, event)
                        else:
                            # Regular call to the registered method.
                            custom_handler(event)

            if event.deferred:
                deferred = True
            else:
                self._storage.drop_notice(event_path, observer_path, method_name)
            # We intentionally consider this event to be dead and reload it from
            # scratch in the next path.
            self.framework._forget(event)  # type: ignore

        if not deferred and last_event_path is not None:
            self._storage.drop_snapshot(last_event_path)

    def _show_debug_code_message(self):
        """Present the welcome message (only once!) when using debugger functionality."""
        if not self._breakpoint_welcomed:
            self._breakpoint_welcomed = True
            print(_BREAKPOINT_WELCOME_MESSAGE, file=sys.stderr, end='')

    def breakpoint(self, name: Optional[str] = None):
        """Add breakpoint, optionally named, at the place where this method is called.

        For the breakpoint to be activated the JUJU_DEBUG_AT environment variable
        must be set to "all" or to the specific name parameter provided, if any. In every
        other situation calling this method does nothing.

        The framework also provides a standard breakpoint named "hook", that will
        stop execution when a hook event is about to be handled.

        For those reasons, the "all" and "hook" breakpoint names are reserved.

        Raises:
            ValueError: if the breakpoint name is invalid.
        """
        # If given, validate the name comply with all the rules
        if name is not None:
            if not isinstance(name, str):
                raise TypeError('breakpoint names must be strings')
            if name in ('hook', 'all'):
                raise ValueError('breakpoint names "all" and "hook" are reserved')
            if not re.match(r'^[a-z0-9]([a-z0-9\-]*[a-z0-9])?$', name):
                raise ValueError('breakpoint names must look like "foo" or "foo-bar"')

        indicated_breakpoints = self._juju_debug_at
        if not indicated_breakpoints:
            return

        if 'all' in indicated_breakpoints or name in indicated_breakpoints:
            self._show_debug_code_message()

            # If we call set_trace() directly it will open the debugger *here*, so indicating
            # it to use our caller's frame
            code_frame = inspect.currentframe().f_back  # type: ignore
            pdb.Pdb().set_trace(code_frame)
        else:
            logger.warning(
                "Breakpoint %r skipped (not found in the requested breakpoints: %s)",
                name, indicated_breakpoints)

    def remove_unreferenced_events(self) -> None:
        """Remove events from storage that are not referenced.

        In older versions of the framework, events that had no observers would get recorded but
        never deleted. This makes a best effort to find these events and remove them from the
        database.
        """
        event_regex = re.compile(_event_regex)
        to_remove: List[str] = []
        for handle_path in self._storage.list_snapshots():
            if event_regex.match(handle_path):
                notices = self._storage.notices(handle_path)
                if next(notices, None) is None:
                    # There are no notices for this handle_path, it is valid to remove it
                    to_remove.append(handle_path)
        for handle_path in to_remove:
            self._storage.drop_snapshot(handle_path)


class StoredStateData(Object):
    """Manager of the stored data."""

    def __init__(self, parent: Object, attr_name: str):
        super().__init__(parent, attr_name)
        self._cache: Dict[str, Any] = {}
        self.dirty: bool = False

    def __getitem__(self, key: str) -> Any:
        return self._cache.get(key)

    def __setitem__(self, key: str, value: Any):
        self._cache[key] = value
        self.dirty = True

    def __contains__(self, key: str):
        return key in self._cache

    def snapshot(self) -> Dict[str, Any]:
        """Return the current state."""
        return self._cache

    def restore(self, snapshot: Dict[str, Any]):
        """Restore current state to the given snapshot."""
        self._cache = snapshot
        self.dirty = False

    def on_commit(self, event: EventBase) -> None:
        """Save changes to the storage backend."""
        if self.dirty:
            self.framework.save_snapshot(self)
            self.dirty = False


class BoundStoredState:
    """Stored state data bound to a specific Object."""
    if TYPE_CHECKING:
        # to help the type checker and IDEs:
        @property
        def _data(self) -> StoredStateData: ...  # noqa, type: ignore

        @property
        def _attr_name(self) -> str: ...  # noqa, type: ignore

    def __init__(self, parent: Object, attr_name: str):
        parent.framework.register_type(StoredStateData, parent)

        handle = Handle(parent, StoredStateData.handle_kind, attr_name)
        try:
            data = parent.framework.load_snapshot(handle)
        except NoSnapshotError:
            data = StoredStateData(parent, attr_name)

        # __dict__ is used to avoid infinite recursion.
        self.__dict__["_data"] = data
        self.__dict__["_attr_name"] = attr_name

        parent.framework.observe(parent.framework.on.commit, self._data.on_commit)  # type: ignore

    @typing.overload
    def __getattr__(self, key: Literal['on']) -> ObjectEvents:
        pass

    @typing.overload
    def __getattr__(self, key: str) -> Any:
        pass

    def __getattr__(self, key: str) -> Any:
        # "on" is the only reserved key that can't be used in the data map.
        if key == "on":
            return self._data.on
        if key not in self._data:
            raise AttributeError(f"attribute '{key}' is not stored")
        return _wrap_stored(self._data, self._data[key])

    def __setattr__(self, key: str, value: Any):
        if key == "on":
            raise AttributeError("attribute 'on' is reserved and cannot be set")

        unwrapped = _unwrap_stored(self._data, value)

        if not isinstance(unwrapped, (type(None), int, float, str, bytes, list, dict, set)):
            raise AttributeError(
                'attribute {!r} cannot be a {}: must be int/float/dict/list/etc'.format(
                    key, type(unwrapped).__name__))

        self._data[key] = unwrapped

    def set_default(self, **kwargs: Any):
        """Set the value of any given key if it has not already been set."""
        for k, v in kwargs.items():
            if k not in self._data:
                self._data[k] = v


class StoredState:
    """A class used to store data the charm needs, persisted across invocations.

    Example::

        class MyClass(ops.Object):
            _stored = ops.StoredState()

    Instances of ``MyClass`` can transparently save state between invocations by
    setting attributes on ``_stored``. Initial state should be set with
    ``set_default`` on the bound object, that is::

        class MyClass(ops.Object):
            _stored = ops.StoredState()

            def __init__(self, parent, key):
                super().__init__(parent, key)
                self._stored.set_default(seen=set())
                self.framework.observe(self.on.seen, self._on_seen)

            def _on_seen(self, event):
                self._stored.seen.add(event.uuid)

    """

    def __init__(self):
        self.parent_type: Optional[Type[Any]] = None
        self.attr_name: Optional[str] = None

    @typing.overload
    def __get__(
            self,
            parent: Literal[None],
            parent_type: 'Type[_ObjectType]') -> 'StoredState':
        pass

    @typing.overload
    def __get__(
            self,
            parent: '_ObjectType',
            parent_type: 'Type[_ObjectType]') -> BoundStoredState:
        pass

    def __get__(self,
                parent: Optional['_ObjectType'],
                parent_type: 'Type[_ObjectType]') -> Union['StoredState',
                                                           BoundStoredState]:
        if self.parent_type is not None and self.parent_type not in parent_type.mro():
            # the StoredState instance is being shared between two unrelated classes
            # -> unclear what is expected of us -> bail out
            raise RuntimeError(
                f'StoredState shared by {self.parent_type.__name__} and {parent_type.__name__}')

        if parent is None:
            # accessing via the class directly (e.g. MyClass.stored)
            return self

        bound = None
        if self.attr_name is not None:
            bound = parent.__dict__.get(self.attr_name)
            if bound is not None:
                # we already have the thing from a previous pass, huzzah
                return bound

        # need to find ourselves amongst the parent's bases
        for cls in parent_type.mro():
            for attr_name, attr_value in cls.__dict__.items():
                if attr_value is not self:
                    continue
                # we've found ourselves! is it the first time?
                if bound is not None:
                    # the StoredState instance is being stored in two different
                    # attributes -> unclear what is expected of us -> bail out
                    raise RuntimeError("StoredState shared by {0}.{1} and {0}.{2}".format(
                        cls.__name__, self.attr_name, attr_name))
                # we've found ourselves for the first time; save where, and bind the object
                self.attr_name = attr_name
                self.parent_type = cls
                bound = BoundStoredState(parent, attr_name)

        if bound is not None:
            # cache the bound object to avoid the expensive lookup the next time
            # (don't use setattr, to keep things symmetric with the fast-path lookup above)

            # attr_name is optional at descriptor level, but we're bound now: it's
            # guaranteed to be a string. We need to help the type checker:
            assert isinstance(self.attr_name, str)
            parent.__dict__[self.attr_name] = bound
            return bound

        raise AttributeError(
            f'cannot find {self.__class__.__name__} attribute in type {parent_type.__name__}')


def _wrap_stored(parent_data: StoredStateData, value: Any) -> Any:
    if isinstance(value, dict):
        return StoredDict(parent_data, value)  # type: ignore
    if isinstance(value, list):
        return StoredList(parent_data, value)  # type: ignore
    if isinstance(value, set):
        return StoredSet(parent_data, value)  # type: ignore
    return value


def _unwrap_stored(parent_data: StoredStateData, value: Any) -> Any:
    if isinstance(value, (StoredDict, StoredList, StoredSet)):
        return value._under  # pyright: ignore[reportPrivateUsage]
    return value


def _wrapped_repr(obj: '_StoredObject') -> str:
    t = type(obj)
    if obj._under:
        return f"{t.__module__}.{t.__name__}({obj._under!r})"  # type: ignore
    else:
        return f"{t.__module__}.{t.__name__}()"


class StoredDict(typing.MutableMapping[Hashable, Any]):
    """A dict-like object that uses the StoredState as backend."""

    def __init__(self, stored_data: StoredStateData, under: Dict[Hashable, Any]):
        self._stored_data = stored_data
        self._under = under

    def __getitem__(self, key: Hashable):
        return _wrap_stored(self._stored_data, self._under[key])

    def __setitem__(self, key: Hashable, value: Any):
        self._under[key] = _unwrap_stored(self._stored_data, value)
        self._stored_data.dirty = True

    def __delitem__(self, key: Hashable):
        del self._under[key]
        self._stored_data.dirty = True

    def __iter__(self):
        return self._under.__iter__()

    def __len__(self):
        return len(self._under)

    def __eq__(self, other: Any):
        if isinstance(other, StoredDict):
            return self._under == other._under
        elif isinstance(other, collections.abc.Mapping):
            return self._under == other
        else:
            return NotImplemented

    __repr__ = _wrapped_repr  # type: ignore


class StoredList(typing.MutableSequence[Any]):
    """A list-like object that uses the StoredState as backend."""

    def __init__(self, stored_data: StoredStateData, under: List[Any]):
        self._stored_data = stored_data
        self._under = under

    def __getitem__(self, index: int):
        return _wrap_stored(self._stored_data, self._under[index])

    def __setitem__(self, index: int, value: Any):
        self._under[index] = _unwrap_stored(self._stored_data, value)
        self._stored_data.dirty = True

    def __delitem__(self, index: int):
        del self._under[index]
        self._stored_data.dirty = True

    def __len__(self):
        return len(self._under)

    def insert(self, index: int, value: Any):
        """Insert value before index."""
        self._under.insert(index, value)
        self._stored_data.dirty = True

    def append(self, value: Any):
        """Append value to the end of the list."""
        self._under.append(value)
        self._stored_data.dirty = True

    def __eq__(self, other: Any):
        if isinstance(other, StoredList):
            return self._under == other._under
        elif isinstance(other, list):
            return self._under == other
        else:
            return NotImplemented

    def __lt__(self, other: Any):
        if isinstance(other, StoredList):
            return self._under < other._under
        elif isinstance(other, list):
            return self._under < other
        else:
            return NotImplemented

    def __le__(self, other: Any):
        if isinstance(other, StoredList):
            return self._under <= other._under
        elif isinstance(other, list):
            return self._under <= other
        else:
            return NotImplemented

    def __gt__(self, other: Any):
        if isinstance(other, StoredList):
            return self._under > other._under
        elif isinstance(other, list):
            return self._under > other
        else:
            return NotImplemented

    def __ge__(self, other: Any):
        if isinstance(other, StoredList):
            return self._under >= other._under
        elif isinstance(other, list):
            return self._under >= other
        else:
            return NotImplemented

    __repr__ = _wrapped_repr  # type: ignore


class StoredSet(typing.MutableSet[Any]):
    """A set-like object that uses the StoredState as backend."""

    def __init__(self, stored_data: StoredStateData, under: Set[Any]):
        self._stored_data = stored_data
        self._under = under

    def add(self, key: Any):
        """Add a key to a set.

        This has no effect if the key is already present.
        """
        self._under.add(key)
        self._stored_data.dirty = True

    def discard(self, key: Any):
        """Remove a key from a set if it is a member.

        If the key is not a member, do nothing.
        """
        self._under.discard(key)
        self._stored_data.dirty = True

    def __contains__(self, key: Any):
        return key in self._under

    def __iter__(self):
        return self._under.__iter__()

    def __len__(self):
        return len(self._under)

    @classmethod
    def _from_iterable(cls, it: Iterable[_T]) -> Set[_T]:
        """Construct an instance of the class from any iterable input.

        Per https://docs.python.org/3/library/collections.abc.html
        if the Set mixin is being used in a class with a different constructor signature,
        override _from_iterable() with a classmethod that can construct new instances
        from an iterable argument.
        """
        return set(it)

    def __le__(self, other: Any):
        if isinstance(other, StoredSet):
            return self._under <= other._under
        elif isinstance(other, collections.abc.Set):
            return self._under <= other
        else:
            return NotImplemented

    def __ge__(self, other: Any):
        if isinstance(other, StoredSet):
            return self._under >= other._under
        elif isinstance(other, collections.abc.Set):
            return self._under >= other
        else:
            return NotImplemented

    def __eq__(self, other: Any):
        if isinstance(other, StoredSet):
            return self._under == other._under
        elif isinstance(other, collections.abc.Set):
            return self._under == other
        else:
            return NotImplemented

    __repr__ = _wrapped_repr  # type: ignore
