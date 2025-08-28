#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Provide functionality to test ops.hookcmds.

Note that all use of the model and framework should be avoided here, in favour
of using the low-level ops.hookcmds module. This is *not* how charms should be
written!
"""

import logging

import ops
import ops.hookcmds as hookcmds

logger = logging.getLogger(__name__)


# TODO: Add something to trigger juju_reboot(). This cannot be done in an action.


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
        hookcmds.application_version_set("1.25.79")
        self.unit.status = ops.ActiveStatus()
        try:
            credentials = hookcmds.credential_get()
        except hookcmds.HookCommandError:
            hookcmds.juju_log("No credentials available (probably no trust, or K8s)")
        else:
            hookcmds.juju_log(f"Credentials: name={credentials.name}, type={credentials.type}")
        goal = hookcmds.goal_state()
        hookcmds.juju_log(f"Goal state: {goal!r}")
        hookcmds.juju_log(f"This unit is the leader: {hookcmds.is_leader()}")

    #    for relation in hookcmds.relation_list():  # TODO fix this
    #        hookcmds.juju_log(
    #            f"Relation: {relation!r}, network: {hookcmds.network_get(endpoint, relation_id)}"
    #        )

    def _on_open_port(self, event: ops.ActionEvent):
        """Handle open-port action."""
        protocol = event.params.get("protocol")
        port = event.params.get("port")
        args = {}
        if protocol:
            args["protocol"] = protocol
        if port:
            args["port"] = port
        hookcmds.open_port(**args)

    def _on_close_port(self, event: ops.ActionEvent):
        """Handle close-port action."""
        protocol = event.params.get("protocol")
        port = event.params.get("port")
        args = {}
        if protocol:
            args["protocol"] = protocol
        if port:
            args["port"] = port
        hookcmds.close_port(**args)

    def _on_opened_ports(self, event: ops.ActionEvent):
        """Handle opened-ports action."""
        opened_ports = hookcmds.get_opened_ports()
        event.set_results({"opened_ports": opened_ports})

    def _on_backup(self, event: ops.ActionEvent):
        params = hookcmds.action_get()
        location = params.get("backup-location")
        days = params.get("days", 0)
        hookcmds.action_log(f"Asked to backup {days} days of data to {location}")
        hookcmds.action_fail("Oh no, I failed!")
        hookcmds.action_set({"backup-location": location, "days+1": days + 1})

    def _on_config_changed(self, event: ops.ConfigChangedEvent):
        config = hookcmds.config_get(all=True)
        hookcmds.juju_log(f"New config: {config!r}", level="WARNING")

    def _on_peer_relation_changed(self, event: ops.RelationChangedEvent):
        data = hookcmds.relation_get()
        rlist = hookcmds.relation_list()
        model = hookcmds.relation_model_get()
        hookcmds.juju_log(f"Peer data: {data!r}, list: {rlist!r}, model: {model!r}")


if __name__ == "__main__":  # pragma: nocover
    ops.main(HookcmdsTester)
