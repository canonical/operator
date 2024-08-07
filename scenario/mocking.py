#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
import datetime
import shutil
from io import StringIO
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    Mapping,
    Optional,
    Set,
    Tuple,
    Union,
    cast,
)

from ops import JujuVersion, pebble
from ops.model import CloudSpec as CloudSpec_Ops
from ops.model import ModelError
from ops.model import Port as Port_Ops
from ops.model import RelationNotFoundError
from ops.model import Secret as Secret_Ops  # lol
from ops.model import (
    SecretInfo,
    SecretNotFoundError,
    SecretRotate,
    _format_action_result_dict,
    _ModelBackend,
)
from ops.pebble import Client, ExecError
from ops.testing import _TestingPebbleClient

from scenario.logger import logger as scenario_logger
from scenario.state import (
    JujuLogLine,
    Mount,
    Network,
    PeerRelation,
    Storage,
    _EntityStatus,
    _port_cls_by_protocol,
    _RawPortProtocolLiteral,
    _RawStatusLiteral,
)

if TYPE_CHECKING:  # pragma: no cover
    from scenario.context import Context
    from scenario.state import Container as ContainerSpec
    from scenario.state import (
        ExecOutput,
        Relation,
        Secret,
        State,
        SubordinateRelation,
        _CharmSpec,
        _Event,
    )

logger = scenario_logger.getChild("mocking")


class ActionMissingFromContextError(Exception):
    """Raised when the user attempts to invoke action hook tools outside an action context."""

    # This is not an ops error: in ops, you'd have to go exceptionally out of your way to trigger
    # this flow.


class _MockExecProcess:
    def __init__(self, command: Tuple[str, ...], change_id: int, out: "ExecOutput"):
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


