import pathlib
import urllib.request
from io import StringIO
from typing import TYPE_CHECKING, Dict, Optional, Tuple, Union

from ops import pebble
from ops.model import _ModelBackend
from ops.pebble import Client, ExecError
from ops.testing import _TestingFilesystem, _TestingPebbleClient, _TestingStorageMount

from scenario.logger import logger as scenario_logger

if TYPE_CHECKING:
    from scenario.state import Container as ContainerSpec
    from scenario.state import Event, ExecOutput, State, _CharmSpec

logger = scenario_logger.getChild("mocking")


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

    def send_signal(self, sig: Union[int, str]):
        pass


class _MockModelBackend(_ModelBackend):
    def __init__(self, state: "State", event: "Event", charm_spec: "_CharmSpec"):
        super().__init__(state.unit_name, state.model.name, state.model.uuid)
        self._state = state
        self._event = event
        self._charm_spec = charm_spec

    def get_pebble(self, socket_path: str) -> "Client":
        return _MockPebbleClient(
            socket_path=socket_path,
            state=self._state,
            event=self._event,
            charm_spec=self._charm_spec,
        )

    def _get_relation_by_id(self, rel_id):
        try:
            return next(
                filter(lambda r: r.relation_id == rel_id, self._state.relations)
            )
        except StopIteration as e:
            raise RuntimeError(f"Not found: relation with id={rel_id}.") from e

    def relation_get(self, rel_id, obj_name, app):
        relation = self._get_relation_by_id(rel_id)
        if app and obj_name == self._state.app_name:
            return relation.local_app_data
        elif app:
            return relation.remote_app_data
        elif obj_name == self._state.unit_name:
            return relation.local_unit_data
        else:
            unit_id = obj_name.split("/")[-1]
            return relation.remote_units_data[int(unit_id)]

    def is_leader(self):
        return self._state.leader

    def status_get(self, *args, **kwargs):
        status, message = (
            self._state.status.app if kwargs.get("app") else self._state.status.unit
        )
        return {"status": status, "message": message}

    def relation_ids(self, endpoint, *args, **kwargs):
        return [
            rel.relation_id for rel in self._state.relations if rel.endpoint == endpoint
        ]

    def relation_list(self, rel_id, *args, **kwargs):
        relation = self._get_relation_by_id(rel_id)
        return tuple(
            f"{relation.remote_app_name}/{unit_id}"
            for unit_id in relation.remote_unit_ids
        )

    def config_get(self, *args, **kwargs):
        state_config = self._state.config
        if not state_config:
            state_config = {
                key: value.get("default")
                for key, value in self._charm_spec.config.items()
            }

        if args:  # one specific key requested
            # Fixme: may raise KeyError if the key isn't defaulted. What do we do then?
            return state_config[args[0]]

        return state_config  # full config

    def network_get(self, *args, **kwargs):
        name, relation_id = args

        network = next(filter(lambda r: r.name == name, self._state.networks))
        return network.hook_tool_output_fmt()

    def action_get(self, *args, **kwargs):
        raise NotImplementedError("action_get")

    def relation_remote_app_name(self, *args, **kwargs):
        raise NotImplementedError("relation_remote_app_name")

    def resource_get(self, *args, **kwargs):
        raise NotImplementedError("resource_get")

    def storage_list(self, *args, **kwargs):
        raise NotImplementedError("storage_list")

    def storage_get(self, *args, **kwargs):
        raise NotImplementedError("storage_get")

    def planned_units(self, *args, **kwargs):
        raise NotImplementedError("planned_units")

    # setter methods: these can mutate the state.
    def application_version_set(self, *args, **kwargs):
        self._state.status.app_version = args[0]
        return None

    def status_set(self, *args, **kwargs):
        if kwargs.get("is_app"):
            self._state.status.app = args
        else:
            self._state.status.unit = args
        return None

    def juju_log(self, *args, **kwargs):
        self._state.juju_log.append(args)
        return None

    def relation_set(self, *args, **kwargs):
        rel_id, key, value, app = args
        relation = self._get_relation_by_id(rel_id)
        if app:
            if not self._state.leader:
                raise RuntimeError("needs leadership to set app data")
            tgt = relation.local_app_data
        else:
            tgt = relation.local_unit_data
        tgt[key] = value
        return None

    # TODO:
    def action_set(self, *args, **kwargs):
        raise NotImplementedError("action_set")

    def action_fail(self, *args, **kwargs):
        raise NotImplementedError("action_fail")

    def action_log(self, *args, **kwargs):
        raise NotImplementedError("action_log")

    def storage_add(self, *args, **kwargs):
        raise NotImplementedError("storage_add")

    def secret_get(
        self,
        *,
        id: str = None,
        label: str = None,
        refresh: bool = False,
        peek: bool = False,
    ) -> Dict[str, str]:
        # cleanup id:
        if id and id.startswith("secret:"):
            id = id[7:]

        if id:
            try:
                secret = next(filter(lambda s: s.id == id, self._state.secrets))
            except StopIteration:
                raise RuntimeError(f"not found: secret with id={id}.")
        elif label:
            try:
                secret = next(filter(lambda s: s.label == label, self._state.secrets))
            except StopIteration:
                raise RuntimeError(f"not found: secret with label={label}.")
        else:
            raise RuntimeError(f"need id or label.")

        revision = secret.revision
        if peek or refresh:
            revision = max(secret.contents.keys())
            if refresh:
                secret.revision = revision

        return secret.contents[revision]

    def secret_set(self, *args, **kwargs):
        raise NotImplementedError("secret_set")

    def secret_grant(self, *args, **kwargs):
        raise NotImplementedError("secret_grant")

    def secret_remove(self, *args, **kwargs):
        raise NotImplementedError("secret_remove")


