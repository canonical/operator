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

"""The Operator Framework infrastructure."""

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
import weakref

from ops import charm
from ops.storage import (
    NoSnapshotError,
    SQLiteStorage,
)

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

    def __init__(self, parent, kind, key):
        if parent and not isinstance(parent, Handle):
            parent = parent.handle
        self._parent = parent
        self._kind = kind
        self._key = key
        if parent:
            if key:
                self._path = "{}/{}[{}]".format(parent, kind, key)
            else:
                self._path = "{}/{}".format(parent, kind)
        else:
            if key:
                self._path = "{}[{}]".format(kind, key)
            else:
                self._path = "{}".format(kind)

    def nest(self, kind, key):
        """Create a new handle as child of the current one."""
        return Handle(self, kind, key)

    def __hash__(self):
        return hash((self.parent, self.kind, self.key))

    def __eq__(self, other):
        return (self.parent, self.kind, self.key) == (other.parent, other.kind, other.key)

    def __str__(self):
        return self.path

    @property
    def parent(self):
        """Return own parent handle."""
        return self._parent

    @property
    def kind(self):
        """Return the handle's kind."""
        return self._kind

    @property
    def key(self):
        """Return the handle's key."""
        return self._key

    @property
    def path(self):
        """Return the handle's path."""
        return self._path

    @classmethod
    def from_path(cls, path):
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
                raise RuntimeError("attempted to restore invalid handle path {}".format(path))
            handle = Handle(handle, kind, key)
        return handle


class EventBase:
    """The base for all the different Events.

    Inherit this and override 'snapshot' and 'restore' methods to build a custom event.
    """

    def __init__(self, handle):
        self.handle = handle
        self.deferred = False

    def __repr__(self):
        return "<%s via %s>" % (self.__class__.__name__, self.handle)

    def defer(self):
        """Defer the event to the future.

        Deferring an event from a handler puts that handler into a queue, to be
        called again the next time the charm is invoked. This invocation may be
        the result of an action, or any event other than metric events. The
        queue of events will be dispatched before the new event is processed.

        From the above you may deduce, but it's important to point out:

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
        better to defer this event so that you see it again, or whether it is
        better to just wait for the event that indicates the precondition has
        been met.

        For example, if ``config-changed`` is fired, and you are waiting for
        different config, there is no reason to defer the event because there
        will be a *different* ``config-changed`` event when the config actually
        changes, rather than checking to see if maybe config has changed prior
        to every other event that occurs.

        Similarly, if you need 2 events to occur before you are ready to
        proceed (say event A and B). When you see event A, you could chose to
        ``defer()`` it because you haven't seen B yet. However, that leads to:

        1. event A fires, calls defer()

        2. event B fires, event A handler is called first, still hasn't seen B
           happen, so is deferred again. Then B happens, which progresses since
           it has seen A.

        3. At some future time, event C happens, which also checks if A can
           proceed.

        """
        logger.debug("Deferring %s.", self)
        self.deferred = True

    def snapshot(self):
        """Return the snapshot data that should be persisted.

        Subclasses must override to save any custom state.
        """
        return None

    def restore(self, snapshot):
        """Restore the value state from the given snapshot.

        Subclasses must override to restore their custom state.
        """
        self.deferred = False


class EventSource:
    """EventSource wraps an event type with a descriptor to facilitate observing and emitting.

    It is generally used as:

        class SomethingHappened(EventBase):
            pass

        class SomeObject(Object):
            something_happened = EventSource(SomethingHappened)

    With that, instances of that type will offer the someobj.something_happened
    attribute which is a BoundEvent and may be used to emit and observe the event.
    """

    def __init__(self, event_type):
        if not isinstance(event_type, type) or not issubclass(event_type, EventBase):
            raise RuntimeError(
                'Event requires a subclass of EventBase as an argument, got {}'.format(event_type))
        self.event_type = event_type
        self.event_kind = None
        self.emitter_type = None

    def _set_name(self, emitter_type, event_kind):
        if self.event_kind is not None:
            raise RuntimeError(
                'EventSource({}) reused as {}.{} and {}.{}'.format(
                    self.event_type.__name__,
                    self.emitter_type.__name__,
                    self.event_kind,
                    emitter_type.__name__,
                    event_kind,
                ))
        self.event_kind = event_kind
        self.emitter_type = emitter_type

    def __get__(self, emitter, emitter_type=None):
        if emitter is None:
            return self
        # Framework might not be available if accessed as CharmClass.on.event
        # rather than charm_instance.on.event, but in that case it couldn't be
        # emitted anyway, so there's no point to registering it.
        framework = getattr(emitter, 'framework', None)
        if framework is not None:
            framework.register_type(self.event_type, emitter, self.event_kind)
        return BoundEvent(emitter, self.event_type, self.event_kind)


