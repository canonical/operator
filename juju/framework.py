import pickle
import marshal
import types
import sqlite3


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
        self.parent = parent
        self.kind = kind
        self.key = key

    def nest(self, kind, key):
        return Handle(self, kind, key)

    def __hash__(self):
        return hash((self.parent, self.kind, self.key))

    def __eq__(self, other):
        return (self.parent, self.kind, self.key) == (other.parent, other.kind, other.key)

    def __str__(self):
        return self.path

    @property
    def path(self):
        # TODO Cache result and either clear cache when attributes change, or make it read-only.
        if self.parent:
            if self.key:
                return f"{self.parent}/{self.kind}.{self.key}"
            else:
                return f"{self.parent}/{self.kind}"
        else:
            if self.key:
                return f"{self.kind}.{self.key}"
            else:
                return f"{self.kind}"

    @classmethod
    def from_path(cls, path):
        handle = None
        for pair in path.split("/"):
            pair = pair.split(".")
            if len(pair) == 1:
                kind, key = pair[0], None
            elif len(pair) == 2:
                kind, key = pair
            else:
                raise RuntimeError("attempted to restore invalid handle path {path}")
            handle = Handle(handle, kind, key)
        return handle


class EventBase:

    def __init__(self, handle):
        self.handle = handle
        self.deferred = False

    def defer(self):
        self.deferred = True

    def snapshot(self):
        return None

    def restore(self, snapshot):
        """Restore the value state from the given snapshot.

        Subclasses must override to restore their custom state.
        """
        self.deferred = False


class Event:
    """Event creates class descriptors to operate with events.

    It generally used as:

        class SomethingHappened(EventBase):
            pass

        class SomeObject:
            something_happened = Event(SomethingHappened)


    With that, instances of that type will offer the someobj.something_happened
    attribute which is a BoundEvent and may be used to emit and observe the event.
    """

    def __init__(self, event_type):
        if not isinstance(event_type, type) or not issubclass(event_type, EventBase):
            raise RuntimeError(f"Event requires a subclass of EventBase as an argument, got {event_type}")
        self.event_type = event_type
        self.event_kind = {}

    def __get__(self, emitter, emitter_type=None):
        event_kind = self.event_kind.get(emitter_type)
        if not event_kind:
            found_cls = None
            for cls in emitter_type.__mro__:
                for attr_name, attr_value in cls.__dict__.items():
                    if attr_value is self:
                        if event_kind:
                            raise RuntimeError("Event({}) shared between {}.{} and {}.{}".format(
                                self.event_type.__name__, found_cls.__name__, event_kind, cls.__name__, attr_name))
                        found_cls = cls
                        event_kind = attr_name
                        self.event_kind[emitter_type] = event_kind
            if not event_kind:
                raise RuntimeError("Cannot find Event({}) attribute in type {}".format(self.event_type.__name__, emitter_type.__name__))
        if emitter is None:
            return self
        return BoundEvent(emitter, self.event_type, event_kind)


class BoundEvent:

    def __init__(self, emitter, event_type, event_kind):
        self.emitter = emitter
        self.event_type = event_type
        self.event_kind = event_kind

    def emit(self, *args, **kwargs):
        """Emit event to all registered observers.

        The current storage state is committed before and after each observer is notified.
        """
        framework = self.emitter.framework
        framework._event_count += 1
        key = str(framework._event_count)
        event = self.event_type(Handle(self.emitter, self.event_kind, key), *args, **kwargs)
        framework._emit(event)


class HandleKind:
    """Helper descriptor to define the Object.handle_kind field.

    The handle_kind for an object defaults to its type name, but it may
    be explicitly overriden if desired.
    """

    def __get__(self, obj, obj_type):
        kind = obj_type.__dict__.get("handle_kind")
        if kind:
            return kind
        return obj_type.__name__


class Object:

    handle_kind = HandleKind()

    def __init__(self, parent=None, key=None):
        kind = self.handle_kind
        if isinstance(parent, Framework):
            self.framework = parent
            self.handle = Handle(None, kind, key)
        else:
            self.framework = parent.framework
            self.handle = Handle(parent, kind, key)

        # TODO Detect conflicting handles here.

        # TODO Register all event types found in 'self' or 'self.on' into the framework upfront.


class EventsBase(Object):
    """Convenience type to allow defining .on attributes at class level."""

    handle_kind = "on"

    def __init__(self, parent=None):
        if parent != None:
            super().__init__(parent)

    def __get__(self, emitter, emitter_type):
        # Same type, different instance, more data (http://j.mp/mgc1111).
        return type(self)(emitter)


class NoSnapshotError(Exception):

    def __init__(self, handle_path):
        self.handle_path = handle_path

    def __str__(self):
        return f'no snapshot data found for {self.handle_path} object'


