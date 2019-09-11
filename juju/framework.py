import pickle
import marshal
import types
import sqlite3


class Handle:
    """Handle defines a name for an object in the form of a hierarchical path.

    The handle context is the handle for the parent object that this handle
    sits under, or None if the object identified by this handle stands by
    itself.

    The handle kind is a string that defines a namespace so objects with the
    same context and kind will have unique keys.

    The handle key is a string uniquely identifying the object. No other objects
    under the same context and kind may have the same key.
    """

    def __init__(self, context, kind, key):
        if context and not isinstance(context, Handle):
            context = context.handle
        self.context = context
        self.kind = kind
        self.key = key

    def nest(self, kind, key):
        return Handle(self, kind, key)

    def __hash__(self):
        return hash((self.context, self.kind, self.key))

    def __eq__(self, other):
        return (self.context, self.kind, self.key) == (other.context, other.kind, other.key)

    def __str__(self):
        return self.path

    @property
    def path(self):
        # TODO Cache result and either clear cache when attributes change, or make it read-only.
        if self.context:
            if self.key:
                return f"{self.context}/{self.kind}:{self.key}"
            else:
                return f"{self.context}/{self.kind}"
        else:
            if self.key:
                return f"{self.kind}:{self.key}"
            else:
                return f"{self.kind}"

    @classmethod
    def from_path(cls, path):
        handle = None
        for pair in path.split("/"):
            pair = pair.split(":")
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

    emitter_type = None
    event_kind = None

    def __init__(self, event_type):
        if not isinstance(event_type, type) or not issubclass(event_type, EventBase):
            raise RuntimeError(f"Event requires a subclass of EventBase as an argument, got {event_type}")
        self.event_type = event_type

    def __get__(self, emitter, emitter_type=None):
        if self.emitter_type is None:
            for attr_name, attr_value in emitter_type.__dict__.items():
                if attr_value is self:
                    self.event_kind = attr_name
                    break
            else:
                raise RuntimeError("Cannot find Event({}) attribute in type {}".format(self.event_type.__name__, emitter_type.__name__))
            self.emitter_type = emitter_type
        elif self.emitter_type is not emitter_type:
            raise RuntimeError("Event field for {} shared by {} and {}".format(self.event_type.__name__, self.emitter_type.__name__, emitter_type.__name__))

        if emitter is None:
            return self
        return BoundEvent(emitter, self.event_type, self.event_kind)


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


class Object:

    def __init__(self, context=None, key=None):
        if isinstance(context, Framework):
            self.framework = context
            self.handle = Handle(None, type(self).__name__, key)
        else:
            self.framework = context.framework
            self.handle = Handle(context, type(self).__name__, key)

        # TODO Detect conflicting handles here.


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
        self._db.execute("INSERT INTO snapshot VALUES (?, ?)", (handle_path, snapshot_data))

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
        self._observers = [] # [(observer, method_name, context_path, event_key)]
        self._observer = {}  # {observer_path: observer}
        self._type_registry = {} # {(context_path, kind): cls}
        self._type_known = set() # {cls}

        self._storage = SQLiteStorage(data_path)

    def close(self):
        self._storage.close()

    def commit(self):
        self._storage.commit()

    def register_type(self, cls, context, kind):
        if context and not isinstance(context, Handle):
            context = context.handle
        if context:
            context_path = context.path
        else:
            context_path = None
        self._type_registry[(context_path, kind)] = cls
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
        context_path = None
        if handle.context:
            context_path = handle.context.path
        cls = self._type_registry.get((context_path, handle.kind))
        if not cls:
            # TODO Proper exception type here.
            raise RuntimeError(f"cannot restore {handle.path} since no class was registered for it")
        raw_data = self._storage.load_snapshot(handle.path)
        if not raw_data:
            raise NoSnapshotError(handle.path)
        data = pickle.loads(raw_data)
        obj = cls.__new__(cls)
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

        self._observer[observer.handle.path] = observer
        self._observers.append((observer.handle.path, method_name, emitter_path, event_kind))

    def _emit(self, event):
        """See BoundEvent.emit for the public way to call this."""

        # Save the event for all known observers before the first notification
        # takes place, so that either everyone interested sees it, or nobody does.
        self.save_snapshot(event)
        event_path = event.handle.path
        event_kind = event.handle.kind
        context_path = event.handle.context.path
        notices = []
        for observer_path, method_name, _context_path, _event_kind in self._observers:
            if _context_path != context_path:
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
            self.commit()
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
        self.commit()
