.. _ops_hookcmds:

`ops.hookcmds`
==============

Low-level access to the Juju hook commands.

Charm authors should use the :class:`ops.Model` (via ``self.model``) rather than
directly running the hook commands, where possible. This module is primarily
provided to help with developing charming alternatives to the Ops framework.

Note: ``hookcmds`` is not covered by the semver policy that applies to the rest
of Ops. We will do our best to avoid breaking changes, but we reserve the right
to make breaking changes within this package if necessary, within the Ops 3.x
series.

All methods are 1:1 mapping to Juju hook commands. This is a *low-level* API,
available for charm use, but expected to be used via higher-level wrappers.

See https://documentation.ubuntu.com/juju/3.6/reference/hook-command/ and
https://documentation.ubuntu.com/juju/3.6/reference/hook-command/list-of-hook-commands/
for a list of all Juju hook commands.

.. autoclass:: ops.hookcmds.Address
.. autoclass:: ops.hookcmds.AppStatus
.. autoclass:: ops.hookcmds.BindAddress
.. autoclass:: ops.hookcmds.Error
.. autoclass:: ops.hookcmds.Goal
.. autoclass:: ops.hookcmds.GoalState
.. autoclass:: ops.hookcmds.Network
.. autoclass:: ops.hookcmds.Port
.. autoclass:: ops.hookcmds.RelationModel
.. autoclass:: ops.hookcmds.SecretInfo
.. autoclass:: ops.hookcmds.SecretRotate
.. autoclass:: ops.hookcmds.SettableStatusName
.. autoclass:: ops.hookcmds.StatusName
.. autoclass:: ops.hookcmds.Storage
.. autoclass:: ops.hookcmds.UnitStatus
.. automethod:: ops.hookcmds.action_fail
.. automethod:: ops.hookcmds.action_get
.. automethod:: ops.hookcmds.action_log
.. automethod:: ops.hookcmds.action_set
.. automethod:: ops.hookcmds.app_version_set
.. automethod:: ops.hookcmds.close_port
.. automethod:: ops.hookcmds.config_get
.. automethod:: ops.hookcmds.credential_get
.. automethod:: ops.hookcmds.goal_state
.. automethod:: ops.hookcmds.is_leader
.. automethod:: ops.hookcmds.juju_log
.. automethod:: ops.hookcmds.juju_reboot
.. automethod:: ops.hookcmds.network_get
.. automethod:: ops.hookcmds.open_port
.. automethod:: ops.hookcmds.opened_ports
.. automethod:: ops.hookcmds.relation_get
.. automethod:: ops.hookcmds.relation_ids
.. automethod:: ops.hookcmds.relation_list
.. automethod:: ops.hookcmds.relation_model_get
.. automethod:: ops.hookcmds.relation_set
.. automethod:: ops.hookcmds.resource_get
.. automethod:: ops.hookcmds.secret_add
.. automethod:: ops.hookcmds.secret_get
.. automethod:: ops.hookcmds.secret_grant
.. automethod:: ops.hookcmds.secret_ids
.. automethod:: ops.hookcmds.secret_info_get
.. automethod:: ops.hookcmds.secret_remove
.. automethod:: ops.hookcmds.secret_revoke
.. automethod:: ops.hookcmds.secret_set
.. automethod:: ops.hookcmds.state_delete
.. automethod:: ops.hookcmds.state_get
.. automethod:: ops.hookcmds.state_set
.. automethod:: ops.hookcmds.status_get
.. automethod:: ops.hookcmds.status_set
.. automethod:: ops.hookcmds.storage_add
.. automethod:: ops.hookcmds.storage_get
.. automethod:: ops.hookcmds.storage_list
