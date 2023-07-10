# Copyright 2023 Canonical Ltd.
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

"""Multi-status test charm for OP035, using Framework.observe events."""

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
        self.harness.model._evaluate_status(self.harness.charm)
        status = self.harness.model.unit.status
        self.assertEqual(status.name, "blocked")
        self.assertEqual(status.message, '"database_mode" required')

    def test_database_mode_set(self):
        self.harness.update_config({"database_mode": "single"})
        self.harness.model._evaluate_status(self.harness.charm)
        status = self.harness.model.unit.status
        self.assertEqual(status.name, "blocked")
        self.assertEqual(status.message, '"webapp_port" required')

    def test_webapp_port_set(self):
        self.harness.update_config({"webapp_port": 8080})
        self.harness.model._evaluate_status(self.harness.charm)
        status = self.harness.model.unit.status
        self.assertEqual(status.name, "blocked")
        self.assertEqual(status.message, '"database_mode" required')

    def test_all_config_set(self):
        self.harness.update_config({"database_mode": "single", "webapp_port": 8080})
        self.harness.model._evaluate_status(self.harness.charm)
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


class Database(ops.Object):
    """Database component."""

    def __init__(self, charm: ops.CharmBase):
        super().__init__(charm, "database")
        self.framework.observe(charm.on.config_changed, self._on_config_changed)

        # Note that you can have multiple collect_status observers even
        # within a single component, as shown here. Alternatively, we could
        # do both of these tests within a single handler.
        # self.framework.observe(charm.on.collect_unit_status, self._on_collect_db_status)
        self.framework.observe(charm.on.collect_unit_status, self._on_collect_config_status)

    # def _on_collect_db_status(self, event: ops.CollectStatusEvent):
    #     if 'db' not in self.model.relations:
    #         event.add_status(ops.BlockedStatus('please integrate with database'))
    #         return
    #     event.add_status(ops.ActiveStatus())

    def _on_collect_config_status(self, event: ops.CollectStatusEvent):
        status = self._validate_config()
        if status is not None:
            event.add_status(status)
            return
        event.add_status(ops.ActiveStatus())

    def _validate_config(self) -> typing.Optional[ops.StatusBase]:
        """Validate charm config for the database component.

        Return a status if the config is incorrect, None if it's valid.
        """
        if "database_mode" not in self.model.config:
            return ops.BlockedStatus('"database_mode" required')
        return None

    def _on_config_changed(self, event):
        if self._validate_config() is not None:
            return
        mode = self.model.config["database_mode"]
        logger.info("Using database mode %r", mode)


class Webapp(ops.Object):
    """Web app component."""

    def __init__(self, charm: ops.CharmBase):
        super().__init__(charm, "webapp")
        self.framework.observe(charm.on.collect_unit_status, self._on_collect_status)
        self.framework.observe(charm.on.config_changed, self._on_config_changed)

    def _on_collect_status(self, event: ops.CollectStatusEvent):
        status = self._validate_config()
        if status is not None:
            event.add_status(status)
            return
        event.add_status(ops.ActiveStatus())

    def _validate_config(self) -> typing.Optional[ops.StatusBase]:
        """Validate charm config for the web app component.

        Return a status if the config is incorrect, None if it's valid.
        """
        if "webapp_port" not in self.model.config:
            return ops.BlockedStatus('"webapp_port" required')
        return None

    def _on_config_changed(self, event):
        if self._validate_config() is not None:
            return
        port = self.model.config["webapp_port"]
        logger.info("Using web app port %r", port)