class SQLiteStorage:

    def __init__(self, filename):
        self._db = sqlite3.connect(str(filename), isolation_level="EXCLUSIVE")
        self._setup()

    def _setup(self):
        c = self._db.execute("BEGIN")
        c.execute("SELECT count(name) FROM sqlite_master WHERE type='table' AND name='snapshot'")
        if c.fetchone()[0] == 0:
            # Keep it mind what might happen if the process dies somewhere below.
            # The system must not be rendered permanently broken by that.
            self._db.execute("CREATE TABLE snapshot (handle TEXT PRIMARY KEY, data TEXT)")
            self._db.execute("CREATE TABLE notice (sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_path TEXT, observer_path TEXT, method_name TEXT)")
            self._db.commit()

    def close(self):
        self._db.close()

    def commit(self):
        self._db.commit()

    # There's commit but no rollback. For abort to be supported, we'll need logic that
    # can rollback decisions made by third-party code in terms of the internal state
    # of objects that have been snapshotted, and hooks to let them know about it and
    # take the needed actions to undo their logic until the last snapshot.
    # This is doable but will increase significantly the chances for mistakes.

    def save_snapshot(self, handle_path, snapshot_data):
        self._db.execute("REPLACE INTO snapshot VALUES (?, ?)", (handle_path, snapshot_data))

    def load_snapshot(self, handle_path):
        c = self._db.cursor()
        c.execute("SELECT data FROM snapshot WHERE handle=?", (handle_path,))
        row = c.fetchone()
        if row:
            return row[0]
        return None

    def drop_snapshot(self, handle_path):
        self._db.execute("DELETE FROM snapshot WHERE handle=?", (handle_path,))

    def save_notice(self, event_path, observer_path, method_name):
        self._db.execute("INSERT INTO notice VALUES (NULL, ?, ?, ?)", (event_path, observer_path, method_name))

    def drop_notice(self, event_path, observer_path, method_name):
        self._db.execute("DELETE FROM notice WHERE event_path=? AND observer_path=? AND method_name=?", (event_path, observer_path, method_name))

    def notices(self, event_path):
        if event_path:
            c = self._db.execute("SELECT event_path, observer_path, method_name FROM notice WHERE event_path=? ORDER BY sequence", (event_path,))
        else:
            c = self._db.execute("SELECT event_path, observer_path, method_name FROM notice ORDER BY sequence")
        while True:
            rows = c.fetchmany()
            if not rows:
                break
            for row in rows:
                yield tuple(row)


class Framework:

    def __init__(self, data_path):
        self._data_path = data_path
        self._event_count = 0
        self._observers = [] # [(observer, method_name, parent_path, event_key)]
        self._observer = {}  # {observer_path: observer}
        self._type_registry = {} # {(parent_path, kind): cls}
        self._type_known = set() # {cls}

        self._storage = SQLiteStorage(data_path)

    def close(self):
        self._storage.close()

    def commit(self):
        self._storage.commit()

    def register_type(self, cls, parent, kind=None):
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
            raise RuntimeError(f"cannot save {type(value).__name__} values before registering that type")
        data = value.snapshot()
        # Use marshal as a validator, enforcing the use of simple types.
        _ = marshal.dumps(data)
        # Use pickle for serialization, so the value remains portable.
        raw_data = pickle.dumps(data)
        self._storage.save_snapshot(value.handle.path, raw_data)

    def load_snapshot(self, handle):
        parent_path = None
        if handle.parent:
            parent_path = handle.parent.path
        cls = self._type_registry.get((parent_path, handle.kind))
        if not cls:
            # TODO Proper exception type here.
            raise RuntimeError(f"cannot restore {handle.path} since no class was registered for it")
        raw_data = self._storage.load_snapshot(handle.path)
        if not raw_data:
            raise NoSnapshotError(handle.path)
        data = pickle.loads(raw_data)
        obj = cls.__new__(cls)
        obj.framework = self
        obj.handle = handle
        obj.restore(data)
        return obj

    def drop_snapshot(self, handle):
        self._storage.drop_snapshot(handle.path)

    def observe(self, bound_event, observer):
        """Register observer to be called when bound_event is emitted.

        The bound_event is generally provided as an attribute of the object that emits
        the event, and is created in this style:

            class SomeObject:
                something_happened = Event(SomethingHappened)

        That event may be observed as:

            framework.observe(someobj.something_happened, self.on_something_happened)

        If the method to be called follows the name convention "on_<event name>", it
        may be omitted from the observe call. That means the above is equivalent to:

            framework.observe(someobj.something_happened, self)

        """
        if not isinstance(bound_event, BoundEvent):
            raise RuntimeError(f'Framework.observe requires a BoundEvent as second parameter, got {bound_event}')

        event_type = bound_event.event_type
        event_kind = bound_event.event_kind
        emitter = bound_event.emitter

        self.register_type(event_type, emitter, event_kind)

        if hasattr(emitter, "handle"):
            emitter_path = emitter.handle.path
        else:
            raise RuntimeError(f'event emitter {type(emitter).__name__} must have a "handle" attribute')

        method_name = None
        if isinstance(observer, types.MethodType):
            method_name = observer.__name__
            observer = observer.__self__
        else:
            method_name = "on_" + event_kind
            if not hasattr(observer, method_name):
                raise RuntimeError(f'Observer method not provided explicitly and {type(observer).__name__} type has no "on_{method_name}" method')

        # TODO Validate that the method has the right signature here.

        # TODO Prevent the exact same parameters from being registered more than once.

        self._observer[observer.handle.path] = observer
        self._observers.append((observer.handle.path, method_name, emitter_path, event_kind))

    def _emit(self, event):
        """See BoundEvent.emit for the public way to call this."""

        # Save the event for all known observers before the first notification
        # takes place, so that either everyone interested sees it, or nobody does.
        self.save_snapshot(event)
        event_path = event.handle.path
        event_kind = event.handle.kind
        parent_path = event.handle.parent.path
        notices = []
        for observer_path, method_name, _parent_path, _event_kind in self._observers:
            if _parent_path != parent_path:
                continue
            if _event_kind and _event_kind != event_kind:
                continue
            # Again, only commit this after all notices are saved.
            self._storage.save_notice(event_path, observer_path, method_name)
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
                if not deferred:
                    self._storage.drop_snapshot(last_event_path)
                last_event_path = event_path
                deferred = False

            event = self.load_snapshot(event_handle)
            event.deferred = False
            observer = self._observer.get(observer_path)
            if observer:
                custom_handler = getattr(observer, method_name, None)
                if custom_handler:
                    custom_handler(event)

            if event.deferred:
                deferred = True
            else:
                self._storage.drop_notice(event_path, observer_path, method_name)

        if not deferred:
            self._storage.drop_snapshot(last_event_path)


