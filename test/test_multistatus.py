"""Multi-status test charm for OP035, using Framework.observe events instead
of regular Python functions.
"""

import logging
import typing
import unittest

import ops
import ops.testing


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = ops.testing.Harness(StatustestCharm, config="""
options:
  database_mode:
    description: "Database mode"
    type: "string"
  webapp_port:
    description: "Web app port"
    type: "int"
        """)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_initial(self):
        self.harness.framework.on.commit.emit()
        status = self.harness.model.unit.status
        self.assertEqual(status.name, "blocked")
        self.assertEqual(status.message, '"database_mode" required')

    def test_database_mode_set(self):
        self.harness.update_config({"database_mode": "single"})
        self.harness.framework.on.commit.emit()
        status = self.harness.model.unit.status
        self.assertEqual(status.name, "blocked")
        self.assertEqual(status.message, '"webapp_port" required')

    def test_webapp_port_set(self):
        self.harness.update_config({"webapp_port": 8080})
        self.harness.framework.on.commit.emit()
        status = self.harness.model.unit.status
        self.assertEqual(status.name, "blocked")
        self.assertEqual(status.message, '"database_mode" required')

    def test_all_config_set(self):
        self.harness.update_config({"database_mode": "single", "webapp_port": 8080})
        self.harness.framework.on.commit.emit()
        status = self.harness.model.unit.status
        self.assertEqual(status.name, "active")


# ------------------------------------------------------------------
# This is the test charm taken from the StatusPrioritiser test at
# https://github.com/benhoyt/test-charms/blob/statustest-stateless/statustest/src/charm.py
# but with the Prioritiser replaced with framework.on.get_status events.

logger = logging.getLogger(__name__)


class StatustestCharm(ops.CharmBase):
    """Status test charm."""

    def __init__(self, *args):
        super().__init__(*args)
        self.database = Database(self)
        self.webapp = Webapp(self)

        # This (and the code inside _on_commit) would probably be done in
        # the ops library automatically.
        self.framework.observe(self.framework.on.commit, self._on_commit)

    def _on_commit(self, event):
        statuses = self.framework.on.get_status.emit()
        priorities = {
            "error": 100,
            "blocked": 90,
            "waiting": 80,
            "maintenance": 70,
            "active": 60,
        }
        highest = max(statuses, key=lambda s: priorities.get(s.name, 0))
        self.unit.status = highest


class Database(ops.Object):
    """Database component."""

    def __init__(self, charm: ops.CharmBase):
        super().__init__(charm, "database")
        self.charm = charm

        # Note that get_status is framework.on.get_status rather than
        # charm.on.get_status as it's purely a framework concern, not a Juju event.
        charm.framework.observe(charm.framework.on.get_status, self._on_get_status)

        charm.framework.observe(charm.on.config_changed, self._on_config_changed)

    def _on_get_status(self, event) -> ops.StatusBase:
        """Return this component's status."""
        status = self._validate_config()
        return status if status is not None else ops.ActiveStatus()

    def _validate_config(self) -> typing.Optional[ops.StatusBase]:
        """Validate charm config for the database component.

        Return a status if the config is incorrect, None if it's valid.
        """
        if "database_mode" not in self.charm.model.config:
            return ops.BlockedStatus('"database_mode" required')
        return None

    def _on_config_changed(self, event):
        if self._validate_config() is not None:
            return
        mode = self.charm.model.config["database_mode"]
        logger.info("Using database mode %r", mode)


class Webapp(ops.Object):
    """Web app component."""

    def __init__(self, charm):
        super().__init__(charm, "webapp")
        self.charm = charm
        charm.framework.observe(charm.framework.on.get_status, self._on_get_status)
        charm.framework.observe(charm.on.config_changed, self._on_config_changed)

    def _on_get_status(self, event) -> ops.StatusBase:
        """Return this component's status."""
        status = self._validate_config()
        return status if status is not None else ops.ActiveStatus()

    def _validate_config(self) -> typing.Optional[ops.StatusBase]:
        """Validate charm config for the web app component.

        Return a status if the config is incorrect, None if it's valid.
        """
        if "webapp_port" not in self.charm.model.config:
            return ops.BlockedStatus('"webapp_port" required')
        return None

    def _on_config_changed(self, event):
        if self._validate_config() is not None:
            return
        port = self.charm.model.config["webapp_port"]
        logger.info("Using web app port %r", port)