class BoundEvent:
    """Event bound to an Object."""

    def __repr__(self):
        return '<BoundEvent {} bound to {}.{} at {}>'.format(
            self.event_type.__name__,
            type(self.emitter).__name__,
            self.event_kind,
            hex(id(self)),
        )

    def __init__(self, emitter, event_type, event_kind):
        self.emitter = emitter
        self.event_type = event_type
        self.event_kind = event_kind

    def emit(self, *args, **kwargs):
        """Emit event to all registered observers.

        The current storage state is committed before and after each observer is notified.
        """
        framework = self.emitter.framework
        key = framework._next_event_key()
        event = self.event_type(Handle(self.emitter, self.event_kind, key), *args, **kwargs)
        framework._emit(event)


class HandleKind:
    """Helper descriptor to define the Object.handle_kind field.

    The handle_kind for an object defaults to its type name, but it may
    be explicitly overridden if desired.
    """

    def __get__(self, obj, obj_type):
        kind = obj_type.__dict__.get("handle_kind")
        if kind:
            return kind
        return obj_type.__name__


class _Metaclass(type):
    """Helper class to ensure proper instantiation of Object-derived classes.

    This class currently has a single purpose: events derived from EventSource
    that are class attributes of Object-derived classes need to be told what
    their name is in that class. For example, in

        class SomeObject(Object):
            something_happened = EventSource(SomethingHappened)

    the instance of EventSource needs to know it's called 'something_happened'.

    Starting from python 3.6 we could use __set_name__ on EventSource for this,
    but until then this (meta)class does the equivalent work.

    TODO: when we drop support for 3.5 drop this class, and rename _set_name in
          EventSource to __set_name__; everything should continue to work.

    """

    def __new__(typ, *a, **kw):
        k = super().__new__(typ, *a, **kw)
        # k is now the Object-derived class; loop over its class attributes
        for n, v in vars(k).items():
            # we could do duck typing here if we want to support
            # non-EventSource-derived shenanigans. We don't.
            if isinstance(v, EventSource):
                # this is what 3.6+ does automatically for us:
                v._set_name(k, n)
        return k


class Object(metaclass=_Metaclass):
    """Base class of all the charm-related objects."""

    handle_kind = HandleKind()

    def __init__(self, parent, key):
        kind = self.handle_kind
        if isinstance(parent, Framework):
            self.framework = parent
            # Avoid Framework instances having a circular reference to themselves.
            if self.framework is self:
                self.framework = weakref.proxy(self.framework)
            self.handle = Handle(None, kind, key)
        else:
            self.framework = parent.framework
            self.handle = Handle(parent, kind, key)
        self.framework._track(self)

        # TODO Detect conflicting handles here.

    @property
    def model(self):
        """Shortcut for more simple access the model."""
        return self.framework.model