class StoredStateData(Object):

    def __init__(self, parent, attr_name):
        super().__init__(parent, attr_name)
        self._cache = {}

    def __getitem__(self, key):
        return self._cache.get(key)

    def __setitem__(self, key, value):
        self._cache[key] = value

    def __contains__(self, key):
        return key in self._cache

    def snapshot(self):
        return self._cache

    def restore(self, snapshot):
        self._cache = snapshot

class StoredStateChanged(EventBase):
    pass

class StoredStateEvents(EventsBase):
    changed = Event(StoredStateChanged)

class BoundStoredState:

    def __init__(self, parent, attr_name):
        parent.framework.register_type(StoredStateData, parent)

        handle = Handle(parent, StoredStateData.handle_kind, attr_name)
        try:
            data = parent.framework.load_snapshot(handle)
        except NoSnapshotError:
            data = StoredStateData(parent, attr_name)

        self.__dict__["_data"] = data
        self.__dict__["_attr_name"] = attr_name

        # "on" is the only reserved key that can't be used in the data map.
        self.__dict__["on"] = StoredStateEvents(self._data)

    def __getattr__(self, key):
        if key not in self._data:
            raise AttributeError(f"{self._data.handle.parent}.{self._data.handle.key} has no '{key}' attribute stored")
        return self._data[key]

    def __setattr__(self, key, value):
        if key == "on":
            raise AttributeError(f"{self._data.handle.parent}.{self._data.handle.key} attempting to set reserved 'on' attribute")
        self._data[key] = value
        self._data.framework.save_snapshot(self._data)
        self.on.changed.emit()

        # TODO Saving a snapshot on every change is not efficient. Instead, the
        # the framework should offer a pre-commit event that the state can monitor
        # and save itself at the right time if changes are pending.

        # TODO Values that can be mutated, such as dicts, lists, sets, won't work well
        # as stored state. We'll likely need StoredDict, StoredList, and StoredSet to
        # fix that. Those objects will emit their own events, which must be caught by
        # the parent stored state and reemited to notify observers that the overall
        # state is also changing.


class StoredState:

    def __init__(self):
        self.parent_type = None
        self.attr_name = None

    def __get__(self, parent, parent_type=None):
        if self.parent_type is None:
            self.parent_type = parent_type
        elif self.parent_type is not parent_type:
            raise RuntimeError("StoredState shared by {} and {}".format(self.parent_type.__name__, parent_type.__name__))

        if parent is None:
            return self

        bound = parent.__dict__.get(self.attr_name)
        if bound is None:
            for attr_name, attr_value in parent_type.__dict__.items():
                if attr_value is self:
                    if self.attr_name and attr_name != self.attr_name:
                        raise RuntimeError("StoredState shared by {}.{} and {}.{}".format(parent_type.__name__, self.attr_name, parent_type.__name__, attr_name))
                    self.attr_name = attr_name
                    bound = BoundStoredState(parent, attr_name)
                    parent.__dict__[attr_name] = bound
                    break
            else:
                raise RuntimeError("Cannot find StoredVariable attribute in type {}".format(parent_type.__name__))

        return bound

