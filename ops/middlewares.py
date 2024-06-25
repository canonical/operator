import typing
from abc import ABC

if typing.TYPE_CHECKING:
    from ops import CharmBase


class Middleware(ABC):
    """Ops middleware abstract base class.

    Can be used to define middlewares for the operator framework.
    Pass any subclass to ``ops.main.main(middlewares=[...])`` to apply the
    middleware to the charm execution.
    """

    def setup_class(self, charm_type: typing.Type["CharmBase"]):
        """Override this method to manipulate the charm type before it's instantiated."""

        # insert charm-type-hook code here

    def pre_init(self, charm: "CharmBase"):
        """Override this method to hook into the charm `__init__`.

        This will be called before any initialization beyond super() takes place.
        """

        # insert pre-charm-init code here


    def post_init(self, charm: "CharmBase"):
        """Override this method to hook into the charm `__init__`.

        This will be called after the charm's `__init__` has returned.
        """

        # insert post-charm-init-code here
