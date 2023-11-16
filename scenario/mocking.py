#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import datetime
import random
import shutil
from io import StringIO
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Mapping, Optional, Set, Tuple, Union

from ops import JujuVersion, pebble
from ops.model import (
    ModelError,
    RelationNotFoundError,
    SecretInfo,
    SecretNotFoundError,
    SecretRotate,
    _format_action_result_dict,
    _ModelBackend,
)
from ops.pebble import Client, ExecError
from ops.testing import _TestingPebbleClient

from scenario.logger import logger as scenario_logger
from scenario.state import JujuLogLine, Mount, PeerRelation, Port, Storage

if TYPE_CHECKING:
    from scenario.context import Context
    from scenario.state import Container as ContainerSpec
    from scenario.state import (
        Event,
        ExecOutput,
        Relation,
        State,
        SubordinateRelation,
        _CharmSpec,
    )

logger = scenario_logger.getChild("mocking")


class ActionMissingFromContextError(Exception):
    """Raised when the user attempts to invoke action hook tools outside an action context."""

    # This is not an ops error: in ops, you'd have to go exceptionally out of your way to trigger
    # this flow.


class _MockExecProcess:
    def __init__(self, command: Tuple[str], change_id: int, out: "ExecOutput"):
        self._command = command
        self._change_id = change_id
        self._out = out
        self._waited = False
        self.stdout = StringIO(self._out.stdout)
        self.stderr = StringIO(self._out.stderr)

    def wait(self):
        self._waited = True
        exit_code = self._out.return_code
        if exit_code != 0:
            raise ExecError(list(self._command), exit_code, None, None)

    def wait_output(self):
        out = self._out
        exit_code = out.return_code
        if exit_code != 0:
            raise ExecError(list(self._command), exit_code, None, None)
        return out.stdout, out.stderr

    def send_signal(self, sig: Union[int, str]):  # noqa: U100
        raise NotImplementedError()


_NOT_GIVEN = object()  # non-None default value sentinel