class ObjectEvents(Object):
    """Convenience type to allow defining .on attributes at class level."""

    handle_kind = "on"

    def __init__(self, parent=None, key=None):
        if parent is not None:
            super().__init__(parent, key)
        else:
            self._cache = weakref.WeakKeyDictionary()

    def __get__(self, emitter, emitter_type):
        if emitter is None:
            return self
        instance = self._cache.get(emitter)
        if instance is None:
            # Same type, different instance, more data. Doing this unusual construct
            # means people can subclass just this one class to have their own 'on'.
            instance = self._cache[emitter] = type(self)(emitter)
        return instance

    @classmethod
    def define_event(cls, event_kind, event_type):
        """Define an event on this type at runtime.

        cls: a type to define an event on.

        event_kind: an attribute name that will be used to access the
                    event. Must be a valid python identifier, not be a keyword
                    or an existing attribute.

        event_type: a type of the event to define.

        """
        prefix = 'unable to define an event with event_kind that '
        if not event_kind.isidentifier():
            raise RuntimeError(prefix + 'is not a valid python identifier: ' + event_kind)
        elif keyword.iskeyword(event_kind):
            raise RuntimeError(prefix + 'is a python keyword: ' + event_kind)
        try:
            getattr(cls, event_kind)
            raise RuntimeError(
                prefix + 'overlaps with an existing type {} attribute: {}'.format(cls, event_kind))
        except AttributeError:
            pass

        event_descriptor = EventSource(event_type)
        event_descriptor._set_name(cls, event_kind)
        setattr(cls, event_kind, event_descriptor)

    def _event_kinds(self):
        event_kinds = []
        # We have to iterate over the class rather than instance to allow for properties which
        # might call this method (e.g., event views), leading to infinite recursion.
        for attr_name, attr_value in inspect.getmembers(type(self)):
            if isinstance(attr_value, EventSource):
                # We actually care about the bound_event, however, since it
                # provides the most info for users of this method.
                event_kinds.append(attr_name)
        return event_kinds

    def events(self):
        """Return a mapping of event_kinds to bound_events for all available events."""
        return {event_kind: getattr(self, event_kind) for event_kind in self._event_kinds()}

    def __getitem__(self, key):
        return PrefixedEvents(self, key)

    def __repr__(self):
        k = type(self)
        event_kinds = ', '.join(sorted(self._event_kinds()))
        return '<{}.{}: {}>'.format(k.__module__, k.__qualname__, event_kinds)


class PrefixedEvents:
    """Events to be found in all events using a specific prefix."""

    def __init__(self, emitter, key):
        self._emitter = emitter
        self._prefix = key.replace("-", "_") + '_'

    def __getattr__(self, name):
        return getattr(self._emitter, self._prefix + name)


class PreCommitEvent(EventBase):
    """Events that will be emited first on commit."""


class CommitEvent(EventBase):
    """Events that will be emited second on commit."""


class FrameworkEvents(ObjectEvents):
    """Manager of all framework events."""
    pre_commit = EventSource(PreCommitEvent)
    commit = EventSource(CommitEvent)


class NoTypeError(Exception):
    """No class to hold it was found when restoring an event."""

    def __init__(self, handle_path):
        self.handle_path = handle_path

    def __str__(self):
        return "cannot restore {} since no class was registered for it".format(self.handle_path)


# the message to show to the user when a pdb breakpoint goes active
_BREAKPOINT_WELCOME_MESSAGE = """
Starting pdb to debug charm operator.
Run `h` for help, `c` to continue, or `exit`/CTRL-d to abort.
Future breakpoints may interrupt execution again.
More details at https://discourse.jujucharms.com/t/debugging-charm-hooks

"""


_event_regex = r'^(|.*/)on/[a-zA-Z_]+\[\d+\]$'