class _MockStorageMount(_TestingStorageMount):
    def __init__(self, location: pathlib.PurePosixPath, src: pathlib.Path):
        """Creates a new simulated storage mount.

        Args:
            location: The path within simulated filesystem at which this storage will be mounted.
            src: The temporary on-disk location where the simulated storage will live.
        """
        self._src = src
        self._location = location
        if (
            not src.exists()
        ):  # we need to add this guard because the directory might exist already.
            src.mkdir(exist_ok=True, parents=True)


# todo consider duplicating the filesystem on State.copy() to be able to diff and have true state snapshots
class _MockFileSystem(_TestingFilesystem):
    def __init__(self, mounts: Dict[str, _MockStorageMount]):
        super().__init__()
        self._mounts = mounts

    def add_mount(self, *args, **kwargs):
        raise NotImplementedError("Cannot mutate mounts; declare them all in State.")

    def remove_mount(self, *args, **kwargs):
        raise NotImplementedError("Cannot mutate mounts; declare them all in State.")


class _MockPebbleClient(_TestingPebbleClient):
    def __init__(
        self,
        socket_path: str,
        opener: Optional[urllib.request.OpenerDirector] = None,
        base_url: str = "http://localhost",
        timeout: float = 5.0,
        *,
        state: "State",
        event: "Event",
        charm_spec: "_CharmSpec",
    ):
        self._state = state
        self.socket_path = socket_path
        self._event = event
        self._charm_spec = charm_spec

    @property
    def _container(self) -> "ContainerSpec":
        container_name = self.socket_path.split("/")[-2]
        try:
            return next(
                filter(lambda x: x.name == container_name, self._state.containers)
            )
        except StopIteration:
            raise RuntimeError(
                f"container with name={container_name!r} not found. "
                f"Did you forget a Container, or is the socket path "
                f"{self.socket_path!r} wrong?"
            )

    @property
    def _fs(self):
        return self._container.filesystem

    @property
    def _layers(self) -> Dict[str, pebble.Layer]:
        return self._container.layers

    @property
    def _service_status(self) -> Dict[str, pebble.ServiceStatus]:
        return self._container.service_status

    def exec(self, *args, **kwargs):
        cmd = tuple(args[0])
        out = self._container.exec_mock.get(cmd)
        if not out:
            raise RuntimeError(f"mock for cmd {cmd} not found.")

        change_id = out._run()
        return _MockExecProcess(change_id=change_id, command=cmd, out=out)

    def _check_connection(self):
        if not self._container.can_connect:  # pyright: reportPrivateUsage=false
            msg = (
                f"Cannot connect to Pebble; did you forget to set "
                f"can_connect=True for container {self._container.name}?"
            )
            raise pebble.ConnectionError(msg)
