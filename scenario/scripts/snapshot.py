import json
import logging
import os
import re
from pathlib import Path
from subprocess import run
from textwrap import dedent
from typing import Any, Dict, List, Union, Optional, BinaryIO, TextIO, Iterable
import ops.pebble

import typer
import yaml

from scenario.state import Address, BindAddress, Model, Network, Relation, State, Status, Container

logger = logging.getLogger("snapshot")

JUJU_RELATION_KEYS = frozenset({"egress-subnets", "ingress-address", "private-address"})
JUJU_CONFIG_KEYS = frozenset({})


class SnapshotError(RuntimeError):
    pass


class InvalidTarget(SnapshotError):
    pass


class InvalidModel(SnapshotError):
    pass


class Target(str):
    def __init__(self, unit_name: str):
        super().__init__()
        app_name, _, unit_id = unit_name.rpartition('/')
        if not app_name or not unit_id:
            raise InvalidTarget(f'invalid unit name: {unit_name!r}')
        self.unit_name = unit_name
        self.app_name = app_name
        self.unit_id = int(unit_id)
        self.normalized = f"{app_name}-{unit_id}"


def _try_format(string):
    try:
        import black

        try:
            return black.format_str(string, mode=black.Mode())
        except black.parsing.InvalidInput as e:
            logger.error(f"error parsing {string}: {e}")
            return string
    except ModuleNotFoundError:
        logger.warning("install black for formatting")
        return string


def format_state(state):
    return _try_format(repr(state))


def format_test_case(state, charm_type_name=None, event_name=None):
    ct = charm_type_name or "CHARM_TYPE  # TODO: replace with charm type name"
    en = event_name or "EVENT_NAME,  # TODO: replace with event name"
    return _try_format(
        dedent(
            f"""
from scenario.state import *
from charm import {ct}

def test_case():
    state = {state}
    out = state.trigger(
        {en}
        {ct}
        )

"""
        )
    )


def _juju_run(cmd, model=None) -> Dict[str, Any]:
    _model = f" -m {model}" if model else ""
    raw = run(
        f"""juju {cmd}{_model} --format json""".split(), capture_output=True
    ).stdout.decode("utf-8")
    return json.loads(raw)


def _juju_ssh(target: Target, cmd, model=None) -> str:
    _model = f" -m {model}" if model else ""
    raw = run(
        f"""juju ssh {target.unit_name} {_model} {cmd}""".split(), capture_output=True
    ).stdout.decode("utf-8")
    return raw


def _juju_exec(target: Target, model, cmd) -> str:
    # action-fail              juju-reboot         payload-unregister  secret-remove
    # action-get               jujuc               pod-spec-get        secret-revoke
    # action-log               k8s-raw-get         pod-spec-set        secret-set
    # action-set               k8s-raw-set         relation-get        state-delete
    # add-metric               k8s-spec-get        relation-ids        state-get
    # application-version-set  k8s-spec-set        relation-list       state-set
    # close-port               leader-get          relation-set        status-get
    # config-get               leader-set          resource-get        status-set
    # containeragent           network-get         secret-add          storage-add
    # credential-get           open-port           secret-get          storage-get
    # goal-state               opened-ports        secret-grant        storage-list
    # is-leader                payload-register    secret-ids          unit-get
    # juju-log                 payload-status-set  secret-info-get
    _model = f" -m {model}" if model else ""
    _target = f" -u {target}" if target else ""
    return run(
        f"juju exec{_model}{_target} -- {cmd}".split(), capture_output=True
    ).stdout.decode("utf-8")


def get_leader(target: Target, model):
    # could also get it from _juju_run('status')...
    return _juju_exec(target, model, "is-leader") == "True"


def get_network(target: Target, model, relation_name: str, is_default=False) -> Network:
    status = _juju_run(f"status {target}", model=model)
    app = status["applications"][target.app_name]
    bind_address = app.get("address", "")

    raw = _juju_exec(target, model, f"network-get {relation_name}")
    jsn = yaml.safe_load(raw)

    bind_addresses = []
    for raw_bind in jsn["bind-addresses"]:

        addresses = []
        for raw_adds in raw_bind["addresses"]:
            addresses.append(
                Address(
                    hostname=raw_adds["hostname"],
                    value=raw_adds["value"],
                    cidr=raw_adds["cidr"],
                    address=raw_adds.get("address", ""),
                )
            )

        bind_addresses.append(
            BindAddress(
                interface_name=raw_bind.get("interface-name", ""), addresses=addresses
            )
        )
    return Network(
        relation_name,
        bind_addresses=bind_addresses,
        bind_address=bind_address,
        egress_subnets=jsn["egress-subnets"],
        ingress_addresses=jsn["ingress-addresses"],
        is_default=is_default,
    )


def get_networks(target: Target, model, relations: List[str]) -> List[Network]:
    networks = []
    networks.append(get_network(target, model, "juju-info"))
    for relation in relations:
        networks.append(get_network(target, model, relation))
    return networks