class Framework(Object):
    """Main interface to from the Charm to the Operator Framework internals."""

    on = FrameworkEvents()

    # Override properties from Object so that we can set them in __init__.
    model = None
    meta = None
    charm_dir = None

    def __init__(self, storage, charm_dir, meta, model):

        super().__init__(self, None)

        self.charm_dir = charm_dir
        self.meta = meta
        self.model = model
        self._observers = []      # [(observer_path, method_name, parent_path, event_key)]
        self._observer = weakref.WeakValueDictionary()       # {observer_path: observer}
        self._objects = weakref.WeakValueDictionary()
        self._type_registry = {}  # {(parent_path, kind): cls}
        self._type_known = set()  # {cls}

        if isinstance(storage, (str, pathlib.Path)):
            logger.warning(
                "deprecated: Framework now takes a Storage not a path")
            storage = SQLiteStorage(storage)
        self._storage = storage

        # We can't use the higher-level StoredState because it relies on events.
        self.register_type(StoredStateData, None, StoredStateData.handle_kind)
        stored_handle = Handle(None, StoredStateData.handle_kind, '_stored')
        try:
            self._stored = self.load_snapshot(stored_handle)
        except NoSnapshotError:
            self._stored = StoredStateData(self, '_stored')
            self._stored['event_count'] = 0

        # Flag to indicate that we already presented the welcome message in a debugger breakpoint
        self._breakpoint_welcomed = False

        # Parse the env var once, which may be used multiple times later
        debug_at = os.environ.get('JUJU_DEBUG_AT')
        self._juju_debug_at = debug_at.split(',') if debug_at else ()

    def set_breakpointhook(self):
        """Hook into sys.breakpointhook so the builtin breakpoint() works as expected.

        This method is called by ``main``, and is not intended to be
        called by users of the framework itself outside of perhaps
        some testing scenarios.

        It returns the old value of sys.excepthook.

        The breakpoint function is a Python >= 3.7 feature.

        This method was added in ops 1.0; before that, it was done as
        part of the Framework's __init__.
        """
        old_breakpointhook = getattr(sys, 'breakpointhook', None)
        if old_breakpointhook is not None:
            # Hook into builtin breakpoint, so if Python >= 3.7, devs will be able to just do
            # breakpoint()
            sys.breakpointhook = self.breakpoint
        return old_breakpointhook

    def close(self):
        """Close the underlying backends."""
        self._storage.close()

    def _track(self, obj):
        """Track object and ensure it is the only object created using its handle path."""
        if obj is self:
            # Framework objects don't track themselves
            return
        if obj.handle.path in self.framework._objects:
            raise RuntimeError(
                'two objects claiming to be {} have been created'.format(obj.handle.path))
        self._objects[obj.handle.path] = obj

    def _forget(self, obj):
        """Stop tracking the given object. See also _track."""
        self._objects.pop(obj.handle.path, None)

    def commit(self):
        """Save changes to the underlying backends."""
        # Give a chance for objects to persist data they want to before a commit is made.
        self.on.pre_commit.emit()
        # Make sure snapshots are saved by instances of StoredStateData. Any possible state
        # modifications in on_commit handlers of instances of other classes will not be persisted.
        self.on.commit.emit()
        # Save our event count after all events have been emitted.
        self.save_snapshot(self._stored)
        self._storage.commit()

    def register_type(self, cls, parent, kind=None):
        """Register a type to a handle."""
        if parent and not isinstance(parent, Handle):
            parent = parent.handle
        if parent:
            parent_path = parent.path
        else:
            parent_path = None
        if not kind:
            kind = cls.handle_kind
        self._type_registry[(parent_path, kind)] = cls
        self._type_known.add(cls)

    def save_snapshot(self, value):
        """Save a persistent snapshot of the provided value.

        The provided value must implement the following interface:

        value.handle = Handle(...)
        value.snapshot() => {...}  # Simple builtin types only.
        value.restore(snapshot)    # Restore custom state from prior snapshot.
        """
        if type(value) not in self._type_known:
            raise RuntimeError(
                'cannot save {} values before registering that type'.format(type(value).__name__))
        data = value.snapshot()

        # Use marshal as a validator, enforcing the use of simple types, as we later the
        # information is really pickled, which is too error prone for future evolution of the
        # stored data (e.g. if the developer stores a custom object and later changes its
        # class name; when unpickling the original class will not be there and event
        # data loading will fail).
        try:
            marshal.dumps(data)
        except ValueError:
            msg = "unable to save the data for {}, it must contain only simple types: {!r}"
            raise ValueError(msg.format(value.__class__.__name__, data))

        self._storage.save_snapshot(value.handle.path, data)

    def load_snapshot(self, handle):
        """Load a persistent snapshot."""
        parent_path = None
        if handle.parent:
            parent_path = handle.parent.path
        cls = self._type_registry.get((parent_path, handle.kind))
        if not cls:
            raise NoTypeError(handle.path)
        data = self._storage.load_snapshot(handle.path)
        obj = cls.__new__(cls)
        obj.framework = self
        obj.handle = handle
        obj.restore(data)
        self._track(obj)
        return obj

    def drop_snapshot(self, handle):
        """Discard a persistent snapshot."""
        self._storage.drop_snapshot(handle.path)

    def observe(self, bound_event: BoundEvent, observer: types.MethodType):
        """Register observer to be called when bound_event is emitted.

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
                'Framework.observe requires a BoundEvent as second parameter, got {}'.format(
                    bound_event))
        if not isinstance(observer, types.MethodType):
            # help users of older versions of the framework
            if isinstance(observer, charm.CharmBase):
                raise TypeError(
                    'observer methods must now be explicitly provided;'
                    ' please replace observe(self.on.{0}, self)'
                    ' with e.g. observe(self.on.{0}, self._on_{0})'.format(
                        bound_event.event_kind))
            raise RuntimeError(
                'Framework.observe requires a method as third parameter, got {}'.format(observer))

        event_type = bound_event.event_type
        event_kind = bound_event.event_kind
        emitter = bound_event.emitter

        self.register_type(event_type, emitter, event_kind)

        if hasattr(emitter, "handle"):
            emitter_path = emitter.handle.path
        else:
            raise RuntimeError(
                'event emitter {} must have a "handle" attribute'.format(type(emitter).__name__))

        # Validate that the method has an acceptable call signature.
        sig = inspect.signature(observer)
        # Self isn't included in the params list, so the first arg will be the event.
        extra_params = list(sig.parameters.values())[1:]

        method_name = observer.__name__
        observer = observer.__self__
        if not sig.parameters:
            raise TypeError(
                '{}.{} must accept event parameter'.format(type(observer).__name__, method_name))
        elif any(param.default is inspect.Parameter.empty for param in extra_params):
            # Allow for additional optional params, since there's no reason to exclude them, but
            # required params will break.
            raise TypeError(
                '{}.{} has extra required parameter'.format(type(observer).__name__, method_name))

        # TODO Prevent the exact same parameters from being registered more than once.

        self._observer[observer.handle.path] = observer
        self._observers.append((observer.handle.path, method_name, emitter_path, event_kind))

    def _next_event_key(self):
        """Return the next event key that should be used, incrementing the internal counter."""
        # Increment the count first; this means the keys will start at 1, and 0
        # means no events have been emitted.
        self._stored['event_count'] += 1
        return str(self._stored['event_count'])

    def _emit(self, event):
        """See BoundEvent.emit for the public way to call this."""
        saved = False
        event_path = event.handle.path
        event_kind = event.handle.kind
        parent_path = event.handle.parent.path
        # TODO Track observers by (parent_path, event_kind) rather than as a list of
        # all observers. Avoiding linear search through all observers for every event
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

    def reemit(self):
        """Reemit previously deferred events to the observers that deferred them.

        Only the specific observers that have previously deferred the event will be
        notified again. Observers that asked to be notified about events after it's
        been first emitted won't be notified, as that would mean potentially observing
        events out of order.
        """
        self._reemit()

    def _reemit(self, single_event_path=None):
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

            event.deferred = False
            observer = self._observer.get(observer_path)
            if observer:
                if single_event_path is None:
                    logger.debug("Re-emitting %s.", event)
                custom_handler = getattr(observer, method_name, None)
                if custom_handler:
                    event_is_from_juju = isinstance(event, charm.HookEvent)
                    event_is_action = isinstance(event, charm.ActionEvent)
                    if (event_is_from_juju or event_is_action) and 'hook' in self._juju_debug_at:
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
            self.framework._forget(event)

        if not deferred and last_event_path is not None:
            self._storage.drop_snapshot(last_event_path)

    def _show_debug_code_message(self):
        """Present the welcome message (only once!) when using debugger functionality."""
        if not self._breakpoint_welcomed:
            self._breakpoint_welcomed = True
            print(_BREAKPOINT_WELCOME_MESSAGE, file=sys.stderr, end='')

    def breakpoint(self, name=None):
        """Add breakpoint, optionally named, at the place where this method is called.

        For the breakpoint to be activated the JUJU_DEBUG_AT environment variable
        must be set to "all" or to the specific name parameter provided, if any. In every
        other situation calling this method does nothing.

        The framework also provides a standard breakpoint named "hook", that will
        stop execution when a hook event is about to be handled.

        For those reasons, the "all" and "hook" breakpoint names are reserved.
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
            code_frame = inspect.currentframe().f_back
            pdb.Pdb().set_trace(code_frame)
        else:
            logger.warning(
                "Breakpoint %r skipped (not found in the requested breakpoints: %s)",
                name, indicated_breakpoints)

    def remove_unreferenced_events(self):
        """Remove events from storage that are not referenced.

        In older versions of the framework, events that had no observers would get recorded but
        never deleted. This makes a best effort to find these events and remove them from the
        database.
        """
        event_regex = re.compile(_event_regex)
        to_remove = []
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

    def __init__(self, parent, attr_name):
        super().__init__(parent, attr_name)
        self._cache = {}
        self.dirty = False

    def __getitem__(self, key):
        return self._cache.get(key)

    def __setitem__(self, key, value):
        self._cache[key] = value
        self.dirty = True

    def __contains__(self, key):
        return key in self._cache

    def snapshot(self):
        """Return the current state."""
        return self._cache

    def restore(self, snapshot):
        """Restore current state to the given snapshot."""
        self._cache = snapshot
        self.dirty = False

    def on_commit(self, event):
        """Save changes to the storage backend."""
        if self.dirty:
            self.framework.save_snapshot(self)
            self.dirty = False


