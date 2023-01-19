import functools
from dataclasses import dataclass
from typing import Dict, Optional, Tuple, Any, TYPE_CHECKING, Callable, Type

from scenario.logger import logger as scenario_logger

if TYPE_CHECKING:
    from scenario.scenario import Scene

logger = scenario_logger.getChild('mocking')

Simulator = Callable[
    [Callable[[Any], Any],  # simulated function
     str,  # namespace
     str,  # tool name
     "Scene",  # scene
     Tuple[Any, ...],  # call args
     Dict[str, Any]],  # call kwargs
    None]


def wrap_tool(
        fn: Callable,
        namespace: str,
        tool_name: str,
        scene: "Scene",
        call_args: Tuple[Any, ...],
        call_kwargs: Dict[str, Any]
):
    # all builtin tools we wrap are methods:
    # _self = call_args[0]
    args = tuple(call_args[1:])
    input_state = scene.state
    this_unit_name = scene.meta.unit_name
    this_app_name = scene.meta.app_name

    setter = False
    wrap_errors = True

    try:
        # MODEL BACKEND CALLS
        if namespace == "_ModelBackend":
            if tool_name == "relation_get":
                rel_id, obj_name, app = args
                relation = next(
                    filter(lambda r: r.meta.relation_id == rel_id, input_state.relations)
                )
                if app and obj_name == this_app_name:
                    return relation.local_app_data
                elif app:
                    return relation.remote_app_data
                elif obj_name == this_unit_name:
                    return relation.local_unit_data
                else:
                    unit_id = obj_name.split("/")[-1]
                    return relation.remote_units_data[int(unit_id)]

            elif tool_name == "is_leader":
                return input_state.leader

            elif tool_name == "status_get":
                status, message = (
                    input_state.status.app if call_kwargs.get("app") else input_state.status.unit
                )
                return {"status": status, "message": message}

            elif tool_name == "relation_ids":
                return [rel.meta.relation_id for rel in input_state.relations]

            elif tool_name == "relation_list":
                rel_id = args[0]
                relation = next(
                    filter(lambda r: r.meta.relation_id == rel_id, input_state.relations)
                )
                return tuple(
                    f"{relation.meta.remote_app_name}/{unit_id}"
                    for unit_id in relation.meta.remote_unit_ids
                )

            elif tool_name == "config_get":
                state_config = input_state.config
                if state_config:
                    if args:  # one specific key requested
                        return state_config[args[0]]
                    return state_config  # full config

                # todo fetch default config value from config.yaml
                return state_config

            elif tool_name == "action_get":
                raise NotImplementedError("action_get")
            elif tool_name == "relation_remote_app_name":
                raise NotImplementedError("relation_remote_app_name")
            elif tool_name == "resource_get":
                raise NotImplementedError("resource_get")
            elif tool_name == "storage_list":
                raise NotImplementedError("storage_list")
            elif tool_name == "storage_get":
                raise NotImplementedError("storage_get")
            elif tool_name == "network_get":
                raise NotImplementedError("network_get")
            elif tool_name == "planned_units":
                raise NotImplementedError("planned_units")
            else:
                setter = True

            # # setter methods

            if tool_name == "application_version_set":
                scene.state.status.app_version = args[0]
                return None

            elif tool_name == "status_set":
                if call_kwargs.get("is_app"):
                    scene.state.status.app = args
                else:
                    scene.state.status.unit = args
                return None

            elif tool_name == "juju_log":
                scene.state.juju_log.append(args)
                return None

            elif tool_name == "relation_set":
                rel_id, key, value, app = args
                relation = next(
                    filter(lambda r: r.meta.relation_id == rel_id, scene.state.relations)
                )
                if app:
                    if not scene.state.leader:
                        raise RuntimeError("needs leadership to set app data")
                    tgt = relation.local_app_data
                else:
                    tgt = relation.local_unit_data
                tgt[key] = value
                return None

            elif tool_name == "action_set":
                raise NotImplementedError("action_set")
            elif tool_name == "action_fail":
                raise NotImplementedError("action_fail")
            elif tool_name == "action_log":
                raise NotImplementedError("action_log")
            elif tool_name == "storage_add":
                raise NotImplementedError("storage_add")
            elif tool_name == "secret_get":
                raise NotImplementedError("secret_get")
            elif tool_name == "secret_set":
                raise NotImplementedError("secret_set")
            elif tool_name == "secret_grant":
                raise NotImplementedError("secret_grant")
            elif tool_name == "secret_remove":
                raise NotImplementedError("secret_remove")

        # PEBBLE CALLS
        elif namespace == "Client":
            if tool_name == "_request":
                if args == ("GET", "/v1/system-info"):
                    # fixme: can't differentiate between containers ATM, because Client._request
                    #  does not pass around the container name as argument
                    if input_state.containers[0].can_connect:
                        return {"result": {"version": "unknown"}}
                    else:
                        wrap_errors = False  # this is what pebble.Client expects!
                        raise FileNotFoundError("")
            elif tool_name == "pull":
                raise NotImplementedError("pull")
            elif tool_name == "push":
                setter = True
                raise NotImplementedError("push")

        else:
            raise QuestionNotImplementedError(namespace)
    except Exception as e:
        if not wrap_errors:
            # reraise
            raise e

        action = "setting" if setter else "getting"
        msg = f"Error {action} state for {namespace}.{tool_name} given ({call_args}, {call_kwargs})"
        raise StateError(msg) from e

    raise QuestionNotImplementedError((namespace, tool_name, call_args, call_kwargs))


