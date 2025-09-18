#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide functionality to test ops.hookcmds.

Note that all use of the model and framework should be avoided here, in favour
of using the low-level ops.hookcmds module. This is *not* how charms should be
written!
"""

import dataclasses
import logging

import ops
import ops.hookcmds as hookcmds

logger = logging.getLogger(__name__)


class HookcmdsTester(ops.CharmBase):
    """Charm the application."""

    def __init__(self, framework: ops.Framework):
        super().__init__(framework)
        framework.observe(self.on["open-port"].action, self._on_open_port)
        framework.observe(self.on["close-port"].action, self._on_close_port)
        framework.observe(self.on["opened-ports"].action, self._on_opened_ports)
        framework.observe(self.on["backup"].action, self._on_backup)
        framework.observe(self.on.config_changed, self._on_config_changed)
        framework.observe(self.on["peer"].relation_changed, self._on_peer_relation_changed)
        framework.observe(self.on["test-status"].action, self._on_test_status)
        framework.observe(self.on["test-state"].action, self._on_test_state)
        framework.observe(self.on["test-secrets"].action, self._on_test_secrets)
        framework.observe(self.on["get-storage"].action, self._on_get_storage)
        framework.observe(self.on["add-storage"].action, self._on_add_storage)
        framework.observe(self.on["set-peer-data"].action, self._on_set_peer_data)
        hookcmds.application_version_set("1.25.79")
        self.unit.status = ops.ActiveStatus()
        try:
            credentials = hookcmds.credential_get()
        except hookcmds.Error:
            hookcmds.juju_log("No credentials available (probably no trust, or K8s)")
        else:
            hookcmds.juju_log(f"Credentials: name={credentials.name}, type={credentials.type}")
        goal = hookcmds.goal_state()
        hookcmds.juju_log(f"Goal state: {goal!r}")
        hookcmds.juju_log(f"This unit is the leader: {hookcmds.is_leader()}")
        try:
            hookcmds.secret_get(label="test-secret")
        except hookcmds.Error:
            # We assume this means that the secret doesn't exist.
            hookcmds.secret_add({"foo": "bar"}, label="test-secret")

    def _on_open_port(self, event: ops.ActionEvent):
        """Handle open-port action."""
        params = hookcmds.action_get()
        protocol = params.get("protocol")
        port = params.get("port")
        args = {}
        if protocol:
            args["protocol"] = protocol
        if port:
            args["port"] = port
        hookcmds.open_port(**args)

    def _on_close_port(self, event: ops.ActionEvent):
        """Handle close-port action."""
        params = hookcmds.action_get()
        protocol = params.get("protocol")
        port = params.get("port")
        args = {}
        if protocol:
            args["protocol"] = protocol
        if port:
            args["port"] = port
        hookcmds.close_port(**args)

    def _on_opened_ports(self, event: ops.ActionEvent):
        """Handle opened-ports action."""
        opened_ports = hookcmds.opened_ports()
        event.set_results({"opened_ports": opened_ports})

    def _on_backup(self, event: ops.ActionEvent):
        params = hookcmds.action_get()
        location = params.get("backup-location")
        days = params.get("days", 0)
        hookcmds.action_log(f"Asked to backup {days} days of data to {location}")
        hookcmds.action_fail("Oh no, I failed!")
        hookcmds.action_set({"backup-location": location, "days-plus-one": days + 1})

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        config: dict[str, bool | int | float | str] = dict(hookcmds.config_get())
        hookcmds.juju_log(f"New config: {list(config.items())}", level="WARNING")
        if config.get("crash"):
            raise RuntimeError("Crash requested by config")

    def _on_peer_relation_changed(self, event: ops.RelationChangedEvent):
        data = hookcmds.relation_get()
        rlist = hookcmds.relation_list()
        model = hookcmds.relation_model_get()
        hookcmds.juju_log(f"Peer data: {data!r}, list: {rlist!r}, model: {model!r}")

    def _on_test_status(self, event: ops.ActionEvent):
        original_status = hookcmds.status_get()
        hookcmds.status_set("active", "Status set by test-status")
        new_status = hookcmds.status_get()
        event.set_results({
            "original_status": original_status.status,
            "new_status": new_status.status,
        })

    def _on_test_state(self, event: ops.ActionEvent):
        params = hookcmds.action_get()
        value = params.get("value")
        if value and value != "delete":
            hookcmds.state_set({"foo": value})
            return
        if value == "delete":
            hookcmds.state_delete("foo")
            return
        value = hookcmds.state_get("foo")
        event.set_results({"value": value})
        return

    def _on_test_secrets(self, event: ops.ActionEvent):
        secrets = [
            (dataclasses.asdict(hookcmds.secret_info_get(id=id)), hookcmds.secret_get(id=id))
            for id in hookcmds.secret_ids()
        ]
        event.set_results({"secrets": secrets})

    def _on_get_storage(self, event: ops.ActionEvent):
        storages = [
            dataclasses.asdict(hookcmds.storage_get(store)) for store in hookcmds.storage_list()
        ]
        event.set_results({"storages": storages})

    def _on_add_storage(self, event: ops.ActionEvent):
        params = hookcmds.action_get()
        count = params.get("count", 1)
        hookcmds.storage_add("cache", count=count)

    def _on_set_peer_data(self, event: ops.ActionEvent):
        params = hookcmds.action_get()
        rels = hookcmds.relation_ids("peer")
        if rels:
            id = int(rels[0].rsplit(":", 1)[1])
            hookcmds.relation_set({"data": params["data"]}, id=id)


if __name__ == "__main__":  # pragma: nocover
    ops.main(HookcmdsTester)
