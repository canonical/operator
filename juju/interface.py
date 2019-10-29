from juju.framework import Event, EventsBase, Object
from juju.charm import (
    RelationJoinedEvent,
    RelationChangedEvent,
    RelationDepartedEvent,
    RelationBrokenEvent,
)


class Endpoint:
    def __init__(self, interface_type):
        self.interface_type = interface_type
        self.name = None

    def __set_name__(self, charm_type, name):
        self.name = name

    def __get__(self, charm, charm_type):
        if charm is None:
            return self
        else:
            interface = self.interface_type(charm, self.name)
            # Permanently bind the interface instance to the charm. Because Endpoint is a
            # descriptor and not a data descriptor (i.e., it does not define either __set__
            # or __delete__), the descriptor can be overridden on a per-instance basis,
            # meaning this method will no longer be invoked for that instance.
            charm.__setattr__(self.name, interface)
            return interface


class InterfaceEvents(EventsBase):
    joined = Event(RelationJoinedEvent)
    changed = Event(RelationChangedEvent)
    departed = Event(RelationDepartedEvent)
    broken = Event(RelationBrokenEvent)


class InterfaceBase(Object):
    on = InterfaceEvents

    def __init__(self, charm, name):
        super().__init__(charm, name)
        self.framework.observe(getattr(charm.on, f'{self.name}_relation_joined'), self.on.joined.emit)
        self.framework.observe(getattr(charm.on, f'{self.name}_relation_changed'), self.on.changed.emit)
        self.framework.observe(getattr(charm.on, f'{self.name}_relation_departed'), self.on.departed.emit)
        self.framework.observe(getattr(charm.on, f'{self.name}_relation_broken'), self.on.broken.emit)

    @property
    def name(self):
        return self.handle.key

    @property
    def relations(self):
        return self.framework.model.relations[self.name]