@dataclass
class DecorateSpec:
    # the memo's namespace will default to the class name it's being defined in
    namespace: Optional[str] = None

    # the memo's name will default to the memoized function's __name__
    name: Optional[str] = None

    # the function to be called instead of the decorated one
    simulator: Simulator = wrap_tool


def _log_call(
        namespace: str,
        tool_name: str,
        args,
        kwargs,
        recorded_output: Any = None,
        # use print, not logger calls, else the root logger will recurse if
        # juju-log calls are being @wrapped as well.
        log_fn: Callable[[str], None] = logger.debug,
):
    try:
        output_repr = repr(recorded_output)
    except:  # noqa catchall
        output_repr = "<repr failed: cannot repr(memoized output).>"

    trim = output_repr[:100]
    trimmed = "[...]" if len(output_repr) > 100 else ""

    return log_fn(
        f"@wrap_tool: intercepted {namespace}.{tool_name}(*{args}, **{kwargs})"
        f"\n\t --> {trim}{trimmed}"
    )


class StateError(RuntimeError):
    pass


class QuestionNotImplementedError(StateError):
    pass


def wrap(
        fn: Callable,
        namespace: str,
        tool_name: str,
        scene: "Scene",
        simulator: Simulator = wrap_tool
):
    @functools.wraps(fn)
    def wrapper(*call_args, **call_kwargs):
        out = simulator(
            fn=fn,
            namespace=namespace,
            tool_name=tool_name,
            scene=scene,
            call_args=call_args,
            call_kwargs=call_kwargs)

        _log_call(namespace, tool_name, call_args, call_kwargs, out)
        return out

    return wrapper


# todo: figure out how to allow users to manually tag individual functions for wrapping
def patch_module(
        module,
        decorate: Dict[str, Dict[str, DecorateSpec]],
        scene: "Scene"):
    """Patch a module by decorating methods in a number of classes.

    Decorate: a dict mapping class names to methods of that class that should be decorated.
    Example::
        >>> patch_module(my_module, {'MyClass': {
        ...     'do_x': DecorateSpec(),
        ...     'is_ready': DecorateSpec(caching_policy='loose'),
        ...     'refresh': DecorateSpec(caching_policy='loose'),
        ...     'bar': DecorateSpec(caching_policy='loose')
        ... }},
        ... some_scene)
    """

    for name, obj in module.__dict__.items():
        specs = decorate.get(name)

        if not specs:
            continue

        patch_class(specs, obj,
                    scene=scene)


def patch_class(specs: Dict[str, DecorateSpec],
                obj: Type,
                scene: "Scene"):
    for meth_name, fn in obj.__dict__.items():
        spec = specs.get(meth_name)

        if not spec:
            continue

        # todo: use mock.patch and lift after exit
        wrapped_fn = wrap(fn,
                          namespace=obj.__name__,
                          tool_name=meth_name,
                          scene=scene,
                          simulator=spec.simulator)

        setattr(obj, meth_name, wrapped_fn)