class BoundStoredState:
    """Stored state data bound to a specific Object."""

    def __init__(self, parent, attr_name):
        parent.framework.register_type(StoredStateData, parent)

        handle = Handle(parent, StoredStateData.handle_kind, attr_name)
        try:
            data = parent.framework.load_snapshot(handle)
        except NoSnapshotError:
            data = StoredStateData(parent, attr_name)

        # __dict__ is used to avoid infinite recursion.
        self.__dict__["_data"] = data
        self.__dict__["_attr_name"] = attr_name

        parent.framework.observe(parent.framework.on.commit, self._data.on_commit)

    def __getattr__(self, key):
        # "on" is the only reserved key that can't be used in the data map.
        if key == "on":
            return self._data.on
        if key not in self._data:
            raise AttributeError("attribute '{}' is not stored".format(key))
        return _wrap_stored(self._data, self._data[key])

    def __setattr__(self, key, value):
        if key == "on":
            raise AttributeError("attribute 'on' is reserved and cannot be set")

        value = _unwrap_stored(self._data, value)

        if not isinstance(value, (type(None), int, float, str, bytes, list, dict, set)):
            raise AttributeError(
                'attribute {!r} cannot be a {}: must be int/float/dict/list/etc'.format(
                    key, type(value).__name__))

        self._data[key] = _unwrap_stored(self._data, value)

    def set_default(self, **kwargs):
        """Set the value of any given key if it has not already been set."""
        for k, v in kwargs.items():
            if k not in self._data:
                self._data[k] = v