class _MockModelBackend(_ModelBackend):
    def __init__(
        self,
        state: "State",
        event: "Event",
        charm_spec: "_CharmSpec",
        context: "Context",
    ):
        super().__init__()
        self._state = state
        self._event = event
        self._context = context
        self._charm_spec = charm_spec

    def opened_ports(self) -> Set[Port]:
        return set(self._state.opened_ports)

    def open_port(self, protocol: str, port: Optional[int] = None):
        # fixme: the charm will get hit with a StateValidationError
        #  here, not the expected ModelError...
        port = Port(protocol, port)
        ports = self._state.opened_ports
        if port not in ports:
            ports.append(port)

    def close_port(self, protocol: str, port: Optional[int] = None):
        port = Port(protocol, port)
        ports = self._state.opened_ports
        if port in ports:
            ports.remove(port)

    def get_pebble(self, socket_path: str) -> "Client":
        container_name = socket_path.split("/")[
            3
        ]  # /charm/containers/<container_name>/pebble.socket
        container_root = self._context._get_container_root(container_name)
        try:
            mounts = self._state.get_container(container_name).mounts
        except ValueError:
            # container not defined in state.
            mounts = {}

        return _MockPebbleClient(
            socket_path=socket_path,
            container_root=container_root,
            mounts=mounts,
            state=self._state,
            event=self._event,
            charm_spec=self._charm_spec,
        )

    def _get_relation_by_id(
        self,
        rel_id,
    ) -> Union["Relation", "SubordinateRelation", "PeerRelation"]:
        try:
            return next(
                filter(lambda r: r.relation_id == rel_id, self._state.relations),
            )
        except StopIteration:
            raise RelationNotFoundError()

    def _get_secret(self, id=None, label=None):
        # cleanup id:
        if id and id.startswith("secret:"):
            id = id[7:]

        if id:
            try:
                return next(filter(lambda s: s.id == id, self._state.secrets))
            except StopIteration:
                raise SecretNotFoundError()
        elif label:
            try:
                return next(filter(lambda s: s.label == label, self._state.secrets))
            except StopIteration:
                raise SecretNotFoundError()
        else:
            # if all goes well, this should never be reached. ops.model.Secret will check upon
            # instantiation that either an id or a label are set, and raise a TypeError if not.
            raise RuntimeError("need id or label.")

    @staticmethod
    def _generate_secret_id():
        id = "".join(map(str, [random.choice(list(range(10))) for _ in range(20)]))
        return f"secret:{id}"

    def _check_app_data_access(self, is_app: bool):
        if not isinstance(is_app, bool):
            raise TypeError("is_app parameter to relation_get must be a boolean")

        if not is_app:
            return

        version = JujuVersion(self._context.juju_version)
        if not version.has_app_data():
            raise RuntimeError(
                f"setting application data is not supported on Juju version {version}",
            )

    def relation_get(self, relation_id: int, member_name: str, is_app: bool):
        self._check_app_data_access(is_app)
        relation = self._get_relation_by_id(relation_id)
        if is_app and member_name == self.app_name:
            return relation.local_app_data
        elif is_app:
            return relation.remote_app_data
        elif member_name == self.unit_name:
            return relation.local_unit_data

        unit_id = int(member_name.split("/")[-1])
        return relation._get_databag_for_remote(unit_id)  # noqa

    def is_leader(self):
        return self._state.leader

    def status_get(self, *, is_app: bool = False):
        status, message = self._state.app_status if is_app else self._state.unit_status
        return {"status": status, "message": message}

    def relation_ids(self, relation_name):
        return [
            rel.relation_id
            for rel in self._state.relations
            if rel.endpoint == relation_name
        ]

    def relation_list(self, relation_id: int) -> Tuple[str]:
        relation = self._get_relation_by_id(relation_id)

        if isinstance(relation, PeerRelation):
            return tuple(
                f"{self.app_name}/{unit_id}" for unit_id in relation.peers_data
            )
        return tuple(
            f"{relation.remote_app_name}/{unit_id}"
            for unit_id in relation._remote_unit_ids
        )

    def config_get(self):
        state_config = self._state.config

        # add defaults
        charm_config = self._charm_spec.config
        if not charm_config:
            return state_config

        for key, value in charm_config["options"].items():
            # if it has a default, and it's not overwritten from State, use it:
            if key not in state_config:
                default_value = value.get("default", _NOT_GIVEN)
                if default_value is not _NOT_GIVEN:  # accept False as default value
                    state_config[key] = default_value

        return state_config  # full config

    def network_get(self, binding_name: str, relation_id: Optional[int] = None):
        if relation_id:
            logger.warning("network-get -r not implemented")

        relations = self._state.get_relations(binding_name)
        if not relations:
            raise RelationNotFoundError()

        network = next(filter(lambda r: r.name == binding_name, self._state.networks))
        return network.hook_tool_output_fmt()

    # setter methods: these can mutate the state.
    def application_version_set(self, version: str):
        if workload_version := self._state.workload_version:
            # do not record if empty = unset
            self._context.workload_version_history.append(workload_version)

        self._state._update_workload_version(version)

    def status_set(self, status: str, message: str = "", *, is_app: bool = False):
        self._context._record_status(self._state, is_app)
        self._state._update_status(status, message, is_app)

    def juju_log(self, level: str, message: str):
        self._context.juju_log.append(JujuLogLine(level, message))

    def relation_set(self, relation_id: int, key: str, value: str, is_app: bool):
        self._check_app_data_access(is_app)
        relation = self._get_relation_by_id(relation_id)
        if is_app:
            if not self._state.leader:
                # will in practice not be reached because RelationData will check leadership
                # and raise RelationDataAccessError upstream on this path
                raise RuntimeError("needs leadership to set app data")
            tgt = relation.local_app_data
        else:
            tgt = relation.local_unit_data
        tgt[key] = value
        return None

    def secret_add(
        self,
        content: Dict[str, str],
        *,
        label: Optional[str] = None,
        description: Optional[str] = None,
        expire: Optional[datetime.datetime] = None,
        rotate: Optional[SecretRotate] = None,
        owner: Optional[str] = None,
    ) -> str:
        from scenario.state import Secret

        id = self._generate_secret_id()
        secret = Secret(
            id=id,
            contents={0: content},
            label=label,
            description=description,
            expire=expire,
            rotate=rotate,
            owner=owner,
        )
        self._state.secrets.append(secret)
        return id

    def secret_get(
        self,
        *,
        id: str = None,
        label: str = None,
        refresh: bool = False,
        peek: bool = False,
    ) -> Dict[str, str]:
        secret = self._get_secret(id, label)
        revision = secret.revision
        if peek or refresh:
            revision = max(secret.contents.keys())
            if refresh:
                secret._set_revision(revision)

        return secret.contents[revision]

    def secret_info_get(
        self,
        *,
        id: Optional[str] = None,
        label: Optional[str] = None,
    ) -> SecretInfo:
        secret = self._get_secret(id, label)
        if not secret.owner:
            raise RuntimeError(f"not the owner of {secret}")

        return SecretInfo(
            id=secret.id,
            label=secret.label,
            revision=max(secret.contents),
            expires=secret.expire,
            rotation=secret.rotate,
            rotates=None,  # not implemented yet.
        )

    def secret_set(
        self,
        id: str,
        *,
        content: Optional[Dict[str, str]] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        expire: Optional[datetime.datetime] = None,
        rotate: Optional[SecretRotate] = None,
    ):
        secret = self._get_secret(id, label)
        if not secret.owner:
            raise RuntimeError(f"not the owner of {secret}")

        secret._update_metadata(
            content=content,
            label=label,
            description=description,
            expire=expire,
            rotate=rotate,
        )

    def secret_grant(self, id: str, relation_id: int, *, unit: Optional[str] = None):
        secret = self._get_secret(id)
        if not secret.owner:
            raise RuntimeError(f"not the owner of {secret}")

        grantee = unit or self._get_relation_by_id(relation_id).remote_app_name

        if not secret.remote_grants.get(relation_id):
            secret.remote_grants[relation_id] = set()

        secret.remote_grants[relation_id].add(grantee)

    def secret_revoke(self, id: str, relation_id: int, *, unit: Optional[str] = None):
        secret = self._get_secret(id)
        if not secret.owner:
            raise RuntimeError(f"not the owner of {secret}")

        grantee = unit or self._get_relation_by_id(relation_id).remote_app_name
        secret.remote_grants[relation_id].remove(grantee)

    def secret_remove(self, id: str, *, revision: Optional[int] = None):
        secret = self._get_secret(id)
        if not secret.owner:
            raise RuntimeError(f"not the owner of {secret}")

        if revision:
            del secret.contents[revision]
        else:
            secret.contents.clear()

    def relation_remote_app_name(self, relation_id: int) -> Optional[str]:
        # ops catches relationnotfounderrors and returns None:
        try:
            relation = self._get_relation_by_id(relation_id)
        except RelationNotFoundError:
            return None
        return relation.remote_app_name

    def action_set(self, results: Dict[str, Any]):
        if not self._event.action:
            raise ActionMissingFromContextError(
                "not in the context of an action event: cannot action-set",
            )
        # let ops validate the results dict
        _format_action_result_dict(results)
        # but then we will store it in its unformatted,
        # original form for testing ease
        self._context._action_results = results

    def action_fail(self, message: str = ""):
        if not self._event.action:
            raise ActionMissingFromContextError(
                "not in the context of an action event: cannot action-fail",
            )
        self._context._action_failure = message

    def action_log(self, message: str):
        if not self._event.action:
            raise ActionMissingFromContextError(
                "not in the context of an action event: cannot action-log",
            )
        self._context._action_logs.append(message)

    def action_get(self):
        action = self._event.action
        if not action:
            raise ActionMissingFromContextError(
                "not in the context of an action event: cannot action-get",
            )
        return action.params

    def storage_add(self, name: str, count: int = 1):
        if not isinstance(count, int) or isinstance(count, bool):
            raise TypeError(
                f"storage count must be integer, got: {count} ({type(count)})",
            )

        if "/" in name:
            # this error is raised by ops.testing but not by ops at runtime
            raise ModelError('storage name cannot contain "/"')

        self._context.requested_storages[name] = count

    def storage_list(self, name: str) -> List[int]:
        return [
            storage.index for storage in self._state.storage if storage.name == name
        ]

    def _storage_event_details(self) -> Tuple[int, str]:
        storage = self._event.storage
        if not storage:
            # only occurs if this method is called when outside the scope of a storage event
            raise RuntimeError('unable to find storage key in ""')
        fs_path = storage.get_filesystem(self._context)
        return storage.index, str(fs_path)

    def storage_get(self, storage_name_id: str, attribute: str) -> str:
        if not len(attribute) > 0:  # assume it's an empty string.
            raise RuntimeError(
                'calling storage_get with `attribute=""` will return a dict '
                "and not a string. This usage is not supported.",
            )

        if attribute != "location":
            # this should not happen: in ops it's hardcoded to be "location"
            raise NotImplementedError(
                f"storage-get not implemented for attribute={attribute}",
            )

        name, index = storage_name_id.split("/")
        index = int(index)
        storages: List[Storage] = [
            s for s in self._state.storage if s.name == name and s.index == index
        ]

        # should not really happen: sanity checks. In practice, ops will guard against these paths.
        if not storages:
            raise RuntimeError(f"Storage with name={name} and index={index} not found.")
        if len(storages) > 1:
            raise RuntimeError(
                f"Multiple Storage instances with name={name} and index={index} found. "
                f"Inconsistent state.",
            )

        storage = storages[0]
        fs_path = storage.get_filesystem(self._context)
        return str(fs_path)

    def planned_units(self) -> int:
        return self._state.planned_units

    # legacy ops API that we don't intend to mock:
    def pod_spec_set(
        self,
        spec: Mapping[str, Any],  # noqa: U100
        k8s_resources: Optional[Mapping[str, Any]] = None,  # noqa: U100
    ):
        raise NotImplementedError(
            "pod-spec-set is not implemented in Scenario (and probably never will be: "
            "it's deprecated API)",
        )

    def add_metrics(
        self,
        metrics: Mapping[str, Union[int, float]],  # noqa: U100
        labels: Optional[Mapping[str, str]] = None,  # noqa: U100
    ) -> None:
        raise NotImplementedError(
            "add-metrics is not implemented in Scenario (and probably never will be: "
            "it's deprecated API)",
        )

    def resource_get(self, resource_name: str) -> str:
        try:
            return str(self._state.resources[resource_name])
        except KeyError:
            # ops will not let us get there if the resource name is unknown from metadata.
            # but if the user forgot to add it in State, then we remind you of that.
            raise RuntimeError(
                f"Inconsistent state: "
                f"resource {resource_name} not found in State. please pass it.",
            )