# pyright: reportIncompatibleMethodOverride=false
class _MockModelBackend(_ModelBackend):
    def __init__(
        self,
        state: "State",
        event: "_Event",
        charm_spec: "_CharmSpec",
        context: "Context",
    ):
        super().__init__()
        self._state = state
        self._event = event
        self._context = context
        self._charm_spec = charm_spec

    def opened_ports(self) -> Set[Port_Ops]:
        return {
            Port_Ops(protocol=port.protocol, port=port.port)
            for port in self._state.opened_ports
        }

    def open_port(
        self,
        protocol: "_RawPortProtocolLiteral",  # pyright: ignore[reportIncompatibleMethodOverride]
        port: Optional[int] = None,
    ):
        # fixme: the charm will get hit with a StateValidationError
        #  here, not the expected ModelError...
        port_ = _port_cls_by_protocol[protocol](port=port)
        ports = set(self._state.opened_ports)
        if port_ not in ports:
            ports.add(port_)
        if ports != self._state.opened_ports:
            self._state._update_opened_ports(frozenset(ports))

    def close_port(
        self,
        protocol: "_RawPortProtocolLiteral",
        port: Optional[int] = None,
    ):
        _port = _port_cls_by_protocol[protocol](port=port)
        ports = set(self._state.opened_ports)
        if _port in ports:
            ports.remove(_port)
        if ports != self._state.opened_ports:
            self._state._update_opened_ports(frozenset(ports))

    def get_pebble(self, socket_path: str) -> "Client":
        container_name = socket_path.split("/")[
            3
        ]  # /charm/containers/<container_name>/pebble.socket
        container_root = self._context._get_container_root(container_name)
        try:
            mounts = self._state.get_container(container_name).mounts
        except KeyError:
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
            return self._state.get_relation(rel_id)
        except ValueError:
            raise RelationNotFoundError() from None

    def _get_secret(self, id=None, label=None):
        # FIXME: what error would a charm get IRL?
        # ops 2.0 supports secrets, but juju only supports it from 3.0.2
        if self._context.juju_version < "3.0.2":
            raise RuntimeError(
                "secrets are only available in juju >= 3.0.2."
                "Set ``Context.juju_version`` to 3.0.2+ to use them.",
            )

        canonicalize_id = Secret_Ops._canonicalize_id

        if id:
            # in scenario, you can create Secret(id="foo"),
            # but ops.Secret will prepend a "secret:" prefix to that ID.
            # we allow getting secret by either version.
            secrets = [
                s
                for s in self._state.secrets
                if canonicalize_id(s.id) == canonicalize_id(id)
            ]
            if not secrets:
                raise SecretNotFoundError(id)
            return secrets[0]

        elif label:
            try:
                return self._state.get_secret(label=label)
            except KeyError:
                raise SecretNotFoundError(label) from None

        else:
            # if all goes well, this should never be reached. ops.model.Secret will check upon
            # instantiation that either an id or a label are set, and raise a TypeError if not.
            raise RuntimeError("need id or label.")

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
            if isinstance(relation, PeerRelation):
                return relation.local_app_data
            return relation.remote_app_data
        elif member_name == self.unit_name:
            return relation.local_unit_data

        unit_id = int(member_name.split("/")[-1])
        return relation._get_databag_for_remote(unit_id)  # noqa

    def is_leader(self):
        return self._state.leader

    def status_get(self, *, is_app: bool = False):
        status = self._state.app_status if is_app else self._state.unit_status
        return {"status": status.name, "message": status.message}

    def relation_ids(self, relation_name):
        return [
            rel.id for rel in self._state.relations if rel.endpoint == relation_name
        ]

    def relation_list(self, relation_id: int) -> Tuple[str, ...]:
        relation = self._get_relation_by_id(relation_id)

        if isinstance(relation, PeerRelation):
            return tuple(
                f"{self.app_name}/{unit_id}" for unit_id in relation.peers_data
            )
        remote_name = self.relation_remote_app_name(relation_id)
        return tuple(
            f"{remote_name}/{unit_id}" for unit_id in relation._remote_unit_ids
        )

    def config_get(self):
        state_config = self._state.config.copy()  # dedup or we'll mutate the state!

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
        # validation:
        extra_bindings = self._charm_spec.meta.get("extra-bindings", ())
        all_endpoints = self._charm_spec.get_all_relations()
        non_sub_relations = {
            name for name, meta in all_endpoints if meta.get("scope") != "container"
        }

        # - is binding_name a valid binding name?
        if binding_name in extra_bindings:
            logger.warning("extra-bindings is a deprecated feature")  # fyi

            # - verify that if the binding is an extra binding, we're not ignoring a relation_id
            if relation_id is not None:
                # this should not happen
                logger.error(
                    "cannot pass relation_id to network_get if the binding name is "
                    "that of an extra-binding. Extra-bindings are not mapped to relation IDs.",
                )
        elif binding_name == "juju-info":
            # implicit relation that always exists
            pass
        # - verify that the binding is a relation endpoint name, but not a subordinate one
        elif binding_name not in non_sub_relations:
            logger.error(
                f"cannot get network binding for {binding_name}: is not a valid relation "
                f"endpoint name nor an extra-binding.",
            )
            raise RelationNotFoundError()

        # We look in State.networks for an override. If not given, we return a default network.
        try:
            network = self._state.get_network(binding_name)
        except KeyError:
            network = Network("default")  # The name is not used in the output.
        return network.hook_tool_output_fmt()

    # setter methods: these can mutate the state.
    def application_version_set(self, version: str):
        if workload_version := self._state.workload_version:
            # do not record if empty = unset
            self._context.workload_version_history.append(workload_version)

        self._state._update_workload_version(version)

    def status_set(
        self,
        status: _RawStatusLiteral,
        message: str = "",
        *,
        is_app: bool = False,
    ):
        self._context._record_status(self._state, is_app)
        status_obj = _EntityStatus.from_status_name(status, message)
        self._state._update_status(status_obj, is_app)

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
        owner: Optional[Literal["unit", "app"]] = None,
    ) -> str:
        from scenario.state import Secret

        secret = Secret(
            content,
            label=label,
            description=description,
            expire=expire,
            rotate=rotate,
            owner=owner,
        )
        secrets = set(self._state.secrets)
        secrets.add(secret)
        self._state._update_secrets(frozenset(secrets))
        return secret.id

    def _check_can_manage_secret(
        self,
        secret: "Secret",
    ):
        if secret.owner is None:
            raise SecretNotFoundError(
                "this secret is not owned by this unit/app or granted to it. "
                "Did you forget passing it to State.secrets?",
            )
        if secret.owner == "app" and not self.is_leader():
            understandable_error = SecretNotFoundError(
                f"App-owned secret {secret.id!r} can only be "
                f"managed by the leader.",
            )
            # charm-facing side: respect ops error
            raise ModelError("ERROR permission denied") from understandable_error

    def secret_get(
        self,
        *,
        id: Optional[str] = None,
        label: Optional[str] = None,
        refresh: bool = False,
        peek: bool = False,
    ) -> Dict[str, str]:
        secret = self._get_secret(id, label)
        juju_version = self._context.juju_version
        if not (juju_version == "3.1.7" or juju_version >= "3.3.1"):
            # In this medieval Juju chapter,
            # secret owners always used to track the latest revision.
            # ref: https://bugs.launchpad.net/juju/+bug/2037120
            if secret.owner is not None:
                refresh = True

        if peek or refresh:
            if refresh:
                secret._track_latest_revision()
            assert secret.latest_content is not None
            return secret.latest_content

        return secret.tracked_content

    def secret_info_get(
        self,
        *,
        id: Optional[str] = None,
        label: Optional[str] = None,
    ) -> SecretInfo:
        secret = self._get_secret(id, label)

        # only "manage"=write access level can read secret info
        self._check_can_manage_secret(secret)

        return SecretInfo(
            id=secret.id,
            label=secret.label,
            revision=secret._latest_revision,
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
        self._check_can_manage_secret(secret)

        if content == secret.latest_content:
            # In Juju 3.6 and higher, this is a no-op, but it's good to warn
            # charmers if they are doing this, because it's not generally good
            # practice.
            # https://bugs.launchpad.net/juju/+bug/2069238
            logger.warning(
                f"secret {id} contents set to the existing value: new revision not needed",
            )

        secret._update_metadata(
            content=content,
            label=label,
            description=description,
            expire=expire,
            rotate=rotate,
        )

    def secret_grant(self, id: str, relation_id: int, *, unit: Optional[str] = None):
        secret = self._get_secret(id)
        self._check_can_manage_secret(secret)

        grantee = unit or self.relation_remote_app_name(
            relation_id,
            _raise_on_error=True,
        )

        if not secret.remote_grants.get(relation_id):
            secret.remote_grants[relation_id] = set()

        secret.remote_grants[relation_id].add(cast(str, grantee))

    def secret_revoke(self, id: str, relation_id: int, *, unit: Optional[str] = None):
        secret = self._get_secret(id)
        self._check_can_manage_secret(secret)

        grantee = unit or self.relation_remote_app_name(
            relation_id,
            _raise_on_error=True,
        )
        secret.remote_grants[relation_id].remove(cast(str, grantee))
        if not secret.remote_grants[relation_id]:
            del secret.remote_grants[relation_id]

    def secret_remove(self, id: str, *, revision: Optional[int] = None):
        secret = self._get_secret(id)
        self._check_can_manage_secret(secret)

        # Removing all revisions means that the secret is removed, so is no
        # longer in the state.
        if revision is None:
            secrets = set(self._state.secrets)
            secrets.remove(secret)
            self._state._update_secrets(frozenset(secrets))
            return

        # Juju does not prevent removing the tracked or latest revision, but it
        # is always a mistake to do this. Rather than having the state model a
        # secret where the tracked/latest revision cannot be retrieved but the
        # secret still exists, we raise instead, so that charms know that there
        # is a problem with their code.
        if revision in (secret._tracked_revision, secret._latest_revision):
            raise ValueError(
                "Charms should not remove the latest revision of a secret. "
                "Add a new revision with `set_content()` instead, and the previous "
                "revision will be cleaned up by the secret owner when no longer in use.",
            )

        # For all other revisions, the content is not visible to the charm
        # (this is as designed: the secret is being removed, so it should no
        # longer be in use). That means that the state does not need to be
        # modified - however, unit tests should be able to verify that the remove call was
        # executed, so we track that in a history list in the context.
        self._context.removed_secret_revisions.append(revision)

    def relation_remote_app_name(
        self,
        relation_id: int,
        _raise_on_error=False,
    ) -> Optional[str]:
        # ops catches relationnotfounderrors and returns None:
        try:
            relation = self._get_relation_by_id(relation_id)
        except RelationNotFoundError:
            if _raise_on_error:
                raise
            return None

        if isinstance(relation, PeerRelation):
            return self.app_name
        else:
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
            storage.index for storage in self._state.storages if storage.name == name
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
            s for s in self._state.storages if s.name == name and s.index == index
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

    # TODO: It seems like this method has no tests.
    def resource_get(self, resource_name: str) -> str:
        # We assume that there are few enough resources that a linear search
        # will perform well enough.
        for resource in self._state.resources:
            if resource.name == resource_name:
                return str(resource.path)
        # ops will not let us get there if the resource name is unknown from metadata.
        # but if the user forgot to add it in State, then we remind you of that.
        raise RuntimeError(
            f"Inconsistent state: "
            f"resource {resource_name} not found in State. please pass it.",
        )

    def credential_get(self) -> CloudSpec_Ops:
        if not self._context.app_trusted:
            raise ModelError(
                "ERROR charm is not trusted, initialise Context with `app_trusted=True`",
            )
        if not self._state.model.cloud_spec:
            raise ModelError(
                "ERROR cloud spec is empty, initialise it with "
                "`State(model=Model(..., cloud_spec=ops.CloudSpec(...)))`",
            )
        return self._state.model.cloud_spec._to_ops()


class _MockPebbleClient(_TestingPebbleClient):
    def __init__(
        self,
        socket_path: str,
        container_root: Path,
        mounts: Dict[str, Mount],
        *,
        state: "State",
        event: "_Event",
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
            path = Path(mount.location).parts
            mounting_dir = container_root.joinpath(*path[1:])
            mounting_dir.parent.mkdir(parents=True, exist_ok=True)
            mounting_dir.symlink_to(mount.source)

        self._root = container_root

        # load any existing notices and check information from the state
        self._notices: Dict[Tuple[str, str], pebble.Notice] = {}
        self._check_infos: Dict[str, pebble.CheckInfo] = {}
        for container in state.containers:
            for notice in container.notices:
                if hasattr(notice.type, "value"):
                    notice_type = cast(pebble.NoticeType, notice.type).value
                else:
                    notice_type = str(notice.type)
                self._notices[notice_type, notice.key] = notice._to_ops()
            for check in container.check_infos:
                self._check_infos[check.name] = check._to_ops()

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

    def exec(self, *args, **kwargs):  # noqa: U100 type: ignore
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
        if not self._container.can_connect:
            msg = (
                f"Cannot connect to Pebble; did you forget to set "
                f"can_connect=True for container {self._container.name}?"
            )
            raise pebble.ConnectionError(msg)