class StoredState:
    """A class used to store data the charm needs persisted across invocations.

    Example::

        class MyClass(Object):
            _stored = StoredState()

    Instances of `MyClass` can transparently save state between invocations by
    setting attributes on `_stored`. Initial state should be set with
    `set_default` on the bound object, that is::

        class MyClass(Object):
            _stored = StoredState()

        def __init__(self, parent, key):
            super().__init__(parent, key)
            self._stored.set_default(seen=set())
            self.framework.observe(self.on.seen, self._on_seen)

        def _on_seen(self, event):
            self._stored.seen.add(event.uuid)

    """

    def __init__(self):
        self.parent_type = None
        self.attr_name = None

    def __get__(self, parent, parent_type=None):
        if self.parent_type is not None and self.parent_type not in parent_type.mro():
            # the StoredState instance is being shared between two unrelated classes
            # -> unclear what is exepcted of us -> bail out
            raise RuntimeError(
                'StoredState shared by {} and {}'.format(
                    self.parent_type.__name__, parent_type.__name__))

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
            parent.__dict__[self.attr_name] = bound
            return bound

        raise AttributeError(
            'cannot find {} attribute in type {}'.format(
                self.__class__.__name__, parent_type.__name__))


def _wrap_stored(parent_data, value):
    t = type(value)
    if t is dict:
        return StoredDict(parent_data, value)
    if t is list:
        return StoredList(parent_data, value)
    if t is set:
        return StoredSet(parent_data, value)
    return value


def _unwrap_stored(parent_data, value):
    t = type(value)
    if t is StoredDict or t is StoredList or t is StoredSet:
        return value._under
    return value


def _wrapped_repr(obj):
    t = type(obj)
    if obj._under:
        return "{}.{}({!r})".format(t.__module__, t.__name__, obj._under)
    else:
        return "{}.{}()".format(t.__module__, t.__name__)