def get_metadata(target: Target, model: str):
    raw_meta = _juju_ssh(target, f"cat ./agents/unit-{target.normalized}/charm/metadata.yaml", model=model)
    return yaml.safe_load(raw_meta)


class RemotePebbleClient:
    """Clever little class that wraps calls to a remote pebble client."""

    # TODO: there is a .pebble.state
    #  " j ssh --container traefik traefik/0 cat var/lib/pebble/default/.pebble.state | jq"
    #  figure out what it's for.

    def __init__(self, container: str, target: Target, model: str = None):
        self.container = container
        self.target = target
        self.model = model
        self.socket_path = f"/charm/containers/{container}/pebble.socket"

    def _run(self, cmd) -> str:
        _model = f" -m {self.model}" if self.model else ""
        command = f'juju ssh --container charm {self.target.unit_name}{_model} {cmd}'
        proc = run(command.split(), capture_output=True)
        if proc.returncode == 0:
            return proc.stdout.decode('utf-8')
        raise RuntimeError(f"error wrapping pebble call with {command}: "
                           f"process exited with {proc.returncode}; "
                           f"stdout = {proc.stdout}; "
                           f"stderr = {proc.stderr}")

    def wrap_call(self, meth: str):
        # todo: machine charm compat?
        cd = f"cd ./agents/unit-{self.target.normalized}/charm/venv"
        imports = "from ops.pebble import Client"
        method_call = f"print(Client(socket_path='{self.socket_path}').{meth})"
        cmd = dedent(f"""{cd}; python3 -c "{imports};{method_call}" """)
        out = self._run(cmd)
        return out

    def can_connect(self) -> bool:
        try:
            version = self.get_system_info()
        except Exception:
            return False
        return bool(version)

    def get_system_info(self):
        return self.wrap_call('get_system_info().version')

    def get_plan(self):
        dct_plan = self.wrap_call('get_plan().to_dict()')
        return ops.pebble.Plan(dct_plan)

    def pull(self,
             path: str,
             *,
             encoding: Optional[str] = 'utf-8') -> Union[BinaryIO, TextIO]:
        raise NotImplementedError()

    def list_files(self, path: str, *, pattern: Optional[str] = None,
                   itself: bool = False) -> List[ops.pebble.FileInfo]:
        raise NotImplementedError()

    def get_checks(
            self,
            level: Optional[ops.pebble.CheckLevel] = None,
            names: Optional[Iterable[str]] = None
    ) -> List[ops.pebble.CheckInfo]:
        raise NotImplementedError()


def get_container(target: Target, model, container_name: str, container_meta) -> Container:
    pebble = RemotePebbleClient(container_name, target, model)
    layers = pebble.get_plan()
    return Container(
        name=container_name,
        layers=layers,
        can_connect=pebble.can_connect()
    )


def get_containers(target: Target, model, metadata) -> List[Container]:
    containers = []
    for container_name, container_meta in metadata.get('containers', {}).items():
        container = get_container(target, model, container_name, container_meta)
        containers.append(container)
    return containers


def get_status(target: Target, model) -> Status:
    status = _juju_run(f"status {target}", model=model)
    app = status["applications"][target.app_name]

    app_status_raw = app["application-status"]
    app_status = app_status_raw["current"], app_status_raw.get("message", "")

    unit_status_raw = app["units"][target]["workload-status"]
    unit_status = unit_status_raw["current"], unit_status_raw.get("message", "")

    app_version = app.get("version", "")
    return Status(app=app_status, unit=unit_status, app_version=app_version)


def _cast(value: str, _type):
    if _type == "string":
        return value
    elif _type == "integer":
        return int(value)
    elif _type == "number":
        return float(value)
    elif _type == "bool":
        return value == "true"
    elif _type == "attrs":  # TODO: WOT?
        return value
    else:
        raise ValueError(_type)


def get_config(target: Target, model: str) -> Dict[str, Union[str, int, float, bool]]:
    _model = f" -m {model}" if model else ""
    jsn = _juju_run(f"config {target.app_name}", model=model)

    cfg = {}
    for name, option in jsn.get("settings", ()).items():
        if not option.get("value"):
            logger.debug(f"skipped {name}: no value.")
            continue
        cfg[name] = _cast(option["value"], option["type"])

    return cfg


def _get_interface_from_metadata(endpoint, metadata):
    for role in ['provides', 'requires']:
        for ep, ep_meta in metadata.get(role, {}).items():
            if ep == endpoint:
                return ep_meta['interface']

    logger.error(f'No interface for endpoint {endpoint} found in charm metadata.')
    return None