class _MockPebbleClient(_TestingPebbleClient):
    def __init__(
        self,
        socket_path: str,
        container_root: Path,
        mounts: Dict[str, Mount],
        *,
        state: "State",
        event: "Event",
        charm_spec: "_CharmSpec",
    ):
        self._state = state
        self.socket_path = socket_path
        self._event = event
        self._charm_spec = charm_spec

        # wipe just in case
        if container_root.exists():
            # Path.rmdir will fail if root is nonempty
            shutil.rmtree(container_root)

        # initialize simulated filesystem
        container_root.mkdir(parents=True)
        for _, mount in mounts.items():
            mounting_dir = container_root / mount.location[1:]
            mounting_dir.parent.mkdir(parents=True, exist_ok=True)
            mounting_dir.symlink_to(mount.src)

        self._root = container_root

    def get_plan(self) -> pebble.Plan:
        return self._container.plan

    @property
    def _container(self) -> "ContainerSpec":
        container_name = self.socket_path.split("/")[-2]
        try:
            return next(
                filter(lambda x: x.name == container_name, self._state.containers),
            )
        except StopIteration:
            raise RuntimeError(
                f"container with name={container_name!r} not found. "
                f"Did you forget a Container, or is the socket path "
                f"{self.socket_path!r} wrong?",
            )

    @property
    def _layers(self) -> Dict[str, pebble.Layer]:
        return self._container.layers

    @property
    def _service_status(self) -> Dict[str, pebble.ServiceStatus]:
        return self._container.service_status

    def exec(self, *args, **kwargs):  # noqa: U100
        cmd = tuple(args[0])
        out = self._container.exec_mock.get(cmd)
        if not out:
            raise RuntimeError(
                f"mock for cmd {cmd} not found. Please pass to the Container "
                f"{self._container.name} a scenario.ExecOutput mock for the "
                f"command your charm is attempting to run, or patch "
                f"out whatever leads to the call.",
            )

        change_id = out._run()
        return _MockExecProcess(change_id=change_id, command=cmd, out=out)

    def _check_connection(self):
        if not self._container.can_connect:  # pyright: reportPrivateUsage=false
            msg = (
                f"Cannot connect to Pebble; did you forget to set "
                f"can_connect=True for container {self._container.name}?"
            )
            raise pebble.ConnectionError(msg)