class StoredDict(collections.abc.MutableMapping):
    """A dict-like object that uses the StoredState as backend."""

    def __init__(self, stored_data, under):
        self._stored_data = stored_data
        self._under = under

    def __getitem__(self, key):
        return _wrap_stored(self._stored_data, self._under[key])

    def __setitem__(self, key, value):
        self._under[key] = _unwrap_stored(self._stored_data, value)
        self._stored_data.dirty = True

    def __delitem__(self, key):
        del self._under[key]
        self._stored_data.dirty = True

    def __iter__(self):
        return self._under.__iter__()

    def __len__(self):
        return len(self._under)

    def __eq__(self, other):
        if isinstance(other, StoredDict):
            return self._under == other._under
        elif isinstance(other, collections.abc.Mapping):
            return self._under == other
        else:
            return NotImplemented

    __repr__ = _wrapped_repr


class StoredList(collections.abc.MutableSequence):
    """A list-like object that uses the StoredState as backend."""

    def __init__(self, stored_data, under):
        self._stored_data = stored_data
        self._under = under

    def __getitem__(self, index):
        return _wrap_stored(self._stored_data, self._under[index])

    def __setitem__(self, index, value):
        self._under[index] = _unwrap_stored(self._stored_data, value)
        self._stored_data.dirty = True

    def __delitem__(self, index):
        del self._under[index]
        self._stored_data.dirty = True

    def __len__(self):
        return len(self._under)

    def insert(self, index, value):
        """Insert value before index."""
        self._under.insert(index, value)
        self._stored_data.dirty = True

    def append(self, value):
        """Append value to the end of the list."""
        self._under.append(value)
        self._stored_data.dirty = True

    def __eq__(self, other):
        if isinstance(other, StoredList):
            return self._under == other._under
        elif isinstance(other, collections.abc.Sequence):
            return self._under == other
        else:
            return NotImplemented

    def __lt__(self, other):
        if isinstance(other, StoredList):
            return self._under < other._under
        elif isinstance(other, collections.abc.Sequence):
            return self._under < other
        else:
            return NotImplemented

    def __le__(self, other):
        if isinstance(other, StoredList):
            return self._under <= other._under
        elif isinstance(other, collections.abc.Sequence):
            return self._under <= other
        else:
            return NotImplemented

    def __gt__(self, other):
        if isinstance(other, StoredList):
            return self._under > other._under
        elif isinstance(other, collections.abc.Sequence):
            return self._under > other
        else:
            return NotImplemented

    def __ge__(self, other):
        if isinstance(other, StoredList):
            return self._under >= other._under
        elif isinstance(other, collections.abc.Sequence):
            return self._under >= other
        else:
            return NotImplemented

    __repr__ = _wrapped_repr


class StoredSet(collections.abc.MutableSet):
    """A set-like object that uses the StoredState as backend."""

    def __init__(self, stored_data, under):
        self._stored_data = stored_data
        self._under = under

    def add(self, key):
        """Add a key to a set.

        This has no effect if the key is already present.
        """
        self._under.add(key)
        self._stored_data.dirty = True

    def discard(self, key):
        """Remove a key from a set if it is a member.

        If the key is not a member, do nothing.
        """
        self._under.discard(key)
        self._stored_data.dirty = True

    def __contains__(self, key):
        return key in self._under

    def __iter__(self):
        return self._under.__iter__()

    def __len__(self):
        return len(self._under)

    @classmethod
    def _from_iterable(cls, it):
        """Construct an instance of the class from any iterable input.

        Per https://docs.python.org/3/library/collections.abc.html
        if the Set mixin is being used in a class with a different constructor signature,
        you will need to override _from_iterable() with a classmethod that can construct
        new instances from an iterable argument.
        """
        return set(it)

    def __le__(self, other):
        if isinstance(other, StoredSet):
            return self._under <= other._under
        elif isinstance(other, collections.abc.Set):
            return self._under <= other
        else:
            return NotImplemented

    def __ge__(self, other):
        if isinstance(other, StoredSet):
            return self._under >= other._under
        elif isinstance(other, collections.abc.Set):
            return self._under >= other
        else:
            return NotImplemented

    def __eq__(self, other):
        if isinstance(other, StoredSet):
            return self._under == other._under
        elif isinstance(other, collections.abc.Set):
            return self._under == other
        else:
            return NotImplemented

    __repr__ = _wrapped_repr
