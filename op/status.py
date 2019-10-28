from abc import ABC

class Status(ABC):
    """Status values specific to applications and units."""

    _statuses = {}

    def __init__(self, message=''):
        self.message = message

    def __new__(cls, *args, **kwargs):
        if cls is Status:
            raise TypeError("cannot instantiate a base class")

        return super().__new__(cls)

    @classmethod
    def _register_status(cls, name, type_):
        """For use by subclasses only."""
        cls._statuses[name] = type_

    @classmethod
    def from_string(cls, name, message):
        return cls._statuses[name](message)

    def __init_subclass__(cls):
        super().__init_subclass__()
        Status._register_status(cls.name, cls)

class Active(Status):
    """The unit believes it is correctly offering all the services it has been asked to offer."""
    name = 'active'

class Blocked(Status):
    """The unit needs manual intervention to get back to the Running state."""
    name = 'blocked'

class Maintenance(Status):
    """
    The unit is not yet providing services, but is actively doing work in preparation for providing those services.
    This is a "spinning" state, not an error state. It reflects activity on the unit itself, not on peers or related units.
    """
    name = 'maintenance'

class Unknown(Status):
    """A unit-agent has finished calling install, config-changed and start, but the charm has not called status-set yet."""
    name = 'unknown'

    def __init__(self, message=''):
        # Unknown status cannot be set and does not have a message associated with it.
        super().__init__('')

class Waiting(Status):
    """The unit is unable to progress to an active state because an application to which it is related is not running."""
    name = 'waiting'