def get_relations(
        target: Target, model: str, metadata: Dict, include_juju_relation_data=False,
) -> List[Relation]:
    _model = f" -m {model}" if model else ""
    try:
        jsn = _juju_run(f"show-unit {target}", model=model)
    except json.JSONDecodeError as e:
        raise InvalidTarget(target) from e

    def _clean(relation_data: dict):
        if include_juju_relation_data:
            return relation_data
        else:
            for key in JUJU_RELATION_KEYS:
                del relation_data[key]
        return relation_data

    relations = []
    for raw_relation in jsn[target].get("relation-info", ()):
        related_units = raw_relation["related-units"]
        #    related-units:
        #      owner/0:
        #        in-scope: true
        #        data:
        #          egress-subnets: 10.152.183.130/32
        #          ingress-address: 10.152.183.130
        #          private-address: 10.152.183.130

        relation_id = raw_relation["relation-id"]

        local_unit_data_raw = _juju_exec(
            target, model, f"relation-get -r {relation_id} - {target} --format json"
        )
        local_unit_data = json.loads(local_unit_data_raw)
        local_app_data_raw = _juju_exec(
            target,
            model,
            f"relation-get -r {relation_id} - {target} --format json --app",
        )
        local_app_data = json.loads(local_app_data_raw)

        some_remote_unit_id = Target(next(iter(related_units)))
        relations.append(
            Relation(
                endpoint=raw_relation["endpoint"],
                interface=_get_interface_from_metadata(raw_relation["endpoint"], metadata),
                relation_id=relation_id,
                remote_app_data=raw_relation["application-data"],
                remote_app_name=some_remote_unit_id.app_name,
                remote_units_data={
                    Target(tgt).unit_id: _clean(val["data"])
                    for tgt, val in related_units.items()
                },
                local_app_data=local_app_data,
                local_unit_data=_clean(local_unit_data),
            )
        )
    return relations


def get_model(name: str = None) -> Model:
    jsn = _juju_run("models")
    model_name = name or jsn["current-model"]
    try:
        model_info = next(
            filter(lambda m: m["short-name"] == model_name, jsn["models"])
        )
    except StopIteration as e:
        raise InvalidModel(name) from e

    model_uuid = model_info["model-uuid"]
    model_type = model_info["type"]

    return Model(name=model_name, uuid=model_uuid, type=model_type)


def try_guess_charm_type_name():
    try:
        charm_path = Path(os.getcwd()) / "src" / "charm.py"
        if charm_path.exists():
            source = charm_path.read_text()
            charms = re.compile(r"class (\D+)\(CharmBase\):").findall(source)
            if len(charms) < 1:
                raise RuntimeError(f"Not enough charms at {charm_path}.")
            elif len(charms) > 1:
                raise RuntimeError(f"Too many charms at {charm_path}.")
            return charms[0]
    except Exception as e:
        logger.warning(f"unable to guess charm type: {e}")
    return None


def _snapshot(
        target: str,
        model: str = None,
        pprint: bool = True,
        include_juju_relation_data=False,
        full_case=False,
):
    try:
        target = Target(target)
    except InvalidTarget:
        print(f"invalid target: {target!r} is not a valid unit name. Should be formatted like so:"
              f"`foo/1`, or `database/0`, or `myapp-foo-bar/42`.")
        exit(1)

    metadata = get_metadata(target, model)

    try:
        relations = get_relations(
            target, model, metadata=metadata,
            include_juju_relation_data=include_juju_relation_data
        )
    except InvalidTarget:
        _model = f"model {model}" or "the current model"
        print(f"invalid target: {target!r} not found in {_model}")
        exit(1)

    try:
        model_info = get_model(model)
    except InvalidModel:
        # todo: this should surface earlier.
        print(f"invalid model: {model!r} not found.")
        exit(1)

    state = State(
        leader=get_leader(target, model),
        model=model_info,
        status=get_status(target, model),
        config=get_config(target, model),
        relations=relations,
        app_name=target.app_name,
        unit_id=target.unit_id,
        containers=get_containers(target, model, metadata),
        networks=get_networks(target, model, [r.endpoint for r in relations]),
    )

    if pprint:
        if full_case:
            charm_type_name = try_guess_charm_type_name()
            txt = format_test_case(state, charm_type_name=charm_type_name)
        else:
            txt = format_state(state)
        print(txt)

    return state


def snapshot(
        target: str = typer.Argument(..., help="Target unit."),
        model: str = typer.Option(None, "-m", "--model", help="Which model to look at."),
        full: bool = typer.Option(
            False,
            "-f",
            "--full",
            help="Whether to print a full, nearly-executable Scenario test, or just the State.",
        ),
        include_juju_relation_data: bool = typer.Option(
            False,
            "--include",
            help="Whether to include in the relation data the default juju keys (egress-subnets,"
                 "ingress-address, private-address).",
            is_flag=True,
        ),
) -> State:
    """Print the State of a remote target unit.

    If black is available, the output will be piped through it for formatting.

    Usage: snapshot myapp/0 > ./tests/scenario/case1.py
    """
    return _snapshot(
        target,
        model,
        full_case=full,
        include_juju_relation_data=include_juju_relation_data,
    )


if __name__ == "__main__":
    # print(_snapshot("owner/0"))
    print(get_container(Target('traefik/0'), "", container_name='traefik', container_meta={}))

